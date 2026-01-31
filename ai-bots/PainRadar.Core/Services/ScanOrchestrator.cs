using PainRadar.Infrastructure;
using PainRadar.Models;

namespace PainRadar.Services;

public sealed class ScanOrchestrator
{
    private readonly IReadOnlyList<IGearSource> _sources;
    private readonly GearIntentAnalyzer _analyzer;
    private readonly IPainRadarLogger _log;

    public ScanOrchestrator(
        IReadOnlyList<IGearSource> sources,
        GearIntentAnalyzer analyzer,
        IPainRadarLogger? log = null)
    {
        _sources = sources;
        _analyzer = analyzer;
        _log = log ?? NullPainRadarLogger.Instance;
    }

    public async Task<IReadOnlyList<GearSignalItem>> ScanAsync(
        ScanOptions options,
        IProgress<ScanProgress> progress,
        CancellationToken cancellationToken)
    {
        var enabledSources = _sources
            .Where(s => IsEnabled(options, s.SourceName))
            .ToArray();

        _log.Info($"ScanOrchestrator: enabledSources=[{string.Join(", ", enabledSources.Select(s => s.SourceName))}] search=\"{options.SearchTerm}\" requireIntentAndGear={options.RequireIntentAndGearMatch}");
        progress.Report(new ScanProgress("Fetching posts", 0, enabledSources.Length));

        var fetched = new List<GearSignalItem>();
        var completed = 0;
        foreach (var source in enabledSources)
        {
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                var limit = LimitForSource(options, source.SourceName);
                var items = await source.FetchAsync(options.SearchTerm, limit, cancellationToken).ConfigureAwait(false);
                fetched.AddRange(items);
                _log.Info($"Fetched {items.Count} items from {source.SourceName}");
            }
            catch (Exception ex)
            {
                // graceful failure per-source
                _log.Exception(ex, $"Fetch failed: {source.SourceName}");
            }
            finally
            {
                completed++;
                progress.Report(new ScanProgress("Fetching posts", completed, enabledSources.Length));
            }
        }

        var deduped = Deduplicate(fetched);
        _log.Info($"Deduped: fetched={fetched.Count} deduped={deduped.Count}");

        progress.Report(new ScanProgress("Scoring posts", 0, deduped.Count));
        for (var i = 0; i < deduped.Count; i++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var item = deduped[i];
            var analysis = _analyzer.AnalyzePost(item.Title, item.Body);
            item.IntentScore = analysis.IntentScore;
            item.GearScore = analysis.GearScore;
            item.ConfidenceScore = analysis.ConfidenceScore;
            item.MatchedIntentPhrases = analysis.MatchedIntentPhrases;
            item.MatchedGear = analysis.MatchedGear;
            progress.Report(new ScanProgress("Scoring posts", i + 1, deduped.Count));
        }

        if (options.RequireIntentAndGearMatch)
        {
            progress.Report(new ScanProgress("Filtering matches", 0, 1));
            var before = deduped.Count;
            deduped = deduped
                .Where(i => i.MatchedIntentPhrases.Count > 0 && i.MatchedGear.Count > 0)
                .ToList();
            _log.Info($"Filter requireIntentAndGear: before={before} after={deduped.Count}");
            progress.Report(new ScanProgress("Filtering matches", 1, 1));
        }
        else
        {
            _log.Info("Filter requireIntentAndGear disabled");
        }

        return deduped.OrderByDescending(x => x.TotalScore).ToArray();
    }

    private static bool IsEnabled(ScanOptions o, string sourceName) =>
        sourceName switch
        {
            "Reddit" => o.EnableReddit,
            "Craigslist" => o.EnableCraigslist,
            _ => true
        };

    private static int LimitForSource(ScanOptions o, string sourceName) =>
        sourceName switch
        {
            "Reddit" => o.RedditLimitPerSubreddit > 0 ? o.RedditLimitPerSubreddit : o.MaxResultsPerSource,
            "Craigslist" => o.CraigslistLimitPerSite > 0 ? o.CraigslistLimitPerSite : o.MaxResultsPerSource,
            _ => o.MaxResultsPerSource
        };

    private static List<GearSignalItem> Deduplicate(List<GearSignalItem> input)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var list = new List<GearSignalItem>(input.Count);
        foreach (var i in input)
        {
            var url = (i.Url ?? "").Trim();
            var key = url.Length > 0
                ? $"{i.Platform}|{url}"
                : $"{i.Platform}|{i.Buyer}|{i.Title}|{i.PostedAtUtc?.ToUnixTimeSeconds() ?? 0}";
            if (seen.Add(key))
                list.Add(i);
        }
        return list;
    }
}
