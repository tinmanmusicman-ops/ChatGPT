using System.Text.Json;
using PainRadar.Models;
using PainRadar.Services;

namespace PainRadar.Services.Sources;

public sealed class RedditWtbSource : IGearSource
{
    private readonly HttpClient _http;
    private readonly IReadOnlyList<string> _subreddits;

    public RedditWtbSource(HttpClient http, IReadOnlyList<string> subreddits)
    {
        _http = http;
        _subreddits = subreddits
            .Select(s => (s ?? "").Trim().TrimStart('/').TrimStart('r').TrimStart('/'))
            .Where(s => !string.IsNullOrWhiteSpace(s))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    public string SourceName => "Reddit";

    public async Task<IReadOnlyList<GearSignalItem>> FetchAsync(string searchTerm, int maxResults, CancellationToken cancellationToken)
    {
        var perSubLimit = Math.Clamp(maxResults, 1, 100);
        var results = new List<GearSignalItem>(_subreddits.Count * Math.Min(25, perSubLimit));
        var queries = GearSearchQueryBuilder.BuildQueries(searchTerm);

        foreach (var sub in _subreddits)
        {
            cancellationToken.ThrowIfCancellationRequested();

            var seenPermalinks = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var fetchedForSub = 0;

            try
            {
                foreach (var query in queries)
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    if (fetchedForSub >= perSubLimit)
                        break;

                    var remaining = perSubLimit - fetchedForSub;
                    var limit = Math.Clamp(remaining, 1, 25);

                    var url =
                        $"https://www.reddit.com/r/{Uri.EscapeDataString(sub)}/search.json" +
                        $"?q={Uri.EscapeDataString(query)}&restrict_sr=1&sort=new&t=year&limit={limit}";

                    using var resp = await _http.GetAsync(url, cancellationToken).ConfigureAwait(false);
                    resp.EnsureSuccessStatusCode();

                    await using var stream = await resp.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
                    using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken).ConfigureAwait(false);

                    if (!doc.RootElement.TryGetProperty("data", out var data) || data.ValueKind != JsonValueKind.Object)
                        continue;

                    if (!data.TryGetProperty("children", out var children) || children.ValueKind != JsonValueKind.Array)
                        continue;

                    foreach (var child in children.EnumerateArray())
                    {
                        if (fetchedForSub >= perSubLimit)
                            break;

                        if (child.ValueKind != JsonValueKind.Object || !child.TryGetProperty("data", out var post) || post.ValueKind != JsonValueKind.Object)
                            continue;

                        var title = post.TryGetProperty("title", out var eTitle) ? eTitle.GetString() ?? "" : "";
                        var selfText = post.TryGetProperty("selftext", out var eSelf) ? eSelf.GetString() ?? "" : "";
                        var author = post.TryGetProperty("author", out var eAuthor) ? eAuthor.GetString() ?? "" : "";
                        var permalink = post.TryGetProperty("permalink", out var ePerma) ? ePerma.GetString() ?? "" : "";
                        var createdUtc = post.TryGetProperty("created_utc", out var eCreated) && eCreated.ValueKind == JsonValueKind.Number && eCreated.TryGetDouble(out var seconds)
                            ? DateTimeOffset.FromUnixTimeSeconds((long)seconds)
                            : (DateTimeOffset?)null;

                        if (string.IsNullOrWhiteSpace(title) && string.IsNullOrWhiteSpace(selfText))
                            continue;

                        var fullUrl = string.IsNullOrWhiteSpace(permalink) ? "" : "https://www.reddit.com" + permalink;
                        if (!string.IsNullOrWhiteSpace(permalink) && !seenPermalinks.Add(permalink))
                            continue;

                        results.Add(new GearSignalItem(
                            platform: "Reddit",
                            buyer: string.IsNullOrWhiteSpace(author) ? "" : $"u/{author.Trim()}",
                            title: title,
                            body: TextSanitizer.ToPlainText(selfText),
                            url: fullUrl,
                            postedAtUtc: createdUtc
                        ));
                        fetchedForSub++;
                    }
                }
            }
            catch
            {
                // graceful per-subreddit failure; orchestrator logs overall
            }
        }

        return results;
    }
}
