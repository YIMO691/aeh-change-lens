from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "schemas"


def load_json(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def load_yaml(relative_path: str) -> dict:
    return yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8"))


def schema_registry() -> Registry:
    resources = []
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        contents = json.loads(path.read_text(encoding="utf-8"))
        resources.append((contents["$id"], Resource.from_contents(contents)))
    return Registry().with_resources(resources)


def validate(schema_name: str, instance: dict) -> None:
    schema = load_json(f"schemas/{schema_name}")
    validator = Draft202012Validator(
        schema,
        registry=schema_registry(),
        format_checker=FormatChecker(),
    )
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    if errors:
        rendered = "\n".join(f"{list(error.path)}: {error.message}" for error in errors)
        raise AssertionError(rendered)


def assert_bundle_semantics(bundle: dict) -> None:
    node_ids: set[str] = set()
    evidence_ids = {item["evidence_id"] for item in bundle["evidence"]}

    if bundle["revisions"]["old"]["role"] != "OLD":
        raise AssertionError("old revision binding must use role OLD")
    if bundle["revisions"]["new"]["role"] != "NEW":
        raise AssertionError("new revision binding must use role NEW")

    for node in bundle["nodes"]:
        if node["node_id"] in node_ids:
            raise AssertionError(f"duplicate node id: {node['node_id']}")
        node_ids.add(node["node_id"])
        if node["revision"] != node["location"]["revision_role"]:
            raise AssertionError(f"mixed revision roles: {node['node_id']}")
        if node["location"]["end_line"] < node["location"]["start_line"]:
            raise AssertionError(f"invalid source range: {node['node_id']}")

    for edge in bundle["edges"]:
        if edge["source_node_id"] not in node_ids or edge["target_node_id"] not in node_ids:
            raise AssertionError(f"dangling edge: {edge['edge_id']}")

    mapping_ids: set[str] = set()
    for mapping in bundle["mappings"]:
        mapping_ids.add(mapping["mapping_id"])
        if mapping["old_node_id"] not in node_ids or mapping["new_node_id"] not in node_ids:
            raise AssertionError(f"dangling mapping: {mapping['mapping_id']}")

    subjects = node_ids | mapping_ids | {edge["edge_id"] for edge in bundle["edges"]}
    for explanation in bundle["explanations"]:
        if not set(explanation["subject_refs"]).issubset(subjects):
            raise AssertionError(f"dangling explanation subject: {explanation['explanation_id']}")
        if not set(explanation["evidence_refs"]).issubset(evidence_ids):
            raise AssertionError(f"dangling evidence reference: {explanation['explanation_id']}")


class JsonSchemaContractTests(unittest.TestCase):
    def test_examples_validate(self) -> None:
        validate("analyzer-request.schema.json", load_json("examples/analyzer-request.json"))
        validate("analyzer-result.schema.json", load_json("examples/analyzer-result.json"))
        bundle = load_json("examples/explain-bundle.json")
        validate("explain-bundle.schema.json", bundle)
        assert_bundle_semantics(bundle)

    def test_analyzer_request_rejects_network_and_execution(self) -> None:
        request = load_json("examples/analyzer-request.json")
        request["policy"]["network_access"] = "ALLOW"
        request["policy"]["execute_project_code"] = True
        with self.assertRaises(AssertionError):
            validate("analyzer-request.schema.json", request)

    def test_analyzer_request_rejects_unbounded_graph(self) -> None:
        request = load_json("examples/analyzer-request.json")
        request["scope"]["relationship_hops"] = 2
        with self.assertRaises(AssertionError):
            validate("analyzer-request.schema.json", request)

    def test_supported_explanation_requires_evidence(self) -> None:
        bundle = load_json("examples/explain-bundle.json")
        bundle["explanations"][0]["evidence_refs"] = []
        with self.assertRaises(AssertionError):
            validate("explain-bundle.schema.json", bundle)

    def test_old_new_location_mix_is_rejected(self) -> None:
        bundle = load_json("examples/explain-bundle.json")
        bundle["nodes"][0]["location"]["revision_role"] = "NEW"
        validate("explain-bundle.schema.json", bundle)
        with self.assertRaisesRegex(AssertionError, "mixed revision roles"):
            assert_bundle_semantics(bundle)

    def test_dangling_mapping_is_rejected(self) -> None:
        bundle = load_json("examples/explain-bundle.json")
        bundle["mappings"][0]["new_node_id"] = "new:missing"
        validate("explain-bundle.schema.json", bundle)
        with self.assertRaisesRegex(AssertionError, "dangling mapping"):
            assert_bundle_semantics(bundle)


class GovernanceContractTests(unittest.TestCase):
    def test_active_work_package_respects_gate_order(self) -> None:
        governance = load_yaml("governance/proposal.yaml")
        status = governance["status"]
        self.assertEqual("GRANTED", status["implementation_authorization"])
        packages = {item["id"]: item for item in governance["work_packages"]}
        active = status["active_work_package"]
        self.assertIn(active, packages)
        self.assertEqual(packages[active]["exit_gate"], status["active_gate"])
        for dependency in packages[active]["depends_on"]:
            self.assertEqual("GATE_PASSED", packages[dependency].get("status"))
        self.assertEqual("owner_chat_instruction", governance["implementation_authorization_evidence"]["source"])

    def test_every_p0_has_one_falsifiable_oracle(self) -> None:
        governance = load_yaml("governance/proposal.yaml")
        oracles = load_yaml("contracts/p0-oracles.yaml")["oracles"]
        self.assertEqual(set(governance["p0_acceptance"]), set(oracles))
        for acceptance_id, oracle in oracles.items():
            self.assertGreater(len(oracle["oracle"]), 30, acceptance_id)
            self.assertIn("planned_evidence", oracle, acceptance_id)

    def test_fixture_covers_gate00_change_classes(self) -> None:
        fixture = load_yaml("fixtures/unity-minimal/expected-change.yaml")
        required = {
            "ADDED", "REMOVED", "UPDATED", "MOVED", "RENAMED", "BRANCH",
            "EXCEPTION", "SIDE_EFFECT", "DYNAMIC_CALL", "STALE",
        }
        self.assertTrue(required.issubset(set(fixture["coverage"])))
        self.assertFalse(fixture["execution_allowed"])

    def test_relation_schema_and_catalog_are_synchronized(self) -> None:
        schema = load_json("schemas/explain-bundle.schema.json")
        schema_relations = set(schema["$defs"]["graph_edge"]["properties"]["relation"]["enum"])
        catalog = load_yaml("contracts/relation-catalog.yaml")
        self.assertEqual(schema_relations, set(catalog["relations"]))
        allowed_confidence = {
            "CONFIRMED_STATIC", "OBSERVED_RUNTIME", "STRUCTURAL", "INFERRED", "UNKNOWN"
        }
        for relation, details in catalog["relations"].items():
            self.assertTrue(set(details["allowed_confidence"]).issubset(allowed_confidence), relation)

    def test_privacy_policy_is_offline_and_non_executing(self) -> None:
        policy = load_yaml("contracts/privacy-export-policy.yaml")
        self.assertEqual("offline", policy["default_mode"])
        self.assertEqual("DENY", policy["network"]["default"])
        self.assertEqual("DENY", policy["network"]["telemetry"])
        self.assertEqual("DENY", policy["execution"]["target_project_code"])
        self.assertEqual("DENY", policy["filesystem"]["aeh_normative_truth_write"])

    def test_dynamic_relations_cannot_be_confirmed_static(self) -> None:
        catalog = load_yaml("contracts/relation-catalog.yaml")["relations"]
        for relation in ("INSPECTOR_BINDING_UNKNOWN", "DYNAMIC_DISPATCH_UNKNOWN"):
            self.assertNotIn("CONFIRMED_STATIC", catalog[relation]["allowed_confidence"])


if __name__ == "__main__":
    unittest.main()
