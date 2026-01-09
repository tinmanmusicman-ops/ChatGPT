using System.Net.Http;
using System.Text.Json;
using PainRadar.Models;

namespace PainRadar.Services;

public sealed class RemotiveJobSource : IJobSource
{
    private readonly HttpClient _http;

    public RemotiveJobSource(HttpClient http) => _http = http;

    public string SourceName => "Remotive";

    public async Task<IReadOnlyList<SignalItem>> FetchAsync(string searchTerm, int maxResults, CancellationToken cancellationToken)
    {
        var url = "https://remotive.com/api/remote-jobs";
        if (!string.IsNullOrWhiteSpace(searchTerm))
            url += "?search=" + Uri.EscapeDataString(searchTerm.Trim());

        using var resp = await _http.GetAsync(url, cancellationToken).ConfigureAwait(false);
        resp.EnsureSuccessStatusCode();

        await using var stream = await resp.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken).ConfigureAwait(false);

        if (!doc.RootElement.TryGetProperty("jobs", out var jobs) || jobs.ValueKind != JsonValueKind.Array)
            return Array.Empty<SignalItem>();

        var list = new List<SignalItem>(Math.Min(maxResults, jobs.GetArrayLength()));
        foreach (var j in jobs.EnumerateArray())
        {
            if (list.Count >= maxResults)
                break;

            var title = j.TryGetProperty("title", out var eTitle) ? eTitle.GetString() ?? "" : "";
            var company = j.TryGetProperty("company_name", out var eCompany) ? eCompany.GetString() ?? "" : "";
            var location = j.TryGetProperty("candidate_required_location", out var eLoc) ? eLoc.GetString() ?? "" : "";
            var jobUrl = j.TryGetProperty("url", out var eUrl) ? eUrl.GetString() ?? "" : "";
            var desc = j.TryGetProperty("description", out var eDesc) ? eDesc.GetString() ?? "" : "";

            title = title.Trim();
            company = company.Trim();
            jobUrl = jobUrl.Trim();
            if (string.IsNullOrWhiteSpace(company) || string.IsNullOrWhiteSpace(title) || string.IsNullOrWhiteSpace(jobUrl))
                continue;

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
