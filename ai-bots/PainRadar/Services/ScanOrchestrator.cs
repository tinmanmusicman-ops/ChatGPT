using PainRadar.Models;
using PainRadar.Infrastructure;

namespace PainRadar.Services;

public sealed class ScanOrchestrator
{
    private readonly IReadOnlyList<IJobSource> _sources;
    private readonly RedditSearchService _reddit;
    private readonly GooglePlacesService _google;
    private readonly PainAnalyzer _analyzer;
    private readonly CompanySmbFilter _smbFilter = new();

    public ScanOrchestrator(
        IReadOnlyList<IJobSource> sources,
        RedditSearchService reddit,
        GooglePlacesService google,
        PainAnalyzer analyzer)
    {
        _sources = sources;
        _reddit = reddit;
        _google = google;
        _analyzer = analyzer;
    }

    public async Task<IReadOnlyList<SignalItem>> ScanAsync(
        ScanOptions options,
        IProgress<ScanProgress> progress,
        CancellationToken cancellationToken)
    {
        var enabledSources = _sources
            .Where(s => IsEnabled(options, s.SourceName))
            .ToArray();

        if (options.EnableGoogleReviews && !_google.IsEnabled)
            AppLogger.Warn("Google Reviews enabled in UI but GooglePlacesApiKey is missing; skipping Google enrichment.");

        AppLogger.Info($"ScanOrchestrator: enabledSources=[{string.Join(", ", enabledSources.Select(s => s.SourceName))}] search=\"{options.SearchTerm}\"");
        progress.Report(new ScanProgress("Fetching jobs", 0, enabledSources.Length));

        var fetched = new List<SignalItem>();
        var completed = 0;
        foreach (var source in enabledSources)
        {
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                var items = await source.FetchAsync(options.SearchTerm, options.MaxResultsPerSource, cancellationToken).ConfigureAwait(false);
                fetched.AddRange(items);
                AppLogger.Info($"Fetched {items.Count} items from {source.SourceName}");
            }
            catch (Exception ex)
            {
                // graceful failure per-source
                AppLogger.Exception(ex, $"Fetch failed: {source.SourceName}");
            }
            finally
            {
                completed++;
                progress.Report(new ScanProgress("Fetching jobs", completed, enabledSources.Length));
            }
        }

        var deduped = Deduplicate(fetched);
        AppLogger.Info($"Deduped: fetched={fetched.Count} deduped={deduped.Count}");

        progress.Report(new ScanProgress("Scoring job text", 0, deduped.Count));
        for (var i = 0; i < deduped.Count; i++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var item = deduped[i];
            var analysis = _analyzer.AnalyzeJob(item.JobTitle, item.Description);
            item.PainScore = analysis.PainScore;
            item.GrowthScore = analysis.GrowthScore;
            item.FixableScore = analysis.FixableScore;
            item.SmbFitScore = analysis.SmbFitScore;
            item.MatchedKeywords = analysis.AllMatchedKeywords;
            progress.Report(new ScanProgress("Scoring job text", i + 1, deduped.Count));
        }

        // SMB-only filtering (default). Can be disabled via IncludeEnterprises.
        if (!options.IncludeEnterprises)
        {
            progress.Report(new ScanProgress("Filtering SMB", 0, 1));
            var byCompany = deduped
                .GroupBy(x => x.Company, StringComparer.OrdinalIgnoreCase)
                .ToDictionary(g => g.Key, g => (IReadOnlyList<SignalItem>)g.ToList(), StringComparer.OrdinalIgnoreCase);

            var decisions = new Dictionary<string, CompanyDecision>(StringComparer.OrdinalIgnoreCase);
            foreach (var (company, items) in byCompany)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var decision = _smbFilter.DecideCompany(company, items);
                decisions[company] = decision;
                CompanySmbFilter.LogDecision(decision);
            }

