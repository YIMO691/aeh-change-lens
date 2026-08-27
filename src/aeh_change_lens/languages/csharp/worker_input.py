from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from aeh_change_lens.snapshot import SnapshotBinding, SnapshotResolver, SnapshotStaleError
from aeh_change_lens.snapshot.security import normalize_repo_relative

from .unity_context import UnityCompilationContext, UnityContextBuilder


@dataclass(frozen=True, slots=True)
class WorkerSourceInput:
    path: str
    content: str
    content_hash: str
    snapshot_content_hash: str
    source_encoding: str


@dataclass(frozen=True, slots=True)
class RoslynWorkerInput:
    schema_version: str
    request_id: str
    revision: str
    unity_context: dict
    source_files: tuple[WorkerSourceInput, ...]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "revision": self.revision,
            "unity_context": self.unity_context,
            "source_files": [asdict(item) for item in self.source_files],
        }


class WorkerInputAssembler:
    """Assemble Roslyn input only from digest-bound snapshot source bytes."""

    def __init__(
        self,
        resolver: SnapshotResolver,
        unity_project_root: str | os.PathLike[str],
    ) -> None:
        self.resolver = resolver
        unity_root = Path(unity_project_root).resolve(strict=True)
        try:
            relative = unity_root.relative_to(resolver.repository_root)
        except ValueError as error:
            raise ValueError("Unity project root must be inside the bound Git repository") from error
        self.unity_root = unity_root
        self._repo_prefix = relative.as_posix()

    def assemble(
        self,
        binding: SnapshotBinding,
        context: UnityCompilationContext,
        request_id: str,
    ) -> RoslynWorkerInput:
        if not request_id or "\x00" in request_id:
            raise ValueError("request_id is empty or contains NUL")
        if context.assembly is None:
            raise ValueError("Unity context has no bound assembly definition")
        if context.applicability.status == "EXCLUDED":
            raise ValueError("Unity assembly is excluded by the active platform or define constraints")
        self._assert_snapshot_current(binding)
        self._assert_context_current(context)
        self._assert_asmdef_bound(binding, context)

        source_inputs: list[WorkerSourceInput] = []
        for unity_path in context.source_files:
            normalized_unity_path = normalize_repo_relative(unity_path)
            repo_path = self._repo_path(normalized_unity_path)
            content = self.resolver.read_bound_bytes(binding, repo_path)
            text, source_encoding = self._decode_source(content, repo_path)
            file_binding = self._bound_file(binding, repo_path)
            transport_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            source_inputs.append(WorkerSourceInput(
                path=repo_path,
                content=text,
                content_hash=transport_hash,
                snapshot_content_hash=file_binding.sha256,
                source_encoding=source_encoding,
            ))

        if not source_inputs:
            raise ValueError("Unity context has no snapshot-bound C# source files")

        # ScriptAssemblies outputs are deliberately excluded: their bytes are
        # generated outside the source snapshot and therefore cannot raise
        # semantic confidence until a provenance binding is implemented.
        references = [
            asdict(item)
            for item in context.metadata_references
            if item.kind in {"UNITY", "EXTERNAL"}
        ]
        result = RoslynWorkerInput(
            schema_version="1.0.0",
            request_id=request_id,
            revision=binding.role,
            unity_context={
                "completeness": context.completeness,
                "unity_version": context.unity_version,
                "defines": list(context.defines),
                "references": references,
            },
            source_files=tuple(source_inputs),
        )
        self._assert_context_current(context)
        self._assert_snapshot_current(binding)
        return result

    def _repo_path(self, unity_path: str) -> str:
        if not self._repo_prefix or self._repo_prefix == ".":
            return unity_path
        return normalize_repo_relative((PurePosixPath(self._repo_prefix) / unity_path).as_posix())

    @staticmethod
    def _bound_file(binding: SnapshotBinding, repo_path: str):
        matches = [item for item in binding.files if item.path == repo_path]
        if len(matches) != 1:
            raise SnapshotStaleError(f"Unity input is not bound by the snapshot: {repo_path!r}")
        return matches[0]

    def _assert_asmdef_bound(
        self,
        binding: SnapshotBinding,
        context: UnityCompilationContext,
    ) -> None:
        assert context.assembly is not None
        repo_path = self._repo_path(normalize_repo_relative(context.assembly.path))
        file_binding = self._bound_file(binding, repo_path)
        if file_binding.sha256 != context.assembly.sha256:
            raise SnapshotStaleError("Unity assembly definition does not match the source snapshot")
        self.resolver.read_bound_bytes(binding, repo_path)

    def _assert_context_current(self, context: UnityCompilationContext) -> None:
        assert context.assembly is not None
        current = UnityContextBuilder(self.unity_root).build(context.assembly.name)
        if current.context_digest != context.context_digest:
            raise SnapshotStaleError("Unity compilation context changed after it was bound")

    def _assert_snapshot_current(self, binding: SnapshotBinding) -> None:
        if not self.resolver.is_current(binding):
            raise SnapshotStaleError("source snapshot changed after it was bound")

    @staticmethod
    def _decode_source(content: bytes, repo_path: str) -> tuple[str, str]:
        candidates: list[tuple[str, str]] = []
        if content.startswith(b"\xef\xbb\xbf"):
            candidates.append(("utf-8-sig", "UTF-8-BOM"))
        elif content.startswith(b"\xff\xfe"):
            candidates.append(("utf-16", "UTF-16-LE-BOM"))
        elif content.startswith(b"\xfe\xff"):
            candidates.append(("utf-16", "UTF-16-BE-BOM"))
        else:
            candidates.extend((("utf-8", "UTF-8"), ("gb18030", "GB18030")))
        for codec, label in candidates:
            try:
                return content.decode(codec), label
            except UnicodeDecodeError:
                continue
        raise ValueError(f"C# source encoding is unsupported: {repo_path!r}")
