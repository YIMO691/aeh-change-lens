from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aeh_change_lens.cli import main  # noqa: E402
from aeh_change_lens.languages.csharp import (  # noqa: E402
    RevisionChangeAnalyzer,
    RevisionWorkerInputAssembler,
)
from aeh_change_lens.snapshot import SnapshotResolver  # noqa: E402
from tests.contract.test_contracts import validate  # noqa: E402


def git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", os.fspath(root), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


class RevisionAnalysisRepository:
    def __init__(self, root: Path, *, include_project: bool = True) -> None:
        self.root = root
        unity = root / "Unity"
        (unity / "Assets/Game").mkdir(parents=True)
        (unity / "ProjectSettings").mkdir()
        (unity / "Packages").mkdir()
        (unity / "Assets/Game/Game.asmdef").write_text(
            '{"name":"Game","noEngineReferences":true}\n', encoding="utf-8"
        )
        (unity / "ProjectSettings/ProjectVersion.txt").write_text(
            "m_EditorVersion: 2022.3.62f1\n", encoding="utf-8"
        )
        (unity / "Packages/packages-lock.json").write_text(
            '{"dependencies":{}}\n', encoding="utf-8"
        )
        if include_project:
            (unity / "Game.csproj").write_text("""<Project>
  <PropertyGroup><DefineConstants>UNITY_EDITOR</DefineConstants></PropertyGroup>
  <ItemGroup><Compile Include="Assets/Game/**/*.cs" /></ItemGroup>
</Project>
""", encoding="utf-8")
        self.source = unity / "Assets/Game/Counter.cs"
        self.source.write_text("""namespace RevisionFixture;
public sealed class Counter
{
    private int value;
    public int Add(int amount)
    {
        value += amount;
        return value;
    }
}
""", encoding="utf-8")
        git(root, "init", "-q")
        git(root, "config", "user.name", "Change Lens Test")
        git(root, "config", "user.email", "change-lens@example.invalid")
        git(root, "add", ".")
        git(root, "commit", "-qm", "base")
        self.base = git(root, "rev-parse", "HEAD")

    def modify_target(self) -> None:
        self.source.write_text("""namespace RevisionFixture;
public sealed class Counter
{
    private int value;
    public int Add(int amount)
    {
        if (amount <= 0)
            return value;
        value += amount;
        return value;
    }
}
""", encoding="utf-8")


class RevisionChangeAnalyzerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_head_to_worktree_analysis_is_snapshot_bound_and_read_only(self) -> None:
        repository = RevisionAnalysisRepository(self.root)
        repository.modify_target()
        before = git(self.root, "status", "--porcelain=v1", "--untracked-files=all")
        resolver = SnapshotResolver(self.root)
        old = resolver.resolve_revision(repository.base, "OLD")
        new = resolver.resolve_worktree("NEW")

        result = RevisionChangeAnalyzer(resolver, "Unity").analyze(
            old, new, "Game", "REVISION-GOLDEN"
        )

        after = git(self.root, "status", "--porcelain=v1", "--untracked-files=all")
        self.assertEqual(before, after)
        validate("change-analysis.schema.json", result)
        self.assertEqual("OLD", result["revisions"]["old"]["role"])
        self.assertEqual("NEW", result["revisions"]["new"]["role"])
        self.assertNotEqual(
            result["revisions"]["old"]["source_manifest_hash"],
            result["revisions"]["new"]["source_manifest_hash"],
        )
        self.assertEqual(1, result["contexts"]["old"]["source_files"])
        self.assertEqual(1, result["contexts"]["new"]["source_files"])
        self.assertEqual("Game.csproj", result["contexts"]["old"]["generated_project"]["path"])
        self.assertEqual(64, len(result["contexts"]["old"]["generated_project"]["sha256"]))
        self.assertGreaterEqual(result["diff"]["summary"]["added_edges"], 1)
        self.assertTrue(any(
            node["kind"] == "CONDITION" and node["revision"] == "NEW" and node["change"] == "ADDED"
            for node in result["diff"]["nodes"]
        ))
        self.assertEqual({
            "network_access": "DENY", "execute_project_code": False, "checkout": False
        }, result["policy"])

    def test_cli_analyze_change_emits_same_schema_valid_contract(self) -> None:
        repository = RevisionAnalysisRepository(self.root)
        repository.modify_target()
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main([
                "analyze-change", os.fspath(self.root), "Unity",
                "--assembly", "Game", "--base", repository.base,
                "--target", "WORKTREE", "--request-id", "CLI-REVISION",
            ])

        self.assertEqual(0, exit_code)
        result = json.loads(output.getvalue())
        validate("change-analysis.schema.json", result)
        self.assertEqual("CLI-REVISION", result["request_id"])

    def test_two_immutable_git_revisions_are_analyzed_without_checkout(self) -> None:
        repository = RevisionAnalysisRepository(self.root)
        repository.modify_target()
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "target")
        target = git(self.root, "rev-parse", "HEAD")
        head_before = target
        resolver = SnapshotResolver(self.root)

        result = RevisionChangeAnalyzer(resolver, "Unity").analyze(
            resolver.resolve_revision(repository.base, "OLD"),
            resolver.resolve_revision(target, "NEW"),
            "Game",
            "TWO-COMMITS",
        )

        self.assertEqual(head_before, git(self.root, "rev-parse", "HEAD"))
        self.assertFalse(result["revisions"]["old"]["dirty"])
        self.assertFalse(result["revisions"]["new"]["dirty"])
        self.assertNotEqual(
            result["revisions"]["old"]["revision"], result["revisions"]["new"]["revision"]
        )
        validate("change-analysis.schema.json", result)

    def test_missing_revision_bound_csproj_fails_closed(self) -> None:
        repository = RevisionAnalysisRepository(self.root, include_project=False)
        resolver = SnapshotResolver(self.root)
        old = resolver.resolve_revision(repository.base, "OLD")

        with self.assertRaisesRegex(ValueError, "revision-bound generated Unity project"):
            RevisionWorkerInputAssembler(resolver, "Unity").assemble(
                old, "Game", "MISSING-CSPROJ"
            )

        error = io.StringIO()
        with redirect_stderr(error):
            exit_code = main([
                "analyze-change", os.fspath(self.root), "Unity",
                "--assembly", "Game", "--base", repository.base,
                "--request-id", "CLI-MISSING-CSPROJ",
            ])
        self.assertEqual(2, exit_code)
        self.assertIn("revision-bound generated Unity project", error.getvalue())


if __name__ == "__main__":
    unittest.main()
