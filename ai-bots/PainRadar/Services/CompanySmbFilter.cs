using System.Text.RegularExpressions;
using PainRadar.Infrastructure;
using PainRadar.Models;

namespace PainRadar.Services;

public sealed class CompanySmbFilter
{
    private static readonly string[] EnterpriseIndicators =
    {
        "enterprise",
        "global",
        "corporation",
        "fortune",
        "shareholder",
        "public company",
        "publicly traded",
        "sec reporting",
        "sox",
        "sarbanes",
        "compliance-heavy",
        "compliance heavy",
        "enterprise-scale",
        "enterprise scale",
        "multinational",
        "worldwide",
        "global presence",
        "fortune 500",
        "fortune500",
        "nyse",
        "nasdaq",
        "big four",
        "audit committee"
    };

    private static readonly string[] BrandExclusions =
    {
        // Big tech / platforms
        "google", "alphabet", "amazon", "microsoft", "meta", "facebook", "apple", "netflix", "tesla",
        "oracle", "ibm", "salesforce", "adobe",

        // Big retail
        "walmart", "target", "costco", "home depot", "lowe's", "lowes", "kroger", "cvs", "walgreens",

        // Major banks / finance
        "jpmorgan", "jp morgan", "jpmorgan chase", "chase bank", "bank of america", "wells fargo", "citibank", "goldman sachs",
        "morgan stanley", "hsbc", "barclays"
    };

    private static readonly string[] SmbSignals =
    {
        "small team",
        "lean team",
        "tiny team",
        "wear many hats",
        "wearing many hats",
        "report directly to the ceo",
        "report directly to ceo",
        "reporting to the ceo",
        "work closely with the founder",
        "founder",
        "owner-led",
        "owner led",
        "startup",
        "early-stage",
        "early stage",
        "series a",
        "series b",
        "growing fast",
        "rapid growth",
        "ops team of",
        "operations team of",
        "small ops team",
        "no dedicated",
        "no systems",
        "lack of systems",
        "build processes",
        "build the function",
        "first ops hire",
        "first operations hire"
    };

    public CompanyDecision DecideCompany(string company, IReadOnlyList<SignalItem> items)
    {
        var normalizedCompany = (company ?? "").Trim();
        var combinedText = BuildCombinedText(normalizedCompany, items);

        var reasons = new List<CompanyExclusionReason>();

        // Brand exclusions (name-only, to reduce false positives from generic job text)
        foreach (var brand in BrandExclusions)
        {
            if (normalizedCompany.Contains(brand, StringComparison.OrdinalIgnoreCase))
            {
                reasons.Add(new CompanyExclusionReason(CompanyExclusionKind.Brand, $"Brand match: \"{brand}\""));
                break;
            }
        }

        // Enterprise indicators (name + content)
        foreach (var indicator in EnterpriseIndicators)
        {
            if (combinedText.Contains(indicator, StringComparison.OrdinalIgnoreCase))
            {
                reasons.Add(new CompanyExclusionReason(CompanyExclusionKind.EnterpriseIndicator, $"Indicator: \"{indicator}\""));
                break;
            }
        }

        // Employee count (content)
        var estimate = EmployeeCountEstimator.TryEstimate(combinedText);
        if (estimate is not null)
        {
            if (estimate.MinEmployees > 200 || estimate.MaxEmployees > 200)
                reasons.Add(new CompanyExclusionReason(CompanyExclusionKind.Size, $"Employee estimate {estimate.MinEmployees}-{estimate.MaxEmployees} (>200)"));
            else if (estimate.MaxEmployees < 5)
                reasons.Add(new CompanyExclusionReason(CompanyExclusionKind.Size, $"Employee estimate {estimate.MinEmployees}-{estimate.MaxEmployees} (<5)"));
        }

        // Unknown size: include only if SMB language is present (default SMB-focused)
        var smbMatches = MatchAll(combinedText, SmbSignals);

        if (reasons.Count > 0)
            return CompanyDecision.Excluded(normalizedCompany, estimate, reasons);

        if (estimate is not null)
        {
            // Explicitly include only 5–200 when known
            if (estimate.MinEmployees >= 5 && estimate.MaxEmployees <= 200)
                return CompanyDecision.Included(normalizedCompany, estimate, smbMatches);

            return CompanyDecision.Excluded(normalizedCompany, estimate,
                new[] { new CompanyExclusionReason(CompanyExclusionKind.Size, $"Employee estimate {estimate.MinEmployees}-{estimate.MaxEmployees} (outside 5–200)") });
        }

        if (smbMatches.Count > 0)
            return CompanyDecision.Included(normalizedCompany, null, smbMatches);

        // Conservative default: unknown size with no SMB signals => exclude
        return CompanyDecision.Excluded(normalizedCompany, null,
            new[] { new CompanyExclusionReason(CompanyExclusionKind.Size, "Unknown size and no SMB signals") });
    }

