using System;
using System.IO;
using System.Text.Json;

namespace DiskInsight;

internal static class UserSettings
{
    private sealed class SettingsModel
    {
        public float OutputFontSizePt { get; set; } = DefaultOutputFontSizePt;
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
            var directory = Path.GetDirectoryName(SettingsPath);
            if (!string.IsNullOrWhiteSpace(directory))
            {
                Directory.CreateDirectory(directory);
            }

            var model = new SettingsModel { OutputFontSizePt = sizePt };
            var json = JsonSerializer.Serialize(model, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(SettingsPath, json);
        }
        catch
        {
        }
    }
}

