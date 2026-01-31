using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using UglyToad.PdfPig;

namespace SARes.engine;

// BOOTSTRAP ONLY:
// One-time, lossy PDF -> internal Markdown intake.
//
// OVERRIDE — HUMAN NORMALIZATION MODE (PDF → MD ONLY)
// “HUMAN-NORMALIZED INTAKE — APPROVED OVERRIDE”
public static class PdfResumeImporter
{
    private const char BulletGlyph = '\u2022'; // •
    private const int MaxLineChars = 120;
    private const string HumanNormalizedLabel = "HUMAN-NORMALIZED INTAKE — APPROVED OVERRIDE";

    private static readonly IReadOnlyList<string> BaseSectionTitles = ResumeParserDefaults.SectionTitles;

    private static IReadOnlyList<string> ComposeSectionTitles(IEnumerable<string>? overrides)
    {
        var comparer = StringComparer.OrdinalIgnoreCase;
        var list = new List<string>();

        if (overrides is not null)
        {
            foreach (var header in overrides)
            {
                var trimmed = (header ?? "").Trim();
                if (trimmed.Length == 0)
                    continue;
                if (list.Any(existing => comparer.Equals(existing, trimmed)))
                    continue;
                list.Add(trimmed);
            }
        }

        return list;
    }

    public static IReadOnlyList<string> DefaultSectionTitles => BaseSectionTitles;

    public static string ImportPdfToTemplateMarkdown(string pdfPath, IEnumerable<string>? headerAliases = null)
        => ImportPdfToTemplateMarkdown(pdfPath, headerAliases, PdfLayoutMode.SingleColumn, bulletizeSectionTitles: null);

    public static string ImportPdfToTemplateMarkdown(string pdfPath, IEnumerable<string>? headerAliases, PdfLayoutMode layoutMode)
        => ImportPdfToTemplateMarkdown(pdfPath, headerAliases, layoutMode, bulletizeSectionTitles: null);

    public static string ImportPdfToTemplateMarkdown(
        string pdfPath,
        IEnumerable<string>? headerAliases,
        PdfLayoutMode layoutMode,
        IEnumerable<string>? bulletizeSectionTitles)
    {
        if (string.IsNullOrWhiteSpace(pdfPath) || !File.Exists(pdfPath))
            throw new FileNotFoundException("PDF not found: " + pdfPath);

        using var doc = PdfDocument.Open(pdfPath);
        var rawLines = new List<string>();

        for (var pageIndex = 1; pageIndex <= doc.NumberOfPages; pageIndex++)
        {
            var page = doc.GetPage(pageIndex);
            rawLines.AddRange(ExtractLogicalLinesFromPage(page, layoutMode));
            if (pageIndex < doc.NumberOfPages)
                rawLines.Add("");
        }

        if (rawLines.All(string.IsNullOrWhiteSpace))
            throw new InvalidOperationException("PDF text extraction returned empty content.");

        var sectionTitles = ComposeSectionTitles(headerAliases);
        var normalized = NormalizeStructure(rawLines, sectionTitles);
        normalized = HumanReflowParagraphs(normalized, sectionTitles);

        var markdownLines = WrapMarkdown(normalized, sectionTitles, bulletizeSectionTitles);
        var wrappedLines = HardWrap(markdownLines, MaxLineChars);

        var errors = Verify(wrappedLines, sectionTitles);
        if (errors.Count > 0)
            throw new InvalidOperationException("PDF intake failed invariants:\n- " + string.Join("\n- ", errors));

        return "<!-- " + HumanNormalizedLabel + " -->\n\n" + string.Join("\n", wrappedLines).TrimEnd() + "\n";
    }

    // Phase 2: reconstruct logical lines (prefer readability).
    private static List<string> ExtractLogicalLinesFromPage(UglyToad.PdfPig.Content.Page page, PdfLayoutMode layoutMode)
    {
        var words = page.GetWords()?.ToList() ?? [];
        if (words.Count > 0)
            return ExtractLinesFromWords(page, words, layoutMode);

        var letters = page.Letters?.ToList() ?? [];
        if (letters.Count > 0)
            return ExtractLinesFromLetters(page, letters, layoutMode);

        var text = (page.Text ?? "").Replace("\r\n", "\n").Replace("\r", "\n").Trim();
        if (text.Length > 0)
            return text.Split('\n').Select(l => l.TrimEnd()).ToList();

        throw new InvalidOperationException("PDF intake failed: no extractable text on at least one page.");
    }

