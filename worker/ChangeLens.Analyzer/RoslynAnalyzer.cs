using System.Collections.Immutable;
using System.Security.Cryptography;
using System.Text;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace ChangeLens.Analyzer;

internal static class RoslynAnalyzer
{
    private static readonly HashSet<string> LifecycleNames = new(StringComparer.Ordinal)
    {
        "Awake", "OnEnable", "Start", "FixedUpdate", "Update", "LateUpdate", "OnDisable", "OnDestroy",
    };

    public static AnalyzerOutput Analyze(AnalyzerInput input)
    {
        ValidateInput(input);
        var parseOptions = new CSharpParseOptions(
            LanguageVersion.Latest,
            preprocessorSymbols: input.UnityContext.Defines);
        var trees = input.SourceFiles
            .Select(file => CSharpSyntaxTree.ParseText(
                file.Content,
                parseOptions,
                file.Path,
                Encoding.UTF8))
            .ToArray();
        var compilation = CSharpCompilation.Create(
            $"ChangeLens_{input.RequestId}",
            trees,
            PlatformReferences(),
            new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));

        // Source stubs make semantic tests possible, but they are not
        // authoritative Unity metadata assemblies. This slice must therefore
        // never advertise complete Unity context.
        var effectiveUnityContext = input.UnityContext.Completeness == "MISSING" ? "MISSING" : "PARTIAL";
        var state = new AnalysisState(input, compilation, effectiveUnityContext);
        state.IndexDeclarations(trees);
        state.AnalyzeRelations(trees);
        var compilerErrors = compilation.GetDiagnostics()
            .Where(item => item.Severity == DiagnosticSeverity.Error)
            .ToArray();
        foreach (var diagnostic in compilerErrors.Take(50))
        {
            state.Diagnostics.Add(new AnalyzerDiagnostic(
                "CL-CS-COMPILER",
                "WARNING",
                diagnostic.ToString(),
                Array.Empty<string>()));
        }

        state.Diagnostics.Add(new AnalyzerDiagnostic(
            "CL-CS-CTX-001",
            "WARNING",
            "当前 Worker 尚未加载权威 Unity 元数据程序集，框架关系保持部分/结构置信度。",
            input.SourceFiles.Select(file => file.ContentHash).ToArray()));

