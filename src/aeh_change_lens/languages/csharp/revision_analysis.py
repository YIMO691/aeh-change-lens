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

from aeh_change_lens.snapshot import SnapshotBinding, SnapshotResolver, SnapshotStaleError
from aeh_change_lens.snapshot.security import normalize_repo_relative

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
    generated_project_path: str
    generated_project_sha256: str
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
        if project_path not in bound_files:
            raise ValueError(
                f"revision-bound generated Unity project is unavailable: {self._repo_path(project_path)}"
            )

        with tempfile.TemporaryDirectory(prefix="aeh-change-lens-revision-") as temporary:
            unity_root = Path(temporary) / "Unity"
            for relative, file_binding in sorted(bound_files.items()):
                destination = unity_root / Path(PurePosixPath(relative))
                destination.parent.mkdir(parents=True, exist_ok=True)
                content = self.resolver.read_bound_bytes(binding, file_binding.path)
                destination.write_bytes(content)

            context = UnityContextBuilder(unity_root).build(assembly_name)
            self._assert_context_bound(context, bound_files)
            worker_input = self._assemble_sources(binding, context, bound_files, request_id)

        self._assert_current(binding)
        return RevisionWorkerAssembly(
            worker_input=worker_input,
            context_digest=context.context_digest,
            context_completeness=context.completeness,
            unity_version=context.unity_version,
            generated_project_path=context.generated_project.path,
            generated_project_sha256=context.generated_project.sha256,
            source_files=len(worker_input.source_files),
            limitations=context.limitations,
        )

    def _assemble_sources(
        self,
        binding: SnapshotBinding,
        context: UnityCompilationContext,
        bound_files: dict[str, object],
        request_id: str,
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
        references = [
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
        bound_files: dict[str, object],
    ) -> None:
        if context.assembly is None:
            raise ValueError("revision has no matching asmdef")
        generated_project = bound_files.get(context.generated_project.path)
        if (
            generated_project is None or
            generated_project.sha256 != context.generated_project.sha256
        ):
            raise SnapshotStaleError("generated Unity project is not bound by the selected snapshot")
        assembly_file = bound_files.get(context.assembly.path)
        if assembly_file is None or assembly_file.sha256 != context.assembly.sha256:
            raise SnapshotStaleError("revision asmdef is not bound by the selected snapshot")
        if context.package_manifest is not None:
            package_file = bound_files.get(context.package_manifest.path)
            if package_file is None or package_file.sha256 != context.package_manifest.sha256:
                raise SnapshotStaleError("revision package lock is not bound by the selected snapshot")

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
                "path": assembly.generated_project_path,
                "sha256": assembly.generated_project_sha256,
            },
            "source_files": assembly.source_files,
            "limitations": list(assembly.limitations),
        }