    public static void LogDecision(CompanyDecision decision)
    {
        if (decision.IsIncluded)
            return;

        var parts = decision.ExclusionReasons.Select(r => $"{r.Kind}: {r.Detail}");
        var size = decision.EmployeeEstimate is null ? "unknown" : $"{decision.EmployeeEstimate.MinEmployees}-{decision.EmployeeEstimate.MaxEmployees}";
        AppLogger.Info($"SMB filter excluded company=\"{decision.Company}\" size={size} reasons=[{string.Join("; ", parts)}]");
    }

    private static string BuildCombinedText(string company, IReadOnlyList<SignalItem> items)
    {
        var lines = new List<string>(1 + items.Count * 3) { company };
        foreach (var i in items)
        {
            lines.Add(i.JobTitle);
            lines.Add(i.Description);
            lines.Add(i.Location);
        }
        return string.Join("\n", lines.Where(s => !string.IsNullOrWhiteSpace(s)));
    }

    private static IReadOnlyList<string> MatchAll(string haystack, IReadOnlyList<string> needles)
    {
        var list = new List<string>();
        foreach (var n in needles)
        {
            if (haystack.Contains(n, StringComparison.OrdinalIgnoreCase))
                list.Add(n);
        }
        return list;
    }
}

public enum CompanyExclusionKind
{
    Size,
    EnterpriseIndicator,
    Brand
}

public sealed record CompanyExclusionReason(CompanyExclusionKind Kind, string Detail);

public sealed record EmployeeEstimate(int MinEmployees, int MaxEmployees, string Source);

public sealed record CompanyDecision(
    string Company,
    bool IsIncluded,
    EmployeeEstimate? EmployeeEstimate,
    IReadOnlyList<string> SmbSignalsMatched,
    IReadOnlyList<CompanyExclusionReason> ExclusionReasons)
{
    public bool IsExcluded => !IsIncluded;

    public static CompanyDecision Included(string company, EmployeeEstimate? estimate, IReadOnlyList<string> smbSignalsMatched) =>
        new(company, true, estimate, smbSignalsMatched, Array.Empty<CompanyExclusionReason>());

    public static CompanyDecision Excluded(string company, EmployeeEstimate? estimate, IEnumerable<CompanyExclusionReason> reasons) =>
        new(company, false, estimate, Array.Empty<string>(), reasons.ToArray());
}

internal static class EmployeeCountEstimator
{
    // Examples:
    // - "500+ employees"
    // - "1,200 employees"
    // - "team of 50"
    // - "between 50 and 150 employees"
    // - "50-200 employees"
    private static readonly Regex RangeRegex = new(@"(?<min>\d{1,5}(?:,\d{3})?)\s*[-–]\s*(?<max>\d{1,5}(?:,\d{3})?)\s*(?:employees|people|team members|staff)", RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex BetweenRegex = new(@"between\s+(?<min>\d{1,5}(?:,\d{3})?)\s+and\s+(?<max>\d{1,5}(?:,\d{3})?)\s*(?:employees|people|team members|staff)", RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex PlusRegex = new(@"(?<min>\d{1,5}(?:,\d{3})?)\s*\+\s*(?:employees|people|team members|staff)", RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex ExactRegex = new(@"(?<n>\d{1,5}(?:,\d{3})?)\s*(?:employees|people|team members|staff)", RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex TeamOfRegex = new(@"(?:team of|ops team of|operations team of)\s+(?<n>\d{1,5}(?:,\d{3})?)", RegexOptions.IgnoreCase | RegexOptions.Compiled);

    public static EmployeeEstimate? TryEstimate(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return null;

        var t = text;
        var range = RangeRegex.Match(t);
        if (range.Success)
            return new EmployeeEstimate(Parse(range.Groups["min"].Value), Parse(range.Groups["max"].Value), "range");

        var between = BetweenRegex.Match(t);
        if (between.Success)
            return new EmployeeEstimate(Parse(between.Groups["min"].Value), Parse(between.Groups["max"].Value), "between");

        var plus = PlusRegex.Match(t);
        if (plus.Success)
        {
            var min = Parse(plus.Groups["min"].Value);
            // Interpret "<n>+ employees" conservatively:
            // - If n < 200, treat as SMB upper-bounded to 200 (still consistent with target range).
            // - If n >= 200, treat as likely >200 and exclude via max > 200.
            var max = min < 200 ? 200 : min + 500;
            return new EmployeeEstimate(min, max, "plus");
        }

        var team = TeamOfRegex.Match(t);
        if (team.Success)
        {
            var n = Parse(team.Groups["n"].Value);
            return new EmployeeEstimate(n, n, "team");
        }

        var exact = ExactRegex.Match(t);
        if (exact.Success)
        {
            var n = Parse(exact.Groups["n"].Value);
            // treat as approximate
            return new EmployeeEstimate(Math.Max(1, n - 5), n + 5, "exact");
        }

        return null;
    }

    private static int Parse(string s)
    {
        if (string.IsNullOrWhiteSpace(s))
            return 0;
        s = s.Replace(",", "");
        return int.TryParse(s, out var n) ? n : 0;
    }
}