        const string status = "PARTIAL";
        return new AnalyzerOutput(
            "1.0.0",
            input.RequestId,
            status,
            new Capabilities(true, true, effectiveUnityContext),
            state.Nodes.OrderBy(item => item.NodeId, StringComparer.Ordinal).ToArray(),
            state.Edges.OrderBy(item => item.EdgeId, StringComparer.Ordinal).ToArray(),
            state.Diagnostics.ToArray());
    }

    private static void ValidateInput(AnalyzerInput input)
    {
        if (input.SchemaVersion != "1.0.0")
            throw new InvalidDataException("Unsupported schema_version.");
        if (string.IsNullOrWhiteSpace(input.RequestId) || input.UnityContext is null || input.SourceFiles is null)
            throw new InvalidDataException("request_id, unity_context and source_files are required.");
        if (input.Revision is not ("OLD" or "NEW"))
            throw new InvalidDataException("revision must be OLD or NEW.");
        if (input.UnityContext.Completeness is not ("COMPLETE" or "PARTIAL" or "MISSING"))
            throw new InvalidDataException("Invalid Unity context completeness.");
        if (input.UnityContext.Defines is null || input.UnityContext.References is null)
            throw new InvalidDataException("Unity defines and references are required.");
        if (input.SourceFiles.Count == 0 || input.SourceFiles.Any(file => file is null))
            throw new InvalidDataException("source_files must not be empty.");
        var paths = new HashSet<string>(StringComparer.Ordinal);
        foreach (var file in input.SourceFiles)
        {
            if (!IsSafeRelativePath(file.Path) || !paths.Add(file.Path))
                throw new InvalidDataException($"Unsafe or duplicate source path: {file.Path}");
            var actual = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(file.Content))).ToLowerInvariant();
            if (!CryptographicOperations.FixedTimeEquals(
                Encoding.ASCII.GetBytes(actual), Encoding.ASCII.GetBytes(file.ContentHash)))
                throw new InvalidDataException($"content_hash mismatch: {file.Path}");
        }
    }

    private static bool IsSafeRelativePath(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || path.Contains('\0') || path.Contains('\\') ||
            path.StartsWith('/') || Path.IsPathRooted(path) ||
            (path.Length >= 2 && char.IsAsciiLetter(path[0]) && path[1] == ':'))
            return false;
        var normalized = path.Replace('\\', '/');
        return normalized.Split('/').All(part => part is not ("" or "." or ".."));
    }

    private static IEnumerable<MetadataReference> PlatformReferences()
    {
        var trusted = AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") as string
            ?? throw new InvalidDataException("Trusted platform assemblies are unavailable.");
        return trusted.Split(Path.PathSeparator).Select(path => MetadataReference.CreateFromFile(path));
    }

    private sealed class AnalysisState
    {
        private readonly AnalyzerInput _input;
        private readonly CSharpCompilation _compilation;
        private readonly string _effectiveUnityContext;
        private readonly Dictionary<ISymbol, GraphNode> _symbolNodes = new(SymbolEqualityComparer.Default);
        private readonly HashSet<string> _nodeIds = new(StringComparer.Ordinal);
        private readonly HashSet<string> _edgeIds = new(StringComparer.Ordinal);

        public List<GraphNode> Nodes { get; } = [];
        public List<GraphEdge> Edges { get; } = [];
        public List<AnalyzerDiagnostic> Diagnostics { get; } = [];

        public AnalysisState(AnalyzerInput input, CSharpCompilation compilation, string effectiveUnityContext)
        {
            _input = input;
            _compilation = compilation;
            _effectiveUnityContext = effectiveUnityContext;
        }

        public void IndexDeclarations(IEnumerable<SyntaxTree> trees)
        {
            foreach (var tree in trees.Where(tree => !tree.FilePath.StartsWith("__stubs__/", StringComparison.Ordinal)))
            {
                var model = _compilation.GetSemanticModel(tree);
                var root = tree.GetRoot();
                foreach (var declaration in root.DescendantNodes().OfType<TypeDeclarationSyntax>())
                {
                    if (model.GetDeclaredSymbol(declaration) is { } symbol)
                        AddSymbolNode(symbol, declaration, "TYPE", "roslyn_declaration", "CONFIRMED_STATIC");
                }
                foreach (var declaration in root.DescendantNodes().OfType<MethodDeclarationSyntax>())
                {
                    if (model.GetDeclaredSymbol(declaration) is { } symbol)
                        AddSymbolNode(symbol, declaration, "METHOD", "roslyn_declaration", "CONFIRMED_STATIC");
                }
            }
        }

        public void AnalyzeRelations(IEnumerable<SyntaxTree> trees)
        {
            foreach (var tree in trees.Where(tree => !tree.FilePath.StartsWith("__stubs__/", StringComparison.Ordinal)))
            {
                var model = _compilation.GetSemanticModel(tree);
                var root = tree.GetRoot();
                foreach (var method in root.DescendantNodes().OfType<MethodDeclarationSyntax>())
                {
                    if (model.GetDeclaredSymbol(method) is not { } methodSymbol || !_symbolNodes.TryGetValue(methodSymbol, out var methodNode))
                        continue;
                    AddLifecycle(method, methodSymbol, methodNode);
                    AddControlFlow(method, methodNode);
                    AddInvocations(method, model, methodNode);
                    AddStateWrites(method, model, methodNode);
                }
                AddSerializedReferences(root, model);
            }
        }

        private void AddLifecycle(MethodDeclarationSyntax syntax, IMethodSymbol symbol, GraphNode methodNode)
        {
            if (!LifecycleNames.Contains(symbol.Name) || symbol.Parameters.Length != 0 || !DerivesFrom(symbol.ContainingType, "UnityEngine.MonoBehaviour"))
                return;
            var framework = AddSyntheticNode(
                $"unity:{_input.Revision}:lifecycle:{symbol.Name}:{SymbolName(symbol.ContainingType)}",
                "UNKNOWN_TARGET",
                $"Unity PlayerLoop::{symbol.Name}",
                syntax,
                "unity_lifecycle_catalog",
                UnityConfidence());
            AddEdge(framework, methodNode, "FRAMEWORK_LIFECYCLE", "unity_lifecycle_catalog", framework.Provenance.Confidence);
        }

        private void AddControlFlow(MethodDeclarationSyntax method, GraphNode methodNode)
        {
            foreach (var condition in method.DescendantNodes().OfType<IfStatementSyntax>())
            {
                var node = AddSyntheticNode(Id("condition", condition), "CONDITION", condition.Condition.ToString(), condition, "roslyn_syntax", "STRUCTURAL");
                AddEdge(methodNode, node, "BRANCHES_TO", "roslyn_syntax", "STRUCTURAL");
            }
            foreach (var statement in method.DescendantNodes().OfType<ThrowStatementSyntax>())
            {
                var node = AddSyntheticNode(Id("throw", statement), "THROW", statement.Expression?.ToString() ?? "throw", statement, "roslyn_syntax", "STRUCTURAL");
                AddEdge(methodNode, node, "THROWS_FROM", "roslyn_syntax", "STRUCTURAL");
            }
            foreach (var statement in method.DescendantNodes().OfType<ReturnStatementSyntax>())
            {
                var node = AddSyntheticNode(Id("return", statement), "RETURN", statement.Expression?.ToString() ?? "return", statement, "roslyn_syntax", "STRUCTURAL");
                AddEdge(methodNode, node, "RETURNS_FROM", "roslyn_syntax", "STRUCTURAL");
            }
        }

        private void AddInvocations(MethodDeclarationSyntax method, SemanticModel model, GraphNode methodNode)
        {
            foreach (var invocation in method.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                var name = invocation.Expression switch
                {
                    IdentifierNameSyntax identifier => identifier.Identifier.ValueText,
                    MemberAccessExpressionSyntax member => member.Name.Identifier.ValueText,
                    _ => invocation.Expression.ToString(),
                };
                if (name == "SendMessage")
                {
                    var label = invocation.ArgumentList.Arguments.FirstOrDefault()?.Expression is LiteralExpressionSyntax literal
                        ? literal.Token.ValueText
                        : "dynamic target";
                    var target = AddSyntheticNode(Id("dynamic", invocation), "UNKNOWN_TARGET", label, invocation, "unity_dynamic_rule", "UNKNOWN");
                    AddEdge(methodNode, target, "DYNAMIC_DISPATCH_UNKNOWN", "unity_dynamic_rule", "UNKNOWN");
                    continue;
                }

                var targetSymbol = model.GetSymbolInfo(invocation).Symbol as IMethodSymbol;
                if (targetSymbol is not null && _symbolNodes.TryGetValue(targetSymbol.OriginalDefinition, out var targetNode))
                {
                    AddEdge(methodNode, targetNode, "DIRECT_CALL", "roslyn_semantic_model", "CONFIRMED_STATIC");
                    continue;
                }

                if (name == "Invoke" && invocation.Expression is MemberAccessExpressionSyntax access)
                {
                    var receiverType = model.GetTypeInfo(access.Expression).Type;
                    if (receiverType is not null && DerivesFrom(receiverType, "UnityEngine.Events.UnityEventBase"))
                    {
                        var confidence = UnityConfidence();
                        var target = AddSyntheticNode(Id("unity-event", invocation), "EVENT", access.Expression.ToString(), invocation, "roslyn_semantic_model", confidence);
                        AddEdge(methodNode, target, "INVOKES_UNITY_EVENT", "roslyn_semantic_model", confidence);
                    }
                }
            }
        }

        private void AddStateWrites(MethodDeclarationSyntax method, SemanticModel model, GraphNode methodNode)
        {
            foreach (var assignment in method.DescendantNodes().OfType<AssignmentExpressionSyntax>())
            {
                var symbol = model.GetSymbolInfo(assignment.Left).Symbol;
                if (symbol is not (IFieldSymbol or IPropertySymbol))
                    continue;
                var state = AddSyntheticNode(Id("state", assignment), "STATE", SymbolName(symbol), assignment.Left, "roslyn_semantic_model", "CONFIRMED_STATIC");
                AddEdge(methodNode, state, "WRITES_STATE", "roslyn_semantic_model", "CONFIRMED_STATIC");
            }
        }

        private void AddSerializedReferences(SyntaxNode root, SemanticModel model)
        {
            foreach (var field in root.DescendantNodes().OfType<FieldDeclarationSyntax>())
            {
                if (!field.AttributeLists.SelectMany(list => list.Attributes).Any(attribute => attribute.Name.ToString().EndsWith("SerializeField", StringComparison.Ordinal)))
                    continue;
                var containing = field.FirstAncestorOrSelf<TypeDeclarationSyntax>();
                var sourceSymbol = containing is null ? null : model.GetDeclaredSymbol(containing);
                var type = model.GetTypeInfo(field.Declaration.Type).Type;
                if (sourceSymbol is null || type is null || !_symbolNodes.TryGetValue(sourceSymbol, out var source) || !_symbolNodes.TryGetValue(type, out var target))
                    continue;
                AddEdge(source, target, "SERIALIZED_REFERENCE", "roslyn_semantic_model", UnityConfidence());
            }
        }

        private GraphNode AddSymbolNode(ISymbol symbol, SyntaxNode syntax, string kind, string origin, string confidence)
        {
            var node = CreateNode($"csharp:{_input.Revision}:{SymbolName(symbol)}", kind, SymbolName(symbol), syntax, origin, confidence);
            _symbolNodes[symbol] = node;
            if (symbol is IMethodSymbol method)
                _symbolNodes[method.OriginalDefinition] = node;
            return node;
        }

        private GraphNode AddSyntheticNode(string id, string kind, string label, SyntaxNode syntax, string origin, string confidence)
            => CreateNode(id, kind, label, syntax, origin, confidence);

        private GraphNode CreateNode(string id, string kind, string label, SyntaxNode syntax, string origin, string confidence)
        {
            if (_nodeIds.Contains(id))
                return Nodes.Single(item => item.NodeId == id);
            var file = _input.SourceFiles.Single(item => item.Path == syntax.SyntaxTree.FilePath);
            var span = syntax.GetLocation().GetLineSpan();
            var node = new GraphNode(
                id,
                _input.Revision,
                kind,
                "UNCHANGED_CONTEXT",
                label,
                new SourceLocation(_input.Revision, file.Path, span.StartLinePosition.Line + 1, span.EndLinePosition.Line + 1, file.ContentHash),
                new Provenance(origin, confidence, [file.ContentHash], confidence == "UNKNOWN" ? ["目标无法由静态源码唯一解析。"] : []),
                Array.Empty<string>());
            _nodeIds.Add(id);
            Nodes.Add(node);
            return node;
        }

        private void AddEdge(GraphNode source, GraphNode target, string relation, string origin, string confidence)
        {
            var id = $"edge:{_input.Revision}:{relation}:{source.NodeId}->{target.NodeId}";
            if (!_edgeIds.Add(id))
                return;
            Edges.Add(new GraphEdge(
                id, _input.Revision, source.NodeId, target.NodeId, relation, "UNCHANGED_CONTEXT",
                new Provenance(origin, confidence, source.Provenance.SourceIds.Concat(target.Provenance.SourceIds).Distinct().ToArray(), Array.Empty<string>()),
                Array.Empty<string>()));
        }

        private string Id(string kind, SyntaxNode syntax)
            => $"csharp:{_input.Revision}:{syntax.SyntaxTree.FilePath}:{kind}:{syntax.SpanStart}";

        private string UnityConfidence()
            => _effectiveUnityContext == "COMPLETE" ? "CONFIRMED_STATIC" : "STRUCTURAL";

        private static string SymbolName(ISymbol symbol)
            => symbol.ToDisplayString(SymbolDisplayFormat.CSharpErrorMessageFormat);

        private static bool DerivesFrom(ITypeSymbol type, string metadataName)
        {
            for (var current = type; current is not null; current = current.BaseType)
            {
                if ($"{current.ContainingNamespace}.{current.MetadataName}" == metadataName)
                    return true;
            }
            return false;
        }
    }
}
