using System.IO;
using System.Linq;
using System.Text.Json;

namespace SARes.engine;

public static class AppSettingsStore
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    public static AppSettings LoadOrDefault()
    {
        try
        {
            var path = SettingsPath();
            if (!File.Exists(path))
                return AppSettings.Default();

            var json = File.ReadAllText(path);
            var loaded = JsonSerializer.Deserialize<AppSettings>(json);
            if (loaded is null)
                return AppSettings.Default();

            var dir = (loaded.OutputDirectory ?? "").Trim();
            if (dir.Length == 0)
                return AppSettings.Default();

            var migrated = MigrateLegacyVariantSettings(loaded);
            migrated = MigrateLegacyResumeTailoringMode(migrated);
            migrated = MigrateLegacyBaseTemplates(migrated);
            return migrated with { OutputDirectory = dir };
        }
        catch
        {
            return AppSettings.Default();
        }
    }

    public static void Save(AppSettings settings)
    {
        try
        {
            var path = SettingsPath();
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllText(path, JsonSerializer.Serialize(settings, JsonOptions));
        }
        catch
        {
        }
    }

    private static string SettingsPath()
    {
        var appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        return Path.Combine(appData, "SARES", "settings.json");
    }

    private static AppSettings MigrateLegacyVariantSettings(AppSettings settings)
    {
        var basePath = (settings.BaseResumeTemplatePath ?? "").Trim();
        if (basePath.Length == 0 && settings.ResumeVariantOverridePaths is { Count: > 0 })
        {
            if (settings.ResumeVariantOverridePaths.TryGetValue(1, out var v1) && !string.IsNullOrWhiteSpace(v1))
                basePath = v1.Trim();
            else
                basePath = settings.ResumeVariantOverridePaths.Values.FirstOrDefault(p => !string.IsNullOrWhiteSpace(p))?.Trim() ?? "";
        }

        var presets = settings.SummaryPresets ?? new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        string? selected = settings.SelectedPresetName;

        if (presets.Count == 0 && settings.VariantSummaries is { Count: > 0 })
        {
            presets = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var kvp in settings.VariantSummaries.OrderBy(k => k.Key))
                presets[$"Summary {kvp.Key}"] = (kvp.Value ?? "").Trim();

            selected = presets.Keys.FirstOrDefault();
        }

        // Drop legacy fields once migrated.
        var cleaned = settings with
        {
            BaseResumeTemplatePath = basePath.Length == 0 ? null : basePath,
            SummaryPresets = presets,
            SelectedPresetName = string.IsNullOrWhiteSpace(selected) ? null : selected,
            ResumeVariantOverridePaths = null,
            VariantSummaries = null
        };

        return cleaned;
    }

    private static AppSettings MigrateLegacyResumeTailoringMode(AppSettings settings)
    {
        // Older settings only had TailorResumeWithAi (bool). Map it to the new 3-mode selector.
        if (settings.TailorResumeWithAi && settings.ResumeTailoringMode == ResumeTailoringMode.CoverLetterOnly)
            return settings with { ResumeTailoringMode = ResumeTailoringMode.Light };
        return settings;
    }

    private static AppSettings MigrateLegacyBaseTemplates(AppSettings settings)
    {
        // Legacy: single BaseResumeTemplatePath.
        // New: multiple templates with a selected name.
        if (settings.BaseResumeTemplates.Count > 0)
        {
            var selected = (settings.SelectedBaseResumeTemplateName ?? "").Trim();
            if (selected.Length == 0)
                selected = settings.BaseTemplateNamesSorted().FirstOrDefault() ?? "";
            return settings with { SelectedBaseResumeTemplateName = string.IsNullOrWhiteSpace(selected) ? null : selected };
        }

        var legacyPath = (settings.BaseResumeTemplatePath ?? "").Trim();
        if (legacyPath.Length == 0)
            return settings;

        var migrated = settings.UpsertBaseTemplate("Base", legacyPath);
        return migrated with { BaseResumeTemplatePath = null };
    }
}
