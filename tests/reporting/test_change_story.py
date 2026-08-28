from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aeh_change_lens.cli import main  # noqa: E402
from aeh_change_lens.languages.csharp import AnalyzerGraphDiffer, MappingHint  # noqa: E402
from aeh_change_lens.reporting import ChangeStoryBuilder, HtmlChangeStoryRenderer  # noqa: E402
from tests.analyzer.test_graph_diff import golden_worker_input  # noqa: E402
from tests.analyzer.test_worker import run_worker  # noqa: E402
from tests.contract.test_contracts import validate  # noqa: E402


def _location(role: str, line: int) -> dict:
    return {
        "revision_role": role,
        "path": "Assets/Game/RewardController.cs",
        "start_line": line,
        "end_line": line,
        "content_hash": ("a" if role == "OLD" else "b") * 64,
    }


def _node(role: str, suffix: str, kind: str, label: str, line: int, change: str) -> dict:
    return {
        "node_id": f"node:{role.lower()}:{suffix}",
        "revision": role,
        "kind": kind,
        "change": change,
        "label": label,
        "location": _location(role, line),
        "provenance": {
            "origin": "test-fixture",
            "confidence": "CONFIRMED_STATIC",
            "source_ids": [("a" if role == "OLD" else "b") * 64],
            "limitations": [],
        },
        "evidence_refs": [],
    }


def _edge(
    role: str, suffix: str, source: str, target: str, relation: str, change: str
) -> dict:
    return {
        "edge_id": f"edge:{role.lower()}:{suffix}",
        "revision": role,
        "source_node_id": source,
        "target_node_id": target,
        "relation": relation,
        "change": change,
        "provenance": {
            "origin": "test-fixture",
            "confidence": "STRUCTURAL" if relation == "BRANCHES_TO" else "CONFIRMED_STATIC",
            "source_ids": [("a" if role == "OLD" else "b") * 64],
            "limitations": [],
        },
        "evidence_refs": [],
    }


def analysis() -> dict:
    old_method = _node("OLD", "claim", "METHOD", "Game.RewardController.Claim(int)", 10, "UPDATED")
    old_state = _node("OLD", "balance", "STATE", "Game.Wallet.Balance", 30, "UNCHANGED_CONTEXT")
    new_method = _node("NEW", "try-claim", "METHOD", "Game.RewardController.TryClaim(int)", 10, "UPDATED")
    new_condition = _node("NEW", "authorized", "CONDITION", "amount > 0", 13, "ADDED")
    new_state = _node("NEW", "balance", "STATE", "Game.Wallet.Balance", 31, "UNCHANGED_CONTEXT")
    nodes = [old_method, old_state, new_method, new_condition, new_state]
    edges = [
        _edge("OLD", "write", old_method["node_id"], old_state["node_id"], "WRITES_STATE", "REMOVED"),
        _edge("NEW", "guard", new_method["node_id"], new_condition["node_id"], "BRANCHES_TO", "ADDED"),
        _edge("NEW", "write", new_condition["node_id"], new_state["node_id"], "WRITES_STATE", "ADDED"),
    ]
    mappings = [
        {
            "mapping_id": "mapping:claim",
            "old_node_id": old_method["node_id"],
            "new_node_id": new_method["node_id"],
            "kind": "RENAMED",
            "confidence": "STRUCTURAL",
            "basis": ["human_annotation"],
            "alternatives": [],
        },
        {
            "mapping_id": "mapping:balance",
            "old_node_id": old_state["node_id"],
            "new_node_id": new_state["node_id"],
            "kind": "SAME_SYMBOL",
            "confidence": "CONFIRMED_STATIC",
            "basis": ["same_qualified_symbol"],
            "alternatives": [],
        },
    ]
    summary = {
        "old_nodes": 2,
        "new_nodes": 3,
        "mapped_nodes": 2,
        "added_nodes": 1,
        "removed_nodes": 0,
        "updated_node_pairs": 1,
        "moved_node_pairs": 0,
        "added_edges": 2,
        "removed_edges": 1,
        "unchanged_edge_pairs": 0,
    }
    return {
        "schema_version": "1.0.0",
        "request_id": "STORY-TEST",
        "status": "PARTIAL",
        "revisions": {
            "old": {
                "role": "OLD", "revision": "base", "tree_hash": "1" * 64,
                "source_manifest_hash": "2" * 64, "dirty": False,
            },
            "new": {
                "role": "NEW", "revision": "WORKTREE", "tree_hash": "3" * 64,
                "source_manifest_hash": "4" * 64, "dirty": True,
            },
        },
        "renames": [],
        "contexts": {},
        "diff": {
            "schema_version": "1.0.0", "status": "PARTIAL",
            "old_request_id": "STORY-TEST-OLD", "new_request_id": "STORY-TEST-NEW",
            "source_status": {"old": "PARTIAL", "new": "PARTIAL"},
            "nodes": nodes, "edges": edges, "mappings": mappings, "summary": summary,
            "limitations": [], "canonical_digest": "5" * 64,
        },
        "policy": {"network_access": "DENY", "execute_project_code": False, "checkout": False},
        "limitations": ["Unity 上下文不完整。"],
        "canonical_digest": "6" * 64,
    }


