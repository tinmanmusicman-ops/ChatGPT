using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using SARes.engine;

namespace SARes.ui;

public partial class TemplatesAndSummariesWindow : Window
{
    private const string BundledTemplateName = "(Bundled)";
    private AppSettings _settings;
    private readonly Func<string> _getCurrentMainSummary;

    public TemplatesAndSummariesWindow(AppSettings settings, Func<string> getCurrentMainSummary)
    {
        InitializeComponent();
        _settings = settings;
        _getCurrentMainSummary = getCurrentMainSummary;

        UseBundledBaseTemplateButton.Click += (_, _) => UseBundledTemplate();
        EditBaseTemplateButton.Click += (_, _) => EditBaseTemplate();
        ImportPdfButton.Click += (_, _) => ImportPdf();
        ImportMdButton.Click += (_, _) => ImportMarkdown();
        NewBaseTemplateButton.Click += (_, _) => CreateNewBaseTemplateCopy();
        RenameBaseTemplateButton.Click += (_, _) => RenameBaseTemplate();
        DeleteBaseTemplateButton.Click += (_, _) => DeleteBaseTemplate();
        BaseTemplateComboBox.SelectionChanged += (_, _) => SwitchBaseTemplate();

        PresetList.SelectionChanged += (_, _) => LoadSelectedPresetIntoEditor();
        AddPresetButton.Click += (_, _) => AddPreset();
        RenamePresetButton.Click += (_, _) => RenamePreset();
        DeletePresetButton.Click += (_, _) => DeletePreset();
        EditPresetButton.Click += (_, _) => EditSelectedPreset();
        LoadFromMainButton.Click += (_, _) => SummaryPresetTextBox.Text = (_getCurrentMainSummary() ?? "").Trim();

        SaveButton.Click += (_, _) => SaveAndKeepOpen();
        CloseButton.Click += (_, _) => Close();

        ReloadBaseTemplatesUi();
        ReloadPresetsUi(selectName: _settings.SelectedPresetName);

        DialogStatus.Text = "Ready";
    }

    public AppSettings UpdatedSettings => _settings;

    private void UseBundledTemplate()
    {
        _settings = _settings with { SelectedBaseResumeTemplateName = null, BaseResumeTemplatePath = null };
        AppSettingsStore.Save(_settings);
        ReloadBaseTemplatesUi(selectName: BundledTemplateName);
        DialogStatus.Text = "Using bundled base template.";
    }

    private void ImportPdf()
    {
        string? initialPdfPath = null;
        if ((_settings.PdfSectionHeaderAliases ?? Array.Empty<string>()).Count == 0)
        {
            var mapDlg = new PdfMapBuilderWindow(_settings) { Owner = this };
            if (mapDlg.ShowDialog() != true)
                return;
            _settings = mapDlg.UpdatedSettings;
            initialPdfPath = mapDlg.SelectedPdfPath;
        }

        var dlg = new ImportPdfWindow(_settings, initialPdfPath) { Owner = this };
        dlg.ShowDialog();
        _settings = dlg.UpdatedSettings;
        ReloadBaseTemplatesUi();
        DialogStatus.Text = "Imported base resume template.";
    }

    private void EditBaseTemplate()
    {
        var dlg = new EditBaseTemplateWindow(_settings) { Owner = this };
        dlg.ShowDialog();
        _settings = dlg.UpdatedSettings;
        ReloadBaseTemplatesUi();
        DialogStatus.Text = "Base template updated.";
    }