    private static List<string> ExtractLinesFromWords(UglyToad.PdfPig.Content.Page page, List<UglyToad.PdfPig.Content.Word> words, PdfLayoutMode layoutMode)
    {
        var heights = words.Select(w => w.BoundingBox.Height).Where(h => h > 0).OrderBy(h => h).ToList();
        var medianHeight = heights.Count == 0 ? 10 : heights[heights.Count / 2];
        var yThreshold = Math.Max(1.5, medianHeight * 0.65);

        var items = words
            .Select(w => new PositionedText(w.Text, CenterY(w.BoundingBox.Bottom, w.BoundingBox.Top), w.BoundingBox.Left, w.BoundingBox.Right))
            .OrderByDescending(w => w.CenterY)
            .ThenBy(w => w.Left)
            .ToList();

        return BuildLinesFromItems(page, items, yThreshold, joinWithSpaces: true, medianHeight: medianHeight, layoutMode: layoutMode);
    }

    private static List<string> ExtractLinesFromLetters(UglyToad.PdfPig.Content.Page page, List<UglyToad.PdfPig.Content.Letter> letters, PdfLayoutMode layoutMode)
    {
        var heights = letters.Select(l => l.GlyphRectangle.Height).Where(h => h > 0).OrderBy(h => h).ToList();
        var medianHeight = heights.Count == 0 ? 10 : heights[heights.Count / 2];
        var yThreshold = Math.Max(1.5, medianHeight * 0.70);

        var items = letters
            .Select(l => new PositionedText(l.Value, CenterY(l.GlyphRectangle.Bottom, l.GlyphRectangle.Top), l.GlyphRectangle.Left, l.GlyphRectangle.Right))
            .OrderByDescending(l => l.CenterY)
            .ThenBy(l => l.Left)
            .ToList();

        return BuildLinesFromItems(page, items, yThreshold, joinWithSpaces: false, medianHeight: medianHeight, layoutMode: layoutMode);
    }

    private static List<string> BuildLinesFromItems(
        UglyToad.PdfPig.Content.Page page,
        List<PositionedText> items,
        double yThreshold,
        bool joinWithSpaces,
        double medianHeight,
        PdfLayoutMode layoutMode)
    {
        if (layoutMode == PdfLayoutMode.SingleColumn)
        {
            var clusters = ClusterByY(items, yThreshold);
            return BuildLinesFromClusters(page, clusters, joinWithSpaces: joinWithSpaces, medianHeight: medianHeight, allowColumnSplit: true);
        }

        var splitX = page.Width * 0.5;
        var fullWidth = new List<PositionedText>();
        var left = new List<PositionedText>();
        var right = new List<PositionedText>();

        foreach (var it in items)
        {
            // If a token crosses the centerline, treat it as a full-width line candidate (e.g., name/header).
            if (it.Left < splitX && it.Right > splitX)
            {
                fullWidth.Add(it);
                continue;
            }

            var centerX = (it.Left + it.Right) / 2.0;
            if (centerX < splitX)
                left.Add(it);
            else
                right.Add(it);
        }

        var output = new List<string>();

        if (fullWidth.Count > 0)
        {
            var clusters = ClusterByY(fullWidth, yThreshold);
            output.AddRange(BuildLinesFromClusters(page, clusters, joinWithSpaces: joinWithSpaces, medianHeight: medianHeight, allowColumnSplit: false));
        }

        var leftLines = left.Count > 0
            ? BuildLinesFromClusters(page, ClusterByY(left, yThreshold), joinWithSpaces: joinWithSpaces, medianHeight: medianHeight, allowColumnSplit: false)
            : new List<string>();
        var rightLines = right.Count > 0
            ? BuildLinesFromClusters(page, ClusterByY(right, yThreshold), joinWithSpaces: joinWithSpaces, medianHeight: medianHeight, allowColumnSplit: false)
            : new List<string>();

        if (layoutMode == PdfLayoutMode.TwoColumnsLeftToRight)
        {
            output.AddRange(leftLines);
            if (leftLines.Count > 0 && rightLines.Count > 0) output.Add("");
            output.AddRange(rightLines);
        }
        else
        {
            output.AddRange(rightLines);
            if (leftLines.Count > 0 && rightLines.Count > 0) output.Add("");
            output.AddRange(leftLines);
        }

        return TrimEdgeBlankLines(output);
    }

    private static List<LineCluster> ClusterByY(List<PositionedText> items, double yThreshold)
    {
        var lines = new List<LineCluster>();
        foreach (var item in items)
        {
            LineCluster? best = null;
            var bestDelta = double.MaxValue;
            foreach (var line in lines)
            {
                var delta = Math.Abs(item.CenterY - line.CenterY);
                if (delta <= yThreshold && delta < bestDelta)
                {
                    best = line;
                    bestDelta = delta;
                }
            }

            if (best is null)
            {
                best = new LineCluster(item.CenterY);
                lines.Add(best);
            }

            best.Add(item);
        }

        lines.Sort((a, b) => b.CenterY.CompareTo(a.CenterY));
        return lines;
    }

