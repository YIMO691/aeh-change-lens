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
        change_canvas = self._change_canvas(
            status=str(analysis["status"]),
            scenario_lens=scenario_lens,
            daily_brief=daily_brief,
        )
        semantic = {
            "schema_version": "1.7.0",
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
            "change_canvas": change_canvas,
            "deep_dive": deep_dive,
            "lanes": lanes,
            "changes": changes,
            "claims": sorted(claims, key=lambda item: item["claim_id"]),
            "impacts": self._impacts(nodes, edges),
            "limitations": sorted(set(limitations)),
        }
        return {**semantic, "canonical_digest": _canonical_digest(semantic)}

    @staticmethod
    def _change_canvas(
        *, status: str, scenario_lens: Mapping[str, object],
        daily_brief: Mapping[str, object],
    ) -> dict:
        """Bind the canvas to existing stable scenario items without inferring pairs or edges."""

        chapters = []
        for scenario in scenario_lens["scenarios"]:
            before_ids = [str(item["item_id"]) for item in scenario["before"]]
            after_ids = [str(item["item_id"]) for item in scenario["after"]]
            delta_ids = before_ids + after_ids
            relationship_ids = (
                [str(item["edge_id"]) for item in scenario["relationships"]]
                if scenario["relationship_mode"] == "VERIFIED_FLOW"
                else []
            )
            focused_items = list(scenario["before"]) + list(scenario["after"])
            summary = {
                "added_items": sum(item["change"] == "ADDED" for item in focused_items),
                "removed_items": sum(item["change"] == "REMOVED" for item in focused_items),
                "changed_items": sum(
                    item["change"] not in {"ADDED", "REMOVED"}
                    for item in focused_items
                ),
            }
            chapter_id = f"canvas-chapter:{str(scenario['scenario_id']).split(':', 1)[1]}"
            chapters.append({
                "chapter_id": chapter_id,
                "scenario_id": str(scenario["scenario_id"]),
                "order": int(scenario["order"]),
                "title_zh": str(scenario["title_zh"]),
                "question_zh": str(scenario["question_zh"]),
                "change_shape": str(scenario["change_shape"]),
                "relationship_mode": str(scenario["relationship_mode"]),
                "before_item_ids": before_ids,
                "delta_item_ids": delta_ids,
                "after_item_ids": after_ids,
                "relationship_ids": relationship_ids,
                "default_focus_item_id": (
                    after_ids[0] if after_ids else before_ids[0] if before_ids else None
                ),
                "summary": summary,
                "boundary_note_zh": (
                    "只绘制本场景中明确列出的结构关系；画布位置不代表额外调用。"
                    if scenario["relationship_mode"] == "VERIFIED_FLOW"
                    else "这些对象是回答同一问题的并列事实；画布不绘制方向箭头。"
                ),
            })
        primary_scenario_id = str(scenario_lens["primary_scenario_id"])
        primary = next(item for item in chapters if item["scenario_id"] == primary_scenario_id)
        primary_scenario = next(
            item for item in scenario_lens["scenarios"]
            if item["scenario_id"] == primary_scenario_id
        )

        def unique_labels(items: Sequence[Mapping[str, object]]) -> list[str]:
            labels: list[str] = []
            for item in items:
                label = str(item["business_label_zh"])
                if label not in labels:
                    labels.append(label)
            return labels

        before_labels = unique_labels(primary_scenario["before"])
        after_labels = unique_labels(primary_scenario["after"])
        common_labels = [item for item in before_labels if item in after_labels]
        old_only = [item for item in before_labels if item not in after_labels]
        new_only = [item for item in after_labels if item not in before_labels]
        before_change = {
            str(item["business_label_zh"]): str(item["change"])
            for item in primary_scenario["before"]
        }
        after_change = {
            str(item["business_label_zh"]): str(item["change"])
            for item in primary_scenario["after"]
        }
        removed_labels = [
            item for item in old_only if before_change.get(item) == "REMOVED"
        ]
        added_labels = [
            item for item in new_only if after_change.get(item) == "ADDED"
        ]

        def joined(labels: Sequence[str], empty: str) -> str:
            if not labels:
                return empty
            suffix = "等" if len(labels) > 2 else ""
            return "、".join(labels[:2]) + suffix

        def lane_summary(
            exclusive: Sequence[str], common: Sequence[str], empty: str
        ) -> str:
            if exclusive and common:
                return f"{joined(exclusive, empty)}；{joined(common, empty)}保持"
            if exclusive:
                return joined(exclusive, empty)
            if common:
                return f"{joined(common, empty)}保持，内部实现重组"
            return empty

        title = str(primary["title_zh"])
        shape = str(primary["change_shape"])
        if shape == "ADDED":
            verdict = f"新增「{title}」：{joined(after_labels, '形成新的业务能力')}"
        elif shape == "REMOVED":
            verdict = f"移除「{title}」：{joined(before_labels, '原有能力退出')}"
        elif removed_labels and added_labels:
            verdict = f"「{title}」：移除“{removed_labels[0]}”，新增“{added_labels[0]}”"
        elif old_only and new_only:
            verdict = f"「{title}」：旧版突出“{old_only[0]}”，新版突出“{new_only[0]}”"
        elif added_labels:
            verdict = f"「{title}」保留原职责，并新增“{added_labels[0]}”"
        elif removed_labels:
            verdict = f"「{title}」保留原职责，并移除“{removed_labels[0]}”"
        elif new_only:
            verdict = f"「{title}」出现新的聚焦项“{new_only[0]}”"
        elif old_only:
            verdict = f"「{title}」不再聚焦“{old_only[0]}”"
        elif common_labels:
            verdict = f"「{title}」职责仍在，但相关实现已重新组织"
        else:
            verdict = f"「{title}」的实现结构已调整"
        first_check = daily_brief["checks"][0]
        impact = str(daily_brief["why_it_matters_zh"])
        impact = impact.split("；完整符号", 1)[0].removeprefix("直接影响 ")
        verify = (
            f"在 Unity 中走一遍“{new_only[0]}”，确认结果符合预期。"
            if new_only else str(first_check["action_zh"])
        )
        capsule = {
            "read_time_seconds": 10,
            "verdict_zh": verdict,
            "before_zh": lane_summary(
                old_only, common_labels, "没有进入聚焦层的旧版能力"
            ),
            "after_zh": lane_summary(
                new_only, common_labels, "没有进入聚焦层的新版能力"
            ),
            "impact_zh": impact,
            "verify_zh": verify.replace("PARTIAL", "当前证据边界"),
        }
        verification_mission = ChangeStoryBuilder._verification_mission(
            status=status,
            primary_scenario=primary_scenario,
            scenario_lens=scenario_lens,
            daily_brief=daily_brief,
            capsule=capsule,
        )
        capsule["verify_zh"] = verification_mission["steps"][0]["action_zh"]
        return {
            "default_view": "DELTA",
            "primary_chapter_id": str(primary["chapter_id"]),
            "summary": dict(primary["summary"]),
            "capsule": capsule,
            "verification_mission": verification_mission,
            "partial_note_zh": (
                "PARTIAL：当前画布只覆盖已变更 C# 文件；未变更依赖、完整程序集和运行时绑定尚未确认。"
                if status == "PARTIAL"
                else "FRESH：分析上下文完整；实际运行表现仍需通过目标环境验证。"
            ),
            "chapters": chapters,
        }

    @staticmethod
    def _verification_mission(
        *,
        status: str,
        primary_scenario: Mapping[str, object],
        scenario_lens: Mapping[str, object],
        daily_brief: Mapping[str, object],
        capsule: Mapping[str, object],
    ) -> dict:
        """Turn evidence-backed checks into a short guided task with observable success."""

        checks = list(daily_brief["checks"])
        takeaways_zh = list(scenario_lens["takeaways_zh"])
        takeaways_en = list(scenario_lens["takeaways_en"])
        primary_zh = takeaways_zh[0]
        primary_en = takeaways_en[0]
        selected_items = list(primary_scenario["after"]) + list(primary_scenario["before"])
        primary_area = str(selected_items[0]["area"]) if selected_items else "CLIENT"
        first_actions = {
            "EDITOR": (
                f"打开 Unity 中与「{primary_scenario['title_zh']}」相关的工具窗口，选择一份真实数据并触发“{primary_zh}”。",
                f'Open the Unity tool for “{primary_scenario["title_en"]}”, select real data, and trigger “{primary_en}”.',
            ),
            "CONFIGURATION": (
                f"准备一份最小真实配置，执行一次与“{primary_zh}”对应的保存或导出流程。",
                f'Prepare a minimal real configuration and run the save or export flow for “{primary_en}”.',
            ),
            "TEST": (
                f"运行与“{primary_zh}”直接相关的最小测试用例。",
                f'Run the smallest test case directly related to “{primary_en}”.',
            ),
        }
        first_action_zh, first_action_en = first_actions.get(
            primary_area,
            (
                f"在目标环境触发一次与“{primary_zh}”对应的真实流程。",
                f'Trigger one real target-environment workflow for “{primary_en}”.',
            ),
        )
        success_by_kind = {
            "PRIMARY_BEHAVIOR": (
                f"实际结果体现“{primary_zh}”，并且 Unity 控制台没有新增错误。",
                f'The observed result reflects “{primary_en}” and the Unity Console shows no new errors.',
            ),
            "SECONDARY_BEHAVIOR": (
                "边界操作没有产生异常、错误数据或意外状态变化。",
                "The boundary interaction produces no exception, invalid data, or unexpected state change.",
            ),
            "RELATIONSHIP_PATH": (
                "输入、判断和最终表现与已证实关系一致，没有中断或顺序异常。",
                "Input, decisions, and presentation match the verified relationships without interruption or ordering errors.",
            ),
            "EVIDENCE_BOUNDARY": (
                "目标 Unity 工程编译通过，实际操作结果与 Change Capsule 描述一致。",
                "The target Unity project compiles and the observed behavior matches the Change Capsule.",
            ),
            "REGRESSION": (
                "相邻流程仍可完成，且没有出现本次修改引入的新错误。",
                "The adjacent workflow still completes without a new error introduced by this change.",
            ),
        }
        steps = []
        for index, check in enumerate(checks[:3], start=1):
            success_zh, success_en = success_by_kind[str(check["kind"])]
            steps.append({
                "step_id": f"mission-step:{index}",
                "order": index,
                "action_zh": (
                    first_action_zh if index == 1 else str(check["action_zh"])
                ),
                "action_en": (
                    first_action_en if index == 1 else str(check["action_en"])
                ),
                "success_zh": success_zh,
                "success_en": success_en,
                "evidence_refs": list(check["evidence_refs"]),
            })
        title_zh = str(primary_scenario["title_zh"])
        title_en = str(primary_scenario["title_en"])
        return {
            "mission_id": "verification-mission:primary-change",
            "title_zh": f"验证「{title_zh}」",
            "title_en": f"Verify {title_en}",
            "goal_zh": f"用一次真实操作确认：{capsule['verdict_zh']}",
            "goal_en": f"Use a real workflow to confirm: {daily_brief['what_changed_en']}",
            "estimated_minutes": min(5, max(1, len(steps))),
            "state": "PARTIAL" if status == "PARTIAL" else "SUGGESTED",
            "first_step_id": "mission-step:1",
            "steps": steps,
            "completion_zh": "所有步骤的成功标志均出现，且 Unity 控制台没有新增错误时，任务完成。",
            "completion_en": "The mission is complete when every success signal is observed and the Unity Console shows no new errors.",
            "boundary_zh": (
                "这是基于语法局部证据生成的建议任务；完成前不能视为运行时已验证。"
                if status == "PARTIAL"
                else "这是建议验证任务；只有实际完成步骤后，才能确认运行表现。"
            ),
            "boundary_en": (
                "This suggested mission is based on syntax-partial evidence and does not prove runtime behavior until completed."
                if status == "PARTIAL"
                else "This is a suggested verification mission; runtime behavior is confirmed only after the steps are completed."
            ),
        }

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
                "action_zh": "在目标 Unity 环境完成编译和实际运行验证，补齐当前证据边界。",
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
                ("resolvepretime", "计算攻击前摇时间", "Calculate attack anticipation time"),
                ("resolveanchor", "按锚点计算攻击位置", "Resolve attack position from anchors"),
                ("template", "用模板生成初始技能", "Create initial skill data from a template"),
                ("duplicate", "复制可独立编辑的数据", "Duplicate independently editable data"),
                ("allocate", "分配新的配置标识", "Allocate new configuration identifiers"),
                ("addcomplete", "创建一套完整技能", "Create a complete skill"),
                ("addstep", "增加一个攻击步骤", "Add an attack step"),
                ("create", "创建并组装技能数据", "Create and assemble skill data"),
                ("validate", "校验技能步骤", "Validate skill steps"),
                ("write", "写回技能配置数据", "Write skill configuration data"),
                ("read", "读取已有技能配置", "Read existing skill configuration"),
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
    """Render a self-contained, script-free Chinese Change Canvas."""

    def render(
        self,
        story: Mapping[str, object],
        *,
        repository_root: str | os.PathLike[str] | None = None,
    ) -> str:
        """Render the v1.7 Change Canvas with a first-action verification mission."""

        if story.get("schema_version") != "1.7.0" or story.get("language") != "zh-CN":
            raise ValueError("unsupported Change Story")
        esc = lambda value: html.escape(str(value), quote=True)
        body_esc = lambda value: esc(str(value).replace("PARTIAL", "当前证据边界"))
        repo = Path(repository_root).resolve() if repository_root is not None else None
        revisions = story.get("revisions")
        new_binding = revisions.get("new") if isinstance(revisions, Mapping) else None
        new_is_worktree = bool(
            isinstance(new_binding, Mapping)
            and (new_binding.get("revision") == "WORKTREE" or new_binding.get("dirty") is True)
        )
        canvas = story["change_canvas"]
        mission = canvas["verification_mission"]
        scenario_lens = story["scenario_lens"]
        scenarios = {
            str(item["scenario_id"]): item for item in scenario_lens["scenarios"]
        }

        def source_location(item: Mapping[str, object]) -> str:
            label = f"{item['path']}:{item['start_line']}"
            if repo is None or not new_is_worktree or item["revision_role"] != "NEW":
                return f'<span class="location">{esc(label)}</span>'
            candidate = (repo / Path(str(item["path"]))).resolve()
            try:
                candidate.relative_to(repo)
            except ValueError:
                return f'<span class="location">{esc(label)}</span>'
            return (
                f'<a class="location" href="{esc(candidate.as_uri())}#L{item["start_line"]}">'
                f'{esc(label)}</a>'
            )

        change_symbol = {
            "ADDED": "+",
            "REMOVED": "−",
            "UPDATED": "∆",
            "MOVED": "↗",
            "RENAMED": "Aa",
            "RENAMED_AND_MOVED": "↗",
            "CONTEXT": "·",
        }

        def node_markup(
            item: Mapping[str, object], focus_id: str, *, role: str, compact: bool = False
        ) -> str:
            classes = [
                "canvas-node",
                f'change-{str(item["change"]).lower()}',
                f'role-{role.lower()}',
            ]
            if compact:
                classes.append("compact")
            return (
                f'<label class="{" ".join(classes)}" for="{focus_id}">'
                f'<span class="node-symbol">{esc(change_symbol.get(str(item["change"]), "∆"))}</span>'
                f'<span class="node-copy"><strong>{esc(item["business_label_zh"])}</strong>'
                f'<small>{esc(item["technical_label"])}</small></span>'
                f'<span class="node-change">{esc(_CHANGE_ZH.get(item["change"], item["change"]))}</span>'
                f'</label>'
            )

        def relation_markup(
            scenario: Mapping[str, object], item_by_id: Mapping[str, Mapping[str, object]],
            allowed_ids: set[str], visible_item_ids: set[str] | None = None,
        ) -> str:
            if scenario["relationship_mode"] != "VERIFIED_FLOW":
                return (
                    '<div class="parallel-boundary"><span>≡</span><div><strong>并列事实</strong>'
                    '<p>这些对象共同回答本章问题，但没有证据证明它们按画布顺序调用。</p></div></div>'
                )
            rows = []
            for relation in scenario["relationships"]:
                if str(relation["edge_id"]) not in allowed_ids:
                    continue
                if visible_item_ids is not None and not {
                    str(relation["source_item_id"]), str(relation["target_item_id"])
                }.issubset(visible_item_ids):
                    continue
                source = item_by_id.get(str(relation["source_item_id"]))
                target = item_by_id.get(str(relation["target_item_id"]))
                if source is None or target is None:
                    continue
                rows.append(
                    '<div class="verified-route">'
                    f'<span>{esc(source["business_label_zh"])}</span>'
                    f'<b><small>{esc(relation["relation_zh"])}</small>→</b>'
                    f'<span>{esc(target["business_label_zh"])}</span>'
                    f'<em>{esc(relation["confidence"])}</em></div>'
                )
            if not rows:
                return (
                    '<div class="parallel-boundary"><span>?</span><div><strong>暂无可画关系</strong>'
                    '<p>节点有变更证据，但本章没有可用于连线的明确关系边。</p></div></div>'
                )
            return '<div class="verified-routes"><div class="route-title">已证实关系</div>' + "".join(rows) + "</div>"

        chapter_inputs: list[str] = []
        chapter_labels: list[str] = []
        chapter_panels: list[str] = []
        chapter_css: list[str] = []
        focus_css: list[str] = []
        primary_chapter_id = str(canvas["primary_chapter_id"])
        primary_chapter = next(
            item for item in canvas["chapters"]
            if str(item["chapter_id"]) == primary_chapter_id
        )
        capsule = canvas["capsule"]
        for chapter_index, chapter in enumerate(canvas["chapters"]):
            chapter_control = f"canvas-chapter-{chapter_index}"
            is_primary = str(chapter["chapter_id"]) == primary_chapter_id
            chapter_inputs.append(
                f'<input class="canvas-radio" type="radio" name="canvas-chapter" '
                f'id="{chapter_control}"{" checked" if is_primary else ""}>'
            )
            chapter_labels.append(
                f'<label class="chapter-step" for="{chapter_control}"><span>{chapter_index + 1:02d}</span>'
                f'<strong>{esc(chapter["title_zh"])}</strong></label>'
            )
            chapter_css.append(
                f'#{chapter_control}:checked~.canvas-workspace .chapter-step[for="{chapter_control}"]'
                '{color:var(--ink);border-color:var(--blue);background:var(--blue-soft)}'
                f'#{chapter_control}:checked~.canvas-workspace .canvas-chapter[data-chapter="{chapter_index}"]'
                '{display:block}'
                f'#{chapter_control}:focus-visible~.canvas-workspace .chapter-step[for="{chapter_control}"]'
                '{outline:3px solid var(--focus);outline-offset:2px}'
            )
            scenario = scenarios[str(chapter["scenario_id"])]
            all_items = list(scenario["before"]) + list(scenario["after"])
            item_by_id = {str(item["item_id"]): item for item in all_items}
            focus_ids: dict[str, str] = {}
            focus_inputs: list[str] = []
            passports: list[str] = []
            for item_index, item in enumerate(all_items):
                item_id = str(item["item_id"])
                focus_control = f"canvas-focus-{chapter_index}-{item_index}"
                focus_ids[item_id] = focus_control
                focus_inputs.append(
                    f'<input class="canvas-radio" type="radio" name="canvas-focus-{chapter_index}" '
                    f'id="{focus_control}"'
                    f'{" checked" if item_id == chapter["default_focus_item_id"] else ""}>'
                )
                focus_css.append(
                    f'#{focus_control}:checked~.canvas-chapter-shell '
                    f'.canvas-passport[data-focus="{focus_control}"]{{display:block}}'
                    f'#{focus_control}:checked~.canvas-chapter-shell label[for="{focus_control}"]'
                    '{outline:3px solid var(--focus);outline-offset:2px}'
                )
                passports.append(
                    f'<article class="canvas-passport" data-focus="{focus_control}">'
                    f'<div class="passport-kicker">语义护照 · {esc(item["area"])} · {esc(item["confidence"])}</div>'
                    f'<h3>{esc(item["business_label_zh"])}</h3>'
                    f'<p class="passport-tech">{esc(item["technical_label"])}</p>'
                    f'<div class="passport-facts"><span>版本侧<b>{esc(item["role"])}</b></span>'
                    f'<span>变化<b>{esc(_CHANGE_ZH.get(item["change"], item["change"]))}</b></span></div>'
                    f'{source_location(item["location"])}'
                    '<details><summary>查看证据标识</summary>'
                    f'<code>{esc(", ".join(str(ref) for ref in item["evidence_refs"]))}</code></details>'
                    '</article>'
                )

            def render_ids(ids: Sequence[object], role: str) -> str:
                items = [
                    node_markup(item_by_id[str(item_id)], focus_ids[str(item_id)], role=role)
                    for item_id in ids if str(item_id) in item_by_id
                ]
                return "".join(items) or '<p class="scene-empty">这一侧没有进入聚焦层的变更证据。</p>'

            before_nodes = render_ids(chapter["before_item_ids"], "old")
            after_nodes = render_ids(chapter["after_item_ids"], "new")
            allowed_relation_ids = {str(item) for item in chapter["relationship_ids"]}
            before_item_ids = {str(item) for item in chapter["before_item_ids"]}
            after_item_ids = {str(item) for item in chapter["after_item_ids"]}
            before_relations = relation_markup(
                scenario, item_by_id, allowed_relation_ids, before_item_ids
            )
            delta_relations = relation_markup(
                scenario, item_by_id, allowed_relation_ids, before_item_ids | after_item_ids
            )
            after_relations = relation_markup(
                scenario, item_by_id, allowed_relation_ids, after_item_ids
            )
            empty_passport = (
                '<article class="canvas-passport empty-passport"><div class="passport-kicker">语义护照</div>'
                '<h3>没有可聚焦节点</h3><p>当前变化只有边界信息；请展开下方技术证据核对。</p></article>'
                if not passports else ""
            )
            chapter_panels.append(
                f'<section class="canvas-chapter" data-chapter="{chapter_index}" '
                f'data-change-shape="{esc(chapter["change_shape"])}" '
                f'data-relationship-mode="{esc(chapter["relationship_mode"])}">'
                f'{"".join(focus_inputs)}<div class="canvas-chapter-shell">'
                '<div class="canvas-main"><div class="chapter-heading">'
                f'<div><span>第 {chapter_index + 1} 章 · {esc(chapter["change_shape"])}</span>'
                f'<h2>{esc(chapter["question_zh"])}</h2></div>'
                f'<div class="mini-counts"><span>+{chapter["summary"]["added_items"]}</span>'
                f'<span>−{chapter["summary"]["removed_items"]}</span>'
                f'<span>∆{chapter["summary"]["changed_items"]}</span></div></div>'
                '<div class="canvas-scene" data-canvas-view="BEFORE">'
                f'<div class="scene-column"><div class="scene-label">原链路事实 · BEFORE</div>{before_nodes}</div>'
                f'{before_relations}</div>'
                '<div class="canvas-scene" data-canvas-view="DELTA">'
                '<div class="delta-grid"><div class="scene-column old-zone"><div class="scene-label">原来 · OLD EVIDENCE</div>'
                f'{before_nodes}</div><div class="delta-divider"><span>变化</span><b>→</b></div>'
                f'<div class="scene-column new-zone"><div class="scene-label">现在 · NEW EVIDENCE</div>{after_nodes}</div></div>'
                f'{delta_relations}</div>'
                '<div class="canvas-scene" data-canvas-view="AFTER">'
                f'<div class="scene-column"><div class="scene-label">新链路事实 · AFTER</div>{after_nodes}</div>'
                f'{after_relations}</div>'
                f'<p class="truth-boundary">证据边界：{esc(chapter["boundary_note_zh"])}</p></div>'
                f'<aside class="passport-rail">{"".join(passports)}{empty_passport}</aside>'
                '</div></section>'
            )

        first_mission_step = mission["steps"][0]
        mission_followups = "".join(
            '<li><span>{order}</span><div><strong>{action}</strong>'
            '<small>成功标志：{success}</small></div></li>'.format(
                order=item["order"],
                action=body_esc(item["action_zh"]),
                success=body_esc(item["success_zh"]),
            )
            for item in mission["steps"][1:]
        )
        mission_more = (
            '<details class="mission-more"><summary>完成后查看后续步骤</summary>'
            f'<ol class="action-list">{mission_followups}</ol></details>'
            if mission_followups else ""
        )
        visible_impacts = list(story["impacts"])[:12]
        impacts = "".join(
            f'<li><strong>{esc(item["label"])}</strong><small>{esc(item["kind"])} · '
            f'{esc(_CHANGE_ZH.get(item["change"], item["change"]))}</small></li>'
            for item in visible_impacts
        ) or '<li>没有识别到直接状态或事件影响。</li>'
        if len(story["impacts"]) > len(visible_impacts):
            impacts += (
                f'<li><strong>其余 {len(story["impacts"]) - len(visible_impacts)} 项</strong>'
                '<small>保留在 change-story.json</small></li>'
            )
        visible_limitations = list(story["limitations"])[:16]
        limitations = "".join(f'<li>{body_esc(item)}</li>' for item in visible_limitations)
        if len(story["limitations"]) > len(visible_limitations):
            limitations += (
                f'<li>其余 {len(story["limitations"]) - len(visible_limitations)} 项已折叠；'
                '完整内容保留在 change-story.json。</li>'
            )
        claims = "".join(
            f'<article class="evidence-card"><span>{esc(item["layer"])} · {esc(item["confidence"])}</span>'
            f'<p>{body_esc(item["statement_zh"])}</p><details><summary>证据标识</summary>'
            f'<code>{esc(", ".join(str(ref) for ref in item["evidence_refs"]))}</code></details></article>'
            for item in story["claims"]
        ) or '<p>没有可展示的声明。</p>'
        visible_changes = list(story["changes"])[:40]
        changes = "".join(
            f'<tr><td>{esc(_CHANGE_ZH.get(item["kind"], item["kind"]))}</td>'
            f'<td>{esc(item["subject_zh"])}</td><td>{esc(item["confidence"])}</td></tr>'
            for item in visible_changes
        ) or '<tr><td colspan="3">没有符号级变化。</td></tr>'
        if len(story["changes"]) > len(visible_changes):
            changes += (
                f'<tr><td colspan="3">其余 {len(story["changes"]) - len(visible_changes)} 项已折叠；'
                '完整内容保留在 change-story.json。</td></tr>'
            )

        view_css = "".join(
            f'#canvas-view-{view.lower()}:checked~.canvas-workspace '
            f'.view-switch label[for="canvas-view-{view.lower()}"]'
            '{background:var(--ink);color:white;border-color:var(--ink)}'
            f'#canvas-view-{view.lower()}:checked~.canvas-workspace '
            f'.canvas-scene[data-canvas-view="{view}"]{{display:grid}}'
            f'#canvas-view-{view.lower()}:focus-visible~.canvas-workspace '
            f'.view-switch label[for="canvas-view-{view.lower()}"]'
            '{outline:3px solid var(--focus);outline-offset:2px}'
            for view in ("BEFORE", "DELTA", "AFTER")
        )
        mission_css = """
.mission-card{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:16px;align-items:center;margin-bottom:12px;padding:18px 20px;border:1px solid #b9c8f6;border-radius:18px;background:linear-gradient(120deg,#f8faff,#edf2ff 70%,#f2fbf6);box-shadow:0 10px 30px rgba(49,93,216,.10)}
.mission-number{display:grid;place-items:center;width:48px;height:48px;border-radius:14px;background:var(--blue);color:white;font-size:20px;font-weight:900}.mission-copy small{color:var(--blue);font-size:10px;font-weight:800;letter-spacing:.1em}.mission-copy h2{margin:2px 0 5px;font-size:20px}.mission-copy p{margin:0}.mission-success{margin-top:7px!important;color:var(--green);font-weight:700}.mission-meta{display:grid;gap:6px;justify-items:end;color:var(--muted);font-size:11px}.mission-meta b{padding:6px 10px;border-radius:999px;background:white;color:var(--blue)}
.mission-more{grid-column:2/4}.mission-more summary{cursor:pointer;color:var(--blue);font-size:12px;font-weight:700}.mission-more .action-list{margin-top:8px}.action-list small{display:block;margin-top:3px;color:var(--green)}
@media(max-width:640px){.mission-card{grid-template-columns:auto 1fr}.mission-meta{grid-column:1/-1;grid-auto-flow:column;justify-items:start}.mission-more{grid-column:1/-1}}
"""
        css = """
:root{--bg:#f2f3f0;--paper:#fbfbf8;--ink:#18201d;--muted:#68716d;--line:#d8dcd6;--blue:#315dd8;--blue-soft:#eaf0ff;--green:#17834a;--green-soft:#e9f7ee;--red:#c13d45;--red-soft:#fff0f0;--amber:#a86308;--focus:#ef9f1a;--shadow:0 18px 55px rgba(31,45,39,.10)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;overflow-x:hidden;background:linear-gradient(135deg,#eef0eb,#f8f8f5 55%,#edf2f0);color:var(--ink);font:15px/1.55 "Segoe UI","Microsoft YaHei",sans-serif}button,label,summary{font:inherit}.canvas-radio{position:absolute;width:1px;height:1px;opacity:.001;clip-path:inset(50%)}main{max-width:1440px;margin:auto;padding:18px 24px 40px}.canvas-header{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:20px;align-items:end;padding:22px 26px;border:1px solid #29312e;border-radius:20px;background:#18201d;color:white;box-shadow:var(--shadow)}.eyebrow{color:#9fb7ff;font-size:11px;font-weight:800;letter-spacing:.16em}.canvas-header h1{max-width:980px;margin:5px 0 8px;font-size:clamp(24px,3vw,38px);line-height:1.18;letter-spacing:-.025em}.canvas-header p{max-width:940px;margin:0;color:#cad1ce}.capsule-route{display:grid;grid-template-columns:minmax(0,1fr) 38px minmax(0,1fr);gap:10px;align-items:center;max-width:980px;margin:12px 0}.capsule-route span{padding:10px 12px;border:1px solid #40504a;border-radius:10px;background:#222c28;color:#f3f6f4;font-weight:700}.capsule-route small{display:block;margin-bottom:2px;color:#9fb7ff;font-size:9px;letter-spacing:.1em}.capsule-route b{color:#9fb7ff;font-size:22px;text-align:center}.status-stack{display:grid;gap:8px;justify-items:end}.status-pill{padding:6px 11px;border:1px solid #82958d;border-radius:999px;color:#dce5e1;font-size:11px;font-weight:800}.delta-summary{display:flex;gap:6px}.delta-summary span{min-width:45px;padding:7px 10px;border-radius:9px;background:#27322e;text-align:center;font-weight:800}.delta-summary span:first-child{color:#76d59b}.delta-summary span:nth-child(2){color:#ff959a}.delta-summary span:last-child{color:#f1bd6c}.partial-banner{grid-column:1/-1;padding:8px 12px;border-radius:9px;background:#3b3020;color:#ffe0a9;font-size:12px}.canvas-workspace{margin-top:12px}.canvas-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:9px 12px;border:1px solid var(--line);border-radius:15px;background:rgba(251,251,248,.94)}.view-switch{display:flex;gap:5px;padding:4px;border-radius:11px;background:#e5e8e3}.view-switch label{min-width:92px;padding:8px 13px;border:1px solid transparent;border-radius:8px;color:var(--muted);text-align:center;font-weight:750;cursor:pointer}.view-switch label small{display:block;font-size:9px;letter-spacing:.08em}.legend{display:flex;gap:14px;color:var(--muted);font-size:12px}.legend i{display:inline-block;width:8px;height:8px;margin-right:5px;border-radius:50%}.legend .add{background:var(--green)}.legend .remove{background:var(--red)}.legend .change{background:var(--amber)}.chapter-stepper{display:flex;gap:8px;margin:9px 0;overflow:auto;scrollbar-width:thin}.chapter-step{display:flex;flex:1;min-width:155px;align-items:center;gap:9px;padding:9px 12px;border:1px solid var(--line);border-radius:12px;background:#f9faf7;color:var(--muted);cursor:pointer}.chapter-step>span{display:grid;place-items:center;flex:0 0 28px;height:28px;border-radius:8px;background:#e6e9e4;font-size:10px}.chapter-step strong{font-size:13px;white-space:nowrap}.canvas-chapter{display:none}.canvas-chapter-shell{display:grid;grid-template-columns:minmax(0,2.25fr) minmax(270px,.75fr);min-height:475px;border:1px solid var(--line);border-radius:20px;background:var(--paper);box-shadow:var(--shadow);overflow:hidden}.canvas-main{min-width:0;padding:20px}.chapter-heading{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.chapter-heading span{color:var(--blue);font-size:10px;font-weight:800;letter-spacing:.09em}.chapter-heading h2{max-width:850px;margin:3px 0 14px;font-size:21px;line-height:1.35}.mini-counts{display:flex;gap:4px}.mini-counts span{padding:3px 7px;border:1px solid var(--line);border-radius:999px;color:var(--muted);font-size:10px}.canvas-scene{display:none;align-content:start;gap:12px;min-height:330px;padding:15px;border:1px solid #dfe3dd;border-radius:15px;background:radial-gradient(circle at 20% 0,#fff 0,transparent 42%),linear-gradient(#f5f6f2,#f0f2ed);background-size:auto,auto}.scene-column{display:grid;align-content:start;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}.scene-label{grid-column:1/-1;color:var(--muted);font-size:10px;font-weight:800;letter-spacing:.11em}.delta-grid{display:grid;grid-template-columns:minmax(0,1fr) 58px minmax(0,1fr);gap:10px}.delta-divider{display:grid;place-items:center;align-content:center;color:var(--blue)}.delta-divider span{font-size:10px;font-weight:800}.delta-divider b{font-size:26px}.canvas-node{display:flex;position:relative;min-width:0;gap:10px;align-items:center;padding:13px;border:1px solid var(--line);border-left:5px solid var(--amber);border-radius:12px;background:white;box-shadow:0 5px 18px rgba(35,48,42,.06);cursor:pointer;transition:transform .16s,box-shadow .16s,opacity .16s}.canvas-node:hover{transform:translateY(-2px);box-shadow:0 9px 24px rgba(35,48,42,.12)}.canvas-scene[data-canvas-view="DELTA"] .canvas-node.role-old{background:#f6f6f3;opacity:.58}.canvas-node.change-added{border-left-color:var(--green)}.canvas-node.change-removed{border-left-color:var(--red)}.node-symbol{display:grid;place-items:center;flex:0 0 32px;height:32px;border-radius:9px;background:#eef0ec;font-weight:900}.change-added .node-symbol{color:var(--green);background:var(--green-soft)}.change-removed .node-symbol{color:var(--red);background:var(--red-soft)}.node-copy{min-width:0}.node-copy strong,.node-copy small{display:block;overflow:hidden;text-overflow:ellipsis}.node-copy small{color:var(--muted);font:10px/1.35 Consolas,monospace;white-space:nowrap}.node-change{margin-left:auto;color:var(--muted);font-size:10px}.verified-routes,.parallel-boundary{grid-column:1/-1;margin-top:2px;padding:10px;border:1px dashed #b9c2bc;border-radius:11px;background:#fbfcfa}.route-title{margin-bottom:6px;color:var(--blue);font-size:10px;font-weight:800;letter-spacing:.08em}.verified-route{display:grid;grid-template-columns:minmax(100px,1fr) minmax(95px,.65fr) minmax(100px,1fr) auto;gap:8px;align-items:center;margin-top:5px;font-size:12px}.verified-route>span{padding:6px 8px;border-radius:7px;background:white;text-align:center}.verified-route b{display:flex;gap:5px;justify-content:center;color:var(--blue)}.verified-route b small{font-weight:600}.verified-route em{color:var(--muted);font-size:9px}.parallel-boundary{display:flex;gap:10px;align-items:center}.parallel-boundary>span{display:grid;place-items:center;width:32px;height:32px;border-radius:9px;background:#ecefea;color:#69736e;font-weight:900}.parallel-boundary strong{font-size:12px}.parallel-boundary p{margin:1px 0;color:var(--muted);font-size:11px}.truth-boundary{margin:9px 2px 0;color:var(--muted);font-size:11px}.passport-rail{padding:20px;border-left:1px solid var(--line);background:#f0f2ed}.canvas-passport{display:none;position:sticky;top:14px;padding:17px;border:1px solid var(--line);border-radius:15px;background:white;box-shadow:0 8px 24px rgba(34,46,40,.07)}.empty-passport{display:block}.passport-kicker{color:var(--blue);font-size:9px;font-weight:800;letter-spacing:.08em}.canvas-passport h3{margin:7px 0;font-size:20px}.passport-tech{padding:9px;border-radius:8px;background:#f2f4f1;font:11px/1.45 Consolas,monospace;overflow-wrap:anywhere}.passport-facts{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin:12px 0}.passport-facts span{padding:8px;border:1px solid var(--line);border-radius:8px;color:var(--muted);font-size:10px}.passport-facts b{display:block;color:var(--ink);font-size:12px}.location{display:block;margin-top:10px;color:var(--blue);font:11px/1.4 Consolas,monospace;overflow-wrap:anywhere}.canvas-passport details{margin-top:12px}.canvas-passport summary,.evidence-details summary{cursor:pointer;color:var(--blue);font-size:11px;font-weight:700}code{display:block;margin-top:7px;color:#5f6964;font:10px/1.45 Consolas,monospace;overflow-wrap:anywhere}.below-fold{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px}.insight-card,.evidence-details{padding:16px;border:1px solid var(--line);border-radius:15px;background:var(--paper)}.insight-card h2{margin:0 0 9px;font-size:17px}.action-list,.impact-list{display:grid;gap:7px;margin:0;padding:0;list-style:none}.action-list li{display:flex;gap:10px;align-items:flex-start;padding:8px;border-radius:9px;background:#f0f2ed}.action-list li>span{display:grid;place-items:center;flex:0 0 24px;height:24px;border-radius:7px;background:var(--ink);color:white;font-size:10px}.impact-list li{display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid var(--line)}.impact-list small{color:var(--muted)}.evidence-details{grid-column:1/-1}.evidence-details>summary{font-size:14px}.evidence-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:13px}.evidence-card{padding:11px;border:1px solid var(--line);border-radius:10px;background:white}.evidence-card>span{color:var(--blue);font-size:9px;font-weight:800}.evidence-card p{font-size:12px}.technical-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.technical-grid h3{font-size:14px}.technical-grid ul{padding-left:20px}.technical-grid table{width:100%;border-collapse:collapse;font-size:11px}.technical-grid th,.technical-grid td{padding:7px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}footer{margin:22px 2px;color:var(--muted);font-size:11px}
@media(max-width:960px){main{padding:12px}.canvas-header{grid-template-columns:1fr}.status-stack{justify-items:start}.canvas-chapter-shell{grid-template-columns:1fr}.passport-rail{border-top:1px solid var(--line);border-left:0}.canvas-passport{position:static}.delta-grid{grid-template-columns:1fr}.delta-divider{grid-template-columns:auto auto;gap:8px}.below-fold{grid-template-columns:1fr}.evidence-details{grid-column:1}.evidence-grid,.technical-grid{grid-template-columns:1fr}}
@media(max-width:640px){.canvas-header{padding:18px}.capsule-route{grid-template-columns:1fr}.capsule-route b{transform:rotate(90deg)}.canvas-toolbar{align-items:stretch;flex-direction:column}.view-switch label{min-width:0;flex:1;padding:7px}.legend{justify-content:center}.chapter-step{flex:0 0 auto}.canvas-main{padding:13px}.chapter-heading{display:block}.mini-counts{margin-bottom:10px}.scene-column{grid-template-columns:1fr}.verified-route{grid-template-columns:1fr}.verified-route b{transform:rotate(90deg)}.node-change{display:none}.passport-rail{padding:13px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
""" + mission_css + view_css + "".join(chapter_css) + "".join(focus_css)

        partial_banner = (
            f'<div class="partial-banner">{esc(canvas["partial_note_zh"])}</div>'
            if story["status"] == "PARTIAL" else ""
        )
        status_label = "分析不完整" if story["status"] == "PARTIAL" else "FRESH"
        return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(story["title"])}</title><style>{css}</style></head>
