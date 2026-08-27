# CL-GATE-02 progress — Real Unity metadata vertical slice

- Status: `IN_PROGRESS` — this is not exit-Gate evidence
- Date: `2026-08-27`
- Primary work package: `CL-WP-02`
- Pilot input: local `D:\ares\project\ET6\Unity` (read-only)
- Unity version: `2020.3.26f1c1`
- Assembly: `Unity.Model`

## Implemented in this increment

- namespace-agnostic parsing of Unity-generated MSBuild projects;
- `.asmdef`, Unity version, define, Compile glob and ProjectReference discovery;
- SHA-256 binding of metadata DLLs and context canonical digest;
- Worker-side digest verification before `MetadataReference.CreateFromFile`;
- rejection of missing, changed, non-DLL and reparse-point metadata inputs;
- recursive ProjectReference assembly graph with explicit dependency status;
- `Library/ScriptAssemblies` discovery without treating unproven output as trusted metadata;
- snapshot-only Worker input assembly with pre/post stale checks;
- separate raw-snapshot and UTF-8 transport digests for legacy source encoding;
- strict UTF-8, UTF BOM and GB18030 source decoding;
- confidence upgrade only when a bound `UnityEngine.CoreModule.dll` resolves
  `MonoBehaviour` and `UnityEventBase`;
- caller-provided source stubs cannot overstate Unity context.

## ET6 read-only measurements

```text
defines=140
metadata_references=221
unity_references=69
project_references=5
source_files=632
assembly_graph_nodes=6
assembly_graph_edges=12
selected_snapshot_files=9325
assembled_source_files=632
source_encodings=UTF-8:336,UTF-8-BOM:273,GB18030:23
completeness=PARTIAL
context_digest=30242841ab9333fdf5f5c0e0257959a659f7f1c9f465c9838c7e259fb318655c
assembly_graph_digest=3bb255e149e693090d7c3fd4865127fd7773890eae44ef025ba0b5d7c9ef1f87
```

The graph recursively follows the five root `ProjectReference` entries. Four
corresponding `Library/ScriptAssemblies` outputs exist, but are explicitly
`BOUND_UNVERIFIED`: their bytes are not accepted by the Worker until source,
compiler options and output provenance can be bound. The root context and graph
therefore correctly remain `PARTIAL`.

All 632 `Unity.Model` sources were read through the worktree `SnapshotBinding`.
Twenty-three legacy GB18030 files were decoded without losing their raw-byte
snapshot digests; the Worker receives a separate digest for transcoded UTF-8
text. Snapshot and Unity context are checked both before and after assembly.

A synthetic `PilotBehaviour` compiled only in memory against the digest-bound
Unity 2020.3 metadata. Its lifecycle and UnityEvent relations were emitted as
`CONFIRMED_STATIC`.

## Raw verification

```text
dotnet restore worker/ChangeLens.Analyzer/ChangeLens.Analyzer.csproj --locked-mode
dotnet build worker/ChangeLens.Analyzer/ChangeLens.Analyzer.csproj --configuration Release --no-restore
$env:CHANGE_LENS_UNITY_PROJECT='D:\ares\project\ET6\Unity'
python -m unittest discover -s tests -v
```

Latest result:

```text
Build succeeded: 0 warnings, 0 errors
Ran 40 tests in 98.433s
OK (skipped=1)
```

The skipped test is the Windows privilege-dependent filesystem-symlink test;
the Git symlink-blob test passed, and the same filesystem test has already
passed on Ubuntu CI in `CL-GATE-01`.

## Target-project integrity

ET6 Git status was captured before and after the pilot:

```text
entry_count=203
sha256=7c47c6fd1bce7f21375a4c965e6bcbb92ae937e765b84b30ea6af25432389228
```

The count and digest are identical. No ET6 file was written, checked out,
compiled, executed, staged, or cleaned.

## Remaining before CL-GATE-02

- bind verifiable build provenance for generated ScriptAssemblies outputs;
- evaluate platform and define constraints;
- add coroutine, async/await, delegate, C# event and component relations;
- produce and measure OLD/NEW golden graphs against manual annotation;
- run performance and adversarial matrices.
