from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from .snapshot import SnapshotResolver
from .snapshot.errors import SnapshotError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="change-lens",
        description="AEH Change Lens（当前仅开放只读快照诊断命令）",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    snapshot = subcommands.add_parser("snapshot", help="绑定原版本与新版本源码清单")
    snapshot.add_argument("repository", help="Git 仓库根目录（必须精确指向根目录）")
    snapshot.add_argument("--base", required=True, help="原版本 Git revision")
    snapshot.add_argument("--target", default="WORKTREE", help="新版本 Git revision 或 WORKTREE")
    snapshot.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    return parser


def _snapshot(arguments: argparse.Namespace) -> dict:
    resolver = SnapshotResolver(arguments.repository)
    old = resolver.resolve_revision(arguments.base, "OLD")
    if arguments.target == "WORKTREE":
        new = resolver.resolve_worktree("NEW")
    else:
        new = resolver.resolve_revision(arguments.target, "NEW")
    renames = resolver.detect_renames(arguments.base, arguments.target)
    return {
        "schema_version": "1.0.0",
        "old": old.to_dict(),
        "new": new.to_dict(),
        "renames": [asdict(item) for item in renames],
    }


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "snapshot":
            result = _snapshot(arguments)
        else:  # pragma: no cover - argparse prevents this branch
            parser.error(f"unsupported command: {arguments.command}")
    except SnapshotError as error:
        print(json.dumps({"status": "FAILED", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    indent = 2 if arguments.pretty else None
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=None if indent else (",", ":"), indent=indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

