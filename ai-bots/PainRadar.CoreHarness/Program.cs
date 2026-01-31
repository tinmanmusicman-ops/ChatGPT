using PainRadar.Infrastructure;
using PainRadar.Models;
using PainRadar.Services;

var logger = new ConsoleLogger();
logger.Info("PainRadar.CoreHarness starting");

using var http = new HttpClient();

var sources = new IGearSource[] { new FakeGearSource() };
var orchestrator = new ScanOrchestrator(
    sources: sources,
    analyzer: new GearIntentAnalyzer(new GearMatcher(new GearDictionary())),
    log: logger
);

var options = new ScanOptions(
    SearchTerm: "support",
    EnableReddit: true,
    EnableCraigslist: false,
    RequireIntentAndGearMatch: true,
    MaxResultsPerSource: 5,
    RedditLimitPerSubreddit: 5,
    CraigslistLimitPerSite: 5
);

var progress = new Progress<ScanProgress>(p =>
{
    Console.WriteLine($"[PROGRESS] {p.Stage} {p.Completed}/{p.Total} ({p.Percent:0}%)");
});

var results = await orchestrator.ScanAsync(options, progress, CancellationToken.None);
Console.WriteLine($"[DONE] results={results.Count}");
foreach (var item in results)
{
    Console.WriteLine($"- {item.Platform} | {item.Buyer} | TotalScore={item.TotalScore} | Gear={item.MatchedGearDisplay} | Intent={item.MatchedIntentPhrasesDisplay}");
}

sealed class ConsoleLogger : IPainRadarLogger
{
    public void Info(string message) => Console.WriteLine($"[INFO] {message}");
    public void Warn(string message) => Console.WriteLine($"[WARN] {message}");
    public void Error(string message) => Console.WriteLine($"[ERROR] {message}");

    public void Exception(Exception ex, string context)
        => Console.WriteLine($"[EX] {context}: {ex.GetType().Name}: {ex.Message}");
}

sealed class FakeGearSource : IGearSource
{
    public string SourceName => "Reddit";

    public Task<IReadOnlyList<GearSignalItem>> FetchAsync(string searchTerm, int maxResults, CancellationToken cancellationToken)
    {
        var item = new GearSignalItem(
            platform: "Reddit",
            buyer: "u/example",
            title: "WTB Komplete Kontrol S88 Mk1",
            body: "Looking for a Komplete Kontrol S88 mk1. Anyone selling?",
            url: "https://example.com/post",
            postedAtUtc: DateTimeOffset.UtcNow
        );
        return Task.FromResult<IReadOnlyList<GearSignalItem>>(new[] { item });
    }
}
