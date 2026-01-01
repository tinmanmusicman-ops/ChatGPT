using System;
using System.IO;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text;

namespace DiskInsight;

internal static class UserSettings
{
    private sealed class SettingsModel
    {
        public float OutputFontSizePt { get; set; } = DefaultOutputFontSizePt;
        public bool EiEnabled { get; set; } = false;
        public string? EiEndpoint { get; set; }
        public string? EiApiKeyProtected { get; set; }
    }

    private const float DefaultOutputFontSizePt = 10f;
    private static readonly string SettingsPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "DiskInsight",
        "settings.json");

    public static float LoadOutputFontSizePt()
    {
        try
        {
            if (!File.Exists(SettingsPath))
            {
                return DefaultOutputFontSizePt;
            }

            var json = File.ReadAllText(SettingsPath);
            var model = JsonSerializer.Deserialize<SettingsModel>(json);
            return model?.OutputFontSizePt is > 0 ? model.OutputFontSizePt : DefaultOutputFontSizePt;
        }
        catch
        {
            return DefaultOutputFontSizePt;
        }
    }

    public static void SaveOutputFontSizePt(float sizePt)
    {
        try
        {
            var model = LoadModel();
            model.OutputFontSizePt = sizePt;
            SaveModel(model);
        }
        catch
        {
        }
    }

    public static bool LoadEiEnabled()
    {
        try
        {
            return LoadModel().EiEnabled;
        }
        catch
        {
            return false;
        }
    }

    public static void SaveEiEnabled(bool enabled)
    {
        try
        {
            var model = LoadModel();
            model.EiEnabled = enabled;
            SaveModel(model);
        }
        catch
        {
        }
    }

    public static string? LoadEiEndpoint()
    {
        try
        {
            return LoadModel().EiEndpoint;
        }
        catch
        {
            return null;
        }
    }

    public static string? LoadEiApiKey()
    {
        try
        {
            var protectedBase64 = LoadModel().EiApiKeyProtected;
            if (string.IsNullOrWhiteSpace(protectedBase64))
            {
                return null;
            }

            var protectedBytes = Convert.FromBase64String(protectedBase64);
            var bytes = ProtectedData.Unprotect(protectedBytes, optionalEntropy: null, scope: DataProtectionScope.CurrentUser);
            return Encoding.UTF8.GetString(bytes);
        }
        catch
        {
            return null;
        }
    }

    public static bool TrySaveEiConfig(string endpoint, string apiKey, out string error)
    {
        error = string.Empty;
        if (string.IsNullOrWhiteSpace(endpoint) || !Uri.TryCreate(endpoint, UriKind.Absolute, out _))
        {
            error = "EI endpoint must be a valid absolute URL.";
            return false;
        }

        if (string.IsNullOrWhiteSpace(apiKey))
        {
            error = "EI API key is required.";
            return false;
        }

        try
        {
            var protectedBytes = ProtectedData.Protect(Encoding.UTF8.GetBytes(apiKey.Trim()), optionalEntropy: null, scope: DataProtectionScope.CurrentUser);
            var protectedBase64 = Convert.ToBase64String(protectedBytes);

            var model = LoadModel();
            model.EiEndpoint = endpoint.Trim();
            model.EiApiKeyProtected = protectedBase64;
            SaveModel(model);
            return true;
        }
        catch (Exception ex)
        {
            error = "Failed to save EI settings: " + ex.Message;
            return false;
        }
    }

    private static SettingsModel LoadModel()
    {
        try
        {
            if (!File.Exists(SettingsPath))
            {
                return new SettingsModel();
            }

            var json = File.ReadAllText(SettingsPath);
            return JsonSerializer.Deserialize<SettingsModel>(json) ?? new SettingsModel();
        }
        catch
        {
            return new SettingsModel();
        }
    }

    private static void SaveModel(SettingsModel model)
    {
        var directory = Path.GetDirectoryName(SettingsPath);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            Directory.CreateDirectory(directory);
        }

        var json = JsonSerializer.Serialize(model, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(SettingsPath, json);
    }
}
