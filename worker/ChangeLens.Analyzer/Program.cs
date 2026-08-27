using System.Text.Json;
using ChangeLens.Analyzer;

var options = new JsonSerializerOptions
{
    PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    PropertyNameCaseInsensitive = false,
    WriteIndented = false,
};

try
{
    string json;
    if (args.Length == 2 && args[0] == "--input")
    {
        json = await File.ReadAllTextAsync(args[1]);
    }
    else if (args.Length == 0)
    {
        json = await Console.In.ReadToEndAsync();
    }
    else
    {
        throw new ArgumentException("Usage: ChangeLens.Analyzer [--input request.json]");
    }

    var input = JsonSerializer.Deserialize<AnalyzerInput>(json, options)
        ?? throw new InvalidDataException("Analyzer input is empty.");
    var output = RoslynAnalyzer.Analyze(input);
    Console.WriteLine(JsonSerializer.Serialize(output, options));
    return 0;
}
catch (Exception error) when (error is ArgumentException or InvalidDataException or JsonException)
{
    Console.Error.WriteLine(JsonSerializer.Serialize(new
    {
        status = "FAILED",
        error = error.Message,
    }, options));
    return 2;
}

