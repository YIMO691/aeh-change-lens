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
    CompileManifestExporter,
    RevisionChangeAnalyzer,
    RevisionWorkerInputAssembler,
)
from aeh_change_lens.snapshot import SnapshotResolver, SnapshotStaleError  # noqa: E402
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
    def __init__(
        self,
        root: Path,
        *,
        include_project: bool = True,
        ignore_project: bool = False,
        export_manifest: bool = False,
    ) -> None:
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
        if ignore_project:
            (root / ".gitignore").write_text("*.csproj\n", encoding="utf-8")
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
        if export_manifest:
            exporter = CompileManifestExporter(root, "Unity")
            exporter.write(exporter.build("Game"))
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

    def test_cli_explain_runs_old_new_analysis_and_writes_offline_story(self) -> None:
        repository = RevisionAnalysisRepository(self.root)
        repository.modify_target()
        report_path = self.root.parent / f"{self.root.name}-change-story.html"
        analysis_path = self.root.parent / f"{self.root.name}-change-analysis.json"
        intent_path = self.root.parent / f"{self.root.name}-intent.json"
        intent_path.write_text(json.dumps({
            "schema_version": "1.0.0",
            "source": "revision integration fixture",
            "user_goal": "拒绝非正数增量。",
            "ai_plan": ["在写入计数器前增加条件判断。"],
        }), encoding="utf-8")
        self.addCleanup(report_path.unlink, missing_ok=True)
        self.addCleanup(analysis_path.unlink, missing_ok=True)
        self.addCleanup(intent_path.unlink, missing_ok=True)
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main([
                "explain", os.fspath(self.root), "Unity",
                "--assembly", "Game", "--base", repository.base,
                "--target", "WORKTREE", "--request-id", "CLI-EXPLAIN",
                "--intent-evidence", os.fspath(intent_path),
                "--analysis-output", os.fspath(analysis_path),
                "--output", os.fspath(report_path), "--pretty",
            ])

        result = json.loads(output.getvalue())
        rendered = report_path.read_text(encoding="utf-8")
        retained_analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        self.assertEqual(0, exit_code)
        self.assertEqual("CLI-EXPLAIN", retained_analysis["request_id"])
        self.assertEqual(retained_analysis["canonical_digest"], result["analysis_digest"])
        self.assertIn("原链路", rendered)
        self.assertIn("新链路", rendered)
        self.assertIn("拒绝非正数增量", rendered)
        self.assertIn(repository.source.resolve().as_uri(), rendered)
        self.assertNotIn((self.root / "Unity/Unity/Assets/Game/Counter.cs").as_uri(), rendered)
        self.assertNotIn("<script", rendered.lower())

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

    def test_explicit_syntax_partial_fallback_writes_report_without_baseline(self) -> None:
        repository = RevisionAnalysisRepository(self.root, include_project=False)
        repository.modify_target()
        report_path = self.root.parent / f"{self.root.name}-syntax-partial.html"
        analysis_path = self.root.parent / f"{self.root.name}-syntax-partial.json"
        self.addCleanup(report_path.unlink, missing_ok=True)
        self.addCleanup(analysis_path.unlink, missing_ok=True)
        before = git(self.root, "status", "--porcelain=v1", "--untracked-files=all")
        output = io.StringIO()
        progress = io.StringIO()

        with redirect_stdout(output), redirect_stderr(progress):
            exit_code = main([
                "explain", os.fspath(self.root), "Unity",
                "--assembly", "Game", "--base", repository.base,
                "--target", "WORKTREE", "--request-id", "SYNTAX-PARTIAL",
                "--analysis-output", os.fspath(analysis_path),
                "--output", os.fspath(report_path),
                "--allow-syntax-partial", "--progress", "--pretty",
            ])

        self.assertEqual(0, exit_code, progress.getvalue())
        result = json.loads(output.getvalue())
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        validate("change-analysis.schema.json", analysis)
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual("PARTIAL", analysis["status"])
        self.assertEqual("SYNTAX_ONLY", analysis["contexts"]["old"]["generated_project"]["kind"])
        self.assertEqual("MISSING", analysis["contexts"]["new"]["completeness"])
        self.assertTrue(any(
            "syntax-only PARTIAL" in item for item in analysis["limitations"]
        ))
        self.assertFalse(any(
            item["provenance"]["confidence"] == "CONFIRMED_STATIC"
            for collection in ("nodes", "edges")
            for item in analysis["diff"][collection]
        ))
        self.assertFalse(any(
            item["confidence"] == "CONFIRMED_STATIC"
            for item in analysis["diff"]["mappings"]
        ))
        self.assertIn("预检 OLD/NEW revision 编译基线", progress.getvalue())
        self.assertIn("生成双层 Change Story", progress.getvalue())
        rendered = report_path.read_text(encoding="utf-8")
        self.assertIn("PARTIAL", rendered)
        self.assertIn("PARTIAL 结构分析显示", rendered)
        self.assertNotIn("CODE_FACT · CONFIRMED_STATIC", rendered)
        self.assertEqual(
            before, git(self.root, "status", "--porcelain=v1", "--untracked-files=all")
        )

    def test_missing_baseline_preflight_fails_before_full_snapshot_resolution(self) -> None:
        repository = RevisionAnalysisRepository(self.root, include_project=False)
        repository.modify_target()
        original = SnapshotResolver.resolve_revision

        def forbidden_full_resolution(*args, **kwargs):
            raise AssertionError("full snapshot resolution must not run before baseline failure")

        SnapshotResolver.resolve_revision = forbidden_full_resolution
        try:
            error = io.StringIO()
            with redirect_stderr(error):
                exit_code = main([
                    "analyze-change", os.fspath(self.root), "Unity",
                    "--assembly", "Game", "--base", repository.base,
                    "--request-id", "FAST-PREFLIGHT",
                ])
        finally:
            SnapshotResolver.resolve_revision = original

        self.assertEqual(2, exit_code)
        self.assertIn("--allow-syntax-partial", error.getvalue())

    def test_ignored_csproj_uses_revision_bound_compile_manifests(self) -> None:
        repository = RevisionAnalysisRepository(
            self.root, ignore_project=True, export_manifest=True
        )
        self.assertNotIn("Unity/Game.csproj", git(self.root, "ls-files").splitlines())
        repository.modify_target()
        exporter = CompileManifestExporter(self.root, "Unity")
        exporter.write(exporter.build("Game"))
        resolver = SnapshotResolver(self.root)

        result = RevisionChangeAnalyzer(resolver, "Unity").analyze(
            resolver.resolve_revision(repository.base, "OLD"),
            resolver.resolve_worktree("NEW"),
            "Game",
            "MANIFEST-GOLDEN",
        )

        validate("change-analysis.schema.json", result)
        self.assertEqual(
            "COMPILE_MANIFEST", result["contexts"]["old"]["generated_project"]["kind"]
        )
        self.assertEqual(
            "COMPILE_MANIFEST", result["contexts"]["new"]["generated_project"]["kind"]
        )
        self.assertNotEqual(
            result["contexts"]["old"]["generated_project"]["manifest_sha256"],
            result["contexts"]["new"]["generated_project"]["manifest_sha256"],
        )
        self.assertTrue(any(
            node["kind"] == "CONDITION" and node["revision"] == "NEW"
            for node in result["diff"]["nodes"]
        ))

    def test_stale_compile_manifest_source_digest_fails_closed(self) -> None:
        repository = RevisionAnalysisRepository(
            self.root, ignore_project=True, export_manifest=True
        )
        repository.modify_target()
        resolver = SnapshotResolver(self.root)

        with self.assertRaisesRegex(SnapshotStaleError, "compile manifest source digest"):
            RevisionWorkerInputAssembler(resolver, "Unity").assemble(
                resolver.resolve_worktree("NEW"), "Game", "STALE-MANIFEST"
            )

    def test_stale_worktree_manifest_options_fail_closed(self) -> None:
        repository = RevisionAnalysisRepository(
            self.root, ignore_project=True, export_manifest=True
        )
        project = self.root / "Unity/Game.csproj"
        project.write_text(
            project.read_text(encoding="utf-8").replace(
                "UNITY_EDITOR", "UNITY_EDITOR;NEW_OPTION"
            ),
            encoding="utf-8",
        )
        resolver = SnapshotResolver(self.root)

        with self.assertRaisesRegex(SnapshotStaleError, "live generated project"):
            RevisionWorkerInputAssembler(resolver, "Unity").assemble(
                resolver.resolve_worktree("NEW"), "Game", "STALE-OPTIONS"
            )


if __name__ == "__main__":
    unittest.main()
