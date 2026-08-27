# AEH Change Lens Implementation Plan

> Language: English translation; the Chinese plan is authoritative.
> Status: `PLAN_READY / IMPLEMENTATION_AUTHORIZATION_NOT_GRANTED`
> Canonical Chinese plan: [IMPLEMENTATION_PLAN.zh-CN.md](IMPLEMENTATION_PLAN.zh-CN.md)
> Machine contract: [proposal.yaml](../governance/proposal.yaml)

## 1. Outcome

For one explicit AEH Change, a reviewer should be able to identify the old logic path, new logic path, material graph delta, evidence-backed reason for each material change, verification coverage, and remaining uncertainty without reading the entire diff.

The product explains externally recorded rationale. It never claims to expose or reconstruct hidden model chain of thought.

## 2. Confirmed Owner decisions

| ID | Decision |
|---|---|
| CL-DEC-001 | Python is the first analyzed language |
| CL-DEC-002 | Separate repository and Python package outside the AEH TCB |
| CL-DEC-003 | Deterministic offline core; LLM explanation is explicit opt-in |
| CL-DEC-004 | Change authors and reviewers are the primary users |
| CL-DEC-005 | Pilot with 10–20 manually annotated Changes |
| CL-DEC-006 | Bilingual product and documentation, Chinese authoritative and first |

These decisions make the plan executable. They do not authorize implementation or release.

## 3. MVP boundary

In scope: one local Git repository, one `CHG-*`, base versus worktree/target revision, Python, changed symbols plus one bounded relationship hop, calls/branches/errors/recognized side effects, syntax-aware graph delta, AEH evidence links, deterministic Explain Bundle, local read-only UI, static HTML export, and Chinese-first bilingual presentation.

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
| CL-WP-02 | Python symbols, calls, branches, errors, side effects | Golden graphs pass; dynamic ambiguity remains explicit |
| CL-WP-03 | Old/new node mapping and graph delta | Mapping measured; move/rename and ambiguity handled honestly |
| CL-WP-04 | Read-only AEH linker and canonical Bundle | Deterministic; forged/missing/stale refs fail closed; AEH unchanged |
| CL-WP-05 | Deterministic and optional LLM explanation | Claims cited or inferred; prompt injection cannot change authority |
| CL-WP-06 | Bilingual old/new viewer and export | Same facts in both languages; accessible; offline |
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
- `CL-AC-011`: Chinese is default, English is available, and translation cannot change facts.

## 8. Invariants and risks

The governed invariants are `CL-INV-001` through `CL-INV-011`; risks are `CL-RISK-001` through `CL-RISK-010`. Their authoritative statements and mitigations are in the Chinese plan and machine-readable proposal.

The main risks are false certainty, graph explosion, stale explanations, AEH TCB expansion, source disclosure, prompt injection, Python dynamic-semantics mismatch, license conflict, lack of reviewer value, and bilingual semantic drift.

## 9. Anti-drift PR rule

Every implementation PR must name one primary `CL-WP-*`, list affected acceptance/invariant/risk IDs, provide raw exit-Gate evidence, declare scope/trust/data/dependency/confidence changes, and update Chinese, English and YAML governance artifacts together when governed fields change.

An Owner decision is required before changing the target user, scope, mutation authority, confidence semantics, P0 criteria, invariants, work-package order, privacy default, first language, or delivery topology.

## 10. Start condition

```text
PLAN_READY
IMPLEMENTATION_AUTHORIZATION_NOT_GRANTED
RELEASE_NOT_ASSESSED
```

Implementation may enter `CL-WP-00` only after explicit Owner authorization. Such authorization does not automatically permit project-code execution, source upload, unsandboxed tests, or AEH repository mutation.
