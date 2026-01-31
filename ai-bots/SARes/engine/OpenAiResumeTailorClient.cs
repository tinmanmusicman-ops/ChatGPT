using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace SARes.engine;

public sealed class OpenAiResumeTailorClient
{
    private readonly HttpClient _http;

    public OpenAiResumeTailorClient(string apiKey)
    {
        _http = new HttpClient { Timeout = TimeSpan.FromSeconds(90) };
        _http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", apiKey);
    }

    public async Task<(string TailoredSummary, string TailoredCoreSkills)> TailorSummaryAndSkillsAsync(
        string baseResumeMd,
        string userSummarySeed,
        string jobDescription,
        IReadOnlyList<string> allowedSkills,
        ResumeTailoringMode mode,
        Action<string>? log = null)
    {
        log?.Invoke("Preparing resume-tailoring prompt...");

        var isHeavy = mode == ResumeTailoringMode.Heavy;
        var system =
            "You are an ATS resume editor.\n" +
            "You may ONLY edit the Summary and Core Skills sections.\n" +
            "You MUST NOT invent skills, languages, tools, employers, degrees, certifications, dates, or metrics.\n" +
            "For Core Skills: you MUST use ONLY the provided AllowedSkills list (reorder/group/rephrase minimally, but do not add new items).\n" +
            "For Summary: you may adapt wording to align with the job description, but only using supported facts from the resume.\n" +
            (isHeavy
                ? "Mode: HEAVY. Strongly align Summary wording and prioritize the most relevant allowed skills; aim for higher keyword coverage.\n"
                : "Mode: LIGHT. Make the smallest wording changes needed for alignment; keep original tone and phrasing when possible.\n") +
            "Return ONLY valid JSON with keys: tailoredSummaryMarkdown, tailoredCoreSkillsMarkdown.\n";

        var user = new StringBuilder();
        user.AppendLine("Job description:");
        user.AppendLine(string.IsNullOrWhiteSpace(jobDescription) ? "(none provided)" : jobDescription.Trim());
        user.AppendLine();
        user.AppendLine("Base resume (source of truth; do not invent beyond this):");
        user.AppendLine(baseResumeMd.Trim());
        user.AppendLine();
        user.AppendLine("User summary seed (starting point; may be rewritten, but no new facts):");
        user.AppendLine(userSummarySeed.Trim());
        user.AppendLine();
        user.AppendLine("AllowedSkills (use ONLY these items for Core Skills bullets):");
        foreach (var s in allowedSkills)
            user.AppendLine("- " + s);
        user.AppendLine();
        user.AppendLine("Output JSON schema:");
        user.AppendLine("{\"tailoredSummaryMarkdown\":\"...\",\"tailoredCoreSkillsMarkdown\":\"...\"}");

        var payload = new
        {
            model = "gpt-4.1",
            temperature = isHeavy ? 0.3 : 0.15,
            max_tokens = 1400,
            messages = new[]
            {
                new { role = "system", content = system },
                new { role = "user", content = user.ToString().Trim() }
            }
        };

        var json = JsonSerializer.Serialize(payload);
        using var req = new HttpRequestMessage(HttpMethod.Post, "https://api.openai.com/v1/chat/completions")
        {
            Content = new StringContent(json, Encoding.UTF8, "application/json")
        };

        log?.Invoke("Sending resume-tailoring request to OpenAI...");
        using var resp = await _http.SendAsync(req).ConfigureAwait(false);
        var body = await resp.Content.ReadAsStringAsync().ConfigureAwait(false);
        if (!resp.IsSuccessStatusCode)
            throw new InvalidOperationException($"OpenAI error {(int)resp.StatusCode}: {body}");

        log?.Invoke("Received resume-tailoring response. Parsing...");
        using var doc = JsonDocument.Parse(body);
        var content = doc.RootElement
            .GetProperty("choices")[0]
            .GetProperty("message")
            .GetProperty("content")
            .GetString();

        var text = (content ?? "").Trim();
        if (text.Length == 0)
            throw new InvalidOperationException("AI returned empty content.");

        // Parse returned JSON (best-effort).
        using var outDoc = JsonDocument.Parse(text);
        var root = outDoc.RootElement;
        var summary = root.GetProperty("tailoredSummaryMarkdown").GetString() ?? "";
        var skills = root.GetProperty("tailoredCoreSkillsMarkdown").GetString() ?? "";

        return (summary.Trim(), skills.Trim());
    }
}
