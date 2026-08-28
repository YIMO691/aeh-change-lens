from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Sequence

from aeh_change_lens.snapshot import (
    FileBinding,
    SnapshotBinding,
    SnapshotResolver,
    SnapshotStaleError,
)
from aeh_change_lens.snapshot.security import normalize_repo_relative

from .build_provenance import (
    BuildProvenanceExporter,
    BuildProvenanceManifest,
    ProvenanceFileBinding,
    build_manifest_unity_path,
)
from .compile_manifest import (
    CompileManifest,
    CompileManifestExporter,
    locate_manifest_references,
    manifest_unity_path,
)
from .graph_diff import AnalyzerGraphDiffer, MappingHint
from .unity_context import (
    MetadataReferenceBinding,
    UnityCompilationContext,
    UnityContextBuilder,
)
from .worker_input import RoslynWorkerInput, WorkerInputAssembler, WorkerSourceInput


_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class RevisionWorkerAssembly:
    worker_input: RoslynWorkerInput
    context_digest: str
    context_completeness: str
    unity_version: str | None
    generated_project_kind: str
    generated_project_path: str | None
    generated_project_sha256: str | None
    generated_project_origin_sha256: str | None
    manifest_path: str | None
    manifest_sha256: str | None
    source_files: int
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RevisionBaselineAvailability:
    strict_ready: bool
    old_ready: bool
    new_ready: bool
    old_candidates: tuple[str, str]
    new_candidates: tuple[str, str]

    @property
    def missing_lanes(self) -> tuple[str, ...]:
        missing: list[str] = []
        if not self.old_ready:
            missing.append("OLD")
        if not self.new_ready:
            missing.append("NEW")
        return tuple(missing)


class RevisionBaselinePreflight:
    """Check revision-bound compile inputs before expensive snapshot hashing."""

    def __init__(
        self,
        resolver: SnapshotResolver,
        unity_project_path: str,
    ) -> None:
        normalized = normalize_repo_relative(unity_project_path)
        self.resolver = resolver
        self.unity_project_path = "" if normalized == "." else normalized.rstrip("/")

    def inspect(
        self,
        old_revision: str,
        new_revision: str,
        assembly_name: str,
    ) -> RevisionBaselineAvailability:
        project = self._repo_path(f"{assembly_name}.csproj")
        manifest = self._repo_path(manifest_unity_path(assembly_name))
        old_candidates = (project, manifest)
        new_candidates = (project, manifest)
        old_ready = any(
            self.resolver.revision_path_exists(old_revision, path)
            for path in old_candidates
        )
        if new_revision == "WORKTREE":
            new_ready = any(
                self.resolver.worktree_path_exists(path)
                for path in new_candidates
            )
        else:
            new_ready = any(
                self.resolver.revision_path_exists(new_revision, path)
                for path in new_candidates
            )
        return RevisionBaselineAvailability(
            strict_ready=old_ready and new_ready,
            old_ready=old_ready,
            new_ready=new_ready,
            old_candidates=old_candidates,
            new_candidates=new_candidates,
        )

    def _repo_path(self, unity_path: str) -> str:
        if not self.unity_project_path:
            return normalize_repo_relative(unity_path)
        return normalize_repo_relative(
            (PurePosixPath(self.unity_project_path) / unity_path).as_posix()
        )


