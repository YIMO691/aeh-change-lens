---
name: aeh-change-lens
description: Explicitly use AEH Change Lens for a quick change-shape map or detailed Unity C# modification explanation when the user asks for Change Lens, an AI modification path report, or invokes $aeh-change-lens. Do not invoke implicitly for ordinary code review or editing.
---

# AEH Change Lens

Use the local Change Lens tool as a read-only analysis assistant for the user's Unity/gameplay work. Default to a Chinese-first daily brief of what changed, why it matters, and what to verify. Use scenario understanding when the user asks how it works, and detailed evidence for step-by-step or technical review.

Before running an analysis, read [references/workflow.md](references/workflow.md) completely.

## Defaults

- Tool: `D:\\ares\\aeh-change-lens`
- Work repository: the explicitly named repository, otherwise the current Git repository, otherwise `D:\\ares\\project\\ET6`
- Unity project: auto-detect, preferring `<repository>\\Unity`
- Comparison: `HEAD` to `WORKTREE`
- Language: Chinese first
- Output: outside the analyzed repository
- Reading mode: `daily_brief` by default; use Scenario Lens when the user asks how the change works, and detailed evidence only when requested

Do not expose assembly names, request IDs, manifests, digests, or Worker setup unless they affect the result or the user asks for technical evidence.

## Authority boundary

Explicit invocation authorizes read-only inspection, building the Change Lens repository-owned Worker, and writing report artifacts outside the analyzed repository. It does not authorize modifying, checking out, compiling, or executing target-project code.

Never run `export-compile-manifest` or `export-build-provenance` without separate, explicit authorization in the current conversation because they write evidence files into the target repository. When a revision baseline is missing, use the explicit read-only `--allow-syntax-partial` fallback first. Report `PARTIAL` prominently and explain that it covers only changed C# files; do not imply that a compile baseline was reconstructed.

Never claim access to hidden model reasoning. Keep these layers distinct:

- code facts: Git/Roslyn-supported;
- source evidence: statements the user actually supplied;
- intent inference: conservative hypotheses labeled as possible.

## Handoff

Read the focused `change-story.json` before the full analysis JSON. In daily mode, lead with `daily_brief.what_changed_zh`, its one to three bounded memory points, and `daily_brief.checks`; clearly call checks suggestions rather than code facts. Do not name every scenario unless the user asks how the change works. Use `scenario_lens` for that explanation, and `visual_map` only for a requested OLD / NEW comparison or as a short secondary confirmation.

When the user selects a scenario, explain only that scenario. Use its `change_shape` to distinguish a newly introduced scene, a removed scene, and a modified before/after comparison. Respect its `relationship_mode`: `VERIFIED_FLOW` permits only the exact listed relationships; `PARALLEL_FACTS` must remain a set of related facts rather than a narrated call sequence. In detailed mode, expand that selected scenario first, then use staged implementation structure and decision points as evidence while keeping code facts, source evidence, and inference distinct.

State `PARTIAL` prominently when present. Do not dump raw node/edge counts unless asked for technical evidence. Open the report in a visible browser only when the user asks to open it.
