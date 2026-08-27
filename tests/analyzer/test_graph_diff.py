from __future__ import annotations

import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aeh_change_lens.languages.csharp import AnalyzerGraphDiffer, MappingHint
from aeh_change_lens.cli import main
from tests.analyzer.test_worker import run_worker
from tests.contract.test_contracts import validate
import yaml


_OLD_HASH = "a" * 64
_NEW_HASH = "b" * 64


def node(revision: str, node_id: str, kind: str, label: str, line: int) -> dict:
    return {
        "node_id": node_id,
        "revision": revision,
        "kind": kind,
        "change": "UNCHANGED_CONTEXT",
        "label": label,
        "location": {
            "revision_role": revision,
            "path": "Assets/Game.cs",
            "start_line": line,
            "end_line": line,
            "content_hash": _OLD_HASH if revision == "OLD" else _NEW_HASH,
        },
        "provenance": {
            "origin": "fixture",
            "confidence": "CONFIRMED_STATIC",
            "source_ids": [_OLD_HASH if revision == "OLD" else _NEW_HASH],
            "limitations": [],
        },
        "evidence_refs": [],
    }


def edge(revision: str, edge_id: str, source: str, target: str) -> dict:
    return {
        "edge_id": edge_id,
        "revision": revision,
        "source_node_id": source,
        "target_node_id": target,
        "relation": "BRANCHES_TO",
        "change": "UNCHANGED_CONTEXT",
        "provenance": {
            "origin": "fixture",
            "confidence": "STRUCTURAL",
            "source_ids": [_OLD_HASH if revision == "OLD" else _NEW_HASH],
            "limitations": [],
        },
        "evidence_refs": [],
    }


def result(revision: str, nodes: list[dict], edges: list[dict]) -> dict:
    return {
        "schema_version": "1.0.0",
        "request_id": f"REQ-{revision}",
        "status": "COMPLETE",
        "capabilities": {
            "syntax": True,
            "semantic_model": True,
            "unity_context": "COMPLETE",
        },
        "nodes": nodes,
        "edges": edges,
        "diagnostics": [],
    }


def golden_worker_input(lane: str, revision: str) -> dict:
    fixture_root = ROOT / "fixtures" / "unity-minimal" / lane
    source_paths = sorted(fixture_root.rglob("*.cs"))
    source_paths.append(ROOT / "tests" / "analyzer" / "UnityStubs.cs")
    sources = []
    for path in source_paths:
        content = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        logical_path = (
            "__stubs__/UnityStubs.cs"
            if path.name == "UnityStubs.cs"
            else path.relative_to(fixture_root).as_posix()
        )
        sources.append({
            "path": logical_path,
            "content": content,
            "content_hash": digest,
            "snapshot_content_hash": digest,
            "source_encoding": "UTF-8",
        })
    return {
        "schema_version": "1.0.0",
        "request_id": f"GOLDEN-{revision}",
        "revision": revision,
        "unity_context": {
            "completeness": "PARTIAL",
            "unity_version": "2022.3.62f1",
            "defines": ["UNITY_EDITOR"],
            "references": [],
        },
        "source_files": sources,
    }


