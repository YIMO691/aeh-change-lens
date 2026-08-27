"""C# and Unity analysis support."""

from .graph_diff import AnalyzerGraphDiff, AnalyzerGraphDiffer, MappingHint
from .unity_context import UnityAssemblyGraph, UnityCompilationContext, UnityContextBuilder
from .worker_input import RoslynWorkerInput, WorkerInputAssembler

__all__ = [
    "AnalyzerGraphDiff", "AnalyzerGraphDiffer", "MappingHint", "RoslynWorkerInput",
    "UnityAssemblyGraph", "UnityCompilationContext", "UnityContextBuilder",
    "WorkerInputAssembler",
]