<body><main data-story-id="{esc(story["story_id"])}" data-story-digest="{esc(story["canonical_digest"])}">
<input class="canvas-radio" type="radio" name="canvas-view" id="canvas-view-before">
<input class="canvas-radio" type="radio" name="canvas-view" id="canvas-view-delta" checked>
<input class="canvas-radio" type="radio" name="canvas-view" id="canvas-view-after">
{"".join(chapter_inputs)}
<header class="canvas-header"><div><div class="eyebrow">AEH CHANGE CANVAS · 10 秒结论</div>
<h1>{esc(capsule["verdict_zh"])}</h1><div class="capsule-route">
<span><small>原来</small>{esc(capsule["before_zh"])}</span><b>→</b>
<span><small>现在</small>{esc(capsule["after_zh"])}</span></div>
<p><strong>影响：</strong>{esc(capsule["impact_zh"])}</p></div>
<div class="status-stack"><span class="status-pill">{status_label}</span><div class="delta-summary">
<span>+{canvas["summary"]["added_items"]}</span><span>−{canvas["summary"]["removed_items"]}</span>
<span>∆{canvas["summary"]["changed_items"]}</span></div></div>{partial_banner}</header>
<div class="canvas-workspace"><section class="mission-card" aria-label="验证任务">
<div class="mission-number">1</div><div class="mission-copy"><small>现在只做这一步</small>
<h2>{body_esc(first_mission_step["action_zh"])}</h2>
<p class="mission-success">成功标志：{body_esc(first_mission_step["success_zh"])}</p></div>
<div class="mission-meta"><b>约 {mission["estimated_minutes"]} 分钟</b>
<span>建议验证 · 尚未执行</span></div>{mission_more}</section>
<section class="canvas-toolbar" aria-label="画布工具栏">
<div class="view-switch"><label for="canvas-view-before">原来<small>BEFORE</small></label>
<label for="canvas-view-delta">变化<small>DELTA</small></label>
<label for="canvas-view-after">现在<small>AFTER</small></label></div>
<div class="legend"><span><i class="add"></i>新增</span><span><i class="remove"></i>移除</span>
<span><i class="change"></i>修改</span></div></section>
<nav class="chapter-stepper" aria-label="修改故事章节">{"".join(chapter_labels)}</nav>
<section class="canvas-chapters">{"".join(chapter_panels)}</section>
<section class="below-fold"><article class="insight-card"><h2>验证边界</h2>
<p>{body_esc(mission["boundary_zh"])}</p><p><strong>完成条件：</strong>{body_esc(mission["completion_zh"])}</p>
</article><article class="insight-card"><h2>影响与未知项</h2>
<ul class="impact-list">{impacts}</ul></article>
<details class="evidence-details"><summary>详细思路拆解与代码证据（按需展开）</summary>
<p>{body_esc(story["deep_dive"]["method_note_zh"])}</p><div class="evidence-grid">{claims}</div>
<div class="technical-grid"><div><h3>符号变化</h3><table><thead><tr><th>类型</th><th>对象</th><th>置信度</th></tr></thead>
<tbody>{changes}</tbody></table></div><div><h3>限制与未知项</h3><ul>{limitations}</ul></div></div></details></section>
<footer>AEH Change Lens · 离线、无脚本 · 点击节点查看语义护照 · 连线只代表已验证关系</footer>
</div></main></body></html>'''


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
