from __future__ import annotations

import hashlib
import html
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Mapping, Sequence


_RELATION_ZH = {
    "DIRECT_CALL": "直接调用",
    "FRAMEWORK_LIFECYCLE": "Unity 生命周期调度",
    "STARTS_COROUTINE": "启动协程",
    "YIELDS_TO": "协程等待",
    "AWAITS": "异步等待",
    "SUBSCRIBES_EVENT": "订阅事件",
    "PUBLISHES_EVENT": "发布事件",
    "INVOKES_UNITY_EVENT": "触发 UnityEvent",
    "INSPECTOR_BINDING_UNKNOWN": "Inspector 绑定（目标未知）",
    "BRANCHES_TO": "条件分支",
    "RETURNS_FROM": "返回",
    "THROWS_FROM": "抛出异常",
    "READS_STATE": "读取状态",
    "WRITES_STATE": "写入状态",
    "SERIALIZED_REFERENCE": "序列化引用",
    "COMPONENT_LOOKUP": "查找组件",
    "DYNAMIC_DISPATCH_UNKNOWN": "动态调用（目标未知）",
}

_CHANGE_ZH = {
    "ADDED": "新增",
    "REMOVED": "删除",
    "UPDATED": "修改",
    "MOVED": "移动",
    "UNCHANGED_CONTEXT": "上下文",
    "RENAMED": "重命名",
    "RENAMED_AND_MOVED": "重命名并移动",
    "HEURISTIC": "结构匹配",
    "SAME_SYMBOL": "同一符号",
}

_CHANGE_EN = {
    "ADDED": "Added",
    "REMOVED": "Removed",
    "UPDATED": "Updated",
    "MOVED": "Moved",
    "UNCHANGED_CONTEXT": "Context",
    "RENAMED": "Renamed",
    "RENAMED_AND_MOVED": "Renamed and moved",
    "HEURISTIC": "Structural match",
    "SAME_SYMBOL": "Same symbol",
}

_MAX_RELATIONSHIPS = 80
_MAX_CHAINS = 16
_MAX_CHAIN_HOPS = 8
_MAX_QUICK_CARDS = 5
_MAX_FLOW_STEPS = 8
_MAX_STAGE_ITEMS = 6
_MAX_DECISIONS = 6

_AREA_ORDER = {
    "CONFIGURATION": 0,
    "SERVER": 1,
    "PROTOCOL": 2,
    "CLIENT": 3,
    "RUNTIME": 4,
    "TEST": 5,
    "GENERATED": 6,
}

_AREA_LABELS = {
    "CONFIGURATION": ("配置与规则", "Configuration and rules", "📋"),
    "SERVER": ("服务端编排", "Server orchestration", "🧠"),
    "PROTOCOL": ("协议与数据", "Protocol and data", "🛰️"),
    "CLIENT": ("客户端表现", "Client behavior", "🎮"),
    "RUNTIME": ("运行逻辑", "Runtime logic", "⚙️"),
    "TEST": ("测试保障", "Test coverage", "🧪"),
    "GENERATED": ("生成代码", "Generated code", "🧩"),
}


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be a non-empty string without NUL")
    return value.strip()


