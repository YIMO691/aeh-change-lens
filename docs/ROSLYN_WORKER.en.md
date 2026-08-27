# Current Roslyn Worker Contract

> English translation; the [Chinese contract](ROSLYN_WORKER.zh-CN.md) is authoritative.

This document describes the first runnable `CL-WP-02` vertical slice. It does not claim that `CL-GATE-02` has passed.

The .NET 8 worker accepts local JSON over stdin or `--input`, binds each in-memory source to SHA-256, rejects unsafe paths, and uses Roslyn 5.9.0 syntax/compilation/semantic APIs. It emits deterministic graph nodes and provenance-bearing relations for declarations, direct calls, branches, throws, returns, state writes, lifecycle scheduling, UnityEvent invocation, serialized references, and unknown `SendMessage` dispatch.

The Unity Context Builder now reads `.asmdef`, ProjectVersion, generated csproj defines, Compile globs, ProjectReference entries, and metadata HintPaths. Metadata DLLs are SHA-256 validated by both the builder contract and worker. A caller cannot obtain complete Unity capability without a bound `UnityEngine.CoreModule.dll` and resolved `MonoBehaviour`/`UnityEventBase`; stub-only analysis remains `PARTIAL` and Unity-specific relations remain at most `STRUCTURAL`.

An ET6 Unity 2020.3.26f1c1 read-only pilot confirmed lifecycle and UnityEvent relations against real Unity metadata. `CL-GATE-02` still requires recursive ProjectReference/assembly construction, platform and define-constraint evaluation, snapshot-to-worker source orchestration, broader coroutine/async/event/component relations, old/new golden graphs, a capability matrix, performance evidence, and more adversarial cases.

The dependency graph is locked in `worker/ChangeLens.Analyzer/packages.lock.json`; the official package source is the [NuGet Gallery](https://www.nuget.org/packages/Microsoft.CodeAnalysis.CSharp/5.9.0).
