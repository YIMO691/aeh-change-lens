"""Snapshot boundary failures."""


class SnapshotError(RuntimeError):
    """Base class for fail-closed snapshot errors."""


class InvalidRepositoryError(SnapshotError):
    """The requested path is not the exact root of a readable Git worktree."""


class UnsafePathError(SnapshotError):
    """A path escaped the repository or traversed a link/reparse point."""


class GitReadError(SnapshotError):
    """A read-only Git operation failed."""