    private static List<string> BuildLinesFromClusters(
        UglyToad.PdfPig.Content.Page page,
        List<LineCluster> clusters,
        bool joinWithSpaces,
        double medianHeight = 10,
        bool allowColumnSplit = true)
    {
        var output = new List<string>();
        var columnSplitGap = allowColumnSplit ? Math.Max(90, page.Width * 0.25) : double.PositiveInfinity;
        double? prevCenterY = null;

        foreach (var cluster in clusters)
        {
            if (prevCenterY is not null)
            {
                var gap = prevCenterY.Value - cluster.CenterY;
                var paragraphGap = Math.Max(medianHeight * 2.2, medianHeight + 6);
                if (gap >= paragraphGap && output.Count > 0 && !string.IsNullOrWhiteSpace(output[^1]))
                    output.Add("");
            }

            var items = cluster.Items.OrderBy(i => i.Left).ToList();
            if (items.Count == 0)
                continue;

            var segments = new List<List<PositionedText>>();
            if (!allowColumnSplit)
            {
                segments.Add(items);
            }
            else
            {
                segments.Add(new List<PositionedText> { items[0] });
                for (var i = 1; i < items.Count; i++)
                {
                    var prev = items[i - 1];
                    var cur = items[i];
                    var gap = cur.Left - prev.Right;
                    if (gap > columnSplitGap)
                        segments.Add(new List<PositionedText>());
                    segments[^1].Add(cur);
                }
            }

            foreach (var seg in segments)
            {
                var text = joinWithSpaces
                    ? string.Join(" ", seg.Select(s => s.Text))
                    : JoinLettersWithSpaces(seg, medianHeight);

                text = text.Replace('\u00A0', ' ').Trim();
                if (text.Length > 0)
                    output.Add(text);
            }

            prevCenterY = cluster.CenterY;
        }

        return output;
    }

    private static string JoinLettersWithSpaces(List<PositionedText> letters, double medianHeight)
    {
        var sb = new StringBuilder();
        PositionedText? prev = null;
        var spaceGap = Math.Max(1.0, medianHeight * 0.22);

        foreach (var l in letters.OrderBy(x => x.Left))
        {
            if (prev is not null)
            {
                var gap = l.Left - prev.Value.Right;
                if (gap > spaceGap)
                    sb.Append(' ');
            }
            sb.Append(l.Text);
            prev = l;
        }

        return sb.ToString();
    }

    private static double CenterY(double bottom, double top) => (bottom + top) / 2.0;

    private static List<string> NormalizeStructure(List<string> lines, IReadOnlyList<string> sectionTitles)
    {
        var output = new List<string>();

        foreach (var raw in lines)
        {
            var line = (raw ?? "").Replace('\u00A0', ' ').Trim();
            if (line.Length == 0)
            {
                output.Add("");
                continue;
            }

            output.AddRange(SplitByKnownTitles(line, sectionTitles));
        }

        output = SplitContactInfo(output, sectionTitles);
        output = RepairGluedWordsInHeaderBlock(output, sectionTitles);
        output = ExpandBullets(output);

        return TrimEdgeBlankLines(output);
    }

    private static List<string> SplitByKnownTitles(string line, IReadOnlyList<string> sectionTitles)
    {
        var remaining = line;
        var parts = new List<string>();

        while (true)
        {
            var best = FindEarliestKnownTitle(remaining, sectionTitles);
            if (best is null)
            {
                if (remaining.Trim().Length > 0)
                    parts.Add(remaining.Trim());
                break;
            }

            var (idx, len) = best.Value;
            var before = remaining[..idx];
            var title = remaining.Substring(idx, len);
            var after = remaining[(idx + len)..];

            if (before.Trim().Length > 0)
                parts.Add(before.Trim());
            parts.Add(title.Trim());
            remaining = after;

            if (remaining.Trim().Length == 0)
                break;
        }

        return parts;
    }

    private static (int idx, int len)? FindEarliestKnownTitle(string text, IReadOnlyList<string> sectionTitles)
    {
        (int idx, int len)? best = null;
        foreach (var title in sectionTitles)
        {
            var idx = text.IndexOf(title, StringComparison.Ordinal);
            if (idx < 0) continue;

            var beforeSegment = text[..idx];
            var afterSegment = text[(idx + title.Length)..];

            var beforeOk = idx == 0 || !char.IsLetterOrDigit(text[idx - 1]);
            var afterIdx = idx + title.Length;
            var afterOk = afterIdx >= text.Length || !char.IsLetterOrDigit(text[afterIdx]);
            if (!beforeOk || !afterOk) continue;

            var hasWordChars = new Func<string, bool>(segment => Regex.IsMatch(segment, @"\p{L}|\p{Nd}"));
            if (hasWordChars(beforeSegment) || hasWordChars(afterSegment))
                continue;

            if (best is null || idx < best.Value.idx)
                best = (idx, title.Length);
        }
        return best;
    }

