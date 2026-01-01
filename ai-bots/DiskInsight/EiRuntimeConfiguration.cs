using System;
using System.IO;
using System.Text.Json;

namespace DiskInsight;

internal static class EiRuntimeConfiguration
{
    public static bool TryGet(out Uri endpoint, out string apiKey, out string error)
    {
        endpoint = null!;
        apiKey = string.Empty;
        error = string.Empty;

        var endpointString =
            Environment.GetEnvironmentVariable("DISKINSIGHT_EI_ENDPOINT") ??
            UserSettings.LoadEiEndpoint() ??
            TryReadFromGlobalJson("diskinsight_ei_endpoint") ??
            TryReadFromGlobalJson("ei_endpoint");

        var apiKeyString =
            Environment.GetEnvironmentVariable("DISKINSIGHT_EI_API_KEY") ??
            UserSettings.LoadEiApiKey() ??
            TryReadFromGlobalJson("diskinsight_ei_api_key") ??
            TryReadFromGlobalJson("ei_api_key") ??
            TryReadFromGlobalJson("openai_api_key");

        if (string.IsNullOrWhiteSpace(endpointString) && !string.IsNullOrWhiteSpace(apiKeyString))
        {
            endpointString = "https://api.openai.com/v1/chat/completions";
        }

        if (string.IsNullOrWhiteSpace(endpointString))
        {
            error =
                "EI endpoint is not configured.\r\n\r\n" +
                "Set DISKINSIGHT_EI_ENDPOINT, or add 'ei_endpoint' to Global.json.";
            return false;
        }

        if (!Uri.TryCreate(endpointString.Trim(), UriKind.Absolute, out var endpointResult) || endpointResult is null)
        {
            error = "EI endpoint is not a valid absolute URL.";
            return false;
        }
        endpoint = endpointResult;

        if (string.IsNullOrWhiteSpace(apiKeyString))
        {
            error =
                "EI API key is not configured.\r\n\r\n" +
                "Set DISKINSIGHT_EI_API_KEY, or add 'ei_api_key' to Global.json.";
            return false;
        }

        apiKey = apiKeyString.Trim();
        return true;
    }

    private static string? TryReadFromGlobalJson(string key)
    {
        try
        {
            var path = FindGlobalJsonPath();
            if (path is null || !File.Exists(path))
            {
                return null;
            }

            var json = File.ReadAllText(path);
            using var doc = JsonDocument.Parse(json);
            return TryGetStringCaseInsensitive(doc.RootElement, key);
        }
        catch
        {
            return null;
        }
    }

    private static string? FindGlobalJsonPath()
    {
        // Prefer explicit override.
        var explicitPath = Environment.GetEnvironmentVariable("DISKINSIGHT_EI_CONFIG_PATH");
        if (!string.IsNullOrWhiteSpace(explicitPath) && File.Exists(explicitPath))
        {
            return explicitPath;
        }

        var dir = AppContext.BaseDirectory;
        for (var i = 0; i < 10 && !string.IsNullOrWhiteSpace(dir); i++)
        {
            var candidate1 = Path.Combine(dir, "Global.json");
            if (File.Exists(candidate1))
            {
                return candidate1;
            }

            var candidate2 = Path.Combine(dir, "shared", "Global.json");
            if (File.Exists(candidate2))
            {
                return candidate2;
            }

            var candidate3 = Path.Combine(dir, "ai-bots", "shared", "Global.json");
            if (File.Exists(candidate3))
            {
                return candidate3;
            }

            dir = Directory.GetParent(dir)?.FullName;
        }

        return null;
    }

    private static string? TryGetStringCaseInsensitive(JsonElement element, string key)
    {
        if (element.ValueKind != JsonValueKind.Object)
        {
            return null;
        }

        foreach (var prop in element.EnumerateObject())
        {
            if (string.Equals(prop.Name, key, StringComparison.OrdinalIgnoreCase) && prop.Value.ValueKind == JsonValueKind.String)
            {
                return prop.Value.GetString();
            }
        }

        return null;
    }
}
