using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace SARes.engine;

public static class ResumeSkillsLexicon
{
    public static IReadOnlyList<string> ExtractAllowedSkills(string resumeMarkdown)
    {
        var skillsBody = ResumeSectionEditor.ExtractSectionBody(resumeMarkdown ?? "", ResumeSectionEditor.IsCoreSkillsHeader);
        if (string.IsNullOrWhiteSpace(skillsBody))
            return Array.Empty<string>();

        var rawItems = new List<string>();
        foreach (var line in skillsBody.Split('\n'))
        {
            var t = (line ?? "").Trim();
            if (t.Length == 0)
                continue;

            if (t.StartsWith("- ", StringComparison.Ordinal))
                t = t.Substring(2).Trim();
            else if (t.StartsWith("* ", StringComparison.Ordinal))
                t = t.Substring(2).Trim();

            if (t.Length == 0)
                continue;

            rawItems.AddRange(SplitSkillLine(t));
        }

        // Normalize + de-dup.
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var output = new List<string>();
        foreach (var item in rawItems.Select(NormalizeSkill))
        {
            if (item.Length == 0)
                continue;
            if (seen.Add(item))
                output.Add(item);
        }

        return output;
    }

    public static bool SkillsAreSubset(IEnumerable<string> proposed, IReadOnlyList<string> allowed, out string? firstInvalid)
    {
        var allowedSet = new HashSet<string>(allowed.Select(NormalizeSkill), StringComparer.OrdinalIgnoreCase);
        foreach (var p in proposed)
        {
            var n = NormalizeSkill(p);
            if (n.Length == 0)
                continue;
            if (!allowedSet.Contains(n))
            {
                firstInvalid = p;
                return false;
            }
        }

        firstInvalid = null;
        return true;
    }

    public static IReadOnlyList<string> ParseBulletItems(string markdownBody)
    {
        var items = new List<string>();
        foreach (var line in (markdownBody ?? "").Split('\n'))
        {
            var t = (line ?? "").Trim();
            if (t.StartsWith("- ", StringComparison.Ordinal))
            {
                var item = t.Substring(2).Trim();
                if (item.Length > 0)
                    items.Add(item);
            }
        }
        return items;
    }

    public static string NormalizeToBulletList(string markdownBody)
    {
        var lines = (markdownBody ?? "").Replace("\r\n", "\n").Replace("\r", "\n").Split('\n').ToList();
        var output = new List<string>();

        foreach (var raw in lines)
        {
            var t = (raw ?? "").Trim();
            if (t.Length == 0)
                continue;

            if (t.StartsWith("- ", StringComparison.Ordinal))
                output.Add(t);
            else
                output.Add("- " + t);
        }

        return string.Join("\n", output).Trim();
    }

    private static IEnumerable<string> SplitSkillLine(string line)
    {
        // Split common “combo” bullets like "Git/GitHub" or "OpenAI Codex, Genesys, ServiceNow".
        var t = (line ?? "").Trim();
        if (t.Length == 0)
            yield break;

        // Keep parenthetical chunks intact.
        foreach (var part in Regex.Split(t, @"\s*(?:,|;|\||\u2022)\s*"))
        {
            var p = part.Trim();
            if (p.Length == 0)
                continue;

            // Split "A / B" into A and B.
            if (p.Contains(" / ", StringComparison.Ordinal))
            {
                foreach (var sub in p.Split(new[] { " / " }, StringSplitOptions.RemoveEmptyEntries))
                {
                    var s = sub.Trim();
                    if (s.Length > 0)
                        yield return s;
                }
                continue;
            }

            // Split simple "A/B" into A and B, but preserve things like "CI/CD".
            if (p.Count(c => c == '/') == 1 && !p.Contains("CI/CD", StringComparison.OrdinalIgnoreCase))
            {
                var subs = p.Split('/');
                if (subs.Length == 2)
                {
                    var a = subs[0].Trim();
                    var b = subs[1].Trim();
                    if (a.Length > 0) yield return a;
                    if (b.Length > 0) yield return b;
                    continue;
                }
            }

            yield return p;
        }
    }

    private static string NormalizeSkill(string s)
    {
        var t = (s ?? "").Trim();
        t = t.TrimEnd('.');
        t = Regex.Replace(t, @"\s+", " ");
        return t;
    }
}

