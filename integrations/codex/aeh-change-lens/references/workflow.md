# Personal workflow

Read this file only after the user explicitly invokes `$aeh-change-lens` or clearly asks Codex to use Change Lens.

## 1. Resolve the workspace

Use this precedence:

1. repository and Unity project named by the user;
2. the current exact Git root and its Unity project;
3. `D:\ares\project\ET6` and `D:\ares\project\ET6\Unity`.

Confirm the Git root with a read-only command. Find Unity roots by the pair `Assets/` plus `ProjectSettings/ProjectVersion.txt`. Do not recursively search outside the selected repository.

When the user names a workspace container rather than an exact Git root, inspect only its immediate project directories to find the exact root. Never pass a non-repository parent directory to Change Lens. For the personal Ares2 workspace, resolve `D:\ares2` to `D:\ares2\project\ET6` and its `Unity` child when those boundaries are present.

The tool root is `D:\ares\aeh-change-lens`. Invoke its source checkout without installing it globally:

```powershell
python D:\ares\aeh-change-lens\run_change_lens.py <arguments>
```

If `worker/ChangeLens.Analyzer/bin/Release/net8.0/ChangeLens.Analyzer.dll` is absent, build only that repository-owned Worker:

```powershell
dotnet build D:\ares\aeh-change-lens\worker\ChangeLens.Analyzer\ChangeLens.Analyzer.csproj --configuration Release
```

Never build the analyzed Unity project.

## 2. Select the comparison

Default to `HEAD -> WORKTREE`. Respect explicit revisions.

Inspect changed `.cs`, `.asmdef`, package, and project-setting paths. Resolve assemblies from the nearest applicable `.asmdef` or generated project. If all relevant changes map to one assembly, use it without asking. For ET6, prefer `Unity.Model` when the changed paths belong to that project.

When two or three assemblies are independently affected, generate one report per assembly. When resolution remains ambiguous or more than three assemblies are material, ask the user to select; do not guess.

Create a non-sensitive request ID. Store reports under `D:\ares\change-lens-output\<repository-name>\`; keep `latest.html`, `latest.story.json`, and `latest.analysis.json`. This directory is outside ET6 and may be updated by an explicit skill invocation.

If the current request contains a user goal or an AI plan, create `latest.intent.json` in the same output directory using the `intent-evidence.schema.json` contract. Include only statements actually supplied in the conversation. Do not generate a synthetic plan.

## 3. Run

Use the one-command path:

```powershell
python D:\ares\aeh-change-lens\run_change_lens.py explain <repository> <unity-relative-path> `
  --assembly <assembly> `
  --base <base> `
  --target <target> `
  --request-id <id> `
  --intent-evidence <intent-json-if-present> `
  --analysis-output D:\ares\change-lens-output\<repository-name>\latest.analysis.json `
  --story-output D:\ares\change-lens-output\<repository-name>\latest.story.json `
  --output D:\ares\change-lens-output\<repository-name>\latest.html `
  --allow-syntax-partial `
  --progress `
  --pretty
```

Omit `--intent-evidence` when no source evidence was supplied. Do not turn tool failure into an inferred report.

## 4. Missing baseline

If an OLD or NEW lane has no revision-bound generated project or compile manifest:

1. let `explain --allow-syntax-partial` generate a changed-C# report outside the repository;
2. require the result status to be `PARTIAL` and disclose that unchanged dependencies, defines, metadata, complete assembly boundaries, and runtime bindings are absent;
3. run `export-compile-manifest ... --dry-run` only when it can clarify readiness for a future strict analysis;
4. ask whether the user authorizes creating an evidence file in the target repository before any non-dry-run export.

Do not copy NEW project options into OLD, edit Git history, or promote syntax-only relationships to compile-confirmed facts. If authorized later, export the manifest but do not stage or commit it unless separately requested. A manifest created after changes already exist is a baseline for later changes; do not claim that it repairs the missing OLD context for the current comparison.

## 5. Validate and explain

Require exit code zero, present HTML/story/analysis files, and matching analysis digest in the command result. Read `latest.story.json` first.

For quick understanding, report:

- `visual_map.change_shape` and `visual_map.headline_zh`;
- the bounded `before` / `changes` / `after` items without raw signatures;
- `visual_map.impact_zh` and `visual_map.risk_zh`;
- whether `relationship_mode` is `VERIFIED_FLOW` or `PARALLEL_FACTS`.

Do not narrate `PARALLEL_FACTS` in display order as a call chain. Use `quick_view` only for optional area and mental-model context after the visual map.

For a requested detailed breakdown, additionally report:

- `deep_dive.stages` and representative relationships;
- `deep_dive.decision_points`;
- source-backed rationale separately from inferred rationale;
- unresolved dynamic/Unity bindings.

Use the full analysis JSON only to verify or expand technical evidence. Always report:

- status (`FRESH` or `PARTIAL`);
- limitations material to the requested conclusion.

Give the user a clickable local HTML path. Do not lead with node/edge counts. Keep raw counts, hashes, and schema details in a short technical-evidence note only when requested.
