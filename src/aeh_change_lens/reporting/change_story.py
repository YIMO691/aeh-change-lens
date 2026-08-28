from __future__ import annotations

import hashlib
import html
import json
import os
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
        headline_zh = (
            f"新增 {summary['added_nodes']} 个节点、删除 {summary['removed_nodes']} 个节点，"
            f"修改 {summary['updated_node_pairs']} 对、移动 {summary['moved_node_pairs']} 对；"
            f"关系新增 {summary['added_edges']} 条、删除 {summary['removed_edges']} 条。"
        )
        headline_en = (
            f"{summary['added_nodes']} nodes added, {summary['removed_nodes']} removed, "
            f"{summary['updated_node_pairs']} updated and {summary['moved_node_pairs']} moved; "
            f"{summary['added_edges']} relationships added and {summary['removed_edges']} removed."
        )
        semantic = {
            "schema_version": "1.0.0",
            "story_id": f"story:{analysis_digest[:24]}",
            "language": "zh-CN",
            "status": str(analysis["status"]),
            "title": title,
            "analysis_digest": analysis_digest,
            "revisions": analysis["revisions"],
            "overview": {
                "headline_zh": headline_zh,
                "headline_en": headline_en,
                "counts": summary,
            },
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
    """Render a self-contained, script-free Chinese-first HTML report."""

    def render(self, story: Mapping[str, object], *, repository_root: str | os.PathLike[str] | None = None) -> str:
        if story.get("schema_version") != "1.0.0" or story.get("language") != "zh-CN":
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
        claims = story["claims"]
        facts = [item for item in claims if item["layer"] == "CODE_FACT"]
        sources = [item for item in claims if item["layer"] == "SOURCE_EVIDENCE"]
        inferences = [item for item in claims if item["layer"] == "INTENT_INFERENCE"]

        def location(node: Mapping[str, object]) -> str:
            item = node["location"]
            label = f"{item['path']}:{item['start_line']}"
            if repo is None or not new_is_worktree or item["revision_role"] != "NEW":
                return f'<span class="location">{esc(label)}</span>'
            candidate = (repo / Path(str(item["path"]))).resolve()
            try:
                candidate.relative_to(repo)
            except ValueError:
                return f'<span class="location">{esc(label)}</span>'
            return f'<a class="location" href="{esc(candidate.as_uri())}#L{item["start_line"]}">{esc(label)}</a>'

        def claim_cards(items: Sequence[Mapping[str, object]], empty: str) -> str:
            if not items:
                return f'<p class="empty">{esc(empty)}</p>'
            return "".join(
                f'<article class="claim {esc(item["layer"].lower())}">'
                f'<div class="claim-tag">{esc(item["layer"])} · {esc(item["confidence"])}</div>'
                f'<p>{esc(item["statement_zh"])}</p><small>{esc(item["statement_en"])}</small>'
                f'<details><summary>证据引用</summary><code>{esc(", ".join(item["evidence_refs"]))}</code></details>'
                f'</article>' for item in items
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
                locations = " → ".join(
                    f"{entry['path']}:{entry['start_line']}" for entry in item["locations"]
                )
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
:root{{--bg:#f5f7fb;--panel:#fff;--ink:#172033;--muted:#667085;--line:#dfe4ec;--blue:#2563eb;--green:#16803c;--red:#c73535;--amber:#b36b00;--purple:#7657c5}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif}}
main{{max-width:1440px;margin:auto;padding:32px}} header{{background:linear-gradient(135deg,#172554,#1d4ed8);color:white;border-radius:18px;padding:30px;box-shadow:0 12px 35px #1d4ed833}}
h1{{margin:0 0 8px;font-size:30px}} h2{{margin:34px 0 14px}} h3{{margin:0 0 12px}} .en{{opacity:.72;margin:0}} .digest{{word-break:break-all;opacity:.75;font-size:12px}}
.status{{display:inline-block;padding:4px 10px;border-radius:999px;background:#ffffff22;border:1px solid #ffffff44}}
.metrics{{display:grid;grid-template-columns:repeat(6,minmax(100px,1fr));gap:10px;margin:18px 0}}
.metric,.panel,.claim,.chain{{background:var(--panel);border:1px solid var(--line);border-radius:12px}}
.metric{{padding:14px}} .metric strong{{display:block;font-size:22px}} .metric span,small{{color:var(--muted)}}
.layers,.lanes{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}} .layers{{grid-template-columns:repeat(3,minmax(0,1fr))}}
.panel{{padding:18px;min-width:0}} .claim{{padding:13px;margin:10px 0;border-left:4px solid var(--blue)}}
.claim.source_evidence{{border-left-color:var(--purple)}} .claim.intent_inference{{border-left-color:var(--amber)}} .claim p{{margin:5px 0}} .claim-tag{{font-size:11px;letter-spacing:.04em;color:var(--muted)}}
.chain{{padding:12px;margin:10px 0}} .chain-node{{padding:10px 12px;border-radius:9px;background:#f8fafc;border-left:4px solid #94a3b8;overflow-wrap:anywhere}}
.chain-node span,.location{{display:block;color:var(--muted);font-size:12px}} .arrow{{padding:6px 18px;color:var(--blue)}} .arrow span:before{{content:"↓  "}} .arrow small{{display:block;margin-left:18px}}
.change-added{{border-color:var(--green)!important;color:var(--green)}} .change-removed{{border-color:var(--red)!important;color:var(--red)}} .change-updated{{border-color:var(--amber)!important;color:var(--amber)}} .change-moved,.change-renamed,.change-renamed_and_moved{{border-color:var(--blue)!important;color:var(--blue)}}
table{{width:100%;border-collapse:collapse;background:white;border-radius:12px;overflow:hidden}} th,td{{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}} th{{background:#edf2f8}} code{{font-size:12px;word-break:break-all}} .badge{{display:inline-block;border:1px solid currentColor;border-radius:999px;padding:2px 8px;font-size:12px}} .empty{{color:var(--muted)}} details{{margin-top:7px}} footer{{margin:30px 0;color:var(--muted)}}
@media(max-width:900px){{main{{padding:14px}}.metrics{{grid-template-columns:repeat(2,1fr)}}.layers,.lanes{{grid-template-columns:1fr}}}}
</style></head><body><main data-story-digest="{esc(story["canonical_digest"])}">
<header><span class="status">{status}</span><h1>{esc(story["title"])}</h1>
<p>{esc(overview["headline_zh"])}</p><p class="en">{esc(overview["headline_en"])}</p>
<p class="digest">Analysis {esc(story["analysis_digest"])} · Story {esc(story["canonical_digest"])}</p></header>
<section class="metrics">
<div class="metric"><strong>{counts["added_nodes"]}</strong><span>新增节点</span></div><div class="metric"><strong>{counts["removed_nodes"]}</strong><span>删除节点</span></div>
<div class="metric"><strong>{counts["updated_node_pairs"]}</strong><span>修改节点对</span></div><div class="metric"><strong>{counts["moved_node_pairs"]}</strong><span>移动节点对</span></div>
<div class="metric"><strong>{counts["added_edges"]}</strong><span>新增关系</span></div><div class="metric"><strong>{counts["removed_edges"]}</strong><span>删除关系</span></div></section>
<h2>修改依据 <small>事实、来源和推断严格分层</small></h2><section class="layers">
<div class="panel"><h3>代码事实</h3>{claim_cards(facts,"没有可展示的代码事实。")}</div>
<div class="panel"><h3>来源证据</h3>{claim_cards(sources,"未提供用户需求、AI 计划或提交说明。")}</div>
<div class="panel"><h3>意图推断</h3>{claim_cards(inferences,"没有足够代码模式支持意图推断。")}</div></section>
<h2>原链路 → 新链路</h2><section class="lanes">
<div class="panel old-lane"><h3>原链路 <small>Old path</small></h3>{chain_cards(story["lanes"]["old"])}</div>
<div class="panel new-lane"><h3>新链路 <small>New path</small></h3>{chain_cards(story["lanes"]["new"])}</div></section>
<h2>符号变化</h2><table><thead><tr><th>类型</th><th>对象</th><th>置信度</th><th>代码位置</th></tr></thead><tbody>{change_rows()}</tbody></table>
<section class="lanes"><div><h2>影响范围</h2><div class="panel"><ul>{impacts}</ul></div></div>
<div><h2>限制与未知项</h2><div class="panel"><ul>{limitations}</ul></div></div></section>
<footer>AEH Change Lens · 中文优先离线报告 · 不执行目标项目代码 · 不声称还原隐藏思维链</footer>
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