class RevisionWorkerInputAssembler:
    """Materialize only digest-bound Unity inputs for one Git/worktree snapshot."""

    def __init__(self, resolver: SnapshotResolver, unity_project_path: str) -> None:
        normalized = normalize_repo_relative(unity_project_path)
        self.resolver = resolver
        self.unity_project_path = "" if normalized == "." else normalized.rstrip("/")

    def assemble(
        self,
        binding: SnapshotBinding,
        assembly_name: str,
        request_id: str,
    ) -> RevisionWorkerAssembly:
        if not request_id or "\x00" in request_id:
            raise ValueError("request_id is empty or contains NUL")
        if binding.role not in {"OLD", "NEW"}:
            raise ValueError("snapshot role must be OLD or NEW")
        self._assert_current(binding)
        bound_files = {
            relative: item
            for item in binding.files
            if (relative := self._relative_unity_path(item.path)) is not None
        }
        project_path = f"{assembly_name}.csproj"
        compile_manifest: CompileManifest | None = None
        manifest_path = manifest_unity_path(assembly_name)
        manifest_binding = bound_files.get(manifest_path)
        if project_path not in bound_files and manifest_binding is None:
            raise ValueError(
                "revision-bound generated Unity project or compile manifest is unavailable: "
                f"{self._repo_path(project_path)}"
            )
        if project_path not in bound_files:
            manifest_content = self.resolver.read_bound_bytes(binding, manifest_binding.path)
            compile_manifest = CompileManifest.from_bytes(manifest_content)
            if compile_manifest.assembly_name != assembly_name:
                raise ValueError("compile manifest assembly does not match the requested assembly")
            self._assert_manifest_sources(binding, compile_manifest, bound_files)
            self._assert_worktree_manifest_matches_live(binding, compile_manifest)

        with tempfile.TemporaryDirectory(prefix="aeh-change-lens-revision-") as temporary:
            unity_root = Path(temporary) / "Unity"
            for relative, file_binding in sorted(bound_files.items()):
                destination = unity_root / Path(PurePosixPath(relative))
                destination.parent.mkdir(parents=True, exist_ok=True)
                content = self.resolver.read_bound_bytes(binding, file_binding.path)
                destination.write_bytes(content)

            reference_overrides: list[dict] | None = None
            builder_arguments: dict[str, object] = {}
            if compile_manifest is None:
                context = UnityContextBuilder(unity_root).build(assembly_name)
            else:
                live_unity_root = self.resolver.repository_root / Path(
                    PurePosixPath(self.unity_project_path)
                )
                located = locate_manifest_references(
                    live_unity_root, assembly_name, compile_manifest.metadata_references
                )
                reference_overrides = self._materialize_manifest_project(
                    unity_root, compile_manifest, located
                )
                builder_arguments = {
                    "portable_metadata_paths": True,
                }
                context = UnityContextBuilder(unity_root, **builder_arguments).build(
                    assembly_name,
                    generated_project_kind="COMPILE_MANIFEST",
                    generated_project_origin_sha256=compile_manifest.generated_project_sha256,
                    manifest_path=manifest_path,
                    manifest_sha256=manifest_binding.sha256,
                )
            project_bindings, project_references = self._attested_project_outputs(
                binding, bound_files, context
            )
            if project_bindings:
                context_builder = UnityContextBuilder(
                    unity_root,
                    **builder_arguments,
                    project_output_bindings=project_bindings,
                )
                context = (
                    context_builder.build(assembly_name)
                    if compile_manifest is None
                    else context_builder.build(
                        assembly_name,
                        generated_project_kind="COMPILE_MANIFEST",
                        generated_project_origin_sha256=compile_manifest.generated_project_sha256,
                        manifest_path=manifest_path,
                        manifest_sha256=manifest_binding.sha256,
                    )
                )
            self._assert_context_bound(context, bound_files, compile_manifest)
            worker_input = self._assemble_sources(
                binding,
                context,
                bound_files,
                request_id,
                reference_overrides,
                project_references,
            )

        self._assert_current(binding)
        return RevisionWorkerAssembly(
            worker_input=worker_input,
            context_digest=context.context_digest,
            context_completeness=context.completeness,
            unity_version=context.unity_version,
            generated_project_kind=context.generated_project.kind,
            generated_project_path=context.generated_project.path,
            generated_project_sha256=context.generated_project.sha256,
            generated_project_origin_sha256=context.generated_project.origin_sha256,
            manifest_path=context.generated_project.manifest_path,
            manifest_sha256=context.generated_project.manifest_sha256,
            source_files=len(worker_input.source_files),
            limitations=context.limitations,
        )

    def _assemble_sources(
        self,
        binding: SnapshotBinding,
        context: UnityCompilationContext,
        bound_files: dict[str, FileBinding],
        request_id: str,
        reference_overrides: list[dict] | None = None,
        project_references: list[dict] | None = None,
    ) -> RoslynWorkerInput:
        if context.assembly is None:
            raise ValueError("Unity context has no revision-bound assembly definition")
        if context.applicability.status == "EXCLUDED":
            raise ValueError("Unity assembly is excluded in the selected revision")
        sources: list[WorkerSourceInput] = []
        for unity_path in context.source_files:
            normalized = normalize_repo_relative(unity_path)
            file_binding = bound_files.get(normalized)
            if file_binding is None:
                raise SnapshotStaleError(
                    f"revision context source is not bound by the snapshot: {self._repo_path(normalized)!r}"
                )
            content = self.resolver.read_bound_bytes(binding, file_binding.path)
            text, source_encoding = WorkerInputAssembler._decode_source(content, file_binding.path)
            sources.append(WorkerSourceInput(
                path=file_binding.path,
                content=text,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                snapshot_content_hash=file_binding.sha256,
                source_encoding=source_encoding,
            ))
        if not sources:
            raise ValueError("revision Unity context has no snapshot-bound C# source files")
        references = list(reference_overrides) if reference_overrides is not None else [
            asdict(item) for item in context.metadata_references
            if item.kind in {"UNITY", "EXTERNAL"}
        ]
        references.extend(project_references or [])
        return RoslynWorkerInput(
            schema_version="1.0.0",
            request_id=request_id,
            revision=binding.role,
            unity_context={
                "completeness": context.completeness,
                "unity_version": context.unity_version,
                "defines": list(context.defines),
                "references": references,
            },
            source_files=tuple(sources),
        )

    @staticmethod
    def _assert_context_bound(
        context: UnityCompilationContext,
        bound_files: dict[str, FileBinding],
        compile_manifest: CompileManifest | None,
    ) -> None:
        if context.assembly is None:
            raise ValueError("revision has no matching asmdef")
        if compile_manifest is None:
            generated_project = bound_files.get(context.generated_project.path)
            if (
                generated_project is None or
                generated_project.sha256 != context.generated_project.sha256
            ):
                raise SnapshotStaleError("generated Unity project is not bound by the selected snapshot")
        else:
            manifest_path = context.generated_project.manifest_path
            manifest_file = bound_files.get(manifest_path or "")
            if (
                context.generated_project.kind != "COMPILE_MANIFEST" or
                context.generated_project.sha256 != compile_manifest.canonical_project_sha256 or
                context.generated_project.origin_sha256 != compile_manifest.generated_project_sha256 or
                manifest_file is None or
                manifest_file.sha256 != context.generated_project.manifest_sha256
            ):
                raise SnapshotStaleError("compile manifest provenance is not bound by the selected snapshot")
            expected_sources = {item.path for item in compile_manifest.source_files}
            if set(context.source_files) != expected_sources:
                raise SnapshotStaleError("materialized compile manifest source set changed")
            expected_projects = {
                (
                    item.include, item.assembly_name, item.reference_output_assembly,
                    item.output_item_type,
                )
                for item in compile_manifest.project_references
            }
            actual_projects = {
                (
                    item.include, item.assembly_name, item.reference_output_assembly,
                    item.output_item_type,
                )
                for item in context.project_references
            }
            if actual_projects != expected_projects:
                raise SnapshotStaleError("materialized compile manifest project references changed")
            expected_references = {
                (item.name.casefold(), item.sha256, item.kind)
                for item in compile_manifest.metadata_references
            }
            actual_references = {
                (Path(item.path).name.casefold(), item.sha256, item.kind)
                for item in context.metadata_references
            }
            if not actual_references.issubset(expected_references):
                raise SnapshotStaleError("materialized compile manifest metadata references changed")
        assembly_file = bound_files.get(context.assembly.path)
        if assembly_file is None or assembly_file.sha256 != context.assembly.sha256:
            raise SnapshotStaleError("revision asmdef is not bound by the selected snapshot")
        if context.package_manifest is not None:
            package_file = bound_files.get(context.package_manifest.path)
            if package_file is None or package_file.sha256 != context.package_manifest.sha256:
                raise SnapshotStaleError("revision package lock is not bound by the selected snapshot")

    def _assert_manifest_sources(
        self,
        binding_owner: SnapshotBinding,
        manifest: CompileManifest,
        bound_files: dict[str, FileBinding],
    ) -> None:
        for source in manifest.source_files:
            binding = bound_files.get(source.path)
            if binding is None:
                raise SnapshotStaleError(
                    f"compile manifest source digest mismatch: {source.path!r}"
                )
            content = self.resolver.read_bound_bytes(binding_owner, binding.path)
            text, _ = WorkerInputAssembler._decode_source(content, binding.path)
            semantic_text = text.replace("\r\n", "\n").replace("\r", "\n")
            if hashlib.sha256(semantic_text.encode("utf-8")).hexdigest() != source.semantic_sha256:
                raise SnapshotStaleError(
                    f"compile manifest source digest mismatch: {source.path!r}"
                )

    def _assert_worktree_manifest_matches_live(
        self,
        binding: SnapshotBinding,
        manifest: CompileManifest,
    ) -> None:
        if binding.commit_oid is not None:
            return
        live_project = (
            self.resolver.repository_root / Path(PurePosixPath(self.unity_project_path)) /
            f"{manifest.assembly_name}.csproj"
        )
        if not live_project.is_file():
            return
        current = CompileManifestExporter(
            self.resolver.repository_root, self.unity_project_path
        ).build(manifest.assembly_name)
        if current.canonical_digest != manifest.canonical_digest:
            raise SnapshotStaleError(
                "worktree compile manifest does not match the live generated project"
            )

    @staticmethod
    def _materialize_manifest_project(
        unity_root: Path,
        manifest: CompileManifest,
        located: dict[tuple[str, str], Path],
    ) -> list[dict]:
        references: list[dict] = []
        for reference in manifest.metadata_references:
            key = (reference.name.casefold(), reference.sha256)
            source = located.get(key)
            if source is None:
                continue
            content = source.read_bytes()
            if hashlib.sha256(content).hexdigest() != reference.sha256:
                raise SnapshotStaleError(
                    f"compile manifest reference changed during materialization: {reference.name!r}"
                )
            destination = (
                unity_root / ".aeh-change-lens" / "references" /
                reference.sha256 / reference.name
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            references.append({
                "path": os.fspath(source),
                "sha256": reference.sha256,
                "kind": reference.kind,
            })
        (unity_root / f"{manifest.assembly_name}.csproj").write_bytes(
            manifest.project_bytes()
        )
        return references

    def _attested_project_outputs(
        self,
        binding: SnapshotBinding,
        bound_files: dict[str, FileBinding],
        context: UnityCompilationContext,
    ) -> tuple[dict[str, MetadataReferenceBinding], list[dict]]:
        context_bindings: dict[str, MetadataReferenceBinding] = {}
        worker_references: list[dict] = []
        for reference in context.project_references:
            if not reference.reference_output_assembly or reference.status == "OUTSIDE_UNITY_ROOT":
                continue
            assembly_name = reference.assembly_name
            build_path = build_manifest_unity_path(assembly_name)
            build_binding = bound_files.get(build_path)
            if build_binding is None:
                continue
            build_manifest = BuildProvenanceManifest.from_bytes(
                self.resolver.read_bound_bytes(binding, build_binding.path)
            )
            if build_manifest.assembly_name != assembly_name:
                raise SnapshotStaleError("build provenance assembly does not match ProjectReference")
            compile_path = manifest_unity_path(assembly_name)
            compile_binding = bound_files.get(compile_path)
            if compile_binding is None:
                raise SnapshotStaleError(
                    f"attested project output has no revision-bound compile manifest: {assembly_name}"
                )
            compile_manifest = CompileManifest.from_bytes(
                self.resolver.read_bound_bytes(binding, compile_binding.path)
            )
            if (
                compile_manifest.assembly_name != assembly_name or
                compile_manifest.canonical_digest != build_manifest.compile_manifest_digest
            ):
                raise SnapshotStaleError("build provenance compile manifest digest mismatch")
            self._assert_manifest_sources(binding, compile_manifest, bound_files)
            assembly_content = self._assert_provenance_file(
                binding, bound_files, build_manifest.assembly_definition
            )
            try:
                assembly_value = json.loads(assembly_content.decode("utf-8-sig"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise SnapshotStaleError("build provenance asmdef is invalid") from error
            if (
                not isinstance(assembly_value, dict) or
                assembly_value.get("name") != assembly_name or
                not build_manifest.assembly_definition.path.casefold().endswith(".asmdef")
            ):
                raise SnapshotStaleError("build provenance asmdef does not match assembly")
            if build_manifest.unity_version.path != "ProjectSettings/ProjectVersion.txt":
                raise SnapshotStaleError("build provenance Unity version path is not canonical")
            self._assert_provenance_file(binding, bound_files, build_manifest.unity_version)
            if build_manifest.package_lock is not None:
                if build_manifest.package_lock.path != "Packages/packages-lock.json":
                    raise SnapshotStaleError("build provenance package-lock path is not canonical")
                self._assert_provenance_file(
                    binding, bound_files, build_manifest.package_lock
                )
            elif "Packages/packages-lock.json" in bound_files:
                raise SnapshotStaleError("build provenance omits the revision package lock")
            expected_inputs = {
                item.assembly_name
                for item in compile_manifest.project_references
                if item.reference_output_assembly
            }
            actual_inputs = {item.assembly_name for item in build_manifest.project_inputs}
            if expected_inputs != actual_inputs:
                raise SnapshotStaleError("build provenance project input closure mismatch")
            if build_manifest.output.name.casefold() != f"{assembly_name}.dll".casefold():
                raise SnapshotStaleError("build provenance output name disagrees with assembly")

            live_output = self._live_script_output(build_manifest.output.name)
            if live_output is None:
                continue
            actual_digest = hashlib.sha256(live_output.read_bytes()).hexdigest()
            if actual_digest != build_manifest.output.sha256:
                if binding.commit_oid is None:
                    raise SnapshotStaleError(
                        f"worktree build provenance output digest mismatch: {assembly_name}"
                    )
                continue
            if binding.commit_oid is None:
                current = BuildProvenanceExporter(
                    self.resolver.repository_root, self.unity_project_path
                ).build(assembly_name)
                if current.canonical_digest != build_manifest.canonical_digest:
                    raise SnapshotStaleError(
                        f"worktree build provenance is stale: {assembly_name}"
                    )
            logical_path = (
                f".aeh-change-lens/project-outputs/"
                f"{build_manifest.output.sha256}/{build_manifest.output.name}"
            )
            context_bindings[assembly_name] = MetadataReferenceBinding(
                path=logical_path,
                sha256=build_manifest.output.sha256,
                kind="PROJECT_ATTESTED",
            )
            worker_references.append({
                "path": os.fspath(live_output),
                "sha256": build_manifest.output.sha256,
                "kind": "PROJECT_ATTESTED",
            })
        return context_bindings, worker_references

    def _assert_provenance_file(
        self,
        binding: SnapshotBinding,
        bound_files: dict[str, FileBinding],
        provenance: ProvenanceFileBinding,
    ) -> bytes:
        path = normalize_repo_relative(provenance.path)
        file_binding = bound_files.get(path)
        if file_binding is None:
            raise SnapshotStaleError(f"build provenance input mismatch: {path!r}")
        content = self.resolver.read_bound_bytes(binding, file_binding.path)
        try:
            text = content.decode("utf-8-sig")
        except UnicodeError as error:
            raise SnapshotStaleError(
                f"build provenance text input is not UTF-8: {path!r}"
            ) from error
        semantic_text = text.replace("\r\n", "\n").replace("\r", "\n")
        if hashlib.sha256(semantic_text.encode("utf-8")).hexdigest() != provenance.semantic_sha256:
            raise SnapshotStaleError(f"build provenance input mismatch: {path!r}")
        return content

    def _live_script_output(self, output_name: str) -> Path | None:
        unity_root = self.resolver.repository_root / Path(
            PurePosixPath(self.unity_project_path)
        )
        output = unity_root / "Library" / "ScriptAssemblies" / output_name
        if not output.is_file():
            return None
        info = output.lstat()
        if output.is_symlink() or bool(
            getattr(info, "st_file_attributes", 0) & _REPARSE_POINT
        ):
            raise ValueError("attested ScriptAssemblies output must not be a link/reparse point")
        return output.resolve(strict=True)

    def _relative_unity_path(self, repo_path: str) -> str | None:
        if not self.unity_project_path:
            return repo_path
        prefix = f"{self.unity_project_path}/"
        return repo_path[len(prefix):] if repo_path.startswith(prefix) else None

    def _repo_path(self, unity_path: str) -> str:
        if not self.unity_project_path:
            return unity_path
        return normalize_repo_relative(
            (PurePosixPath(self.unity_project_path) / unity_path).as_posix()
        )

    def _assert_current(self, binding: SnapshotBinding) -> None:
        if binding.commit_oid is None and not self.resolver.is_current(binding):
            raise SnapshotStaleError("worktree snapshot changed during revision analysis")


class RoslynWorkerRunner:
    """Run only the repository-owned static Roslyn worker."""

    def __init__(self, worker_path: str | os.PathLike[str] | None = None) -> None:
        default = (
            Path(__file__).resolve().parents[4]
            / "worker" / "ChangeLens.Analyzer" / "bin" / "Release" / "net8.0"
            / "ChangeLens.Analyzer.dll"
        )
        path = Path(worker_path) if worker_path is not None else default
        if not path.is_file():
            raise FileNotFoundError(f"Roslyn worker is unavailable: {path}")
        info = path.lstat()
        if path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT):
            raise ValueError("Roslyn worker must not be a link/reparse point")
        self.worker_path = path.resolve(strict=True)

    def run(self, worker_input: RoslynWorkerInput) -> dict:
        with tempfile.TemporaryDirectory(prefix="aeh-change-lens-worker-") as temporary:
            request_path = Path(temporary) / "request.json"
            request_path.write_text(
                json.dumps(worker_input.to_dict(), ensure_ascii=False), encoding="utf-8"
            )
            environment = os.environ.copy()
            environment.update({"DOTNET_NOLOGO": "1", "DOTNET_CLI_TELEMETRY_OPTOUT": "1"})
            try:
                completed = subprocess.run(
                    ["dotnet", os.fspath(self.worker_path), "--input", os.fspath(request_path)],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    env=environment,
                    timeout=300,
                )
            except subprocess.TimeoutExpired as error:
                raise ValueError("Roslyn worker timed out") from error
            except OSError as error:
                raise ValueError(f"unable to start Roslyn worker: {error}") from error
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise ValueError(f"Roslyn worker failed: {detail or completed.returncode}")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ValueError("Roslyn worker returned invalid JSON") from error
        if not isinstance(result, dict) or result.get("status") not in {"COMPLETE", "PARTIAL"}:
            raise ValueError("Roslyn worker returned a non-comparable result")
        return result


class RevisionChangeAnalyzer:
    """Analyze OLD and NEW source/context snapshots and produce one evidence-bound diff."""

    def __init__(
        self,
        resolver: SnapshotResolver,
        unity_project_path: str,
        worker_runner: RoslynWorkerRunner | None = None,
    ) -> None:
        self.resolver = resolver
        self.assembler = RevisionWorkerInputAssembler(resolver, unity_project_path)
        self.worker_runner = worker_runner or RoslynWorkerRunner()

    def analyze(
        self,
        old_binding: SnapshotBinding,
        new_binding: SnapshotBinding,
        assembly_name: str,
        request_id: str,
        *,
        renames: Sequence[object] = (),
        mapping_hints: Sequence[MappingHint] = (),
        progress: Callable[[str], None] | None = None,
    ) -> dict:
        if not request_id or "\x00" in request_id:
            raise ValueError("request_id is empty or contains NUL")
        notify = progress or (lambda _: None)
        notify("装配 OLD revision 编译上下文")
        old = self.assembler.assemble(old_binding, assembly_name, f"{request_id}-OLD")
        notify("装配 NEW revision 编译上下文")
        new = self.assembler.assemble(new_binding, assembly_name, f"{request_id}-NEW")
        notify("运行 OLD Roslyn 分析")
        old_result = self.worker_runner.run(old.worker_input)
        notify("运行 NEW Roslyn 分析")
        new_result = self.worker_runner.run(new.worker_input)
        notify("计算 OLD/NEW 图差异")
        diff = AnalyzerGraphDiffer().compare(
            old_result, new_result, renames=renames, mapping_hints=mapping_hints
        ).to_dict()
        self.assembler._assert_current(old_binding)
        self.assembler._assert_current(new_binding)
        limitations = sorted(set(
            [f"OLD: {item}" for item in old.limitations]
            + [f"NEW: {item}" for item in new.limitations]
            + list(diff["limitations"])
        ))
        status = (
            "FRESH" if diff["status"] == "COMPLETE" and
            old.context_completeness == new.context_completeness == "COMPLETE" and
            not limitations else "PARTIAL"
        )
        semantic = {
            "schema_version": "1.0.0",
            "request_id": request_id,
            "status": status,
            "revisions": {
                "old": self._revision_projection(old_binding),
                "new": self._revision_projection(new_binding),
            },
            "renames": [asdict(item) if not isinstance(item, dict) else dict(item) for item in renames],
            "contexts": {
                "old": self._context_projection(old),
                "new": self._context_projection(new),
            },
            "diff": diff,
            "policy": {
                "network_access": "DENY",
                "execute_project_code": False,
                "checkout": False,
            },
            "limitations": limitations,
        }
        return {**semantic, "canonical_digest": _canonical_digest(semantic)}

    def analyze_syntax_partial(
        self,
        old_binding: SnapshotBinding,
        new_binding: SnapshotBinding,
        request_id: str,
        *,
        renames: Sequence[object] = (),
        mapping_hints: Sequence[MappingHint] = (),
        missing_baseline_lanes: Sequence[str] = (),
        progress: Callable[[str], None] | None = None,
    ) -> dict:
        """Analyze only changed C# files with no compile-context claims.

        This path is deliberately explicit and always PARTIAL. It never supplies
        current compile options, metadata, or Unity defines to the OLD lane.
        """
        if not request_id or "\x00" in request_id:
            raise ValueError("request_id is empty or contains NUL")
        notify = progress or (lambda _: None)
        notify("装配 OLD 变更 C# 子图")
        old = self._syntax_only_assembly(old_binding, f"{request_id}-OLD")
        notify("装配 NEW 变更 C# 子图")
        new = self._syntax_only_assembly(new_binding, f"{request_id}-NEW")
        if old.source_files == new.source_files == 0:
            raise ValueError("syntax-only fallback found no changed C# source files")
        notify("运行 OLD syntax-only Roslyn 分析")
        old_result = (
            self.worker_runner.run(old.worker_input)
            if old.source_files else self._empty_worker_result(f"{request_id}-OLD")
        )
        notify("运行 NEW syntax-only Roslyn 分析")
        new_result = (
            self.worker_runner.run(new.worker_input)
            if new.source_files else self._empty_worker_result(f"{request_id}-NEW")
        )
        old_result = self._structuralize_worker_result(old_result)
        new_result = self._structuralize_worker_result(new_result)
        notify("计算 PARTIAL OLD/NEW 图差异")
        diff = AnalyzerGraphDiffer().compare(
            old_result,
            new_result,
            renames=renames,
            mapping_hints=mapping_hints,
            stable_symbol_confidence="STRUCTURAL",
        ).to_dict()
        self._assert_scoped_current(old_binding)
        self._assert_scoped_current(new_binding)
        missing = ", ".join(sorted(set(missing_baseline_lanes))) or "OLD/NEW"
        limitations = sorted(set(
            [f"OLD: {item}" for item in old.limitations]
            + [f"NEW: {item}" for item in new.limitations]
            + list(diff["limitations"])
            + [
                f"{missing} 缺少 revision-bound 编译基线；报告使用显式 syntax-only PARTIAL 模式。",
                "仅分析仓库内已变更的 C# 文件；未变更依赖、完整程序集边界、Unity define 和 metadata 未纳入。",
                "调用和类型关系最多为结构证据，不得解释为完整 Roslyn 编译语义或运行时路径。",
            ]
        ))
        semantic = {
            "schema_version": "1.0.0",
            "request_id": request_id,
            "status": "PARTIAL",
            "revisions": {
                "old": self._revision_projection(old_binding),
                "new": self._revision_projection(new_binding),
            },
            "renames": [
                asdict(item) if not isinstance(item, dict) else dict(item)
                for item in renames
            ],
            "contexts": {
                "old": self._context_projection(old),
                "new": self._context_projection(new),
            },
            "diff": diff,
            "policy": {
                "network_access": "DENY",
                "execute_project_code": False,
                "checkout": False,
            },
            "limitations": limitations,
        }
        return {**semantic, "canonical_digest": _canonical_digest(semantic)}

    def _syntax_only_assembly(
        self, binding: SnapshotBinding, request_id: str
    ) -> RevisionWorkerAssembly:
        sources: list[WorkerSourceInput] = []
        for file_binding in binding.files:
            if not file_binding.path.lower().endswith(".cs"):
                continue
            content = self.resolver.read_bound_bytes(binding, file_binding.path)
            text, source_encoding = WorkerInputAssembler._decode_source(
                content, file_binding.path
            )
            sources.append(WorkerSourceInput(
                path=file_binding.path,
                content=text,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                snapshot_content_hash=file_binding.sha256,
                source_encoding=source_encoding,
            ))
        worker_input = RoslynWorkerInput(
            schema_version="1.0.0",
            request_id=request_id,
            revision=binding.role,
            unity_context={
                "completeness": "MISSING",
                "unity_version": None,
                "defines": [],
                "references": [],
            },
            source_files=tuple(sources),
        )
        context_semantic = {
            "mode": "SYNTAX_ONLY",
            "revision": binding.role,
            "source_manifest_hash": binding.source_manifest_hash,
            "source_files": len(sources),
        }
        limitation = (
            "未使用生成 csproj 或 compile manifest；仅对已变更 C# 文件执行 Roslyn syntax/局部符号分析。"
        )
        return RevisionWorkerAssembly(
            worker_input=worker_input,
            context_digest=_canonical_digest(context_semantic),
            context_completeness="MISSING",
            unity_version=None,
            generated_project_kind="SYNTAX_ONLY",
            generated_project_path=None,
            generated_project_sha256=None,
            generated_project_origin_sha256=None,
            manifest_path=None,
            manifest_sha256=None,
            source_files=len(sources),
            limitations=(limitation,),
        )

    def _assert_scoped_current(self, binding: SnapshotBinding) -> None:
        for file_binding in binding.files:
            self.resolver.read_bound_bytes(binding, file_binding.path)

    @staticmethod
    def _empty_worker_result(request_id: str) -> dict:
        return {
            "schema_version": "1.0.0",
            "request_id": request_id,
            "status": "PARTIAL",
            "capabilities": {
                "syntax": True,
                "semantic_model": False,
                "unity_context": "MISSING",
            },
            "nodes": [],
            "edges": [],
            "diagnostics": [{
                "code": "CL-CS-SYNTAX-EMPTY",
                "severity": "WARNING",
                "message_zh": "该 revision 在变更范围内没有 C# 源文件。",
                "source_ids": [],
            }],
        }

    @staticmethod
    def _structuralize_worker_result(result: dict) -> dict:
        structural = json.loads(json.dumps(result, ensure_ascii=False))
        for collection in ("nodes", "edges"):
            for item in structural.get(collection, []):
                provenance = item.get("provenance")
                if (
                    isinstance(provenance, dict)
                    and provenance.get("confidence") == "CONFIRMED_STATIC"
                ):
                    provenance["confidence"] = "STRUCTURAL"
                    limitations = provenance.get("limitations")
                    if isinstance(limitations, list):
                        limitations.append("syntax-only confidence ceiling")
        return structural

    @staticmethod
    def _revision_projection(binding: SnapshotBinding) -> dict:
        return {
            "role": binding.role,
            "revision": binding.revision,
            "tree_hash": binding.tree_hash,
            "source_manifest_hash": binding.source_manifest_hash,
            "dirty": binding.dirty,
        }

    @staticmethod
    def _context_projection(assembly: RevisionWorkerAssembly) -> dict:
        return {
            "context_digest": assembly.context_digest,
            "completeness": assembly.context_completeness,
            "unity_version": assembly.unity_version,
            "generated_project": {
                "kind": assembly.generated_project_kind,
                "path": assembly.generated_project_path,
                "sha256": assembly.generated_project_sha256,
                "origin_sha256": assembly.generated_project_origin_sha256,
                "manifest_path": assembly.manifest_path,
                "manifest_sha256": assembly.manifest_sha256,
            },
            "source_files": assembly.source_files,
            "limitations": list(assembly.limitations),
        }