class ChangeStoryBuilder:
    """Project a revision analysis into a deterministic, human-facing story.

    The builder never claims access to hidden model reasoning. Code facts, supplied
    source statements, and deterministic intent hypotheses remain separate layers.
    """

    def build(
        self,
        analysis: Mapping[str, object],
        *,
        title: str = "代码修改逻辑链路",
        intent_evidence: Mapping[str, object] | None = None,
    ) -> dict:
        title = _non_empty_string(title, "title")
        diff, nodes, edges, mappings = self._validate_analysis(analysis)
        analysis_digest = _non_empty_string(analysis.get("canonical_digest"), "analysis digest")
        limitations = list(self._string_list(analysis.get("limitations", []), "limitations"))

        lanes: dict[str, dict] = {}
        relationships_truncated = False
        for role, key, label_zh, label_en in (
            ("OLD", "old", "原链路", "Old path"),
            ("NEW", "new", "新链路", "New path"),
        ):
            relationships, was_truncated = self._relationships(role, nodes, edges)
            relationships_truncated = relationships_truncated or was_truncated
            chains, chains_truncated = self._chains(role, relationships)
            if chains_truncated:
                limitations.append(
                    f"{label_zh}超过 {_MAX_CHAINS} 条链或单链 {_MAX_CHAIN_HOPS} 个 hop，报告已确定性截断。"
                )
            lanes[key] = {
                "role": role,
                "label_zh": label_zh,
                "label_en": label_en,
                "chains": chains,
                "relationships": relationships,
            }
        if relationships_truncated:
            limitations.append(
                f"报告每个版本最多展示 {_MAX_RELATIONSHIPS} 条聚焦关系；完整关系仍保留在分析 JSON。"
            )

        changes = self._changes(nodes, edges, mappings)
        claims = self._code_fact_claims(diff, nodes, edges, mappings)
        source_claims = self._source_claims(intent_evidence)
        claims.extend(source_claims)
        claims.extend(self._intent_inferences(edges, mappings, nodes))
        if not source_claims:
            limitations.append(
                "未提供用户需求、AI 计划或提交说明；“为什么修改”仅能显示明确标注的代码模式推断。"
            )
        limitations.append(
            "报告不读取或还原模型隐藏思维链；意图推断不是 AI 真实思考过程的证明。"
        )

        summary = dict(diff["summary"])
        quick_view, deep_dive = self._story_views(
            analysis=analysis,
            nodes=nodes,
            edges=edges,
            mappings=mappings,
            source_claims=source_claims,
        )
        semantic = {
            "schema_version": "1.1.0",
            "story_id": f"story:{analysis_digest[:24]}",
            "language": "zh-CN",
            "status": str(analysis["status"]),
            "title": title,
            "analysis_digest": analysis_digest,
            "revisions": analysis["revisions"],
            "overview": {
                "headline_zh": quick_view["summary_zh"],
                "headline_en": quick_view["summary_en"],
                "counts": summary,
            },
            "quick_view": quick_view,
            "deep_dive": deep_dive,
            "lanes": lanes,
            "changes": changes,
            "claims": sorted(claims, key=lambda item: item["claim_id"]),
            "impacts": self._impacts(nodes, edges),
            "limitations": sorted(set(limitations)),
        }
        return {**semantic, "canonical_digest": _canonical_digest(semantic)}

    @staticmethod
    def _validate_analysis(analysis: Mapping[str, object]) -> tuple[dict, dict[str, dict], list[dict], list[dict]]:
        if not isinstance(analysis, Mapping):
            raise ValueError("change analysis must be an object")
        if analysis.get("schema_version") != "1.0.0":
            raise ValueError("unsupported change analysis schema version")
        if analysis.get("status") not in {"FRESH", "PARTIAL"}:
            raise ValueError("change analysis status is not reportable")
        revisions = analysis.get("revisions")
        if not isinstance(revisions, Mapping):
            raise ValueError("change analysis revisions are missing")
        if not isinstance(revisions.get("old"), Mapping) or revisions["old"].get("role") != "OLD":
            raise ValueError("old revision binding is invalid")
        if not isinstance(revisions.get("new"), Mapping) or revisions["new"].get("role") != "NEW":
            raise ValueError("new revision binding is invalid")
        diff = analysis.get("diff")
        if not isinstance(diff, dict):
            raise ValueError("change analysis diff is missing")
        raw_nodes, raw_edges, raw_mappings = diff.get("nodes"), diff.get("edges"), diff.get("mappings")
        if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list) or not isinstance(raw_mappings, list):
            raise ValueError("change analysis diff collections are invalid")
        summary = diff.get("summary")
        required_counts = {
            "old_nodes", "new_nodes", "mapped_nodes", "added_nodes", "removed_nodes",
            "updated_node_pairs", "moved_node_pairs", "added_edges", "removed_edges",
            "unchanged_edge_pairs",
        }
        if not isinstance(summary, dict) or not required_counts.issubset(summary):
            raise ValueError("change analysis summary is invalid")
        nodes: dict[str, dict] = {}
        for node in raw_nodes:
            if not isinstance(node, dict) or not isinstance(node.get("node_id"), str):
                raise ValueError("change analysis contains an invalid node")
            if node["node_id"] in nodes:
                raise ValueError(f"duplicate node id: {node['node_id']}")
            nodes[node["node_id"]] = node
        for edge in raw_edges:
            if not isinstance(edge, dict) or edge.get("source_node_id") not in nodes or edge.get("target_node_id") not in nodes:
                raise ValueError("change analysis contains a dangling edge")
        for mapping in raw_mappings:
            if not isinstance(mapping, dict) or mapping.get("old_node_id") not in nodes or mapping.get("new_node_id") not in nodes:
                raise ValueError("change analysis contains a dangling mapping")
        return diff, nodes, raw_edges, raw_mappings

    @staticmethod
    def _string_list(value: object, name: str) -> tuple[str, ...]:
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            raise ValueError(f"{name} must be a string array")
        return tuple(value)

    @staticmethod
    def _node_projection(node: Mapping[str, object]) -> dict:
        location = node.get("location")
        provenance = node.get("provenance")
        if not isinstance(location, dict) or not isinstance(provenance, dict):
            raise ValueError("node location/provenance is invalid")
        return {
            "node_id": node["node_id"],
            "label": node["label"],
            "kind": node["kind"],
            "change": node["change"],
            "location": location,
            "confidence": provenance["confidence"],
        }

    def _relationships(
        self, role: str, nodes: Mapping[str, dict], edges: Sequence[dict]
    ) -> tuple[list[dict], bool]:
        selected = []
        for edge in edges:
            if edge.get("revision") != role:
                continue
            source, target = nodes[edge["source_node_id"]], nodes[edge["target_node_id"]]
            if (
                edge.get("change") == "UNCHANGED_CONTEXT"
                and source.get("change") == "UNCHANGED_CONTEXT"
                and target.get("change") == "UNCHANGED_CONTEXT"
            ):
                continue
            provenance = edge.get("provenance")
            if not isinstance(provenance, dict):
                raise ValueError("edge provenance is invalid")
            selected.append({
                "edge_id": edge["edge_id"],
                "source": self._node_projection(source),
                "target": self._node_projection(target),
                "relation": edge["relation"],
                "relation_zh": _RELATION_ZH.get(edge["relation"], edge["relation"]),
                "change": edge["change"],
                "confidence": provenance["confidence"],
            })
        selected.sort(key=lambda item: (
            item["source"]["location"]["path"], item["source"]["location"]["start_line"],
            item["relation"], item["target"]["label"], item["edge_id"],
        ))
        return selected[:_MAX_RELATIONSHIPS], len(selected) > _MAX_RELATIONSHIPS

    def _chains(self, role: str, relationships: Sequence[dict]) -> tuple[list[dict], bool]:
        adjacency: dict[str, list[dict]] = {}
        targets: set[str] = set()
        node_values: dict[str, dict] = {}
        for relationship in relationships:
            source, target = relationship["source"], relationship["target"]
            node_values[source["node_id"]] = source
            node_values[target["node_id"]] = target
            adjacency.setdefault(source["node_id"], []).append(relationship)
            targets.add(target["node_id"])
        for values in adjacency.values():
            values.sort(key=lambda item: (item["relation"], item["target"]["label"], item["edge_id"]))
        roots = sorted((set(adjacency) - targets), key=lambda item: (node_values[item]["label"], item))
        if not roots:
            roots = sorted(adjacency, key=lambda item: (node_values[item]["label"], item))
        chains: list[dict] = []
        truncated = False

        def visit(node_id: str, path_nodes: list[dict], path_relations: list[dict], seen: set[str]) -> None:
            nonlocal truncated
            if len(chains) >= _MAX_CHAINS:
                truncated = True
                return
            outgoing = [item for item in adjacency.get(node_id, []) if item["target"]["node_id"] not in seen]
            if not outgoing or len(path_relations) >= _MAX_CHAIN_HOPS:
                if outgoing:
                    truncated = True
                if path_relations:
                    identity = "\0".join(item["edge_id"] for item in path_relations)
                    chains.append({
                        "chain_id": f"chain:{role.lower()}:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}",
                        "nodes": path_nodes,
                        "relations": [{
                            "edge_id": item["edge_id"],
                            "relation": item["relation"],
                            "relation_zh": item["relation_zh"],
                            "change": item["change"],
                            "confidence": item["confidence"],
                        } for item in path_relations],
                    })
                return
            for relationship in outgoing:
                target = relationship["target"]
                visit(
                    target["node_id"], path_nodes + [target], path_relations + [relationship],
                    seen | {target["node_id"]},
                )

        for root in roots:
            visit(root, [node_values[root]], [], {root})
            if len(chains) >= _MAX_CHAINS:
                if root != roots[-1]:
                    truncated = True
                break
        return chains, truncated

    def _changes(self, nodes: Mapping[str, dict], edges: Sequence[dict], mappings: Sequence[dict]) -> list[dict]:
        changes: list[dict] = []
        mapped_nodes: set[str] = set()
        for mapping in sorted(mappings, key=lambda item: item["mapping_id"]):
            old, new = nodes[mapping["old_node_id"]], nodes[mapping["new_node_id"]]
            mapped_nodes.update((old["node_id"], new["node_id"]))
            if (
                old.get("change") == "UNCHANGED_CONTEXT"
                and mapping.get("kind") not in {"RENAMED", "MOVED", "RENAMED_AND_MOVED"}
            ):
                continue
            kind = (
                mapping["kind"]
                if mapping["kind"] in {"RENAMED", "MOVED", "RENAMED_AND_MOVED"}
                else old["change"]
            )
            changes.append({
                "change_id": mapping["mapping_id"], "kind": kind,
                "subject_zh": f"{old['label']} → {new['label']}",
                "subject_en": f"{old['label']} → {new['label']}",
                "confidence": mapping["confidence"],
                "evidence_refs": [mapping["mapping_id"], old["node_id"], new["node_id"]],
                "locations": [old["location"], new["location"]],
            })
        for node in sorted(nodes.values(), key=lambda item: item["node_id"]):
            if node["node_id"] in mapped_nodes or node.get("change") not in {"ADDED", "REMOVED"}:
                continue
            changes.append({
                "change_id": f"change:{node['node_id']}", "kind": node["change"],
                "subject_zh": node["label"], "subject_en": node["label"],
                "confidence": node["provenance"]["confidence"],
                "evidence_refs": [node["node_id"]], "locations": [node["location"]],
            })
        return changes[:120]

    @staticmethod
    def _area(node: Mapping[str, object]) -> str:
        location = node.get("location")
        path = str(location.get("path", "") if isinstance(location, Mapping) else "")
        normalized = "/" + path.replace("\\", "/").lower().strip("/") + "/"
        if "/tests/" in normalized or "/test/" in normalized:
            return "TEST"
        if any(token in normalized for token in ("/config/", "/configpartial/", "config.cs/")):
            return "CONFIGURATION"
        if any(token in normalized for token in ("/message/", "outermessage", ".proto/", "/proto/", "opcode")):
            return "PROTOCOL"
        if "/generate/" in normalized or "/generated/" in normalized:
            return "GENERATED"
        if normalized.startswith("/server/") or "/server/" in normalized:
            return "SERVER"
        if normalized.startswith("/unity/") or any(
            token in normalized for token in ("/client/", "/hotfixview/", "/assets/")
        ):
            return "CLIENT"
        return "RUNTIME"

    @staticmethod
    def _short_label(value: object) -> str:
        label = str(value)
        return re.sub(r"^(?:global::)?(?:ET|Game|ChangeLens\.Fixture)\.", "", label)

    @classmethod
    def _compact_label(cls, value: object) -> str:
        label = cls._short_label(value)
        if "(" in label:
            head = label.split("(", 1)[0]
            parts = head.split(".")
            return f"{'.'.join(parts[-2:])}()"
        return label.rsplit(".", 1)[-1]

    @classmethod
    def _headline_label(cls, value: object) -> str:
        label = cls._compact_label(value)
        return label.rsplit(".", 1)[-1]

    @classmethod
    def _label_tokens(cls, value: object) -> set[str]:
        label = cls._short_label(value)
        words = re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|\d+", label)
        ignored = {
            "system", "component", "category", "config", "helper", "program", "unit",
            "get", "set", "create", "resolve", "validate", "build", "try", "on", "by",
            "list", "generic", "int", "float", "string", "vector", "void", "bool",
            "random", "bullet", "data", "info", "index", "count", "active", "display",
        }
        return {word.lower() for word in words if len(word) > 2 and word.lower() not in ignored}

    def _node_score(self, node: Mapping[str, object], changed_degree: int = 0) -> int:
        score = {
            "ADDED": 12,
            "REMOVED": 11,
            "UPDATED": 10,
            "MOVED": 9,
            "UNCHANGED_CONTEXT": -8,
        }.get(str(node.get("change")), 0)
        score += {
            "METHOD": 7,
            "TYPE": 5,
            "STATE": 3,
            "EVENT": 3,
            "CONDITION": 1,
        }.get(str(node.get("kind")), 0)
        label = str(node.get("label", ""))
        if re.search(r"(?:^|\.)(?:Try|On|Handle|Execute|Create|Resolve|Validate|Load|Send|Broadcast|GetRandom)", label):
            score += 4
        if re.search(r"(?:^|\.)(?:On|Handle|Execute)[A-Z]", label):
            score += 3
        if re.search(r"(?:^|\.)Try[A-Z]", label):
            score += 2
        area = self._area(node)
        if area == "GENERATED":
            score -= 12
        elif area == "TEST":
            score -= 7
        elif area in {"CONFIGURATION", "SERVER", "PROTOCOL", "CLIENT"}:
            score += 3
        return score + min(changed_degree, 5)

    def _focus_nodes(
        self, nodes: Mapping[str, dict], edges: Sequence[dict]
    ) -> list[dict]:
        degree: dict[str, int] = {}
        for edge in edges:
            if edge.get("change") == "UNCHANGED_CONTEXT":
                continue
            for key in ("source_node_id", "target_node_id"):
                node_id = edge.get(key)
                if isinstance(node_id, str):
                    degree[node_id] = degree.get(node_id, 0) + 1
        selected = [
            node for node in nodes.values()
            if node.get("change") != "UNCHANGED_CONTEXT"
        ]
        selected.sort(key=lambda node: (
            -self._node_score(node, degree.get(str(node["node_id"]), 0)),
            _AREA_ORDER[self._area(node)],
            str(node.get("label", "")),
            str(node.get("node_id", "")),
        ))
        return selected

    def _change_cards(self, focus_nodes: Sequence[dict], topic_tokens: set[str]) -> list[dict]:
        grouped: dict[str, list[dict]] = {}
        for node in focus_nodes:
            grouped.setdefault(self._area(node), []).append(node)
        ranked_areas = sorted(
            grouped,
            key=lambda area: (
                -sum(max(self._node_score(node), 0) for node in grouped[area][:8]),
                _AREA_ORDER[area],
            ),
        )
        non_generated = [area for area in ranked_areas if area != "GENERATED"]
        if non_generated:
            ranked_areas = non_generated
        cards: list[dict] = []
        for area in ranked_areas[:_MAX_QUICK_CARDS]:
            candidates = grouped[area]
            minimum_overlap = 1 if area == "TEST" else 2
            topic_candidates = [
                node for node in candidates
                if len(self._label_tokens(node["label"]) & topic_tokens) >= minimum_overlap
            ]
            if topic_candidates:
                candidates = topic_candidates
            unique: list[dict] = []
            seen: set[str] = set()
            for node in candidates:
                label = self._short_label(node["label"])
                if label in seen or node.get("kind") in {"CONDITION", "RETURN"}:
                    continue
                seen.add(label)
                unique.append(node)
                if len(unique) == 3:
                    break
            if not unique:
                unique = candidates[:2]
            names = "、".join(self._headline_label(node["label"]) for node in unique)
            label_zh, label_en, icon = _AREA_LABELS[area]
            cards.append({
                "card_id": f"card:{area.lower()}",
                "area": area,
                "icon": icon,
                "title_zh": label_zh,
                "title_en": label_en,
                "summary_zh": f"重点包括 {names}；完整数量与语法细节已折叠。",
                "summary_en": f"Key changed symbols: {', '.join(self._headline_label(node['label']) for node in unique)}; full counts and syntax details are collapsed.",
                "evidence_refs": [str(node["node_id"]) for node in unique],
                "locations": [node["location"] for node in unique],
            })
        return cards

    def _context_change_cards(
        self,
        nodes: Mapping[str, dict],
        mappings: Sequence[dict],
        focus_nodes: Sequence[dict],
        existing_areas: set[str],
    ) -> list[dict]:
        focus_text = " ".join(str(node.get("label", "")) for node in focus_nodes)
        candidates: dict[str, tuple[dict, dict]] = {}
        for mapping in mappings:
            old = nodes[mapping["old_node_id"]]
            new = nodes[mapping["new_node_id"]]
            old_location, new_location = old.get("location"), new.get("location")
            if not isinstance(old_location, Mapping) or not isinstance(new_location, Mapping):
                continue
            area = self._area(new)
            if area in existing_areas or area == "GENERATED" or new.get("kind") != "TYPE":
                continue
            if old_location.get("content_hash") == new_location.get("content_hash"):
                continue
            simple_name = self._compact_label(new["label"])
            if simple_name not in focus_text:
                continue
            candidates.setdefault(area, (mapping, new))
        cards = []
        for area in sorted(candidates, key=lambda item: _AREA_ORDER[item]):
            mapping, node = candidates[area]
            label_zh, label_en, icon = _AREA_LABELS[area]
            name = self._compact_label(node["label"])
            cards.append({
                "card_id": f"card:{area.lower()}-context",
                "area": area,
                "icon": icon,
                "title_zh": label_zh,
                "title_en": label_en,
                "summary_zh": f"相关文件内容发生变化，业务上下文包括 {name}；字段级差异需展开证据查看。",
                "summary_en": f"A related file changed around {name}; expand the evidence for field-level details.",
                "evidence_refs": [mapping["mapping_id"], node["node_id"]],
                "locations": [node["location"]],
            })
        return cards

    def _flow_steps(
        self, role: str, focus_nodes: Sequence[dict], topic_tokens: set[str]
    ) -> list[dict]:
        candidates = [node for node in focus_nodes if node.get("revision") == role]
        grouped: dict[str, list[dict]] = {}
        for node in candidates:
            area = self._area(node)
            if area in {"GENERATED", "TEST"}:
                continue
            grouped.setdefault(area, []).append(node)
        steps: list[dict] = []
        for area in sorted(grouped, key=lambda item: _AREA_ORDER[item]):
            picked: list[dict] = []
            seen: set[str] = set()
            area_candidates = [
                node for node in grouped[area]
                if len(self._label_tokens(node["label"]) & topic_tokens) >= 2
            ]
            area_limit = 4 if role == "NEW" and area == "SERVER" else 2
            for node in area_candidates:
                if node.get("kind") not in {"METHOD", "TYPE", "EVENT", "STATE"}:
                    continue
                label = self._compact_label(node["label"])
                if label in seen:
                    continue
                seen.add(label)
                picked.append(node)
                if len(picked) == area_limit:
                    break
            picked.sort(key=lambda node: (
                str(node["location"]["path"]), int(node["location"]["start_line"]),
                str(node["node_id"]),
            ))
            for node in picked:
                label_zh, label_en, _ = _AREA_LABELS[area]
                identity = f"{role}:{node['node_id']}"
                steps.append({
                    "step_id": f"flow:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}",
                    "order": len(steps) + 1,
                    "area": area,
                    "area_label_zh": label_zh,
                    "area_label_en": label_en,
                    "label": self._compact_label(node["label"]),
                    "kind": node["kind"],
                    "change": node["change"],
                    "confidence": node["provenance"]["confidence"],
                    "evidence_refs": [node["node_id"]],
                    "location": node["location"],
                })
                if len(steps) == _MAX_FLOW_STEPS:
                    return steps
        return steps

    def _deep_stages(
        self, focus_nodes: Sequence[dict], nodes: Mapping[str, dict], edges: Sequence[dict]
    ) -> list[dict]:
        grouped: dict[str, list[dict]] = {}
        for node in focus_nodes:
            area = self._area(node)
            if area == "GENERATED":
                continue
            grouped.setdefault(area, []).append(node)
        stages: list[dict] = []
        for area in sorted(grouped, key=lambda item: _AREA_ORDER[item]):
            candidates = grouped[area]
            items = []
            seen: set[tuple[str, str]] = set()
            for node in candidates:
                key = (str(node["revision"]), self._short_label(node["label"]))
                if key in seen or node.get("kind") in {"CONDITION", "RETURN"}:
                    continue
                seen.add(key)
                items.append({**self._node_projection(node), "label": self._short_label(node["label"])})
                if len(items) == _MAX_STAGE_ITEMS:
                    break
            if not items:
                continue
            related = []
            for edge in edges:
                if edge.get("change") == "UNCHANGED_CONTEXT":
                    continue
                source = nodes[edge["source_node_id"]]
                target = nodes[edge["target_node_id"]]
                if self._area(source) != area or self._area(target) != area:
                    continue
                if self._area(source) == "GENERATED" or self._area(target) == "GENERATED":
                    continue
                related.append({
                    "edge_id": edge["edge_id"],
                    "source_label": self._short_label(source["label"]),
                    "target_label": self._short_label(target["label"]),
                    "relation": edge["relation"],
                    "relation_zh": _RELATION_ZH.get(edge["relation"], edge["relation"]),
                    "change": edge["change"],
                    "confidence": edge["provenance"]["confidence"],
                })
            related.sort(key=lambda item: (
                0 if item["relation"] == "DIRECT_CALL" else 1,
                item["source_label"], item["target_label"], item["edge_id"],
            ))
            counts = {
                kind: sum(1 for node in candidates if node.get("change") == kind)
                for kind in ("ADDED", "UPDATED", "REMOVED")
            }
            label_zh, label_en, icon = _AREA_LABELS[area]
            stages.append({
                "stage_id": f"stage:{area.lower()}",
                "order": len(stages) + 1,
                "area": area,
                "icon": icon,
                "title_zh": label_zh,
                "title_en": label_en,
                "summary_zh": (
                    f"从新增 {counts['ADDED']}、修改 {counts['UPDATED']}、删除 {counts['REMOVED']} "
                    f"个结构信号中，聚焦 {len(items)} 个代表对象。"
                ),
                "summary_en": (
                    f"Focused {len(items)} representative objects from {counts['ADDED']} added, "
                    f"{counts['UPDATED']} updated and {counts['REMOVED']} removed structural signals."
                ),
                "items": items,
                "relationships": related[:8],
            })
        return stages

    def _decision_points(
        self, focus_nodes: Sequence[dict], nodes: Mapping[str, dict], edges: Sequence[dict]
    ) -> list[dict]:
        incoming: dict[str, list[dict]] = {}
        for edge in edges:
            if edge.get("revision") == "NEW" and edge.get("change") == "ADDED":
                incoming.setdefault(str(edge["target_node_id"]), []).append(edge)
        candidates = [
            node for node in focus_nodes
            if node.get("revision") == "NEW"
            and node.get("change") == "ADDED"
            and node.get("kind") in {"CONDITION", "RETURN", "THROW"}
            and self._area(node) not in {"TEST", "GENERATED"}
        ]
        decisions: list[dict] = []
        for node in candidates:
            parent_edges = sorted(
                incoming.get(str(node["node_id"]), []),
                key=lambda edge: (edge["relation"], edge["source_node_id"], edge["edge_id"]),
            )
            parent = nodes[parent_edges[0]["source_node_id"]] if parent_edges else None
            context = self._short_label(parent["label"]) if parent is not None else "变更流程"
            relation = parent_edges[0]["relation"] if parent_edges else "BRANCHES_TO"
            label = self._short_label(node["label"])
            decisions.append({
                "decision_id": f"decision:{hashlib.sha256(str(node['node_id']).encode('utf-8')).hexdigest()[:16]}",
                "context": context,
                "condition": label,
                "statement_zh": f"{context} 新增“{label}”判断或退出点。",
                "statement_en": f"{context} adds the decision or exit point: {label}.",
                "relation": relation,
                "confidence": node["provenance"]["confidence"],
                "evidence_refs": [str(node["node_id"])] + [str(edge["edge_id"]) for edge in parent_edges[:1]],
                "location": node["location"],
            })
            if len(decisions) == _MAX_DECISIONS:
                break
        return decisions

    def _risk_cards(self, status: object, cards: Sequence[dict], analysis_digest: str) -> list[dict]:
        areas = {str(card["area"]) for card in cards}
        risks: list[dict] = []

        def add(level: str, suffix: str, title_zh: str, title_en: str, description_zh: str, description_en: str) -> None:
            risks.append({
                "risk_id": f"risk:{suffix}", "level": level,
                "title_zh": title_zh, "title_en": title_en,
                "description_zh": description_zh, "description_en": description_en,
                "evidence_refs": [analysis_digest],
            })

        if status == "PARTIAL":
            add(
                "HIGH", "partial", "编译上下文缺失", "Missing compile context",
                "当前只覆盖变更 C# 文件；未变更依赖、define、metadata 与完整程序集边界尚未确认。",
                "Only changed C# files are covered; unchanged dependencies, defines, metadata and full assembly boundaries remain unverified.",
            )
        if "SERVER" in areas and "CLIENT" in areas:
            add(
                "MEDIUM", "cross-runtime", "跨端行为需要联调", "Cross-runtime behavior needs integration testing",
                "服务端与客户端同时变化，消息时序、资源绑定和实际表现需要在运行环境验证。",
                "Server and client both changed; message timing, asset bindings and runtime behavior need integration validation.",
            )
        if "PROTOCOL" in areas:
            add(
                "MEDIUM", "protocol", "协议兼容需要验证", "Protocol compatibility needs validation",
                "协议或消息结构发生变化，需要确认新旧数据读取和灰度兼容行为。",
                "Protocol or message structures changed; old/new decoding and rollout compatibility need validation.",
            )
        if "CONFIGURATION" in areas:
            add(
                "MEDIUM", "configuration", "配置边界需要验证", "Configuration boundaries need validation",
                "配置结构或校验发生变化，需要用真实导出数据覆盖缺失、越界和顺序异常。",
                "Configuration or validation changed; real exported data should cover missing, out-of-range and ordering cases.",
            )
        return risks[:4]

    def _story_views(
        self,
        *,
        analysis: Mapping[str, object],
        nodes: Mapping[str, dict],
        edges: Sequence[dict],
        mappings: Sequence[dict],
        source_claims: Sequence[dict],
    ) -> tuple[dict, dict]:
        focus_nodes = self._focus_nodes(nodes, edges)
        topic_tokens: set[str] = set()
        for node in focus_nodes:
            if (
                node.get("revision") == "NEW"
                and node.get("change") == "ADDED"
                and node.get("kind") in {"METHOD", "TYPE"}
                and self._area(node) not in {"TEST", "GENERATED"}
            ):
                topic_tokens.update(self._label_tokens(node["label"]))
            if len(topic_tokens) >= 12:
                break
        if not topic_tokens:
            for node in focus_nodes:
                if node.get("revision") == "NEW" and node.get("kind") in {"METHOD", "TYPE"}:
                    topic_tokens.update(self._label_tokens(node["label"]))
                if len(topic_tokens) >= 8:
                    break
        cards = self._change_cards(focus_nodes, topic_tokens)
        cards.extend(self._context_change_cards(
            nodes, mappings, focus_nodes, {str(card["area"]) for card in cards}
        ))
        cards.sort(key=lambda card: _AREA_ORDER[str(card["area"])])
        cards = cards[:_MAX_QUICK_CARDS]
        representative = []
        for node in focus_nodes:
            if (
                node.get("revision") != "NEW"
                or node.get("change") != "ADDED"
                or node.get("kind") not in {"METHOD", "TYPE"}
                or self._area(node) in {"TEST", "GENERATED"}
            ):
                continue
            label = self._headline_label(node["label"])
            if label not in representative:
                representative.append(label)
            if len(representative) == 3:
                break
        if not representative:
            for node in focus_nodes:
                if node.get("revision") != "NEW" or node.get("kind") not in {"METHOD", "TYPE"}:
                    continue
                label = self._headline_label(node["label"])
                if label not in representative:
                    representative.append(label)
                if len(representative) == 3:
                    break
        if not representative:
            representative = ["当前代码路径"]
        areas_zh = "、".join(card["title_zh"] for card in cards) or "代码结构"
        primary_topic = "、".join(representative)
        summary_zh = f"本次修改主要围绕 {primary_topic} 展开，影响 {areas_zh}。"
        summary_en = f"The change centers on {', '.join(representative)} and affects {', '.join(card['title_en'] for card in cards) or 'code structure'}."
        area_keys = {card["area"] for card in cards}
        if {"CONFIGURATION", "SERVER", "CLIENT"}.issubset(area_keys):
            analogy_zh = "帮助理解：像把一条固定执行路线改造成“配置剧本 → 服务端编排 → 客户端演出”的流水线。"
            analogy_en = "Mental model: a fixed execution route becomes a configuration script, server orchestration and client presentation pipeline."
        elif any(node.get("kind") == "CONDITION" for node in focus_nodes):
            analogy_zh = "帮助理解：像在原有道路上增加新的岔路和安全护栏，让流程能选择、校验并在失败时退出。"
            analogy_en = "Mental model: new junctions and guardrails are added to the existing road so the flow can choose, validate and stop safely."
        else:
            analogy_zh = "帮助理解：像保留原有骨架，同时替换和补充其中的关键零件。"
            analogy_en = "Mental model: the original frame remains while key parts are replaced or added."
        impact_summary_zh = f"直接影响 {areas_zh}；完整符号和关系仍保留在技术证据中。"
        impact_summary_en = f"Directly affects {', '.join(card['title_en'] for card in cards)}; full symbols and relationships remain in technical evidence."
        analysis_digest = _non_empty_string(analysis.get("canonical_digest"), "analysis digest")
        quick_view = {
            "summary_zh": summary_zh,
            "summary_en": summary_en,
            "analogy_zh": analogy_zh,
            "analogy_en": analogy_en,
            "primary_topic": primary_topic,
            "change_cards": cards,
            "old_flow": self._flow_steps("OLD", focus_nodes, topic_tokens),
            "new_flow": self._flow_steps("NEW", focus_nodes, topic_tokens),
            "impact_summary_zh": impact_summary_zh,
            "impact_summary_en": impact_summary_en,
            "risk_cards": self._risk_cards(analysis.get("status"), cards, analysis_digest),
        }
        source_note = (
            "来源证据已提供；实现策略说明会将来源陈述与代码事实分开。"
            if source_claims
            else "未提供需求说明；以下内容是依据代码变化重建的工程实现结构，不是隐藏思维链。"
        )
        deep_dive = {
            "method_note_zh": source_note,
            "method_note_en": (
                "Source evidence is available and remains separate from code facts."
                if source_claims
                else "No requirement statement was supplied; this is an evidence-backed reconstruction of the implementation structure, not hidden chain-of-thought."
            ),
            "strategy_summary_zh": (
                f"修改按 {areas_zh} 分层展开；重点查看新增入口、关键分支、跨层数据和失败边界。"
            ),
            "strategy_summary_en": (
                f"The change spans {', '.join(card['title_en'] for card in cards)}; focus on new entries, decisions, cross-layer data and failure boundaries."
            ),
            "stages": self._deep_stages(focus_nodes, nodes, edges),
            "decision_points": self._decision_points(focus_nodes, nodes, edges),
            "evidence_summary_zh": "每个阶段、步骤和决策点都保留节点、关系或源码位置引用；原始分析作为最终证据层。",
            "evidence_summary_en": "Every stage, step and decision retains node, relationship or source-location references; the raw analysis remains the final evidence layer.",
        }
        return quick_view, deep_dive

    def _code_fact_claims(
        self, diff: Mapping[str, object], nodes: Mapping[str, dict], edges: Sequence[dict], mappings: Sequence[dict]
    ) -> list[dict]:
        summary = diff["summary"]
        source_status = diff.get("source_status")
        summary_confirmed = bool(
            diff.get("status") == "COMPLETE"
            and isinstance(source_status, Mapping)
            and source_status.get("old") == source_status.get("new") == "COMPLETE"
        )
        claims = [{
            "claim_id": "claim:code:summary", "layer": "CODE_FACT",
            "statement_zh": (
                ("静态分析确认" if summary_confirmed else "PARTIAL 结构分析显示")
                + f"新增 {summary['added_nodes']} 个、删除 {summary['removed_nodes']} 个图节点，"
                f"新增 {summary['added_edges']} 条、删除 {summary['removed_edges']} 条关系。"
            ),
            "statement_en": (
                ("Static analysis confirmed " if summary_confirmed else "PARTIAL structural analysis found ")
                + f"{summary['added_nodes']} added and {summary['removed_nodes']} removed "
                f"graph nodes, plus {summary['added_edges']} added and {summary['removed_edges']} removed relationships."
            ),
            "confidence": "CONFIRMED_STATIC" if summary_confirmed else "STRUCTURAL",
            "evidence_refs": [str(diff["canonical_digest"])],
        }]
        for index, mapping in enumerate(sorted(mappings, key=lambda item: item["mapping_id"])):
            if mapping["kind"] not in {"RENAMED", "MOVED", "RENAMED_AND_MOVED"}:
                continue
            old, new = nodes[mapping["old_node_id"]], nodes[mapping["new_node_id"]]
            action_zh = _CHANGE_ZH[mapping["kind"]]
            action_en = _CHANGE_EN[mapping["kind"]]
            claims.append({
                "claim_id": f"claim:code:mapping:{index}", "layer": "CODE_FACT",
                "statement_zh": f"{old['label']} 被{action_zh}为 {new['label']}。",
                "statement_en": f"{old['label']} was {action_en.lower()} to {new['label']}.",
                "confidence": mapping["confidence"], "evidence_refs": [mapping["mapping_id"]],
            })
        return claims

    def _source_claims(self, evidence: Mapping[str, object] | None) -> list[dict]:
        if evidence is None:
            return []
        allowed = {"schema_version", "source", "user_goal", "ai_plan", "commit_message"}
        unknown = set(evidence) - allowed
        if unknown:
            raise ValueError(f"unsupported intent evidence fields: {sorted(unknown)}")
        if evidence.get("schema_version") != "1.0.0":
            raise ValueError("unsupported intent evidence schema version")
        source = _non_empty_string(evidence.get("source"), "intent evidence source")
        claims: list[dict] = []
        entries: list[tuple[str, str, str]] = []
        if evidence.get("user_goal") is not None:
            entries.append(("user-goal", "用户目标", _non_empty_string(evidence["user_goal"], "user_goal")))
        if evidence.get("commit_message") is not None:
            entries.append(("commit-message", "提交说明", _non_empty_string(evidence["commit_message"], "commit_message")))
        plans = evidence.get("ai_plan", [])
        if not isinstance(plans, list):
            raise ValueError("ai_plan must be a string array")
        for index, plan in enumerate(plans):
            entries.append((f"ai-plan-{index}", "AI 计划", _non_empty_string(plan, "ai_plan item")))
        if not entries:
            raise ValueError("intent evidence must contain user_goal, ai_plan, or commit_message")
        for suffix, prefix, statement in entries:
            claims.append({
                "claim_id": f"claim:source:{suffix}", "layer": "SOURCE_EVIDENCE",
                "statement_zh": f"{prefix}：{statement}",
                "statement_en": f"Source statement ({source}): {statement}",
                "confidence": "UNKNOWN", "evidence_refs": [f"intent:{source}:{suffix}"],
            })
        return claims

    def _intent_inferences(
        self, edges: Sequence[dict], mappings: Sequence[dict], nodes: Mapping[str, dict]
    ) -> list[dict]:
        rules = {
            "BRANCHES_TO": ("可能引入了新的条件判断或前置校验。", "The change may introduce a condition or precondition check."),
            "THROWS_FROM": ("可能增加了显式失败处理。", "The change may add explicit failure handling."),
            "AWAITS": ("可能将部分流程调整为异步执行。", "The change may make part of the flow asynchronous."),
            "STARTS_COROUTINE": ("可能将部分流程调整为 Unity 协程。", "The change may move part of the flow into a Unity coroutine."),
            "SUBSCRIBES_EVENT": ("可能新增了事件驱动的响应路径。", "The change may add an event-driven response path."),
            "WRITES_STATE": ("可能改变了业务状态的更新时机或范围。", "The change may alter when or where business state is updated."),
        }
        claims: list[dict] = []
        for relation, (statement_zh, statement_en) in rules.items():
            evidence_refs = sorted(
                edge["edge_id"] for edge in edges
                if edge.get("revision") == "NEW" and edge.get("change") == "ADDED" and edge.get("relation") == relation
            )
            if evidence_refs:
                claims.append({
                    "claim_id": f"claim:inference:{relation.lower()}", "layer": "INTENT_INFERENCE",
                    "statement_zh": statement_zh, "statement_en": statement_en,
                    "confidence": "INFERRED", "evidence_refs": evidence_refs,
                })
        moved = [item for item in mappings if item.get("kind") in {"MOVED", "RENAMED_AND_MOVED"}]
        if moved:
            claims.append({
                "claim_id": "claim:inference:responsibility", "layer": "INTENT_INFERENCE",
                "statement_zh": "可能在重新划分类型或模块职责。",
                "statement_en": "The change may redistribute type or module responsibilities.",
                "confidence": "INFERRED", "evidence_refs": sorted(item["mapping_id"] for item in moved),
            })
        return claims

    def _impacts(self, nodes: Mapping[str, dict], edges: Sequence[dict]) -> list[dict]:
        impact_kinds = {"STATE", "EVENT", "TYPE", "UNKNOWN_TARGET"}
        impacted: dict[str, dict] = {}
        for edge in edges:
            if edge.get("change") not in {"ADDED", "REMOVED"}:
                continue
            target = nodes[edge["target_node_id"]]
            if target.get("kind") not in impact_kinds:
                continue
            key = f"{target['revision']}:{target['node_id']}"
            impacted[key] = {
                "impact_id": f"impact:{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}",
                "label": target["label"], "kind": target["kind"], "change": edge["change"],
                "location": target["location"], "evidence_refs": [edge["edge_id"], target["node_id"]],
            }
        return [impacted[key] for key in sorted(impacted)][:40]


