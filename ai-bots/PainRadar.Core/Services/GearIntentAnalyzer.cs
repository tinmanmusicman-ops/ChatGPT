namespace PainRadar.Services;

public sealed class GearIntentAnalyzer
{
    public static readonly string[] BuyerIntentPhrases =
    {
        "wtb",
        "want to buy",
        "looking for",
        "need",
        "anyone selling",
        "searching for"
    };

    private readonly GearMatcher _matcher;

    public GearIntentAnalyzer(GearMatcher matcher) => _matcher = matcher;

    public GearIntentAnalysisResult AnalyzePost(string title, string body)
    {
        var text = ((title ?? "") + "\n" + (body ?? "")).Trim();
        if (text.Length == 0)
            return new GearIntentAnalysisResult(Array.Empty<string>(), Array.Empty<string>(), 0, 0, 0);

        var matchedIntent = MatchPhrases(text, BuyerIntentPhrases);
        var intentScore = matchedIntent.Count == 0 ? 0 : 20 + Math.Max(0, matchedIntent.Count - 1) * 5;

        var gear = _matcher.Match(text);

        var confidence = Math.Clamp(intentScore + gear.GearScore, 0, 100);

        return new GearIntentAnalysisResult(
            MatchedIntentPhrases: matchedIntent,
            MatchedGear: gear.MatchedGear,
            IntentScore: intentScore,
            GearScore: gear.GearScore,
            ConfidenceScore: confidence
        );
    }

    private static IReadOnlyList<string> MatchPhrases(string haystack, IReadOnlyList<string> phrases)
    {
        var matched = new List<string>();
        foreach (var p in phrases)
        {
            if (string.IsNullOrWhiteSpace(p))
                continue;
            if (haystack.Contains(p, StringComparison.OrdinalIgnoreCase))
                matched.Add(p);
        }

        return matched
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(s => s)
            .ToArray();
    }
}

public sealed record GearIntentAnalysisResult(
    IReadOnlyList<string> MatchedIntentPhrases,
    IReadOnlyList<string> MatchedGear,
    int IntentScore,
    int GearScore,
    int ConfidenceScore
);