class ChangeStoryTests(unittest.TestCase):
    def test_story_is_deterministic_schema_valid_and_separates_claim_layers(self) -> None:
        evidence = {
            "schema_version": "1.0.0",
            "source": "reviewed-session",
            "user_goal": "购买数量必须大于零。",
            "ai_plan": ["在写入余额前增加参数检查。"],
            "commit_message": "guard invalid reward amounts",
        }
        first = ChangeStoryBuilder().build(analysis(), intent_evidence=evidence)
        second = ChangeStoryBuilder().build(analysis(), intent_evidence=evidence)

        self.assertEqual(first, second)
        validate("change-story.schema.json", first)
        layers = {item["layer"] for item in first["claims"]}
        self.assertEqual({"CODE_FACT", "SOURCE_EVIDENCE", "INTENT_INFERENCE"}, layers)
        self.assertEqual("原链路", first["lanes"]["old"]["label_zh"])
        self.assertEqual("新链路", first["lanes"]["new"]["label_zh"])
        self.assertTrue(first["lanes"]["old"]["chains"])
        self.assertTrue(first["lanes"]["new"]["chains"])
        self.assertTrue(any(item["kind"] == "RENAMED" for item in first["changes"]))
        self.assertTrue(any(item["kind"] == "STATE" for item in first["impacts"]))

    def test_absent_source_evidence_is_disclosed_not_invented(self) -> None:
        story = ChangeStoryBuilder().build(analysis())

        self.assertFalse(any(item["layer"] == "SOURCE_EVIDENCE" for item in story["claims"]))
        self.assertTrue(any("未提供用户需求" in item for item in story["limitations"]))
        self.assertTrue(all(
            "可能" in item["statement_zh"]
            for item in story["claims"] if item["layer"] == "INTENT_INFERENCE"
        ))

    def test_html_is_offline_script_free_and_escapes_untrusted_text(self) -> None:
        story = ChangeStoryBuilder().build(analysis(), title="奖励 <script>alert(1)</script>")
        rendered = HtmlChangeStoryRenderer().render(story)

        self.assertIn("原链路", rendered)
        self.assertIn("新链路", rendered)
        self.assertIn("CODE_FACT", rendered)
        self.assertIn("INTENT_INFERENCE", rendered)
        self.assertIn("奖励 &lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertNotIn("<script", rendered.lower())
        self.assertNotIn("https://", rendered)

    def test_only_new_worktree_locations_receive_local_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            story = ChangeStoryBuilder().build(analysis())
            worktree_html = HtmlChangeStoryRenderer().render(story, repository_root=root)
            immutable = analysis()
            immutable["revisions"]["new"]["revision"] = "target-commit"
            immutable["revisions"]["new"]["dirty"] = False
            immutable_story = ChangeStoryBuilder().build(immutable)
            immutable_html = HtmlChangeStoryRenderer().render(
                immutable_story, repository_root=root
            )

        self.assertIn('href="file:///', worktree_html)
        self.assertNotIn('href="file:///', immutable_html)

    def test_chain_limit_is_deterministic_and_disclosed(self) -> None:
        payload = copy.deepcopy(analysis())
        source_id = "node:new:try-claim"
        for index in range(20):
            candidate = _node(
                "NEW", f"branch-{index:02d}", "CONDITION", f"condition {index}",
                40 + index, "ADDED",
            )
            payload["diff"]["nodes"].append(candidate)
            payload["diff"]["edges"].append(_edge(
                "NEW", f"branch-{index:02d}", source_id, candidate["node_id"],
                "BRANCHES_TO", "ADDED",
            ))
        payload["diff"]["summary"]["new_nodes"] += 20
        payload["diff"]["summary"]["added_nodes"] += 20
        payload["diff"]["summary"]["added_edges"] += 20

        first = ChangeStoryBuilder().build(payload)
        second = ChangeStoryBuilder().build(payload)

        self.assertEqual(first, second)
        self.assertEqual(16, len(first["lanes"]["new"]["chains"]))
        self.assertTrue(any("确定性截断" in item for item in first["limitations"]))

    def test_render_report_cli_writes_html_and_returns_digests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            analysis_path = root / "analysis.json"
            output_path = root / "report.html"
            evidence_path = root / "intent.json"
            analysis_path.write_text(json.dumps(analysis()), encoding="utf-8")
            evidence_path.write_text(json.dumps({
                "schema_version": "1.0.0", "source": "test",
                "user_goal": "阻止无效奖励。",
            }), encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main([
                    "render-report", str(analysis_path), "--output", str(output_path),
                    "--intent-evidence", str(evidence_path), "--pretty",
                ])

            result = json.loads(stdout.getvalue())
            rendered = output_path.read_text(encoding="utf-8")

        self.assertEqual(0, exit_code)
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual(64, len(result["story_digest"]))
        self.assertIn("阻止无效奖励", rendered)
        self.assertIn('data-story-digest=', rendered)

    def test_invalid_or_empty_intent_evidence_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported intent evidence fields"):
            ChangeStoryBuilder().build(analysis(), intent_evidence={
                "schema_version": "1.0.0", "source": "test", "thoughts": ["hidden"]
            })
        with self.assertRaisesRegex(ValueError, "must contain"):
            ChangeStoryBuilder().build(analysis(), intent_evidence={
                "schema_version": "1.0.0", "source": "test", "ai_plan": []
            })

    def test_unity_minimal_real_worker_diff_becomes_readable_old_new_story(self) -> None:
        old_run = run_worker(golden_worker_input("base", "OLD"))
        new_run = run_worker(golden_worker_input("target", "NEW"))
        self.assertEqual(0, old_run.returncode, old_run.stderr)
        self.assertEqual(0, new_run.returncode, new_run.stderr)
        raw_hints = json.loads(
            (ROOT / "fixtures/unity-minimal/mapping-hints.json").read_text(encoding="utf-8")
        )
        hints = [MappingHint(
            old_label=item["old_label"], new_label=item["new_label"],
            kind=item["kind"], basis=tuple(item["basis"]),
        ) for item in raw_hints]
        diff = AnalyzerGraphDiffer().compare(
            json.loads(old_run.stdout), json.loads(new_run.stdout), mapping_hints=hints
        ).to_dict()
        payload = analysis()
        payload["diff"] = diff
        payload["canonical_digest"] = "7" * 64

        story = ChangeStoryBuilder().build(payload, intent_evidence={
            "schema_version": "1.0.0", "source": "UNITY-MINIMAL-001 annotation",
            "user_goal": "增加领奖校验，并把奖励策略拆分到独立类型。",
        })
        rendered = HtmlChangeStoryRenderer().render(story)

        validate("change-story.schema.json", story)
        self.assertIn("ChangeLens.Fixture.RewardController.Claim(int)", rendered)
        self.assertIn("ChangeLens.Fixture.RewardController.TryClaim(int)", rendered)
        self.assertIn("ChangeLens.Fixture.RewardPolicy.CalculateBonus(int)", rendered)
        self.assertIn("可能在重新划分类型或模块职责", rendered)


if __name__ == "__main__":
    unittest.main()