    private static List<string> SplitContactInfo(List<string> lines, IReadOnlyList<string> sectionTitles)
    {
        var stop = lines.FindIndex(line => IsKnownSectionTitleLine(line, sectionTitles));
        if (stop < 0)
            stop = Math.Min(lines.Count, 30);

        var output = new List<string>();
        for (var i = 0; i < lines.Count; i++)
        {
            var line = lines[i] ?? "";
            if (i >= stop)
            {
                output.Add(line);
                continue;
            }

            var pieces = SplitLineByContactTokens(line).ToList();
            output.AddRange(FixPipeSeparators(pieces));
        }

        return TrimEdgeBlankLines(output);
    }

    private static IEnumerable<string> SplitLineByContactTokens(string line)
    {
        var text = (line ?? "").Trim();
        if (text.Length == 0)
            yield break;

        while (true)
        {
            var best = FindEarliestContactMatch(text);
            if (best is null)
            {
                if (text.Trim().Length > 0)
                    yield return text.Trim();
                yield break;
            }

            var (idx, len) = best.Value;
            var before = text[..idx];
            var token = text.Substring(idx, len);
            var after = text[(idx + len)..];

            if (before.Trim().Length > 0)
                yield return before.Trim();

            yield return token.Trim();

            text = after;
        }
    }

    private static (int idx, int len)? FindEarliestContactMatch(string text)
    {
        var candidates = new List<(int idx, int len)>();

        var url = Regex.Match(text, @"https?://\S+", RegexOptions.IgnoreCase);
        if (url.Success) candidates.Add((url.Index, url.Length));

        var email = Regex.Match(text, @"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", RegexOptions.IgnoreCase);
        if (email.Success) candidates.Add((email.Index, email.Length));

        var phone = Regex.Match(text, @"\(?\d{3}\)?[ \-\.]?\d{3}[ \-\.]?\d{4}");
        if (phone.Success) candidates.Add((phone.Index, phone.Length));

        if (candidates.Count == 0)
            return null;

        return candidates.OrderBy(c => c.idx).First();
    }

    private static List<string> FixPipeSeparators(List<string> pieces)
    {
        var output = new List<string>();
        foreach (var p in pieces)
        {
            var t = (p ?? "").Trim();
            if (t == "|")
            {
                if (output.Count > 0)
                    output[^1] = output[^1].TrimEnd() + " |";
                else
                    output.Add("|");
                continue;
            }

            if (t.StartsWith("|", StringComparison.Ordinal) && t.Length > 1)
            {
                if (output.Count > 0)
                    output[^1] = output[^1].TrimEnd() + " |";
                output.Add(t[1..].TrimStart());
                continue;
            }

            output.Add((p ?? "").Trim());
        }
        return output;
    }

    private static List<string> RepairGluedWordsInHeaderBlock(List<string> lines, IReadOnlyList<string> sectionTitles)
    {
        var output = new List<string>(lines);
        var stop = output.FindIndex(line => IsKnownSectionTitleLine(line, sectionTitles));
        if (stop < 0)
            stop = Math.Min(output.Count, 25);

        for (var i = 0; i < stop; i++)
        {
            var t = (output[i] ?? "").TrimEnd();
            if (t.Length == 0) continue;
            if (LooksLikeContactLine(t)) continue;
            if (t.StartsWith("- ", StringComparison.Ordinal)) continue;

            t = Regex.Replace(t, @"(?<=[a-z])(?=[A-Z][a-z])", " ");
            output[i] = t;
        }

        return output;
    }

    private static List<string> ExpandBullets(List<string> lines)
    {
        var output = new List<string>();
        foreach (var line in lines)
        {
            var text = (line ?? "").Replace('\u00A0', ' ').Trim();
            if (text.Length == 0)
            {
                output.Add("");
                continue;
            }

            if (text.IndexOf(BulletGlyph) < 0)
            {
                if (text.StartsWith("-", StringComparison.Ordinal) && !text.StartsWith("- ", StringComparison.Ordinal) && text.Length > 1 && !char.IsDigit(text[1]))
                    output.Add("- " + text[1..].TrimStart());
                else
                    output.Add(text);
                continue;
            }

            var tmp = text.Replace(BulletGlyph.ToString(), "\n" + BulletGlyph);
            foreach (var part in tmp.Split('\n'))
            {
                var p = part.Trim();
                if (p.Length == 0) continue;
                if (p[0] == BulletGlyph)
                    output.Add("- " + p[1..].TrimStart());
                else
                    output.Add(p);
            }
        }

        return TrimEdgeBlankLines(output);
    }

