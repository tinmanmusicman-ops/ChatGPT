using System;
using System.Globalization;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace DiskInsight;

internal sealed class EiCommentaryService : IEiCommentaryService, IDisposable
{
    private readonly HttpClient _httpClient = new();

    public void Dispose() => _httpClient.Dispose();

    public async Task<string> GetCommentaryAsync(EiCommentaryRequest request, CancellationToken cancellationToken)
    {
        if (request is null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        if (!EiRuntimeConfiguration.TryGet(out var endpoint, out var apiKey, out var error))
        {
            throw new InvalidOperationException(error);
        }

        var prompt = BuildPrompt(request);
        using var httpRequest = new HttpRequestMessage(HttpMethod.Post, endpoint);
        httpRequest.Headers.Authorization = new AuthenticationHeaderValue("Bearer", apiKey);

        var payload = CreatePayload(endpoint, prompt, request);

        httpRequest.Content = new StringContent(payload, Encoding.UTF8, "application/json");
        using var response = await _httpClient.SendAsync(httpRequest, cancellationToken).ConfigureAwait(false);
        var body = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);

        if (!response.IsSuccessStatusCode)
        {
            throw new HttpRequestException($"EI request failed ({(int)response.StatusCode} {response.ReasonPhrase}).\r\n\r\n{body}");
        }

        var text = TryExtractTextFromJson(body);
        return string.IsNullOrWhiteSpace(text) ? body : text;
    }

