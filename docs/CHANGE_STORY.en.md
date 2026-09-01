# Change Canvas HTML report

> English mirror; the [Chinese document](CHANGE_STORY.zh-CN.md) is authoritative. This viewer slice remains inside `CL-WP-02`; it is not a `CL-GATE-02` pass or an activation of a downstream work package.

## Purpose

Change Story turns an evidence-bound OLD/NEW Roslyn graph diff into a brief explanation followed by one verification action and an observable success signal. The Chinese-first Change Canvas, question-led chapters, semantic passports, and detailed evidence remain available on demand. The breakdown reconstructs an engineering structure from evidence; it is not hidden model chain of thought.

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

## Change Canvas reading model

### Default entry: 10-second Change Capsule

The `explain` command returns `change_capsule` and `verification_mission` directly. Codex responds with only six lines: conclusion, before, after, impact, first action, and observable success signal. Users do not need to open the HTML. A `PARTIAL` sentence may follow once; later steps, chapters, nodes, paths, hashes, and report locations remain hidden by default.

The capsule compares stable business labels: common labels are retained responsibilities, OLD-only labels are removed focus, and NEW-only labels are added focus. This is a version comparison, not an inferred call sequence or one-to-one mapping.

### Guided verification: one step at a time

`change_canvas.verification_mission` contains one to three deterministic steps. Every step carries bilingual action and success text plus `evidence_refs` for investigating a mismatch. Mission state is `SUGGESTED` or `PARTIAL`; report generation never marks it completed. When the user asks to be guided, Codex presents only the current step, waits for the observed result, then advances or inspects that step's evidence. Target-project compilation, execution, and mutation still require separate authorization.

### On-demand entry: four-beat visual story

When the user asks to expand or explain why, the HTML opens with a bounded four-beat storyboard: Before, Change, Now, and Verify. It uses at most seven stable business slots, keeps the same business label in the same position, shows old-to-new state inside each DELTA slot, and reserves the VERIFY beat for one action and observable success signal. DELTA is the default so the answer appears immediately.

Only exact business-label matches share a slot; single-sided items remain visibly added or removed. Existing `VERIFIED_FLOW` relationships may appear as connectors, while `PARALLEL_FACTS` never receive arrows.

### On-demand drill-down: Change Canvas

The detailed Change Canvas is collapsed below the storyboard. Expanding it reveals BEFORE/DELTA/AFTER controls, up to five question-led chapters, OLD/NEW nodes, change counts, semantic passports, and technical evidence.

The page does not visibly print analysis or story digests. A `PARTIAL` warning appears once.

### Chapters and semantic passports

Each chapter contains at most three BEFORE nodes, four AFTER nodes, and six explicit relationships. Selecting a node reveals its business label, technical name, revision side, change kind, confidence, source location, and evidence identifiers. Added, removed, and empty-sided scenarios remain asymmetric instead of receiving invented placeholder nodes.

### Relationship truth

- `VERIFIED_FLOW` renders only relationships already supported by scenario edges.
- `PARALLEL_FACTS` renders no directional arrows.
- Column placement, node position, and reading order never imply a call.
- `PARTIAL` syntax-only evidence is not promoted to complete static or runtime truth.

### Detailed evidence

Verification boundaries, completion criteria, impacts, evidence-layer claims, symbol changes, and limitations remain below the canvas and collapsed by default. HTML shows representative entries for very long lists; the complete deterministic payload remains in `change-story.json`. Codex should use the returned capsule and mission first, inspect the rest of `change_canvas` only after a follow-up, and open the full analysis only when needed.

## Focus and safety

The quick layer scores change type, business entry points, topic overlap, and cross-layer role. Ordinary generated and test code cannot displace the primary business flow. When changed protocol files do not yield field-level Roslyn nodes, the report shows only file-context evidence rather than inventing field semantics. Technical lanes remain bounded to 80 focused relationships, 16 paths, and eight hops per path.

The HTML contains no scripts or remote resources. Untrusted titles, labels, paths, and source statements are escaped. Story and analysis artifacts have separate canonical digests. The report is UTF-8, offline, and written only to the caller-selected output path.

## Current limits

- The view is a bounded explanation graph, not a runtime call stack or complete CFG.
- Code alone cannot prove the AI's actual intent.
- Large branching graphs are deterministically truncated and disclosed.
- The viewer uses a script-free canvas, radio controls, and disclosure panels; search, free zoom, and IDE integration are not implemented.
- There is still one Golden Change rather than the planned 10–20, so `CL-GATE-02` remains open.
