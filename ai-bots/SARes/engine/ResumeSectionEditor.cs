using System;
using System.Collections.Generic;
using System.Linq;

namespace SARes.engine;

public static class ResumeSectionEditor
{
    public static string ReplaceSectionBody(string markdown, Func<string, bool> isHeaderMatch, string newBody)
    {
        var md = NormalizeNewlines(markdown ?? "");
        var lines = md.Split('\n').ToList();

        var headerIndex = FindHeaderIndex(lines, isHeaderMatch);
        if (headerIndex < 0)
            throw new InvalidOperationException("Section header not found.");

        var bodyStart = headerIndex + 1;
        while (bodyStart < lines.Count && string.IsNullOrWhiteSpace(lines[bodyStart]))
            bodyStart++;

        var bodyEnd = bodyStart;
        while (bodyEnd < lines.Count && !IsH2(lines[bodyEnd]))
            bodyEnd++;

        if (bodyEnd > bodyStart)
            lines.RemoveRange(bodyStart, bodyEnd - bodyStart);

        var insertLines = NormalizeNewlines(newBody ?? "").Split('\n').Select(s => s.TrimEnd()).ToList();
        while (insertLines.Count > 0 && string.IsNullOrWhiteSpace(insertLines[0]))
            insertLines.RemoveAt(0);
        while (insertLines.Count > 0 && string.IsNullOrWhiteSpace(insertLines[^1]))
            insertLines.RemoveAt(insertLines.Count - 1);

        if (insertLines.Count == 0)
            throw new ArgumentException("New body is empty.", nameof(newBody));

        lines.InsertRange(bodyStart, insertLines);
        lines.Insert(bodyStart + insertLines.Count, "");

        return string.Join("\n", lines).TrimEnd() + "\n";
    }

    public static string ExtractSectionBody(string markdown, Func<string, bool> isHeaderMatch)
    {
        var md = NormalizeNewlines(markdown ?? "");
        var lines = md.Split('\n').ToList();

        var headerIndex = FindHeaderIndex(lines, isHeaderMatch);
        if (headerIndex < 0)
            return "";

        var bodyStart = headerIndex + 1;
        while (bodyStart < lines.Count && string.IsNullOrWhiteSpace(lines[bodyStart]))
            bodyStart++;

        var bodyEnd = bodyStart;
        while (bodyEnd < lines.Count && !IsH2(lines[bodyEnd]))
            bodyEnd++;

        var body = lines.Skip(bodyStart).Take(Math.Max(0, bodyEnd - bodyStart)).ToList();
        while (body.Count > 0 && string.IsNullOrWhiteSpace(body[0]))
            body.RemoveAt(0);
        while (body.Count > 0 && string.IsNullOrWhiteSpace(body[^1]))
            body.RemoveAt(body.Count - 1);

        return string.Join("\n", body).Trim();
    }

    public static bool IsSummaryHeader(string line)
    {
        var t = (line ?? "").Trim();
        if (!t.StartsWith("##", StringComparison.Ordinal))
            return false;
        var text = t.TrimStart('#').Trim().TrimEnd(':');
        return text.Equals("Summary", StringComparison.OrdinalIgnoreCase);
    }

    public static bool IsCoreSkillsHeader(string line)
    {
        var t = (line ?? "").Trim();
        if (!t.StartsWith("##", StringComparison.Ordinal))
            return false;
        var text = t.TrimStart('#').Trim().TrimEnd(':');
        return text.Equals("Core Skills", StringComparison.OrdinalIgnoreCase) ||
               text.Equals("Skills", StringComparison.OrdinalIgnoreCase) ||
               text.Equals("Technical Skills", StringComparison.OrdinalIgnoreCase);
    }

    private static int FindHeaderIndex(List<string> lines, Func<string, bool> isHeaderMatch)
    {
        for (var i = 0; i < lines.Count; i++)
        {
            if (isHeaderMatch(lines[i] ?? ""))
                return i;
        }
        return -1;
    }

    private static bool IsH2(string line) => (line ?? "").TrimStart().StartsWith("## ", StringComparison.Ordinal);
    private static string NormalizeNewlines(string text) => (text ?? "").Replace("\r\n", "\n").Replace("\r", "\n");
}

