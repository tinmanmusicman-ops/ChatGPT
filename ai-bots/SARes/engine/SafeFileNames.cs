using System.IO;
using System.Linq;

namespace SARes.engine;

public static class SafeFileNames
{
    public static string ToSafeFileSegment(string value, int maxLen = 60)
    {
        var s = (value ?? "").Trim();
        if (s.Length == 0)
            return "";

        var invalid = Path.GetInvalidFileNameChars();
        var cleaned = new string(s.Select(ch => invalid.Contains(ch) ? '_' : ch).ToArray());
        cleaned = string.Join("_", cleaned.Split(new[] { ' ', '\t', '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries));
        return cleaned.Length > maxLen ? cleaned[..maxLen] : cleaned;
    }
}

