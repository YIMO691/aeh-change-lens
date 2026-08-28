# Change Story HTML report

> English mirror; the [Chinese document](CHANGE_STORY.zh-CN.md) is authoritative. This viewer slice remains inside `CL-WP-02`; it is not a `CL-GATE-02` pass or an activation of a downstream work package.

## Purpose

Change Story turns an evidence-bound OLD/NEW Roslyn graph diff into a self-contained, Chinese-first HTML report. It answers what the old path was, what the new path is, what changed, why the change may have happened, and what remains unknown. It does not read or reconstruct hidden model chain of thought.

## Generate in one command

```powershell
change-lens explain D:\GameRepo Unity `
  --assembly Unity.Model `
  --base <old-commit> `
  --target WORKTREE `
  --request-id CHANGE-001 `
  --intent-evidence intent-evidence.json `
  --analysis-output change-analysis.json `
  --output change-story.html `
  --pretty
```

The command performs revision-bound static analysis, deterministic graph differencing, Change Story projection, and HTML rendering. The existing policy remains in force: no network, no checkout, and no compilation or execution of target-project code.

Render an existing analysis without running Roslyn again:

```powershell
change-lens render-report change-analysis.json `
  --intent-evidence intent-evidence.json `
  --source-root D:\GameRepo\Unity `
  --output change-story.html
```

### Missing historical compile baseline

Strict mode preflights revision-bound `.csproj`/compile manifests before scanning the full source closure. Add `--allow-syntax-partial --progress` only when an explicit lower-confidence report is useful. The resulting report is always `PARTIAL` and contains only the Roslyn syntax/local-symbol subgraph of changed C# files. Current worktree options are never injected into OLD.

The optional Unity source root creates local links only for NEW worktree locations. OLD locations and immutable NEW revisions remain revision/path/line evidence so the current file is never presented as historical source.

## Evidence layers

| Layer | Meaning |
|---|---|
| `CODE_FACT` | Supported by Git, Roslyn, or the deterministic diff |
| `SOURCE_EVIDENCE` | A supplied user goal, AI plan, or commit statement |
| `INTENT_INFERENCE` | A conservative hypothesis derived from code patterns |

Source statements are never promoted to code facts merely because they came from an AI transcript or commit message. Missing source evidence is shown as missing. Intent hypotheses use “may”, carry `INFERRED` confidence, and link to the triggering edge or mapping IDs.

## Focus and safety

The viewer includes relationships that changed or touch a changed node. Each lane is bounded to 80 focused relationships, 16 paths, and eight hops per path; truncation is disclosed while the complete JSON can be retained separately.

The HTML contains no scripts or remote resources. Untrusted titles, labels, paths, and source statements are escaped. Story and analysis artifacts have separate canonical digests. The report is UTF-8, offline, and written only to the caller-selected output path.

## Current limits

- The view is a bounded explanation graph, not a runtime call stack or complete CFG.
- Code alone cannot prove the AI's actual intent.
- Large branching graphs are deterministically truncated and disclosed.
- The viewer is static; filtering, zoom, search, and IDE integration are not implemented.
- There is still one Golden Change rather than the planned 10–20, so `CL-GATE-02` remains open.
