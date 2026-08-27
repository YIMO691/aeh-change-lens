# CL-GATE-01 — Read-only snapshot resolver

- Result: `PASSED`
- Date: `2026-08-27`
- Primary work package: `CL-WP-01`
- Scope change: none
- Trust-boundary change: none
- External data flow: none in product behavior; GitHub Actions downloaded declared test/build dependencies
- Target-project execution: none
- AEH mutation: none

## Exit criteria and evidence

| Exit criterion | Evidence | Result |
|---|---|---|
| Read Git revision objects without checkout | HEAD/status before-after test; `git ls-tree` and `git cat-file` implementation | PASS |
| Do not execute project code | Resolver subprocess allowlist consists of Git read/compare commands; fixture code is never compiled or run | PASS |
| Bind worktree bytes and detect stale input | Per-file SHA-256, canonical manifest hash, mutation test | PASS |
| Record file rename without mutating index | Git rename output plus unique byte-identical worktree fallback | PASS |
| Reject path traversal and non-root invocation | Absolute, drive, `..`, NUL/root boundary tests | PASS |
| Block symlink/reparse escape | Git symlink-blob test on Windows and Linux; filesystem symlink test passed on Linux | PASS |
| Package and CLI install | Python wheel built and installed on Ubuntu 24.04 / Python 3.11.16 | PASS |

## Raw evidence

Windows local command:

```text
python -m unittest discover -s tests -v
```

Windows result:

```text
Ran 21 tests in 9.471s
OK (skipped=1)
```

The skipped case required Windows symlink privilege. The separate Git
symlink-blob rejection test passed locally.

GitHub Actions result on Ubuntu 24.04:

```text
Ran 21 tests in 0.353s
OK
```

The real filesystem symlink case passed. The package wheel was built and
installed successfully before the test run.

- Run: https://github.com/YIMO691/aeh-change-lens/actions/runs/33053468536
- Tested implementation commit: `d6f8076aff60d8a56e06f530df5f2be601420ab4`
- Pull request: https://github.com/YIMO691/aeh-change-lens/pull/2

Additional local checks:

```text
python -m compileall -q src tests
git diff --check
```

Both returned exit code 0.

## Bound implementation

- `src/aeh_change_lens/snapshot/**`
- `src/aeh_change_lens/cli.py` (`snapshot` subcommand only)
- `schemas/snapshot.schema.json`
- `docs/SNAPSHOT_CONTRACT.zh-CN.md`
- `docs/SNAPSHOT_CONTRACT.en.md`
- `tests/snapshot/**`

Exact bytes are bound by the merged Git tree. Later changes to these files must
retain or supersede this evidence.

## Honest limitations

- Git LFS pointers are bound as the bytes read; LFS content is not fetched.
- Worktree supplemental rename detection only confirms unique, byte-identical moves.
- Filenames that do not decode as UTF-8 fail closed.
- No C# or Unity semantic claim is made by this Gate.

