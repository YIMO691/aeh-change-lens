# Unity minimal annotated change

This fixture freezes the first manually annotated contract case. It is source
text only: contract tests must not compile or execute it during `CL-WP-00`.

- `base/` is the old lane.
- `target/` is the new lane.
- `expected-change.yaml` records human judgment, including uncertainty.
- `stale-case.yaml` records the mutation oracle without changing either lane.

The fixture deliberately contains a Unity lifecycle transition, a renamed
method, a method moved to another type, a new branch and return, an exception,
state mutation, UnityEvent invocation, a removed method, and dynamic
`SendMessage` dispatch whose target must remain unknown.

