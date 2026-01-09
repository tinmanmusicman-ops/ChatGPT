namespace PainRadar.Services;

public sealed class PainAnalyzer
{
    public static readonly string[] PainKeywords =
    {
        "manual",
        "workaround",
        "broken",
        "coordination",
        "follow-up",
        "multiple systems",
        "high volume",
        "disorganized",
        "inefficient"
    };

    public static readonly string[] GoogleReviewPainKeywords =
        PainKeywords.Concat(new[]
        {
            "follow up",
            "unorganized",
            "unresponsive",
            "no response",
            "slow",
            "delay",
            "delayed",
            "wait",
            "waiting",
            "poor communication",
            "no communication",
            "miscommunication"
        }).ToArray();

    public static readonly string[] GrowthKeywords =
    {
        "fast-paced",
        "fast paced",
        "wear many hats",
        "wearing many hats",
        "scaling",
        "ambiguity",
        "ownership"
    };

    public static readonly string[] FixableOpsKeywords =
    {
        "spreadsheet",
        "spreadsheets",
        "excel",
        "google sheets",
        "manual data entry",
        "manual entry",
        "copy/paste",
        "copy paste",
        "reconcile",
        "reconciliation",
        "handoff",
        "handoffs",
        "follow up",
        "follow-up",
        "small ops team",
        "ops team of",
        "operations team of",
        "no system",
        "no systems",
        "lack of systems",
        "multiple systems",
        "disorganized",
        "inefficient",
        "coordination"
    };

    public static readonly string[] SmbFitKeywords =
    {
        "small team",
        "lean team",
        "startup",
        "early-stage",
        "early stage",
        "series a",
        "series b",
        "first ops hire",
        "first operations hire",
        "report directly to the ceo",
        "report directly to ceo",
        "work closely with the founder",
        "founder",
        "owner-led",
        "owner led"
    };

    public JobAnalysisResult AnalyzeJob(string title, string description)
    {
        var text = ((title ?? "") + "\n" + (description ?? "")).ToLowerInvariant();

        var painMatches = MatchKeywords(text, PainKeywords);
        var growthMatches = MatchKeywords(text, GrowthKeywords);
        var fixableMatches = MatchKeywords(text, FixableOpsKeywords);
        var smbMatches = MatchKeywords(text, SmbFitKeywords);

        var painScore = painMatches.Count * 20;
        var growthScore = growthMatches.Count * 5;
        var fixableScore = fixableMatches.Count * 8;
        var smbFitScore = smbMatches.Count * 6;

        var all = painMatches.Concat(growthMatches).Distinct(StringComparer.OrdinalIgnoreCase).OrderBy(s => s).ToArray();
        var allExpanded = all
            .Concat(fixableMatches)
            .Concat(smbMatches)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(s => s)
            .ToArray();

        return new JobAnalysisResult(
            PainScore: painScore,
            GrowthScore: growthScore,
            FixableScore: fixableScore,
            SmbFitScore: smbFitScore,
            PainMatchedKeywords: painMatches,
            GrowthMatchedKeywords: growthMatches,
            FixableMatchedKeywords: fixableMatches,
            SmbMatchedKeywords: smbMatches,
            AllMatchedKeywords: allExpanded
        );
    }

    private static IReadOnlyList<string> MatchKeywords(string haystackLower, IReadOnlyList<string> keywords)
    {
        var matched = new List<string>();
        foreach (var kw in keywords)
        {
            if (haystackLower.Contains(kw, StringComparison.OrdinalIgnoreCase))
                matched.Add(kw);
        }
        return matched;
    }
}

public sealed record JobAnalysisResult(
    int PainScore,
    int GrowthScore,
    int FixableScore,
    int SmbFitScore,
    IReadOnlyList<string> PainMatchedKeywords,
    IReadOnlyList<string> GrowthMatchedKeywords,
    IReadOnlyList<string> FixableMatchedKeywords,
    IReadOnlyList<string> SmbMatchedKeywords,
    IReadOnlyList<string> AllMatchedKeywords
);
