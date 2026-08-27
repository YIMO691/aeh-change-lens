# Current Roslyn Worker Contract

> English translation; the [Chinese contract](ROSLYN_WORKER.zh-CN.md) is authoritative.

This document describes the first runnable `CL-WP-02` vertical slice. It does not claim that `CL-GATE-02` has passed.

The .NET 8 worker accepts local JSON over stdin or `--input`, binds each in-memory source to SHA-256, rejects unsafe paths, and uses Roslyn 5.9.0 syntax/compilation/semantic APIs. It emits deterministic graph nodes and provenance-bearing relations for declarations, direct calls, branches, throws, returns, state writes, lifecycle scheduling, UnityEvent invocation, serialized references, and unknown `SendMessage` dispatch.

The worker currently loads .NET platform metadata plus caller-provided source. Test Unity types are controlled stubs, not authoritative Unity assemblies. It therefore forces `PARTIAL` capability even when a caller claims `COMPLETE`; Unity-specific relations are at most `STRUCTURAL`, while uniquely resolved ordinary C# calls may be `CONFIRMED_STATIC`.

`CL-GATE-02` still requires `.asmdef` assembly construction, digest-bound real Unity reference assemblies, platform/define constraints, broader coroutine/async/event/component relations, old/new golden graphs, a capability matrix, performance evidence, and more adversarial cases.

The dependency graph is locked in `worker/ChangeLens.Analyzer/packages.lock.json`; the official package source is the [NuGet Gallery](https://www.nuget.org/packages/Microsoft.CodeAnalysis.CSharp/5.9.0).

