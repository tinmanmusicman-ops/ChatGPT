namespace PainRadar.Services;

public sealed class GearMatcher
{
    private readonly GearDictionary _dictionary;

    public GearMatcher(GearDictionary dictionary) => _dictionary = dictionary;

    public GearMatchResult Match(string text)
    {
        var t = (text ?? "").Trim();
        if (t.Length == 0)
            return new GearMatchResult(Array.Empty<string>(), 0);

        var matched = new List<string>();
        var score = 0;

        foreach (var entry in _dictionary.Entries)
        {
            if (ContainsAny(t, entry.Aliases, out var isExactCanonical))
            {
                matched.Add(entry.CanonicalName);
                score += isExactCanonical ? 40 : 20;
            }
        }

        var distinct = matched
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(s => s)
            .ToArray();

        return new GearMatchResult(distinct, score);
    }

    private static bool ContainsAny(string haystack, IReadOnlyList<string> needles, out bool isExactCanonical)
    {
        isExactCanonical = false;
        foreach (var n in needles)
        {
            if (string.IsNullOrWhiteSpace(n))
                continue;
            if (haystack.Contains(n, StringComparison.OrdinalIgnoreCase))
            {
                // Heuristic: treat the first alias as "most exact".
                isExactCanonical = ReferenceEquals(n, needles[0]) || string.Equals(n, needles[0], StringComparison.OrdinalIgnoreCase);
                return true;
            }
        }
        return false;
    }
}

public sealed record GearMatchResult(IReadOnlyList<string> MatchedGear, int GearScore);

