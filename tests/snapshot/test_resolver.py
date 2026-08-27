from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aeh_change_lens.snapshot import SnapshotResolver  # noqa: E402
from aeh_change_lens.snapshot.errors import (  # noqa: E402
    InvalidRepositoryError,
    SnapshotStaleError,
    UnsafePathError,
)
from aeh_change_lens.snapshot.security import (  # noqa: E402
    normalize_repo_relative,
    secure_worktree_path,
)
from aeh_change_lens.cli import main as cli_main  # noqa: E402


def git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", os.fspath(root), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


class RepositoryFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        git(root, "init", "--initial-branch=main")
        git(root, "config", "user.name", "Change Lens Tests")
        git(root, "config", "user.email", "change-lens@example.invalid")
        self.write("Assets/Game.asmdef", '{"name":"Game"}\n')
        self.write("Assets/A.cs", "class A { public int Value => 1; }\n")
        self.write("ProjectSettings/ProjectVersion.txt", "m_EditorVersion: 2022.3.62f1\n")
        self.write("ignored.txt", "not part of the source manifest\n")
        git(root, "add", ".")
        git(root, "commit", "-m", "base")
        self.base = git(root, "rev-parse", "HEAD")

    def write(self, relative_path: str, content: str) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


def validate_snapshot(instance: dict) -> None:
    schemas = {}
    for path in (ROOT / "schemas").glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        schemas[schema["$id"]] = schema
    registry = Registry().with_resources(
        (identifier, Resource.from_contents(schema)) for identifier, schema in schemas.items()
    )
    errors = list(Draft202012Validator(
        schemas["https://aeh-change-lens.dev/schemas/snapshot.schema.json"],
        registry=registry,
    ).iter_errors(instance))
    if errors:
        raise AssertionError("\n".join(error.message for error in errors))


class SnapshotResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.repository = RepositoryFixture(self.root)
        self.resolver = SnapshotResolver(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_revision_snapshot_is_deterministic_and_read_only(self) -> None:
        head_before = git(self.root, "rev-parse", "HEAD")
        status_before = git(self.root, "status", "--porcelain=v1")

        first = self.resolver.resolve_revision(self.repository.base, "OLD")
        second = self.resolver.resolve_revision(self.repository.base, "OLD")

        self.assertEqual(first, second)
        self.assertEqual(head_before, git(self.root, "rev-parse", "HEAD"))
        self.assertEqual(status_before, git(self.root, "status", "--porcelain=v1"))
        self.assertEqual(3, len(first.files))
        self.assertFalse(first.dirty)
        validate_snapshot(first.to_dict())

    def test_worktree_mutation_makes_binding_stale(self) -> None:
        self.repository.write("Assets/A.cs", "class A { public int Value => 2; }\n")
        binding = self.resolver.resolve_worktree()
        self.assertTrue(binding.dirty)
        self.assertTrue(self.resolver.is_current(binding))

        self.repository.write("Assets/A.cs", "class A { public int Value => 3; }\n")
        self.assertFalse(self.resolver.is_current(binding))
        validate_snapshot(binding.to_dict())

    def test_reads_only_bytes_named_by_revision_binding(self) -> None:
        binding = self.resolver.resolve_revision(self.repository.base, "OLD")
        content = self.resolver.read_bound_bytes(binding, "Assets/A.cs")
        self.assertEqual("class A { public int Value => 1; }\n", content.decode("utf-8"))

    def test_direct_bound_worktree_read_rejects_mutated_bytes(self) -> None:
        binding = self.resolver.resolve_worktree("NEW")
        self.repository.write("Assets/A.cs", "class A { public int Value => 9; }\n")
        with self.assertRaisesRegex(SnapshotStaleError, "bound source bytes changed"):
            self.resolver.read_bound_bytes(binding, "Assets/A.cs")

    def test_unselected_file_does_not_change_source_manifest(self) -> None:
        binding = self.resolver.resolve_worktree()
        self.repository.write("ignored.txt", "changed but not analyzed\n")
        current = self.resolver.resolve_worktree()
        self.assertEqual(binding.source_manifest_hash, current.source_manifest_hash)
        self.assertFalse(binding.dirty)
        self.assertTrue(current.dirty)

    def test_detects_git_rename_without_checkout(self) -> None:
        (self.root / "Assets/A.cs").rename(self.root / "Assets/Renamed.cs")
        renames = self.resolver.detect_renames(self.repository.base)
        self.assertEqual(1, len(renames))
        self.assertEqual("Assets/A.cs", renames[0].old_path)
        self.assertEqual("Assets/Renamed.cs", renames[0].new_path)
        self.assertEqual(100, renames[0].similarity)

    def test_requires_exact_repository_root(self) -> None:
        with self.assertRaises(InvalidRepositoryError):
            SnapshotResolver(self.root / "Assets")

    def test_rejects_absolute_and_traversal_paths(self) -> None:
        for candidate in ("../secret.cs", "/absolute.cs", "C:/absolute.cs", "Assets/../secret.cs"):
            with self.subTest(candidate=candidate), self.assertRaises(UnsafePathError):
                normalize_repo_relative(candidate)

    def test_rejects_symlink_or_reparse_escape(self) -> None:
        outside = self.root.parent / f"{self.root.name}-outside.cs"
        outside.write_text("class Secret {}\n", encoding="utf-8")
        link = self.root / "Assets/Linked.cs"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as error:
            outside.unlink(missing_ok=True)
            self.skipTest(f"symlink creation unavailable: {error}")
        try:
            with self.assertRaises(UnsafePathError):
                secure_worktree_path(self.root, "Assets/Linked.cs")
        finally:
            link.unlink(missing_ok=True)
            outside.unlink(missing_ok=True)

    def test_rejects_git_symlink_blob_without_touching_filesystem(self) -> None:
        completed = subprocess.run(
            ["git", "-C", os.fspath(self.root), "hash-object", "-w", "--stdin"],
            input="../../outside.cs\n",
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        blob_oid = completed.stdout.strip()
        git(self.root, "update-index", "--add", "--cacheinfo", f"120000,{blob_oid},Assets/Linked.cs")
        git(self.root, "commit", "-m", "add source symlink blob")
        with self.assertRaisesRegex(UnsafePathError, "Git symlink source is forbidden"):
            self.resolver.resolve_revision("HEAD", "NEW")

    def test_cli_emits_snapshot_pair(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        output = StringIO()
        with redirect_stdout(output):
            exit_code = cli_main([
                "snapshot", os.fspath(self.root), "--base", self.repository.base,
            ])
        self.assertEqual(0, exit_code)
        payload = json.loads(output.getvalue())
        self.assertEqual("OLD", payload["old"]["role"])
        self.assertEqual("NEW", payload["new"]["role"])


if __name__ == "__main__":
    unittest.main()
