from __future__ import annotations

import os
import re
import stat
from pathlib import Path, PurePosixPath

from .errors import UnsafePathError


_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def normalize_repo_relative(value: str) -> str:
    """Return a canonical Git-style relative path or fail closed."""
    if not value or "\x00" in value:
        raise UnsafePathError("repository-relative path is empty or contains NUL")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or _WINDOWS_DRIVE.match(normalized):
        raise UnsafePathError(f"absolute path is forbidden: {value!r}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise UnsafePathError(f"non-canonical or escaping path is forbidden: {value!r}")
    return path.as_posix()


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def secure_worktree_path(repository_root: Path, relative_path: str) -> Path:
    """Resolve a path without allowing symlink, junction, or repository escape."""
    normalized = normalize_repo_relative(relative_path)
    root = repository_root.resolve(strict=True)
    current = root
    for part in PurePosixPath(normalized).parts:
        current = current / part
        if _is_link_or_reparse(current):
            raise UnsafePathError(f"link or reparse point is forbidden: {normalized!r}")

    resolved = current.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise UnsafePathError(f"path escapes repository: {normalized!r}") from error
    return current


def assert_safe_repository_root(repository_root: Path) -> Path:
    root = repository_root.resolve(strict=True)
    if _is_link_or_reparse(repository_root):
        raise UnsafePathError("repository root cannot be a symlink or reparse point")
    if not root.is_dir():
        raise UnsafePathError("repository root must be a directory")
    return root

