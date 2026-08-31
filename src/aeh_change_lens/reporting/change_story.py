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
_MAX_MAP_ITEMS = 3
_MAX_MAP_CHANGES = 3
_MAX_SCENARIOS = 5
_MAX_SCENARIO_BEFORE = 3
_MAX_SCENARIO_AFTER = 4
_MAX_SCENARIO_RELATIONSHIPS = 6

_ROLE_TYPE_PATTERN = re.compile(
    r"(?:Window|Repository|Validator|Service|Controller|Manager|AutoFixer|"
    r"ChangeTracker|ExportRunner|Preview|Templates|Planner)$"
)

_AREA_ORDER = {
    "CONFIGURATION": 0,
    "SERVER": 1,
    "PROTOCOL": 2,
    "EDITOR": 3,
    "CLIENT": 4,
    "RUNTIME": 5,
    "TEST": 6,
    "GENERATED": 7,
}

_AREA_LABELS = {
    "CONFIGURATION": ("配置与规则", "Configuration and rules", "📋"),
    "SERVER": ("服务端编排", "Server orchestration", "🧠"),
    "PROTOCOL": ("协议与数据", "Protocol and data", "🛰️"),
    "EDITOR": ("Unity 编辑器工具", "Unity Editor tooling", "🛠️"),
    "CLIENT": ("客户端表现", "Client behavior", "🎮"),
    "RUNTIME": ("运行逻辑", "Runtime logic", "⚙️"),
    "TEST": ("测试保障", "Test coverage", "🧪"),
    "GENERATED": ("生成代码", "Generated code", "🧩"),
}

