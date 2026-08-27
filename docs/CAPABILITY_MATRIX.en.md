# C#/Unity Analyzer Capability Matrix

> English translation; the [Chinese matrix](CAPABILITY_MATRIX.zh-CN.md) is authoritative. This is `CL-WP-02` progress, not a `CL-GATE-02` pass claim.

| Capability | Status | Maximum static confidence | Explicit limit |
|---|---|---|---|
| Type and method declarations | Implemented | `CONFIRMED_STATIC` | Input assembly sources only |
| Direct calls | Implemented | `CONFIRMED_STATIC` | Roslyn must uniquely resolve the target |
| Branch, return, throw | Implemented | `STRUCTURAL` | Not yet a complete control-flow graph |
| State writes | Partial | `CONFIRMED_STATIC` | Field/property assignments and `++`/`--`; reflective writes are not inferred |
| State reads | Partial | `CONFIRMED_STATIC` | Resolved fields/properties; no alias, reflection, or runtime-object inference |
| Unity lifecycle | Implemented | `CONFIRMED_STATIC` | Downgraded to `STRUCTURAL` with partial context |
| Coroutine start | Implemented | `CONFIRMED_STATIC` | String targets remain `UNKNOWN` |
| `yield` | Implemented | `STRUCTURAL` | Does not claim the actual runtime resume path |
| `await` | Implemented | `CONFIRMED_STATIC` | Downgraded when target/awaitable cannot resolve |
| C# event/delegate subscription | Partial | `CONFIRMED_STATIC` | Direct method groups are confirmed; lambdas are `STRUCTURAL`, handler factories `UNKNOWN`; no `-=` yet |
| C# event/delegate publication | Partial | `CONFIRMED_STATIC` | Direct symbols are confirmed; indirect delegate `Invoke` is `STRUCTURAL` |
| UnityEvent invocation | Implemented | `CONFIRMED_STATIC` | Concrete Inspector listeners remain unknown |
| Serialized reference | Partial | `CONFIRMED_STATIC` | Field-to-type only; concrete object unknown |
| Component lookup | Implemented | `CONFIRMED_STATIC` | Common generic/`typeof` APIs; runtime instance unknown |
| Dynamic dispatch such as `SendMessage` | Explicit downgrade | `UNKNOWN` | No guessing from method-name strings |
| asmdef platform applicability | Implemented | Deterministic context fact | Current compile platform inferred from generated csproj defines |
| asmdef Define Constraints | Implemented | Deterministic context fact | Line-level AND, `||`, and `!`; invalid expressions are `UNKNOWN` |
| Version Defines | Partial | Deterministic context fact | Binds Unity and `packages-lock.json` versions; unparseable Git/path package versions are `UNKNOWN` |
| ScriptAssemblies provenance | Partial | `PROJECT_UNVERIFIED` | Output exists but source/options/output closure is unproven |
| Inspector UnityEvent binding | Not implemented | `UNKNOWN` | Requires serialized assets or runtime evidence |

Define-constraint evaluation follows the [Unity 2020.3 Assembly Definition properties](https://docs.unity3d.com/2020.3/Documentation/Manual/class-AssemblyDefinitionImporter.html): all constraint lines must pass, `||` is allowed within a line, and `!` negates a symbol.

Version Defines support Unity's documented mathematical ranges, inclusive `[]` and exclusive `()` endpoints, exact `[x]` versions, and bare minimum versions. Whitespace and wildcards are invalid; package versions come from the snapshot-bound `Packages/packages-lock.json`, and unparseable sources are never guessed.
