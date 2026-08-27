from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from aeh_change_lens.snapshot import SnapshotResolver
from aeh_change_lens.snapshot.security import normalize_repo_relative, secure_worktree_path

from .unity_context import UnityContextBuilder
from .worker_input import WorkerInputAssembler


MANIFEST_DIRECTORY = ".aeh-change-lens/compile-manifests"
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_ASSEMBLY_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _assembly_name(value: str) -> str:
    if (
        not isinstance(value, str) or
        not _ASSEMBLY_NAME.fullmatch(value) or
        value.rstrip(". ") != value or
        value.split(".", 1)[0].upper() in _WINDOWS_RESERVED
    ):
        raise ValueError("assembly_name must contain only letters, digits, dot, underscore, or hyphen")
    return value


def _reference_name(value: object) -> str:
    if (
        not isinstance(value, str) or not value or
        Path(value).name != value or
        value.rstrip(". ") != value or
        any(character in value for character in '<>:"/\\|?*') or
        value.split(".", 1)[0].upper() in _WINDOWS_RESERVED or
        not value.casefold().endswith(".dll")
    ):
        raise ValueError("invalid compile manifest metadata reference name")
    return value


def manifest_unity_path(assembly_name: str) -> str:
    return f"{MANIFEST_DIRECTORY}/{_assembly_name(assembly_name)}.json"


@dataclass(frozen=True, slots=True)
class CompileSourceBinding:
    path: str
    semantic_sha256: str


@dataclass(frozen=True, slots=True)
class CompileReferenceBinding:
    name: str
    sha256: str
    kind: str


@dataclass(frozen=True, slots=True)
class CompileProjectReferenceBinding:
    include: str
    assembly_name: str
    reference_output_assembly: bool
    output_item_type: str | None


