from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from aeh_change_lens.snapshot import SnapshotResolver
from aeh_change_lens.snapshot.security import normalize_repo_relative, secure_worktree_path

from .compile_manifest import (
    CompileManifest,
    CompileManifestExporter,
    manifest_unity_path,
)
from .unity_context import UnityContextBuilder


BUILD_MANIFEST_DIRECTORY = ".aeh-change-lens/build-manifests"
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


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


def _simple_name(value: object) -> str:
    if (
        not isinstance(value, str) or not value or
        any(character in value for character in '/\\\x00<>:"|?*') or
        value.rstrip(". ") != value
    ):
        raise ValueError("assembly name is not safe for a build manifest")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"invalid build manifest {field} SHA-256")
    return value


def build_manifest_unity_path(assembly_name: str) -> str:
    return f"{BUILD_MANIFEST_DIRECTORY}/{_simple_name(assembly_name)}.json"


@dataclass(frozen=True, slots=True)
class ProvenanceFileBinding:
    path: str
    semantic_sha256: str


@dataclass(frozen=True, slots=True)
class ProjectInputBinding:
    assembly_name: str
    output_name: str
    output_sha256: str


@dataclass(frozen=True, slots=True)
class ProjectOutputBinding:
    name: str
    sha256: str


@dataclass(frozen=True, slots=True)
class BuildProvenanceManifest:
    schema_version: str
    assurance: str
    producer: str
    assembly_name: str
    compile_manifest_digest: str
    assembly_definition: ProvenanceFileBinding
    unity_version: ProvenanceFileBinding
    package_lock: ProvenanceFileBinding | None
    project_inputs: tuple[ProjectInputBinding, ...]
    output: ProjectOutputBinding
    canonical_digest: str

    @classmethod
    def create(
        cls,
        *,
        assembly_name: str,
        compile_manifest_digest: str,
        assembly_definition: ProvenanceFileBinding,
        unity_version: ProvenanceFileBinding,
        package_lock: ProvenanceFileBinding | None,
        project_inputs: tuple[ProjectInputBinding, ...],
        output: ProjectOutputBinding,
    ) -> BuildProvenanceManifest:
        semantic = {
            "schema_version": "1.0.0",
            "assurance": "ATTESTED_HASH_CLOSURE",
            "producer": "EXTERNAL_UNITY_BUILD",
            "assembly_name": _simple_name(assembly_name),
            "compile_manifest_digest": _digest(
                compile_manifest_digest, "compile manifest"
            ),
            "assembly_definition": asdict(assembly_definition),
            "unity_version": asdict(unity_version),
            "package_lock": asdict(package_lock) if package_lock else None,
            "project_inputs": [asdict(item) for item in sorted(
                set(project_inputs), key=lambda item: item.assembly_name.casefold()
            )],
            "output": asdict(output),
        }
        return cls(
            schema_version="1.0.0",
            assurance="ATTESTED_HASH_CLOSURE",
            producer="EXTERNAL_UNITY_BUILD",
            assembly_name=semantic["assembly_name"],
            compile_manifest_digest=semantic["compile_manifest_digest"],
            assembly_definition=assembly_definition,
            unity_version=unity_version,
            package_lock=package_lock,
            project_inputs=tuple(ProjectInputBinding(**item) for item in semantic["project_inputs"]),
            output=output,
            canonical_digest=_sha256(_canonical_bytes(semantic)),
        )

    @classmethod
    def from_bytes(cls, content: bytes) -> BuildProvenanceManifest:
        try:
            raw = json.loads(content.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("invalid build provenance manifest JSON") from error
        required = {
            "schema_version", "assurance", "producer", "assembly_name",
            "compile_manifest_digest", "assembly_definition", "unity_version",
            "package_lock", "project_inputs", "output", "canonical_digest",
        }
        if not isinstance(raw, dict) or set(raw) != required:
            raise ValueError("build provenance manifest fields are invalid")
        if (
            raw.get("schema_version") != "1.0.0" or
            raw.get("assurance") != "ATTESTED_HASH_CLOSURE" or
            raw.get("producer") != "EXTERNAL_UNITY_BUILD"
        ):
            raise ValueError("unsupported build provenance assurance")
        assembly = _simple_name(raw.get("assembly_name"))
        compile_digest = _digest(raw.get("compile_manifest_digest"), "compile manifest")
        assembly_definition = cls._file(raw.get("assembly_definition"), "assembly definition")
        unity_version = cls._file(raw.get("unity_version"), "Unity version")
        package_raw = raw.get("package_lock")
        package_lock = None if package_raw is None else cls._file(package_raw, "package lock")
        project_inputs = cls._inputs(raw.get("project_inputs"))
        output_raw = raw.get("output")
        if not isinstance(output_raw, dict) or set(output_raw) != {"name", "sha256"}:
            raise ValueError("invalid build provenance output")
        output = ProjectOutputBinding(
            cls._dll_name(output_raw.get("name")),
            _digest(output_raw.get("sha256"), "output"),
        )
        manifest = cls(
            schema_version="1.0.0",
            assurance="ATTESTED_HASH_CLOSURE",
            producer="EXTERNAL_UNITY_BUILD",
            assembly_name=assembly,
            compile_manifest_digest=compile_digest,
            assembly_definition=assembly_definition,
            unity_version=unity_version,
            package_lock=package_lock,
            project_inputs=project_inputs,
            output=output,
            canonical_digest=_digest(raw.get("canonical_digest"), "canonical"),
        )
        semantic = manifest._semantic()
        if manifest.canonical_digest != _sha256(_canonical_bytes(semantic)):
            raise ValueError("build provenance canonical digest mismatch")
        return manifest

    @staticmethod
    def _file(raw: object, field: str) -> ProvenanceFileBinding:
        if not isinstance(raw, dict) or set(raw) != {"path", "semantic_sha256"}:
            raise ValueError(f"invalid build provenance {field}")
        return ProvenanceFileBinding(
            normalize_repo_relative(raw.get("path", "")),
            _digest(raw.get("semantic_sha256"), field),
        )

    @staticmethod
    def _dll_name(value: object) -> str:
        if (
            not isinstance(value, str) or Path(value).name != value or
            not value.casefold().endswith(".dll")
        ):
            raise ValueError("build provenance output name must be a DLL file name")
        _simple_name(value)
        return value

    @classmethod
    def _inputs(cls, raw: object) -> tuple[ProjectInputBinding, ...]:
        if not isinstance(raw, list):
            raise ValueError("build provenance project_inputs must be an array")
        values: list[ProjectInputBinding] = []
        for item in raw:
            if not isinstance(item, dict) or set(item) != {
                "assembly_name", "output_name", "output_sha256"
            }:
                raise ValueError("invalid build provenance project input")
            assembly = _simple_name(item.get("assembly_name"))
            output = cls._dll_name(item.get("output_name"))
            if output.casefold() != f"{assembly}.dll".casefold():
                raise ValueError("project input assembly and output name disagree")
            values.append(ProjectInputBinding(
                assembly, output, _digest(item.get("output_sha256"), "project input")
            ))
        result = tuple(values)
        ordered = tuple(sorted(set(result), key=lambda item: item.assembly_name.casefold()))
        if result != ordered or len({item.assembly_name.casefold() for item in result}) != len(result):
            raise ValueError("build provenance project inputs must be sorted and unique")
        return result

    def _semantic(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "assurance": self.assurance,
            "producer": self.producer,
            "assembly_name": self.assembly_name,
            "compile_manifest_digest": self.compile_manifest_digest,
            "assembly_definition": asdict(self.assembly_definition),
            "unity_version": asdict(self.unity_version),
            "package_lock": asdict(self.package_lock) if self.package_lock else None,
            "project_inputs": [asdict(item) for item in self.project_inputs],
            "output": asdict(self.output),
        }

    def to_dict(self) -> dict:
        return {**self._semantic(), "canonical_digest": self.canonical_digest}


class BuildProvenanceExporter:
    """Attest an externally produced Unity assembly without running its build."""

    def __init__(self, repository_root: Path, unity_project_path: str) -> None:
        self.resolver = SnapshotResolver(repository_root)
        self.repository_root = self.resolver.repository_root
        self.unity_project_path = normalize_repo_relative(unity_project_path).rstrip("/")
        self.unity_root = secure_worktree_path(
            self.repository_root, self.unity_project_path
        )

    def build(self, assembly_name: str) -> BuildProvenanceManifest:
        name = _simple_name(assembly_name)
        compile_path = secure_worktree_path(
            self.repository_root,
            normalize_repo_relative((
                PurePosixPath(self.unity_project_path) / manifest_unity_path(name)
            ).as_posix()),
        )
        if not compile_path.is_file():
            raise FileNotFoundError(
                f"export the compile manifest before build provenance: {manifest_unity_path(name)}"
            )
        compile_manifest = CompileManifest.from_bytes(compile_path.read_bytes())
        current_compile = CompileManifestExporter(
            self.repository_root, self.unity_project_path
        ).build(name)
        if compile_manifest.canonical_digest != current_compile.canonical_digest:
            raise ValueError("compile manifest is stale; export it before build provenance")

        context = UnityContextBuilder(self.unity_root).build(name)
        if context.assembly is None:
            raise ValueError("build provenance requires a matching asmdef")
        version_path = self.unity_root / "ProjectSettings/ProjectVersion.txt"
        if not version_path.is_file():
            raise FileNotFoundError("ProjectSettings/ProjectVersion.txt is unavailable")
        project_inputs: list[ProjectInputBinding] = []
        for reference in context.project_references:
            if not reference.reference_output_assembly:
                continue
            if reference.status != "BOUND_UNVERIFIED" or reference.script_assembly is None:
                raise ValueError(
                    f"project input output is unavailable for attestation: {reference.assembly_name}"
                )
            project_inputs.append(ProjectInputBinding(
                assembly_name=reference.assembly_name,
                output_name=f"{reference.assembly_name}.dll",
                output_sha256=reference.script_assembly.sha256,
            ))
        output_path = self._script_output(name)
        observed_inputs = [
            self.unity_root / f"{name}.csproj",
            self.unity_root / context.assembly.path,
            version_path,
            *(self.unity_root / path for path in context.source_files),
            *(Path(item.script_assembly.path) for item in context.project_references
              if item.script_assembly is not None),
        ]
        if context.package_manifest is not None:
            observed_inputs.append(self.unity_root / context.package_manifest.path)
        latest_input = max(path.stat().st_mtime_ns for path in observed_inputs)
        if output_path.stat().st_mtime_ns < latest_input:
            raise ValueError(
                "ScriptAssemblies output predates an observed compile input; rebuild in Unity first"
            )
        output = ProjectOutputBinding(output_path.name, _sha256(output_path.read_bytes()))
        package_lock = None if context.package_manifest is None else ProvenanceFileBinding(
            context.package_manifest.path,
            self._text_semantic_sha(self.unity_root / context.package_manifest.path),
        )
        return BuildProvenanceManifest.create(
            assembly_name=name,
            compile_manifest_digest=compile_manifest.canonical_digest,
            assembly_definition=ProvenanceFileBinding(
                context.assembly.path,
                self._text_semantic_sha(self.unity_root / context.assembly.path),
            ),
            unity_version=ProvenanceFileBinding(
                "ProjectSettings/ProjectVersion.txt", self._text_semantic_sha(version_path)
            ),
            package_lock=package_lock,
            project_inputs=tuple(project_inputs),
            output=output,
        )

    def write(self, manifest: BuildProvenanceManifest) -> str:
        unity_relative = build_manifest_unity_path(manifest.assembly_name)
        repo_relative = normalize_repo_relative((
            PurePosixPath(self.unity_project_path) / unity_relative
        ).as_posix())
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

    @staticmethod
    def _text_semantic_sha(path: Path) -> str:
        try:
            text = path.read_bytes().decode("utf-8-sig")
        except UnicodeError as error:
            raise ValueError(f"build provenance text input is not UTF-8: {path.name}") from error
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        return _sha256(normalized.encode("utf-8"))

    def _script_output(self, assembly_name: str) -> Path:
        path = self.unity_root / "Library" / "ScriptAssemblies" / f"{assembly_name}.dll"
        if not path.is_file():
            raise FileNotFoundError(f"ScriptAssemblies output is unavailable: {path.name}")
        info = path.lstat()
        if path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT):
            raise ValueError("ScriptAssemblies output must not be a link/reparse point")
        return path.resolve(strict=True)
