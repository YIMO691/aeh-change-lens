# AEH Change Lens Implementation Plan

> Language: English translation; the Chinese plan is authoritative.
> Status: `PLAN_READY / IMPLEMENTATION_AUTHORIZATION_GRANTED / CL-GATE-01_PASSED / CL-WP-02_IN_PROGRESS`
> Canonical Chinese plan: [IMPLEMENTATION_PLAN.zh-CN.md](IMPLEMENTATION_PLAN.zh-CN.md)
> Machine contract: [proposal.yaml](../governance/proposal.yaml)

## 1. Outcome

For one explicit AEH Change, a reviewer should be able to identify the old logic path, new logic path, material graph delta, evidence-backed reason for each material change, verification coverage, and remaining uncertainty without reading the entire diff.

The product explains externally recorded rationale. It never claims to expose or reconstruct hidden model chain of thought.

## 2. Confirmed Owner decisions

| ID | Decision |
|---|---|
| CL-DEC-001 | C# is the first analyzed language, focused on Unity/gameplay code |
| CL-DEC-002 | Separate repository; Python CLI/orchestration plus a .NET/Roslyn analyzer worker |
| CL-DEC-003 | Deterministic offline core; LLM explanation is explicit opt-in |
| CL-DEC-004 | Change authors and reviewers are the primary users |
| CL-DEC-005 | Pilot with 10–20 manually annotated Changes |
| CL-DEC-006 | Chinese launch product/UI; Chinese plan authoritative, English plan retained |

These decisions make the plan executable. The Owner explicitly authorized implementation on 2026-08-27; release remains subject to a separate Gate.

## 3. MVP boundary

In scope: one local Git repository, one `CHG-*`, base versus worktree/target revision, C# in Unity projects, `.asmdef` and available compilation context, changed symbols plus one bounded relationship hop, calls/branches/errors/recognized side effects, Unity lifecycle and event relationships, syntax-aware graph delta, AEH evidence links, deterministic Explain Bundle, local read-only Chinese UI, and static HTML export.

Out of scope: whole-repository knowledge graphs, multiple first-release languages, hidden reasoning capture, AEH Gate mutation, default networking or telemetry, complete dynamic/runtime reconstruction, multi-agent orchestration, and presenting inference as fact.

## 4. Authority and confidence

Change Lens is a projection, not a new source of truth. Git owns revisions and source bytes; AEH owns Change and Gate truth; compiler/indexer facts are `CONFIRMED_STATIC`; parsed syntax is `STRUCTURAL`; authorized traces are `OBSERVED_RUNTIME`; generated rationale is `INFERRED`; unresolved facts are `UNKNOWN`.

No confidence level may be raised without a stronger source. The translation layer cannot alter semantic facts.

## 5. Architecture

```text
Snapshot Resolver
  -> Python Language Adapter
  -> Semantic Differ
  -> AEH Evidence Linker
  -> Explain Bundle Builder
  -> Chinese-first Local Viewer / Static Export
```

The static MVP reads Git objects without checkout and does not execute project code. Runtime evidence is a later, explicit, separately authorized overlay.

## 6. Work packages

| Work package | Output | Exit Gate |
|---|---|---|
| CL-WP-00 | Bundle/adapter contracts, annotated fixtures, privacy policy | P0 oracles, adversarial corpus and licenses reviewed |
| CL-WP-01 | Snapshot resolver, digests, rename/path/stale handling | No checkout/execution; escape blocked; stale proven |
| CL-WP-02 | Roslyn C#/Unity symbols, calls, branches, lifecycle, events and side effects | Golden graphs pass; missing Unity context and dynamic binding remain explicit |
| CL-WP-03 | Old/new node mapping and graph delta | Mapping measured; move/rename and ambiguity handled honestly |
| CL-WP-04 | Read-only AEH linker and canonical Bundle | Deterministic; forged/missing/stale refs fail closed; AEH unchanged |
| CL-WP-05 | Deterministic and optional LLM explanation | Claims cited or inferred; prompt injection cannot change authority |
| CL-WP-06 | Chinese old/new viewer and export | Chinese facts match the Bundle; accessible; offline |
| CL-WP-07 | Measured pilot | Explicit CONTINUE, REPOSITION, or STOP decision |

## 7. P0 acceptance criteria

- `CL-AC-001`: deterministic binding of revisions, inputs, analyzers and configuration.
- `CL-AC-002`: any bound-input change makes the report `STALE`.
- `CL-AC-003`: old/new locations and change kinds never mix.
- `CL-AC-004`: every material node, edge, rationale and verification has provenance and confidence.
- `CL-AC-005`: no write path to AEH machine truth, approvals or Gates.
- `CL-AC-006`: no hidden-chain-of-thought claim.
- `CL-AC-007`: default output is a bounded Change subgraph.
- `CL-AC-008`: material changes are evidence-linked or visibly `UNLINKED`.
- `CL-AC-009`: missing, invalid, escaped, unsupported and unresolved inputs fail closed or become explicit partial results.
- `CL-AC-010`: pilot reviewers can answer the five product questions.
- `CL-AC-011`: the launch UI is Chinese; English plan documentation cannot conflict with the authoritative Chinese plan, and a future English UI must reuse the same Bundle.
- `CL-AC-012`: Unity assembly, lifecycle and platform context is provenance-bound; incomplete context cannot yield a complete-confidence path.

## 8. Invariants and risks

The governed invariants are `CL-INV-001` through `CL-INV-013`; risks are `CL-RISK-001` through `CL-RISK-012`. Their authoritative statements and mitigations are in the Chinese plan and machine-readable proposal.

The main risks are false certainty, graph explosion, stale explanations, AEH TCB expansion, source disclosure, prompt injection, incomplete Unity compilation context, framework lifecycle/event misrepresentation, license conflict, lack of reviewer value, and bilingual semantic drift.

## 9. Anti-drift PR rule

Every implementation PR must name one primary `CL-WP-*`, list affected acceptance/invariant/risk IDs, provide raw exit-Gate evidence, declare scope/trust/data/dependency/confidence changes, and update Chinese, English and YAML governance artifacts together when governed fields change.

An Owner decision is required before changing the target user, scope, mutation authority, confidence semantics, P0 criteria, invariants, work-package order, privacy default, first language, or delivery topology.

## 10. Start condition

```text
PLAN_READY
IMPLEMENTATION_AUTHORIZATION_GRANTED
CL-GATE-00_PASSED
CL-GATE-01_PASSED
CL-WP-02_IN_PROGRESS
RELEASE_NOT_ASSESSED
```

The Owner explicitly authorized entry into `CL-WP-00` with the instruction “开始实施” on 2026-08-27. This authorization does not automatically permit target-project execution, analyzed-source upload, unsandboxed tests, or AEH repository mutation.

Raw `CL-GATE-00` verification evidence is recorded in [CL-GATE-00.md](../governance/gates/CL-GATE-00.md).
Raw `CL-GATE-01` verification evidence is recorded in [CL-GATE-01.md](../governance/gates/CL-GATE-01.md).
