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
            MaxResultsPerSource: 100,
            RedditLimitPerSubreddit: 40,
            CraigslistLimitPerSite: 30,
            RedditSubreddits: new[] { "Gear4Sale", "Synths4Sale", "guitarpedals" },
            CraigslistBaseUrls: new[] { "https://newyork.craigslist.org" },
            RequireIntentAndGearMatchDefault: true,
            AlertMinConfidence: 70,
            CsvPath: "gearradar_matches.csv",
            UserAgent: "GearRadar/1.0"
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
            var pr = default(JsonElement);
            if (doc.RootElement.TryGetProperty("GearRadar", out var gr) && gr.ValueKind == JsonValueKind.Object)
                pr = gr;
            else if (doc.RootElement.TryGetProperty("PainRadar", out var legacy) && legacy.ValueKind == JsonValueKind.Object)
                pr = legacy;
            else
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

            IReadOnlyList<string> GetStringList(string name, IReadOnlyList<string> fallback)
            {
                if (!pr.TryGetProperty(name, out var e))
                    return fallback;

                if (e.ValueKind == JsonValueKind.Array)
                {
                    var list = new List<string>();
                    foreach (var v in e.EnumerateArray())
                    {
                        if (v.ValueKind == JsonValueKind.String)
                        {
                            var s = (v.GetString() ?? "").Trim();
                            if (!string.IsNullOrWhiteSpace(s))
                                list.Add(s);
                        }
                    }
                    return list.Count == 0 ? fallback : list;
                }

                if (e.ValueKind == JsonValueKind.String)
                {
                    var raw = (e.GetString() ?? "").Trim();
                    if (raw.Length == 0)
                        return fallback;
                    var parts = raw.Split(new[] { ',', ';', '\n' }, StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
                    return parts.Length == 0 ? fallback : parts;
                }

                return fallback;
            }

            config = new AppConfig(
                MaxResultsPerSource: GetInt("MaxResultsPerSource", 100),
                RedditLimitPerSubreddit: GetInt("RedditLimitPerSubreddit", 40),
                CraigslistLimitPerSite: GetInt("CraigslistLimitPerSite", 30),
                RedditSubreddits: GetStringList("RedditSubreddits", new[] { "Gear4Sale", "Synths4Sale", "guitarpedals" }),
                CraigslistBaseUrls: GetStringList("CraigslistBaseUrls", new[] { "https://newyork.craigslist.org" }),
                RequireIntentAndGearMatchDefault: GetBool("RequireIntentAndGearMatchDefault", true),
                AlertMinConfidence: GetInt("AlertMinConfidence", 70),
                CsvPath: GetString("CsvPath", "gearradar_matches.csv"),
                UserAgent: GetString("UserAgent", "GearRadar/1.0")
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
