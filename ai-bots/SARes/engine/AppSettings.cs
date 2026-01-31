using System.IO;

namespace SARes.engine;

public sealed record AppSettings
{
    public string OutputDirectory { get; init; } = DefaultOutputDirectory();
    public string? PandocPath { get; init; }
    public ResumeTailoringMode ResumeTailoringMode { get; init; } = ResumeTailoringMode.CoverLetterOnly;
    public bool TailorResumeWithAi { get; init; } = false;

    // Global base resume template. If null/empty, uses bundled assets\resume\resume1.md.
    public string? BaseResumeTemplatePath { get; init; }

    // Multiple base resume templates (name -> path). One of them is selected for generation.
    public Dictionary<string, string> BaseResumeTemplates { get; init; } = new(StringComparer.OrdinalIgnoreCase);
    public string? SelectedBaseResumeTemplateName { get; init; }

    // Unlimited named summaries. Key = preset name, Value = summary text.
    public Dictionary<string, string> SummaryPresets { get; init; } = new(StringComparer.OrdinalIgnoreCase);

    // Currently selected preset name on the main screen.
    public string? SelectedPresetName { get; init; }

    // Extra header labels the user wants the PDF importer to treat as sections.
    public IReadOnlyList<string> PdfSectionHeaderAliases { get; init; } = Array.Empty<string>();

    public Dictionary<string, string[]> PdfHeaderPresets { get; init; } = new(ResumeParserDefaults.HeaderPresets, StringComparer.OrdinalIgnoreCase);
    public string? SelectedPdfHeaderPresetName { get; init; }
    public PdfLayoutMode SelectedPdfLayoutMode { get; init; } = PdfLayoutMode.SingleColumn;
    public Dictionary<string, string[]> PdfBulletizePresets { get; init; } = new(ResumeParserDefaults.BulletizePresets, StringComparer.OrdinalIgnoreCase);

    // Legacy settings (PainRadar-era "variants") kept only for migration from older settings.json.
    public Dictionary<int, string>? ResumeVariantOverridePaths { get; init; }
    public Dictionary<int, string>? VariantSummaries { get; init; }

    public static AppSettings Default() => new();

    public string ResolveBaseTemplatePath(string appBaseDirectory)
    {
        var selectedName = (SelectedBaseResumeTemplateName ?? "").Trim();
        if (selectedName.Length > 0 && BaseResumeTemplates.TryGetValue(selectedName, out var selectedPath))
        {
            var selectedTemplatePath = (selectedPath ?? "").Trim();
            if (selectedTemplatePath.Length == 0)
                return Path.Combine(appBaseDirectory, "assets", "resume", "resume1.md");
            if (!File.Exists(selectedTemplatePath))
                throw new FileNotFoundException($"Base resume template not found (\"{selectedName}\"): {selectedTemplatePath}");
            return selectedTemplatePath;
        }

        var p = (BaseResumeTemplatePath ?? "").Trim();
        if (p.Length > 0)
        {
            if (!File.Exists(p))
                throw new FileNotFoundException("Base resume template not found: " + p);
            return p;
        }

        return Path.Combine(appBaseDirectory, "assets", "resume", "resume1.md");
    }

    public IReadOnlyList<string> BaseTemplateNamesSorted()
        => BaseResumeTemplates.Keys.OrderBy(s => s, StringComparer.OrdinalIgnoreCase).ToArray();

    public string GetSelectedBaseTemplateNameOrDefault()
    {
        var selected = (SelectedBaseResumeTemplateName ?? "").Trim();
        if (selected.Length > 0 && BaseResumeTemplates.ContainsKey(selected))
            return selected;
        return BaseTemplateNamesSorted().FirstOrDefault() ?? "";
    }

    public AppSettings UpsertBaseTemplate(string templateName, string templatePath)
    {
        var name = (templateName ?? "").Trim();
        if (name.Length == 0)
            throw new ArgumentException("Template name is required.", nameof(templateName));

        var map = new Dictionary<string, string>(BaseResumeTemplates, StringComparer.OrdinalIgnoreCase)
        {
            [name] = (templatePath ?? "").Trim()
        };

        return this with { BaseResumeTemplates = map, SelectedBaseResumeTemplateName = name };
    }

    public AppSettings RenameBaseTemplate(string fromName, string toName)
    {
        var from = (fromName ?? "").Trim();
        var to = (toName ?? "").Trim();
        if (from.Length == 0)
            throw new ArgumentException("Source template name is required.", nameof(fromName));
        if (to.Length == 0)
            throw new ArgumentException("Target template name is required.", nameof(toName));

        if (!BaseResumeTemplates.TryGetValue(from, out var path))
            return this;

        var map = new Dictionary<string, string>(BaseResumeTemplates, StringComparer.OrdinalIgnoreCase);
        map.Remove(from);
        map[to] = path ?? "";

        var selected = (SelectedBaseResumeTemplateName ?? "").Trim();
        if (selected.Equals(from, StringComparison.OrdinalIgnoreCase))
            selected = to;

        return this with { BaseResumeTemplates = map, SelectedBaseResumeTemplateName = string.IsNullOrWhiteSpace(selected) ? null : selected };
    }

    public AppSettings RemoveBaseTemplate(string name)
    {
        var key = (name ?? "").Trim();
        if (key.Length == 0)
            return this;

        var map = new Dictionary<string, string>(BaseResumeTemplates, StringComparer.OrdinalIgnoreCase);
        map.Remove(key);

        var selected = (SelectedBaseResumeTemplateName ?? "").Trim();
        if (selected.Equals(key, StringComparison.OrdinalIgnoreCase))
            selected = map.Keys.OrderBy(s => s, StringComparer.OrdinalIgnoreCase).FirstOrDefault() ?? "";

        return this with { BaseResumeTemplates = map, SelectedBaseResumeTemplateName = string.IsNullOrWhiteSpace(selected) ? null : selected };
    }

