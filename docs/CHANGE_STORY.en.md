# Change Story HTML report

> English mirror; the [Chinese document](CHANGE_STORY.zh-CN.md) is authoritative. This viewer slice remains inside `CL-WP-02`; it is not a `CL-GATE-02` pass or an activation of a downstream work package.

## Purpose

Change Story turns an evidence-bound OLD/NEW Roslyn graph diff into a self-contained, Chinese-first HTML report: one question-first scenario by default, OLD/NEW comparison on demand, and a detailed implementation breakdown as evidence. The breakdown reconstructs an engineering structure from evidence; it is not hidden model chain of thought.

## Generate in one command

```powershell
change-lens explain D:\GameRepo Unity `
  --assembly Unity.Model `
  --base <old-commit> `
  --target WORKTREE `
  --request-id CHANGE-001 `
  --intent-evidence intent-evidence.json `
  --analysis-output change-analysis.json `
  --story-output change-story.json `
  --output change-story.html `
  --pretty
```

The command performs revision-bound static analysis, deterministic graph differencing, Change Story projection, and HTML rendering. The existing policy remains in force: no network, no checkout, and no compilation or execution of target-project code.

Render an existing analysis without running Roslyn again:

```powershell
change-lens render-report change-analysis.json `
  --intent-evidence intent-evidence.json `
  --source-root D:\GameRepo `
  --story-output change-story.json `
  --output change-story.html
```

### Missing historical compile baseline

Strict mode preflights revision-bound `.csproj`/compile manifests before scanning the full source closure. Add `--allow-syntax-partial --progress` only when an explicit lower-confidence report is useful. The resulting report is always `PARTIAL` and contains only the Roslyn syntax/local-symbol subgraph of changed C# files. Current worktree options are never injected into OLD.

The optional Git repository root creates local links only for NEW worktree locations. OLD locations and immutable NEW revisions remain revision/path/line evidence so the current file is never presented as historical source.

## Evidence layers

| Layer | Meaning |
|---|---|
| `CODE_FACT` | Supported by Git, Roslyn, or the deterministic diff |
| `SOURCE_EVIDENCE` | A supplied user goal, AI plan, or commit statement |
| `INTENT_INFERENCE` | A conservative hypothesis derived from code patterns |

Source statements are never promoted to code facts merely because they came from an AI transcript or commit message. Missing source evidence is shown as missing. Intent hypotheses use “may”, carry `INFERRED` confidence, and link to the triggering edge or mapping IDs.

## Three reading depths

The default Daily Brief answers “What should I look at first today?” with one plain-language change sentence, up to three memory points, work impact, and two or three verification suggestions. Suggestions remain explicitly separate from code facts and retain evidence references.

Understand the change opens Scenario Lens. It answers one reader question, offers at most five scenarios, and bounds each scenario to at most seven OLD/NEW focus objects and six evidence-backed relationships. Each scenario has its own `change_shape`: `ADDED` and `REMOVED` use an asymmetric full-width capability canvas, while `MODIFIED` uses OLD/NEW columns. Technical names stay collapsed. `VERIFIED_FLOW` renders only listed exact relationships as path cards; `PARALLEL_FACTS` remains directionless.

Check evidence contains staged implementation evidence, decisions, claims, raw paths, impacts, and limitations.

Change Map Lite remains available as an on-demand OLD / NEW comparison. It classifies the evidence as `MODIFIED`, `ADDED`, `REMOVED`, `TEST_ONLY`, `CONFIG_PROTOCOL`, or `PARALLEL`, then shows a bounded Before / Core change / After map with at most three items per column. The columns are always revision comparison, never calls between the displayed items.

Impact scope and the first material risk stay visible. The mental model and up to five area cards move into an optional support disclosure, while long signatures, repeated conditions, generated-code counts, and full graph relationships stay out of the landing view.

The detailed view groups representative objects, relationships, and new decision points by configuration, server, protocol, Unity Editor tooling, client, runtime, and test stages. Stages and decision sections are collapsed by default. Full claims, raw paths, symbol tables, impacts, and limitations remain available under collapsed technical evidence.

`--story-output` optionally writes the same focused `change-story.json`; Codex should read it before the much larger `change-analysis.json`.

## Focus and safety

The quick layer scores change type, business entry points, topic overlap, and cross-layer role. Ordinary generated and test code cannot displace the primary business flow. When changed protocol files do not yield field-level Roslyn nodes, the report shows only file-context evidence rather than inventing field semantics. Technical lanes remain bounded to 80 focused relationships, 16 paths, and eight hops per path.

The HTML contains no scripts or remote resources. Untrusted titles, labels, paths, and source statements are escaped. Story and analysis artifacts have separate canonical digests. The report is UTF-8, offline, and written only to the caller-selected output path.

## Current limits

- The view is a bounded explanation graph, not a runtime call stack or complete CFG.
- Code alone cannot prove the AI's actual intent.
- Large branching graphs are deterministically truncated and disclosed.
- The viewer uses script-free tabs and disclosure panels; search, zoom, and IDE integration are not implemented.
- There is still one Golden Change rather than the planned 10–20, so `CL-GATE-02` remains open.
