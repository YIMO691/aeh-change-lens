# CL-WP-00 Dependency and License Review

Status: reviewed for the planned MVP architecture on 2026-08-27. This is an
allowlist decision, not an instruction to install every candidate.

| Component | Planned role | License | WP-00 decision |
|---|---|---|---|
| Python 3.11+ | CLI and orchestration runtime | PSF-2.0 | Allow |
| .NET 8+ | Analyzer worker runtime | MIT | Allow |
| Microsoft.CodeAnalysis.CSharp 5.9.0 (Roslyn) | C# syntax and semantic analysis | MIT | Added in CL-WP-02 with package lock |
| jsonschema | Contract validation in Python | MIT | Allow |
| PyYAML | Governance and fixture contract loading | MIT | Allow |
| Tree-sitter / tree-sitter-c-sharp | Explicit syntax-only fallback | MIT | Allow only behind a partial-mode adapter |
| React | Local viewer | MIT | Allow in CL-WP-06 |
| React Flow (`@xyflow/react`) | Old/new graph viewer | MIT | Allow in CL-WP-06 |
| GumTree | Possible AST mapping experiment | LGPL-3.0 | Do not include in MVP core; requires a new review if proposed |
| Joern | Possible research comparison | Apache-2.0 | Do not include in MVP; unnecessary scope and runtime weight |

Conditions:

1. Lockfiles and exact package versions are reviewed in the work package that
   first introduces each dependency.
2. The shipped product must preserve required notices and license texts.
3. Optional analyzers run behind typed adapters and cannot raise confidence
   beyond the authority defined by the contracts.
4. No SaaS, telemetry SDK, remote model client, or source-upload dependency is
   approved by this review.
5. A dependency or license change is declared in the implementing PR.

Primary references: the official repositories or runtime distributions for
[Roslyn](https://github.com/dotnet/roslyn),
[jsonschema](https://github.com/python-jsonschema/jsonschema),
[PyYAML](https://github.com/yaml/pyyaml),
[Tree-sitter](https://github.com/tree-sitter/tree-sitter),
[React](https://github.com/facebook/react), and
[React Flow](https://github.com/xyflow/xyflow).