    private static List<string> HumanReflowParagraphs(List<string> lines, IReadOnlyList<string> sectionTitles)
    {
        var output = new List<string>();
        foreach (var raw in lines)
        {
            var line = (raw ?? "").TrimEnd();
            if (line.Length == 0)
            {
                if (output.Count > 0 && output[^1].Length != 0)
                    output.Add("");
                continue;
            }

            if (output.Count == 0)
            {
                output.Add(line);
                continue;
            }

            var prevTrim = (output[^1] ?? "").TrimEnd();
            var curTrim = line.TrimStart();

            var prevIsSpecial = prevTrim.StartsWith("- ", StringComparison.Ordinal)
                                || LooksLikeContactLine(prevTrim)
                                || IsKnownSectionTitleLine(prevTrim, sectionTitles);
            var curIsSpecial = curTrim.StartsWith("- ", StringComparison.Ordinal)
                               || LooksLikeContactLine(curTrim)
                               || IsKnownSectionTitleLine(curTrim, sectionTitles);

            if (prevIsSpecial || curIsSpecial)
            {
                output.Add(line);
                continue;
            }

            if (prevTrim.EndsWith("-", StringComparison.Ordinal) && curTrim.Length > 0 && char.IsLetter(curTrim[0]))
            {
                output[^1] = prevTrim[..^1] + curTrim;
                continue;
            }

            var prevEndsSentence = prevTrim.EndsWith(".", StringComparison.Ordinal)
                                   || prevTrim.EndsWith("!", StringComparison.Ordinal)
                                   || prevTrim.EndsWith("?", StringComparison.Ordinal)
                                   || prevTrim.EndsWith(":", StringComparison.Ordinal);
            var curStartsLower = curTrim.Length > 0 && char.IsLower(curTrim[0]);
            var prevLongish = prevTrim.Length >= 35;

            if (!prevEndsSentence && (curStartsLower || prevLongish))
            {
                output[^1] = prevTrim + " " + curTrim;
                continue;
            }

            output.Add(line);
        }

        return TrimEdgeBlankLines(output);
    }

    private static List<string> WrapMarkdown(List<string> lines, IReadOnlyList<string> sectionTitles, IEnumerable<string>? bulletizeSectionTitles)
    {
        var output = new List<string>();
        var firstNonEmpty = lines.FindIndex(l => !string.IsNullOrWhiteSpace(l));
        if (firstNonEmpty < 0)
            throw new InvalidOperationException("PDF intake failed: no lines after normalization.");

        output.Add("# " + lines[firstNonEmpty].Trim());
        for (var i = firstNonEmpty + 1; i < lines.Count; i++)
            output.Add(lines[i]);

        // Only wrap headers that are explicitly provided via sectionTitles (from presets/custom mappings).
        for (var i = 0; i < output.Count; i++)
        {
            var t = (output[i] ?? "").Trim();
            if (t.Length == 0) continue;
            if (IsKnownSectionTitleLine(t, sectionTitles))
                output[i] = "## " + t;
        }

        // In PDF imports, many short lines (especially in skills) are expected.
        // Do not guess additional headers beyond the explicit sectionTitles list.
        // If the user opted into bullet forcing for certain sections, apply it now.
        ForceBulletsUnderSections(output, bulletizeSectionTitles);

        output = InsertBlankLinesAroundHeadings(output);
        return TrimEdgeBlankLines(output);
    }