class HtmlChangeStoryRenderer:
    """Render a self-contained, script-free two-level Chinese-first report."""

    def render(self, story: Mapping[str, object], *, repository_root: str | os.PathLike[str] | None = None) -> str:
        if story.get("schema_version") != "1.1.0" or story.get("language") != "zh-CN":
            raise ValueError("unsupported Change Story")
        repo = Path(repository_root).resolve() if repository_root is not None else None
        revisions = story.get("revisions")
        new_binding = revisions.get("new") if isinstance(revisions, Mapping) else None
        new_is_worktree = bool(
            isinstance(new_binding, Mapping)
            and (new_binding.get("revision") == "WORKTREE" or new_binding.get("dirty") is True)
        )
        esc = lambda value: html.escape(str(value), quote=True)
        status = esc(story["status"])
        overview = story["overview"]
        counts = overview["counts"]
        quick = story["quick_view"]
        deep = story["deep_dive"]
        claims = story["claims"]
        facts = [item for item in claims if item["layer"] == "CODE_FACT"]
        sources = [item for item in claims if item["layer"] == "SOURCE_EVIDENCE"]
        inferences = [item for item in claims if item["layer"] == "INTENT_INFERENCE"]

        def source_location(item: Mapping[str, object]) -> str:
            label = f"{item['path']}:{item['start_line']}"
            if repo is None or not new_is_worktree or item["revision_role"] != "NEW":
                return f'<span class="location">{esc(label)}</span>'
            candidate = (repo / Path(str(item["path"]))).resolve()
            try:
                candidate.relative_to(repo)
            except ValueError:
                return f'<span class="location">{esc(label)}</span>'
            return f'<a class="location" href="{esc(candidate.as_uri())}#L{item["start_line"]}">{esc(label)}</a>'

        def location(node: Mapping[str, object]) -> str:
            return source_location(node["location"])

        def evidence_details(evidence_refs: Sequence[object], locations: Sequence[Mapping[str, object]] = ()) -> str:
            links = "".join(source_location(item) for item in locations)
            return (
                '<details class="evidence"><summary>查看代码证据</summary>'
                f'{links}<code>{esc(", ".join(str(item) for item in evidence_refs))}</code></details>'
            )

        def quick_cards() -> str:
            if not quick["change_cards"]:
                return '<p class="empty">没有可聚焦的业务变化。</p>'
            return "".join(
                f'<article class="change-card area-{esc(item["area"].lower())}">'
                f'<div class="card-icon">{esc(item["icon"])}</div><div><h3>{esc(item["title_zh"])}</h3>'
                f'<p>{esc(item["summary_zh"])}</p><small>{esc(item["title_en"])}</small>'
                f'{evidence_details(item["evidence_refs"], item["locations"])}</div></article>'
                for item in quick["change_cards"]
            )

        def flow_steps(items: Sequence[Mapping[str, object]], empty: str) -> str:
            if not items:
                return f'<p class="empty">{esc(empty)}</p>'
            rendered = []
            for index, item in enumerate(items):
                if index:
                    rendered.append('<div class="flow-arrow">↓</div>')
                rendered.append(
                    f'<article class="flow-step change-{esc(item["change"].lower())}">'
                    f'<span class="step-number">{item["order"]}</span><div><small>{esc(item["area_label_zh"])}</small>'
                    f'<strong>{esc(item["label"])}</strong>'
                    f'<span>{esc(_CHANGE_ZH.get(item["change"], item["change"]))} · {esc(item["confidence"])}</span>'
                    f'{source_location(item["location"])}</div></article>'
                )
            return "".join(rendered)

        def risk_cards() -> str:
            if not quick["risk_cards"]:
                return '<p class="empty">没有自动提取到需要突出显示的风险。</p>'
            return "".join(
                f'<article class="risk risk-{esc(item["level"].lower())}"><span>{esc(item["level"])}</span>'
                f'<div><strong>{esc(item["title_zh"])}</strong><p>{esc(item["description_zh"])}</p></div></article>'
                for item in quick["risk_cards"]
            )

        def stages() -> str:
            if not deep["stages"]:
                return '<p class="empty">没有可拆解的实现阶段。</p>'
            rendered = []
            for stage in deep["stages"]:
                items = "".join(
                    f'<li><span class="badge change-{esc(item["change"].lower())}">'
                    f'{esc(_CHANGE_ZH.get(item["change"], item["change"]))}</span> '
                    f'<strong>{esc(item["label"])}</strong>{location(item)}</li>'
                    for item in stage["items"]
                )
                relationships = "".join(
                    f'<li><strong>{esc(item["source_label"])}</strong> '
                    f'<span class="relation">—{esc(item["relation_zh"])}→</span> '
                    f'<strong>{esc(item["target_label"])}</strong> '
                    f'<small>{esc(item["confidence"])}</small></li>'
                    for item in stage["relationships"]
                ) or '<li class="empty">没有进入聚焦视图的直接关系；可在技术证据中继续查看。</li>'
                rendered.append(
                    f'<details class="stage" open><summary><span class="stage-number">{stage["order"]}</span>'
                    f'<span class="stage-icon">{esc(stage["icon"])}</span><span><strong>{esc(stage["title_zh"])}</strong>'
                    f'<small>{esc(stage["summary_zh"])}</small></span></summary>'
                    f'<div class="stage-body"><div><h4>重点对象</h4><ul>{items}</ul></div>'
                    f'<div><h4>关键关系</h4><ul>{relationships}</ul></div></div></details>'
                )
            return "".join(rendered)

        def decisions() -> str:
            if not deep["decision_points"]:
                return '<p class="empty">没有提取到新增判断或退出点。</p>'
            return "".join(
                f'<article class="decision"><div class="decision-mark">◇</div><div>'
                f'<strong>{esc(item["statement_zh"])}</strong><small>{esc(item["relation"])} · {esc(item["confidence"])}</small>'
                f'{source_location(item["location"])}</div></article>'
                for item in deep["decision_points"]
            )

        def claim_cards(items: Sequence[Mapping[str, object]], empty: str) -> str:
            if not items:
                return f'<p class="empty">{esc(empty)}</p>'
            return "".join(
                f'<article class="claim {esc(item["layer"].lower())}">'
                f'<div class="claim-tag">{esc(item["layer"])} · {esc(item["confidence"])}</div>'
                f'<p>{esc(item["statement_zh"])}</p><small>{esc(item["statement_en"])}</small>'
                f'{evidence_details(item["evidence_refs"])}</article>' for item in items
            )

        def chain_cards(lane: Mapping[str, object]) -> str:
            chains = lane["chains"]
            if not chains:
                return '<p class="empty">该版本没有可聚焦的变更关系。</p>'
            rendered = []
            for chain in chains:
                pieces = []
                for index, node in enumerate(chain["nodes"]):
                    if index:
                        relation = chain["relations"][index - 1]
                        pieces.append(
                            f'<div class="arrow"><span>{esc(relation["relation_zh"])}</span>'
                            f'<small>{esc(relation["change"])} · {esc(relation["confidence"])}</small></div>'
                        )
                    pieces.append(
                        f'<div class="chain-node change-{esc(node["change"].lower())}">'
                        f'<strong>{esc(node["label"])}</strong>'
                        f'<span>{esc(node["kind"])} · {esc(_CHANGE_ZH.get(node["change"], node["change"]))}</span>'
                        f'{location(node)}</div>'
                    )
                rendered.append(f'<article class="chain" id="{esc(chain["chain_id"])}">{"".join(pieces)}</article>')
            return "".join(rendered)

        def change_rows() -> str:
            if not story["changes"]:
                return '<tr><td colspan="4" class="empty">没有符号级变化。</td></tr>'
            rows = []
            for item in story["changes"]:
                locations = " → ".join(f"{entry['path']}:{entry['start_line']}" for entry in item["locations"])
                rows.append(
                    f'<tr><td><span class="badge change-{esc(item["kind"].lower())}">'
                    f'{esc(_CHANGE_ZH.get(item["kind"], item["kind"]))}</span></td>'
                    f'<td>{esc(item["subject_zh"])}</td><td>{esc(item["confidence"])}</td>'
                    f'<td><code>{esc(locations)}</code></td></tr>'
                )
            return "".join(rows)

        limitations = "".join(f"<li>{esc(item)}</li>" for item in story["limitations"])
        impacts = "".join(
            f'<li><span class="badge change-{esc(item["change"].lower())}">{esc(_CHANGE_ZH[item["change"]])}</span> '
            f'<strong>{esc(item["label"])}</strong> <small>{esc(item["kind"])} · '
            f'{esc(item["location"]["path"])}:{item["location"]["start_line"]}</small></li>'
            for item in story["impacts"]
        ) or '<li class="empty">未发现状态、事件、类型或未知动态目标的直接增删影响。</li>'

        return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(story["title"])}</title>
