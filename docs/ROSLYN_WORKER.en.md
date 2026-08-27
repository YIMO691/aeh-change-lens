# Current Roslyn Worker Contract

> English translation; the [Chinese contract](ROSLYN_WORKER.zh-CN.md) is authoritative.

This document describes the first runnable `CL-WP-02` vertical slice. It does not claim that `CL-GATE-02` has passed.

The .NET 8 worker accepts local JSON over stdin or `--input`, binds original source bytes to a snapshot SHA-256 and transcoded text to a separate transport SHA-256, rejects unsafe paths, and uses Roslyn 5.9.0 syntax/compilation/semantic APIs. It emits deterministic graph nodes and provenance-bearing relations for declarations, direct calls, branches, throws, returns, state writes, lifecycle scheduling, UnityEvent invocation, serialized references, and unknown `SendMessage` dispatch.

The Unity Context Builder now reads `.asmdef`, ProjectVersion, generated csproj defines, Compile globs, ProjectReference entries, and metadata HintPaths. It recursively builds an assembly dependency graph. The input assembler reads source bytes only through `SnapshotBinding`, checks both the snapshot and Unity context before and after assembly, and strictly supports UTF-8, BOM-qualified UTF encodings, and GB18030. Generated `Library/ScriptAssemblies` outputs remain `PROJECT_UNVERIFIED` and are excluded from worker references until their build provenance can be bound. Metadata DLLs are SHA-256 validated by both the builder contract and worker.

The builder now evaluates asmdef include/exclude platforms and Define Constraints; an excluded assembly cannot be assembled into worker input. The worker emits bounded relations for coroutine start/yield, async await, C# event/delegate subscription and publication, and common component lookup APIs. String coroutine targets remain `UNKNOWN`, and yield remains `STRUCTURAL`.

An ET6 Unity 2020.3.26f1c1 read-only pilot assembled all 632 `Unity.Model` sources from a 9,325-file selected snapshot, including 23 GB18030 legacy sources, and resolved a graph of 6 applicable assemblies and 12 dependencies. Static analysis of the full source set emitted 12,377 nodes and 8,869 edges, including 12 `AWAITS` and 1,268 `DIRECT_CALL` edges. The result correctly remained `PARTIAL` because generated project-assembly outputs lack bound provenance and symbols remain unresolved. `CL-GATE-02` still requires verifiable ScriptAssemblies provenance, Version Defines, state reads and broader event/component coverage, old/new golden graphs, performance evidence, and more adversarial cases.

See the [C#/Unity capability matrix](CAPABILITY_MATRIX.en.md) for exact coverage and limits.

The dependency graph is locked in `worker/ChangeLens.Analyzer/packages.lock.json`; the official package source is the [NuGet Gallery](https://www.nuget.org/packages/Microsoft.CodeAnalysis.CSharp/5.9.0).
