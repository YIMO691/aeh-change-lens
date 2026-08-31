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
- Chinese-first, self-contained Change Story HTML projection from the deterministic diff;
- explicit separation of `CODE_FACT`, `SOURCE_EVIDENCE` and `INTENT_INFERENCE`;
- bounded OLD/NEW path rendering with source locations, impact list and limitations;
- script-free/offline rendering with HTML escaping and independent story digest;
- `explain` end-to-end CLI plus `render-report` for an existing analysis artifact.

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
Local: Ran 85 tests in 54.984s; OK (skipped=4)
ET6: Ran 85 tests in 158.180s
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

The Change Story increment additionally hashed the content of all supported
source/configuration files outside generated `Library`, `Temp`, `Logs` and
`obj` directories before and after the real-project suite:

```text
protected_entries=7575
before_sha256=0bbc339f93ae90ad8deecbb440567e333fc5060fdaab4206b02045ff5c8e732c
after_sha256=0bbc339f93ae90ad8deecbb440567e333fc5060fdaab4206b02045ff5c8e732c
fingerprint_equal=True
```

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
- validate Change Story comprehension and navigation on larger real gameplay changes;
- run performance and adversarial matrices.

## 2026-08-28 usability increment: explicit syntax-only fallback

This is progress evidence only. It does not close `CL-GATE-02` or upgrade the
semantic analyzer's acceptance status.

- strict `analyze-change` and `explain` now perform a fast baseline preflight
  and still fail closed when either revision lacks immutable compile evidence;
- `--allow-syntax-partial` is an explicit, read-only fallback limited to changed
  C# files, with progress emitted on stderr and machine-readable JSON preserved
  on stdout;
- fallback output is always `PARTIAL`: graph nodes, edges and mappings are
  capped at `STRUCTURAL`, and the report states that defines, metadata and Unity
  compilation context are missing;
- the Codex Skill, bilingual user documentation and schema contract were updated
  to expose the same strict-versus-fallback boundary;
- the full local suite passed 93 tests with 4 platform-dependent skips, and the
  .NET Worker built with 0 warnings and 0 errors.

A private, read-only Ares2 ET6 pilot completed in approximately 12.6 seconds.
It bound 20 changed C# paths and produced an offline Change Story outside the
target repository. The target Git-status fingerprint was identical before and
after (`487230d058e693939b492d556f0f91cfb317e44e54f230a689d92958da07aa1e`),
and no analyzer output was written into the target. The resulting analysis was
schema-valid and contained zero `CONFIRMED_STATIC` nodes, edges or mappings.

This fallback improves immediate comprehension when historical manifests do
not exist; it does not retroactively create revision-bound semantic evidence.
Future strict analysis still requires compile manifests captured for both
revisions before the change is evaluated.

## 2026-08-31 usability increment: two-level Change Story

This is additional progress evidence only. It does not close `CL-GATE-02` or
promote business-focus heuristics to compile-confirmed semantics.

- Change Story contract `1.1.0` adds a bounded quick-understanding model and a
  detailed, evidence-backed implementation breakdown;
- the default landing view contains one summary, an explicitly labeled mental
  model, at most five business-area cards, at most eight OLD/NEW focus steps,
  impact scope and bounded priority risks;
- detailed mode groups representative objects and relationships by
  configuration, server, protocol, client, runtime and tests, then exposes new
  decision/exit points before the complete technical evidence;
- generated code, tests, unchanged context and syntax fragments remain in the
  full evidence but cannot displace the primary business flow;
- `--story-output` writes the focused contract for Codex, and the explicit Skill
  now reads it before the full analysis JSON.

The complete local suite passed 95 tests with 4 platform-dependent skips. The
.NET Worker built with 0 warnings and 0 errors, the updated Skill passed its
validator, and the final HTML remained script-free with no remote resources.

A read-only Ares2 ET6 pilot bound 20 changed C# paths and produced a `PARTIAL`
two-level story outside the target repository. The quick layer reduced the
current gameplay change to five area cards, four OLD focus steps and eight NEW
focus steps. Target Git-status hashes were identical before and after
(`74267bae547e935dccd81a0ccbe2b75befc1cf850eeb6453f584ea2a564e9f23`).
The report remains structurally honest: missing compile context is prominent,
and the focused path is not described as a complete runtime call stack.

A follow-up pilot against six newly added Unity Editor C# paths verified that
Editor lifecycle callbacks no longer displace the Window, Excel Repository and
Validator responsibilities in the quick summary. Its target-status hash also
remained identical before and after analysis
(`c462d9256d2c29da83ef0780673cafa912944d00aac30e3dc04c5af8886b54a3`).

## 2026-08-29 usability increment: Change Map Lite

This is user-comprehension evidence only. It does not close `CL-GATE-02`, turn
structural reachability into runtime impact, or promote presentation heuristics
to analyzer truth.

- Change Story contract `1.2.0` adds a bounded `visual_map` with explicit
  `MODIFIED`, `ADDED`, `REMOVED`, `TEST_ONLY`, `CONFIG_PROTOCOL` and `PARALLEL`
  shapes;
- the quick view presents at most three Before, Core change and After items,
  followed by impact and the first material risk;
