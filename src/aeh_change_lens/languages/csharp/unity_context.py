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
class GeneratedProjectBinding:
    kind: str
    path: str
    sha256: str
    origin_sha256: str
    manifest_path: str | None
    manifest_sha256: str | None


@dataclass(frozen=True, slots=True)
class VersionDefineBinding:
    resource: str
    expression: str
    define: str


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
    version_defines: tuple[VersionDefineBinding, ...]
    no_engine_references: bool


@dataclass(frozen=True, slots=True)
class DefineConstraintEvaluation:
    expression: str
    terms: tuple[str, ...]
    valid: bool
    satisfied: bool | None


@dataclass(frozen=True, slots=True)
class VersionDefineEvaluation:
    resource: str
    expression: str
    define: str
    resource_version: str | None
    status: str


@dataclass(frozen=True, slots=True)
class AssemblyApplicabilityBinding:
    status: str
    active_platforms: tuple[str, ...]
    platform_status: str
    define_constraints: tuple[DefineConstraintEvaluation, ...]
    version_defines: tuple[VersionDefineEvaluation, ...]


@dataclass(frozen=True, slots=True)
class PackageVersionBinding:
    name: str
    version: str
    source: str


@dataclass(frozen=True, slots=True)
class PackageManifestBinding:
    path: str
    sha256: str
    packages: tuple[PackageVersionBinding, ...]


@dataclass(frozen=True, slots=True)
class ProjectReferenceBinding:
    include: str
    assembly_name: str
    reference_output_assembly: bool
    output_item_type: str | None
    status: str
    script_assembly: MetadataReferenceBinding | None


@dataclass(frozen=True, slots=True)
class UnityCompilationContext:
    schema_version: str
    completeness: str
    unity_version: str | None
    generated_project: GeneratedProjectBinding
    assembly: AssemblyDefinitionBinding | None
    applicability: AssemblyApplicabilityBinding
    package_manifest: PackageManifestBinding | None
    defines: tuple[str, ...]
    metadata_references: tuple[MetadataReferenceBinding, ...]
    project_references: tuple[ProjectReferenceBinding, ...]
    source_files: tuple[str, ...]
    limitations: tuple[str, ...]
    context_digest: str

    def to_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self), ensure_ascii=False))


@dataclass(frozen=True, slots=True)
class AssemblyDependencyBinding:
    source_assembly: str
    target_assembly: str
    include: str
    status: str


@dataclass(frozen=True, slots=True)
class UnityAssemblyGraph:
    schema_version: str
    root_assembly: str
    completeness: str
    assemblies: tuple[UnityCompilationContext, ...]
    dependencies: tuple[AssemblyDependencyBinding, ...]
    limitations: tuple[str, ...]
    graph_digest: str

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


def _version_key(value: str, *, unity: bool) -> tuple | None:
    if unity:
        match = re.fullmatch(
            r"(\d+)(?:\.(\d+))?(?:\.(\d+)([abfcpx])(\d+)?)?(?:-[0-9A-Za-z.-]+|c\d+)?",
            value,
        )
        if match is None:
            return None
        major, minor, patch = (int(item or 0) for item in match.group(1, 2, 3))
        stage = match.group(4)
        stage_rank = {None: -1, "a": 0, "b": 1, "f": 2, "c": 2, "p": 3, "x": 4}[stage]
        increment = int(match.group(5) or 0)
        return major, minor, patch, stage_rank, increment

    candidate = value.split("+", 1)[0]
    core, separator, label = candidate.partition("-")
    parts = core.split(".")
    if len(parts) not in {2, 3} or any(not item.isdigit() for item in parts):
        return None
    numbers = tuple(int(item) for item in parts) + ((0,) if len(parts) == 2 else ())
    if not separator:
        return (*numbers, 1, ())
    if not label:
        return None
    prerelease: list[tuple[int, int | str]] = []
    for part in label.split("."):
        if not part or not re.fullmatch(r"[0-9A-Za-z-]+", part):
            return None
        prerelease.append((0, int(part)) if part.isdigit() else (1, part.casefold()))
    return (*numbers, 0, tuple(prerelease))


