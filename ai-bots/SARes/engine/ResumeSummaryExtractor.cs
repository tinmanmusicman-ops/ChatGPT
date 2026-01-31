using System;
using System.Collections.Generic;
using System.Linq;

namespace SARes.engine;

public static class ResumeSummaryExtractor
{
    public static string ExtractSummary(string resumeMarkdown)
    {
        var md = NormalizeNewlines(resumeMarkdown ?? "");
        md = md.Replace(ResumeSections.LegacySummaryStart, "", StringComparison.Ordinal)
               .Replace(ResumeSections.LegacySummaryEnd, "", StringComparison.Ordinal);

        var lines = md.Split('\n').ToList();

        // Preferred: explicit Summary section.
        var summaryHeaderIndex = FindH2StartingWith(lines, "Summary");
        if (summaryHeaderIndex >= 0)
            return ExtractSectionBody(lines, summaryHeaderIndex);

        // Fallback: legacy "first H2 section after HR".
        var hrIndex = lines.FindIndex(l => l.Trim() == "---");
        var start = hrIndex >= 0 ? hrIndex + 1 : 0;

        var firstH2 = -1;
        for (var i = start; i < lines.Count; i++)
        {
            if (IsH2(lines[i]))
            {
                firstH2 = i;
                break;
            }
        }

        if (firstH2 >= 0)
            return ExtractSectionBody(lines, firstH2);

        return "";
    }

    private static string ExtractSectionBody(List<string> lines, int headerIndex)
    {
        var bodyStart = headerIndex + 1;
        while (bodyStart < lines.Count && string.IsNullOrWhiteSpace(lines[bodyStart]))
            bodyStart++;

        var bodyEnd = bodyStart;
        while (bodyEnd < lines.Count && !IsH2(lines[bodyEnd]))
            bodyEnd++;

        if (bodyStart >= lines.Count || bodyEnd < bodyStart)
            return "";

        var body = lines.Skip(bodyStart).Take(bodyEnd - bodyStart).ToList();
        while (body.Count > 0 && string.IsNullOrWhiteSpace(body[0]))
            body.RemoveAt(0);
        while (body.Count > 0 && string.IsNullOrWhiteSpace(body[^1]))
            body.RemoveAt(body.Count - 1);

        return string.Join("\n", body).Trim();
    }

    private static int FindH2StartingWith(List<string> lines, string headerStartsWith)
    {
        for (var i = 0; i < lines.Count; i++)
        {
            var t = (lines[i] ?? "").Trim();
            if (!t.StartsWith("##", StringComparison.Ordinal))
                continue;

            var text = t.TrimStart('#').Trim().TrimEnd(':');
            if (text.StartsWith(headerStartsWith, StringComparison.OrdinalIgnoreCase))
                return i;
        }
        return -1;
    }

    private static bool IsH2(string line) => (line ?? "").TrimStart().StartsWith("## ", StringComparison.Ordinal);

    private static string NormalizeNewlines(string text) => (text ?? "").Replace("\r\n", "\n").Replace("\r", "\n");
}

