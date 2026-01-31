using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace SARes.engine;

public sealed class OpenAiCoverLetterClient
{
    private readonly HttpClient _http;

    public OpenAiCoverLetterClient(string apiKey)
    {
        _http = new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(60)
        };
        _http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", apiKey);
    }

    public async Task<string> DraftCoverLetterAsync(string resumeMd, string coverLetterBaseMd, string jobDescription, TargetInfo target, Action<string>? log = null)
    {
        // Mirrors the SARES (Python) prompt style: strict source-grounding and explicit constraints.
        log?.Invoke("Preparing prompt...");

        var system =
            "Write a targeted cover letter using ONLY supported facts from the resume.\n" +
            "You may reference the target company/role/mission/needs from the job description.\n" +
            "Do NOT invent experience; if not explicitly in the resume, frame as alignment, interest, or capability.\n" +
            "If the job description does not explicitly provide the company name and/or role title, do NOT guess; write generically for \"this role\".\n" +
            "Output Markdown only (no code fences).\n";

        var baseBlock = string.IsNullOrWhiteSpace(coverLetterBaseMd)
            ? ""
            : $"\n\nCover letter base (optional template):\n{coverLetterBaseMd}\n";

        var user = new StringBuilder();
        user.AppendLine("Job description:");
        user.AppendLine(string.IsNullOrWhiteSpace(jobDescription) ? "(none provided)" : jobDescription);
        user.AppendLine();
        user.AppendLine("Resume (source of truth):");
        user.AppendLine(resumeMd);
        user.AppendLine(baseBlock);
        user.AppendLine("Requirements:");
        user.AppendLine("- Start with: \"# Dear Hiring Manager,\"");
        user.AppendLine("- If the job description explicitly identifies the company name and/or role title, name them in the first paragraph.");
        user.AppendLine("- If the job description does not explicitly identify company/role, do not guess; write generically for this role.");
        user.AppendLine("- Use alignment phrasing like \"aligned with my background in...\" / \"drawing on my experience with...\" / \"this role complements my work in...\".");
        user.AppendLine("- 3-5 short paragraphs, then \"Sincerely,\" and the name.");
        user.AppendLine("- Do NOT add numbers/metrics not present in the resume or job description.");

        var payload = new
        {
            model = "gpt-4.1",
            temperature = 0.2,
            max_tokens = 1200,
            messages = new[]
            {
                new { role = "system", content = system },
                new { role = "user", content = user.ToString().Trim() }
            }
        };

        var json = JsonSerializer.Serialize(payload);
        log?.Invoke("Sending request to OpenAI...");
        using var req = new HttpRequestMessage(HttpMethod.Post, "https://api.openai.com/v1/chat/completions")
        {
            Content = new StringContent(json, Encoding.UTF8, "application/json")
        };

        using var resp = await _http.SendAsync(req).ConfigureAwait(false);
        var body = await resp.Content.ReadAsStringAsync().ConfigureAwait(false);
        if (!resp.IsSuccessStatusCode)
            throw new InvalidOperationException($"OpenAI error {(int)resp.StatusCode}: {body}");

        log?.Invoke("Received response. Parsing...");
        using var doc = JsonDocument.Parse(body);
        var content = doc.RootElement
            .GetProperty("choices")[0]
            .GetProperty("message")
            .GetProperty("content")
            .GetString();

        log?.Invoke("Done.");
        return (content ?? "").Trim();
    }
}
