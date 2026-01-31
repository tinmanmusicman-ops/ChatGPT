using System.Text;
using System.Text.RegularExpressions;

namespace SARes.engine;

public static class CoverLetterGenerator
{
    public static async Task<string> GenerateCoverLetterMarkdownAsync(
        string resumeMd,
        string coverLetterBaseMd,
        string jobDescription,
        Action<string>? log = null)
    {
        var resume = (resumeMd ?? "").Trim();
        if (resume.Length == 0)
            throw new ArgumentException("Resume markdown is empty.", nameof(resumeMd));

        var jd = (jobDescription ?? "").Trim();
        var baseMd = (coverLetterBaseMd ?? "").Trim();

        log?.Invoke("Starting cover letter generation...");

        var apiKey = (Environment.GetEnvironmentVariable("OPENAI_API_KEY") ?? "").Trim();
        if (apiKey.Length == 0)
        {
            log?.Invoke("OPENAI_API_KEY not set; using non-AI cover letter.");
            return GenerateSourceOnlyCoverLetter(resume, jd);
        }

        // Only skip AI when the job description is empty.
        if (jd.Length == 0)
        {
            log?.Invoke("Job description is empty; using non-AI cover letter.");
            return GenerateSourceOnlyCoverLetter(resume, jd);
        }

        try
        {
            // Do not pre-parse company/role for gating; let the model use the job description as the source.
            // (Still no guessing: if not explicitly present in the job description, it must stay generic.)
            var target = new TargetInfo(CompanyName: "", RoleTitle: "", Context: "");
            log?.Invoke("Using AI (job description provided).");

            var client = new OpenAiCoverLetterClient(apiKey);
            var md = await client.DraftCoverLetterAsync(resume, baseMd, jd, target, log).ConfigureAwait(false);
            if (md.Length == 0)
            {
                log?.Invoke("AI returned empty content; falling back to non-AI cover letter.");
                return GenerateSourceOnlyCoverLetter(resume, jd);
            }

            AuditCoverLetterOrThrow(resume, jd, md);
            log?.Invoke("AI cover letter passed audit.");
            return md;
        }
        catch (Exception ex)
        {
            log?.Invoke("AI generation failed; falling back. Error: " + ex.Message);
            return GenerateSourceOnlyCoverLetter(resume, jd);
        }
    }

    private static TargetInfo? TryExtractTargetInfo(string jobDescription)
    {
        var jd = (jobDescription ?? "").Trim();
        if (jd.Length == 0)
            return null;

        string? company = null;
        string? role = null;
        var expectingCompanyValue = false;
        var expectingRoleValue = false;
        var expectingRoleFromJobDescriptionLine = false;

        foreach (var raw in jd.Split('\n'))
        {
            var line = raw.Trim();
            if (line.Length == 0)
                continue;

            // If user typed "Company:" on its own line, take the next non-empty line as the value.
            if (expectingCompanyValue && company is null)
            {
                if (!LooksLikeLabeledField(line))
                    company = line.Trim();
                expectingCompanyValue = false;
                continue;
            }

            if (expectingRoleValue && role is null)
            {
                if (!LooksLikeLabeledField(line))
                    role = line.Trim();
                expectingRoleValue = false;
                continue;
            }

            if (expectingRoleFromJobDescriptionLine && role is null)
            {
                // If they provided a short one-liner JD like "gardener", treat it as role title.
                if (line.Length <= 80)
                    role = line.Trim();
                expectingRoleFromJobDescriptionLine = false;
                continue;
            }

            if (company is null)
            {
                var v = TryExtractLabeledValueAllowEmpty(line, "Company", "Company Name", "Employer");
                if (v is not null)
                {
                    if (v.Length > 0) company = v;
                    else expectingCompanyValue = true;
                    continue;
                }
            }

            if (role is null)
            {
                var v = TryExtractLabeledValueAllowEmpty(line, "Role", "Title", "Position", "Job Title");
                if (v is not null)
                {
                    if (v.Length > 0) role = v;
                    else expectingRoleValue = true;
                    continue;
                }
            }

            // If they wrote "Job Description:" and then a one-line role, use it.
            if (line.StartsWith("Job Description:", StringComparison.OrdinalIgnoreCase))
            {
                var v = line.Substring("Job Description:".Length).Trim();
                if (role is null && v.Length > 0 && v.Length <= 80)
                    role = v;
                else if (role is null)
                    expectingRoleFromJobDescriptionLine = true;
                continue;
            }

            if (company is not null && role is not null)
                break;
        }

        return new TargetInfo((company ?? "").Trim(), (role ?? "").Trim(), Context: "");
    }

