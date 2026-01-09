using System.Net.Http;
using System.Text.Json;
using PainRadar.Models;

namespace PainRadar.Services;

public sealed class RedditSearchService
{
    private readonly HttpClient _http;

    public RedditSearchService(HttpClient http) => _http = http;

    public async Task<(int Score, IReadOnlyList<string> MatchedKeywords, IReadOnlyList<SourceLink> Urls)> SearchCompanyAsync(
        string company,
        IReadOnlyList<string> painKeywords,
        int limit,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(company))
            return (0, Array.Empty<string>(), Array.Empty<SourceLink>());

        var query = $"\"{company}\" (manual OR workaround OR broken OR coordination OR follow-up OR disorganized OR inefficient OR scaling OR ambiguity)";
        var url = $"https://www.reddit.com/search.json?q={Uri.EscapeDataString(query)}&limit={Math.Clamp(limit, 1, 25)}&sort=relevance&t=year";

        using var resp = await _http.GetAsync(url, cancellationToken).ConfigureAwait(false);
        resp.EnsureSuccessStatusCode();

        await using var stream = await resp.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken).ConfigureAwait(false);

        if (!doc.RootElement.TryGetProperty("data", out var data) || data.ValueKind != JsonValueKind.Object)
            return (0, Array.Empty<string>(), Array.Empty<SourceLink>());

        if (!data.TryGetProperty("children", out var children) || children.ValueKind != JsonValueKind.Array)
            return (0, Array.Empty<string>(), Array.Empty<SourceLink>());

        var matched = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var urls = new List<SourceLink>();
        var score = 0;

        foreach (var child in children.EnumerateArray())
        {
            if (child.ValueKind != JsonValueKind.Object || !child.TryGetProperty("data", out var post) || post.ValueKind != JsonValueKind.Object)
                continue;

            var title = post.TryGetProperty("title", out var eTitle) ? eTitle.GetString() ?? "" : "";
            var selfText = post.TryGetProperty("selftext", out var eSelf) ? eSelf.GetString() ?? "" : "";
            var permalink = post.TryGetProperty("permalink", out var ePerma) ? ePerma.GetString() ?? "" : "";

            var combined = (title + "\n" + selfText).ToLowerInvariant();
            foreach (var kw in painKeywords)
            {
                if (combined.Contains(kw, StringComparison.OrdinalIgnoreCase))
                {
                    matched.Add(kw);
                    score += 5;
                }
            }

            if (!string.IsNullOrWhiteSpace(permalink))
            {
                var full = "https://www.reddit.com" + permalink;
                urls.Add(new SourceLink($"Reddit: {TrimForLabel(title, 60)}", full));
            }
        }

        return (score, matched.OrderBy(s => s).ToArray(), urls);
    }

    private static string TrimForLabel(string text, int max)
    {
        var t = (text ?? "").Trim();
        return t.Length <= max ? t : t.Substring(0, max - 1) + "…";
    }
}