    // Endpoint/key resolution is handled by EiRuntimeConfiguration.
    private static string CreatePayload(Uri endpoint, string prompt, EiCommentaryRequest request)
    {
        if (string.Equals(endpoint.Host, "api.openai.com", StringComparison.OrdinalIgnoreCase) &&
            endpoint.AbsolutePath.EndsWith("/v1/chat/completions", StringComparison.OrdinalIgnoreCase))
        {
            var model = Environment.GetEnvironmentVariable("DISKINSIGHT_EI_MODEL") ?? "gpt-4o-mini";
            return JsonSerializer.Serialize(new
            {
                model,
                temperature = 0.2,
                messages = new object[]
                {
                    new { role = "user", content = prompt }
                }
            });
        }

        return JsonSerializer.Serialize(new
        {
            prompt,
            data = new
            {
                request.TargetType,
                request.TargetName,
                request.InstanceCount,
                request.FileCount,
                request.FolderCount,
                TotalWorkingSetMb = request.TotalWorkingSetMb is { } ws ? ws.ToString("0.00", CultureInfo.InvariantCulture) : "n/a",
                TotalSizeMb = request.TotalSizeMb is { } size ? size.ToString("0.00", CultureInfo.InvariantCulture) : "n/a",
                request.ContextHint,
                request.LocationHints,
                request.BrandHints,
                request.AssociatedApplications,
                TotalCpuTime = request.TotalCpuTime is { } cpu ? FormatCpuTime(cpu) : "n/a",
                StartTimeEarliest = request.StartTimeEarliest?.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture) ?? "n/a",
                StartTimeLatest = request.StartTimeLatest?.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture) ?? "n/a",
                request.OsVersion,
            }
        });
    }

    private static string BuildPrompt(EiCommentaryRequest request)
    {
        var sb = new StringBuilder(2048);

        sb.AppendLine("Provide EI Commentary (Advisory Only).");
        sb.AppendLine("Output format: Markdown (no code fences).");
        sb.AppendLine("Strict constraints:");
        sb.AppendLine("- No commands, no step-by-step instructions, no process-kill/suspend advice.");
        sb.AppendLine("- No security advice or threat guidance.");
        sb.AppendLine("- Commentary only: what the process typically does, whether the observed behavior is common/expected, and general considerations (not instructions).");
        sb.AppendLine("- Use short headings and bullet points for readability.");
        sb.AppendLine("- Do not give instructions for changing settings, defaults, or file associations.");
        sb.AppendLine();
        sb.AppendLine("Observed data (privacy-limited):");
        sb.AppendLine("(Note: some fields may be 'n/a' due to OS access limits.)");
        sb.AppendLine($"- TargetType: {request.TargetType}");
        sb.AppendLine($"- TargetName: {request.TargetName}");
        if (!string.IsNullOrWhiteSpace(request.ContextHint))
        {
            sb.AppendLine($"- ContextHint: {request.ContextHint}");
        }
        if (request.LocationHints is { Length: > 0 })
        {
            sb.AppendLine("- LocationHints:");
            foreach (var hint in request.LocationHints)
            {
                if (!string.IsNullOrWhiteSpace(hint))
                {
                    sb.AppendLine($"  - {hint}");
                }
            }
        }
        if (request.BrandHints is { Length: > 0 })
        {
            sb.AppendLine("- BrandHints:");
            foreach (var hint in request.BrandHints)
            {
                if (!string.IsNullOrWhiteSpace(hint))
                {
                    sb.AppendLine($"  - {hint}");
                }
            }
        }
        if (request.AssociatedApplications is { Length: > 0 })
        {
            sb.AppendLine("- AssociatedApplications:");
            foreach (var app in request.AssociatedApplications)
            {
                if (!string.IsNullOrWhiteSpace(app))
                {
                    sb.AppendLine($"  - {app}");
                }
            }
        }
        if (request.InstanceCount is { } count)
        {
            sb.AppendLine($"- InstanceCount: {count.ToString(CultureInfo.InvariantCulture)}");
        }
        if (request.FileCount is { } files)
        {
            sb.AppendLine($"- FileCount: {files.ToString(CultureInfo.InvariantCulture)}");
        }
        if (request.FolderCount is { } folders)
        {
            sb.AppendLine($"- FolderCount: {folders.ToString(CultureInfo.InvariantCulture)}");
        }
        sb.AppendLine($"- TotalWorkingSetMb: {(request.TotalWorkingSetMb is { } ws ? ws.ToString("0.00", CultureInfo.InvariantCulture) : "n/a")}");
        sb.AppendLine($"- TotalSizeMb: {(request.TotalSizeMb is { } size ? size.ToString("0.00", CultureInfo.InvariantCulture) : "n/a")}");
        sb.AppendLine($"- TotalCpuTime: {(request.TotalCpuTime is { } cpu ? FormatCpuTime(cpu) : "n/a")}");

        if (request.StartTimeEarliest is not null || request.StartTimeLatest is not null)
        {
            sb.AppendLine($"- StartTimeEarliest: {request.StartTimeEarliest?.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture) ?? "n/a"}");
            sb.AppendLine($"- StartTimeLatest: {request.StartTimeLatest?.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture) ?? "n/a"}");
        }

        if (!string.IsNullOrWhiteSpace(request.OsVersion))
        {
            sb.AppendLine($"- OSVersion: {request.OsVersion}");
        }

        sb.AppendLine();
        sb.AppendLine("Requested commentary:");
        if (string.Equals(request.TargetType, "FileExtensionGroup", StringComparison.OrdinalIgnoreCase))
        {
            sb.AppendLine("- Briefly describe what this file extension is typically used for.");
            sb.AppendLine("- Using the provided AssociatedApplications/ProgIDs (from the registry) and LocationHints, identify the most likely application(s) that use these files on this system.");
            sb.AppendLine("- If BrandHints indicate a specific vendor/product (example: 'Celemony', 'Melodyne'), treat this as a vendor-specific format and focus on that product's usage of the files.");
            sb.AppendLine("- List common Windows applications associated with this extension (app names).");
            sb.AppendLine("- List common Windows process names you might see when opening/using these files (e.g., app executables), noting this depends on user file associations.");
            sb.AppendLine("- If the provided LocationHints / AssociatedApplications strongly suggest a specific product (example: a folder named 'Melodyne'), focus the commentary on how that product typically uses this file type.");
            sb.AppendLine("- Include a section titled 'Most Likely Vendor/Product (on this system)' and explicitly name the vendor/product when BrandHints contain recognizable names (do not use vague phrases like 'a proprietary tool' when names are present).");
            sb.AppendLine("- In that section, briefly cite which hint(s) drove the conclusion (BrandHints, AssociatedApplications, LocationHints).");
            sb.AppendLine("- Comment on whether the observed file count/size distribution is common for typical usage (no recommendations).");
        }
        else
        {
            sb.AppendLine("- What this process typically does.");
            sb.AppendLine("- Whether the observed behavior is common/expected given the data.");
            sb.AppendLine("- General considerations (not instructions).");
        }

        return sb.ToString();
    }

    private static string? TryExtractTextFromJson(string body)
    {
        try
        {
            using var doc = JsonDocument.Parse(body);
            if (doc.RootElement.ValueKind != JsonValueKind.Object)
            {
                return null;
            }

            if (doc.RootElement.TryGetProperty("commentary", out var commentary) && commentary.ValueKind == JsonValueKind.String)
            {
                return commentary.GetString();
            }

            if (doc.RootElement.TryGetProperty("choices", out var choices) &&
                choices.ValueKind == JsonValueKind.Array &&
                choices.GetArrayLength() > 0)
            {
                var first = choices[0];
                if (first.ValueKind == JsonValueKind.Object &&
                    first.TryGetProperty("message", out var message) &&
                    message.ValueKind == JsonValueKind.Object &&
                    message.TryGetProperty("content", out var content) &&
                    content.ValueKind == JsonValueKind.String)
                {
                    return content.GetString();
                }
            }

            if (doc.RootElement.TryGetProperty("text", out var text) && text.ValueKind == JsonValueKind.String)
            {
                return text.GetString();
            }

            if (doc.RootElement.TryGetProperty("output_text", out var outputText) && outputText.ValueKind == JsonValueKind.String)
            {
                return outputText.GetString();
            }

            return null;
        }
        catch
        {
            return null;
        }
    }

    private static string FormatCpuTime(TimeSpan time)
    {
        if (time.TotalDays >= 1)
        {
            var days = ((int)time.TotalDays).ToString(CultureInfo.InvariantCulture);
            return $"{days}.{time:hh\\:mm\\:ss}";
        }

        return time.ToString("hh\\:mm\\:ss", CultureInfo.InvariantCulture);
    }
}