<style>
:root{{--bg:#f3f6fb;--panel:#fff;--ink:#172033;--muted:#667085;--line:#dce3ee;--blue:#2563eb;--blue-soft:#eaf1ff;--green:#16803c;--red:#c73535;--amber:#b36b00;--purple:#7657c5;--shadow:0 12px 35px #253b6b16}}
*{{box-sizing:border-box}} body{{margin:0;background:radial-gradient(circle at 12% 0,#e7efff 0,transparent 32%),var(--bg);color:var(--ink);font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif}}
main{{max-width:1380px;margin:auto;padding:28px}} header{{background:linear-gradient(135deg,#111d47,#1d4ed8 68%,#4f70e8);color:white;border-radius:22px;padding:30px;box-shadow:0 18px 45px #1d4ed833}}
h1{{margin:8px 0;font-size:30px}} h2{{margin:30px 0 13px}} h3{{margin:0 0 7px}} h4{{margin:0 0 8px}} p{{margin:7px 0}} small,.en{{color:var(--muted)}} header .en{{color:#dbe7ff}} .digest{{word-break:break-all;opacity:.72;font-size:11px}}
.status{{display:inline-block;padding:4px 11px;border-radius:999px;background:#ffffff1f;border:1px solid #ffffff4a;font-weight:700}} .partial-note{{margin-top:16px;padding:11px 14px;border-radius:10px;background:#ffefc5;color:#724500}}
.tab-input{{position:absolute;opacity:0;pointer-events:none}} .tab-nav{{display:flex;gap:8px;margin:20px 0 0;padding:6px;background:#e5eaf3;border-radius:14px;position:sticky;top:8px;z-index:5;box-shadow:var(--shadow)}}
.tab-nav label{{flex:1;text-align:center;padding:12px;border-radius:10px;cursor:pointer;font-weight:700;color:var(--muted)}} #tab-quick:checked~.tab-nav label[for=tab-quick],#tab-deep:checked~.tab-nav label[for=tab-deep]{{background:white;color:var(--blue);box-shadow:0 4px 14px #26395c18}}
.tab-panel{{display:none}} #tab-quick:checked~.quick-panel,#tab-deep:checked~.deep-panel{{display:block}} .hero-summary{{font-size:21px;font-weight:700;margin:24px 0 10px}} .analogy{{padding:16px 18px;border:1px dashed #8aa8ef;background:#f6f9ff;border-radius:13px;color:#25447f}}
.cards{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}} .change-card{{display:flex;gap:11px;background:white;border:1px solid var(--line);border-top:4px solid var(--blue);border-radius:14px;padding:16px;box-shadow:var(--shadow);min-width:0}} .change-card>div:last-child{{min-width:0}} .card-icon{{font-size:25px}} .change-card p{{font-size:14px;overflow-wrap:anywhere}} .evidence summary{{cursor:pointer;color:var(--blue);font-size:12px}}
.comparison,.two-columns,.layers,.lanes,.stage-body{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:17px}} .lane,.panel,.claim,.chain,.stage,.decision,.risk{{background:var(--panel);border:1px solid var(--line);border-radius:14px}} .lane,.panel{{padding:18px}} .lane-old{{border-top:5px solid #8a95a8}} .lane-new{{border-top:5px solid var(--blue)}}
.flow-step{{display:flex;gap:11px;padding:12px;border:1px solid var(--line);border-left:4px solid #94a3b8;border-radius:10px;background:#fafcff}} .flow-step>div{{min-width:0}} .flow-step strong,.flow-step span,.location{{display:block}} .flow-step span,.location{{color:var(--muted);font-size:12px;overflow-wrap:anywhere}} .step-number,.stage-number{{display:grid!important;place-items:center;flex:0 0 25px;height:25px;border-radius:50%;background:var(--blue-soft);color:var(--blue)!important;font-weight:700}} .flow-arrow{{padding:2px 0 2px 11px;color:#7b8aa5}}
.risk{{display:flex;gap:12px;padding:14px;margin:10px 0;border-left:5px solid var(--amber)}} .risk>span{{font-size:11px;font-weight:800;color:var(--amber)}} .risk-high{{border-left-color:var(--red)}} .risk-high>span{{color:var(--red)}}
.method-note{{padding:15px 17px;border-left:5px solid var(--purple);background:#f6f2ff;border-radius:11px}} .stage{{margin:12px 0;overflow:hidden}} .stage>summary{{display:flex;align-items:center;gap:11px;padding:15px;cursor:pointer;background:#f8faff}} .stage>summary small{{display:block}} .stage-icon{{font-size:24px}} .stage-body{{padding:16px}} .stage-body ul{{padding-left:18px}} .stage-body li{{margin:7px 0;overflow-wrap:anywhere}} .relation{{color:var(--blue)}}
.decision{{display:flex;gap:12px;padding:14px;margin:10px 0;border-left:4px solid var(--amber)}} .decision-mark{{font-size:23px;color:var(--amber)}} .decision small{{display:block}} .technical{{margin-top:24px;padding:16px;background:#eef2f7;border-radius:14px}} .technical>summary{{cursor:pointer;font-weight:800}}
.metrics{{display:grid;grid-template-columns:repeat(6,minmax(90px,1fr));gap:9px;margin:16px 0}} .metric{{padding:12px;background:white;border:1px solid var(--line);border-radius:10px}} .metric strong{{display:block;font-size:20px}} .layers{{grid-template-columns:repeat(3,minmax(0,1fr))}} .claim{{padding:13px;margin:9px 0;border-left:4px solid var(--blue)}} .claim.source_evidence{{border-left-color:var(--purple)}} .claim.intent_inference{{border-left-color:var(--amber)}} .claim-tag{{font-size:11px;color:var(--muted)}}
.chain{{padding:12px;margin:10px 0}} .chain-node{{padding:10px 12px;border-radius:9px;background:#f8fafc;border-left:4px solid #94a3b8;overflow-wrap:anywhere}} .chain-node span{{display:block;color:var(--muted);font-size:12px}} .arrow{{padding:6px 18px;color:var(--blue)}} .arrow span:before{{content:"↓  "}} .arrow small{{display:block;margin-left:18px}}
.change-added{{border-color:var(--green)!important;color:var(--green)}} .change-removed{{border-color:var(--red)!important;color:var(--red)}} .change-updated{{border-color:var(--amber)!important;color:var(--amber)}} .change-moved,.change-renamed,.change-renamed_and_moved{{border-color:var(--blue)!important;color:var(--blue)}}
table{{width:100%;border-collapse:collapse;background:white;border-radius:12px;overflow:hidden}} th,td{{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}} th{{background:#edf2f8}} code{{display:block;font-size:11px;word-break:break-all;color:#58647a}} .badge{{display:inline-block;border:1px solid currentColor;border-radius:999px;padding:2px 8px;font-size:11px}} .empty{{color:var(--muted)}} footer{{margin:30px 0;color:var(--muted)}}
@media(max-width:1050px){{.cards{{grid-template-columns:repeat(2,1fr)}}}} @media(max-width:780px){{main{{padding:13px}}.cards,.comparison,.two-columns,.layers,.lanes,.stage-body{{grid-template-columns:1fr}}.metrics{{grid-template-columns:repeat(2,1fr)}}.tab-nav{{position:static}}}}
</style></head><body><main data-story-digest="{esc(story["canonical_digest"])}">
<header><span class="status">{status}</span><h1>{esc(story["title"])}</h1>
<p>{esc(quick["summary_zh"])}</p><p class="en">{esc(quick["summary_en"])}</p>
{('<div class="partial-note">PARTIAL：当前结论仅覆盖变更 C# 文件，所有关系最高为结构级证据。</div>' if story["status"] == "PARTIAL" else '')}
<p class="digest">Analysis {esc(story["analysis_digest"])} · Story {esc(story["canonical_digest"])}</p></header>
<input class="tab-input" type="radio" name="story-tab" id="tab-quick" checked><input class="tab-input" type="radio" name="story-tab" id="tab-deep">
<nav class="tab-nav"><label for="tab-quick">⚡ 快速理解 <small>30–60 秒</small></label><label for="tab-deep">🧭 详细思路拆解 <small>按证据重建</small></label></nav>
<section class="tab-panel quick-panel">
<p class="hero-summary">{esc(quick["summary_zh"])}</p><div class="analogy">{esc(quick["analogy_zh"])}</div>
<h2>到底改了什么</h2><section class="cards">{quick_cards()}</section>
<h2>原来怎样 → 现在怎样</h2><section class="comparison"><div class="lane lane-old"><h3>原链路 <small>OLD</small></h3>{flow_steps(quick["old_flow"],"原版本没有进入业务聚焦层的显著步骤。")}</div>
<div class="lane lane-new"><h3>新链路 <small>NEW</small></h3>{flow_steps(quick["new_flow"],"新版本没有进入业务聚焦层的显著步骤。")}</div></section>
<section class="two-columns"><div><h2>影响范围</h2><div class="panel"><p>{esc(quick["impact_summary_zh"])}</p></div></div><div><h2>优先关注</h2>{risk_cards()}</div></section>
</section>
<section class="tab-panel deep-panel">
<p class="hero-summary">{esc(deep["strategy_summary_zh"])}</p><div class="method-note">{esc(deep["method_note_zh"])}</div>
<h2>修改如何分层展开</h2>{stages()}
<h2>新增决策与退出点</h2><section class="two-columns">{decisions()}</section>
<div class="panel"><strong>证据说明</strong><p>{esc(deep["evidence_summary_zh"])}</p></div>
<details class="technical"><summary>展开完整技术证据（符号、关系、限制）</summary>
<section class="metrics"><div class="metric"><strong>{counts["added_nodes"]}</strong><span>新增节点</span></div><div class="metric"><strong>{counts["removed_nodes"]}</strong><span>删除节点</span></div><div class="metric"><strong>{counts["updated_node_pairs"]}</strong><span>修改节点对</span></div><div class="metric"><strong>{counts["moved_node_pairs"]}</strong><span>移动节点对</span></div><div class="metric"><strong>{counts["added_edges"]}</strong><span>新增关系</span></div><div class="metric"><strong>{counts["removed_edges"]}</strong><span>删除关系</span></div></section>
<h2>修改依据</h2><section class="layers"><div class="panel"><h3>代码事实</h3>{claim_cards(facts,"没有可展示的代码事实。")}</div><div class="panel"><h3>来源证据</h3>{claim_cards(sources,"未提供用户需求、AI 计划或提交说明。")}</div><div class="panel"><h3>意图推断</h3>{claim_cards(inferences,"没有足够代码模式支持意图推断。")}</div></section>
<h2>完整原链路 → 新链路</h2><section class="lanes"><div class="panel"><h3>原链路</h3>{chain_cards(story["lanes"]["old"])}</div><div class="panel"><h3>新链路</h3>{chain_cards(story["lanes"]["new"])}</div></section>
<h2>符号变化</h2><table><thead><tr><th>类型</th><th>对象</th><th>置信度</th><th>代码位置</th></tr></thead><tbody>{change_rows()}</tbody></table>
<section class="lanes"><div><h2>直接影响</h2><div class="panel"><ul>{impacts}</ul></div></div><div><h2>限制与未知项</h2><div class="panel"><ul>{limitations}</ul></div></div></section>
</details></section>
<footer>AEH Change Lens · 中文优先离线报告 · 快速理解 + 详细思路拆解 · 不执行目标项目代码 · 不声称还原隐藏思维链</footer>
</main></body></html>'''


def write_change_story_report(
    output_path: str | os.PathLike[str], story: Mapping[str, object], *, repository_root: str | os.PathLike[str] | None = None
) -> Path:
    path = Path(output_path).resolve()
    if path.exists() and path.is_dir():
        raise ValueError("report output path must be a file")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(HtmlChangeStoryRenderer().render(story, repository_root=repository_root))
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path
