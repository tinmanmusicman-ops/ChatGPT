using System.Text.RegularExpressions;

namespace SARes.engine;

public static class ResumeTailorGenerator
{
    private static readonly string[] CommonLanguages =
    [
        "spanish", "french", "german", "italian", "portuguese", "russian",
        "mandarin", "cantonese", "japanese", "korean", "arabic", "hindi"
    ];

    public static async Task<(string TailoredResumeMd, bool UsedAi)> TailorResumeAsync(
        string baseResumeMd,
        string userSummarySeed,
        string jobDescription,
        ResumeTailoringMode mode,
        Action<string>? log = null)
    {
        var apiKey = (Environment.GetEnvironmentVariable("OPENAI_API_KEY") ?? "").Trim();
        if (apiKey.Length == 0)
            return (baseResumeMd, false);

        var jd = (jobDescription ?? "").Trim();
        if (jd.Length == 0)
            return (baseResumeMd, false);

        if (mode == ResumeTailoringMode.CoverLetterOnly)
            return (baseResumeMd, false);

        var allowedSkills = ResumeSkillsLexicon.ExtractAllowedSkills(baseResumeMd);
        if (allowedSkills.Count == 0)
        {
            log?.Invoke("No Core Skills section found; skipping resume AI tailoring.");
            return (baseResumeMd, false);
        }

        log?.Invoke(mode == ResumeTailoringMode.Heavy
            ? "Tailoring resume (HEAVY: Summary + Core Skills)..."
            : "Tailoring resume (LIGHT: Summary + Core Skills)...");
        var client = new OpenAiResumeTailorClient(apiKey);
        var (tailoredSummary, tailoredSkillsRaw) = await client.TailorSummaryAndSkillsAsync(
            baseResumeMd: baseResumeMd,
            userSummarySeed: userSummarySeed,
            jobDescription: jd,
            allowedSkills: allowedSkills,
            mode: mode,
            log: log).ConfigureAwait(false);

        // Normalize skills to bullets.
        var tailoredSkills = ResumeSkillsLexicon.NormalizeToBulletList(tailoredSkillsRaw);
        var proposedSkillItems = ResumeSkillsLexicon.ParseBulletItems(tailoredSkills);

        if (!ResumeSkillsLexicon.SkillsAreSubset(proposedSkillItems, allowedSkills, out var invalid))
        {
            log?.Invoke($"AI tried to add an unsupported skill: {invalid}. Keeping original Core Skills.");
            tailoredSkills = ResumeSectionEditor.ExtractSectionBody(baseResumeMd, ResumeSectionEditor.IsCoreSkillsHeader);
            tailoredSkills = ResumeSkillsLexicon.NormalizeToBulletList(tailoredSkills);
        }

        // Guardrail: don't introduce languages that aren't in the resume.
        var baseLower = (baseResumeMd ?? "").ToLowerInvariant();
        foreach (var lang in CommonLanguages)
        {
            if (tailoredSummary.Contains(lang, StringComparison.OrdinalIgnoreCase) && !baseLower.Contains(lang))
                throw new InvalidOperationException($"AI introduced unsupported language: {lang}");
        }

        // Guardrail: no new numbers/metrics not present in the resume.
        EnforceNoNewNumbers(baseResumeMd ?? "", tailoredSummary);

        // Apply to resume (only Summary + Core Skills).
        var updated = ResumeAssembler.InjectSummary(baseResumeMd ?? "", tailoredSummary);
        updated = ResumeSectionEditor.ReplaceSectionBody(updated, ResumeSectionEditor.IsCoreSkillsHeader, tailoredSkills);

        return (updated, true);
    }

    private static void EnforceNoNewNumbers(string resumeMd, string newSummaryMd)
    {
        var resumeNumbers = new HashSet<string>(ExtractNumbers(resumeMd));
        foreach (var n in ExtractNumbers(newSummaryMd))
        {
            if (!resumeNumbers.Contains(n))
                throw new InvalidOperationException($"Tailored summary introduced an unsupported number/metric: {n}");
        }
    }

    private static IEnumerable<string> ExtractNumbers(string text)
    {
        foreach (Match m in Regex.Matches(text ?? "", @"(?<!\w)[#]?\d+(?:[.,]\d+)?%?(?!\w)"))
            yield return m.Value;
    }
}
