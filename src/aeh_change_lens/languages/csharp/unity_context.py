from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path

from aeh_change_lens.snapshot.errors import UnsafePathError


_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass(frozen=True, slots=True)
class MetadataReferenceBinding:
    path: str
    sha256: str
    kind: str


@dataclass(frozen=True, slots=True)
class AssemblyDefinitionBinding:
    name: str
    path: str
    sha256: str
    root_namespace: str
    references: tuple[str, ...]
    include_platforms: tuple[str, ...]
    exclude_platforms: tuple[str, ...]
    define_constraints: tuple[str, ...]
    no_engine_references: bool


@dataclass(frozen=True, slots=True)
class UnityCompilationContext:
    schema_version: str
    completeness: str
    unity_version: str | None
    assembly: AssemblyDefinitionBinding | None
    defines: tuple[str, ...]
    metadata_references: tuple[MetadataReferenceBinding, ...]
    project_references: tuple[str, ...]
    source_files: tuple[str, ...]
    limitations: tuple[str, ...]
    context_digest: str

    def to_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self), ensure_ascii=False))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_link_or_reparse(path: Path) -> bool:
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


class UnityContextBuilder:
    """Read Unity-generated metadata without starting Unity or project code."""

    def __init__(self, unity_project_root: str | os.PathLike[str]) -> None:
        supplied = Path(unity_project_root)
        if not supplied.exists() or _is_link_or_reparse(supplied):
            raise UnsafePathError("Unity project root is missing or is a link/reparse point")
        root = supplied.resolve(strict=True)
        if not (root / "Assets").is_dir() or not (root / "ProjectSettings").is_dir():
            raise ValueError("expected a Unity project root containing Assets and ProjectSettings")
        self.root = root

    def build(self, assembly_name: str) -> UnityCompilationContext:
        if not assembly_name or any(character in assembly_name for character in "/\\\x00"):
            raise ValueError("assembly_name must be a simple assembly name")
        csproj = self.root / f"{assembly_name}.csproj"
        if not csproj.is_file() or _is_link_or_reparse(csproj):
            raise FileNotFoundError(f"generated Unity project is unavailable: {csproj.name}")

        try:
            document = ET.parse(csproj)
        except ET.ParseError as error:
            raise ValueError(f"invalid generated Unity project XML: {csproj.name}") from error
        defines = self._defines(document)
        references, missing_references = self._metadata_references(document)
        project_references = self._project_references(document)
        sources, missing_sources = self._source_files(document)
        assembly = self._assembly_definition(assembly_name)
        unity_version = self._unity_version()

        limitations: list[str] = []
        if assembly is None:
            limitations.append(f"未找到 name={assembly_name} 的 .asmdef。")
        if unity_version is None:
            limitations.append("未读取到 Unity ProjectVersion。")
        if not defines:
            limitations.append("生成 csproj 未提供 DefineConstants。")
        if not any(Path(item.path).name.casefold() == "unityengine.coremodule.dll" for item in references):
            limitations.append("未绑定 UnityEngine.CoreModule.dll。")
        if missing_references:
            limitations.append(f"{len(missing_references)} 个 metadata reference 不存在。")
        if project_references:
            limitations.append(f"{len(project_references)} 个 ProjectReference 尚未加载为 metadata。")
        if missing_sources:
            limitations.append(f"{len(missing_sources)} 个 Compile source 不存在。")

        completeness = "COMPLETE" if not limitations else "PARTIAL"
        semantic = {
            "schema_version": "1.0.0",
            "completeness": completeness,
            "unity_version": unity_version,
            "assembly": asdict(assembly) if assembly else None,
            "defines": list(defines),
            "metadata_references": [asdict(item) for item in references],
            "project_references": list(project_references),
            "source_files": list(sources),
            "limitations": limitations,
        }
        return UnityCompilationContext(
            schema_version="1.0.0",
            completeness=completeness,
            unity_version=unity_version,
            assembly=assembly,
            defines=defines,
            metadata_references=references,
            project_references=project_references,
            source_files=sources,
            limitations=tuple(limitations),
            context_digest=_canonical_digest(semantic),
        )

    def _unity_version(self) -> str | None:
        version_file = self.root / "ProjectSettings" / "ProjectVersion.txt"
        if not version_file.is_file() or _is_link_or_reparse(version_file):
            return None
        for line in version_file.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("m_EditorVersion:"):
                return line.partition(":")[2].strip() or None
        return None

    def _assembly_definition(self, assembly_name: str) -> AssemblyDefinitionBinding | None:
        matches: list[tuple[Path, dict]] = []
        for path in sorted((self.root / "Assets").rglob("*.asmdef")):
            if _is_link_or_reparse(path):
                raise UnsafePathError(f"asmdef is a link/reparse point: {path}")
            try:
                value = json.loads(path.read_text(encoding="utf-8-sig"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise ValueError(f"invalid asmdef JSON: {path}") from error
            if value.get("name") == assembly_name:
                matches.append((path, value))
        if len(matches) > 1:
            raise ValueError(f"duplicate asmdef name: {assembly_name}")
        if not matches:
            return None
        path, value = matches[0]
        relative = path.relative_to(self.root).as_posix()
        return AssemblyDefinitionBinding(
            name=assembly_name,
            path=relative,
            sha256=_sha256_file(path),
            root_namespace=str(value.get("rootNamespace", "")),
            references=tuple(sorted(str(item) for item in value.get("references", []))),
            include_platforms=tuple(sorted(str(item) for item in value.get("includePlatforms", []))),
            exclude_platforms=tuple(sorted(str(item) for item in value.get("excludePlatforms", []))),
            define_constraints=tuple(sorted(str(item) for item in value.get("defineConstraints", []))),
            no_engine_references=bool(value.get("noEngineReferences", False)),
        )

    @staticmethod
    def _defines(document: ET.ElementTree) -> tuple[str, ...]:
        values: set[str] = set()
        for element in document.findall(".//{*}DefineConstants"):
            if element.text:
                values.update(item.strip() for item in element.text.split(";") if item.strip())
        return tuple(sorted(values))

    def _metadata_references(
        self, document: ET.ElementTree
    ) -> tuple[tuple[MetadataReferenceBinding, ...], tuple[str, ...]]:
        references: dict[str, MetadataReferenceBinding] = {}
        missing: list[str] = []
        for element in document.findall(".//{*}Reference"):
            hint = element.find("{*}HintPath")
            if hint is None or not hint.text:
                continue
            path = Path(os.path.expandvars(hint.text.strip()))
            if not path.is_absolute():
                path = self.root / path
            path = path.resolve(strict=False)
            if not path.is_file():
                missing.append(os.fspath(path))
                continue
            if _is_link_or_reparse(path):
                raise UnsafePathError(f"metadata reference is a link/reparse point: {path}")
            normalized = os.fspath(path)
            kind = "UNITY" if path.name.casefold().startswith("unityengine") else "EXTERNAL"
            references[normalized.casefold()] = MetadataReferenceBinding(
                path=normalized,
                sha256=_sha256_file(path),
                kind=kind,
            )
        return tuple(sorted(references.values(), key=lambda item: item.path.casefold())), tuple(sorted(missing))

    def _project_references(self, document: ET.ElementTree) -> tuple[str, ...]:
        values: list[str] = []
        for element in document.findall(".//{*}ProjectReference"):
            include = element.get("Include")
            if include:
                normalized = include.replace("\\", "/")
                if "\x00" in normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
                    raise UnsafePathError(f"invalid ProjectReference path: {include}")
                values.append(normalized)
        return tuple(sorted(set(values), key=str.casefold))

    def _source_files(self, document: ET.ElementTree) -> tuple[tuple[str, ...], tuple[str, ...]]:
        present: list[str] = []
        missing: list[str] = []
        for element in document.findall(".//{*}Compile"):
            include = element.get("Include")
            if not include:
                continue
            for pattern in (item.strip() for item in include.split(";") if item.strip()):
                normalized = pattern.replace("\\", "/")
                if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized) or ".." in Path(normalized).parts:
                    raise UnsafePathError(f"Compile source escapes Unity root: {pattern}")
                matches = sorted(self.root.glob(normalized)) if any(char in normalized for char in "*?[") else [self.root / normalized]
                matched_files = 0
                for candidate in matches:
                    path = candidate.resolve(strict=False)
                    try:
                        relative = path.relative_to(self.root).as_posix()
                    except ValueError as error:
                        raise UnsafePathError(f"Compile source escapes Unity root: {pattern}") from error
                    if not path.is_file():
                        continue
                    if _is_link_or_reparse(path):
                        raise UnsafePathError(f"Compile source is a link/reparse point: {relative}")
                    present.append(relative)
                    matched_files += 1
                if matched_files == 0:
                    missing.append(normalized)
        return tuple(sorted(set(present))), tuple(sorted(set(missing)))
