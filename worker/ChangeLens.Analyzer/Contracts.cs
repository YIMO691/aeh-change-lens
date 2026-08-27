using System.Text.Json.Serialization;

namespace ChangeLens.Analyzer;

internal sealed record AnalyzerInput(
    string SchemaVersion,
    string RequestId,
    string Revision,
    UnityContext UnityContext,
    IReadOnlyList<SourceFile> SourceFiles);

internal sealed record UnityContext(
    string Completeness,
    string? UnityVersion,
    IReadOnlyList<string> Defines,
    IReadOnlyList<MetadataReferenceInput> References);

internal sealed record MetadataReferenceInput(string Path, string Sha256, string Kind);

internal sealed record SourceFile(
    string Path,
    string Content,
    string ContentHash,
    string SnapshotContentHash,
    string SourceEncoding);

internal sealed record AnalyzerOutput(
    string SchemaVersion,
    string RequestId,
    string Status,
    Capabilities Capabilities,
    IReadOnlyList<GraphNode> Nodes,
    IReadOnlyList<GraphEdge> Edges,
    IReadOnlyList<AnalyzerDiagnostic> Diagnostics);

internal sealed record Capabilities(bool Syntax, bool SemanticModel, string UnityContext);

internal sealed record GraphNode(
    string NodeId,
    string Revision,
    string Kind,
    string Change,
    string Label,
    SourceLocation Location,
    Provenance Provenance,
    IReadOnlyList<string> EvidenceRefs);

internal sealed record GraphEdge(
    string EdgeId,
    string Revision,
    string SourceNodeId,
    string TargetNodeId,
    string Relation,
    string Change,
    Provenance Provenance,
    IReadOnlyList<string> EvidenceRefs);

internal sealed record SourceLocation(
    string RevisionRole,
    string Path,
    int StartLine,
    int EndLine,
    string ContentHash);

internal sealed record Provenance(
    string Origin,
    string Confidence,
    IReadOnlyList<string> SourceIds,
    IReadOnlyList<string> Limitations);

internal sealed record AnalyzerDiagnostic(
    string Code,
    string Severity,
    string MessageZh,
    IReadOnlyList<string> SourceIds);

[JsonSerializable(typeof(AnalyzerInput))]
[JsonSerializable(typeof(AnalyzerOutput))]
[JsonSourceGenerationOptions(PropertyNamingPolicy = JsonKnownNamingPolicy.SnakeCaseLower)]
internal partial class WorkerJsonContext : JsonSerializerContext;
