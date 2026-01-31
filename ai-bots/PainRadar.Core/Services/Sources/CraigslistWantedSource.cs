using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml.Linq;
using PainRadar.Models;
using PainRadar.Services;

namespace PainRadar.Services.Sources;

public sealed partial class CraigslistWantedSource : IGearSource
{
    private readonly HttpClient _http;
    private readonly IReadOnlyList<string> _baseUrls;

    public CraigslistWantedSource(HttpClient http, IReadOnlyList<string> baseUrls)
    {
        _http = http;
        _baseUrls = baseUrls
            .Select(NormalizeBaseUrl)
            .Where(s => !string.IsNullOrWhiteSpace(s))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    public string SourceName => "Craigslist";

    public async Task<IReadOnlyList<GearSignalItem>> FetchAsync(string searchTerm, int maxResults, CancellationToken cancellationToken)
    {
        var perSiteLimit = Math.Clamp(maxResults, 1, 50);
        var list = new List<GearSignalItem>(_baseUrls.Count * perSiteLimit);
        var queries = GearSearchQueryBuilder.BuildQueries(searchTerm);

        foreach (var baseUrl in _baseUrls)
        {
            cancellationToken.ThrowIfCancellationRequested();

            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var fetchedForSite = 0;

            foreach (var query in queries)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (fetchedForSite >= perSiteLimit)
                    break;

                var remaining = perSiteLimit - fetchedForSite;

                var rssUrl = BuildRssUrl(baseUrl, query);
                try
                {
                    var rss = await _http.GetStringAsync(rssUrl, cancellationToken).ConfigureAwait(false);
                    var parsed = ParseRss(rss, remaining);
                    foreach (var item in parsed)
                    {
                        var key = (item.Url ?? "").Trim();
                        if (key.Length == 0 || !seen.Add(key))
                            continue;
                        list.Add(item);
                        fetchedForSite++;
                        if (fetchedForSite >= perSiteLimit)
                            break;
                    }
                    continue;
                }
                catch
                {
                    // fall back to HTML
                }

                try
                {
                    var htmlUrl = BuildHtmlSearchUrl(baseUrl, query);
                    var html = await _http.GetStringAsync(htmlUrl, cancellationToken).ConfigureAwait(false);
                    var parsed = await ParseHtmlAsync(html, baseUrl, remaining, cancellationToken).ConfigureAwait(false);
                    foreach (var item in parsed)
                    {
                        var key = (item.Url ?? "").Trim();
                        if (key.Length == 0 || !seen.Add(key))
                            continue;
                        list.Add(item);
                        fetchedForSite++;
                        if (fetchedForSite >= perSiteLimit)
                            break;
                    }
                }
                catch
                {
                }
            }
        }

        return list;
    }

    private static IReadOnlyList<GearSignalItem> ParseRss(string rssXml, int limit)
    {
        var doc = XDocument.Parse(rssXml);
        var items = doc.Descendants("item").Take(limit);
        var list = new List<GearSignalItem>(limit);

        foreach (var item in items)
        {
            var title = (item.Element("title")?.Value ?? "").Trim();
            var link = (item.Element("link")?.Value ?? "").Trim();
            var description = (item.Element("description")?.Value ?? "").Trim();
            var pubDate = (item.Element("pubDate")?.Value ?? "").Trim();
            var posted = TryParseDate(pubDate);

            if (string.IsNullOrWhiteSpace(title) && string.IsNullOrWhiteSpace(description))
                continue;

            list.Add(new GearSignalItem(
                platform: "Craigslist",
                buyer: "",
                title: title,
                body: TextSanitizer.ToPlainText(description),
                url: link,
                postedAtUtc: posted
            ));
        }

        return list;
    }