class AnalyzerGraphDifferTests(unittest.TestCase):
    def test_stable_symbol_and_unique_structure_form_deterministic_diff(self) -> None:
        old_method = "csharp:OLD:Game.Controller.Run()"
        new_method = "csharp:NEW:Game.Controller.Run()"
        old_condition = "csharp:OLD:Assets/Game.cs:condition:30"
        new_condition = "csharp:NEW:Assets/Game.cs:condition:40"
        added_condition = "csharp:NEW:Assets/Game.cs:condition:50"
        old = result("OLD", [
            node("OLD", old_method, "METHOD", "Game.Controller.Run()", 10),
            node("OLD", old_condition, "CONDITION", "ready", 12),
        ], [edge("OLD", "edge:OLD:ready", old_method, old_condition)])
        new = result("NEW", [
            node("NEW", new_method, "METHOD", "Game.Controller.Run()", 10),
            node("NEW", new_condition, "CONDITION", "ready", 14),
            node("NEW", added_condition, "CONDITION", "authorized", 18),
        ], [
            edge("NEW", "edge:NEW:ready", new_method, new_condition),
            edge("NEW", "edge:NEW:authorized", new_method, added_condition),
        ])

        first = AnalyzerGraphDiffer().compare(old, new).to_dict()
        second = AnalyzerGraphDiffer().compare(copy.deepcopy(old), copy.deepcopy(new)).to_dict()

        self.assertEqual(first, second)
        validate("analyzer-diff.schema.json", first)
        self.assertEqual("UPDATED", next(
            item["change"] for item in first["nodes"] if item["node_id"] == old_method
        ))
        self.assertEqual("ADDED", next(
            item["change"] for item in first["nodes"] if item["node_id"] == added_condition
        ))
        self.assertEqual(1, first["summary"]["added_edges"])
        self.assertEqual(1, first["summary"]["unchanged_edge_pairs"])
        self.assertEqual(2, first["summary"]["mapped_nodes"])

    def test_explicit_rename_is_structural_and_marks_both_nodes_updated(self) -> None:
        old_id = "csharp:OLD:Game.Controller.Claim(int)"
        new_id = "csharp:NEW:Game.Controller.TryClaim(int)"
        old = result("OLD", [node("OLD", old_id, "METHOD", "Game.Controller.Claim(int)", 10)], [])
        new = result("NEW", [node("NEW", new_id, "METHOD", "Game.Controller.TryClaim(int)", 10)], [])

        diff = AnalyzerGraphDiffer().compare(old, new, mapping_hints=[MappingHint(
            old_label="Game.Controller.Claim(int)",
            new_label="Game.Controller.TryClaim(int)",
            kind="RENAMED",
            basis=("human_annotation", "reviewed_rename"),
        )]).to_dict()

        self.assertEqual(1, len(diff["mappings"]))
        self.assertEqual("STRUCTURAL", diff["mappings"][0]["confidence"])
        self.assertEqual("RENAMED", diff["mappings"][0]["kind"])
        self.assertEqual({"UPDATED"}, {item["change"] for item in diff["nodes"]})

    def test_ambiguous_structural_candidates_are_not_guessed(self) -> None:
        old_method = "csharp:OLD:Game.Controller.Run()"
        new_method = "csharp:NEW:Game.Controller.Run()"
        old = result("OLD", [
            node("OLD", old_method, "METHOD", "Game.Controller.Run()", 1),
            node("OLD", "csharp:OLD:Assets/Game.cs:condition:1", "CONDITION", "same", 2),
            node("OLD", "csharp:OLD:Assets/Game.cs:condition:2", "CONDITION", "same", 3),
        ], [])
        new = result("NEW", [
            node("NEW", new_method, "METHOD", "Game.Controller.Run()", 1),
            node("NEW", "csharp:NEW:Assets/Game.cs:condition:3", "CONDITION", "same", 4),
            node("NEW", "csharp:NEW:Assets/Game.cs:condition:4", "CONDITION", "same", 5),
        ], [])

        diff = AnalyzerGraphDiffer().compare(old, new).to_dict()

        self.assertEqual(1, diff["summary"]["mapped_nodes"])
        self.assertEqual(2, diff["summary"]["added_nodes"])
        self.assertEqual(2, diff["summary"]["removed_nodes"])
        self.assertTrue(any("歧义" in item for item in diff["limitations"]))
        self.assertEqual("PARTIAL", diff["status"])

    def test_mixed_revision_and_dangling_edges_fail_closed(self) -> None:
        old_id = "csharp:OLD:Game.Controller.Run()"
        new_id = "csharp:NEW:Game.Controller.Run()"
        old = result("OLD", [node("OLD", old_id, "METHOD", "Game.Controller.Run()", 1)], [])
        new = result("NEW", [node("NEW", new_id, "METHOD", "Game.Controller.Run()", 1)], [])
        old["nodes"][0]["revision"] = "NEW"
        with self.assertRaisesRegex(ValueError, "mixed-revision"):
            AnalyzerGraphDiffer().compare(old, new)

        old = result("OLD", [node("OLD", old_id, "METHOD", "Game.Controller.Run()", 1)], [
            edge("OLD", "edge:OLD:dangling", old_id, "old:missing")
        ])
        with self.assertRaisesRegex(ValueError, "dangling edge"):
            AnalyzerGraphDiffer().compare(old, new)

    def test_cli_emits_schema_valid_diff(self) -> None:
        old_id = "csharp:OLD:Game.Controller.Claim()"
        new_id = "csharp:NEW:Game.Controller.TryClaim()"
        old = result("OLD", [node("OLD", old_id, "METHOD", "Game.Controller.Claim()", 1)], [])
        new = result("NEW", [node("NEW", new_id, "METHOD", "Game.Controller.TryClaim()", 1)], [])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old_path = root / "old.json"
            new_path = root / "new.json"
            hints_path = root / "hints.json"
            old_path.write_text(json.dumps(old), encoding="utf-8")
            new_path.write_text(json.dumps(new), encoding="utf-8")
            hints_path.write_text(json.dumps([{
                "old_label": "Game.Controller.Claim()",
                "new_label": "Game.Controller.TryClaim()",
                "kind": "RENAMED",
                "basis": ["reviewed_fixture"],
            }]), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main([
                    "graph-diff", str(old_path), str(new_path),
                    "--mapping-hints", str(hints_path),
                ])

        self.assertEqual(0, exit_code)
        payload = json.loads(output.getvalue())
        validate("analyzer-diff.schema.json", payload)
        self.assertEqual(1, payload["summary"]["mapped_nodes"])
        self.assertEqual("RENAMED", payload["mappings"][0]["kind"])

    def test_unity_minimal_human_annotation_matches_real_old_new_graph(self) -> None:
        old_run = run_worker(golden_worker_input("base", "OLD"))
        new_run = run_worker(golden_worker_input("target", "NEW"))
        self.assertEqual(0, old_run.returncode, old_run.stderr)
        self.assertEqual(0, new_run.returncode, new_run.stderr)
        old_result = json.loads(old_run.stdout)
        new_result = json.loads(new_run.stdout)
        expected = yaml.safe_load(
            (ROOT / "fixtures/unity-minimal/expected-change.yaml").read_text(encoding="utf-8")
        )
        golden = yaml.safe_load(
            (ROOT / "fixtures/unity-minimal/expected-graph-diff.yaml").read_text(encoding="utf-8")
        )
        raw_hints = json.loads(
            (ROOT / "fixtures/unity-minimal/mapping-hints.json").read_text(encoding="utf-8")
        )
        hints = [MappingHint(
            old_label=item["old_label"],
            new_label=item["new_label"],
            kind=item["kind"],
            basis=tuple(item["basis"]),
        ) for item in raw_hints]

        diff = AnalyzerGraphDiffer().compare(
            old_result, new_result, mapping_hints=hints
        ).to_dict()

        validate("analyzer-diff.schema.json", diff)
        self.assertEqual(golden["source_results"]["old_status"], old_result["status"])
        self.assertEqual(golden["source_results"]["new_status"], new_result["status"])
        self.assertEqual(golden["source_results"]["old_diagnostics"], len(old_result["diagnostics"]))
        self.assertEqual(golden["source_results"]["new_diagnostics"], len(new_result["diagnostics"]))
        self.assertEqual(golden["summary"], diff["summary"])
        self.assertEqual(golden["canonical_digest"], diff["canonical_digest"])
        self.assertEqual(golden["expected_ambiguous_groups"], len(diff["limitations"]))
        nodes = {item["node_id"]: item for item in diff["nodes"]}
        mappings = {(nodes[item["old_node_id"]]["label"], nodes[item["new_node_id"]]["label"]): item
                    for item in diff["mappings"]}
        expected_mapping_kind = {"RENAMED": "RENAMED", "MOVED": "MOVED", "UPDATED": "HEURISTIC"}
        expected_node_change = {"RENAMED": "UPDATED", "MOVED": "MOVED", "UPDATED": "UPDATED"}
        for item in expected["expected_changes"]:
            old_label = item.get("old_symbol")
            new_label = item.get("new_symbol")
            if old_label and new_label:
                mapping = mappings[(old_label, new_label)]
                self.assertEqual(expected_mapping_kind[item["kind"]], mapping["kind"], item["id"])
                self.assertEqual(
                    expected_node_change[item["kind"]], nodes[mapping["old_node_id"]]["change"], item["id"]
                )
                self.assertEqual(
                    expected_node_change[item["kind"]], nodes[mapping["new_node_id"]]["change"], item["id"]
                )
            elif old_label:
                candidates = [node for node in nodes.values() if node["revision"] == "OLD" and node["label"] == old_label]
                self.assertEqual(1, len(candidates), item["id"])
                self.assertEqual("REMOVED", candidates[0]["change"], item["id"])
            else:
                candidates = [node for node in nodes.values() if node["revision"] == "NEW" and node["label"] == new_label]
                self.assertEqual(1, len(candidates), item["id"])
                self.assertEqual("ADDED", candidates[0]["change"], item["id"])

        new_edges = [edge for edge in diff["edges"] if edge["revision"] == "NEW"]
        for expected_relation in expected["expected_relations"]:
            matches = [edge for edge in new_edges if (
                edge["relation"] == expected_relation["relation"] and
                (
                    "source" not in expected_relation or
                    nodes[edge["source_node_id"]]["label"] == expected_relation["source"]
                ) and
                expected_relation["target"] in nodes[edge["target_node_id"]]["label"]
            )]
            self.assertTrue(matches, expected_relation)
            required_confidence = expected_relation.get("required_confidence")
            if required_confidence:
                self.assertTrue(all(
                    edge["provenance"]["confidence"] == required_confidence for edge in matches
                ), expected_relation)
            forbidden_relation = expected_relation.get("forbidden_relation")
            if forbidden_relation:
                self.assertFalse(any(
                    edge["relation"] == forbidden_relation and
                    edge["target_node_id"] == matches[0]["target_node_id"]
                    for edge in new_edges
                ), expected_relation)


if __name__ == "__main__":
    unittest.main()
