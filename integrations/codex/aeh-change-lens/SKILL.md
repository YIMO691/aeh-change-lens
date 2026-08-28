---
name: aeh-change-lens
description: Explicitly use AEH Change Lens to explain an OLD-to-NEW Unity C# modification when the user asks for Change Lens, an AI modification path report, or invokes $aeh-change-lens. Do not invoke implicitly for ordinary code review or editing.
---

# AEH Change Lens

Use the local Change Lens tool as a read-only analysis assistant for the user's Unity/gameplay work. The outcome is a Chinese-first explanation of the old path, new path, code facts, supplied intent evidence, inferred rationale, impacts, and unknowns.

Before running an analysis, read [references/workflow.md](references/workflow.md) completely.

## Defaults

- Tool: `D:\\ares\\aeh-change-lens`
- Work repository: the explicitly named repository, otherwise the current Git repository, otherwise `D:\\ares\\project\\ET6`
- Unity project: auto-detect, preferring `<repository>\\Unity`
- Comparison: `HEAD` to `WORKTREE`
- Language: Chinese first
- Output: outside the analyzed repository

Do not expose assembly names, request IDs, manifests, digests, or Worker setup unless they affect the result or the user asks for technical evidence.

## Authority boundary

Explicit invocation authorizes read-only inspection, building the Change Lens repository-owned Worker, and writing report artifacts outside the analyzed repository. It does not authorize modifying, checking out, compiling, or executing target-project code.

Never run `export-compile-manifest` or `export-build-provenance` without separate, explicit authorization in the current conversation because they write evidence files into the target repository. When a baseline is missing, explain the one-time requirement in plain Chinese and stop after safe dry-run diagnostics.

Never claim access to hidden model reasoning. Keep these layers distinct:

- code facts: Git/Roslyn-supported;
- source evidence: statements the user actually supplied;
- intent inference: conservative hypotheses labeled as possible.

## Handoff

Return the clickable report path plus a concise Chinese summary: what changed, old path, new path, likely rationale, direct impacts, and unresolved items. State `PARTIAL` prominently when present. Open the report in a visible browser only when the user asks to open it.
