from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.contract.test_contracts import validate


ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "worker" / "ChangeLens.Analyzer" / "ChangeLens.Analyzer.csproj"
DLL = ROOT / "worker" / "ChangeLens.Analyzer" / "bin" / "Release" / "net8.0" / "ChangeLens.Analyzer.dll"


def source_file(path: Path, logical_path: str) -> dict:
    content = path.read_text(encoding="utf-8")
    return {
        "path": logical_path,
        "content": content,
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


def worker_input() -> dict:
    fixture = ROOT / "fixtures" / "unity-minimal" / "target" / "Assets" / "Scripts" / "Gameplay"
    sources = [
        source_file(ROOT / "tests" / "analyzer" / "UnityStubs.cs", "__stubs__/UnityEngine.cs"),
        source_file(fixture / "RewardController.cs", "Assets/Scripts/Gameplay/RewardController.cs"),
        source_file(fixture / "RewardPolicy.cs", "Assets/Scripts/Gameplay/RewardPolicy.cs"),
        source_file(fixture / "Wallet.cs", "Assets/Scripts/Gameplay/Wallet.cs"),
    ]
    return {
        "schema_version": "1.0.0",
        "request_id": "TEST-UNITY-TARGET",
        "revision": "NEW",
        "unity_context": {
            "completeness": "PARTIAL",
            "unity_version": "2022.3.62f1",
            "defines": ["UNITY_2022_3_OR_NEWER"],
            "references": ["fixture-source-stubs"],
        },
        "source_files": sources,
    }


def run_worker(payload: dict) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as temporary:
        request = Path(temporary) / "request.json"
        request.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return subprocess.run(
            ["dotnet", str(DLL), "--input", str(request)],
            cwd=ROOT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )


class RoslynWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DLL.exists():
            subprocess.run(
                ["dotnet", "build", str(PROJECT), "--configuration", "Release"],
                cwd=ROOT,
                check=True,
            )

    def test_unity_target_emits_bounded_honest_graph(self) -> None:
        payload = worker_input()
        validate("analyzer-worker-input.schema.json", payload)
        completed = run_worker(payload)
        self.assertEqual(0, completed.returncode, completed.stderr)
        result = json.loads(completed.stdout)
        validate("analyzer-result.schema.json", result)
        self.assertEqual("PARTIAL", result["status"])

        nodes = {node["node_id"]: node for node in result["nodes"]}
        edges = result["edges"]
        self.assertTrue(all(
            edge["source_node_id"] in nodes and edge["target_node_id"] in nodes
            for edge in edges
        ))
        relations = {edge["relation"] for edge in edges}
        self.assertTrue({
            "FRAMEWORK_LIFECYCLE", "DIRECT_CALL", "BRANCHES_TO", "THROWS_FROM",
            "RETURNS_FROM", "WRITES_STATE", "INVOKES_UNITY_EVENT",
            "SERIALIZED_REFERENCE", "DYNAMIC_DISPATCH_UNKNOWN",
        }.issubset(relations))

        lifecycle_edges = [edge for edge in edges if edge["relation"] == "FRAMEWORK_LIFECYCLE"]
        self.assertTrue(any("Awake" in nodes[edge["target_node_id"]]["label"] for edge in lifecycle_edges))
        self.assertTrue(all(edge["provenance"]["confidence"] == "STRUCTURAL" for edge in lifecycle_edges))
        self.assertFalse(any(
            edge["relation"] == "DIRECT_CALL" and edge["source_node_id"].startswith("unity:")
            for edge in edges
        ))

        dynamic_edges = [edge for edge in edges if edge["relation"] == "DYNAMIC_DISPATCH_UNKNOWN"]
        self.assertEqual(1, len(dynamic_edges))
        self.assertEqual("UNKNOWN", dynamic_edges[0]["provenance"]["confidence"])
        self.assertEqual("RefreshHud", nodes[dynamic_edges[0]["target_node_id"]]["label"])

        unity_relations = {"FRAMEWORK_LIFECYCLE", "INVOKES_UNITY_EVENT", "SERIALIZED_REFERENCE"}
        self.assertTrue(all(
            edge["provenance"]["confidence"] != "CONFIRMED_STATIC"
            for edge in edges if edge["relation"] in unity_relations
        ))

    def test_content_digest_mismatch_fails_closed(self) -> None:
        payload = worker_input()
        payload["source_files"][1]["content_hash"] = "0" * 64
        completed = run_worker(payload)
        self.assertEqual(2, completed.returncode)
        self.assertEqual("FAILED", json.loads(completed.stderr)["status"])

    def test_caller_cannot_overstate_unity_context(self) -> None:
        payload = worker_input()
        payload["unity_context"]["completeness"] = "COMPLETE"
        completed = run_worker(payload)
        self.assertEqual(0, completed.returncode, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual("PARTIAL", result["capabilities"]["unity_context"])
        unity_relations = {"FRAMEWORK_LIFECYCLE", "INVOKES_UNITY_EVENT", "SERIALIZED_REFERENCE"}
        self.assertTrue(all(
            edge["provenance"]["confidence"] != "CONFIRMED_STATIC"
            for edge in result["edges"] if edge["relation"] in unity_relations
        ))

    def test_worker_rejects_cross_platform_absolute_path(self) -> None:
        payload = worker_input()
        payload["source_files"][1]["path"] = "C:/outside/RewardController.cs"
        completed = run_worker(payload)
        self.assertEqual(2, completed.returncode)
        self.assertEqual("FAILED", json.loads(completed.stderr)["status"])


if __name__ == "__main__":
    unittest.main()
