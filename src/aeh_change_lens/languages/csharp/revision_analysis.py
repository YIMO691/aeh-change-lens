from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence

from aeh_change_lens.snapshot import (
    FileBinding,
    SnapshotBinding,
    SnapshotResolver,
    SnapshotStaleError,
)
from aeh_change_lens.snapshot.security import normalize_repo_relative

from .compile_manifest import (
    CompileManifest,
    CompileManifestExporter,
    locate_manifest_references,
    manifest_unity_path,
)
from .graph_diff import AnalyzerGraphDiffer, MappingHint
from .unity_context import UnityCompilationContext, UnityContextBuilder
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
    generated_project_path: str
    generated_project_sha256: str
    generated_project_origin_sha256: str
    manifest_path: str | None
    manifest_sha256: str | None
    source_files: int
    limitations: tuple[str, ...]


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
                context = UnityContextBuilder(
                    unity_root, portable_metadata_paths=True
                ).build(
                    assembly_name,
                    generated_project_kind="COMPILE_MANIFEST",
                    generated_project_origin_sha256=compile_manifest.generated_project_sha256,
                    manifest_path=manifest_path,
                    manifest_sha256=manifest_binding.sha256,
                )
            self._assert_context_bound(context, bound_files, compile_manifest)
            worker_input = self._assemble_sources(
                binding, context, bound_files, request_id, reference_overrides
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
        references = reference_overrides if reference_overrides is not None else [
            asdict(item) for item in context.metadata_references
            if item.kind in {"UNITY", "EXTERNAL"}
        ]
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
    ) -> dict:
        if not request_id or "\x00" in request_id:
            raise ValueError("request_id is empty or contains NUL")
        old = self.assembler.assemble(old_binding, assembly_name, f"{request_id}-OLD")
        new = self.assembler.assemble(new_binding, assembly_name, f"{request_id}-NEW")
        old_result = self.worker_runner.run(old.worker_input)
        new_result = self.worker_runner.run(new.worker_input)
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
