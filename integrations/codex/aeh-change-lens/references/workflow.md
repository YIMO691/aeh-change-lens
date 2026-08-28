# Personal workflow

Read this file only after the user explicitly invokes `$aeh-change-lens` or clearly asks Codex to use Change Lens.

## 1. Resolve the workspace

Use this precedence:

1. repository and Unity project named by the user;
2. the current exact Git root and its Unity project;
3. `D:\ares\project\ET6` and `D:\ares\project\ET6\Unity`.

Confirm the Git root with a read-only command. Find Unity roots by the pair `Assets/` plus `ProjectSettings/ProjectVersion.txt`. Do not recursively search outside the selected repository.

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

Create a non-sensitive request ID. Store reports under `D:\ares\change-lens-output\<repository-name>\`; keep `latest.html` and `latest.analysis.json`. This directory is outside ET6 and may be updated by an explicit skill invocation.

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
  --output D:\ares\change-lens-output\<repository-name>\latest.html `
  --pretty
```

Omit `--intent-evidence` when no source evidence was supplied. Do not turn tool failure into an inferred report.

## 4. Missing baseline

If analysis rejects an OLD or NEW lane because no revision-bound generated project or compile manifest exists:

1. run `export-compile-manifest ... --dry-run` only when it can clarify readiness;
2. report that the project needs a one-time local/committed compile baseline;
3. ask whether the user authorizes creating that evidence file in the target repository;
4. stop until authorized.

Do not copy NEW project options into OLD, edit Git history, or weaken stale/hash checks. If authorized later, export the manifest but do not stage or commit it unless separately requested.

## 5. Validate and explain

Require exit code zero, a present HTML file, a present analysis JSON, and matching analysis digest in the command result. Read the analysis JSON and report:

- status (`FRESH` or `PARTIAL`);
- main added/removed/updated/moved counts;
- the most relevant changed relationships;
- source-backed rationale separately from inferred rationale;
- limitations and unresolved dynamic/Unity bindings.

Give the user a clickable local HTML path. Keep raw hashes and schema details in a short technical-evidence note rather than the main explanation.
