# CL-GATE-02 progress — Real Unity metadata vertical slice

- Status: `IN_PROGRESS` — this is not exit-Gate evidence
- Date: `2026-08-28`
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
- explicit failure when either lane lacks both a revision-bound generated project
  and a matching compile manifest.
- deterministic `export-compile-manifest` for repositories that ignore generated csproj;
- portable manifest bindings for base defines, exact source set/semantic hashes,
  metadata names/hashes and ProjectReference entries, without absolute paths;
- per-revision manifest canonical-digest and stale-source rejection;
- hash-qualified use of a live csproj only as a local metadata DLL locator.
- deterministic `export-build-provenance` for externally produced Unity assemblies;
- revision-bound closure over compile manifest, asmdef, ProjectVersion, package lock,
  direct project-input DLL hashes and output DLL hash;
- `PROJECT_ATTESTED` Worker references with a second Worker-side digest check;
- strict separation between external hash attestation and reproducible-build proof;
- historical output mismatch degrades to `PARTIAL`; a stale worktree output fails closed.

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
context_digest=f23712dddd85303a242ce6b4bc03e8ec6adabf2960582eb74bc566bdca74edff
assembly_graph_digest=27945ffd203825ad56d0a3ff2b8298272aa918d07efa9ebec4d6f3a536669cdd
snapshot_manifest=f202d3bfc2c575512362b9904a3127799ce4c457366a7e638850c2dc86f8b3c3
compile_manifest_defines=140
compile_manifest_sources=632
compile_manifest_metadata_references=221
compile_manifest_project_references=5
compile_manifest_project_sha256=867c661b3e8becf7fa6da7177a485d984f65d402112f900a26b1741285dd70da
compile_manifest_digest=c389dc3058fb284c5c6cf15b3e68a08cd90823e4eedb975455e29f3a9ce2d88d
script_assembly_outputs=4
analyzer_only_project_references=1
build_provenance_status=REJECTED_NO_COMPILE_MANIFEST_BASELINE
```

The graph recursively follows the five root `ProjectReference` entries. Four
corresponding `Library/ScriptAssemblies` outputs exist and one reference is
analyzer-only. The implementation can now accept a `PROJECT_ATTESTED` output
when its revision contains both compile and build-provenance manifests. ET6 has
no committed compile-manifest baseline, so `export-build-provenance --dry-run`
correctly exited with code 2 and did not retroactively attest these outputs.
The root context and graph therefore correctly remain `PARTIAL`.

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
Ran 76 tests in 145.536s
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

A read-only compile-manifest dry run successfully normalized the current
`Unity.Model.csproj` without writing ET6 or embedding its absolute path. This
establishes the prospective baseline workflow; because HEAD contains neither
the csproj nor a previously committed manifest, the tool still refuses to
retroactively invent HEAD compilation evidence.

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

- upgrade external `PROJECT_ATTESTED` statements to independently reproducible
  build receipts with pinned Unity/compiler toolchains;
- cover additional platform aliases and non-registry package-version forms;
- add alias-aware state flow, event removal and Inspector bindings;
- expand from 1 Golden Change to the planned 10–20 cases;
- run performance and adversarial matrices.
