using System.IO;
using System.Text.Json;

namespace PainRadar.Configuration;

public static class PainRadarUiSettingsStore
{
    public static PainRadarUiSettings? Load(string path)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
                return null;

            var json = File.ReadAllText(path);
            return JsonSerializer.Deserialize<PainRadarUiSettings>(json);
        }
        catch
        {
            return null;
        }
    }

    public static void Save(string path, PainRadarUiSettings settings)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(path))
                return;

            var dir = Path.GetDirectoryName(path);
            if (!string.IsNullOrWhiteSpace(dir))
                Directory.CreateDirectory(dir);

            var json = JsonSerializer.Serialize(settings, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(path, json);
        }
        catch
        {
        }
    }
}
