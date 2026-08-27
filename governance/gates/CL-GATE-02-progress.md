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
- asmdef include/exclude platform and Define Constraints evaluation;
- asmdef Version Defines evaluation from snapshot-bound Unity and package-lock versions,
  with invalid/unparseable expressions explicitly downgraded;
- fail-closed rejection before Worker input when the assembly is excluded;
- coroutine start/yield, async await, C# event/delegate subscription and publication;
- field/property state reads plus assignment and increment/decrement state writes;
- conservative complex-delegate confidence: direct method group `CONFIRMED_STATIC`,
  lambda `STRUCTURAL`, handler factory `UNKNOWN`;
- common generic and `typeof` Unity component lookups;
- confidence upgrade only when a bound `UnityEngine.CoreModule.dll` resolves
  `MonoBehaviour` and `UnityEventBase`;
- caller-provided source stubs cannot overstate Unity context.
- deterministic OLD/NEW graph differ with schema and canonical digest;
- stable symbol mapping, unique structural mapping and explicit reviewed mapping hints;
- fail-closed mixed-revision/dangling-edge checks and no-guess ambiguous groups;
- first real-Worker Golden Change compared against human annotation.
- strict `analyze-change` OLD revision -> NEW revision/worktree pipeline;
- per-lane temporary materialization of snapshot-bound csproj, asmdef, package/version
  metadata and C# sources, with no checkout;
- direct generated-csproj path/SHA-256 binding in Unity Context;
- explicit failure when either lane lacks its revision-bound generated project.

## ET6 read-only measurements

```text
defines=140
metadata_references=221
unity_references=69
project_references=5
locked_packages=48
version_defines=0
source_files=632
assembly_graph_nodes=6
assembly_graph_edges=12
selected_snapshot_files=9352
selected_csproj_files=24
assembled_source_files=632
source_encodings=UTF-8:336,UTF-8-BOM:273,GB18030:23
completeness=PARTIAL
assembly_applicability=APPLICABLE
active_platform=Editor
applicable_graph_assemblies=6/6
generated_project_sha256=b3eb20ae7abf4c445e1dc6667b3751b31bff0d2131216dca5602da5f747d0e40
context_digest=63bce75e9d0b244ad8e7d58834547e0b1f75ac43ca1b9a03e385937233018acb
assembly_graph_digest=d5c5cc34e12e80c90b07b4d1ba51e5fca833aca61abd656ed3b1865dfedaecc6
snapshot_manifest=f202d3bfc2c575512362b9904a3127799ce4c457366a7e638850c2dc86f8b3c3
```

The graph recursively follows the five root `ProjectReference` entries. Four
corresponding `Library/ScriptAssemblies` outputs exist, but are explicitly
`BOUND_UNVERIFIED`: their bytes are not accepted by the Worker until source,
compiler options and output provenance can be bound. The root context and graph
therefore correctly remain `PARTIAL`.

All 632 `Unity.Model` sources and the package lock were read through the
worktree `SnapshotBinding`.
Twenty-three legacy GB18030 files were decoded without losing their raw-byte
snapshot digests; the Worker receives a separate digest for transcoded UTF-8
text. Snapshot and Unity context are checked both before and after assembly.
The six graph assemblies contain no Version Define entries, so the pilot does
not invent any; registry/prerelease, Unity-version, boundary, invalid-expression,
missing-version and unparseable-Git cases are covered by deterministic fixtures.

A synthetic `PilotBehaviour` compiled only in memory against the digest-bound
Unity 2020.3 metadata. Its lifecycle, UnityEvent, coroutine-start and component-
lookup relations were emitted as `CONFIRMED_STATIC`; yield remains `STRUCTURAL`.

The complete 632-source payload was also analyzed in memory without emitting or
executing project code:

```text
status=PARTIAL
nodes=22382
edges=18874
diagnostics=51
AWAITS=12
BRANCHES_TO=3056
DIRECT_CALL=1268
READS_STATE=9994
RETURNS_FROM=2371
THROWS_FROM=1922
WRITES_STATE=251
```

The 50 compiler diagnostics are retained as warnings rather than hidden. They
are expected while four generated project-assembly dependencies remain
`PROJECT_UNVERIFIED`; the additional diagnostic discloses partial Unity context.

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
Ran 61 tests in 116.199s
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

The worktree snapshot now binds 24 generated csproj files. ET6's
`Unity/Unity.Model.csproj` is not present in HEAD, so strict
`analyze-change HEAD -> WORKTREE` was intentionally rejected before Worker
execution. No NEW configuration was substituted for OLD.

## OLD/NEW Golden measurement

The existing `UNITY-MINIMAL-001` human-reviewed fixture now runs through the
real Roslyn Worker for both lanes in memory. The deterministic projection is:

```text
old_status=PARTIAL
new_status=PARTIAL
old_nodes=19
new_nodes=25
mapped_nodes=11
added_nodes=14
removed_nodes=8
updated_node_pairs=4
moved_node_pairs=1
added_edges=14
removed_edges=8
unchanged_edge_pairs=8
ambiguous_groups=2
canonical_digest=e3d40c21b0026a0e47f0ffc8d921d4350e3c4afcd3d9f98a44f71db575454155
```

The reviewed mappings cover `Claim -> TryClaim`, `CalculateBonus` moving to
`RewardPolicy`, and `Start -> Awake`. They remain `STRUCTURAL`, not falsely
promoted to Roslyn-confirmed identity. Two duplicate state-access signatures
remain unmapped and explicitly limited.

## Remaining before CL-GATE-02

- bind verifiable build provenance for generated ScriptAssemblies outputs;
- cover additional platform aliases and non-registry package-version forms;
- add alias-aware state flow, event removal and Inspector bindings;
- expand from 1 Golden Change to the planned 10–20 cases;
- define a governed compile-manifest export for ordinary Unity repositories whose
  generated csproj files are ignored and absent from history;
- run performance and adversarial matrices.