    private static string? TryExtractLabeledValueAllowEmpty(string line, params string[] labels)
    {
        foreach (var label in labels)
        {
            var prefix = label + ":";
            if (line.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                var value = line.Substring(prefix.Length).Trim();
                return value; // can be empty; caller decides whether to read next line
            }
        }
        return null;
    }

    private static bool LooksLikeLabeledField(string line)
    {
        var t = (line ?? "").Trim();
        if (t.Length == 0)
            return false;

        // If it contains a ":" early, assume it's a label-like line.
        var idx = t.IndexOf(':', StringComparison.Ordinal);
        return idx >= 1 && idx <= 20;
    }

    private static string GenerateSourceOnlyCoverLetter(string resumeMd, string jobDescription)
    {
        var name = ExtractName(resumeMd);
        var bullets = ExtractTopBullets(resumeMd, maxBullets: 5);

        var sb = new StringBuilder();
        sb.AppendLine("# Dear Hiring Manager,");
        sb.AppendLine();
        if (!string.IsNullOrWhiteSpace(jobDescription))
        {
            sb.AppendLine("I’m applying for this role and believe it aligns with my background and the needs described in the job posting. Below are a few highlights from my resume that map well to the work.");
        }
        else
        {
            sb.AppendLine("I’m applying for this role and believe it aligns with my background. Below are a few highlights from my resume that are relevant to the work.");
        }
        sb.AppendLine();

        foreach (var b in bullets)
            sb.AppendLine($"- {b}");

        sb.AppendLine();
        sb.AppendLine("Thank you for your time and consideration.");
        sb.AppendLine();
        sb.AppendLine("Sincerely,");
        sb.AppendLine(name);
        return sb.ToString();
    }

    private static void AuditCoverLetterOrThrow(string resumeMd, string jobDescription, string coverLetterMd)
    {
        // Guardrail: no new numbers/metrics not present in the resume OR job description.
        // (Numbers in the job description may be part of tool names like "Office 365".)
        var allowedNumbers = new HashSet<string>(ExtractNumbers(resumeMd));
        foreach (var n in ExtractNumbers(jobDescription ?? ""))
            allowedNumbers.Add(n);
        var coverNumbers = ExtractNumbers(coverLetterMd);
        foreach (var n in coverNumbers)
        {
            if (!allowedNumbers.Contains(n))
                throw new InvalidOperationException($"Cover letter introduced an unsupported number/metric: {n}");
        }

        // Guardrail: do not claim new employment relationships.
        var lowerResume = resumeMd.ToLowerInvariant();
        var employerPatterns = new[]
        {
            // Only flag employment claims (not simply applying to a company).
            new Regex(@"\bworked\s+at\s+([A-Z][A-Za-z0-9&.,' -]{2,80})", RegexOptions.Compiled),
            new Regex(@"\bemployed\s+at\s+([A-Z][A-Za-z0-9&.,' -]{2,80})", RegexOptions.Compiled),
        };

        foreach (var rx in employerPatterns)
        {
            foreach (Match m in rx.Matches(coverLetterMd))
            {
                var phrase = (m.Groups[1].Value ?? "").Trim().Trim(',', '.', ' ');
                if (phrase.Length == 0)
                    continue;
                if (!lowerResume.Contains(phrase.ToLowerInvariant()))
                    throw new InvalidOperationException($"Cover letter referenced an unsupported employer: {phrase}");
            }
        }
    }

    private static IEnumerable<string> ExtractNumbers(string text)
    {
        foreach (Match m in Regex.Matches(text ?? "", @"(?<!\w)[#]?\d+(?:[.,]\d+)?%?(?!\w)"))
            yield return m.Value;
    }

    private static string ExtractName(string resumeMd)
    {
        foreach (var line in (resumeMd ?? "").Split('\n'))
        {
            var trimmed = line.Trim();
            if (trimmed.StartsWith("# ", StringComparison.Ordinal))
            {
                var name = trimmed.Substring(2).Trim();
                if (name.Length > 0)
                    return name;
            }
        }
        return "Your Name";
    }

    private static IReadOnlyList<string> ExtractTopBullets(string resumeMd, int maxBullets)
    {
        var bullets = new List<string>();
        foreach (var line in (resumeMd ?? "").Split('\n'))
        {
            var t = line.TrimStart();
            if (!t.StartsWith("- ", StringComparison.Ordinal))
                continue;
            var bullet = t.Substring(2).Trim();
            if (bullet.Length == 0)
                continue;
            bullets.Add(bullet);
            if (bullets.Count >= maxBullets)
                break;
        }
        return bullets;
    }
}

public readonly record struct TargetInfo(string CompanyName, string RoleTitle, string Context);
