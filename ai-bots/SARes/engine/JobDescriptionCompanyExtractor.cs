using System;

namespace SARes.engine;

public static class JobDescriptionCompanyExtractor
{
    public static string ExtractCompanyName(string jobDescription)
    {
        var jd = (jobDescription ?? "").Replace("\r\n", "\n").Replace("\r", "\n").Trim();
        if (jd.Length == 0)
            return "";

        string? company = null;
        var expectingCompanyValue = false;

        foreach (var raw in jd.Split('\n'))
        {
            var line = (raw ?? "").Trim();
            if (line.Length == 0)
                continue;

            if (expectingCompanyValue && company is null)
            {
                if (!LooksLikeLabeledField(line))
                    company = line.Trim();
                expectingCompanyValue = false;
                continue;
            }

            if (company is null)
            {
                var v = TryExtractLabeledValueAllowEmpty(line, "Company", "Company Name", "Employer");
                if (v is not null)
                {
                    if (v.Length > 0) company = v;
                    else expectingCompanyValue = true;
                    continue;
                }
            }

            if (company is not null)
                break;
        }

        return (company ?? "").Trim();
    }

    private static string? TryExtractLabeledValueAllowEmpty(string line, params string[] labels)
    {
        foreach (var label in labels)
        {
            var prefix = label + ":";
            if (line.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                var value = line.Substring(prefix.Length).Trim();
                return value;
            }
        }
        return null;
    }

    private static bool LooksLikeLabeledField(string line)
    {
        var t = (line ?? "").Trim();
        if (t.Length == 0)
            return false;

        var idx = t.IndexOf(':', StringComparison.Ordinal);
        return idx >= 1 && idx <= 20;
    }
}

