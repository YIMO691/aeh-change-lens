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


def test_only_analysis() -> dict:
    payload = copy.deepcopy(analysis())
    nodes = []
    for index, label in enumerate((
        "Program.ReadRepoFile(params string[])",
        "Program.VerifyActualExportedConfiguration()",
        "Program.VerifyProtocolFieldNumbers()",
    )):
        node = _node("NEW", f"test-{index}", "METHOD", label, 100 + index * 20, "ADDED")
        node["location"]["path"] = "Tests/MonsterCombo/Program.cs"
        nodes.append(node)
    payload["diff"]["nodes"] = nodes
    payload["diff"]["edges"] = []
    payload["diff"]["mappings"] = []
    payload["diff"]["summary"] = {
        "old_nodes": 0,
        "new_nodes": 3,
        "mapped_nodes": 0,
        "added_nodes": 3,
        "removed_nodes": 0,
        "updated_node_pairs": 0,
        "moved_node_pairs": 0,
        "added_edges": 0,
        "removed_edges": 0,
        "unchanged_edge_pairs": 0,
    }
    payload["canonical_digest"] = "8" * 64
    return payload


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
        self.assertLessEqual(len(first["quick_view"]["change_cards"]), 5)
        self.assertLessEqual(len(first["quick_view"]["old_flow"]), 8)
        self.assertLessEqual(len(first["quick_view"]["new_flow"]), 8)
        self.assertTrue(first["quick_view"]["old_flow"])
        self.assertTrue(first["quick_view"]["new_flow"])
        self.assertEqual("1.5.0", first["schema_version"])
        self.assertEqual("MODIFIED", first["visual_map"]["change_shape"])
        self.assertEqual("VERIFIED_FLOW", first["visual_map"]["relationship_mode"])
        self.assertLessEqual(len(first["visual_map"]["changes"]), 3)
        self.assertLessEqual(len(first["visual_map"]["before"]), 3)
        self.assertLessEqual(len(first["visual_map"]["after"]), 3)
        self.assertTrue(first["deep_dive"]["stages"])
        self.assertTrue(first["scenario_lens"]["scenarios"])
        self.assertLessEqual(len(first["scenario_lens"]["scenarios"]), 5)
        self.assertLessEqual(len(first["scenario_lens"]["takeaways_zh"]), 3)
        self.assertEqual(
            len(first["scenario_lens"]["takeaways_zh"]),
            len(first["scenario_lens"]["takeaways_en"]),
        )
        self.assertIn("来源证据", first["deep_dive"]["method_note_zh"])
        self.assertEqual(
            first["scenario_lens"]["primary_scenario_id"],
            first["daily_brief"]["primary_scenario_id"],
        )
        self.assertGreaterEqual(len(first["daily_brief"]["checks"]), 2)
        self.assertLessEqual(len(first["daily_brief"]["checks"]), 3)
        self.assertTrue(all(item["evidence_refs"] for item in first["daily_brief"]["checks"]))

    def test_absent_source_evidence_is_disclosed_not_invented(self) -> None:
        story = ChangeStoryBuilder().build(analysis())

        self.assertFalse(any(item["layer"] == "SOURCE_EVIDENCE" for item in story["claims"]))
        self.assertTrue(any("未提供用户需求" in item for item in story["limitations"]))
        self.assertIn("不是隐藏思维链", story["deep_dive"]["method_note_zh"])
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
        self.assertIn("只看结论", rendered)
        self.assertIn("理解改法", rendered)
        self.assertIn("核对证据", rendered)
        self.assertIn('id="tab-daily" checked', rendered)
        self.assertIn("我今天应该先看什么", rendered)
        self.assertIn("建议先验证", rendered)
        self.assertIn("这是检查建议，不是代码事实", rendered)
        self.assertIn("先记住这三点", rendered)
        self.assertIn('class="takeaways"', rendered)
        self.assertIn("主场景 · MODIFIED", rendered)
        self.assertIn("选择你要理解的问题", rendered)
        self.assertIn("scenario-view-0", rendered)
        self.assertIn("展开完整 OLD / NEW 版本对照", rendered)
        self.assertNotIn('<details class="stage" open>', rendered)
        self.assertIn('data-change-shape="MODIFIED"', rendered)
        self.assertIn('data-scenario-shape="MODIFIED"', rendered)
        self.assertIn('aria-label="版本变化，不表示调用"', rendered)
        self.assertIn("奖励 &lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertNotIn("<script", rendered.lower())
        self.assertNotIn("https://", rendered)

    def test_test_only_change_uses_parallel_checks_instead_of_empty_old_new_lanes(self) -> None:
        story = ChangeStoryBuilder().build(test_only_analysis())
        rendered = HtmlChangeStoryRenderer().render(story)
        visual = story["visual_map"]

        validate("change-story.schema.json", story)
        self.assertEqual("TEST_ONLY", visual["change_shape"])
        self.assertEqual("PARALLEL_FACTS", visual["relationship_mode"])
        self.assertEqual(3, len(visual["changes"]))
        self.assertIn("测试保障", visual["headline_zh"])
        self.assertIn("不表示它们按显示顺序相互调用", visual["relationship_note_zh"])
        self.assertIn('aria-label="并列事实，不表示调用"', rendered)
        self.assertNotIn('aria-label="版本变化，不表示调用"', rendered)
        self.assertNotIn("原版本没有进入业务聚焦层的显著步骤", rendered)

    def test_new_editor_tool_uses_added_shape_with_explicit_absence_context(self) -> None:
        payload = test_only_analysis()
        for node in payload["diff"]["nodes"]:
            node["location"]["path"] = "Unity/Assets/Editor/Combo/Tool.cs"
        story = ChangeStoryBuilder().build(payload)
        rendered = HtmlChangeStoryRenderer().render(story)

        self.assertEqual("ADDED", story["visual_map"]["change_shape"])
        self.assertTrue(all(
            scenario["change_shape"] == "ADDED"
            for scenario in story["scenario_lens"]["scenarios"]
        ))
        self.assertIn("旧版本未发现对应结构信号", story["visual_map"]["before"][0]["label_zh"])
        self.assertIn("Unity 编辑器工具", story["visual_map"]["after"][0]["label_zh"])
        self.assertIn('data-scenario-shape="ADDED"', rendered)
        self.assertIn('class="scenario-single"', rendered)
        self.assertNotIn("旧版本没有进入该场景的聚焦变化证据", rendered)

    def test_removed_and_configuration_changes_use_shape_specific_maps(self) -> None:
        for role, change, path, expected in (
            ("OLD", "REMOVED", "Unity/Codes/Model/Feature.cs", "REMOVED"),
            ("NEW", "ADDED", "Config/MonsterComboRule.cs", "CONFIG_PROTOCOL"),
        ):
            with self.subTest(expected=expected):
                payload = copy.deepcopy(analysis())
                node = _node(role, expected.lower(), "TYPE", "Game.MonsterComboRule", 10, change)
                node["location"]["path"] = path
                payload["diff"]["nodes"] = [node]
                payload["diff"]["edges"] = []
                payload["diff"]["mappings"] = []
                payload["diff"]["summary"] = {
                    "old_nodes": 1 if role == "OLD" else 0,
                    "new_nodes": 1 if role == "NEW" else 0,
                    "mapped_nodes": 0,
                    "added_nodes": 1 if change == "ADDED" else 0,
                    "removed_nodes": 1 if change == "REMOVED" else 0,
                    "updated_node_pairs": 0,
                    "moved_node_pairs": 0,
                    "added_edges": 0,
                    "removed_edges": 0,
                    "unchanged_edge_pairs": 0,
                }

                story = ChangeStoryBuilder().build(payload)

                validate("change-story.schema.json", story)
                self.assertEqual(expected, story["visual_map"]["change_shape"])

    def test_empty_business_focus_still_produces_a_schema_valid_truthful_map(self) -> None:
        payload = copy.deepcopy(analysis())
        payload["diff"]["nodes"] = []
        payload["diff"]["edges"] = []
        payload["diff"]["mappings"] = []
        payload["diff"]["summary"] = {key: 0 for key in payload["diff"]["summary"]}

        story = ChangeStoryBuilder().build(payload)

        validate("change-story.schema.json", story)
        self.assertEqual("PARALLEL", story["visual_map"]["change_shape"])
        self.assertIn("没有进入快速视图", story["visual_map"]["changes"][0]["label_zh"])

    def test_generated_noise_stays_in_technical_evidence_not_quick_view(self) -> None:
        payload = copy.deepcopy(analysis())
        for index in range(30):
            generated = _node(
                "NEW", f"generated-{index:02d}", "TYPE", f"Generated.Payload{index}",
                100 + index, "ADDED",
            )
            generated["location"]["path"] = "Server/Model/Generate/Payloads.cs"
            payload["diff"]["nodes"].append(generated)
        payload["diff"]["summary"]["new_nodes"] += 30
        payload["diff"]["summary"]["added_nodes"] += 30

        story = ChangeStoryBuilder().build(payload)

        self.assertNotIn("GENERATED", {item["area"] for item in story["quick_view"]["change_cards"]})
        self.assertFalse(any(
            "Generated.Payload" in item["label"]
            for item in story["quick_view"]["new_flow"]
        ))
        self.assertTrue(any("Generated.Payload" in item["subject_zh"] for item in story["changes"]))

    def test_unity_editor_tooling_prioritizes_roles_over_lifecycle_noise(self) -> None:
        payload = copy.deepcopy(analysis())
        additions = (
            ("editor-window", "TYPE", "ET.EditorTools.ComboEditorWindow"),
            ("editor-gui", "METHOD", "ET.EditorTools.ComboEditorWindow.OnGUI()"),
            ("editor-repository", "TYPE", "ET.EditorTools.ComboExcelRepository"),
            ("editor-load", "METHOD", "ET.EditorTools.ComboExcelRepository.Load(string)"),
            ("editor-validator", "TYPE", "ET.EditorTools.ComboValidator"),
            ("editor-validate", "METHOD", "ET.EditorTools.ComboValidator.Validate()"),
        )
        for index, (suffix, kind, label) in enumerate(additions):
            node = _node("NEW", suffix, kind, label, 100 + index, "ADDED")
            node["location"]["path"] = "Unity/Assets/Editor/Combo/Tool.cs"
            payload["diff"]["nodes"].append(node)
        payload["diff"]["summary"]["new_nodes"] += len(additions)
        payload["diff"]["summary"]["added_nodes"] += len(additions)

        story = ChangeStoryBuilder().build(payload)
        editor_card = next(
            item for item in story["quick_view"]["change_cards"] if item["area"] == "EDITOR"
        )

        self.assertIn("ComboEditorWindow", editor_card["summary_zh"])
        self.assertIn("ComboExcelRepository", editor_card["summary_zh"])
        self.assertIn("ComboValidator", editor_card["summary_zh"])
        self.assertNotIn("OnGUI", editor_card["summary_zh"])
        self.assertTrue(any(
            item["area"] == "EDITOR" for item in story["quick_view"]["new_flow"]
        ))

    def test_scenario_lens_groups_editor_readiness_by_reader_question(self) -> None:
        payload = copy.deepcopy(analysis())
        for index, label in enumerate((
            "ET.EditorTools.ComboEditorWindow.DrawSkillReadiness()",
            "ET.EditorTools.MonsterSkillAuthoringService.AnalyzeReadiness()",
            "ET.EditorTools.ComboEditorWindow.HasAllSkillPrefabs()",
        )):
            node = _node("NEW", f"readiness-{index}", "METHOD", label, 180 + index, "ADDED")
            node["location"]["path"] = "Unity/Assets/Editor/Combo/Tool.cs"
            payload["diff"]["nodes"].append(node)
        payload["diff"]["summary"]["new_nodes"] += 3
        payload["diff"]["summary"]["added_nodes"] += 3
        payload["diff"]["edges"].append(_edge(
            "NEW", "readiness-call", "node:new:readiness-0",
            "node:new:readiness-2", "CALLS", "ADDED",
        ))
        payload["diff"]["summary"]["added_edges"] += 1

        story = ChangeStoryBuilder().build(payload)
        rendered = HtmlChangeStoryRenderer().render(story)
        lens = story["scenario_lens"]
        guided = next(
            item for item in lens["scenarios"]
            if item["scenario_id"] == "scenario:guided-authoring"
        )

        validate("change-story.schema.json", story)
        self.assertLessEqual(len(guided["before"]) + len(guided["after"]), 7)
        self.assertIn("完成", guided["question_zh"])
        self.assertTrue(any(
            item["business_label_zh"] == "计算并显示完成度"
            for item in guided["after"]
        ))
        self.assertEqual("VERIFIED_FLOW", guided["relationship_mode"])
        self.assertIn("已证实的关系路径", rendered)
        self.assertIn('<article class="route-row">', rendered)

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
            story_path = root / "story.json"
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
                    "--story-output", str(story_path),
                    "--intent-evidence", str(evidence_path), "--pretty",
                ])

            result = json.loads(stdout.getvalue())
            rendered = output_path.read_text(encoding="utf-8")
            story_payload = json.loads(story_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual(64, len(result["story_digest"]))
        self.assertIn("阻止无效奖励", rendered)
        self.assertIn('data-story-digest=', rendered)
        self.assertEqual(str(story_path.resolve()), result["story_path"])
        validate("change-story.schema.json", story_payload)

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
