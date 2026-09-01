# AEH Change Lens

[![Governed checks](https://github.com/YIMO691/aeh-change-lens/actions/workflows/contracts.yml/badge.svg)](https://github.com/YIMO691/aeh-change-lens/actions/workflows/contracts.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](pyproject.toml)
[![.NET 8](https://img.shields.io/badge/.NET-8.0-512BD4.svg)](worker/ChangeLens.Analyzer/ChangeLens.Analyzer.csproj)

[中文](README.md) | English | [Documentation index](docs/README.md)

AEH Change Lens is a read-only change-explanation tool for Unity/C# gameplay code. It first explains the change briefly, then offers one small verification action with an observable success signal. The Change Canvas and implementation evidence remain available on demand.

It does not read or reconstruct hidden model chain of thought.

The interaction borrows the “learn by completing a real outcome” principle from [project-based-learning](https://github.com/practical-tutorials/project-based-learning) and narrows it to one 1–5 minute mission per change. AEH neither copies its tutorial catalog nor depends on its code.

> [!IMPORTANT]
> This project is a development preview. `CL-WP-02` remains `IN_PROGRESS`, and no release assessment has been completed. The current build is intended for a controlled personal workflow and prototype validation.

## Features

- Compare an OLD Git revision with a NEW revision or worktree without checkout.
- Extract calls, branches, exceptions, state access, lifecycle, coroutine, async, event, and common Unity relationships with Roslyn.
- Produce deterministic added, removed, updated, moved, and context relationships.
- Return a 10-second Change Capsule plus a `verification_mission`, with an action and observable success signal.
- Guide “verify this with me” one step at a time without presenting a suggested mission as already executed.
- Keep the script-free Change Canvas as an optional drill-down with BEFORE/DELTA/AFTER views, chapters, and semantic passports.
- De-emphasize generated code, tests, and syntax fragments on the landing view, then organize changes by configuration, server, protocol, client, and tests.
- Keep `CODE_FACT`, `SOURCE_EVIDENCE`, and `INTENT_INFERENCE` separate.
- Fail closed or become explicitly `PARTIAL` when evidence is missing, stale, escaped, or unsupported.
- Offer an explicit-only `$aeh-change-lens` Codex Skill for the personal workflow.

See the [capability matrix](docs/CAPABILITY_MATRIX.en.md) for exact coverage.

## Quick start

### Codex workflow

```powershell
.\integrations\codex\install_skill.ps1
```

Start a new Codex session and invoke:

```text
$aeh-change-lens analyze my current ET6 changes
```

The Skill does not activate implicitly during ordinary coding tasks. It defaults to the current Git repository, then the personal ET6 workspace, and writes reports outside the analyzed repository. Its default answer contains the conclusion, before, after, impact, the first action, and its success signal. Ask it to “verify this with me” for one-step-at-a-time guidance, or “expand” for the canvas and evidence.

### CLI workflow

Requirements: Python 3.11+, .NET SDK 8.0, Git, and revision-bound Unity project context or compile manifests.

```powershell
python -m pip install -e ".[contract]"
dotnet build worker\ChangeLens.Analyzer\ChangeLens.Analyzer.csproj --configuration Release

change-lens explain D:\GameRepo Unity `
  --assembly Unity.Model `
  --base HEAD `
  --target WORKTREE `
  --request-id CHANGE-001 `
  --analysis-output change-analysis.json `
  --story-output change-story.json `
  --output change-story.html `
  --pretty
```

Strict mode preflights revision-bound projects/manifests before hashing the full source closure. When a historical lane has no baseline, an explicit structural fallback is available:

```powershell
change-lens explain D:\GameRepo Unity `
  --assembly Unity.Model `
  --base HEAD `
  --target WORKTREE `
  --request-id CHANGE-001 `
  --analysis-output change-analysis.json `
  --story-output change-story.json `
  --output change-story.html `
  --allow-syntax-partial `
  --progress `
  --pretty
```

This mode analyzes only changed C# files in the repository and is always `PARTIAL`. It does not inject current compile options into OLD or claim complete assembly semantics.

Run directly from the source checkout without installing the package:

```powershell
python .\run_change_lens.py --help
```

See [Change Canvas](docs/CHANGE_STORY.en.md) for the complete command and intent-evidence contract.

## Output

The default Codex response is a six-line result: conclusion, before, after, impact, first action, and success signal. Users do not need to open a report. `verification_mission` contains one to three evidence-linked steps, but only the first is shown until the user reports an observed result. When detail is requested, the HTML provides the DELTA canvas, question-led chapters, and semantic passports. Only `VERIFIED_FLOW` relationships receive arrows; `PARALLEL_FACTS` remain explicitly unordered.

Detailed claims, impacts, symbol changes, and limitations remain collapsed below the canvas. Long lists show representative entries in HTML while the complete deterministic data stays in the optional `change-story.json`.

## Compile baseline

Trustworthy historical analysis requires each lane to contain either its matching generated Unity `.csproj` or a revision-bound compile manifest. Repositories that ignore generated projects should establish a baseline while the relevant code is clean:

```powershell
change-lens export-compile-manifest D:\GameRepo Unity --assembly Unity.Model --pretty
```

This writes `.aeh-change-lens/compile-manifests/<Assembly>.json` into the target repository. The Codex Skill requires separate authorization before doing so. Change Lens never substitutes current compile options for missing historical evidence.

## Safety boundary

The default policy denies network access, checkout, target-project compilation/execution, and mutation of AEH normative truth. It allows building the repository-owned Roslyn Worker and writing reports to a caller-selected location.

Report vulnerabilities privately according to [SECURITY.md](SECURITY.md). Do not attach proprietary project source to public issues.

## Project layout

```text
src/aeh_change_lens/          Python orchestration and reports
worker/ChangeLens.Analyzer/   .NET 8 / Roslyn static-analysis Worker
schemas/                      JSON Schema contracts
fixtures/                     Human-reviewed Unity Golden Change
tests/                        Contract, snapshot, analyzer, report, and integration tests
integrations/codex/           Explicit-only personal Codex Skill
governance/                   Work packages, Gates, and raw verification
docs/                         Authoritative Chinese docs and English mirrors
```

## Development

```powershell
python -m pip install -e ".[contract]"
dotnet build worker\ChangeLens.Analyzer\ChangeLens.Analyzer.csproj --configuration Release
python -m unittest discover -s tests -v
```

Only the repository-owned Worker may be built by the test workflow. Real Unity pilots must be explicitly configured and remain read-only.

## Documentation

- [Documentation index](docs/README.md)
- [Implementation plan](docs/IMPLEMENTATION_PLAN.en.md)
- [Change Canvas report](docs/CHANGE_STORY.en.md)
- [C#/Unity capability matrix](docs/CAPABILITY_MATRIX.en.md)
- [OLD/NEW graph diff](docs/GRAPH_DIFF.en.md)
- [Roslyn Worker](docs/ROSLYN_WORKER.en.md)
- [Snapshot contract](docs/SNAPSHOT_CONTRACT.en.md)

## Contributing and support

Read [CONTRIBUTING.md](CONTRIBUTING.md), [SUPPORT.md](SUPPORT.md), and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Current Gate evidence is recorded in [CL-GATE-02 progress](governance/gates/CL-GATE-02-progress.md).

## License

[MIT License](LICENSE)