@dataclass(frozen=True, slots=True)
class CompileManifest:
    schema_version: str
    assembly_name: str
    generated_project_sha256: str
    canonical_project_sha256: str
    defines: tuple[str, ...]
    source_files: tuple[CompileSourceBinding, ...]
    metadata_references: tuple[CompileReferenceBinding, ...]
    project_references: tuple[CompileProjectReferenceBinding, ...]
    canonical_digest: str

    @classmethod
    def create(
        cls,
        assembly_name: str,
        generated_project_sha256: str,
        defines: tuple[str, ...],
        source_files: tuple[CompileSourceBinding, ...],
        metadata_references: tuple[CompileReferenceBinding, ...],
        project_references: tuple[CompileProjectReferenceBinding, ...],
    ) -> CompileManifest:
        name = _assembly_name(assembly_name)
        if not _SHA256.fullmatch(generated_project_sha256):
            raise ValueError("generated project SHA-256 is invalid")
        ordered_defines = tuple(sorted(set(defines)))
        ordered_sources = tuple(sorted(set(source_files), key=lambda item: item.path))
        ordered_references = tuple(sorted(
            set(metadata_references), key=lambda item: (item.name.casefold(), item.sha256)
        ))
        ordered_projects = tuple(sorted(
            set(project_references), key=lambda item: (item.assembly_name.casefold(), item.include)
        ))
        provisional = cls(
            schema_version="1.0.0",
            assembly_name=name,
            generated_project_sha256=generated_project_sha256,
            canonical_project_sha256="0" * 64,
            defines=ordered_defines,
            source_files=ordered_sources,
            metadata_references=ordered_references,
            project_references=ordered_projects,
            canonical_digest="0" * 64,
        )
        project_sha256 = _sha256(provisional.project_bytes())
        semantic = provisional._semantic(project_sha256)
        return cls(
            schema_version="1.0.0",
            assembly_name=name,
            generated_project_sha256=generated_project_sha256,
            canonical_project_sha256=project_sha256,
            defines=ordered_defines,
            source_files=ordered_sources,
            metadata_references=ordered_references,
            project_references=ordered_projects,
            canonical_digest=_sha256(_canonical_bytes(semantic)),
        )

    @classmethod
    def from_bytes(cls, content: bytes) -> CompileManifest:
        try:
            raw = json.loads(content.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("invalid compile manifest JSON") from error
        if not isinstance(raw, dict):
            raise ValueError("compile manifest must be a JSON object")
        required = {
            "schema_version", "assembly_name", "generated_project_sha256",
            "canonical_project_sha256", "defines", "source_files",
            "metadata_references", "project_references", "canonical_digest",
        }
        if set(raw) != required or raw.get("schema_version") != "1.0.0":
            raise ValueError("compile manifest fields or schema version are invalid")
        name = _assembly_name(raw.get("assembly_name", ""))
        generated_sha = raw.get("generated_project_sha256")
        project_sha = raw.get("canonical_project_sha256")
        digest = raw.get("canonical_digest")
        if not all(isinstance(item, str) and _SHA256.fullmatch(item) for item in (
            generated_sha, project_sha, digest
        )):
            raise ValueError("compile manifest contains an invalid SHA-256")
        defines = cls._string_tuple(raw.get("defines"), "defines")
        sources = cls._sources(raw.get("source_files"))
        references = cls._references(raw.get("metadata_references"))
        projects = cls._projects(raw.get("project_references"))
        manifest = cls(
            schema_version="1.0.0",
            assembly_name=name,
            generated_project_sha256=generated_sha,
            canonical_project_sha256=project_sha,
            defines=defines,
            source_files=sources,
            metadata_references=references,
            project_references=projects,
            canonical_digest=digest,
        )
        semantic = manifest._semantic(project_sha)
        if digest != _sha256(_canonical_bytes(semantic)):
            raise ValueError("compile manifest canonical digest mismatch")
        if project_sha != _sha256(manifest.project_bytes()):
            raise ValueError("compile manifest canonical project digest mismatch")
        return manifest

    @staticmethod
    def _string_tuple(raw: object, field: str) -> tuple[str, ...]:
        if not isinstance(raw, list) or any(not isinstance(item, str) or not item for item in raw):
            raise ValueError(f"compile manifest {field} must be a non-empty string array")
        values = tuple(raw)
        if values != tuple(sorted(set(values))):
            raise ValueError(f"compile manifest {field} must be sorted and unique")
        return values

    @staticmethod
    def _sources(raw: object) -> tuple[CompileSourceBinding, ...]:
        if not isinstance(raw, list) or not raw:
            raise ValueError("compile manifest source_files must be a non-empty array")
        values: list[CompileSourceBinding] = []
        for item in raw:
            if not isinstance(item, dict) or set(item) != {"path", "semantic_sha256"}:
                raise ValueError("invalid compile manifest source entry")
            path = normalize_repo_relative(item.get("path", ""))
            digest = item.get("semantic_sha256")
            if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
                raise ValueError("invalid compile manifest source SHA-256")
            values.append(CompileSourceBinding(path, digest))
        result = tuple(values)
        if result != tuple(sorted(set(result), key=lambda item: item.path)):
            raise ValueError("compile manifest sources must be sorted and unique")
        return result

    @staticmethod
    def _references(raw: object) -> tuple[CompileReferenceBinding, ...]:
        if not isinstance(raw, list):
            raise ValueError("compile manifest metadata_references must be an array")
        values: list[CompileReferenceBinding] = []
        for item in raw:
            if not isinstance(item, dict) or set(item) != {"name", "sha256", "kind"}:
                raise ValueError("invalid compile manifest metadata reference")
            name = _reference_name(item.get("name"))
            digest = item.get("sha256")
            kind = item.get("kind")
            if (
                not isinstance(digest, str) or not _SHA256.fullmatch(digest) or
                kind not in {"UNITY", "EXTERNAL"} or
                kind != ("UNITY" if name.casefold().startswith("unityengine") else "EXTERNAL")
            ):
                raise ValueError("invalid compile manifest metadata reference value")
            values.append(CompileReferenceBinding(name, digest, kind))
        result = tuple(values)
        ordered = tuple(sorted(set(result), key=lambda item: (item.name.casefold(), item.sha256)))
        if result != ordered:
            raise ValueError("compile manifest metadata references must be sorted and unique")
        return result

    @staticmethod
    def _projects(raw: object) -> tuple[CompileProjectReferenceBinding, ...]:
        if not isinstance(raw, list):
            raise ValueError("compile manifest project_references must be an array")
        values: list[CompileProjectReferenceBinding] = []
        expected = {
            "include", "assembly_name", "reference_output_assembly", "output_item_type"
        }
        for item in raw:
            if not isinstance(item, dict) or set(item) != expected:
                raise ValueError("invalid compile manifest project reference")
            include = normalize_repo_relative(item.get("include", ""))
            assembly = _assembly_name(item.get("assembly_name", ""))
            reference_output = item.get("reference_output_assembly")
            output_type = item.get("output_item_type")
            if not isinstance(reference_output, bool) or not (
                output_type is None or isinstance(output_type, str)
            ):
                raise ValueError("invalid compile manifest project reference value")
            values.append(CompileProjectReferenceBinding(
                include, assembly, reference_output, output_type
            ))
        result = tuple(values)
        ordered = tuple(sorted(
            set(result), key=lambda item: (item.assembly_name.casefold(), item.include)
        ))
        if result != ordered:
            raise ValueError("compile manifest project references must be sorted and unique")
        return result

    def _semantic(self, project_sha256: str) -> dict:
        return {
            "schema_version": self.schema_version,
            "assembly_name": self.assembly_name,
            "generated_project_sha256": self.generated_project_sha256,
            "canonical_project_sha256": project_sha256,
            "defines": list(self.defines),
            "source_files": [asdict(item) for item in self.source_files],
            "metadata_references": [asdict(item) for item in self.metadata_references],
            "project_references": [asdict(item) for item in self.project_references],
        }

    def to_dict(self) -> dict:
        return {**self._semantic(self.canonical_project_sha256), "canonical_digest": self.canonical_digest}

    def project_bytes(self) -> bytes:
        root = ET.Element("Project")
        properties = ET.SubElement(root, "PropertyGroup")
        ET.SubElement(properties, "DefineConstants").text = ";".join(self.defines)
        items = ET.SubElement(root, "ItemGroup")
        for reference in self.metadata_references:
            element = ET.SubElement(items, "Reference", {"Include": Path(reference.name).stem})
            ET.SubElement(element, "HintPath").text = (
                f".aeh-change-lens/references/{reference.sha256}/{reference.name}"
            )
        for reference in self.project_references:
            attributes = {"Include": reference.include}
            if not reference.reference_output_assembly:
                attributes["ReferenceOutputAssembly"] = "false"
            if reference.output_item_type is not None:
                attributes["OutputItemType"] = reference.output_item_type
            element = ET.SubElement(items, "ProjectReference", attributes)
            ET.SubElement(element, "Name").text = reference.assembly_name
        for source in self.source_files:
            ET.SubElement(items, "Compile", {"Include": source.path})
        ET.indent(root, space="  ")
        return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


class CompileManifestExporter:
    """Export portable, deterministic compile evidence from a generated Unity project."""

    def __init__(self, repository_root: Path, unity_project_path: str) -> None:
        self.repository_root = SnapshotResolver(repository_root).repository_root
        self.unity_project_path = normalize_repo_relative(unity_project_path).rstrip("/")
        repo_unity_path = normalize_repo_relative(
            (PurePosixPath(self.unity_project_path)).as_posix()
        )
        self.unity_root = secure_worktree_path(self.repository_root, repo_unity_path)

    def build(self, assembly_name: str) -> CompileManifest:
        context = UnityContextBuilder(self.unity_root).build(_assembly_name(assembly_name))
        generated_document = ET.parse(self.unity_root / f"{assembly_name}.csproj")
        generated_defines = UnityContextBuilder._defines(generated_document)
        sources: list[CompileSourceBinding] = []
        for path in context.source_files:
            content = (self.unity_root / Path(PurePosixPath(path))).read_bytes()
            text, _ = WorkerInputAssembler._decode_source(content, path)
            semantic_text = text.replace("\r\n", "\n").replace("\r", "\n")
            sources.append(CompileSourceBinding(
                path=path,
                semantic_sha256=_sha256(semantic_text.encode("utf-8")),
            ))
        references = tuple(CompileReferenceBinding(
            name=Path(item.path).name,
            sha256=item.sha256,
            kind=item.kind,
        ) for item in context.metadata_references)
        projects = tuple(CompileProjectReferenceBinding(
            include=item.include,
            assembly_name=item.assembly_name,
            reference_output_assembly=item.reference_output_assembly,
            output_item_type=item.output_item_type,
        ) for item in context.project_references)
        return CompileManifest.create(
            assembly_name=assembly_name,
            generated_project_sha256=context.generated_project.sha256,
            defines=generated_defines,
            source_files=tuple(sources),
            metadata_references=references,
            project_references=projects,
        )

    def write(self, manifest: CompileManifest) -> str:
        unity_relative = manifest_unity_path(manifest.assembly_name)
        repo_relative = normalize_repo_relative(
            (PurePosixPath(self.unity_project_path) / unity_relative).as_posix()
        )
        destination = secure_worktree_path(self.repository_root, repo_relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = secure_worktree_path(self.repository_root, repo_relative)
        payload = json.dumps(
            manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
        ).encode("utf-8") + b"\n"
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        return repo_relative


def locate_manifest_references(
    unity_root: Path,
    assembly_name: str,
    expected: tuple[CompileReferenceBinding, ...],
) -> dict[tuple[str, str], Path]:
    """Use a live csproj only as a hash-qualified local DLL locator."""
    if not expected:
        return {}
    try:
        context = UnityContextBuilder(unity_root).build(assembly_name)
    except (FileNotFoundError, ValueError):
        return {}
    available = {
        (Path(item.path).name.casefold(), item.sha256): Path(item.path)
        for item in context.metadata_references
    }
    return {
        (item.name.casefold(), item.sha256): available[(item.name.casefold(), item.sha256)]
        for item in expected
        if (item.name.casefold(), item.sha256) in available
    }
