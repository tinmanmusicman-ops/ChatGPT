using System.Net.Http;
using System.Text.Json;
using System.Text.RegularExpressions;
using PainRadar.Models;
using PainRadar.Infrastructure;

namespace PainRadar.Services;

public sealed class GooglePlacesService
{
    private readonly HttpClient _http;
    private readonly string _apiKey;
    private readonly bool _verbose;

    public GooglePlacesService(HttpClient http, string apiKey, bool verboseLogging = false)
    {
        _http = http;
        _apiKey = apiKey ?? "";
        _verbose = verboseLogging;
    }

    public bool IsEnabled => !string.IsNullOrWhiteSpace(_apiKey);

    public async Task<(int Score, IReadOnlyList<string> MatchedKeywords, SourceLink? PlaceUrl)> GetCompanyReviewSignalsAsync(
        string company,
        IReadOnlyList<string> painKeywords,
        CancellationToken cancellationToken)
    {
        if (!IsEnabled || string.IsNullOrWhiteSpace(company))
            return (0, Array.Empty<string>(), null);

        AppLogger.Info($"Google: enrich start company=\"{company.Trim()}\"");
        var placeId = await FindPlaceIdAsync(company.Trim(), cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(placeId))
        {
            AppLogger.Info($"Google: no place found company=\"{company.Trim()}\"");
            return (0, Array.Empty<string>(), null);
        }

        var result = await GetReviewSignalsByPlaceIdAsync(placeId, painKeywords, cancellationToken).ConfigureAwait(false);
        AppLogger.Info($"Google: enrich done company=\"{company.Trim()}\" score={result.Score} matched={result.MatchedKeywords.Count}");
        return result;
    }

    private async Task<string> FindPlaceIdAsync(string company, CancellationToken cancellationToken)
    {
        var url = $"https://maps.googleapis.com/maps/api/place/textsearch/json?query={Uri.EscapeDataString(company)}&key={Uri.EscapeDataString(_apiKey)}";
        if (_verbose)
            AppLogger.Info($"Google textsearch -> {SanitizeUrl(url)}");
        using var resp = await _http.GetAsync(url, cancellationToken).ConfigureAwait(false);
        if (_verbose)
            AppLogger.Info($"Google textsearch <- HTTP {(int)resp.StatusCode} {resp.ReasonPhrase}");
        resp.EnsureSuccessStatusCode();

        await using var stream = await resp.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken).ConfigureAwait(false);

        var status = doc.RootElement.TryGetProperty("status", out var eStatus) ? eStatus.GetString() ?? "" : "";
        if (_verbose)
            AppLogger.Info($"Google textsearch status={status} company=\"{company}\"");
        if (!string.Equals(status, "OK", StringComparison.OrdinalIgnoreCase) && !string.Equals(status, "ZERO_RESULTS", StringComparison.OrdinalIgnoreCase))
        {
            var err = doc.RootElement.TryGetProperty("error_message", out var eErr) ? eErr.GetString() ?? "" : "";
            AppLogger.Warn($"Google Places textsearch status={status} company=\"{company}\" error=\"{err}\"");
        }

        if (!doc.RootElement.TryGetProperty("results", out var results) || results.ValueKind != JsonValueKind.Array)
            return "";

        AppLogger.Info($"Google textsearch parsed: status={status} results={results.GetArrayLength()} company=\"{company}\"");

        foreach (var r in results.EnumerateArray())
        {
            if (r.ValueKind != JsonValueKind.Object)
                continue;
            if (r.TryGetProperty("place_id", out var ePlace) && ePlace.ValueKind == JsonValueKind.String)
            {
                if (_verbose)
                {
                    var name = r.TryGetProperty("name", out var eName) ? eName.GetString() ?? "" : "";
                    AppLogger.Info($"Google textsearch selected place: name=\"{name}\" placeId={Shorten(ePlace.GetString() ?? "")}");
                }
                return ePlace.GetString() ?? "";
            }
        }

        return "";
    }

    private async Task<(int Score, IReadOnlyList<string> MatchedKeywords, SourceLink? PlaceUrl)> GetReviewSignalsByPlaceIdAsync(
        string placeId,
        IReadOnlyList<string> painKeywords,
        CancellationToken cancellationToken)
    {
        var fields = "name,url,reviews";
        var url = $"https://maps.googleapis.com/maps/api/place/details/json?place_id={Uri.EscapeDataString(placeId)}&fields={Uri.EscapeDataString(fields)}&key={Uri.EscapeDataString(_apiKey)}";
        if (_verbose)
            AppLogger.Info($"Google details -> {SanitizeUrl(url)}");
        using var resp = await _http.GetAsync(url, cancellationToken).ConfigureAwait(false);
        if (_verbose)
            AppLogger.Info($"Google details <- HTTP {(int)resp.StatusCode} {resp.ReasonPhrase} placeId={Shorten(placeId)}");
        resp.EnsureSuccessStatusCode();

        await using var stream = await resp.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken).ConfigureAwait(false);

        var status = doc.RootElement.TryGetProperty("status", out var eStatus) ? eStatus.GetString() ?? "" : "";
        if (_verbose)
            AppLogger.Info($"Google details status={status} placeId={Shorten(placeId)}");
        if (!string.Equals(status, "OK", StringComparison.OrdinalIgnoreCase) && !string.Equals(status, "ZERO_RESULTS", StringComparison.OrdinalIgnoreCase))
        {
            var err = doc.RootElement.TryGetProperty("error_message", out var eErr) ? eErr.GetString() ?? "" : "";
            AppLogger.Warn($"Google Places details status={status} placeId={placeId} error=\"{err}\"");
        }

        if (!doc.RootElement.TryGetProperty("result", out var result) || result.ValueKind != JsonValueKind.Object)
            return (0, Array.Empty<string>(), null);

        var name = result.TryGetProperty("name", out var eName) ? eName.GetString() ?? "Google Place" : "Google Place";
        var placeUrl = result.TryGetProperty("url", out var eUrl) ? eUrl.GetString() ?? "" : "";
        SourceLink? link = string.IsNullOrWhiteSpace(placeUrl) ? null : new SourceLink($"Google: {name}", placeUrl);

        var matched = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var score = 0;
        var reviewCount = 0;

        if (result.TryGetProperty("reviews", out var reviews) && reviews.ValueKind == JsonValueKind.Array)
        {
            reviewCount = reviews.GetArrayLength();
            foreach (var rev in reviews.EnumerateArray())
            {
                if (rev.ValueKind != JsonValueKind.Object)
                    continue;
                var text = rev.TryGetProperty("text", out var eText) ? eText.GetString() ?? "" : "";
                if (string.IsNullOrWhiteSpace(text))
                    continue;

                foreach (var kw in painKeywords)
                {
                    if (text.Contains(kw, StringComparison.OrdinalIgnoreCase))
                    {
                        matched.Add(kw);
                        score += 10;
                    }
                }
            }
        }

        AppLogger.Info($"Google details parsed: status={status} place=\"{name}\" reviews={reviewCount} matched={matched.Count} score={score}");

        return (score, matched.OrderBy(s => s).ToArray(), link);
    }

    private static string SanitizeUrl(string url)
    {
        if (string.IsNullOrWhiteSpace(url))
            return "";
        return Regex.Replace(url, "(?i)([?&]key=)[^&]+", "$1REDACTED");
    }

    private static string Shorten(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return "";
        var v = value.Trim();
        return v.Length <= 10 ? v : v.Substring(0, 6) + "…" + v.Substring(v.Length - 3);
    }
}
