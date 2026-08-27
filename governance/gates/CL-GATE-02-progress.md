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
completeness=PARTIAL
context_digest=7e9311efb85b9b35a8292d712525124612fa365615792fb1e4ab6f0596852001
```

The five generated `ProjectReference` entries are not yet recursively loaded,
so the real assembly context correctly remains `PARTIAL`.

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

Result:

```text
Build succeeded: 0 warnings, 0 errors
Ran 30 tests in 13.952s
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

- recursively resolve assembly and ProjectReference boundaries;
- bind snapshot source bytes into per-assembly Worker inputs;
- evaluate platform and define constraints;
- add coroutine, async/await, delegate, C# event and component relations;
- produce and measure OLD/NEW golden graphs against manual annotation;
- run performance and adversarial matrices.
