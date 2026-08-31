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
    RevisionBaselinePreflight,
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
        description="AEH Change Lens（只读 OLD → NEW 代码变更分析）",
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
    analyze_change.add_argument(
        "--allow-syntax-partial", action="store_true",
        help="缺少 revision 编译基线时，仅分析已变更 C# 文件并显式输出 PARTIAL",
    )
    analyze_change.add_argument(
        "--progress", action="store_true", help="在 stderr 输出阶段进度"
    )
    analyze_change.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    explain = subcommands.add_parser(
        "explain", help="一键分析 OLD/NEW Unity 快照并生成快速理解/详细拆解 Change Story"
    )
    explain.add_argument("repository", help="Git 仓库根目录")
    explain.add_argument("unity_project", help="仓库内 Unity 项目的相对路径")
    explain.add_argument("--assembly", required=True, help="Assembly Definition name")
    explain.add_argument("--base", required=True, help="OLD Git revision")
    explain.add_argument("--target", default="WORKTREE", help="NEW Git revision 或 WORKTREE")
    explain.add_argument("--request-id", required=True)
    explain.add_argument("--output", required=True, help="输出的单文件 HTML 报告路径")
    explain.add_argument("--analysis-output", help="可选：同时保留完整 change-analysis JSON")
    explain.add_argument("--story-output", help="可选：同时保留聚焦后的 change-story JSON")
    explain.add_argument("--mapping-hints", help="可选的人工复核映射提示 JSON 数组")
    explain.add_argument(
        "--allow-syntax-partial", action="store_true",
        help="缺少 revision 编译基线时，仅分析已变更 C# 文件并显式输出 PARTIAL",
    )
    explain.add_argument(
        "--progress", action="store_true", help="在 stderr 输出阶段进度"
    )
    explain.add_argument(
        "--intent-evidence", help="可选的用户目标、AI 计划和提交说明 JSON"
    )
    explain.add_argument("--title", default="代码修改逻辑链路", help="报告标题")
    explain.add_argument("--pretty", action="store_true", help="格式化命令结果 JSON")
    render_report = subcommands.add_parser(
        "render-report", help="将已有 change-analysis JSON 渲染为双层 Change Story"
    )
    render_report.add_argument("analysis", help="change-analysis JSON")
    render_report.add_argument("--output", required=True, help="输出的单文件 HTML 报告路径")
    render_report.add_argument("--story-output", help="可选：同时保留聚焦后的 change-story JSON")
    render_report.add_argument("--source-root", help="可选：用于 NEW 工作树文件链接的 Git 仓库根目录")
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
    progress = (
        (lambda message: print(f"[change-lens] {message}", file=sys.stderr, flush=True))
        if getattr(arguments, "progress", False) else None
    )
    if progress:
        progress("预检 OLD/NEW revision 编译基线")
    availability = RevisionBaselinePreflight(
        resolver, arguments.unity_project
    ).inspect(arguments.base, arguments.target, arguments.assembly)
    analyzer = RevisionChangeAnalyzer(resolver, arguments.unity_project)
    if not availability.strict_ready:
        missing = ", ".join(availability.missing_lanes)
        if not getattr(arguments, "allow_syntax_partial", False):
            project_path = availability.old_candidates[0]
            raise ValueError(
                "revision-bound generated Unity project or compile manifest is unavailable: "
                f"{missing} {project_path}; rerun with --allow-syntax-partial for an "
                "explicit changed-C# structural report"
            )
        if progress:
            progress(f"{missing} 缺少编译基线，切换为显式 syntax-only PARTIAL")
        changed_paths = resolver.changed_csharp_paths(arguments.base, arguments.target)
        if not changed_paths:
            raise ValueError("syntax-only fallback found no changed C# source files")
        if progress:
            progress(f"绑定 {len(changed_paths)} 个已变更 C# 路径")
        old = resolver.resolve_revision_paths(arguments.base, "OLD", changed_paths)
        new = (
            resolver.resolve_worktree_paths("NEW", changed_paths)
            if arguments.target == "WORKTREE"
            else resolver.resolve_revision_paths(arguments.target, "NEW", changed_paths)
        )
        renames = resolver.detect_renames(
            arguments.base,
            arguments.target,
            supplement_untracked_exact=False,
        )
        return analyzer.analyze_syntax_partial(
            old,
            new,
            arguments.request_id,
            renames=renames,
            mapping_hints=_mapping_hints(arguments.mapping_hints),
            missing_baseline_lanes=availability.missing_lanes,
            progress=progress,
        )
    if progress:
        progress("编译基线可用，绑定完整源码快照")
    old = resolver.resolve_revision(arguments.base, "OLD")
    new = (
        resolver.resolve_worktree("NEW")
        if arguments.target == "WORKTREE"
        else resolver.resolve_revision(arguments.target, "NEW")
    )
    renames = resolver.detect_renames(arguments.base, arguments.target)
    return analyzer.analyze(
        old,
        new,
        arguments.assembly,
        arguments.request_id,
        renames=renames,
        mapping_hints=_mapping_hints(arguments.mapping_hints),
        progress=progress,
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
    result = {
        "status": story["status"],
        "report_path": os.fspath(report_path),
        "story_id": story["story_id"],
        "story_digest": story["canonical_digest"],
        "analysis_digest": story["analysis_digest"],
    }
    if getattr(arguments, "story_output", None):
        result["story_path"] = _write_json(
            arguments.story_output, story, pretty=arguments.pretty
        )
    return result


def _explain(arguments: argparse.Namespace) -> dict:
    analysis = _analyze_change(arguments)
    if getattr(arguments, "progress", False):
        print("[change-lens] 聚焦业务变化并生成双层 Change Story", file=sys.stderr, flush=True)
    source_root = Path(arguments.repository)
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