def _version_expression_matches(
    version: str,
    expression: str,
    *,
    unity: bool,
) -> bool | None:
    if not expression or any(character.isspace() for character in expression) or "*" in expression:
        return None
    actual = _version_key(version, unity=unity)
    if actual is None:
        return None
    if expression[0] in "[(":
        if expression[-1:] not in ")]":
            return None
        body = expression[1:-1]
        if "," not in body:
            if expression[0] != "[" or expression[-1] != "]" or not body:
                return None
            exact = _version_key(body, unity=unity)
            return None if exact is None else actual == exact
        endpoints = body.split(",")
        if len(endpoints) != 2 or not all(endpoints):
            return None
        lower = _version_key(endpoints[0], unity=unity)
        upper = _version_key(endpoints[1], unity=unity)
        if lower is None or upper is None or lower > upper:
            return None
        lower_ok = actual >= lower if expression[0] == "[" else actual > lower
        upper_ok = actual <= upper if expression[-1] == "]" else actual < upper
        return lower_ok and upper_ok
    minimum = _version_key(expression, unity=unity)
    return None if minimum is None else actual >= minimum


class UnityContextBuilder:
    """Read Unity-generated metadata without starting Unity or project code."""

    def __init__(
        self,
        unity_project_root: str | os.PathLike[str],
        *,
        portable_metadata_paths: bool = False,
        project_output_bindings: dict[str, MetadataReferenceBinding] | None = None,
    ) -> None:
        supplied = Path(unity_project_root)
        if not supplied.exists() or _is_link_or_reparse(supplied):
            raise UnsafePathError("Unity project root is missing or is a link/reparse point")
        root = supplied.resolve(strict=True)
        if not (root / "Assets").is_dir() or not (root / "ProjectSettings").is_dir():
            raise ValueError("expected a Unity project root containing Assets and ProjectSettings")
        self.root = root
        self.portable_metadata_paths = portable_metadata_paths
        self.project_output_bindings = dict(project_output_bindings or {})
        self._hash_cache: dict[tuple[str, int, int], str] = {}

    def build(
        self,
        assembly_name: str,
        *,
        generated_project_kind: str = "GENERATED_CSPROJ",
        generated_project_origin_sha256: str | None = None,
        manifest_path: str | None = None,
        manifest_sha256: str | None = None,
    ) -> UnityCompilationContext:
        if not assembly_name or any(character in assembly_name for character in "/\\\x00"):
            raise ValueError("assembly_name must be a simple assembly name")
        if generated_project_kind not in {"GENERATED_CSPROJ", "COMPILE_MANIFEST"}:
            raise ValueError("unsupported generated project provenance")
        if generated_project_kind == "GENERATED_CSPROJ" and (
            manifest_path is not None or manifest_sha256 is not None
        ):
            raise ValueError("direct generated project cannot claim manifest provenance")
        if generated_project_kind == "COMPILE_MANIFEST" and (
            not manifest_path or not manifest_sha256 or not generated_project_origin_sha256
        ):
            raise ValueError("compile manifest provenance is incomplete")
        csproj = self.root / f"{assembly_name}.csproj"
        if not csproj.is_file() or _is_link_or_reparse(csproj):
            raise FileNotFoundError(f"generated Unity project is unavailable: {csproj.name}")

        try:
            document = ET.parse(csproj)
        except ET.ParseError as error:
            raise ValueError(f"invalid generated Unity project XML: {csproj.name}") from error
        project_sha256 = self._hash_file(csproj)
        generated_project = GeneratedProjectBinding(
            kind=generated_project_kind,
            path=csproj.relative_to(self.root).as_posix(),
            sha256=project_sha256,
            origin_sha256=generated_project_origin_sha256 or project_sha256,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
        )
        assembly = self._assembly_definition(assembly_name)
        unity_version = self._unity_version()
        package_manifest = self._package_manifest()
        base_defines = self._defines(document)
        version_defines = self._evaluate_version_defines(
            assembly, unity_version, package_manifest
        )
        defines = tuple(sorted(
            set(base_defines) | {
                item.define for item in version_defines if item.status == "DEFINED"
            }
        ))
        references, missing_references = self._metadata_references(document)
        project_references = self._project_references(document)
        sources, missing_sources = self._source_files(document)
        applicability = self._assembly_applicability(assembly, defines, version_defines)

        limitations: list[str] = []
        if assembly is None:
            limitations.append(f"未找到 name={assembly_name} 的 .asmdef。")
        if unity_version is None:
            limitations.append("未读取到 Unity ProjectVersion。")
        if not defines:
            limitations.append("生成 csproj 未提供 DefineConstants。")
        if (
            not (assembly and assembly.no_engine_references)
            and not any(Path(item.path).name.casefold() == "unityengine.coremodule.dll" for item in references)
        ):
            limitations.append("未绑定 UnityEngine.CoreModule.dll。")
        if applicability.status == "EXCLUDED":
            limitations.append("Assembly Definition 与当前平台或 define 不兼容。")
        elif applicability.status == "UNKNOWN":
            limitations.append("Assembly Definition 平台或 define 适用性无法确定。")
        uncertain_version_defines = [
            item for item in version_defines if item.status in {"INVALID", "UNKNOWN"}
        ]
        if uncertain_version_defines:
            limitations.append(f"{len(uncertain_version_defines)} 个 Version Define 无法确定。")
        if missing_references:
            limitations.append(f"{len(missing_references)} 个 metadata reference 不存在。")
        unverified_outputs = [item for item in project_references if item.status == "BOUND_UNVERIFIED"]
        attested_outputs = [item for item in project_references if item.status == "BOUND_ATTESTED"]
        missing_outputs = [item for item in project_references if item.status in {"MISSING", "OUTSIDE_UNITY_ROOT"}]
        if unverified_outputs:
            limitations.append(f"{len(unverified_outputs)} 个 ProjectReference 输出存在但未绑定到当前源码快照。")
        if attested_outputs:
            limitations.append(
                f"{len(attested_outputs)} 个 ProjectReference 使用外部构建哈希证明，尚未独立复现。"
            )
        if missing_outputs:
            limitations.append(f"{len(missing_outputs)} 个 ProjectReference 无可用输出或越出 Unity 根目录。")
        if missing_sources:
            limitations.append(f"{len(missing_sources)} 个 Compile source 不存在。")

        completeness = "COMPLETE" if not limitations else "PARTIAL"
        semantic = {
            "schema_version": "1.0.0",
            "completeness": completeness,
            "unity_version": unity_version,
            "generated_project": asdict(generated_project),
            "assembly": asdict(assembly) if assembly else None,
            "applicability": asdict(applicability),
            "package_manifest": asdict(package_manifest) if package_manifest else None,
            "defines": list(defines),
            "metadata_references": [asdict(item) for item in references],
            "project_references": [asdict(item) for item in project_references],
            "source_files": list(sources),
            "limitations": limitations,
        }
        return UnityCompilationContext(
            schema_version="1.0.0",
            completeness=completeness,
            unity_version=unity_version,
            generated_project=generated_project,
            assembly=assembly,
            applicability=applicability,
            package_manifest=package_manifest,
            defines=defines,
            metadata_references=references,
            project_references=project_references,
            source_files=sources,
            limitations=tuple(limitations),
            context_digest=_canonical_digest(semantic),
        )

    def build_graph(self, root_assembly: str) -> UnityAssemblyGraph:
        contexts: dict[str, UnityCompilationContext] = {}
        dependencies: list[AssemblyDependencyBinding] = []
        limitations: list[str] = []
        pending = [root_assembly]
        while pending:
            assembly_name = pending.pop()
            if assembly_name in contexts:
                continue
            try:
                context = self.build(assembly_name)
            except FileNotFoundError:
                limitations.append(f"缺少生成 csproj：{assembly_name}。")
                continue
            contexts[assembly_name] = context
            for reference in context.project_references:
                dependencies.append(AssemblyDependencyBinding(
                    source_assembly=assembly_name,
                    target_assembly=reference.assembly_name,
                    include=reference.include,
                    status=reference.status,
                ))
                if reference.reference_output_assembly and reference.status != "OUTSIDE_UNITY_ROOT":
                    pending.append(reference.assembly_name)

        active_edges = [item for item in dependencies if item.status != "ANALYZER_ONLY"]
        unresolved = [item for item in active_edges if item.target_assembly not in contexts]
        if unresolved:
            limitations.append(f"{len(unresolved)} 条程序集依赖未解析。")
        partial_contexts = [item for item in contexts.values() if item.completeness != "COMPLETE"]
        if partial_contexts:
            limitations.append(f"{len(partial_contexts)} 个程序集上下文为 PARTIAL。")
        completeness = "COMPLETE" if contexts.get(root_assembly) and not limitations else "PARTIAL"
        ordered_contexts = tuple(sorted(contexts.values(), key=lambda item: item.assembly.name if item.assembly else ""))
        ordered_dependencies = tuple(sorted(
            dependencies,
            key=lambda item: (item.source_assembly, item.target_assembly, item.include),
        ))
        semantic = {
            "schema_version": "1.0.0",
            "root_assembly": root_assembly,
            "completeness": completeness,
            "assemblies": [item.to_dict() for item in ordered_contexts],
            "dependencies": [asdict(item) for item in ordered_dependencies],
            "limitations": limitations,
        }
        return UnityAssemblyGraph(
            schema_version="1.0.0",
            root_assembly=root_assembly,
            completeness=completeness,
            assemblies=ordered_contexts,
            dependencies=ordered_dependencies,
            limitations=tuple(limitations),
            graph_digest=_canonical_digest(semantic),
        )

    def _unity_version(self) -> str | None:
        version_file = self.root / "ProjectSettings" / "ProjectVersion.txt"
        if not version_file.is_file() or _is_link_or_reparse(version_file):
            return None
        for line in version_file.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("m_EditorVersion:"):
                return line.partition(":")[2].strip() or None
        return None

    @staticmethod
    def _assembly_applicability(
        assembly: AssemblyDefinitionBinding | None,
        defines: tuple[str, ...],
        version_defines: tuple[VersionDefineEvaluation, ...],
    ) -> AssemblyApplicabilityBinding:
        defined = set(defines)
        active_platforms = UnityContextBuilder._active_platforms(defined)
        if assembly is None:
            return AssemblyApplicabilityBinding(
                "UNKNOWN", active_platforms, "UNKNOWN", (), version_defines
            )

        include = {item.casefold() for item in assembly.include_platforms}
        exclude = {item.casefold() for item in assembly.exclude_platforms}
        active = {item.casefold() for item in active_platforms}
        if include and exclude:
            platform_status = "INVALID"
        elif not include and not exclude:
            platform_status = "APPLICABLE"
        elif not active:
            platform_status = "UNKNOWN"
        elif include:
            platform_status = "APPLICABLE" if include & active else "EXCLUDED"
        else:
            platform_status = "EXCLUDED" if exclude & active else "APPLICABLE"

        evaluations: list[DefineConstraintEvaluation] = []
        for expression in assembly.define_constraints:
            raw_terms = tuple(item.strip() for item in expression.split("||"))
            valid = bool(raw_terms) and all(
                term and re.fullmatch(r"!?[A-Za-z_][A-Za-z0-9_]*", term)
                for term in raw_terms
            )
            satisfied: bool | None
            if not valid:
                satisfied = None
            else:
                satisfied = any(
                    term[1:] not in defined if term.startswith("!") else term in defined
                    for term in raw_terms
                )
            evaluations.append(DefineConstraintEvaluation(expression, raw_terms, valid, satisfied))

        constraint_values = [item.satisfied for item in evaluations]
        constraints_status = (
            "UNKNOWN" if any(item is None for item in constraint_values)
            else "EXCLUDED" if any(item is False for item in constraint_values)
            else "APPLICABLE"
        )
        if "EXCLUDED" in {platform_status, constraints_status}:
            status = "EXCLUDED"
        elif "UNKNOWN" in {platform_status, constraints_status} or platform_status == "INVALID":
            status = "UNKNOWN"
        else:
            status = "APPLICABLE"
        return AssemblyApplicabilityBinding(
            status=status,
            active_platforms=active_platforms,
            platform_status=platform_status,
            define_constraints=tuple(evaluations),
            version_defines=version_defines,
        )

    @staticmethod
    def _active_platforms(defines: set[str]) -> tuple[str, ...]:
        if "UNITY_EDITOR" in defines:
            return ("Editor",)
        mappings = (
            ("UNITY_ANDROID", "Android"),
            ("UNITY_IOS", "iOS"),
            ("UNITY_TVOS", "tvOS"),
            ("UNITY_WEBGL", "WebGL"),
            ("UNITY_WSA", "WSA"),
            ("UNITY_STANDALONE_OSX", "macOSStandalone"),
            ("UNITY_STANDALONE_LINUX", "LinuxStandalone64"),
            ("UNITY_PS4", "PS4"),
            ("UNITY_PS5", "PS5"),
            ("UNITY_XBOXONE", "XboxOne"),
            ("UNITY_GAMECORE", "GameCoreXboxSeries"),
            ("UNITY_SWITCH", "Switch"),
        )
        active = [platform for symbol, platform in mappings if symbol in defines]
        if "UNITY_STANDALONE_WIN" in defines:
            active.append("WindowsStandalone64" if "UNITY_64" in defines else "WindowsStandalone32")
        return tuple(sorted(set(active), key=str.casefold))

    def _package_manifest(self) -> PackageManifestBinding | None:
        path = self.root / "Packages" / "packages-lock.json"
        if not path.is_file():
            return None
        if _is_link_or_reparse(path):
            raise UnsafePathError("Packages/packages-lock.json is a link/reparse point")
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("invalid Packages/packages-lock.json") from error
        dependencies = document.get("dependencies")
        if not isinstance(dependencies, dict):
            raise ValueError("Packages/packages-lock.json has no dependencies object")
        packages: list[PackageVersionBinding] = []
        for name, details in dependencies.items():
            if not isinstance(details, dict) or not isinstance(details.get("version"), str):
                raise ValueError(f"invalid package lock entry: {name}")
            packages.append(PackageVersionBinding(
                name=str(name),
                version=details["version"],
                source=str(details.get("source", "unknown")),
            ))
        return PackageManifestBinding(
            path="Packages/packages-lock.json",
            sha256=self._hash_file(path),
            packages=tuple(sorted(packages, key=lambda item: item.name.casefold())),
        )

    @staticmethod
    def _evaluate_version_defines(
        assembly: AssemblyDefinitionBinding | None,
        unity_version: str | None,
        package_manifest: PackageManifestBinding | None,
    ) -> tuple[VersionDefineEvaluation, ...]:
        if assembly is None:
            return ()
        packages = {
            item.name: item.version for item in package_manifest.packages
        } if package_manifest else {}
        evaluations: list[VersionDefineEvaluation] = []
        for item in assembly.version_defines:
            is_unity = item.resource.casefold() == "unity"
            resource_version = unity_version if is_unity else packages.get(item.resource)
            valid_define = bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item.define))
            if not valid_define or not item.resource or not item.expression:
                status = "INVALID"
            elif resource_version is None:
                status = (
                    "UNKNOWN" if is_unity or package_manifest is None else "NOT_DEFINED"
                )
            elif _version_key(resource_version, unity=is_unity) is None:
                status = "UNKNOWN"
            else:
                outcome = _version_expression_matches(
                    resource_version, item.expression, unity=is_unity
                )
                status = "INVALID" if outcome is None else "DEFINED" if outcome else "NOT_DEFINED"
            evaluations.append(VersionDefineEvaluation(
                resource=item.resource,
                expression=item.expression,
                define=item.define,
                resource_version=resource_version,
                status=status,
            ))
        return tuple(evaluations)

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
        raw_version_defines = value.get("versionDefines", [])
        if not isinstance(raw_version_defines, list) or any(
            not isinstance(item, dict) for item in raw_version_defines
        ):
            raise ValueError(f"invalid versionDefines in asmdef: {path}")
        return AssemblyDefinitionBinding(
            name=assembly_name,
            path=relative,
            sha256=self._hash_file(path),
            root_namespace=str(value.get("rootNamespace", "")),
            references=tuple(sorted(str(item) for item in value.get("references", []))),
            include_platforms=tuple(sorted(str(item) for item in value.get("includePlatforms", []))),
            exclude_platforms=tuple(sorted(str(item) for item in value.get("excludePlatforms", []))),
            define_constraints=tuple(sorted(str(item) for item in value.get("defineConstraints", []))),
            version_defines=tuple(sorted((
                VersionDefineBinding(
                    resource=str(item.get("name", "")),
                    expression=str(item.get("expression", "")),
                    define=str(item.get("define", "")),
                )
                for item in raw_version_defines
            ), key=lambda item: (item.define, item.resource, item.expression))),
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
            if self.portable_metadata_paths:
                try:
                    normalized = path.relative_to(self.root).as_posix()
                except ValueError:
                    pass
            kind = "UNITY" if path.name.casefold().startswith("unityengine") else "EXTERNAL"
            references[normalized.casefold()] = MetadataReferenceBinding(
                path=normalized,
                sha256=self._hash_file(path),
                kind=kind,
            )
        return tuple(sorted(references.values(), key=lambda item: item.path.casefold())), tuple(sorted(missing))

    def _project_references(self, document: ET.ElementTree) -> tuple[ProjectReferenceBinding, ...]:
        values: list[ProjectReferenceBinding] = []
        for element in document.findall(".//{*}ProjectReference"):
            include = element.get("Include")
            if include:
                normalized = include.replace("\\", "/")
                if "\x00" in normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
                    raise UnsafePathError(f"invalid ProjectReference path: {include}")
                name_element = element.find("{*}Name")
                assembly_name = (
                    name_element.text.strip()
                    if name_element is not None and name_element.text
                    else Path(normalized).stem
                )
                reference_output = element.get("ReferenceOutputAssembly", "true").casefold() != "false"
                output_item_type = element.get("OutputItemType")
                target = (self.root / normalized).resolve(strict=False)
                try:
                    target.relative_to(self.root)
                    inside_root = True
                except ValueError:
                    inside_root = False
                script_assembly: MetadataReferenceBinding | None = None
                if not reference_output:
                    status = "ANALYZER_ONLY"
                elif not inside_root:
                    status = "OUTSIDE_UNITY_ROOT"
                elif assembly_name in self.project_output_bindings:
                    script_assembly = self.project_output_bindings[assembly_name]
                    if script_assembly.kind != "PROJECT_ATTESTED":
                        raise ValueError("project output binding must be PROJECT_ATTESTED")
                    status = "BOUND_ATTESTED"
                else:
                    output = self.root / "Library" / "ScriptAssemblies" / f"{assembly_name}.dll"
                    if output.is_file() and not _is_link_or_reparse(output):
                        script_assembly = MetadataReferenceBinding(
                            path=os.fspath(output.resolve(strict=True)),
                            sha256=self._hash_file(output),
                            kind="PROJECT_UNVERIFIED",
                        )
                        status = "BOUND_UNVERIFIED"
                    else:
                        status = "MISSING"
                values.append(ProjectReferenceBinding(
                    include=normalized,
                    assembly_name=assembly_name,
                    reference_output_assembly=reference_output,
                    output_item_type=output_item_type,
                    status=status,
                    script_assembly=script_assembly,
                ))
        return tuple(sorted(values, key=lambda item: (item.assembly_name.casefold(), item.include.casefold())))

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

    def _hash_file(self, path: Path) -> str:
        info = path.stat()
        key = (os.fspath(path.resolve(strict=True)).casefold(), info.st_size, info.st_mtime_ns)
        digest = self._hash_cache.get(key)
        if digest is None:
            digest = _sha256_file(path)
            self._hash_cache[key] = digest
        return digest