    private static void ForceBulletsUnderSections(List<string> lines, IEnumerable<string>? sectionTitlesToBulletize)
    {
        var titles = (sectionTitlesToBulletize ?? Array.Empty<string>())
            .Select(t => (t ?? "").Trim().TrimEnd(':'))
            .Where(t => t.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        if (titles.Count == 0)
            return;

        for (var sectionIdx = 0; sectionIdx < titles.Count; sectionIdx++)
        {
            var title = titles[sectionIdx];
            var startIdx = FindSectionHeaderIndex(lines, title);
            if (startIdx < 0)
                continue;

            var endIdx = lines.Count;
            for (var i = startIdx + 1; i < lines.Count; i++)
            {
                var t = (lines[i] ?? "").Trim();
                if (t.StartsWith("## ", StringComparison.Ordinal))
                {
                    endIdx = i;
                    break;
                }
            }

            for (var i = startIdx + 1; i < endIdx; i++)
            {
                var t = (lines[i] ?? "").TrimEnd();
                if (t.Length == 0)
                    continue;

                if (t.StartsWith("- ", StringComparison.Ordinal))
                    continue;
                if (t.StartsWith("#", StringComparison.Ordinal))
                    continue;

                lines[i] = "- " + t.TrimStart();
            }
        }
    }

    private static int FindSectionHeaderIndex(List<string> lines, string title)
    {
        for (var i = 0; i < lines.Count; i++)
        {
            var t = (lines[i] ?? "").Trim();
            if (!t.StartsWith("## ", StringComparison.Ordinal))
                continue;
            var headerText = t.Substring(3).Trim().TrimEnd(':');
            if (headerText.Equals(title, StringComparison.OrdinalIgnoreCase))
                return i;
        }
        return -1;
    }

    private static void PromoteProfessionalExperienceRoles(List<string> lines)
    {
        var startIdx = lines.FindIndex(l => string.Equals((l ?? "").Trim(), "## Professional Experience", StringComparison.OrdinalIgnoreCase));
        if (startIdx < 0)
            return;

        var endIdx = lines.Count;
        for (var i = startIdx + 1; i < lines.Count; i++)
        {
            var t = (lines[i] ?? "").Trim();
            if (t.StartsWith("## ", StringComparison.Ordinal))
            {
                endIdx = i;
                break;
            }
        }

        for (var i = startIdx + 1; i < endIdx; i++)
        {
            var t = (lines[i] ?? "").Trim();
            if (t.Length == 0) continue;
            if (t.StartsWith("## ", StringComparison.Ordinal)) continue;
            if (t.StartsWith("### ", StringComparison.Ordinal)) continue;
            if (t.StartsWith("- ", StringComparison.Ordinal)) continue;
            if (LooksLikeLocationLine(t)) continue;
            if (LooksLikeStandaloneDateLine(t)) continue;

            if (!LooksLikeRoleHeaderLine(t))
                continue;

            var lookahead = NextNonEmptyLines(lines, i + 1, endIdx, 2).ToList();
            if (lookahead.Count == 0) continue;
            if (lookahead.Any(x => x.StartsWith("- ", StringComparison.Ordinal)) || lookahead.Any(LooksLikeDateLine) || lookahead.Any(LooksLikeLocationLine))
                lines[i] = "### " + t;
        }
    }

    private static IEnumerable<string> NextNonEmptyLines(List<string> lines, int start, int endExclusive, int count)
    {
        var found = 0;
        for (var i = start; i < endExclusive && found < count; i++)
        {
            var t = (lines[i] ?? "").Trim();
            if (t.Length == 0) continue;
            yield return t;
            found++;
        }
    }

    private static bool LooksLikeRoleHeaderLine(string line)
    {
        var t = (line ?? "").Trim();
        if (t.Length is < 6 or > 110) return false;
        if (t.EndsWith(".", StringComparison.Ordinal)) return false;
        return true;
    }

    private static bool LooksLikeDateLine(string line)
    {
        var t = (line ?? "").Trim();
        if (t.Length == 0) return false;
        if (Regex.IsMatch(t, @"\b(19|20)\d{2}\b")) return true;
        if (Regex.IsMatch(t, @"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\b", RegexOptions.IgnoreCase)) return true;
        return false;
    }

    private static bool LooksLikeStandaloneDateLine(string line)
    {
        var t = (line ?? "").Trim();
        if (t.Length == 0) return false;

        // Date lines tend to start with a month token or a year/digit token.
        if (Regex.IsMatch(t, @"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\b", RegexOptions.IgnoreCase))
            return true;
        if (Regex.IsMatch(t, @"^(\*?\s*)?(\d{1,2}[/\-]\d{4}|\d{4})\b"))
            return true;

        return false;
    }

    private static bool LooksLikeLocationLine(string line)
    {
        var t = (line ?? "").Trim();
        if (t.Length == 0) return false;
        if (Regex.IsMatch(t, @"\b[A-Z]{2}\b")) return true;
        if (t.Contains(',')) return true;
        return false;
    }

    private static bool IsKnownSectionTitleLine(string line, IReadOnlyList<string> sectionTitles)
    {
        var t = (line ?? "").Trim();
        foreach (var title in sectionTitles)
            if (t.Equals(title, StringComparison.OrdinalIgnoreCase))
                return true;
        return false;
    }

    private static bool LooksLikeContactLine(string line)
    {
        var t = (line ?? "").Trim();
        if (t.Length == 0) return false;
        if (Regex.IsMatch(t, @"^(LinkedIn|Linked In)\s*:?\s*$", RegexOptions.IgnoreCase)) return true;
        if (Regex.IsMatch(t, @"https?://\S+", RegexOptions.IgnoreCase)) return true;
        if (Regex.IsMatch(t, @"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", RegexOptions.IgnoreCase)) return true;
        if (Regex.IsMatch(t, @"\(?\d{3}\)?[ \-\.]?\d{3}[ \-\.]?\d{4}")) return true;
        if (t.Contains('|')) return true;
        return false;
    }

    private static bool LooksLikeSectionTitleCandidate(string line)
    {
        var t = (line ?? "").Trim();
        if (t.Length is < 3 or > 90) return false;
        if (t.EndsWith(".", StringComparison.Ordinal)) return false;
        if (t.Contains("@") || t.Contains("http", StringComparison.OrdinalIgnoreCase)) return false;
        if (Regex.IsMatch(t, @"\d{4}")) return false;
        return true;
    }

    private static bool LooksLikeSectionHeaderLine(string line, List<string> allLines, int index)
    {
        var t = (line ?? "").Trim();
        if (t.Length is < 3 or > 60) return false;
        if (t.EndsWith(".", StringComparison.Ordinal)) return false;
        if (t.Contains("@") || t.Contains("http", StringComparison.OrdinalIgnoreCase)) return false;
        if (Regex.IsMatch(t, @"\b(19|20)\d{2}\b")) return false;
        if (t.Contains(',')) return false;
        if (t.Contains('?')) return false;

        var wordCount = t.Split(' ', StringSplitOptions.RemoveEmptyEntries).Length;
        if (wordCount > 5) return false;

        var prevBlank = index == 0 || string.IsNullOrWhiteSpace(allLines[index - 1]);
        var prevNonEmpty = PrevNonEmptyLine(allLines, index - 1);
        var nextNonEmpty = NextNonEmptyLines(allLines, index + 1, allLines.Count, 1).FirstOrDefault();

        var lettersOnly = Regex.Replace(t, @"[^A-Z]", "");
        var isAllCaps = lettersOnly.Length >= 3
                        && lettersOnly.Length == Regex.Replace(t, @"[^A-Za-z]", "").Length
                        && t.ToUpperInvariant() == t;

        if (isAllCaps)
        {
            if (wordCount > 4) return false;
            if (t.Contains(" - ") || t.Contains(" – ") || t.Contains(" — ")) return false;

            var okPrev = prevBlank
                         || (prevNonEmpty?.StartsWith("- ", StringComparison.Ordinal) ?? false)
                         || (prevNonEmpty?.StartsWith("# ", StringComparison.Ordinal) ?? false)
                         || (prevNonEmpty is not null && LooksLikeContactLine(prevNonEmpty));
            return okPrev && nextNonEmpty is not null;
        }

        var isTitleish = LooksLikeSectionTitleCandidate(t);
        if (!isTitleish) return false;
        if (wordCount > 4) return false;
        if (t.Contains(" - ") || t.Contains(" – ") || t.Contains(" — ")) return false;
        if (!prevBlank
            && !(prevNonEmpty?.StartsWith("- ", StringComparison.Ordinal) ?? false)
            && !(prevNonEmpty?.StartsWith("## ", StringComparison.Ordinal) ?? false)
            && !(prevNonEmpty is not null && LooksLikeContactLine(prevNonEmpty)))
            return false;

        if (nextNonEmpty is null) return false;
        if (nextNonEmpty.StartsWith("- ", StringComparison.Ordinal)) return true;
        if (nextNonEmpty.StartsWith("## ", StringComparison.Ordinal)) return true;
        if (Regex.IsMatch(nextNonEmpty, @"[A-Za-z]")) return true;

        return false;
    }

    private static string? PrevNonEmptyLine(List<string> lines, int startIndex)
    {
        for (var i = startIndex; i >= 0; i--)
        {
            var t = (lines[i] ?? "").Trim();
            if (t.Length == 0) continue;
            return t;
        }
        return null;
    }

    private static List<string> InsertBlankLinesAroundHeadings(List<string> lines)
    {
        var output = new List<string>();
        for (var i = 0; i < lines.Count; i++)
        {
            var t = (lines[i] ?? "").TrimEnd();
            var isHeading = t.StartsWith("## ", StringComparison.Ordinal) || t.StartsWith("### ", StringComparison.Ordinal);

            if (isHeading && output.Count > 0 && !string.IsNullOrWhiteSpace(output[^1]))
                output.Add("");

            output.Add(t);

            if (isHeading)
            {
                if (i + 1 < lines.Count && !string.IsNullOrWhiteSpace(lines[i + 1]))
                    output.Add("");
            }
        }
        return TrimEdgeBlankLines(output);
    }

    private static List<string> HardWrap(List<string> lines, int maxChars)
    {
        var output = new List<string>();
        foreach (var raw in lines)
        {
            var line = raw ?? "";
            if (line.Length <= maxChars)
            {
                output.Add(line);
                continue;
            }

            var isBullet = line.StartsWith("- ", StringComparison.Ordinal);
            var bulletPrefix = isBullet ? "- " : "";
            var continuationPrefix = isBullet ? "  " : "";
            var content = isBullet ? line[2..].TrimStart() : line;

            var currentPrefix = bulletPrefix;
            while (content.Length > 0)
            {
                var available = maxChars - currentPrefix.Length;
                if (available <= 10)
                    throw new InvalidOperationException("PDF intake failed: line wrapping cannot satisfy max line length invariant.");

                if (content.Length <= available)
                {
                    output.Add(currentPrefix + content);
                    break;
                }

                var breakAt = content.LastIndexOf(' ', available);
                if (breakAt <= 0)
                    breakAt = available;

                var piece = content[..breakAt].TrimEnd();
                output.Add(currentPrefix + piece);
                content = content[breakAt..].TrimStart();
                currentPrefix = continuationPrefix;
            }
        }
        return output;
    }

    private static List<string> Verify(List<string> lines, IReadOnlyList<string> sectionTitles)
    {
        var errors = new List<string>();

        for (var i = 0; i < lines.Count; i++)
        {
            var len = (lines[i] ?? "").Length;
            if (len > MaxLineChars)
                errors.Add($"Line {i + 1} exceeds {MaxLineChars} chars.");
        }

        foreach (var title in sectionTitles)
        {
            var hasBare = lines.Any(l => string.Equals((l ?? "").Trim(), title, StringComparison.OrdinalIgnoreCase));
            if (hasBare)
                errors.Add($"Section title \"{title}\" is not wrapped as a Markdown header.");
        }

        for (var i = 0; i < lines.Count; i++)
        {
            var t = (lines[i] ?? "").Trim();
            if (t.Length == 0) continue;

            var email = Regex.Match(t, @"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", RegexOptions.IgnoreCase);
            if (email.Success && !IsIsolatedTokenLine(t, email.Value, allowedPrefixes: ["Email:"], allowedSuffixRegex: @"^[\s\|,;:]*$"))
                errors.Add($"Email is not isolated on its own line (line {i + 1}).");

            var url = Regex.Match(t, @"https?://\S+", RegexOptions.IgnoreCase);
            if (url.Success && !IsIsolatedTokenLine(t, url.Value, allowedPrefixes: ["LinkedIn:", "Linked In:", "Portfolio:"], allowedSuffixRegex: @"^[\s\|,;:]*$"))
                errors.Add($"URL is not isolated on its own line (line {i + 1}).");

            var phone = Regex.Match(t, @"\(?\d{3}\)?[ \-\.]?\d{3}[ \-\.]?\d{4}");
            if (phone.Success && !IsIsolatedTokenLine(t, phone.Value, allowedPrefixes: ["Phone:"], allowedSuffixRegex: @"^[\s\|,;:]*$"))
                errors.Add($"Phone is not isolated on its own line (line {i + 1}).");
        }

        for (var i = 0; i < lines.Count; i++)
        {
            var t = (lines[i] ?? "").TrimEnd();
            if (!t.StartsWith("- ", StringComparison.Ordinal))
                continue;
            if (t.Length <= 2 || string.IsNullOrWhiteSpace(t[2..]))
                errors.Add($"Empty bullet item (line {i + 1}).");
        }

        if (lines.Any(l => (l ?? "").IndexOf(BulletGlyph) >= 0))
            errors.Add("Bullet glyph (•) remains after normalization.");

        if (!lines.Any(l => (l ?? "").StartsWith("## ", StringComparison.Ordinal)))
            errors.Add("No section headers (##) found.");

        return errors;
    }

    private static bool IsIsolatedTokenLine(string line, string token, string[] allowedPrefixes, string allowedSuffixRegex)
    {
        var t = (line ?? "").Trim();
        foreach (var prefix in allowedPrefixes)
        {
            if (t.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                t = t[prefix.Length..].TrimStart();
                break;
            }
        }

        if (!t.Contains(token, StringComparison.Ordinal))
            return false;

        var beforeAfter = t.Replace(token, "", StringComparison.Ordinal).Trim();
        return Regex.IsMatch(beforeAfter, allowedSuffixRegex);
    }

    private static List<string> TrimEdgeBlankLines(List<string> lines)
    {
        var output = new List<string>(lines);
        while (output.Count > 0 && string.IsNullOrWhiteSpace(output[0]))
            output.RemoveAt(0);
        while (output.Count > 0 && string.IsNullOrWhiteSpace(output[^1]))
            output.RemoveAt(output.Count - 1);
        return output;
    }

    private readonly record struct PositionedText(string Text, double CenterY, double Left, double Right);

    private sealed class LineCluster(double centerY)
    {
        public double CenterY { get; private set; } = centerY;
        public List<PositionedText> Items { get; } = [];
        private int _count;

        public void Add(PositionedText item)
        {
            Items.Add(item);
            _count++;
            CenterY = ((_count - 1) * CenterY + item.CenterY) / _count;
        }
    }
}
