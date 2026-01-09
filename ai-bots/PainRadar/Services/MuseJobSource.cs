using System.Net.Http;
using System.Text.Json;
using PainRadar.Models;

namespace PainRadar.Services;

public sealed class MuseJobSource : IJobSource
{
    private readonly HttpClient _http;

    public MuseJobSource(HttpClient http) => _http = http;

    public string SourceName => "TheMuse";

    public async Task<IReadOnlyList<SignalItem>> FetchAsync(string searchTerm, int maxResults, CancellationToken cancellationToken)
    {
        var results = new List<SignalItem>(maxResults);
        var page = 1;

        while (results.Count < maxResults && page <= 10)
        {
            var url = $"https://www.themuse.com/api/public/jobs?page={page}";
            using var resp = await _http.GetAsync(url, cancellationToken).ConfigureAwait(false);
            resp.EnsureSuccessStatusCode();

            await using var stream = await resp.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
            using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken).ConfigureAwait(false);

            if (!doc.RootElement.TryGetProperty("results", out var arr) || arr.ValueKind != JsonValueKind.Array)
                break;

            foreach (var j in arr.EnumerateArray())
            {
                if (results.Count >= maxResults)
                    break;

                var title = j.TryGetProperty("name", out var eTitle) ? eTitle.GetString() ?? "" : "";
                var jobUrl = "";
                if (j.TryGetProperty("refs", out var refs) && refs.ValueKind == JsonValueKind.Object &&
                    refs.TryGetProperty("landing_page", out var eUrl))
                    jobUrl = eUrl.GetString() ?? "";

                var company = "";
                if (j.TryGetProperty("company", out var comp) && comp.ValueKind == JsonValueKind.Object &&
                    comp.TryGetProperty("name", out var eCompany))
                    company = eCompany.GetString() ?? "";

                var location = "";
                if (j.TryGetProperty("locations", out var locs) && locs.ValueKind == JsonValueKind.Array)
                {
                    foreach (var l in locs.EnumerateArray())
                    {
                        if (l.ValueKind == JsonValueKind.Object && l.TryGetProperty("name", out var eLoc))
                        {
                            location = eLoc.GetString() ?? "";
                            break;
                        }
                    }
                }

                var contents = j.TryGetProperty("contents", out var eContents) ? eContents.GetString() ?? "" : "";

                title = title.Trim();
                company = company.Trim();
                jobUrl = jobUrl.Trim();
                if (string.IsNullOrWhiteSpace(company) || string.IsNullOrWhiteSpace(title) || string.IsNullOrWhiteSpace(jobUrl))
                    continue;

                var plain = TextSanitizer.ToPlainText(contents);
                if (!string.IsNullOrWhiteSpace(searchTerm))
                {
                    var s = searchTerm.Trim();
                    if (!title.Contains(s, StringComparison.OrdinalIgnoreCase) &&
                        !company.Contains(s, StringComparison.OrdinalIgnoreCase) &&
                        !plain.Contains(s, StringComparison.OrdinalIgnoreCase))
                        continue;
                }

                results.Add(new SignalItem(
                    company: company,
                    jobTitle: title,
                    location: location.Trim(),
                    source: SourceName,
                    jobUrl: jobUrl,
                    description: plain
                ));
            }

            page++;
        }

        return results;
    }
}
