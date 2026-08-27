# Snapshot Resolver Contract

> English translation; the [Chinese contract](SNAPSHOT_CONTRACT.zh-CN.md) is authoritative.

`CL-WP-01` binds old and new source bytes into reviewable inputs without executing target-project code.

## Input modes

- A Git revision is resolved to an immutable commit OID and read with `git ls-tree` and `git cat-file`.
- `WORKTREE` reads tracked and non-ignored untracked files without modifying the index.
- The selector includes `*.cs`, `*.asmdef`, `*.csproj`, `ProjectSettings/ProjectVersion.txt`, `Packages/manifest.json`, and `Packages/packages-lock.json`.

## Digest semantics

- `git_blob_oid` is the Git object ID and is `null` for worktree files.
- `sha256` binds the exact file bytes.
- `source_manifest_hash` binds canonical JSON containing sorted relative paths, sizes, Git OIDs, and SHA-256 values.
- For a revision, `tree_hash` is SHA-256 over the raw root-tree object; child tree OIDs recursively bind the tree.
- For a worktree, `tree_hash` is the supported-source manifest digest and does not claim to be a Git tree OID.
- `tree_oid` is the actual Git tree OID and is `null` for a worktree.

## Security boundary

The resolver requires the exact repository root; rejects absolute paths, traversal, NUL, symlinks, Git symlink blobs, and Windows reparse points; uses read or comparison Git commands with optional locks disabled; never checks out, invokes Unity, compiles, or runs repository code; and emits no absolute repository path or source body.

## Stale rule

A binding remains current only when both `tree_hash` and `source_manifest_hash` match a fresh resolution. Any selected source byte, addition, deletion, or path change makes it stale. Files outside the selector are not bound inputs.

## Current limitations

- Git LFS content is not expanded; the resolver binds the bytes it actually reads.
- Supplemental worktree rename detection confirms only unique byte-identical moves. Git rename detection or later semantic mapping handles modified moves.
- Filenames must decode as UTF-8; failures are closed.
- Ignored, untracked Unity-generated csproj files are not part of a worktree binding; historical analysis does not bypass that boundary.
- This work package does not parse C# semantics.
