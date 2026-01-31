using System;
using System.Collections.Generic;
using System.Linq;

namespace SARes.engine;

public static class ResumeAssembler
{
    public static string InjectSummary(string baseResumeMarkdown, string userSummary)
    {
        if (string.IsNullOrWhiteSpace(baseResumeMarkdown))
            throw new ArgumentException("Base resume markdown is empty.", nameof(baseResumeMarkdown));

        var summary = NormalizeSummary(userSummary);
        if (string.IsNullOrWhiteSpace(summary))
            throw new ArgumentException("Summary is required.", nameof(userSummary));

        var md = NormalizeNewlines(baseResumeMarkdown);

        // Remove legacy marker strings if present (older templates).
        md = md.Replace(ResumeSections.LegacySummaryStart, "", StringComparison.Ordinal)
               .Replace(ResumeSections.LegacySummaryEnd, "", StringComparison.Ordinal);

        var lines = md.Split('\n').ToList();

        var summaryHeaderIndex = FindExplicitSummaryHeaderIndex(lines);
        if (summaryHeaderIndex < 0)
            summaryHeaderIndex = FindFirstH2AfterHr(lines);

        if (summaryHeaderIndex < 0)
        {
            // No sections found; insert a Summary section at the top.
            lines.Insert(0, ResumeSections.SummaryHeader);
            lines.Insert(1, "");
            summaryHeaderIndex = 0;
        }

        lines[summaryHeaderIndex] = ResumeSections.SummaryHeader;
        ReplaceSectionBody(lines, summaryHeaderIndex, summary);

        return string.Join("\n", lines).TrimEnd() + "\n";
    }

    private static int FindExplicitSummaryHeaderIndex(List<string> lines)
    {
        for (var i = 0; i < lines.Count; i++)
        {
            var t = (lines[i] ?? "").Trim();
            if (!t.StartsWith("##", StringComparison.Ordinal))
                continue;

            var text = t.TrimStart('#').Trim().TrimEnd(':');
            if (text.Equals("Summary", StringComparison.OrdinalIgnoreCase))
                return i;
        }
        return -1;
    }

    private static int FindFirstH2AfterHr(List<string> lines)
    {
        var hrIndex = lines.FindIndex(l => (l ?? "").Trim() == "---");
        var start = hrIndex >= 0 ? hrIndex + 1 : 0;
        for (var i = start; i < lines.Count; i++)
        {
            if (IsH2(lines[i]))
                return i;
        }
        return -1;
    }

    private static void ReplaceSectionBody(List<string> lines, int headerIndex, string newBody)
    {
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
            throw new ArgumentException("Summary is required.", nameof(newBody));

        lines.InsertRange(bodyStart, insertLines);
        lines.Insert(bodyStart + insertLines.Count, "");
    }

    private static bool IsH2(string line) => (line ?? "").TrimStart().StartsWith("## ", StringComparison.Ordinal);

    private static string NormalizeSummary(string? summary)
    {
        var s = NormalizeNewlines(summary ?? "").Trim();
        if (s.Length == 0)
            return "";

        // Guard against legacy marker strings being pasted into the summary.
        s = s.Replace(ResumeSections.LegacySummaryStart, "", StringComparison.Ordinal)
             .Replace(ResumeSections.LegacySummaryEnd, "", StringComparison.Ordinal)
             .Trim();

        return s;
    }

    private static string NormalizeNewlines(string text) => (text ?? "").Replace("\r\n", "\n").Replace("\r", "\n");
}
