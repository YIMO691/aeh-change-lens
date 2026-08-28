from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Iterable, Mapping, Sequence


_MAPPING_KINDS = {
    "SAME_SYMBOL", "RENAMED", "MOVED", "RENAMED_AND_MOVED", "HEURISTIC",
}
_SYMBOL_KINDS = {"TYPE", "METHOD"}


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class MappingHint:
    old_label: str
    new_label: str
    kind: str
    basis: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.kind not in _MAPPING_KINDS - {"SAME_SYMBOL"}:
            raise ValueError(f"unsupported explicit mapping kind: {self.kind}")
        if not self.old_label or not self.new_label or not self.basis:
            raise ValueError("mapping hint labels and basis must be non-empty")


@dataclass(frozen=True, slots=True)
class AnalyzerGraphDiff:
    schema_version: str
    status: str
    old_request_id: str
    new_request_id: str
    source_status: dict[str, str]
    nodes: tuple[dict, ...]
    edges: tuple[dict, ...]
    mappings: tuple[dict, ...]
    summary: dict[str, int]
    limitations: tuple[str, ...]
    canonical_digest: str

    def to_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self), ensure_ascii=False))


class AnalyzerGraphDiffer:
    """Compare two bounded Roslyn graphs without inferring hidden intent."""

    def compare(
        self,
        old_result: Mapping[str, object],
        new_result: Mapping[str, object],
        *,
        renames: Iterable[object] = (),
        mapping_hints: Sequence[MappingHint] = (),
        stable_symbol_confidence: str = "CONFIRMED_STATIC",
    ) -> AnalyzerGraphDiff:
        if stable_symbol_confidence not in {"CONFIRMED_STATIC", "STRUCTURAL"}:
            raise ValueError("stable symbol confidence must be CONFIRMED_STATIC or STRUCTURAL")
        old_nodes, old_edges = self._validate_result(old_result, "OLD")
        new_nodes, new_edges = self._validate_result(new_result, "NEW")
        rename_map = self._rename_map(renames)
        old_to_new: dict[str, str] = {}
        new_to_old: dict[str, str] = {}
        mappings: list[dict] = []
        mapping_changes: dict[str, str] = {}
        limitations: list[str] = []

        def add_mapping(
            old_node: dict,
            new_node: dict,
            kind: str,
            confidence: str,
            basis: list[str],
            initial_change: str,
        ) -> None:
            old_id = old_node["node_id"]
            new_id = new_node["node_id"]
            if old_id in old_to_new or new_id in new_to_old:
                raise ValueError(f"mapping is not one-to-one: {old_id} -> {new_id}")
            old_to_new[old_id] = new_id
            new_to_old[new_id] = old_id
            mapping_hash = hashlib.sha256(f"{old_id}\0{new_id}".encode("utf-8")).hexdigest()[:24]
            mapping_id = f"mapping:{mapping_hash}"
            mappings.append({
                "mapping_id": mapping_id,
                "old_node_id": old_id,
                "new_node_id": new_id,
                "kind": kind,
                "confidence": confidence,
                "basis": sorted(set(basis)),
                "alternatives": [],
            })
            mapping_changes[mapping_id] = initial_change

        old_symbols = self._group(old_nodes.values(), self._stable_symbol_key)
        new_symbols = self._group(new_nodes.values(), self._stable_symbol_key)
        for key in sorted(set(old_symbols) & set(new_symbols), key=str):
            if key is None:
                continue
            old_candidates = old_symbols[key]
            new_candidates = new_symbols[key]
            if len(old_candidates) != 1 or len(new_candidates) != 1:
                limitations.append(f"稳定符号键存在重复候选，未自动映射：{key}")
                continue
            old_node, new_node = old_candidates[0], new_candidates[0]
            moved = old_node["location"]["path"] != new_node["location"]["path"]
            add_mapping(
                old_node,
                new_node,
                "MOVED" if moved else "SAME_SYMBOL",
                stable_symbol_confidence,
                ["roslyn_symbol_identity", "source_path_changed" if moved else "same_qualified_symbol"],
                "MOVED" if moved else "UNCHANGED_CONTEXT",
            )

        for hint in mapping_hints:
            old_node = self._unique_label(old_nodes, hint.old_label, old_to_new, "old")
            new_node = self._unique_label(new_nodes, hint.new_label, new_to_old, "new")
            add_mapping(
                old_node,
                new_node,
                hint.kind,
                "STRUCTURAL",
                list(hint.basis),
                "MOVED" if hint.kind in {"MOVED", "RENAMED_AND_MOVED"} else "UPDATED",
            )

        unmatched_old = [node for node_id, node in old_nodes.items() if node_id not in old_to_new]
        unmatched_new = [node for node_id, node in new_nodes.items() if node_id not in new_to_old]
        old_structural = self._group(
            unmatched_old, lambda node: self._structural_key(node, rename_map, old=True)
        )
        new_structural = self._group(
            unmatched_new, lambda node: self._structural_key(node, rename_map, old=False)
        )
        for key in sorted(set(old_structural) & set(new_structural), key=str):
            old_candidates = old_structural[key]
            new_candidates = new_structural[key]
            if len(old_candidates) == 1 and len(new_candidates) == 1:
                add_mapping(
                    old_candidates[0], new_candidates[0], "HEURISTIC", "STRUCTURAL",
                    ["unique_kind_label_path"],
                    "UNCHANGED_CONTEXT",
                )
            else:
                limitations.append(
                    f"结构签名存在歧义，保留为新增/删除而不猜测：{key} "
                    f"(OLD={len(old_candidates)}, NEW={len(new_candidates)})"
                )

        old_changes = {node_id: "REMOVED" for node_id in old_nodes}
        new_changes = {node_id: "ADDED" for node_id in new_nodes}
        for mapping in mappings:
            change = mapping_changes[mapping["mapping_id"]]
            old_changes[mapping["old_node_id"]] = change
            new_changes[mapping["new_node_id"]] = change

        matched_old_edges: set[str] = set()
        matched_new_edges: set[str] = set()
        old_edge_groups: dict[tuple[str, str, str], list[dict]] = {}
        for edge in old_edges.values():
            source = old_to_new.get(edge["source_node_id"])
            target = old_to_new.get(edge["target_node_id"])
            if source is not None and target is not None:
                old_edge_groups.setdefault((edge["relation"], source, target), []).append(edge)
        new_edge_groups = self._group(
            new_edges.values(),
            lambda edge: (edge["relation"], edge["source_node_id"], edge["target_node_id"]),
        )
        for key in sorted(set(old_edge_groups) & set(new_edge_groups), key=str):
            old_candidates = old_edge_groups[key]
            new_candidates = new_edge_groups[key]
            if len(old_candidates) == 1 and len(new_candidates) == 1:
                matched_old_edges.add(old_candidates[0]["edge_id"])
                matched_new_edges.add(new_candidates[0]["edge_id"])
            else:
                limitations.append(f"关系映射存在歧义，未合并：{key}")

        old_edge_changes = {
            edge_id: "UNCHANGED_CONTEXT" if edge_id in matched_old_edges else "REMOVED"
            for edge_id in old_edges
        }
        new_edge_changes = {
            edge_id: "UNCHANGED_CONTEXT" if edge_id in matched_new_edges else "ADDED"
            for edge_id in new_edges
        }
        self._propagate_edge_changes(
            old_edges, old_edge_changes, old_changes, new_changes, old_to_new
        )
        self._propagate_edge_changes(
            new_edges, new_edge_changes, new_changes, old_changes, new_to_old
        )

        rendered_nodes = tuple(sorted(
            [self._with_change(node, old_changes[node_id]) for node_id, node in old_nodes.items()] +
            [self._with_change(node, new_changes[node_id]) for node_id, node in new_nodes.items()],
            key=lambda item: item["node_id"],
        ))
        rendered_edges = tuple(sorted(
            [self._with_change(edge, old_edge_changes[edge_id]) for edge_id, edge in old_edges.items()] +
            [self._with_change(edge, new_edge_changes[edge_id]) for edge_id, edge in new_edges.items()],
            key=lambda item: item["edge_id"],
        ))
        mappings_tuple = tuple(sorted(mappings, key=lambda item: item["mapping_id"]))
        summary = {
            "old_nodes": len(old_nodes),
            "new_nodes": len(new_nodes),
            "mapped_nodes": len(mappings_tuple),
            "added_nodes": sum(value == "ADDED" for value in new_changes.values()),
            "removed_nodes": sum(value == "REMOVED" for value in old_changes.values()),
            "updated_node_pairs": sum(
                old_changes[item["old_node_id"]] == "UPDATED" for item in mappings_tuple
            ),
            "moved_node_pairs": sum(
                old_changes[item["old_node_id"]] == "MOVED" for item in mappings_tuple
            ),
            "added_edges": sum(value == "ADDED" for value in new_edge_changes.values()),
            "removed_edges": sum(value == "REMOVED" for value in old_edge_changes.values()),
            "unchanged_edge_pairs": len(matched_old_edges),
        }
        old_status = str(old_result["status"])
        new_status = str(new_result["status"])
        status = "COMPLETE" if old_status == new_status == "COMPLETE" and not limitations else "PARTIAL"
        semantic = {
            "schema_version": "1.0.0",
            "status": status,
            "old_request_id": str(old_result["request_id"]),
            "new_request_id": str(new_result["request_id"]),
            "source_status": {"old": old_status, "new": new_status},
            "nodes": list(rendered_nodes),
            "edges": list(rendered_edges),
            "mappings": list(mappings_tuple),
            "summary": summary,
            "limitations": sorted(set(limitations)),
        }
        return AnalyzerGraphDiff(
            schema_version="1.0.0",
            status=status,
            old_request_id=str(old_result["request_id"]),
            new_request_id=str(new_result["request_id"]),
            source_status={"old": old_status, "new": new_status},
            nodes=rendered_nodes,
            edges=rendered_edges,
            mappings=mappings_tuple,
            summary=summary,
            limitations=tuple(semantic["limitations"]),
            canonical_digest=_canonical_digest(semantic),
        )

    @staticmethod
    def _validate_result(result: Mapping[str, object], role: str) -> tuple[dict[str, dict], dict[str, dict]]:
        if result.get("status") not in {"COMPLETE", "PARTIAL"}:
            raise ValueError(f"{role} analyzer result is not comparable")
        if not isinstance(result.get("request_id"), str) or not result["request_id"]:
            raise ValueError(f"{role} analyzer result has no request_id")
        raw_nodes = result.get("nodes")
        raw_edges = result.get("edges")
        if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
            raise ValueError(f"{role} analyzer result has invalid graph arrays")
        nodes: dict[str, dict] = {}
        for raw_node in raw_nodes:
            if not isinstance(raw_node, dict) or raw_node.get("revision") != role:
                raise ValueError(f"{role} graph contains a mixed-revision node")
            location = raw_node.get("location")
            if not isinstance(location, dict) or location.get("revision_role") != role:
                raise ValueError(f"{role} graph contains a mixed-revision node location")
            if not isinstance(raw_node.get("kind"), str) or not isinstance(raw_node.get("label"), str):
                raise ValueError(f"{role} graph contains an incomplete node")
            node_id = raw_node.get("node_id")
            if not isinstance(node_id, str) or node_id in nodes:
                raise ValueError(f"{role} graph contains an invalid or duplicate node id")
            nodes[node_id] = copy.deepcopy(raw_node)
        edges: dict[str, dict] = {}
        for raw_edge in raw_edges:
            if not isinstance(raw_edge, dict) or raw_edge.get("revision") != role:
                raise ValueError(f"{role} graph contains a mixed-revision edge")
            if not isinstance(raw_edge.get("relation"), str):
                raise ValueError(f"{role} graph contains an incomplete edge")
            edge_id = raw_edge.get("edge_id")
            if not isinstance(edge_id, str) or edge_id in edges:
                raise ValueError(f"{role} graph contains an invalid or duplicate edge id")
            if raw_edge.get("source_node_id") not in nodes or raw_edge.get("target_node_id") not in nodes:
                raise ValueError(f"{role} graph contains a dangling edge: {edge_id}")
            edges[edge_id] = copy.deepcopy(raw_edge)
        return nodes, edges

    @staticmethod
    def _stable_symbol_key(node: dict) -> tuple[str, str] | None:
        if node.get("kind") not in _SYMBOL_KINDS:
            return None
        node_id = node.get("node_id", "")
        parts = node_id.split(":", 2)
        if len(parts) != 3 or parts[0] != "csharp" or parts[1] not in {"OLD", "NEW"}:
            return None
        return node["kind"], parts[2]

    @staticmethod
    def _rename_map(renames: Iterable[object]) -> dict[str, str]:
        result: dict[str, str] = {}
        for item in renames:
            old_path = item.get("old_path") if isinstance(item, Mapping) else getattr(item, "old_path", None)
            new_path = item.get("new_path") if isinstance(item, Mapping) else getattr(item, "new_path", None)
            if not isinstance(old_path, str) or not isinstance(new_path, str):
                raise ValueError("rename entries require old_path and new_path")
            if old_path in result and result[old_path] != new_path:
                raise ValueError(f"conflicting rename target: {old_path}")
            result[old_path] = new_path
        return result

    @staticmethod
    def _structural_key(node: dict, rename_map: Mapping[str, str], *, old: bool) -> tuple[str, str, str]:
        path = node["location"]["path"]
        normalized_path = rename_map.get(path, path) if old else path
        return node["kind"], node["label"], normalized_path

    @staticmethod
    def _group(items: Iterable[dict], key_function) -> dict[object, list[dict]]:
        groups: dict[object, list[dict]] = {}
        for item in items:
            key = key_function(item)
            groups.setdefault(key, []).append(item)
        return groups

    @staticmethod
    def _unique_label(
        nodes: Mapping[str, dict], label: str, already_mapped: Mapping[str, str], side: str
    ) -> dict:
        candidates = [
            node for node_id, node in nodes.items()
            if node["label"] == label and node_id not in already_mapped
        ]
        if len(candidates) != 1:
            raise ValueError(
                f"explicit {side} mapping label must resolve exactly once: {label} "
                f"(found {len(candidates)})"
            )
        return candidates[0]

    @staticmethod
    def _with_change(item: dict, change: str) -> dict:
        rendered = copy.deepcopy(item)
        rendered["change"] = change
        return rendered

    @staticmethod
    def _propagate_edge_changes(
        edges: Mapping[str, dict],
        edge_changes: Mapping[str, str],
        own_node_changes: dict[str, str],
        peer_node_changes: dict[str, str],
        node_mapping: Mapping[str, str],
    ) -> None:
        for edge_id, edge in edges.items():
            if edge_changes[edge_id] == "UNCHANGED_CONTEXT":
                continue
            for node_id in (edge["source_node_id"], edge["target_node_id"]):
                peer = node_mapping.get(node_id)
                if peer is not None and own_node_changes[node_id] == "UNCHANGED_CONTEXT":
                    own_node_changes[node_id] = "UPDATED"
                    if peer_node_changes[peer] == "UNCHANGED_CONTEXT":
                        peer_node_changes[peer] = "UPDATED"
