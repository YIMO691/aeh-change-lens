from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from .languages.csharp import UnityContextBuilder, WorkerInputAssembler
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
    unity_context = subcommands.add_parser("unity-context", help="读取 asmdef 与 Unity 生成 csproj 上下文")
    unity_context.add_argument("unity_project", help="Unity 项目根目录")
    unity_context.add_argument("--assembly", required=True, help="Assembly Definition name")
    unity_context.add_argument("--graph", action="store_true", help="递归输出程序集依赖图")
    unity_context.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    roslyn_input = subcommands.add_parser(
        "roslyn-input", help="从已验哈希源码快照装配 Roslyn Worker 输入"
    )
    roslyn_input.add_argument("repository", help="Git 仓库根目录")
    roslyn_input.add_argument("unity_project", help="仓库内的 Unity 项目根目录")
    roslyn_input.add_argument("--assembly", required=True, help="Assembly Definition name")
    roslyn_input.add_argument("--snapshot", default="WORKTREE", help="WORKTREE 或 Git revision")
    roslyn_input.add_argument("--role", choices=("OLD", "NEW"), default="NEW")
    roslyn_input.add_argument("--request-id", required=True)
    roslyn_input.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
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
        elif arguments.command == "unity-context":
            builder = UnityContextBuilder(arguments.unity_project)
            result = (
                builder.build_graph(arguments.assembly).to_dict()
                if arguments.graph
                else builder.build(arguments.assembly).to_dict()
            )
        elif arguments.command == "roslyn-input":
            resolver = SnapshotResolver(arguments.repository)
            binding = (
                resolver.resolve_worktree(arguments.role)
                if arguments.snapshot == "WORKTREE"
                else resolver.resolve_revision(arguments.snapshot, arguments.role)
            )
            context = UnityContextBuilder(arguments.unity_project).build(arguments.assembly)
            result = WorkerInputAssembler(resolver, arguments.unity_project).assemble(
                binding, context, arguments.request_id
            ).to_dict()
        else:  # pragma: no cover - argparse prevents this branch
            parser.error(f"unsupported command: {arguments.command}")
    except (SnapshotError, FileNotFoundError, ValueError) as error:
        print(json.dumps({"status": "FAILED", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    indent = 2 if arguments.pretty else None
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=None if indent else (",", ":"), indent=indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
