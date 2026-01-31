using System.IO;
using System.Globalization;
using System.Text;
using PainRadar.Models;

namespace PainRadar.Services;

public sealed class CsvMatchLogService
{
    private readonly object _gate = new();
    private readonly HashSet<string> _seen;

    public CsvMatchLogService(string csvPath)
    {
        CsvPath = (csvPath ?? "").Trim();
        _seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        LoadExistingKeys();
    }

    public string CsvPath { get; }

    public IReadOnlyList<GearSignalItem> AppendNewMatches(IEnumerable<GearSignalItem> items)
    {
        if (string.IsNullOrWhiteSpace(CsvPath))
            return Array.Empty<GearSignalItem>();

        var candidates = (items ?? Array.Empty<GearSignalItem>())
            .Where(i => i.MatchedIntentPhrases.Count > 0 && i.MatchedGear.Count > 0)
            .ToArray();

        if (candidates.Length == 0)
            return Array.Empty<GearSignalItem>();

        var added = new List<GearSignalItem>();
        lock (_gate)
        {
            foreach (var item in candidates)
            {
                var key = BuildKey(item);
                if (key.Length == 0 || !_seen.Add(key))
                    continue;
                added.Add(item);
            }

            if (added.Count == 0)
                return Array.Empty<GearSignalItem>();

            EnsureDirectory(CsvPath);

            var needsHeader = !File.Exists(CsvPath) || new FileInfo(CsvPath).Length == 0;
            using var stream = new FileStream(CsvPath, FileMode.Append, FileAccess.Write, FileShare.Read);
            using var writer = new StreamWriter(stream, Encoding.UTF8);

            if (needsHeader)
                writer.WriteLine("logged_at_utc,platform,buyer,posted_at_utc,score,intent_phrases,gear_matches,title,url,body");

            var now = DateTimeOffset.UtcNow.ToString("o", CultureInfo.InvariantCulture);
            foreach (var item in added)
            {
                var posted = item.PostedAtUtc?.ToString("o", CultureInfo.InvariantCulture) ?? "";
                writer.WriteLine(string.Join(",",
                    Csv(now),
                    Csv(item.Platform),
                    Csv(item.Buyer),
                    Csv(posted),
                    Csv(item.ConfidenceScore.ToString(CultureInfo.InvariantCulture)),
                    Csv(item.MatchedIntentPhrasesDisplay),
                    Csv(item.MatchedGearDisplay),
                    Csv(item.Title),
                    Csv(item.Url),
                    Csv(item.Body)
                ));
            }
        }

        return added;
    }

    private void LoadExistingKeys()
    {
        try
        {
            if (string.IsNullOrWhiteSpace(CsvPath) || !File.Exists(CsvPath))
                return;

            foreach (var line in File.ReadLines(CsvPath))
            {
                var trimmed = (line ?? "").Trim();
                if (trimmed.Length == 0 || trimmed.StartsWith("logged_at_utc,", StringComparison.OrdinalIgnoreCase))
                    continue;

                // naive: URL is the 9th column; safe enough since we only use it as a best-effort dedupe.
                var parts = SplitCsvLine(trimmed);
                if (parts.Count >= 9)
                {
                    var url = parts[8];
                    if (!string.IsNullOrWhiteSpace(url))
                        _seen.Add($"url:{url.Trim()}");
                }
            }
        }
        catch
        {
        }
    }

    private static string BuildKey(GearSignalItem item)
    {
        var url = (item.Url ?? "").Trim();
        if (url.Length > 0)
            return $"url:{url}";

        var t = (item.Title ?? "").Trim();
        if (t.Length == 0)
            return "";

        return $"fallback:{item.Platform}|{item.Buyer}|{t}";
    }

    private static void EnsureDirectory(string path)
    {
        try
        {
            var dir = Path.GetDirectoryName(path);
            if (!string.IsNullOrWhiteSpace(dir))
                Directory.CreateDirectory(dir);
        }
        catch
        {
        }
    }

    private static string Csv(string? value)
    {
        var s = value ?? "";
        s = s.Replace("\r", " ").Replace("\n", " ").Trim();
        var needsQuotes = s.Contains(',') || s.Contains('"');
        if (s.Contains('"'))
            s = s.Replace("\"", "\"\"");
        return needsQuotes ? $"\"{s}\"" : s;
    }

    private static List<string> SplitCsvLine(string line)
    {
        var parts = new List<string>();
        var sb = new StringBuilder();
        var inQuotes = false;

        for (var i = 0; i < line.Length; i++)
        {
            var c = line[i];
            if (inQuotes)
            {
                if (c == '"' && i + 1 < line.Length && line[i + 1] == '"')
                {
                    sb.Append('"');
                    i++;
                }
                else if (c == '"')
                {
                    inQuotes = false;
                }
                else
                {
                    sb.Append(c);
                }
            }
            else
            {
                if (c == ',')
                {
                    parts.Add(sb.ToString());
                    sb.Clear();
                }
                else if (c == '"')
                {
                    inQuotes = true;
                }
                else
                {
                    sb.Append(c);
                }
            }
        }

        parts.Add(sb.ToString());
        return parts;
    }
}
