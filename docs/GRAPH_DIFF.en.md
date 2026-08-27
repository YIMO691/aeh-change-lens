# OLD/NEW Graph Diff Contract

> English translation; the [Chinese contract](GRAPH_DIFF.zh-CN.md) is authoritative. This is a deterministic `CL-WP-02` intermediate artifact, not a `CL-GATE-02` pass claim.

`graph-diff` combines two Roslyn Worker `analyzer-result` documents into one revision-aware graph. Nodes and edges retain their `OLD`/`NEW` identities and receive `ADDED`, `REMOVED`, `UPDATED`, `MOVED`, or `UNCHANGED_CONTEXT` change labels. The output validates against `schemas/analyzer-diff.schema.json` and is intended as direct input to the future Viewer and Explain Bundle assembler.

```powershell
change-lens graph-diff old-result.json new-result.json `
  --renames renames.json `
  --mapping-hints mapping-hints.json `
  --pretty
```

Types and methods with the same Roslyn-qualified identity are mapped as `SAME_SYMBOL / CONFIRMED_STATIC`. A synthetic node is mapped as `HEURISTIC / STRUCTURAL` only when its kind, label, and normalized path form a unique pair. Duplicate candidates are never paired by line number or occurrence order. Renames, cross-type moves, and lifecycle replacements require reviewed mapping hints; these hints remain structural evidence rather than being presented as Roslyn confirmation.

An edge is paired as `UNCHANGED_CONTEXT` only when its mapped endpoints and relation are identical. Other OLD edges are `REMOVED`, and other NEW edges are `ADDED`; those relation changes propagate `UPDATED` to mapped context nodes.

`fixtures/unity-minimal` is the first human-annotated Golden Change. Its frozen projection contains 19 OLD nodes, 25 NEW nodes, 11 mappings, 14 added nodes, 8 removed nodes, 14 added edges, 8 removed edges, and 8 unchanged edge pairs. Two duplicate state-access groups deliberately remain ambiguous and unmapped.

The `canonical_digest` covers the source statuses, both graphs, mappings, summary, and limitations. Identical inputs and configuration must produce the same digest.

## One-command historical analysis

`change-lens analyze-change <repository> <unity-project-relative-path> --assembly <name> --base <commit> --target WORKTREE --request-id <id>` binds both snapshots, hash-validates and materializes each lane into a separate temporary directory, builds each Unity Context, runs the repository-owned static Worker, and emits the final graph diff together with revision manifests, compile-input provenance, context digests, rename evidence, policy, and a canonical digest.

For repositories that ignore Unity-generated projects, run `change-lens export-compile-manifest <repository> <unity-project> --assembly <name>` at the baseline and commit `.aeh-change-lens/compile-manifests/<Assembly>.json`; re-export after source changes. The portable manifest binds generated defines, the exact source set and line-ending-normalized semantic hashes, metadata names/hashes, and project references without storing machine-local absolute paths. Each snapshot still binds exact source bytes. A live csproj may only locate a local DLL with the same name and SHA-256; none of its source or option semantics are borrowed. A missing manifest, changed digest, or stale source fails before the Worker. Commits created before a manifest baseline are not guessed retroactively, and the command never starts Unity or executes target-project code.