    public IReadOnlyList<string> PresetNamesSorted()
        => SummaryPresets.Keys.OrderBy(s => s, StringComparer.OrdinalIgnoreCase).ToArray();

    public string GetPresetSummary(string? presetName)
    {
        var name = (presetName ?? "").Trim();
        if (name.Length == 0)
            return "";
        return SummaryPresets.TryGetValue(name, out var s) ? (s ?? "") : "";
    }

    public AppSettings UpsertPreset(string presetName, string summary)
    {
        var name = (presetName ?? "").Trim();
        if (name.Length == 0)
            throw new ArgumentException("Preset name is required.", nameof(presetName));

        var map = new Dictionary<string, string>(SummaryPresets, StringComparer.OrdinalIgnoreCase)
        {
            [name] = (summary ?? "").Trim()
        };

        var selected = (SelectedPresetName ?? "").Trim();
        if (selected.Length == 0)
            selected = name;

        return this with { SummaryPresets = map, SelectedPresetName = selected };
    }

    public AppSettings RenamePreset(string fromPresetName, string toPresetName)
    {
        var from = (fromPresetName ?? "").Trim();
        var to = (toPresetName ?? "").Trim();
        if (from.Length == 0)
            throw new ArgumentException("Source preset name is required.", nameof(fromPresetName));
        if (to.Length == 0)
            throw new ArgumentException("Target preset name is required.", nameof(toPresetName));

        if (!SummaryPresets.TryGetValue(from, out var summary))
            return this;

        var map = new Dictionary<string, string>(SummaryPresets, StringComparer.OrdinalIgnoreCase);
        map.Remove(from);
        map[to] = summary ?? "";

        var selected = (SelectedPresetName ?? "").Trim();
        if (selected.Equals(from, StringComparison.OrdinalIgnoreCase))
            selected = to;

        return this with { SummaryPresets = map, SelectedPresetName = string.IsNullOrWhiteSpace(selected) ? null : selected };
    }

    public AppSettings RemovePreset(string presetName)
    {
        var name = (presetName ?? "").Trim();
        if (name.Length == 0)
            return this;

        var map = new Dictionary<string, string>(SummaryPresets, StringComparer.OrdinalIgnoreCase);
        map.Remove(name);

        var selected = (SelectedPresetName ?? "").Trim();
        if (selected.Equals(name, StringComparison.OrdinalIgnoreCase))
            selected = map.Keys.OrderBy(s => s, StringComparer.OrdinalIgnoreCase).FirstOrDefault() ?? "";

        return this with { SummaryPresets = map, SelectedPresetName = string.IsNullOrWhiteSpace(selected) ? null : selected };
    }

    public AppSettings WithPdfSectionHeaderAliases(IEnumerable<string>? headers)
    {
        if (headers is null)
            return this with { PdfSectionHeaderAliases = Array.Empty<string>() };

        var list = headers
            .Select(h => (h ?? "").Trim())
            .Where(h => h.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        return this with { PdfSectionHeaderAliases = list };
    }

    public AppSettings WithPdfHeaderPreset(string presetName, IEnumerable<string> headers)
    {
        var name = (presetName ?? "").Trim();
        if (name.Length == 0)
            throw new ArgumentException("Preset name is required.", nameof(presetName));

        var normalized = headers
            .Select(h => (h ?? "").Trim())
            .Where(h => h.Length > 0)
            .ToArray();
        if (normalized.Length == 0)
            throw new ArgumentException("Preset must contain at least one header.", nameof(headers));

        var map = new Dictionary<string, string[]>(PdfHeaderPresets, StringComparer.OrdinalIgnoreCase)
        {
            [name] = normalized
        };

        return this with { PdfHeaderPresets = map, SelectedPdfHeaderPresetName = name };
    }

    public AppSettings WithPdfBulletizePreset(string presetName, IEnumerable<string> sectionTitlesToBulletize)
    {
        var name = (presetName ?? "").Trim();
        if (name.Length == 0)
            throw new ArgumentException("Preset name is required.", nameof(presetName));

        var normalized = sectionTitlesToBulletize
            .Select(h => (h ?? "").Trim())
            .Where(h => h.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();

        var map = new Dictionary<string, string[]>(PdfBulletizePresets, StringComparer.OrdinalIgnoreCase)
        {
            [name] = normalized
        };

        return this with { PdfBulletizePresets = map };
    }

    public AppSettings WithPdfPreset(string presetName, IEnumerable<string> headers, IEnumerable<string> sectionTitlesToBulletize)
    {
        var updated = WithPdfHeaderPreset(presetName, headers);
        updated = updated.WithPdfBulletizePreset(presetName, sectionTitlesToBulletize);
        return updated;
    }

    public IReadOnlyList<string> GetPdfHeaderPreset(string? name)
    {
        if (!string.IsNullOrWhiteSpace(name) && PdfHeaderPresets.TryGetValue(name, out var preset))
            return preset;
        if (PdfHeaderPresets.TryGetValue("Default", out var defaultPreset))
            return defaultPreset;
        return ResumeParserDefaults.SectionTitles;
    }

    public IReadOnlyList<string> GetPdfBulletizePreset(string? name)
    {
        if (!string.IsNullOrWhiteSpace(name) && PdfBulletizePresets.TryGetValue(name, out var preset))
            return preset;
        if (PdfBulletizePresets.TryGetValue("Default", out var defaultPreset))
            return defaultPreset;
        return Array.Empty<string>();
    }

    private static string DefaultOutputDirectory()
    {
        var docs = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
        return Path.Combine(docs, "SARES", "Output");
    }
}
