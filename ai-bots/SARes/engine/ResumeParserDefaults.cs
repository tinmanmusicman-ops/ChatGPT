using System.Collections.Generic;

namespace SARes.engine;

internal static class ResumeParserDefaults
{
    public static IReadOnlyList<string> SectionTitles { get; } = new[]
    {
        "Summary",
        "Core Skills",
        "Achievements",
        "Professional Experience",
        "Education",
        "Certifications"
    };

    public static IReadOnlyDictionary<string, string[]> HeaderPresets { get; } = new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
    {
        ["Default"] = SectionTitles.ToArray(),
        ["ATS Friendly"] = new[]
        {
            "Summary",
            "Core Skills",
            "Technical Skills",
            "Professional Experience",
            "Education",
            "Certifications"
        }
    };

    public static IReadOnlyDictionary<string, string[]> BulletizePresets { get; } = new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
    {
        // Default behavior: bulletize Core Skills (PDF extractions frequently lose bullet markers).
        ["Default"] = new[] { "Core Skills" },
        ["ATS Friendly"] = new[] { "Core Skills", "Technical Skills" }
    };
}
