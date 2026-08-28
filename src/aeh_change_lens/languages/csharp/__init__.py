"""C# and Unity analysis support."""

from .build_provenance import (
    BuildProvenanceExporter,
    BuildProvenanceManifest,
    build_manifest_unity_path,
)
from .compile_manifest import CompileManifest, CompileManifestExporter, manifest_unity_path
from .graph_diff import AnalyzerGraphDiff, AnalyzerGraphDiffer, MappingHint
from .revision_analysis import (
    RevisionChangeAnalyzer,
    RevisionWorkerAssembly,
    RevisionWorkerInputAssembler,
    RoslynWorkerRunner,
)
from .unity_context import UnityAssemblyGraph, UnityCompilationContext, UnityContextBuilder
from .worker_input import RoslynWorkerInput, WorkerInputAssembler

__all__ = [
    "AnalyzerGraphDiff", "AnalyzerGraphDiffer", "BuildProvenanceExporter",
    "BuildProvenanceManifest", "CompileManifest", "CompileManifestExporter",
    "MappingHint", "RevisionChangeAnalyzer",
    "RevisionWorkerAssembly", "RevisionWorkerInputAssembler", "RoslynWorkerInput",
    "RoslynWorkerRunner", "UnityAssemblyGraph", "UnityCompilationContext",
    "UnityContextBuilder", "WorkerInputAssembler", "build_manifest_unity_path",
    "manifest_unity_path",
]
