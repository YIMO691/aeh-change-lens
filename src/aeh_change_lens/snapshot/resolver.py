from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Iterable, Sequence

from .errors import GitReadError, InvalidRepositoryError, SnapshotStaleError, UnsafePathError
from .models import FileBinding, RenameBinding, RevisionRole, SnapshotBinding
from .security import assert_safe_repository_root, normalize_repo_relative, secure_worktree_path


DEFAULT_SOURCE_SUFFIXES = (".cs", ".asmdef", ".csproj")
DEFAULT_EXACT_PATHS = (
    "ProjectSettings/ProjectVersion.txt",
    "Packages/manifest.json",
    "Packages/packages-lock.json",
)
DEFAULT_EXACT_SUFFIXES = (
    "/ProjectSettings/ProjectVersion.txt",
    "/Packages/manifest.json",
    "/Packages/packages-lock.json",
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


class SnapshotResolver:
    """Bind source bytes to Git revisions or the current worktree without checkout."""

    def __init__(self, repository_root: str | os.PathLike[str]) -> None:
        requested = assert_safe_repository_root(Path(repository_root))
        discovered = self._run_git_at(requested, "rev-parse", "--show-toplevel").decode("utf-8").strip()
        try:
            git_root = Path(discovered).resolve(strict=True)
        except (OSError, ValueError) as error:
            raise InvalidRepositoryError("Git returned an unreadable repository root") from error
        if git_root != requested:
            raise InvalidRepositoryError(
                f"an explicit repository root is required; requested={requested}, git_root={git_root}"
            )
        self.repository_root = git_root

    @staticmethod
    def _run_git_at(root: Path, *arguments: str) -> bytes:
        environment = os.environ.copy()
        environment.update({"GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C", "LANG": "C"})
        try:
            completed = subprocess.run(
                ["git", "-C", os.fspath(root), *arguments],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                env=environment,
            )
        except OSError as error:
            raise GitReadError(f"unable to start git: {error}") from error
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise GitReadError(f"git {' '.join(arguments[:2])} failed: {detail}")
        return completed.stdout

    def _git(self, *arguments: str) -> bytes:
        return self._run_git_at(self.repository_root, *arguments)

    @staticmethod
    def _selected(path: str) -> bool:
        return (
            path in DEFAULT_EXACT_PATHS
            or path.endswith(DEFAULT_EXACT_SUFFIXES)
            or path.lower().endswith(DEFAULT_SOURCE_SUFFIXES)
        )

    def _commit_oid(self, revision: str) -> str:
        if not revision or "\x00" in revision:
            raise GitReadError("revision is empty or contains NUL")
        result = self._git(
            "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"
        ).decode("ascii").strip()
        if not result or any(character not in "0123456789abcdefABCDEF" for character in result):
            raise GitReadError("resolved commit object ID is not hexadecimal")
        return result.lower()

    def resolve_revision(self, revision: str, role: RevisionRole) -> SnapshotBinding:
        commit_oid = self._commit_oid(revision)
        tree_oid = self._git("rev-parse", f"{commit_oid}^{{tree}}").decode("ascii").strip().lower()
        raw_tree = self._git("cat-file", "tree", tree_oid)
        files: list[FileBinding] = []
        listing = self._git("ls-tree", "-r", "-z", "--full-tree", commit_oid)
        for record in listing.split(b"\x00"):
            if not record:
                continue
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_oid = metadata.decode("ascii").split(" ", 2)
            path = normalize_repo_relative(raw_path.decode("utf-8"))
            if object_type != "blob" or not self._selected(path):
                continue
            if mode == "120000":
                raise UnsafePathError(f"Git symlink source is forbidden: {path!r}")
            content = self._git("cat-file", "blob", object_oid)
            files.append(
                FileBinding(
                    path=path,
                    byte_size=len(content),
                    sha256=_sha256(content),
                    git_blob_oid=object_oid.lower(),
                )
            )
        files.sort(key=lambda item: item.path)
        return self._binding(
            role=role,
            revision=commit_oid,
            commit_oid=commit_oid,
            tree_oid=tree_oid,
            tree_hash=_sha256(raw_tree),
            dirty=False,
            files=files,
        )

    def resolve_worktree(self, role: RevisionRole = "NEW") -> SnapshotBinding:
        tracked = self._git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
        files: list[FileBinding] = []
        for raw_path in tracked.split(b"\x00"):
            if not raw_path:
                continue
            path = normalize_repo_relative(raw_path.decode("utf-8"))
            if not self._selected(path):
                continue
            local_path = secure_worktree_path(self.repository_root, path)
            if not local_path.exists():
                continue
            if not local_path.is_file():
                raise UnsafePathError(f"selected worktree path is not a file: {path!r}")
            content = local_path.read_bytes()
            files.append(
                FileBinding(path=path, byte_size=len(content), sha256=_sha256(content), git_blob_oid=None)
            )
        files.sort(key=lambda item: item.path)
        manifest_hash = self._manifest_hash(files)
        return self._binding(
            role=role,
            revision="WORKTREE",
            commit_oid=None,
            tree_oid=None,
            tree_hash=manifest_hash,
            dirty=self._worktree_is_dirty(),
            files=files,
        )

    def detect_renames(self, old_revision: str, new_revision: str = "WORKTREE") -> tuple[RenameBinding, ...]:
        old_commit = self._commit_oid(old_revision)
        arguments = ["diff", "--name-status", "-z", "--find-renames", old_commit]
        if new_revision != "WORKTREE":
            arguments.append(self._commit_oid(new_revision))
        arguments.append("--")
        output = self._git(*arguments)
        fields = output.split(b"\x00")
        renames: list[RenameBinding] = []
        index = 0
        while index < len(fields) and fields[index]:
            status = fields[index].decode("ascii")
            index += 1
            if status.startswith("R"):
                if index + 1 >= len(fields):
                    raise GitReadError("malformed rename record from git diff")
                old_path = normalize_repo_relative(fields[index].decode("utf-8"))
                new_path = normalize_repo_relative(fields[index + 1].decode("utf-8"))
                index += 2
                if self._selected(old_path) or self._selected(new_path):
                    renames.append(
                        RenameBinding(
                            old_path=old_path,
                            new_path=new_path,
                            similarity=int(status[1:]),
                        )
                    )
            else:
                index += 1
        if new_revision == "WORKTREE":
            # Git intentionally omits untracked files from `git diff`. Supplement
            # its rename detection with unique, exact content matches while
            # keeping the index untouched.
            old_files = {item.path: item for item in self.resolve_revision(old_commit, "OLD").files}
            new_files = {item.path: item for item in self.resolve_worktree("NEW").files}
            removed = [item for path, item in old_files.items() if path not in new_files]
            added = [item for path, item in new_files.items() if path not in old_files]
            added_by_hash: dict[str, list[FileBinding]] = {}
            for item in added:
                added_by_hash.setdefault(item.sha256, []).append(item)
            existing_pairs = {(item.old_path, item.new_path) for item in renames}
            for old_file in removed:
                candidates = added_by_hash.get(old_file.sha256, [])
                if len(candidates) != 1:
                    continue
                pair = (old_file.path, candidates[0].path)
                if pair not in existing_pairs:
                    renames.append(RenameBinding(pair[0], pair[1], 100))

        return tuple(sorted(renames, key=lambda item: (item.old_path, item.new_path)))

    def is_current(self, binding: SnapshotBinding) -> bool:
        if binding.revision == "WORKTREE":
            current = self.resolve_worktree(binding.role)
        else:
            current = self.resolve_revision(binding.revision, binding.role)
        return (
            current.tree_hash == binding.tree_hash
            and current.source_manifest_hash == binding.source_manifest_hash
        )

    def read_bound_bytes(self, binding: SnapshotBinding, path: str) -> bytes:
        """Read one manifest entry and revalidate its size and digest."""
        normalized = normalize_repo_relative(path)
        matches = [item for item in binding.files if item.path == normalized]
        if len(matches) != 1:
            raise SnapshotStaleError(f"path is not uniquely bound by the snapshot: {normalized!r}")
        file_binding = matches[0]
        if binding.revision == "WORKTREE":
            local_path = secure_worktree_path(self.repository_root, normalized)
            if not local_path.is_file():
                raise SnapshotStaleError(f"bound worktree file is unavailable: {normalized!r}")
            content = local_path.read_bytes()
        else:
            if not file_binding.git_blob_oid:
                raise SnapshotStaleError(f"revision file has no bound Git blob: {normalized!r}")
            content = self._git("cat-file", "blob", file_binding.git_blob_oid)
        if len(content) != file_binding.byte_size or _sha256(content) != file_binding.sha256:
            raise SnapshotStaleError(f"bound source bytes changed: {normalized!r}")
        return content

    def _worktree_is_dirty(self) -> bool:
        return bool(self._git("status", "--porcelain=v1", "-z", "--untracked-files=all"))

    @staticmethod
    def _manifest_hash(files: Sequence[FileBinding]) -> str:
        entries = [
            {
                "byte_size": item.byte_size,
                "git_blob_oid": item.git_blob_oid,
                "path": item.path,
                "sha256": item.sha256,
            }
            for item in files
        ]
        return _sha256(_canonical_json(entries))

    @classmethod
    def _binding(
        cls,
        *,
        role: RevisionRole,
        revision: str,
        commit_oid: str | None,
        tree_oid: str | None,
        tree_hash: str,
        dirty: bool,
        files: Iterable[FileBinding],
    ) -> SnapshotBinding:
        if role not in {"OLD", "NEW"}:
            raise ValueError(f"invalid revision role: {role!r}")
        frozen_files = tuple(files)
        return SnapshotBinding(
            schema_version="1.0.0",
            role=role,
            revision=revision,
            commit_oid=commit_oid,
            tree_oid=tree_oid,
            tree_hash=tree_hash,
            source_manifest_hash=cls._manifest_hash(frozen_files),
            dirty=dirty,
            files=frozen_files,
        )
