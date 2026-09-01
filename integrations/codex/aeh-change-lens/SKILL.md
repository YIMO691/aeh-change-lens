---
name: aeh-change-lens
description: Explicitly use AEH Change Lens for a quick change-shape map or detailed Unity C# modification explanation when the user asks for Change Lens, an AI modification path report, or invokes $aeh-change-lens. Do not invoke implicitly for ordinary code review or editing.
---

# AEH Change Lens

Use the local Change Lens tool as a read-only analysis assistant for the user's Unity/gameplay work. Default to a Chinese-first Change Canvas result delivered in an action-oriented form: the primary business change plus the first step and success signal from a short verification mission. Expand the canvas, semantic passports, and detailed evidence only when useful.

Before running an analysis, read [references/workflow.md](references/workflow.md) completely.

## Defaults

- Tool: `D:\\ares\\aeh-change-lens`
- Work repository: the explicitly named repository, otherwise the current Git repository, otherwise `D:\\ares2\\project\\ET6`
- Unity project: auto-detect, preferring `<repository>\\Unity`
- Comparison: `HEAD` to `WORKTREE`
- Language: Chinese first
- Output: outside the analyzed repository
- Reading mode: `change_canvas.capsule` plus the first `verification_mission` step; when expanded, read `change_canvas.visual_story` in BEFORE → DELTA → AFTER → VERIFY order before the detailed chapters

Do not expose assembly names, request IDs, manifests, digests, or Worker setup unless they affect the result or the user asks for technical evidence.

## Authority boundary

Explicit invocation authorizes read-only inspection, building the Change Lens repository-owned Worker, and writing report artifacts outside the analyzed repository. It does not authorize modifying, checking out, compiling, or executing target-project code.

Never run `export-compile-manifest` or `export-build-provenance` without separate, explicit authorization in the current conversation because they write evidence files into the target repository. When a revision baseline is missing, use the explicit read-only `--allow-syntax-partial` fallback first. Report `PARTIAL` prominently and explain that it covers only changed C# files; do not imply that a compile baseline was reconstructed.

Never claim access to hidden model reasoning. Keep these layers distinct:

- code facts: Git/Roslyn-supported;
- source evidence: statements the user actually supplied;
- intent inference: conservative hypotheses labeled as possible.

## Handoff

Prefer the `change_capsule` and `verification_mission` returned directly by `explain`; fall back to their matching values in `change_canvas` inside `change-story.json`. The default answer must be brief and use this exact information order:

```text
结论：<verdict_zh>
原来：<before_zh>
现在：<after_zh>
影响：<impact_zh>
现在做：<verification_mission.steps[0].action_zh>
成功标志：<verification_mission.steps[0].success_zh>
```

If status is `PARTIAL`, add one short status sentence after those six lines. Do not list later mission steps, chapters, nodes, hashes, output paths, or the HTML link in the default answer. A mission is `SUGGESTED` or `PARTIAL`, never already completed. The report is an optional evidence attachment, not required reading.

## Guided verification

When the user asks “带我验证”, “开始验证”, or equivalent, guide the `verification_mission` one step at a time:

1. Return only the current step's action and success signal.
2. Wait for the user's observed result before advancing; do not reveal all remaining steps as a list.
3. If the result differs, inspect only the evidence references for that step and explain the mismatch without claiming success.
4. After the final observed success, summarize the verified outcome and retain any `PARTIAL` boundary that was not actually closed.

This protocol does not authorize compiling or running the target Unity project. Ask for separate authorization before any target-project execution or write.

When the user asks to expand without naming a scope, summarize the four `visual_story.beats` first and preserve their stable slot order. Do not turn slot adjacency into a call sequence. When the user selects a chapter or node, explain only that scope. Resolve canvas item IDs back to matching `scenario_lens` items for the semantic passport: business label, technical label, revision side, change kind, confidence, source location, and evidence. Respect `relationship_mode`: `VERIFIED_FLOW` permits only the exact listed relationships; `PARALLEL_FACTS` must remain a set of related facts rather than a narrated call sequence. In detailed mode, expand that selected scenario first, then use staged implementation structure and decision points as evidence while keeping code facts, source evidence, and inference distinct.

State `PARTIAL` once when present. Expand a chapter, semantic passport, or technical evidence only after the user asks “为什么”, “展开”, requests detail, or names a scope. Open or link the report only when the user asks for it.
