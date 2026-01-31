using System.Text;
using System.Text.RegularExpressions;

namespace SARes.engine;

public static class HelpManual
{
    public sealed record Section(string Title, IReadOnlyList<string> Tags, string BodyMarkdown);

    private static readonly Regex TagsLineRegex = new(@"^\[tags:\s*(.*?)\]\s*$", RegexOptions.IgnoreCase | RegexOptions.Compiled);

    public static IReadOnlyList<Section> ParseSections(string manualMarkdown)
    {
        var text = (manualMarkdown ?? "").Replace("\r\n", "\n").Replace("\r", "\n");
        var lines = text.Split('\n');

        var sections = new List<Section>();
        var currentTitle = "";
        var currentBodyLines = new List<string>();
        var currentTags = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        void Flush()
        {
            if (currentBodyLines.Count == 0)
                return;

            var body = string.Join("\n", currentBodyLines).Trim();
            if (body.Length == 0)
                return;

            sections.Add(new Section(
                Title: currentTitle,
                Tags: currentTags.OrderBy(t => t, StringComparer.OrdinalIgnoreCase).ToArray(),
                BodyMarkdown: body));

            currentTitle = "";
            currentBodyLines.Clear();
            currentTags.Clear();
        }

        foreach (var rawLine in lines)
        {
            var line = rawLine.Replace("\t", " ").TrimEnd();
            if (line.StartsWith("## ", StringComparison.Ordinal))
            {
                Flush();
                currentTitle = line.Trim();
                currentBodyLines.Add(currentTitle);
                continue;
            }

            if (currentBodyLines.Count == 0)
                continue; // Ignore content before first section header.

            var match = TagsLineRegex.Match(line.Trim());
            if (match.Success)
            {
                var payload = match.Groups[1].Value.Trim();
                foreach (var tag in payload.Split(',').Select(t => t.Trim()).Where(t => t.Length > 0))
                    currentTags.Add(tag.ToLowerInvariant());
            }

            currentBodyLines.Add(line);
        }

        Flush();
        return sections;
    }

    public static string? Search(string question, IReadOnlyList<Section> sections, int maxMatches = 10)
    {
        if (sections is null || sections.Count == 0)
            return null;

        var rawWords = NormalizeQueryWords(question);
        if (rawWords.Count == 0)
            return null;

        var vocab = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var s in sections)
        {
            foreach (var t in s.Tags ?? Array.Empty<string>())
            {
                var tag = (t ?? "").Trim();
                if (tag.Length > 0)
                    vocab.Add(tag.ToLowerInvariant());
            }
        }

        if (vocab.Count == 0)
            return null;

        var tagList = vocab.ToArray();
        var corrected = rawWords
            .Select(w => vocab.Contains(w) ? w : CorrectToVocab(w, tagList))
            .ToArray();

        var keywords = corrected.Where(vocab.Contains).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        if (keywords.Length == 0)
            return null;

        var matches = sections.Where(s =>
        {
            var tags = new HashSet<string>((s.Tags ?? Array.Empty<string>()).Select(t => (t ?? "").Trim().ToLowerInvariant()).Where(t => t.Length > 0));
            if (tags.Count == 0)
                return false;
            return keywords.All(tags.Contains);
        }).Take(Math.Max(1, maxMatches)).Select(s => s.BodyMarkdown).Where(b => !string.IsNullOrWhiteSpace(b)).ToArray();

        if (matches.Length == 0)
            return null;

        return string.Join("\n\n---\n\n", matches);
    }

    public static string FilterTagLines(string markdown)
    {
        if (string.IsNullOrWhiteSpace(markdown))
            return markdown ?? "";

        var sb = new StringBuilder();
        var text = markdown.Replace("\r\n", "\n").Replace("\r", "\n");
        foreach (var line in text.Split('\n'))
        {
            if (line.TrimStart().StartsWith("[tags:", StringComparison.OrdinalIgnoreCase))
                continue;
            sb.AppendLine(line);
        }
        return sb.ToString().TrimEnd();
    }

    private static List<string> NormalizeQueryWords(string question)
    {
        var normalized = (question ?? "")
            .ToLowerInvariant()
            .Replace("\r\n", " ")
            .Replace("\r", " ")
            .Replace("\n", " ");

        var words = new List<string>();
        var current = new StringBuilder();
        foreach (var ch in normalized)
        {
            if (char.IsLetterOrDigit(ch) || ch is '\'' or '-')
            {
                current.Append(ch);
            }
            else
            {
                FlushWord();
            }
        }
        FlushWord();

        void FlushWord()
        {
            if (current.Length == 0)
                return;
            var w = current.ToString().Trim();
            current.Clear();
            if (w.Length == 0)
                return;
            if (w.Length > 3 && w.EndsWith("s", StringComparison.Ordinal))
                w = w[..^1];
            words.Add(w);
        }

        return words;
    }

    private static string CorrectToVocab(string word, IReadOnlyList<string> vocab)
    {
        if (word.Length == 0)
            return word;

        string best = word;
        double bestScore = 0;
        foreach (var candidate in vocab)
        {
            var score = Similarity(word, candidate);
            if (score > bestScore)
            {
                bestScore = score;
                best = candidate;
            }
        }

        return bestScore >= 0.8 ? best : word;
    }

    private static double Similarity(string a, string b)
    {
        var maxLen = Math.Max(a.Length, b.Length);
        if (maxLen == 0)
            return 1.0;
        var dist = LevenshteinDistance(a, b);
        return 1.0 - (double)dist / maxLen;
    }

    private static int LevenshteinDistance(string a, string b)
    {
        var rows = a.Length + 1;
        var cols = b.Length + 1;
        var dist = new int[rows, cols];

        for (var i = 0; i < rows; i++)
            dist[i, 0] = i;
        for (var j = 0; j < cols; j++)
            dist[0, j] = j;

        for (var i = 1; i < rows; i++)
        {
            for (var j = 1; j < cols; j++)
            {
                var cost = a[i - 1] == b[j - 1] ? 0 : 1;
                dist[i, j] = Math.Min(
                    Math.Min(dist[i - 1, j] + 1, dist[i, j - 1] + 1),
                    dist[i - 1, j - 1] + cost);
            }
        }

        return dist[rows - 1, cols - 1];
    }
}

