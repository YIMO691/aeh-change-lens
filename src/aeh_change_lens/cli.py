from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from .languages.csharp import (
    AnalyzerGraphDiffer,
    BuildProvenanceExporter,
    CompileManifestExporter,
    MappingHint,
    RevisionChangeAnalyzer,
    UnityContextBuilder,
    WorkerInputAssembler,
)
from .snapshot import SnapshotResolver
from .snapshot.errors import SnapshotError
from .reporting import ChangeStoryBuilder, write_change_story_report


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
    graph_diff = subcommands.add_parser(
        "graph-diff", help="比较 OLD/NEW Roslyn 结果并输出确定性链路差异"
    )
    graph_diff.add_argument("old_result", help="OLD analyzer-result JSON")
    graph_diff.add_argument("new_result", help="NEW analyzer-result JSON")
    graph_diff.add_argument("--renames", help="可选的 Git rename JSON 数组")
    graph_diff.add_argument("--mapping-hints", help="可选的人工复核映射提示 JSON 数组")
    graph_diff.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    analyze_change = subcommands.add_parser(
        "analyze-change", help="一键分析 Git OLD/NEW Unity 快照并输出链路差异"
    )
    analyze_change.add_argument("repository", help="Git 仓库根目录")
    analyze_change.add_argument("unity_project", help="仓库内 Unity 项目的相对路径")
    analyze_change.add_argument("--assembly", required=True, help="Assembly Definition name")
    analyze_change.add_argument("--base", required=True, help="OLD Git revision")
    analyze_change.add_argument("--target", default="WORKTREE", help="NEW Git revision 或 WORKTREE")
    analyze_change.add_argument("--request-id", required=True)
    analyze_change.add_argument("--mapping-hints", help="可选的人工复核映射提示 JSON 数组")
    analyze_change.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    explain = subcommands.add_parser(
        "explain", help="一键分析 OLD/NEW Unity 快照并生成中文 Change Story HTML 报告"
    )
    explain.add_argument("repository", help="Git 仓库根目录")
    explain.add_argument("unity_project", help="仓库内 Unity 项目的相对路径")
    explain.add_argument("--assembly", required=True, help="Assembly Definition name")
    explain.add_argument("--base", required=True, help="OLD Git revision")
    explain.add_argument("--target", default="WORKTREE", help="NEW Git revision 或 WORKTREE")
    explain.add_argument("--request-id", required=True)
    explain.add_argument("--output", required=True, help="输出的单文件 HTML 报告路径")
    explain.add_argument("--analysis-output", help="可选：同时保留完整 change-analysis JSON")
    explain.add_argument("--mapping-hints", help="可选的人工复核映射提示 JSON 数组")
    explain.add_argument(
        "--intent-evidence", help="可选的用户目标、AI 计划和提交说明 JSON"
    )
    explain.add_argument("--title", default="代码修改逻辑链路", help="报告标题")
    explain.add_argument("--pretty", action="store_true", help="格式化命令结果 JSON")
    render_report = subcommands.add_parser(
        "render-report", help="将已有 change-analysis JSON 渲染为中文 Change Story HTML"
    )
    render_report.add_argument("analysis", help="change-analysis JSON")
    render_report.add_argument("--output", required=True, help="输出的单文件 HTML 报告路径")
    render_report.add_argument("--source-root", help="可选：用于 NEW 工作树文件链接的 Unity 项目根目录")
    render_report.add_argument("--intent-evidence", help="可选的意图来源证据 JSON")
    render_report.add_argument("--title", default="代码修改逻辑链路", help="报告标题")
    render_report.add_argument("--pretty", action="store_true", help="格式化命令结果 JSON")
    export_manifest = subcommands.add_parser(
        "export-compile-manifest",
        help="从当前 Unity 生成 csproj 导出可提交、可验证的编译清单",
    )
    export_manifest.add_argument("repository", help="Git 仓库根目录")
    export_manifest.add_argument("unity_project", help="仓库内 Unity 项目的相对路径")
    export_manifest.add_argument("--assembly", required=True, help="Assembly Definition name")
    export_manifest.add_argument(
        "--dry-run", action="store_true", help="只构建并验证清单，不写入工作区"
    )
    export_manifest.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    export_build = subcommands.add_parser(
        "export-build-provenance",
        help="为 Unity 外部生成的 ScriptAssemblies 输出导出哈希闭包证明",
    )
    export_build.add_argument("repository", help="Git 仓库根目录")
    export_build.add_argument("unity_project", help="仓库内 Unity 项目的相对路径")
    export_build.add_argument("--assembly", required=True, help="Assembly Definition name")
    export_build.add_argument(
        "--dry-run", action="store_true", help="只构建并验证证明，不写入工作区"
    )
    export_build.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
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


def _read_json(path: str, expected_type: type) -> object:
    with open(path, "r", encoding="utf-8-sig") as stream:
        value = json.load(stream)
    if not isinstance(value, expected_type):
        raise ValueError(f"JSON root has unexpected type: {path}")
    return value


