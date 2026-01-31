namespace PainRadar.Services;

public static class GearSearchQueryBuilder
{
    public static IReadOnlyList<string> BuildQueries(string? extraTerm = null)
    {
        var gearTerms = GearDictionary.SearchTerms;
        var categoryTerms = GearDictionary.CategoryTerms;
        var intentPhrases = GearIntentAnalyzer.BuyerIntentPhrases;

        var queries = new List<string>();

        // Gear terms alone
        foreach (var g in gearTerms)
            AddUnique(queries, QuoteIfNeeded(g));

        // Intent + gear (using OR-grouped intent phrases for breadth with fewer calls)
        var intentGroup = BuildOrGroup(intentPhrases);
        foreach (var g in gearTerms)
            AddUnique(queries, $"{intentGroup} {QuoteIfNeeded(g)}".Trim());

        // Intent + category
        foreach (var c in categoryTerms)
            AddUnique(queries, $"{intentGroup} {QuoteIfNeeded(c)}".Trim());

        // Optional: user-provided term as an extra query (never required; appended so it doesn't reduce breadth).
        var extra = (extraTerm ?? "").Trim();
        if (extra.Length > 0)
        {
            AddUnique(queries, QuoteIfNeeded(extra));
            AddUnique(queries, $"{intentGroup} {QuoteIfNeeded(extra)}".Trim());
        }

        return queries;
    }

    private static string BuildOrGroup(IReadOnlyList<string> phrases)
    {
        var parts = phrases
            .Select(p => QuoteIfNeeded((p ?? "").Trim()))
            .Where(p => p.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();

        return parts.Length == 0 ? "" : "(" + string.Join(" OR ", parts) + ")";
    }

    private static string QuoteIfNeeded(string? term)
    {
        var t = (term ?? "").Trim();
        if (t.Length == 0)
            return "";

        var needsQuotes = t.Any(char.IsWhiteSpace) || t.Contains('-', StringComparison.Ordinal);
        if (!needsQuotes)
            return t;

        var escaped = t.Replace("\"", "");
        return $"\"{escaped}\"";
    }

    private static void AddUnique(List<string> queries, string q)
    {
        var t = (q ?? "").Trim();
        if (t.Length == 0)
            return;
        if (!queries.Contains(t, StringComparer.OrdinalIgnoreCase))
            queries.Add(t);
    }
}