            var filtered = deduped.Where(i => decisions.TryGetValue(i.Company, out var d) && d.IsIncluded).ToList();
            AppLogger.Info($"SMB filter: before={deduped.Count} after={filtered.Count} excludedCompanies={decisions.Values.Count(d => d.IsExcluded)}");
            deduped = filtered;
            progress.Report(new ScanProgress("Filtering SMB", 1, 1));
        }
        else
        {
            AppLogger.Info("SMB filter bypassed (IncludeEnterprises=true)");
        }

        var companiesToEnrich = deduped
            .GroupBy(x => x.Company, StringComparer.OrdinalIgnoreCase)
            .Select(g => new { Company = g.Key, Score = g.Max(x => x.PainScore + x.GrowthScore) })
            .OrderByDescending(x => x.Score)
            .Take(options.MaxCompaniesToEnrich)
            .Select(x => x.Company)
            .ToArray();

        if (companiesToEnrich.Length == 0)
            AppLogger.Info("Enrichment skipped: no companies to enrich");

        if (companiesToEnrich.Length == 0 || (!options.EnableReddit && !options.EnableGoogleReviews))
            return deduped.OrderByDescending(x => x.TotalScore).ToArray();

        AppLogger.Info($"Enrichment: companies={companiesToEnrich.Length} reddit={options.EnableReddit} google={options.EnableGoogleReviews && _google.IsEnabled}");
        progress.Report(new ScanProgress("Enriching companies", 0, companiesToEnrich.Length));

        var enrichment = new Dictionary<string, CompanyEnrichment>(StringComparer.OrdinalIgnoreCase);
        var gate = new SemaphoreSlim(Math.Clamp(options.MaxEnrichmentConcurrency, 1, 16));
        var enrichCompleted = 0;

        var tasks = companiesToEnrich.Select(async company =>
        {
            await gate.WaitAsync(cancellationToken).ConfigureAwait(false);
            try
            {
                var e = await EnrichCompanyAsync(company, options, cancellationToken).ConfigureAwait(false);
                lock (enrichment)
                {
                    enrichment[company] = e;
                }
            }
            catch (Exception ex)
            {
                AppLogger.Exception(ex, $"Enrich failed: {company}");
            }
            finally
            {
                gate.Release();
                var done = Interlocked.Increment(ref enrichCompleted);
                progress.Report(new ScanProgress("Enriching companies", done, companiesToEnrich.Length));
            }
        }).ToArray();

        await Task.WhenAll(tasks).ConfigureAwait(false);

        progress.Report(new ScanProgress("Applying enrichment", 0, deduped.Count));
        for (var i = 0; i < deduped.Count; i++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var item = deduped[i];
            if (enrichment.TryGetValue(item.Company, out var e))
            {
                item.RedditScore = e.RedditScore;
                item.GoogleScore = e.GoogleScore;

                var mergedKeywords = item.MatchedKeywords
                    .Concat(e.RedditMatchedKeywords)
                    .Concat(e.GoogleMatchedKeywords)
                    .Distinct(StringComparer.OrdinalIgnoreCase)
                    .OrderBy(s => s)
                    .ToArray();
                item.MatchedKeywords = mergedKeywords;

                var urls = new List<SourceLink>(item.SourceUrls);
                urls.AddRange(e.RedditUrls);
                if (e.GooglePlaceUrl is not null)
                    urls.Add(e.GooglePlaceUrl);
                item.SourceUrls = urls;
            }
            progress.Report(new ScanProgress("Applying enrichment", i + 1, deduped.Count));
        }

        return deduped.OrderByDescending(x => x.TotalScore).ToArray();
    }

    private async Task<CompanyEnrichment> EnrichCompanyAsync(string company, ScanOptions options, CancellationToken cancellationToken)
    {
        var redditScore = 0;
        var redditMatched = Array.Empty<string>();
        var redditUrls = Array.Empty<SourceLink>();

        if (options.EnableReddit)
        {
            try
            {
                var reddit = await _reddit.SearchCompanyAsync(company, PainAnalyzer.PainKeywords, options.RedditSearchLimit, cancellationToken).ConfigureAwait(false);
                redditScore = reddit.Score;
                redditMatched = reddit.MatchedKeywords.ToArray();
                redditUrls = reddit.Urls.ToArray();
            }
            catch
            {
            }
        }

        var googleScore = 0;
        var googleMatched = Array.Empty<string>();
        SourceLink? googleUrl = null;

        if (options.EnableGoogleReviews && _google.IsEnabled)
        {
            try
            {
                var google = await _google.GetCompanyReviewSignalsAsync(company, PainAnalyzer.GoogleReviewPainKeywords, cancellationToken).ConfigureAwait(false);
                googleScore = google.Score;
                googleMatched = google.MatchedKeywords.ToArray();
                googleUrl = google.PlaceUrl;
            }
            catch
            {
            }
        }

        return new CompanyEnrichment(
            RedditScore: redditScore,
            RedditMatchedKeywords: redditMatched,
            RedditUrls: redditUrls,
            GoogleScore: googleScore,
            GoogleMatchedKeywords: googleMatched,
            GooglePlaceUrl: googleUrl
        );
    }

    private static bool IsEnabled(ScanOptions o, string sourceName) =>
        sourceName switch
        {
            "Remotive" => o.EnableRemotive,
            "RemoteOK" => o.EnableRemoteOk,
            "TheMuse" => o.EnableMuse,
            _ => true
        };

    private static List<SignalItem> Deduplicate(List<SignalItem> input)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var list = new List<SignalItem>(input.Count);
        foreach (var i in input)
        {
            var key = $"{i.Company}|{i.JobTitle}|{i.JobUrl}";
            if (seen.Add(key))
                list.Add(i);
        }
        return list;
    }
}

public sealed record CompanyEnrichment(
    int RedditScore,
    IReadOnlyList<string> RedditMatchedKeywords,
    IReadOnlyList<SourceLink> RedditUrls,
    int GoogleScore,
    IReadOnlyList<string> GoogleMatchedKeywords,
    SourceLink? GooglePlaceUrl
);
