using System.Net.Http;
using System.Text.Json;
using PainRadar.Models;

namespace PainRadar.Services;

public sealed class RemoteOkJobSource : IJobSource
{
    private readonly HttpClient _http;

    public RemoteOkJobSource(HttpClient http) => _http = http;

    public string SourceName => "RemoteOK";

    public async Task<IReadOnlyList<SignalItem>> FetchAsync(string searchTerm, int maxResults, CancellationToken cancellationToken)
    {
        using var resp = await _http.GetAsync("https://remoteok.com/api", cancellationToken).ConfigureAwait(false);
        resp.EnsureSuccessStatusCode();

        await using var stream = await resp.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken).ConfigureAwait(false);

        if (doc.RootElement.ValueKind != JsonValueKind.Array)
            return Array.Empty<SignalItem>();

        var list = new List<SignalItem>(maxResults);
        foreach (var item in doc.RootElement.EnumerateArray())
        {
            if (list.Count >= maxResults)
                break;

            if (item.TryGetProperty("legal", out _))
                continue;

            var title = item.TryGetProperty("position", out var eTitle) ? eTitle.GetString() ?? "" : "";
            var company = item.TryGetProperty("company", out var eCompany) ? eCompany.GetString() ?? "" : "";
            var location = item.TryGetProperty("location", out var eLoc) ? eLoc.GetString() ?? "" : "";
            var jobUrl = item.TryGetProperty("url", out var eUrl) ? eUrl.GetString() ?? "" : "";
            var desc = item.TryGetProperty("description", out var eDesc) ? eDesc.GetString() ?? "" : "";

            title = title.Trim();
            company = company.Trim();
            jobUrl = jobUrl.Trim();
            if (string.IsNullOrWhiteSpace(company) || string.IsNullOrWhiteSpace(title) || string.IsNullOrWhiteSpace(jobUrl))
                continue;

            if (!string.IsNullOrWhiteSpace(searchTerm))
            {
                var s = searchTerm.Trim();
                if (!title.Contains(s, StringComparison.OrdinalIgnoreCase) &&
                    !company.Contains(s, StringComparison.OrdinalIgnoreCase) &&
                    !desc.Contains(s, StringComparison.OrdinalIgnoreCase))
                    continue;
            }

            list.Add(new SignalItem(
                company: company,
                jobTitle: title,
                location: location.Trim(),
                source: SourceName,
                jobUrl: jobUrl,
                description: TextSanitizer.ToPlainText(desc)
            ));
        }

        return list;
    }
}