- the three columns are always revision comparison, never an implied call
  sequence; changed edge evidence is disclosed separately and parallel facts
  remain explicitly unordered;
- added, removed and test-only changes no longer produce empty OLD/NEW flow
  boxes, while the detailed evidence view remains available unchanged;
- the Codex Skill now reads `visual_map` first and is forbidden from narrating
  `PARALLEL_FACTS` as a call chain.

The complete local suite passed 99 tests with 4 platform-dependent skips. The
.NET Worker built with 0 warnings and 0 errors, both repository and installed
Skill copies passed validation, and the final HTML remained script-free with no
remote resources.

Two read-only Ares2 pilots exercised different presentation shapes. A 13-file
Unity Editor/test snapshot produced a `MODIFIED` map centered on Auto Fixer,
Change Tracker and Export Runner roles. The worktree then changed independently;
the final current snapshot contained one changed C# test file and produced a
`TEST_ONLY` map centered on repository-file, exported-configuration and protocol
field validation. The final target fingerprint was identical before and after
analysis (`0a0012afe32bd096bc8fd1cc3b89d52ec814621e43da858a5bf9afeadd14efa7`).

## 2026-08-30 usability increment: Scenario Lens

This is reader-comprehension progress evidence only. It does not close
`CL-GATE-02`, infer runtime order from display order, or promote business labels
to compiler-confirmed facts.

- Change Story contract `1.3.0` adds a question-first `scenario_lens` with at
  most five scenarios, seven OLD/NEW focus objects and six exact relationships
  per scenario;
- the default view answers one primary reader question using business labels;
  technical names, the full Change Map Lite comparison and area cards are now
  on-demand evidence;
- scenario ranking favors genuinely added or removed methods and types over the
  volume of ordinary `UPDATED` nodes in a large file, preventing line-shift
  noise from selecting the primary story;
- duplicate business actions are collapsed to the highest-connected
  representative object, while the complete symbol and relationship evidence
  remains available;
- detailed stages and decision points are closed by default, and the Codex
  Skill explains only the primary or explicitly selected scenario.

The complete local suite passed 100 tests with 4 platform-dependent skips, and
both repository and installed Skill copies passed validation. A read-only pilot
against Ares2 commit `4b56a7633` generated a `PARTIAL` report outside the target
repository. It selected “Guidance and readiness” as the primary scenario and
offered bounded load/save/export, preview, authoring and validation views. The
rendered first screen was inspected at 1440×1800; the OLD/NEW map and detailed
stages remained collapsed, and repeated readiness methods no longer appeared as
separate business actions.

## 2026-08-30 usability increment: adaptive visual composition

This is presentation and reader-comprehension evidence only. It does not close
`CL-GATE-02`, convert structural evidence into runtime causality, or copy a
third-party renderer into the product.

- Change Story contract `1.4.0` adds one to three bounded memory points and a
  scenario-local `change_shape`;
- `ADDED` and `REMOVED` scenarios use an asymmetric full-width capability
  canvas instead of reserving an empty OLD or NEW half, while `MODIFIED`
  scenarios retain a direct two-column comparison;
- only `VERIFIED_FLOW` relationships render as individually inspectable path
  cards; `PARALLEL_FACTS` remains directionless and carries no invented arrows;
- the Chinese-first visual system now uses functional status colors, a calmer
  reading order and progressive disclosure while remaining one script-free,
  dependency-free offline HTML file;
- the explicit Codex Skill now leads with `scenario_lens.takeaways_zh`, respects
  scenario shape, and still keeps full technical evidence on demand.

The complete local suite passed 100 tests with 4 platform-dependent skips. The
.NET Worker built with 0 warnings and 0 errors, `git diff --check` passed, and
both repository and installed Skill copies passed validation. The immutable
Ares2 monster-editor pilot remained `PARTIAL`, selected an `ADDED` guidance and
readiness scene, exposed three memory points and two exact relationship paths,
and was visually inspected at 1440×1800. No target-project file was modified by
the render-only regression.

## 2026-08-31 usability increment: Human Daily Brief

This is reader-workflow and presentation evidence only. It does not close
`CL-GATE-02`, turn verification suggestions into analyzer facts, or claim
runtime behavior that was not observed.

- Change Story contract `1.5.0` adds an evidence-linked `daily_brief` with one
  plain-language change sentence, work impact and two or three bounded checks;
- the report now exposes three human reading depths: Daily conclusion,
  Scenario understanding and Technical evidence;
- verification checks are visually and contractually labeled as suggestions,
  carry evidence references and remain distinct from code facts;
- the default desktop first screen contains the change sentence and all three
  memory points at 1440×900, while the narrow layout stacks the same content
  without shrinking labels;
- the explicit Codex Skill now answers from `daily_brief` first and opens
  Scenario Lens only when the user asks how the change works.

The immutable Ares2 monster-editor pilot remained `PARTIAL`. Its Daily Brief
described the added guidance/readiness scene, retained three bounded memory
points, suggested one real editor interaction, one verified-path review and one
Unity compile/runtime check, and preserved the deeper scenario and evidence
views without changing the target repository.

The complete local suite passed 100 tests with 4 platform-dependent skips. The
.NET Worker built with 0 warnings and 0 errors, `git diff --check` passed, and
the installed explicit Skill passed validation.