    private async Task<IReadOnlyList<GearSignalItem>> ParseHtmlAsync(string html, string baseUrl, int limit, CancellationToken cancellationToken)
    {
        var matches = ResultLinkRegex().Matches(html);
        var list = new List<GearSignalItem>(Math.Min(limit, matches.Count));

        foreach (Match m in matches)
        {
            if (list.Count >= limit)
                break;

            var href = WebDecode(m.Groups["href"].Value);
            var title = WebDecode(m.Groups["title"].Value);
            var dt = m.Groups["dt"].Value;
            var postedAt = TryParseDate(dt);

            var url = href.StartsWith("http", StringComparison.OrdinalIgnoreCase)
                ? href
                : baseUrl.TrimEnd('/') + "/" + href.TrimStart('/');

            var body = "";
            try
            {
                var postHtml = await _http.GetStringAsync(url, cancellationToken).ConfigureAwait(false);
                body = ExtractPostingBody(postHtml);
            }
            catch
            {
            }

            list.Add(new GearSignalItem(
                platform: "Craigslist",
                buyer: "",
                title: title,
                body: body,
                url: url,
                postedAtUtc: postedAt
            ));
        }

        return list;
    }

    private static string ExtractPostingBody(string postHtml)
    {
        if (string.IsNullOrWhiteSpace(postHtml))
            return "";

        var m = PostingBodyRegex().Match(postHtml);
        if (!m.Success)
            return "";

        var raw = m.Groups["body"].Value;
        raw = raw.Replace("<!--", "", StringComparison.OrdinalIgnoreCase).Replace("-->", "", StringComparison.OrdinalIgnoreCase);
        return TextSanitizer.ToPlainText(raw);
    }

    private static string BuildRssUrl(string baseUrl, string searchTerm)
    {
        var sb = new StringBuilder();
        sb.Append(baseUrl.TrimEnd('/')).Append("/search/waa?format=rss&sort=date");
        if (!string.IsNullOrWhiteSpace(searchTerm))
            sb.Append("&query=").Append(Uri.EscapeDataString(searchTerm.Trim()));
        return sb.ToString();
    }

    private static string BuildHtmlSearchUrl(string baseUrl, string searchTerm)
    {
        var sb = new StringBuilder();
        sb.Append(baseUrl.TrimEnd('/')).Append("/search/waa?sort=date");
        if (!string.IsNullOrWhiteSpace(searchTerm))
            sb.Append("&query=").Append(Uri.EscapeDataString(searchTerm.Trim()));
        return sb.ToString();
    }

    private static DateTimeOffset? TryParseDate(string? value)
    {
        var v = (value ?? "").Trim();
        if (v.Length == 0)
            return null;

        if (DateTimeOffset.TryParse(v, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out var dto))
            return dto.ToUniversalTime();

        if (DateTimeOffset.TryParse(v, out dto))
            return dto.ToUniversalTime();

        return null;
    }

    private static string NormalizeBaseUrl(string? input)
    {
        var s = (input ?? "").Trim();
        if (s.Length == 0)
            return "";

        s = s.TrimEnd('/');
        if (!s.StartsWith("http://", StringComparison.OrdinalIgnoreCase) && !s.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
            s = "https://" + s;

        return s;
    }

    private static string WebDecode(string s)
    {
        try { return System.Net.WebUtility.HtmlDecode(s ?? ""); } catch { return s ?? ""; }
    }

    [GeneratedRegex("<a[^>]+class=\"result-title\\s+hdrlnk\"[^>]+href=\"(?<href>[^\"]+)\"[^>]*>(?<title>.*?)</a>\\s*(?:</span>\\s*)?(?:</p>)?\\s*(?:<time[^>]+datetime=\"(?<dt>[^\"]+)\")?", RegexOptions.IgnoreCase | RegexOptions.Compiled | RegexOptions.Singleline)]
    private static partial Regex ResultLinkRegex();

    [GeneratedRegex("<section[^>]+id=\"postingbody\"[^>]*>(?<body>.*?)</section>", RegexOptions.IgnoreCase | RegexOptions.Compiled | RegexOptions.Singleline)]
    private static partial Regex PostingBodyRegex();
}