_SCENARIO_RECIPES = (
    {
        "key": "guided-authoring",
        "icon": "🧭",
        "title_zh": "引导与完成度",
        "title_en": "Guidance and readiness",
        "question_zh": "使用者怎样知道当前完成到哪一步？",
        "question_en": "How does the user know what is complete and what to do next?",
        "pattern": re.compile(r"Readiness|Completion|Professional|SimpleMode|AssetPreview|DrawSkill|HasAllSkillPrefabs", re.I),
    },
    {
        "key": "authoring",
        "icon": "🧱",
        "title_zh": "创建与编排",
        "title_en": "Create and author",
        "question_zh": "技能数据怎样被创建、复制或编排？",
        "question_en": "How is skill data created, copied, or authored?",
        "pattern": re.compile(r"Create|Template|Allocate|Duplicate|Authoring|Draft", re.I),
    },
    {
        "key": "validation",
        "icon": "🛡️",
        "title_zh": "校验与安全修复",
        "title_en": "Validate and repair",
        "question_zh": "错误怎样被发现、修复或阻止进入保存？",
        "question_en": "How are errors found, repaired, or blocked before save?",
        "pattern": re.compile(r"Validate|Validation|AutoFix|Repair|HasErrors|Issue|SafeFix", re.I),
    },
    {
        "key": "preview",
        "icon": "🎬",
        "title_zh": "预览与表现",
        "title_en": "Preview and presentation",
        "question_zh": "配置怎样转成可以检查的攻击预览？",
        "question_en": "How does configuration become an inspectable attack preview?",
        "pattern": re.compile(r"Preview|ResolveTransform|DrawSpatial|DrawScene|AttackShape|Gizmo", re.I),
    },
    {
        "key": "persistence",
        "icon": "💾",
        "title_zh": "加载、保存与导出",
        "title_en": "Load, save, and export",
        "question_zh": "编辑结果怎样从配置进入保存和导出？",
        "question_en": "How do edited values move through load, save, and export?",
        "pattern": re.compile(r"Excel|Repository|Load|Save|Export|Import|Write|Read", re.I),
    },
    {
        "key": "runtime",
        "icon": "⚔️",
        "title_zh": "运行时攻击",
        "title_en": "Runtime attack",
        "question_zh": "配置最终怎样驱动怪物攻击？",
        "question_en": "How does configuration ultimately drive the monster attack?",
        "pattern": re.compile(r"OnAttack|SendAttack|GetRandom|CreateComboAttackInfo|ResolveComboStep|AttackInfo", re.I),
    },
)


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
        visual_map = self._visual_map(
            analysis=analysis,
            nodes=nodes,
            edges=edges,
            mappings=mappings,
            quick_view=quick_view,
        )
        scenario_lens = self._scenario_lens(
            analysis=analysis,
            nodes=nodes,
            edges=edges,
            visual_map=visual_map,
        )
        daily_brief = self._daily_brief(
            analysis=analysis,
            scenario_lens=scenario_lens,
            visual_map=visual_map,
        )
        semantic = {
            "schema_version": "1.5.0",
            "story_id": f"story:{analysis_digest[:24]}",
            "language": "zh-CN",
            "status": str(analysis["status"]),
            "title": title,
            "analysis_digest": analysis_digest,
            "revisions": analysis["revisions"],
            "overview": {
                "headline_zh": visual_map["headline_zh"],
                "headline_en": visual_map["headline_en"],
                "counts": summary,
            },
            "quick_view": quick_view,
            "visual_map": visual_map,
            "scenario_lens": scenario_lens,
            "daily_brief": daily_brief,
            "deep_dive": deep_dive,
            "lanes": lanes,
            "changes": changes,
            "claims": sorted(claims, key=lambda item: item["claim_id"]),
            "impacts": self._impacts(nodes, edges),
            "limitations": sorted(set(limitations)),
        }
        return {**semantic, "canonical_digest": _canonical_digest(semantic)}

    def _daily_brief(
        self,
        *,
        analysis: Mapping[str, object],
        scenario_lens: Mapping[str, object],
        visual_map: Mapping[str, object],
    ) -> dict:
        """Turn the primary scenario into a bounded, action-oriented daily brief."""

        primary = next(
            item for item in scenario_lens["scenarios"]
            if item["scenario_id"] == scenario_lens["primary_scenario_id"]
        )
        takeaways_zh = list(scenario_lens["takeaways_zh"])
        takeaways_en = list(scenario_lens["takeaways_en"])
        joined_zh = "、".join(f"“{item}”" for item in takeaways_zh)
        joined_en = ", ".join(takeaways_en)
        shape = str(primary["change_shape"])
        verbs = {
            "ADDED": ("新增了", "adds"),
            "REMOVED": ("移除了", "removes"),
            "MODIFIED": ("重点调整了", "changes"),
            "PARALLEL": ("集中影响", "affects"),
        }
        verb_zh, verb_en = verbs[shape]
        what_changed_zh = f"这次修改{verb_zh}“{primary['title_zh']}”：{joined_zh}。"
        what_changed_en = f"This change {verb_en} {primary['title_en']}: {joined_en}."

        selected_items = list(primary["after"]) + list(primary["before"])
        first_refs = list(selected_items[0]["evidence_refs"]) if selected_items else [str(analysis["canonical_digest"])]
        checks = [{
            "check_id": "daily-check:primary",
            "kind": "PRIMARY_BEHAVIOR",
            "action_zh": f"打开 Unity 编辑器，用一次真实操作确认“{takeaways_zh[0]}”符合预期。",
            "action_en": f"Open the Unity Editor and confirm “{takeaways_en[0]}” with one real workflow.",
            "evidence_refs": first_refs,
        }]
        relationships = list(primary["relationships"])
        if relationships:
            checks.append({
                "check_id": "daily-check:relationship",
                "kind": "RELATIONSHIP_PATH",
                "action_zh": "沿“已证实的关系路径”核对输入、判断和最终表现是否连贯。",
                "action_en": "Follow the verified relationship paths and check that input, decisions, and presentation remain coherent.",
                "evidence_refs": [str(item["edge_id"]) for item in relationships[:3]],
            })
        elif len(takeaways_zh) > 1:
            second_refs = list(selected_items[1]["evidence_refs"]) if len(selected_items) > 1 else first_refs
            checks.append({
                "check_id": "daily-check:secondary",
                "kind": "SECONDARY_BEHAVIOR",
                "action_zh": f"再用一个边界操作确认“{takeaways_zh[1]}”不会产生意外结果。",
                "action_en": f"Use one boundary interaction to confirm “{takeaways_en[1]}” has no unexpected result.",
                "evidence_refs": second_refs,
            })
        if analysis["status"] == "PARTIAL":
            checks.append({
                "check_id": "daily-check:partial",
                "kind": "EVIDENCE_BOUNDARY",
                "action_zh": "在目标 Unity 环境完成编译和实际运行验证，补齐当前 PARTIAL 证据边界。",
                "action_en": "Compile and exercise the change in the target Unity environment to close the current PARTIAL evidence boundary.",
                "evidence_refs": [str(analysis["canonical_digest"])],
            })
        elif len(checks) < 3:
            checks.append({
                "check_id": "daily-check:regression",
                "kind": "REGRESSION",
                "action_zh": "回归一次相邻的保存、预览或运行流程，确认本次修改没有越出主场景。",
                "action_en": "Regression-check one adjacent save, preview, or runtime flow for effects outside the primary scenario.",
                "evidence_refs": list(primary["evidence_refs"][:3]),
            })
        return {
            "question_zh": "我今天应该先看什么？",
            "question_en": "What should I look at first today?",
            "what_changed_zh": what_changed_zh,
            "what_changed_en": what_changed_en,
            "why_it_matters_zh": str(visual_map["impact_zh"]),
            "why_it_matters_en": str(visual_map["impact_en"]),
            "confidence_note_zh": (
                "当前是 PARTIAL：先用它理解改动，再用 Unity 编译和实际操作确认。"
                if analysis["status"] == "PARTIAL"
                else "当前报告具备完整分析上下文，但运行表现仍应通过实际操作确认。"
            ),
            "confidence_note_en": (
                "This is PARTIAL: use it to understand the change, then confirm through Unity compilation and real interaction."
                if analysis["status"] == "PARTIAL"
                else "The report has full analysis context, but runtime behavior should still be confirmed through real interaction."
            ),
            "primary_scenario_id": str(primary["scenario_id"]),
            "change_shape": shape,
            "checks": checks[:3],
        }

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
        if "/assets/editor/" in normalized or "/editor/" in normalized:
            return "EDITOR"
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
        if re.search(r"(?:^|\.)(?:Try|On|Handle|Execute|Create|Resolve|Validate|Verify|Load|Save|Read|Write|Refresh|Import|Export|Send|Broadcast|GetRandom)", label):
            score += 4
        if re.search(r"(?:^|\.)(?:On|Handle|Execute)[A-Z]", label):
            score += 3
        if re.search(r"(?:^|\.)Try[A-Z]", label):
            score += 2
        if _ROLE_TYPE_PATTERN.search(label):
            score += 6
        if re.search(
            r"(?:^|\.)(?:OnGUI|OnSceneGUI|OnEditorUpdate|OnPlayModeStateChanged|OnEnable|OnDisable|OnProjectChange|OnUndoRedo|Update|LateUpdate|FixedUpdate)\(",
            label,
        ):
            score -= 8
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
            ordered_candidates = candidates
            if area == "EDITOR":
                ordered_candidates = sorted(
                    candidates,
                    key=lambda node: (
                        0 if node.get("kind") == "TYPE" else 1,
                        -self._node_score(node), str(node.get("label", "")),
                    ),
                )
            for node in ordered_candidates:
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
            if role == "NEW" and area == "SERVER":
                area_limit = 4
            elif role == "NEW" and area == "EDITOR":
                area_limit = 6
            else:
                area_limit = 2
            owner_counts: dict[str, int] = {}
            for node in area_candidates:
                if node.get("kind") not in {"METHOD", "TYPE", "EVENT", "STATE"}:
                    continue
                if area == "EDITOR":
                    short = self._short_label(node["label"])
                    owner = short.split("(", 1)[0].rsplit(".", 1)[0] if "(" in short else short
                    if owner_counts.get(owner, 0) >= 2:
                        continue
                    owner_counts[owner] = owner_counts.get(owner, 0) + 1
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

    @classmethod
    def _business_label(cls, scenario_key: str, value: object) -> tuple[str, str]:
        label = cls._compact_label(value)
        lowered = label.lower()
        rules = {
            "guided-authoring": (
                ("readiness", "计算并显示完成度", "Calculate and show readiness"),
                ("prefab", "确认攻击资源是否就绪", "Confirm attack assets are ready"),
                ("professional", "按使用者切换字段深度", "Switch field depth for the user"),
                ("mode", "按使用者切换字段深度", "Switch field depth for the user"),
                ("attackcdready", "确认冷却覆盖完整时间轴", "Confirm cooldown covers the full timeline"),
            ),
            "authoring": (
                ("template", "用模板生成初始技能", "Create initial skill data from a template"),
                ("duplicate", "复制可独立编辑的数据", "Duplicate independently editable data"),
                ("allocate", "分配新的配置标识", "Allocate new configuration identifiers"),
                ("addcomplete", "创建一套完整技能", "Create a complete skill"),
                ("addstep", "增加一个攻击步骤", "Add an attack step"),
                ("create", "创建并组装技能数据", "Create and assemble skill data"),
            ),
            "validation": (
                ("autofix", "修复能够确定的问题", "Repair deterministic issues"),
                ("safe", "只执行安全修复", "Apply safe repairs only"),
                ("haserrors", "阻止错误数据继续流转", "Block invalid data from proceeding"),
                ("validate", "检查配置是否合法", "Validate configuration"),
                ("validation", "检查配置是否合法", "Validate configuration"),
                ("issue", "汇总需要处理的问题", "Collect issues that need attention"),
            ),
            "preview": (
                ("resolve", "计算攻击位置和方向", "Resolve attack position and direction"),
                ("plan", "生成攻击预览计划", "Build an attack preview plan"),
                ("draw", "显示攻击范围和时间", "Show attack range and timing"),
                ("preview", "生成可检查的攻击预览", "Build an inspectable attack preview"),
            ),
            "persistence": (
                ("load", "加载已有配置", "Load existing configuration"),
                ("save", "保存编辑结果", "Save edited values"),
                ("export", "导出运行时配置", "Export runtime configuration"),
                ("write", "写回配置数据", "Write configuration data"),
                ("read", "读取配置数据", "Read configuration data"),
            ),
            "runtime": (
                ("random", "选择本次攻击组合", "Select the attack combo"),
                ("resolve", "解析组合步骤", "Resolve combo steps"),
                ("create", "组装攻击消息", "Assemble attack information"),
                ("send", "把攻击结果发送给表现层", "Send attack results to presentation"),
                ("attack", "执行怪物攻击", "Execute the monster attack"),
            ),
        }
        for token, zh, en in rules.get(scenario_key, ()):
            if token in lowered:
                return zh, en
        area_fallbacks = {
            "configuration": ("调整配置规则", "Adjust configuration rules"),
            "server": ("编排服务端处理", "Orchestrate server processing"),
            "protocol": ("传递协议与数据", "Carry protocol and data"),
            "editor": ("支持 Unity 编辑操作", "Support Unity editor work"),
            "client": ("更新客户端表现", "Update client presentation"),
            "runtime": ("调整运行逻辑", "Adjust runtime behavior"),
            "test": ("验证修改行为", "Verify changed behavior"),
        }
        return area_fallbacks.get(scenario_key, (f"查看 {label}", f"Inspect {label}"))

    def _scenario_lens(
        self,
        *,
        analysis: Mapping[str, object],
        nodes: Mapping[str, dict],
        edges: Sequence[dict],
        visual_map: Mapping[str, object],
    ) -> dict:
        """Group changed evidence by reader question instead of file or symbol order."""

        focus_nodes = [
            node for node in self._focus_nodes(nodes, edges)
            if self._area(node) != "GENERATED"
            and node.get("kind") in {"METHOD", "TYPE", "EVENT", "STATE"}
        ]
        business_nodes = [node for node in focus_nodes if self._area(node) != "TEST"]
        test_only = bool(focus_nodes) and not business_nodes
        candidates = business_nodes or focus_nodes
        buckets: dict[str, dict] = {}
        changed_degree: dict[str, int] = {}
        for edge in edges:
            if edge.get("change") == "UNCHANGED_CONTEXT":
                continue
            for endpoint in ("source_node_id", "target_node_id"):
                node_id = str(edge.get(endpoint, ""))
                if node_id:
                    changed_degree[node_id] = changed_degree.get(node_id, 0) + 1

        for node in candidates:
            label = str(node.get("label", ""))
            recipe = next(
                (item for item in _SCENARIO_RECIPES if item["pattern"].search(label)),
                None,
            )
            if recipe is None:
                area = self._area(node)
                label_zh, label_en, icon = _AREA_LABELS[area]
                recipe = {
                    "key": area.lower(),
                    "icon": icon,
                    "title_zh": label_zh,
                    "title_en": label_en,
                    "question_zh": f"{label_zh}在本次修改中承担什么职责？",
                    "question_en": f"What role does {label_en.lower()} play in this change?",
                    "specific": False,
                }
            else:
                recipe = {**recipe, "specific": True}
            bucket = buckets.setdefault(str(recipe["key"]), {**recipe, "nodes": []})
            bucket["nodes"].append(node)

        if not buckets:
            buckets["test" if test_only else "runtime"] = {
                "key": "test" if test_only else "runtime",
                "icon": "🧪" if test_only else "⚙️",
                "title_zh": "测试保障" if test_only else "变化证据",
                "title_en": "Test coverage" if test_only else "Change evidence",
                "question_zh": "这次修改提供了哪些可验证证据？",
                "question_en": "What verifiable evidence does this change provide?",
                "specific": False,
                "nodes": [],
            }

        specific_areas = {
            self._area(node)
            for bucket in buckets.values() if bucket.get("specific")
            for node in bucket["nodes"]
        }
        if specific_areas:
            buckets = {
                key: bucket for key, bucket in buckets.items()
                if bucket.get("specific") or key.upper() not in specific_areas
            }

        ranked = sorted(
            buckets.values(),
            key=lambda item: (
                -(
                    (40 if item.get("specific") else 0)
                    + sum(sorted(
                        (max(self._node_score(node), 0) for node in item["nodes"]),
                        reverse=True,
                    )[:6])
                    + 25 * min(sum(
                        1 for node in item["nodes"]
                        if node.get("change") in {"ADDED", "REMOVED"}
                        and node.get("kind") in {"METHOD", "TYPE"}
                    ), 4)
                    + 2 * min(sum(
                        1 for node in item["nodes"]
                        if node.get("change") in {"ADDED", "REMOVED"}
                    ), 6)
                ),
                str(item["key"]),
            ),
        )[:_MAX_SCENARIOS]

        scenarios: list[dict] = []
        for order, bucket in enumerate(ranked, start=1):
            key = str(bucket["key"])

            def pick(role: str, limit: int) -> list[dict]:
                result: list[dict] = []
                seen_labels: set[str] = set()
                seen_business: set[str] = set()
                values = sorted(
                    (node for node in bucket["nodes"] if node.get("revision") == role),
                    key=lambda node: (
                        -self._node_score(node, changed_degree.get(str(node["node_id"]), 0)),
                        str(node.get("label", "")),
                    ),
                )
                for node in values:
                    label = self._compact_label(node.get("label", ""))
                    business_zh, _ = self._business_label(key, node.get("label", ""))
                    if label in seen_labels or business_zh in seen_business:
                        continue
                    seen_labels.add(label)
                    seen_business.add(business_zh)
                    result.append(node)
                    if len(result) == limit:
                        break
                return result

            old_nodes = pick("OLD", _MAX_SCENARIO_BEFORE)
            new_nodes = pick("NEW", _MAX_SCENARIO_AFTER)

            def project(node: Mapping[str, object], role: str) -> dict:
                node_id = str(node["node_id"])
                business_zh, business_en = self._business_label(key, node.get("label", ""))
                identity = f"scenario:{key}:{role}:{node_id}"
                return {
                    "item_id": f"scenario-item:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}",
                    "role": role,
                    "business_label_zh": business_zh,
                    "business_label_en": business_en,
                    "technical_label": self._compact_label(node.get("label", "")),
                    "area": self._area(node),
                    "change": str(node["change"]),
                    "confidence": str(node["provenance"]["confidence"]),
                    "evidence_refs": [node_id],
                    "location": node["location"],
                }

            before = [project(node, "BEFORE") for node in old_nodes]
            after = [project(node, "AFTER") for node in new_nodes]
            selected_items = before + after
            node_to_item = {
                str(node["node_id"]): item["item_id"]
                for node, item in zip(old_nodes + new_nodes, selected_items)
            }
            relations = []
            for edge in sorted(edges, key=lambda item: str(item["edge_id"])):
                source_id = str(edge.get("source_node_id", ""))
                target_id = str(edge.get("target_node_id", ""))
                if (
                    edge.get("change") == "UNCHANGED_CONTEXT"
                    or source_id not in node_to_item
                    or target_id not in node_to_item
                ):
                    continue
                relations.append({
                    "edge_id": str(edge["edge_id"]),
                    "source_item_id": node_to_item[source_id],
                    "target_item_id": node_to_item[target_id],
                    "relation": str(edge["relation"]),
                    "relation_zh": _RELATION_ZH.get(str(edge["relation"]), str(edge["relation"])),
                    "change": str(edge["change"]),
                    "confidence": str(edge["provenance"]["confidence"]),
                    "evidence_refs": [str(edge["edge_id"]), source_id, target_id],
                })
                if len(relations) == _MAX_SCENARIO_RELATIONSHIPS:
                    break

            business_labels = []
            for item in after + before:
                if item["business_label_zh"] not in business_labels:
                    business_labels.append(item["business_label_zh"])
                if len(business_labels) == 3:
                    break
            answer_zh = (
                f"这个场景的变化集中在：{'；'.join(business_labels)}。技术名称和完整关系按需展开。"
                if business_labels
                else "当前只有范围级变化证据，完整符号保留在技术证据中。"
            )
            answer_en = (
                f"This scenario centers on {', '.join(item['business_label_en'] for item in (after + before)[:3])}; technical names and full relationships stay on demand."
                if selected_items
                else "Only scope-level change evidence is available; full symbols remain in technical evidence."
            )
            scenario_id = f"scenario:{key}"
            evidence_refs = [
                ref
                for item in selected_items for ref in item["evidence_refs"]
            ] + [ref for relation in relations for ref in relation["evidence_refs"][:1]]
            if before and after:
                change_shape = "MODIFIED"
            elif after:
                change_shape = "ADDED"
            elif before:
                change_shape = "REMOVED"
            else:
                change_shape = "PARALLEL"
            scenarios.append({
                "scenario_id": scenario_id,
                "order": order,
                "icon": str(bucket["icon"]),
                "title_zh": str(bucket["title_zh"]),
                "title_en": str(bucket["title_en"]),
                "question_zh": str(bucket["question_zh"]),
                "question_en": str(bucket["question_en"]),
                "answer_zh": answer_zh,
                "answer_en": answer_en,
                "change_shape": change_shape,
                "relationship_mode": "VERIFIED_FLOW" if relations else "PARALLEL_FACTS",
                "before": before,
                "after": after,
                "relationships": relations,
                "evidence_refs": evidence_refs or [_non_empty_string(analysis.get("canonical_digest"), "analysis digest")],
            })

        primary = scenarios[0]
        takeaways_zh: list[str] = []
        takeaways_en: list[str] = []
        for item in primary["after"] + primary["before"]:
            takeaway_zh = str(item["business_label_zh"])
            if takeaway_zh in takeaways_zh:
                continue
            takeaways_zh.append(takeaway_zh)
            takeaways_en.append(str(item["business_label_en"]))
            if len(takeaways_zh) == 3:
                break
        if not takeaways_zh:
            takeaways_zh = [str(primary["title_zh"])]
            takeaways_en = [str(primary["title_en"])]
        return {
            "primary_scenario_id": primary["scenario_id"],
            "summary_zh": f"先回答“{primary['question_zh']}”，再按需切换其他场景。",
            "summary_en": f"Start with “{primary['question_en']}”, then switch scenarios only when needed.",
            "outcome_zh": primary["answer_zh"],
            "outcome_en": primary["answer_en"],
            "takeaways_zh": takeaways_zh,
            "takeaways_en": takeaways_en,
            "scope_note_zh": "场景按读者问题聚合证据；未显示对象不等于无关，完整范围仍以技术证据为准。",
            "scope_note_en": "Scenarios group evidence by reader question; omitted objects are not necessarily irrelevant, and technical evidence remains authoritative.",
            "scenarios": scenarios,
            "visual_map_shape": str(visual_map["change_shape"]),
        }

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
        topic_sources = sorted(
            focus_nodes,
            key=lambda node: (
                0 if node.get("kind") == "TYPE" else 1,
                -self._node_score(node), str(node.get("label", "")),
            ),
        )
        for node in topic_sources:
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
        representative_sources = sorted(
            focus_nodes,
            key=lambda node: (
                0 if (
                    node.get("kind") == "TYPE"
                    and _ROLE_TYPE_PATTERN.search(str(node.get("label", "")))
                ) else 1,
                -self._node_score(node), str(node.get("label", "")),
            ),
        )
        for node in representative_sources:
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
        elif "EDITOR" in area_keys:
            analogy_zh = "帮助理解：像把原本分散的内容处理工作集中到一间 Unity 可视化工作台，由读取、编辑、校验和保存模块分工协作。"
            analogy_en = "Mental model: scattered content work moves into a Unity visual workbench whose loading, editing, validation and saving parts cooperate."
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

    def _visual_map(
        self,
        *,
        analysis: Mapping[str, object],
        nodes: Mapping[str, dict],
        edges: Sequence[dict],
        mappings: Sequence[dict],
        quick_view: Mapping[str, object],
    ) -> dict:
        """Build a bounded, evidence-only first-screen map.

        The map does not treat a list of changed symbols as a call chain.  It only
        advertises a verified flow when the analysis contains a changed edge.
        """

        analysis_digest = _non_empty_string(analysis.get("canonical_digest"), "analysis digest")
        focus_nodes = [
            node for node in self._focus_nodes(nodes, edges)
            if node.get("change") != "UNCHANGED_CONTEXT" and self._area(node) != "GENERATED"
        ]
        old_nodes = [node for node in focus_nodes if node.get("revision") == "OLD"]
        new_nodes = [node for node in focus_nodes if node.get("revision") == "NEW"]
        areas = {self._area(node) for node in focus_nodes}

        if areas and areas <= {"TEST"}:
            shape = "TEST_ONLY"
        elif areas and areas <= {"CONFIGURATION", "PROTOCOL"}:
            shape = "CONFIG_PROTOCOL"
        elif new_nodes and not old_nodes:
            shape = "ADDED"
        elif old_nodes and not new_nodes:
            shape = "REMOVED"
        elif old_nodes and new_nodes:
            shape = "MODIFIED"
        else:
            shape = "PARALLEL"

        focus_ids = {str(node["node_id"]) for node in focus_nodes}
        changed_edges = [
            edge for edge in edges
            if edge.get("change") != "UNCHANGED_CONTEXT"
            and edge.get("source_node_id") in focus_ids
            and edge.get("target_node_id") in focus_ids
        ]
        relationship_mode = "VERIFIED_FLOW" if changed_edges else "PARALLEL_FACTS"

        def picked(values: Sequence[dict], limit: int = _MAX_MAP_ITEMS) -> list[dict]:
            result: list[dict] = []
            seen: set[str] = set()
            ordered = sorted(values, key=lambda node: (
                0 if node.get("kind") == "TYPE" and _ROLE_TYPE_PATTERN.search(str(node.get("label", ""))) else 1,
                -self._node_score(node),
                str(node.get("label", "")),
                str(node.get("node_id", "")),
            ))
            for node in ordered:
                if node.get("kind") in {"CONDITION", "RETURN"} and result:
                    continue
                label = self._compact_label(node.get("label", ""))
                if label in seen:
                    continue
                seen.add(label)
                result.append(node)
                if len(result) == limit:
                    break
            return result

        def node_item(node: Mapping[str, object], role: str) -> dict:
            node_id = str(node["node_id"])
            label = self._compact_label(node.get("label", ""))
            change = str(node["change"])
            identity = f"{role}:{node_id}"
            return {
                "item_id": f"visual:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}",
                "role": role,
                "label_zh": f"{_CHANGE_ZH.get(change, change)} {label}" if role == "CHANGE" else label,
                "label_en": f"{_CHANGE_EN.get(change, change)} {label}" if role == "CHANGE" else label,
                "change": change,
                "confidence": str(node["provenance"]["confidence"]),
                "evidence_refs": [node_id],
                "locations": [node["location"]],
            }

        def context_item(
            seed: str,
            role: str,
            label_zh: str,
            label_en: str,
            refs: Sequence[str],
            locations: Sequence[Mapping[str, object]] = (),
        ) -> dict:
            identity = f"{role}:{seed}:{analysis_digest}"
            return {
                "item_id": f"visual:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}",
                "role": role,
                "label_zh": label_zh,
                "label_en": label_en,
                "change": "CONTEXT",
                "confidence": "STRUCTURAL",
                "evidence_refs": list(refs) or [analysis_digest],
                "locations": list(locations),
            }

        before = [node_item(node, "BEFORE") for node in picked(old_nodes)]
        after = [node_item(node, "AFTER") for node in picked(new_nodes)]
        change_items: list[dict] = []
        if shape == "MODIFIED":
            for mapping in sorted(mappings, key=lambda item: str(item["mapping_id"])):
                old = nodes[mapping["old_node_id"]]
                new = nodes[mapping["new_node_id"]]
                if old.get("change") == "UNCHANGED_CONTEXT" and mapping.get("kind") not in {
                    "RENAMED", "MOVED", "RENAMED_AND_MOVED"
                }:
                    continue
                identity = f"CHANGE:{mapping['mapping_id']}"
                old_label = self._compact_label(old["label"])
                new_label = self._compact_label(new["label"])
                if old_label == new_label and mapping["kind"] not in {
                    "RENAMED", "MOVED", "RENAMED_AND_MOVED"
                }:
                    continue
                visual_change = (
                    str(mapping["kind"])
                    if mapping["kind"] in {"RENAMED", "MOVED", "RENAMED_AND_MOVED"}
                    else str(old["change"])
                )
                change_items.append({
                    "item_id": f"visual:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}",
                    "role": "CHANGE",
                    "label_zh": f"{old_label} → {new_label}",
                    "label_en": f"{old_label} → {new_label}",
                    "change": visual_change,
                    "confidence": str(mapping["confidence"]),
                    "evidence_refs": [str(mapping["mapping_id"]), str(old["node_id"]), str(new["node_id"])],
                    "locations": [old["location"], new["location"]],
                })
                if len(change_items) == _MAX_MAP_CHANGES:
                    break
            seen_change_labels = {str(item["label_zh"]) for item in change_items}
            added_candidates = [node for node in new_nodes if node.get("change") == "ADDED"]
            for node in picked(added_candidates, _MAX_MAP_CHANGES):
                item = node_item(node, "CHANGE")
                if item["label_zh"] in seen_change_labels:
                    continue
                seen_change_labels.add(item["label_zh"])
                change_items.append(item)
                if len(change_items) == _MAX_MAP_CHANGES:
                    break
        if not change_items:
            preferred = new_nodes if new_nodes else old_nodes
            change_items = [node_item(node, "CHANGE") for node in picked(preferred, _MAX_MAP_CHANGES)]
        if not change_items:
            change_items = [context_item(
                "no-business-focus", "CHANGE", "没有进入快速视图的业务结构变化",
                "No business structural change entered the quick view", [analysis_digest],
            )]

        area_zh = "、".join(
            _AREA_LABELS[area][0] for area in sorted(areas, key=lambda item: _AREA_ORDER[item])
        ) or "代码结构"
        area_en = ", ".join(
            _AREA_LABELS[area][1] for area in sorted(areas, key=lambda item: _AREA_ORDER[item])
        ) or "code structure"
        core_refs = [ref for item in change_items for ref in item["evidence_refs"]]
        core_locations = [location for item in change_items for location in item["locations"]]

        if shape == "TEST_ONLY":
            headline_zh = "本次修改集中在测试保障；现有证据未显示业务运行代码的 C# 结构变化。"
            headline_en = "The change is confined to test coverage; current evidence shows no C# structural change in runtime business code."
            before = [context_item(
                "test-before", "BEFORE", "业务运行代码未进入本次 C# 变化范围",
                "Runtime business code is outside this C# change set", [analysis_digest],
            )]
            after = [context_item(
                "test-after", "AFTER", f"形成 {len(change_items)} 个代表性测试变化点",
                f"Produces {len(change_items)} representative test change points", core_refs, core_locations,
            )]
            labels = ("原有业务", "测试变化", "现在得到", "Existing behavior", "Test changes", "Result")
        elif shape == "ADDED":
            headline_zh = f"本次是在原版本没有对应结构的位置新增 {quick_view['primary_topic']}。"
            headline_en = f"This change adds {quick_view['primary_topic']} where no corresponding structure existed in the old revision."
            before = [context_item(
                "added-before", "BEFORE", "旧版本未发现对应结构信号",
                "No corresponding structural signal was found in the old revision", [analysis_digest],
            )]
            after = [context_item(
                "added-after", "AFTER", f"新增结构进入 {area_zh}",
                f"New structure is present in {area_en}", core_refs, core_locations,
            )]
            labels = ("原来没有", "新增核心", "现在具备", "Previously absent", "Added core", "Now present")
        elif shape == "REMOVED":
            headline_zh = f"本次从 {area_zh} 中移除了 {quick_view['primary_topic']}。"
            headline_en = f"This change removes {quick_view['primary_topic']} from {area_en}."
            after = [context_item(
                "removed-after", "AFTER", "新版本未保留对应结构信号",
                "The corresponding structural signal is absent from the new revision", core_refs, core_locations,
            )]
            labels = ("原有结构", "移除核心", "现在结果", "Previous structure", "Removed core", "Result")
        elif shape == "CONFIG_PROTOCOL":
            headline_zh = f"本次修改集中在 {area_zh}，需要结合真实导出数据确认最终消费效果。"
            headline_en = f"The change is concentrated in {area_en}; real exported data is still needed to verify consumption behavior."
            if not before:
                before = [context_item(
                    "data-before", "BEFORE", "旧版本未发现对应配置或协议结构",
                    "No corresponding configuration or protocol structure was found in the old revision", [analysis_digest],
                )]
            if not after:
                after = [context_item(
                    "data-after", "AFTER", "新版本未保留对应配置或协议结构",
                    "The corresponding configuration or protocol structure is absent from the new revision", core_refs, core_locations,
                )]
            labels = ("原数据结构", "配置/协议变化", "新数据结构", "Old data shape", "Data change", "New data shape")
        elif shape == "MODIFIED":
            if any(node.get("change") == "ADDED" for node in new_nodes):
                headline_zh = f"本次调整了 {area_zh} 的既有实现，并加入 {quick_view['primary_topic']} 等新结构。"
                headline_en = f"This change adjusts the existing {area_en} implementation and adds new structures including {quick_view['primary_topic']}."
            else:
                headline_zh = f"本次围绕 {quick_view['primary_topic']} 调整了 {area_zh} 的既有实现结构。"
                headline_en = f"This change adjusts the existing {area_en} implementation around {quick_view['primary_topic']}."
            labels = ("原来怎样", "核心调整", "现在怎样", "Before", "Core change", "After")
        else:
            headline_zh = "本次变化由若干并列代码事实组成，当前证据不足以把它们串成一条调用链。"
            headline_en = "The change contains parallel code facts; current evidence is insufficient to present them as one call chain."
            if not before:
                before = [context_item(
                    "parallel-before", "BEFORE", "没有可对照的旧版本聚焦对象",
                    "No focused old-revision object is available for comparison", [analysis_digest],
                )]
            if not after:
                after = [context_item(
                    "parallel-after", "AFTER", "变化结果保留在并列代码事实中",
                    "The result remains a set of parallel code facts", core_refs, core_locations,
                )]
            labels = ("原有证据", "并列变化", "当前结果", "Old evidence", "Parallel facts", "Current result")

        if relationship_mode == "VERIFIED_FLOW":
            relation_zh = "三列表示版本变化，不表示列中对象相互调用；分析另发现结构关系证据，可在详细页查看。"
            relation_en = "The columns show revision change, not calls between their items; separate structural relationship evidence is available in the detailed view."
        else:
            relation_zh = "中间项目是并列变化，不表示它们按显示顺序相互调用。"
            relation_en = "The middle items are parallel changes and do not imply calls in display order."

        risk_cards = quick_view.get("risk_cards", [])
        risk_zh = (
            str(risk_cards[0]["description_zh"])
            if isinstance(risk_cards, Sequence) and risk_cards else "没有自动提取到需要突出显示的风险。"
        )
        risk_en = (
            str(risk_cards[0]["description_en"])
            if isinstance(risk_cards, Sequence) and risk_cards else "No priority risk was automatically extracted."
        )
        return {
            "change_shape": shape,
            "relationship_mode": relationship_mode,
            "headline_zh": headline_zh,
            "headline_en": headline_en,
            "before_label_zh": labels[0],
            "change_label_zh": labels[1],
            "after_label_zh": labels[2],
            "before_label_en": labels[3],
            "change_label_en": labels[4],
            "after_label_en": labels[5],
            "before": before[:_MAX_MAP_ITEMS],
            "changes": change_items[:_MAX_MAP_CHANGES],
            "after": after[:_MAX_MAP_ITEMS],
            "relationship_note_zh": relation_zh,
            "relationship_note_en": relation_en,
            "impact_zh": str(quick_view["impact_summary_zh"]),
            "impact_en": str(quick_view["impact_summary_en"]),
            "risk_zh": risk_zh,
            "risk_en": risk_en,
        }

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
    """Render a self-contained, script-free scenario-first Chinese report."""

    def render(self, story: Mapping[str, object], *, repository_root: str | os.PathLike[str] | None = None) -> str:
        if story.get("schema_version") != "1.5.0" or story.get("language") != "zh-CN":
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
        visual = story["visual_map"]
        scenario_lens = story["scenario_lens"]
        daily = story["daily_brief"]
        primary_scenario = next(
            item for item in scenario_lens["scenarios"]
            if item["scenario_id"] == scenario_lens["primary_scenario_id"]
        )
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

        def visual_items(items: Sequence[Mapping[str, object]]) -> str:
            return "".join(
                f'<article class="map-item change-{esc(str(item["change"]).lower())}">'
                f'<strong>{esc(item["label_zh"])}</strong>'
                f'<small>{esc(item["confidence"])}</small>'
                f'{evidence_details(item["evidence_refs"], item["locations"])}</article>'
                for item in items
            )

        def map_connector() -> str:
            if visual["relationship_mode"] == "VERIFIED_FLOW":
                return '<div class="map-connector transition" aria-label="版本变化，不表示调用">⇒</div>'
            return '<div class="map-connector parallel" aria-label="并列事实，不表示调用">•••</div>'

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

        def takeaway_cards() -> str:
            return "".join(
                f'<article class="takeaway"><span>{index:02d}</span><div>'
                f'<strong>{esc(zh)}</strong><small>{esc(en)}</small></div></article>'
                for index, (zh, en) in enumerate(
                    zip(scenario_lens["takeaways_zh"], scenario_lens["takeaways_en"]),
                    start=1,
                )
            )

        def daily_checks() -> str:
            labels = {
                "PRIMARY_BEHAVIOR": "先确认主体验",
                "SECONDARY_BEHAVIOR": "再确认边界",
                "RELATIONSHIP_PATH": "沿路径核对",
                "EVIDENCE_BOUNDARY": "补齐证据",
                "REGRESSION": "回归相邻流程",
            }
            return "".join(
                f'<article class="daily-check"><span class="check-box">{index}</span><div>'
                f'<small>{esc(labels[item["kind"]])}</small><strong>{esc(item["action_zh"])}</strong>'
                f'{evidence_details(item["evidence_refs"])}</div></article>'
                for index, item in enumerate(daily["checks"], start=1)
            )

        def scenario_item(item: Mapping[str, object]) -> str:
            return (
                f'<article class="scenario-item change-{esc(str(item["change"]).lower())}" '
                f'id="{esc(item["item_id"])}"><strong>{esc(item["business_label_zh"])}</strong>'
                f'<small>{esc(item["business_label_en"])}</small>'
                f'<details class="evidence"><summary>查看技术名称与证据</summary>'
                f'<code>{esc(item["technical_label"])}</code>{source_location(item["location"])}'
                f'<code>{esc(", ".join(str(ref) for ref in item["evidence_refs"]))}</code></details></article>'
            )

        def scenario_views() -> tuple[str, str]:
            scenarios = scenario_lens["scenarios"]
            inputs = []
            labels = []
            panels = []
            selectors = []
            for index, scenario in enumerate(scenarios):
                control_id = f"scenario-view-{index}"
                inputs.append(
                    f'<input class="scenario-input" type="radio" name="scenario-view" id="{control_id}"'
                    f'{" checked" if index == 0 else ""}>'
                )
                labels.append(
                    f'<label for="{control_id}"><span>{esc(scenario["icon"])}</span>'
                    f'{esc(scenario["title_zh"])}</label>'
                )
                shape = str(scenario["change_shape"])
                before = "".join(scenario_item(item) for item in scenario["before"])
                after = "".join(scenario_item(item) for item in scenario["after"])
                if shape == "ADDED":
                    comparison = (
                        '<div class="scenario-transition transition-added">'
                        '<span><small>原来</small>没有这组聚焦能力</span><b aria-hidden="true">→</b>'
                        '<span><small>现在</small>形成新的工作场景</span></div>'
                        f'<div class="scenario-single"><h4>新增能力 / ADDED</h4>'
                        f'<div class="scenario-item-grid">{after}</div></div>'
                    )
                elif shape == "REMOVED":
                    comparison = (
                        '<div class="scenario-transition transition-removed">'
                        '<span><small>原来</small>存在这组聚焦能力</span><b aria-hidden="true">→</b>'
                        '<span><small>现在</small>已从场景中移除</span></div>'
                        f'<div class="scenario-single removed"><h4>移除能力 / REMOVED</h4>'
                        f'<div class="scenario-item-grid">{before}</div></div>'
                    )
                else:
                    before_content = before or '<p class="empty">没有旧版聚焦证据。</p>'
                    after_content = after or '<p class="empty">没有新版聚焦证据。</p>'
                    comparison = (
                        f'<div class="scenario-compare"><div><h4>原来 / BEFORE</h4>{before_content}</div>'
                        f'<div><h4>现在 / AFTER</h4>{after_content}</div></div>'
                    )
                item_lookup = {
                    str(item["item_id"]): item
                    for item in scenario["before"] + scenario["after"]
                }
                relationships = "".join(
                    f'<article class="route-row"><span class="route-node">'
                    f'{esc(item_lookup[item["source_item_id"]]["business_label_zh"])}</span>'
                    f'<span class="route-edge"><small>{esc(item["relation_zh"])}</small>'
                    f'<b aria-hidden="true">→</b></span><span class="route-node">'
                    f'{esc(item_lookup[item["target_item_id"]]["business_label_zh"])}</span>'
                    f'<span class="route-confidence">{esc(item["confidence"])}</span></article>'
                    for item in scenario["relationships"]
                )
                relationship_note = (
                    "下列关系由变化图中的明确边支持；对象顺序仍以关系证据为准。"
                    if scenario["relationship_mode"] == "VERIFIED_FLOW"
                    else "这些是回答同一问题的并列事实，不表示按显示顺序相互调用。"
                )
                relation_block = (
                    f'<div class="scenario-routes"><h4>已证实的关系路径 <small>VERIFIED PATHS</small></h4>'
                    f'{relationships}</div>' if relationships else ""
                )
                panels.append(
                    f'<section class="scenario-panel" data-scenario-index="{index}" '
                    f'data-scenario-shape="{esc(shape)}">'
                    f'<div class="scenario-heading"><div class="scenario-question"><span>要回答的问题 / QUESTION</span>'
                    f'<strong>{esc(scenario["question_zh"])}</strong>'
                    f'<p>{esc(scenario["answer_zh"])}</p></div>'
                    f'<span class="scenario-shape shape-{esc(shape.lower())}">{esc(shape)}</span></div>'
                    f'{comparison}'
                    f'<p class="scenario-note">{esc(relationship_note)}</p>{relation_block}</section>'
                )
                selectors.append(
                    f'#{control_id}:checked~.scenario-nav label[for={control_id}]'
                    f'{{background:var(--blue);color:white;border-color:var(--blue)}}'
                    f'#{control_id}:checked~.scenario-panels .scenario-panel[data-scenario-index="{index}"]'
                    f'{{display:block}}'
                )
            markup = (
                f'{"".join(inputs)}<nav class="scenario-nav">{"".join(labels)}</nav>'
                f'<div class="scenario-panels">{"".join(panels)}</div>'
            )
            return markup, "".join(selectors)

        scenario_markup, scenario_css = scenario_views()

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
                    f'<details class="stage"><summary><span class="stage-number">{stage["order"]}</span>'
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
:root{{--bg:#f6f8fc;--panel:#fff;--ink:#172033;--muted:#667085;--line:#dce3ee;--blue:#3157d5;--blue-strong:#173ca7;--blue-soft:#eef3ff;--cyan:#0e91a5;--green:#16803c;--red:#c73535;--amber:#a96308;--purple:#7657c5;--shadow:0 12px 32px #253b6b12;--shadow-hover:0 16px 36px #253b6b1c}}
*{{box-sizing:border-box}} body{{margin:0;overflow-x:hidden;background:radial-gradient(circle at 8% 0,#eaf0ff 0,transparent 30%),linear-gradient(#f9fbff,#f4f6fa);color:var(--ink);font:15px/1.65 Inter,"Segoe UI","Microsoft YaHei",sans-serif}}
main{{max-width:1320px;margin:auto;padding:26px 30px}} header{{position:relative;overflow:hidden;background:linear-gradient(135deg,#101b42,#173ca7 62%,#167e9a);color:white;border-radius:22px;padding:25px 32px;box-shadow:0 22px 55px #173ca72c}}
header:after{{content:"";position:absolute;width:240px;height:240px;right:-65px;top:-125px;border:1px solid #ffffff30;border-radius:50%;box-shadow:0 0 0 32px #ffffff0b,0 0 0 68px #ffffff08}} .eyebrow{{font-size:10px;font-weight:800;letter-spacing:.14em;color:#b9d5ff}} .header-lead{{position:relative;z-index:1;max-width:880px;font-size:17px;font-weight:650;overflow-wrap:anywhere}} h1{{position:relative;z-index:1;margin:6px 0;font-size:29px;letter-spacing:-.02em;overflow-wrap:anywhere}} h2{{margin:30px 0 13px;letter-spacing:-.015em}} h3{{margin:0 0 7px}} h4{{margin:0 0 8px}} p{{margin:6px 0}} small,.en{{color:var(--muted)}} header .en{{position:relative;z-index:1;color:#cddcff;overflow-wrap:anywhere;font-size:13px}} .digest{{position:relative;z-index:1;word-break:break-all;opacity:.64;font-size:10px}}
.status{{float:right;position:relative;z-index:2;display:inline-block;padding:3px 10px;border-radius:999px;background:#ffffff1f;border:1px solid #ffffff4a;font-weight:700}} .partial-note{{margin-top:11px;padding:8px 12px;border-radius:9px;background:#ffefc5;color:#724500;font-size:13px}}
.tab-input{{position:absolute;opacity:0;pointer-events:none}} .tab-nav{{display:flex;gap:8px;margin:20px 0 0;padding:6px;background:#e5eaf3;border-radius:14px;position:sticky;top:8px;z-index:5;box-shadow:var(--shadow)}}
.tab-nav label{{flex:1;text-align:center;padding:10px 12px;border-radius:10px;cursor:pointer;font-weight:750;color:var(--muted)}} .tab-nav label small{{display:block;font-size:10px;font-weight:550}} #tab-daily:checked~.tab-nav label[for=tab-daily],#tab-quick:checked~.tab-nav label[for=tab-quick],#tab-deep:checked~.tab-nav label[for=tab-deep]{{background:white;color:var(--blue);box-shadow:0 4px 14px #26395c18}}
.tab-panel{{display:none}} #tab-daily:checked~.daily-panel,#tab-quick:checked~.quick-panel,#tab-deep:checked~.deep-panel{{display:block}} .hero-summary{{font-size:21px;font-weight:700;margin:24px 0 10px}} .analogy{{padding:16px 18px;border:1px dashed #8aa8ef;background:#f6f9ff;border-radius:13px;color:#25447f}}
.daily-hero{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:22px;align-items:start;margin-top:24px;padding:25px 27px;border:1px solid var(--line);border-radius:20px;background:linear-gradient(145deg,#fff,#f5f8ff);box-shadow:var(--shadow)}} .daily-kicker{{display:block;color:var(--blue);font-size:10px;font-weight:850;letter-spacing:.12em}} .daily-hero h2{{margin:3px 0 8px;font-size:26px}} .daily-statement{{display:block;max-width:990px;font-size:21px;line-height:1.55;letter-spacing:-.01em}} .daily-impact{{margin-top:12px;padding-top:11px;border-top:1px solid var(--line);color:#536079}} .daily-impact b{{color:var(--ink)}} .daily-confidence{{margin-top:11px;padding:9px 12px;border-radius:10px;background:#fff4d6;color:#795010;font-size:13px}} .daily-check-title{{display:flex;justify-content:space-between;align-items:end;gap:12px;margin-top:28px}} .daily-check-title h2{{margin:0}} .daily-check-title p{{color:var(--muted)}} .daily-checks{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}} .daily-check{{display:flex;gap:13px;min-height:132px;padding:16px;background:white;border:1px solid var(--line);border-radius:15px;box-shadow:var(--shadow)}} .daily-check>div{{min-width:0}} .daily-check small,.daily-check strong{{display:block}} .daily-check small{{color:var(--blue);font-size:10px;font-weight:800;letter-spacing:.06em}} .daily-check strong{{margin-top:5px;line-height:1.55}} .check-box{{display:grid;place-items:center;flex:0 0 30px;height:30px;border:2px solid #8fa7e8;border-radius:9px;color:var(--blue);font-weight:800}} .daily-actions{{display:flex;justify-content:flex-end;gap:9px;margin-top:15px}} .daily-actions label{{padding:10px 15px;border:1px solid #b9c8eb;border-radius:10px;background:white;color:var(--blue);font-weight:750;cursor:pointer}} .daily-actions label:first-child{{background:var(--blue);border-color:var(--blue);color:white}}
.quick-intro{{display:flex;justify-content:space-between;gap:24px;align-items:flex-end;margin:26px 0 13px;padding:0 3px}} .quick-intro small{{display:block;color:var(--blue);font-size:11px;font-weight:800;letter-spacing:.1em}} .quick-intro h2{{margin:2px 0 3px;font-size:25px}} .quick-intro p{{max-width:900px;color:#43516a}} .shape-tag{{display:inline-grid;place-items:center;min-width:92px;padding:7px 12px;border-radius:999px;background:#e8efff;color:var(--blue);font-size:11px;font-weight:800;letter-spacing:.08em}}
.takeaways{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}} .takeaway{{display:flex;gap:13px;min-height:104px;padding:17px;background:linear-gradient(145deg,#fff,#f8faff);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow)}} .takeaway>span{{display:grid;place-items:center;flex:0 0 34px;height:34px;border-radius:11px;background:var(--blue);color:white;font:800 12px/1 system-ui}} .takeaway strong,.takeaway small{{display:block}} .takeaway strong{{font-size:17px;line-height:1.45}} .takeaway small{{margin-top:4px}} .outcome-card{{display:flex;gap:12px;align-items:flex-start;margin-top:12px;padding:12px 15px;border-radius:12px;background:#eef3ff;color:#354e83}} .outcome-card>span{{font-size:18px}} .outcome-card p{{margin:0;color:var(--muted)}}
.scenario-input{{position:absolute;opacity:0;pointer-events:none}} .scenario-nav{{display:flex;gap:8px;overflow-x:auto;padding:7px;background:#e8edf5;border:1px solid #dfe5ef;border-radius:14px;margin:12px 0}} .scenario-nav label{{display:flex;align-items:center;gap:7px;white-space:nowrap;padding:10px 14px;border:1px solid transparent;border-radius:10px;background:#ffffffcf;color:var(--muted);cursor:pointer;font-weight:700;transition:transform .16s ease,box-shadow .16s ease}} .scenario-nav label:hover{{transform:translateY(-1px);box-shadow:0 5px 12px #33466d15}} .scenario-panel{{display:none;padding:20px;background:white;border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow)}} .scenario-heading{{display:flex;gap:14px;align-items:flex-start}} .scenario-question{{flex:1;padding:14px 17px;border-left:5px solid var(--blue);background:linear-gradient(90deg,#f2f6ff,#fafcff);border-radius:12px}} .scenario-question>span{{display:block;color:var(--blue);font-size:10px;font-weight:800;letter-spacing:.08em}} .scenario-question>strong{{display:block;font-size:20px}} .scenario-question p{{color:#4b5870}} .scenario-shape{{padding:5px 10px;border:1px solid #bac9ef;border-radius:999px;color:var(--blue);font-size:10px;font-weight:800;letter-spacing:.08em}} .shape-added{{color:var(--green);border-color:#abd8ba;background:#f1fbf4}} .shape-removed{{color:var(--red);border-color:#e7b4b4;background:#fff5f5}}
.scenario-compare{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:14px}} .scenario-compare>div,.scenario-single{{padding:15px;border:1px solid var(--line);border-radius:13px;background:#fbfcff}} .scenario-single{{margin-top:12px;border-top:4px solid var(--green);background:#f9fdfb}} .scenario-single.removed{{border-top-color:var(--red);background:#fffafa}} .scenario-item-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(235px,1fr));gap:9px}} .scenario-item-grid .scenario-item{{margin:0}} .scenario-transition{{display:grid;grid-template-columns:1fr 36px 1fr;align-items:center;gap:10px;margin-top:14px;padding:11px 14px;border-radius:13px;background:#f3f6fb;color:#41506b;text-align:center}} .scenario-transition span{{display:block;padding:5px}} .scenario-transition small{{display:block;font-size:10px;font-weight:800;letter-spacing:.08em}} .scenario-transition b{{color:var(--blue);font-size:20px}} .transition-added span:last-child{{color:var(--green);font-weight:700}} .transition-removed span:last-child{{color:var(--red);font-weight:700}}
.scenario-item{{padding:12px 13px;margin:8px 0;border:1px solid var(--line);border-left:4px solid #94a3b8;border-radius:10px;background:white;overflow-wrap:anywhere}} .scenario-item>strong,.scenario-item>small{{display:block}} .scenario-note{{font-size:13px;color:#35558d;background:#edf3ff;padding:9px 12px;border-radius:9px}} .scenario-routes{{margin-top:13px;padding:14px;border:1px solid #cfd9ed;border-radius:13px;background:linear-gradient(145deg,#fbfdff,#f4f7fd)}} .scenario-routes h4 small{{margin-left:6px;font-size:10px;letter-spacing:.08em}} .route-row{{display:grid;grid-template-columns:minmax(140px,1fr) minmax(100px,.55fr) minmax(140px,1fr) auto;align-items:center;gap:8px;margin-top:8px}} .route-node{{padding:9px 11px;border:1px solid var(--line);border-radius:9px;background:white;font-weight:700;text-align:center}} .route-edge{{display:flex;align-items:center;gap:7px;color:var(--blue)}} .route-edge:before{{content:"";height:2px;flex:1;background:linear-gradient(90deg,#b8c7ec,var(--blue))}} .route-edge small{{white-space:nowrap;color:var(--blue);font-weight:700}} .route-edge b{{font-size:17px}} .route-confidence{{padding:2px 7px;border-radius:999px;background:#e7eefc;color:#53688f;font-size:10px;font-weight:700}}
{scenario_css}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}} .change-card{{display:flex;gap:11px;background:white;border:1px solid var(--line);border-top:4px solid var(--blue);border-radius:14px;padding:16px;box-shadow:var(--shadow);min-width:0}} .change-card>div:last-child{{min-width:0}} .card-icon{{font-size:25px}} .change-card p{{font-size:14px;overflow-wrap:anywhere}} .evidence summary{{cursor:pointer;color:var(--blue);font-size:12px}}
.change-map{{display:grid;grid-template-columns:minmax(0,1fr) 44px minmax(0,1.1fr) 44px minmax(0,1fr);gap:10px;align-items:stretch;margin-top:14px}} .map-column{{background:white;border:1px solid var(--line);border-radius:16px;padding:16px;box-shadow:var(--shadow)}} .map-column h3{{display:flex;justify-content:space-between;gap:8px}} .map-column h3 small{{font-weight:500}} .map-before{{border-top:5px solid #8a95a8}} .map-change{{border-top:5px solid var(--amber);background:#fffdf8}} .map-after{{border-top:5px solid var(--blue)}} .map-item{{padding:11px 12px;margin-top:9px;border:1px solid var(--line);border-left:4px solid #94a3b8;border-radius:10px;background:#fafcff;overflow-wrap:anywhere}} .map-item strong,.map-item small{{display:block}} .map-connector{{display:grid;place-items:center;font-size:28px;font-weight:800;color:var(--blue)}} .map-connector.parallel{{font-size:19px;letter-spacing:2px;color:#98a2b3}} .map-note{{margin:12px 0 0;padding:10px 13px;border-radius:10px;background:#edf3ff;color:#35558d;font-size:13px}} .quick-support{{margin-top:18px;padding:13px 15px;background:#eef2f7;border-radius:12px}} .quick-support>summary{{cursor:pointer;font-weight:700}} .quick-support .analogy{{margin:13px 0}}
.comparison,.two-columns,.layers,.lanes,.stage-body{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:17px}} .lane,.panel,.claim,.chain,.stage,.decision,.risk{{background:var(--panel);border:1px solid var(--line);border-radius:14px}} .lane,.panel{{padding:18px}} .lane-old{{border-top:5px solid #8a95a8}} .lane-new{{border-top:5px solid var(--blue)}}
.flow-step{{display:flex;gap:11px;padding:12px;border:1px solid var(--line);border-left:4px solid #94a3b8;border-radius:10px;background:#fafcff}} .flow-step>div{{min-width:0}} .flow-step strong,.flow-step span,.location{{display:block}} .flow-step span,.location{{color:var(--muted);font-size:12px;overflow-wrap:anywhere}} .step-number,.stage-number{{display:grid!important;place-items:center;flex:0 0 25px;height:25px;border-radius:50%;background:var(--blue-soft);color:var(--blue)!important;font-weight:700}} .flow-arrow{{padding:2px 0 2px 11px;color:#7b8aa5}}
.risk{{display:flex;gap:12px;padding:14px;margin:10px 0;border-left:5px solid var(--amber)}} .risk>span{{font-size:11px;font-weight:800;color:var(--amber)}} .risk-high{{border-left-color:var(--red)}} .risk-high>span{{color:var(--red)}}
.method-note{{padding:15px 17px;border-left:5px solid var(--purple);background:#f6f2ff;border-radius:11px}} .deep-section{{margin:18px 0;padding:13px 15px;background:#eef2f7;border-radius:14px}} .deep-section>summary{{cursor:pointer;font-weight:800}} .stage{{margin:12px 0;overflow:hidden}} .stage>summary{{display:flex;align-items:center;gap:11px;padding:15px;cursor:pointer;background:#f8faff}} .stage>summary small{{display:block}} .stage-icon{{font-size:24px}} .stage-body{{padding:16px}} .stage-body ul{{padding-left:18px}} .stage-body li{{margin:7px 0;overflow-wrap:anywhere}} .relation{{color:var(--blue)}}
.decision{{display:flex;gap:12px;padding:14px;margin:10px 0;border-left:4px solid var(--amber)}} .decision-mark{{font-size:23px;color:var(--amber)}} .decision small{{display:block}} .technical{{margin-top:24px;padding:16px;background:#eef2f7;border-radius:14px}} .technical>summary{{cursor:pointer;font-weight:800}}
.metrics{{display:grid;grid-template-columns:repeat(6,minmax(90px,1fr));gap:9px;margin:16px 0}} .metric{{padding:12px;background:white;border:1px solid var(--line);border-radius:10px}} .metric strong{{display:block;font-size:20px}} .layers{{grid-template-columns:repeat(3,minmax(0,1fr))}} .claim{{padding:13px;margin:9px 0;border-left:4px solid var(--blue)}} .claim.source_evidence{{border-left-color:var(--purple)}} .claim.intent_inference{{border-left-color:var(--amber)}} .claim-tag{{font-size:11px;color:var(--muted)}}
.chain{{padding:12px;margin:10px 0}} .chain-node{{padding:10px 12px;border-radius:9px;background:#f8fafc;border-left:4px solid #94a3b8;overflow-wrap:anywhere}} .chain-node span{{display:block;color:var(--muted);font-size:12px}} .arrow{{padding:6px 18px;color:var(--blue)}} .arrow span:before{{content:"↓  "}} .arrow small{{display:block;margin-left:18px}}
.change-added{{border-color:var(--green)!important}} .change-removed{{border-color:var(--red)!important}} .change-updated{{border-color:var(--amber)!important}} .change-moved,.change-renamed,.change-renamed_and_moved{{border-color:var(--blue)!important}} .badge.change-added{{color:var(--green)}} .badge.change-removed{{color:var(--red)}} .badge.change-updated{{color:var(--amber)}} .badge.change-moved,.badge.change-renamed,.badge.change-renamed_and_moved{{color:var(--blue)}}
table{{width:100%;border-collapse:collapse;background:white;border-radius:12px;overflow:hidden}} th,td{{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}} th{{background:#edf2f8}} code{{display:block;font-size:11px;word-break:break-all;color:#58647a}} .badge{{display:inline-block;border:1px solid currentColor;border-radius:999px;padding:2px 8px;font-size:11px}} .empty{{color:var(--muted)}} footer{{margin:30px 0;color:var(--muted)}}
@media(max-width:1050px){{.cards{{grid-template-columns:repeat(2,1fr)}}.change-map{{grid-template-columns:1fr}}.map-connector{{min-height:22px;transform:rotate(90deg)}}.map-connector.parallel{{transform:none}}.route-row{{grid-template-columns:1fr 90px 1fr}}.route-confidence{{display:none}}.daily-checks{{grid-template-columns:1fr}}}} @media(max-width:780px){{main{{padding:13px}}header{{padding:23px 22px}}.status{{float:none;margin-bottom:7px}}.cards,.comparison,.two-columns,.layers,.lanes,.stage-body,.scenario-compare,.takeaways{{grid-template-columns:1fr}}.metrics{{grid-template-columns:repeat(2,1fr)}}.tab-nav{{position:static;overflow-x:auto}}.tab-nav label{{flex:0 0 auto;min-width:155px}}.daily-hero{{grid-template-columns:1fr;padding:20px}}.daily-statement{{font-size:18px}}.daily-check-title{{display:block}}.daily-actions{{justify-content:stretch;flex-direction:column}}.daily-actions label{{text-align:center}}.quick-intro{{align-items:flex-start;flex-direction:column;gap:8px}}.scenario-heading{{display:block}}.scenario-shape{{display:inline-block;margin-top:9px}}.scenario-transition{{grid-template-columns:1fr 28px 1fr}}.route-row{{grid-template-columns:1fr}}.route-edge{{justify-content:center}}.route-edge:before{{max-width:52px}}}}
</style></head><body><main data-story-digest="{esc(story["canonical_digest"])}">
<header><span class="status">{status}</span><div class="eyebrow">AEH CHANGE STORY · SCENARIO LENS</div><h1>{esc(story["title"])}</h1>
<p class="header-lead">{esc(scenario_lens["summary_zh"])}</p><p class="en">{esc(scenario_lens["summary_en"])}</p>
{('<div class="partial-note">PARTIAL：当前结论仅覆盖变更 C# 文件，所有关系最高为结构级证据。</div>' if story["status"] == "PARTIAL" else '')}
<p class="digest">Analysis {esc(story["analysis_digest"])} · Story {esc(story["canonical_digest"])}</p></header>
<input class="tab-input" type="radio" name="story-tab" id="tab-daily" checked><input class="tab-input" type="radio" name="story-tab" id="tab-quick"><input class="tab-input" type="radio" name="story-tab" id="tab-deep">
<nav class="tab-nav"><label for="tab-daily">◎ 只看结论 <small>30 秒 · DAILY</small></label><label for="tab-quick">◇ 理解改法 <small>3 分钟 · READ</small></label><label for="tab-deep">▦ 核对证据 <small>按需 · FULL</small></label></nav>
<section class="tab-panel daily-panel">
<section class="daily-hero"><div><small class="daily-kicker">TODAY'S CHANGE BRIEF</small><h2>{esc(daily["question_zh"])}</h2><strong class="daily-statement">{esc(daily["what_changed_zh"])}</strong><p class="daily-impact"><b>与你的工作有什么关系：</b>{esc(daily["why_it_matters_zh"])}</p>{(f'<p class="daily-confidence">{esc(daily["confidence_note_zh"])}</p>' if story["status"] == "PARTIAL" else '')}</div><span class="shape-tag">主场景 · {esc(daily["change_shape"])}</span></section>
<section class="quick-intro"><div><small>THREE THINGS TO REMEMBER</small><h2>先记住这三点</h2></div></section><section class="takeaways">{takeaway_cards()}</section>
<div class="daily-check-title"><div><small class="daily-kicker">NEXT ACTIONS</small><h2>建议先验证</h2></div><p>这是检查建议，不是代码事实。</p></div><section class="daily-checks">{daily_checks()}</section>
<div class="daily-actions"><label for="tab-quick">继续理解改法 →</label><label for="tab-deep">直接核对证据</label></div>
</section>
<section class="tab-panel quick-panel">
<section class="quick-intro"><div><small>SCENARIO READING</small><h2>选择你要理解的问题</h2><p>{esc(scenario_lens["outcome_zh"])}</p></div><span class="shape-tag">主场景 · {esc(primary_scenario["change_shape"])}</span></section><div class="outcome-card"><span>◎</span><p>{esc(scenario_lens["scope_note_zh"])}</p></div>{scenario_markup}
<section class="two-columns"><div><h2>影响范围</h2><div class="panel"><p>{esc(visual["impact_zh"])}</p></div></div><div><h2>最需要注意</h2><div class="panel"><p>{esc(visual["risk_zh"])}</p></div></div></section>
<details class="quick-support"><summary>展开完整 OLD / NEW 版本对照</summary><section class="change-map" data-change-shape="{esc(visual["change_shape"])}" data-relationship-mode="{esc(visual["relationship_mode"])}">
<div class="map-column map-before"><h3>{esc(visual["before_label_zh"])} <small>{esc(visual["before_label_en"])}</small></h3>{visual_items(visual["before"])}</div>
{map_connector()}<div class="map-column map-change"><h3>{esc(visual["change_label_zh"])} <small>{esc(visual["change_label_en"])}</small></h3>{visual_items(visual["changes"])}</div>
{map_connector()}<div class="map-column map-after"><h3>{esc(visual["after_label_zh"])} <small>{esc(visual["after_label_en"])}</small></h3>{visual_items(visual["after"])}</div></section>
<p class="map-note">证据边界：{esc(visual["relationship_note_zh"])}</p></details>
<details class="quick-support"><summary>展开辅助理解与涉及领域</summary><div class="analogy">{esc(quick["analogy_zh"])}</div><section class="cards">{quick_cards()}</section></details>
</section>
<section class="tab-panel deep-panel">
<p class="hero-summary">{esc(deep["strategy_summary_zh"])}</p><div class="method-note">{esc(deep["method_note_zh"])}</div>
<details class="deep-section"><summary>按业务层展开代表对象与关系</summary>{stages()}</details>
<details class="deep-section"><summary>展开新增决策与退出点</summary><section class="two-columns">{decisions()}</section></details>
<div class="panel"><strong>证据说明</strong><p>{esc(deep["evidence_summary_zh"])}</p></div>
<details class="technical"><summary>展开完整技术证据（符号、关系、限制）</summary>
<section class="metrics"><div class="metric"><strong>{counts["added_nodes"]}</strong><span>新增节点</span></div><div class="metric"><strong>{counts["removed_nodes"]}</strong><span>删除节点</span></div><div class="metric"><strong>{counts["updated_node_pairs"]}</strong><span>修改节点对</span></div><div class="metric"><strong>{counts["moved_node_pairs"]}</strong><span>移动节点对</span></div><div class="metric"><strong>{counts["added_edges"]}</strong><span>新增关系</span></div><div class="metric"><strong>{counts["removed_edges"]}</strong><span>删除关系</span></div></section>
<h2>修改依据</h2><section class="layers"><div class="panel"><h3>代码事实</h3>{claim_cards(facts,"没有可展示的代码事实。")}</div><div class="panel"><h3>来源证据</h3>{claim_cards(sources,"未提供用户需求、AI 计划或提交说明。")}</div><div class="panel"><h3>意图推断</h3>{claim_cards(inferences,"没有足够代码模式支持意图推断。")}</div></section>
<h2>完整原链路 → 新链路</h2><section class="lanes"><div class="panel"><h3>原链路</h3>{chain_cards(story["lanes"]["old"])}</div><div class="panel"><h3>新链路</h3>{chain_cards(story["lanes"]["new"])}</div></section>
<h2>符号变化</h2><table><thead><tr><th>类型</th><th>对象</th><th>置信度</th><th>代码位置</th></tr></thead><tbody>{change_rows()}</tbody></table>
<section class="lanes"><div><h2>直接影响</h2><div class="panel"><ul>{impacts}</ul></div></div><div><h2>限制与未知项</h2><div class="panel"><ul>{limitations}</ul></div></div></section>
</details></section>
<footer>AEH Change Lens · 中文优先离线报告 · 场景优先 + 按需证据 · 不执行目标项目代码 · 不声称还原隐藏思维链</footer>
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