def _graph_diff(arguments: argparse.Namespace) -> dict:
    old_result = _read_json(arguments.old_result, dict)
    new_result = _read_json(arguments.new_result, dict)
    renames = _read_json(arguments.renames, list) if arguments.renames else []
    hints = _mapping_hints(arguments.mapping_hints)
    return AnalyzerGraphDiffer().compare(
        old_result, new_result, renames=renames, mapping_hints=hints
    ).to_dict()


def _mapping_hints(path: str | None) -> list[MappingHint]:
    raw_hints = _read_json(path, list) if path else []
    hints: list[MappingHint] = []
    for item in raw_hints:
        if not isinstance(item, dict):
            raise ValueError("mapping hint entries must be objects")
        basis = item.get("basis")
        if not isinstance(basis, list) or any(not isinstance(value, str) for value in basis):
            raise ValueError("mapping hint basis must be a string array")
        hints.append(MappingHint(
            old_label=item.get("old_label", ""),
            new_label=item.get("new_label", ""),
            kind=item.get("kind", ""),
            basis=tuple(basis),
        ))
    return hints


def _analyze_change(arguments: argparse.Namespace) -> dict:
    resolver = SnapshotResolver(arguments.repository)
    old = resolver.resolve_revision(arguments.base, "OLD")
    new = (
        resolver.resolve_worktree("NEW")
        if arguments.target == "WORKTREE"
        else resolver.resolve_revision(arguments.target, "NEW")
    )
    renames = resolver.detect_renames(arguments.base, arguments.target)
    return RevisionChangeAnalyzer(resolver, arguments.unity_project).analyze(
        old,
        new,
        arguments.assembly,
        arguments.request_id,
        renames=renames,
        mapping_hints=_mapping_hints(arguments.mapping_hints),
    )


def _write_json(path_value: str, value: object, *, pretty: bool) -> str:
    path = Path(path_value).resolve()
    if path.exists() and path.is_dir():
        raise ValueError("JSON output path must be a file")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(
                value, ensure_ascii=False, sort_keys=True,
                separators=None if pretty else (",", ":"), indent=2 if pretty else None,
            ) + "\n")
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return os.fspath(path)


def _story_result(
    analysis: dict, arguments: argparse.Namespace, *, repository: str | None
) -> dict:
    intent = _read_json(arguments.intent_evidence, dict) if arguments.intent_evidence else None
    story = ChangeStoryBuilder().build(
        analysis, title=arguments.title, intent_evidence=intent
    )
    report_path = write_change_story_report(
        arguments.output, story, repository_root=repository
    )
    return {
        "status": story["status"],
        "report_path": os.fspath(report_path),
        "story_id": story["story_id"],
        "story_digest": story["canonical_digest"],
        "analysis_digest": story["analysis_digest"],
    }


def _explain(arguments: argparse.Namespace) -> dict:
    analysis = _analyze_change(arguments)
    source_root = Path(arguments.repository) / Path(arguments.unity_project)
    result = _story_result(analysis, arguments, repository=os.fspath(source_root))
    if arguments.analysis_output:
        result["analysis_path"] = _write_json(
            arguments.analysis_output, analysis, pretty=arguments.pretty
        )
    return result


def _render_report(arguments: argparse.Namespace) -> dict:
    analysis = _read_json(arguments.analysis, dict)
    return _story_result(analysis, arguments, repository=arguments.source_root)


def _export_compile_manifest(arguments: argparse.Namespace) -> dict:
    exporter = CompileManifestExporter(
        Path(arguments.repository), arguments.unity_project
    )
    manifest = exporter.build(arguments.assembly)
    unity_path = arguments.unity_project.replace("\\", "/").rstrip("/")
    path = f"{unity_path}/.aeh-change-lens/compile-manifests/{arguments.assembly}.json"
    if not arguments.dry_run:
        path = exporter.write(manifest)
    return {
        "status": "VALIDATED" if arguments.dry_run else "EXPORTED",
        "path": path,
        "manifest": manifest.to_dict(),
    }


def _export_build_provenance(arguments: argparse.Namespace) -> dict:
    exporter = BuildProvenanceExporter(
        Path(arguments.repository), arguments.unity_project
    )
    manifest = exporter.build(arguments.assembly)
    unity_path = arguments.unity_project.replace("\\", "/").rstrip("/")
    path = f"{unity_path}/.aeh-change-lens/build-manifests/{arguments.assembly}.json"
    if not arguments.dry_run:
        path = exporter.write(manifest)
    return {
        "status": "VALIDATED" if arguments.dry_run else "EXPORTED",
        "path": path,
        "manifest": manifest.to_dict(),
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
        elif arguments.command == "graph-diff":
            result = _graph_diff(arguments)
        elif arguments.command == "analyze-change":
            result = _analyze_change(arguments)
        elif arguments.command == "explain":
            result = _explain(arguments)
        elif arguments.command == "render-report":
            result = _render_report(arguments)
        elif arguments.command == "export-compile-manifest":
            result = _export_compile_manifest(arguments)
        elif arguments.command == "export-build-provenance":
            result = _export_build_provenance(arguments)
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