    private void ImportMarkdown()
    {
        var dlg = new Microsoft.Win32.OpenFileDialog
        {
            Title = "Select resume Markdown (.md) to store as a base template",
            Filter = "Markdown (*.md)|*.md|All files (*.*)|*.*"
        };
        if (dlg.ShowDialog() != true)
            return;

        try
        {
            var content = MarkdownResumeImporter.ImportMarkdownToTemplate(dlg.FileName);

            var defaultName = _settings.GetSelectedBaseTemplateNameOrDefault();
            if (string.IsNullOrWhiteSpace(defaultName))
                defaultName = "Base";

            var name = PromptDialogs.PromptForText(this, "Save Base Resume Template", "Template name:", defaultName) ?? "";
            name = name.Trim();
            if (name.Length == 0)
                return;

            var templatesDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "SARES",
                "Templates");
            Directory.CreateDirectory(templatesDir);

            var fileSegment = SafeFileNames.ToSafeFileSegment(name);
            if (fileSegment.Length == 0)
                throw new InvalidOperationException("Template name results in an invalid filename.");

            var outPath = Path.Combine(templatesDir, $"resume_{fileSegment}.md");
            File.WriteAllText(outPath, content);

            _settings = _settings.UpsertBaseTemplate(name, outPath) with { BaseResumeTemplatePath = null };
            AppSettingsStore.Save(_settings);

            ReloadBaseTemplatesUi(selectName: name);
            DialogStatus.Text = $"Imported base resume template: {name}";
        }
        catch (Exception ex)
        {
            DialogStatus.Text = "Import failed: " + ex.Message;
            System.Windows.MessageBox.Show(ex.Message, "Import failed", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void ReloadBaseTemplatesUi(string? selectName = null)
    {
        var names = _settings.BaseTemplateNamesSorted().ToList();
        names.Insert(0, BundledTemplateName);

        BaseTemplateComboBox.ItemsSource = names;

        var target = (selectName ?? "").Trim();
        if (target.Length == 0)
        {
            target = (_settings.SelectedBaseResumeTemplateName ?? "").Trim();
            if (target.Length == 0)
                target = BundledTemplateName;
        }

        BaseTemplateComboBox.SelectedItem = names.FirstOrDefault(n => n.Equals(target, StringComparison.OrdinalIgnoreCase))
                                            ?? BundledTemplateName;

        UpdateBaseTemplatePathText();
    }

    private void SwitchBaseTemplate()
    {
        var selected = (BaseTemplateComboBox.SelectedItem as string) ?? "";
        if (selected.Length == 0)
            return;

        if (selected.Equals(BundledTemplateName, StringComparison.OrdinalIgnoreCase))
        {
            _settings = _settings with { SelectedBaseResumeTemplateName = null, BaseResumeTemplatePath = null };
            AppSettingsStore.Save(_settings);
            UpdateBaseTemplatePathText();
            return;
        }

        if (!_settings.BaseResumeTemplates.ContainsKey(selected))
            return;

        _settings = _settings with { SelectedBaseResumeTemplateName = selected, BaseResumeTemplatePath = null };
        AppSettingsStore.Save(_settings);
        UpdateBaseTemplatePathText();
    }

    private void UpdateBaseTemplatePathText()
    {
        var selected = (BaseTemplateComboBox.SelectedItem as string) ?? "";
        if (selected.Equals(BundledTemplateName, StringComparison.OrdinalIgnoreCase) || selected.Length == 0)
        {
            BaseTemplatePathTextBox.Text = "(bundled assets/resume/resume1.md)";
            return;
        }

        if (_settings.BaseResumeTemplates.TryGetValue(selected, out var path))
            BaseTemplatePathTextBox.Text = path ?? "";
        else
            BaseTemplatePathTextBox.Text = "";
    }

    private void RenameBaseTemplate()
    {
        var current = (BaseTemplateComboBox.SelectedItem as string) ?? "";
        if (current.Length == 0 || current.Equals(BundledTemplateName, StringComparison.OrdinalIgnoreCase))
            return;

        var next = PromptDialogs.PromptForText(this, "Rename Base Template", "New name:", current);
        if (string.IsNullOrWhiteSpace(next))
            return;

        _settings = _settings.RenameBaseTemplate(current, next.Trim());
        AppSettingsStore.Save(_settings);

        ReloadBaseTemplatesUi(selectName: next);
        DialogStatus.Text = $"Renamed: {current} -> {next}";
    }

    private void DeleteBaseTemplate()
    {
        var current = (BaseTemplateComboBox.SelectedItem as string) ?? "";
        if (current.Length == 0 || current.Equals(BundledTemplateName, StringComparison.OrdinalIgnoreCase))
            return;

        if (_settings.BaseResumeTemplates.Count <= 1)
        {
            System.Windows.MessageBox.Show("You must keep at least one saved base template (or choose bundled).", "SARes", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        if (System.Windows.MessageBox.Show($"Delete base template \"{current}\"?", "SARes", MessageBoxButton.YesNo, MessageBoxImage.Warning) != System.Windows.MessageBoxResult.Yes)
            return;

        _settings = _settings.RemoveBaseTemplate(current);
        AppSettingsStore.Save(_settings);

        ReloadBaseTemplatesUi();
        DialogStatus.Text = $"Deleted: {current}";
    }

    private void CreateNewBaseTemplateCopy()
    {
        try
        {
            var currentName = (BaseTemplateComboBox.SelectedItem as string) ?? "";
            var assets = new AssetLocator(AppContext.BaseDirectory);

            string sourcePath;
            if (currentName.Equals(BundledTemplateName, StringComparison.OrdinalIgnoreCase) || currentName.Length == 0)
            {
                sourcePath = assets.GetBaseResumeTemplatePath(null);
                currentName = "Bundled";
            }
            else if (_settings.BaseResumeTemplates.TryGetValue(currentName, out var selectedPath) && !string.IsNullOrWhiteSpace(selectedPath))
            {
                sourcePath = selectedPath!;
            }
            else
            {
                sourcePath = assets.GetBaseResumeTemplatePath(_settings);
            }

            var defaultName = currentName + " Copy";
            var name = PromptDialogs.PromptForText(this, "New Base Template", "New template name:", defaultName) ?? "";
            name = name.Trim();
            if (name.Length == 0)
                return;

            var md = File.Exists(sourcePath) ? File.ReadAllText(sourcePath) : "";
            if (md.Length == 0)
                md = "# Resume\n\n";

            var templatesDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "SARES",
                "Templates");
            Directory.CreateDirectory(templatesDir);

            var fileSegment = SafeFileNames.ToSafeFileSegment(name);
            if (fileSegment.Length == 0)
            {
                System.Windows.MessageBox.Show("Template name results in an invalid filename.", "SARes", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            var outPath = Path.Combine(templatesDir, $"resume_{fileSegment}.md");
            File.WriteAllText(outPath, md.TrimEnd() + "\n");

            _settings = _settings.UpsertBaseTemplate(name, outPath) with { BaseResumeTemplatePath = null };
            AppSettingsStore.Save(_settings);

            ReloadBaseTemplatesUi(selectName: name);
            DialogStatus.Text = $"Created: {name}";
        }
        catch (Exception ex)
        {
            DialogStatus.Text = "Create failed: " + ex.Message;
            System.Windows.MessageBox.Show(ex.Message, "Create failed", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void ReloadPresetsUi(string? selectName)
    {
        var names = _settings.PresetNamesSorted();
        PresetList.ItemsSource = names;

        var toSelect = (selectName ?? "").Trim();
        if (toSelect.Length == 0)
            toSelect = names.FirstOrDefault() ?? "";

        if (toSelect.Length > 0)
            PresetList.SelectedItem = names.FirstOrDefault(n => n.Equals(toSelect, StringComparison.OrdinalIgnoreCase));
        else
            SummaryPresetTextBox.Text = "";
    }

    private void LoadSelectedPresetIntoEditor()
    {
        var selected = (PresetList.SelectedItem as string) ?? "";
        if (selected.Length == 0)
        {
            SummaryPresetTextBox.Text = "";
            return;
        }

        _settings = _settings with { SelectedPresetName = selected };
        SummaryPresetTextBox.Text = _settings.GetPresetSummary(selected);
    }

    private void EditSelectedPreset()
    {
        var selected = (PresetList.SelectedItem as string) ?? "";
        if (selected.Length == 0)
            return;

        // Persist any pending inline edits before opening the full editor.
        _settings = _settings.UpsertPreset(selected, SummaryPresetTextBox.Text ?? "");
        AppSettingsStore.Save(_settings);

        var dlg = new EditSummaryPresetWindow(_settings, selected) { Owner = this };
        dlg.ShowDialog();
        _settings = dlg.UpdatedSettings;

        ReloadPresetsUi(selectName: _settings.SelectedPresetName);
        DialogStatus.Text = "Summary updated.";
    }

    private void AddPreset()
    {
        var name = PromptDialogs.PromptForText(this, "Add Summary Version", "Name:", "New summary");
        if (string.IsNullOrWhiteSpace(name))
            return;

        var seed = (_getCurrentMainSummary() ?? "").Trim();
        _settings = _settings.UpsertPreset(name.Trim(), seed);
        AppSettingsStore.Save(_settings);

        ReloadPresetsUi(selectName: name);
        DialogStatus.Text = $"Added: {name}";
    }

    private void RenamePreset()
    {
        var current = (PresetList.SelectedItem as string) ?? "";
        if (current.Length == 0)
            return;

        var next = PromptDialogs.PromptForText(this, "Rename Summary Version", "New name:", current);
        if (string.IsNullOrWhiteSpace(next))
            return;

        _settings = _settings.RenamePreset(current, next.Trim());
        AppSettingsStore.Save(_settings);

        ReloadPresetsUi(selectName: next);
        DialogStatus.Text = $"Renamed: {current} -> {next}";
    }

    private void DeletePreset()
    {
        var current = (PresetList.SelectedItem as string) ?? "";
        if (current.Length == 0)
            return;

        if (_settings.PresetNamesSorted().Count <= 1)
        {
            System.Windows.MessageBox.Show("You must keep at least one saved summary.", "SARes", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        if (System.Windows.MessageBox.Show($"Delete summary \"{current}\"?", "SARes", MessageBoxButton.YesNo, MessageBoxImage.Warning) != System.Windows.MessageBoxResult.Yes)
            return;

        _settings = _settings.RemovePreset(current);
        AppSettingsStore.Save(_settings);

        ReloadPresetsUi(selectName: _settings.SelectedPresetName);
        DialogStatus.Text = $"Deleted: {current}";
    }

    private void SaveAndKeepOpen()
    {
        try
        {
            var selected = (PresetList.SelectedItem as string) ?? "";
            if (selected.Length > 0)
            {
                _settings = _settings.UpsertPreset(selected, SummaryPresetTextBox.Text ?? "");
                _settings = _settings with { SelectedPresetName = selected };
            }

            // Base template selection is persisted on selection/import/edit; nothing to do here.
            AppSettingsStore.Save(_settings);

            DialogStatus.Text = "Saved.";
        }
        catch (Exception ex)
        {
            DialogStatus.Text = "Save failed: " + ex.Message;
        }
    }


}
