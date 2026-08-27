"""C# and Unity analysis support."""

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
    "AnalyzerGraphDiff", "AnalyzerGraphDiffer", "MappingHint", "RevisionChangeAnalyzer",
    "RevisionWorkerAssembly", "RevisionWorkerInputAssembler", "RoslynWorkerInput",
    "RoslynWorkerRunner", "UnityAssemblyGraph", "UnityCompilationContext",
    "UnityContextBuilder", "WorkerInputAssembler",
]
