using System.IO;
using System.Text.Json;

namespace PainRadar.Configuration;

public static class AppConfigLoader
{
    public static AppConfig LoadFirstOrDefault(IEnumerable<string> candidatePaths)
    {
        foreach (var p in candidatePaths)
        {
            if (TryLoad(p, out var cfg))
                return cfg;
        }

        return Default();
    }

    public static (AppConfig Config, string? Path) LoadFirstOrDefaultWithPath(IEnumerable<string> candidatePaths)
    {
        foreach (var p in candidatePaths)
        {
            if (TryLoad(p, out var cfg))
                return (cfg, p);
        }

        return (Default(), null);
    }

    public static IEnumerable<string> GetCandidateConfigPaths(string startDirectory)
    {
        var env = Environment.GetEnvironmentVariable("PAINRADAR_CONFIG_PATH");
        if (!string.IsNullOrWhiteSpace(env))
            yield return env.Trim();

        var dir = startDirectory;
        while (!string.IsNullOrWhiteSpace(dir))
        {
            yield return Path.Combine(dir, "shared", "global.json");
            yield return Path.Combine(dir, "global.json");

            var parent = Directory.GetParent(dir);
            if (parent is null)
                break;
            dir = parent.FullName;
        }
    }

    public static AppConfig LoadOrDefault(string path)
    {
        return TryLoad(path, out var cfg) ? cfg : Default();
    }

    private static AppConfig Default() =>
        new(
            GooglePlacesApiKey: "",
            EnableGoogleReviews: false,
            MaxResultsPerSource: 100,
            MaxCompaniesToEnrich: 25,
            MaxEnrichmentConcurrency: 4,
            RedditSearchLimit: 10,
            UserAgent: "PainRadar/1.0"
        );

    private static bool TryLoad(string path, out AppConfig config)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
            {
                config = Default();
                return false;
            }

            using var stream = File.OpenRead(path);
            using var doc = JsonDocument.Parse(stream);
            if (!doc.RootElement.TryGetProperty("PainRadar", out var pr) || pr.ValueKind != JsonValueKind.Object)
            {
                config = Default();
                return false;
            }

            string GetString(string name, string fallback)
                => pr.TryGetProperty(name, out var e) && e.ValueKind == JsonValueKind.String ? e.GetString() ?? fallback : fallback;

            int GetInt(string name, int fallback)
                => pr.TryGetProperty(name, out var e) && e.ValueKind == JsonValueKind.Number && e.TryGetInt32(out var v) ? v : fallback;

            bool GetBool(string name, bool fallback)
                => pr.TryGetProperty(name, out var e) && (e.ValueKind == JsonValueKind.True || e.ValueKind == JsonValueKind.False) ? e.GetBoolean() : fallback;

            config = new AppConfig(
                GooglePlacesApiKey: GetString("GooglePlacesApiKey", ""),
                EnableGoogleReviews: GetBool("EnableGoogleReviews", false),
                MaxResultsPerSource: GetInt("MaxResultsPerSource", 100),
                MaxCompaniesToEnrich: GetInt("MaxCompaniesToEnrich", 25),
                MaxEnrichmentConcurrency: GetInt("MaxEnrichmentConcurrency", 4),
                RedditSearchLimit: GetInt("RedditSearchLimit", 10),
                UserAgent: GetString("UserAgent", "PainRadar/1.0")
            );
            return true;
        }
        catch
        {
            config = Default();
            return false;
        }
    }
}
