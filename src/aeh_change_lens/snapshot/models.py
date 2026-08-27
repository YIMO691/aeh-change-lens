from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


RevisionRole = Literal["OLD", "NEW"]


@dataclass(frozen=True, slots=True)
class FileBinding:
    path: str
    byte_size: int
    sha256: str
    git_blob_oid: str | None


@dataclass(frozen=True, slots=True)
class RenameBinding:
    old_path: str
    new_path: str
    similarity: int


@dataclass(frozen=True, slots=True)
class SnapshotBinding:
    schema_version: str
    role: RevisionRole
    revision: str
    commit_oid: str | None
    tree_oid: str | None
    tree_hash: str
    source_manifest_hash: str
    dirty: bool
    files: tuple[FileBinding, ...]

    def to_dict(self) -> dict:
        result = asdict(self)
        result["files"] = [asdict(item) for item in self.files]
        return result

