using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using Microsoft.Web.WebView2.Core;
using SARes.engine;
using SARes.renderer;
using SARes.ui;

namespace SARes;

public partial class MainWindow : Window
{
    private AppSettings _settings;
    private string _currentPresetName = "";
    private bool _suppressPresetEvents;
    private bool _suppressAiModeEvents;
    private bool _suppressBaseTemplateEvents;
    private const string BasePresetName = "Base";
    private const string BundledTemplateName = "(Bundled)";
    private StartHereFloatingWindow? _startHereWindow;

    public MainWindow()
    {
        InitializeComponent();

        ZoomSlider.ValueChanged += (_, _) => ApplyZoom();

        _settings = AppSettingsStore.LoadOrDefault();
        EnsureAtLeastOnePreset();
        EnsureAtLeastOneBaseTemplateChoice();

        OutputDirTextBox.Text = _settings.OutputDirectory;
        PandocPathTextBox.Text = _settings.PandocPath ?? "";
        ApplyResumeTailoringModeToUi(_settings.ResumeTailoringMode);

        BaseTemplateCombo.SelectionChanged += (_, _) => SwitchBaseTemplate();
        ManageTemplatesButton.Click += (_, _) => TemplatesAndSummaries_Click(this, new RoutedEventArgs());

        PresetCombo.SelectionChanged += (_, _) => SwitchPreset();
        NewPresetButton.Click += (_, _) => CreateNewPresetFromCurrent();
        SavePresetButton.Click += (_, _) => SaveCurrentPresetSummary();

        AiModeCoverLetterOnlyCheckBox.Checked += (_, _) => OnAiModeChecked(ResumeTailoringMode.CoverLetterOnly);
        AiModeLightCheckBox.Checked += (_, _) => OnAiModeChecked(ResumeTailoringMode.Light);
        AiModeHeavyCheckBox.Checked += (_, _) => OnAiModeChecked(ResumeTailoringMode.Heavy);

        AiModeCoverLetterOnlyCheckBox.Unchecked += (_, _) => OnAiModeUnchecked();
        AiModeLightCheckBox.Unchecked += (_, _) => OnAiModeUnchecked();
        AiModeHeavyCheckBox.Unchecked += (_, _) => OnAiModeUnchecked();

        BrowseOutputButton.Click += (_, _) => BrowseOutput();
        BrowsePandocButton.Click += (_, _) => BrowseTool(PandocPathTextBox, "pandoc.exe");
        GenerateButton.Click += async (_, _) => await GenerateAsync();
        StartHereLaunchButton.Click += (_, _) => ShowStartHereFloatingWindow();

        ReloadBaseTemplatesUi(selectName: _settings.SelectedBaseResumeTemplateName);
        ReloadPresetsUi(selectPresetName: _settings.SelectedPresetName);

        Loaded += async (_, _) =>
        {
            try
            {
                FitToWorkArea();
                if (PreviewTabs.Items.Count > 0)
                    PreviewTabs.SelectedIndex = 0;
                await WebViewHelpers.EnsureReadyAsync(ResumeDarkWeb);
                await WebViewHelpers.EnsureReadyAsync(ResumeAtsWeb);
                await WebViewHelpers.EnsureReadyAsync(CoverLetterWeb);
                ApplyZoom();
            }
            catch (Exception ex)
            {
                StatusText.Text = "PDF preview unavailable: " + ex.Message;
            }
        };

        Closing += (_, _) =>
        {
            if (_startHereWindow is { IsLoaded: true })
            {
                _startHereWindow.Close();
                _startHereWindow = null;
            }
        };

        StatusText.Text = "Ready";
    }

    private void ShowStartHereFloatingWindow()
    {
        var assets = new AssetLocator(AppContext.BaseDirectory);
        var mdPath = assets.StartHereMarkdownPath;
        if (!File.Exists(mdPath))
        {
            StartHereStatusText.Text = "Start Here guide missing.";
            return;
        }

        if (_startHereWindow is { IsLoaded: true })
        {
            _startHereWindow.Activate();
            StartHereStatusText.Text = "Start Here guide already open.";
            return;
        }

        var cssPath = assets.HelpCssPath;
        _startHereWindow = new StartHereFloatingWindow(mdPath, cssPath);
        PositionStartHereFloatingWindow(_startHereWindow);
        _startHereWindow.Closed += (_, _) =>
        {
            _startHereWindow = null;
            StartHereStatusText.Text = "Start Here guide closed.";
        };

        _startHereWindow.Show();
        StartHereStatusText.Text = "Start Here guide opened.";
    }

    private void PositionStartHereFloatingWindow(StartHereFloatingWindow window)
    {
        if (window is null)
            return;

        var work = SystemParameters.WorkArea;
        var rightEdge = Math.Min(work.Right - 40, Left + Width);
        window.Left = Math.Max(work.Left + 20, rightEdge - window.Width);
        var desiredTop = Top + 40;
        if (desiredTop + window.Height > work.Bottom - 20)
            desiredTop = Math.Max(work.Top + 20, work.Bottom - window.Height - 20);
        window.Top = desiredTop;
    }

    private void FitToWorkArea()
    {
        try
        {
            var work = SystemParameters.WorkArea;
            if (double.IsNaN(work.Width) || double.IsNaN(work.Height) || work.Width <= 0 || work.Height <= 0)
                return;

            // Clamp minimums to the current screen if needed.
            if (MinWidth > work.Width) MinWidth = Math.Max(600, work.Width);
            if (MinHeight > work.Height) MinHeight = Math.Max(480, work.Height);

            // Start as small as allowed (but still within screen).
            Width = Math.Min(Math.Max(MinWidth, 600), work.Width);
            Height = Math.Min(Math.Max(MinHeight, 480), work.Height);

            // Keep the window fully on-screen and centered.
            Left = work.Left + Math.Max(0, (work.Width - Width) / 2.0);
            Top = work.Top + Math.Max(0, (work.Height - Height) / 2.0);
        }
        catch
        {
        }
    }

    private void EnsureAtLeastOnePreset()
    {
        if (_settings.SummaryPresets.Count > 0)
            return;

        _settings = _settings.UpsertPreset(BasePresetName, "");
        _settings = _settings with { SelectedPresetName = BasePresetName };
        AppSettingsStore.Save(_settings);
    }

    private void EnsureAtLeastOneBaseTemplateChoice()
    {
        // No-op: bundled template is always available. If legacy single-path exists, migration will populate BaseResumeTemplates.
        // Ensure SelectedBaseResumeTemplateName is either a valid key or null.
        var selected = (_settings.SelectedBaseResumeTemplateName ?? "").Trim();
        if (selected.Length == 0)
            return;
        if (_settings.BaseResumeTemplates.ContainsKey(selected))
            return;
        _settings = _settings with { SelectedBaseResumeTemplateName = null };
        AppSettingsStore.Save(_settings);
    }

    private void ReloadBaseTemplatesUi(string? selectName)
    {
        _suppressBaseTemplateEvents = true;
        try
        {
            var names = _settings.BaseTemplateNamesSorted().ToList();
            names.Insert(0, BundledTemplateName);
            BaseTemplateCombo.ItemsSource = names;

            var target = (selectName ?? "").Trim();
            if (target.Length == 0)
                target = (_settings.SelectedBaseResumeTemplateName ?? "").Trim();
            if (target.Length == 0)
                target = BundledTemplateName;

            BaseTemplateCombo.SelectedItem = names.FirstOrDefault(n => n.Equals(target, StringComparison.OrdinalIgnoreCase))
                                             ?? BundledTemplateName;
        }
        finally
        {
            _suppressBaseTemplateEvents = false;
        }
    }

    private void SwitchBaseTemplate()
    {
        if (_suppressBaseTemplateEvents)
            return;

        var selected = (BaseTemplateCombo.SelectedItem as string) ?? "";
        if (selected.Length == 0)
            return;

        if (selected.Equals(BundledTemplateName, StringComparison.OrdinalIgnoreCase))
        {
            _settings = _settings with { SelectedBaseResumeTemplateName = null, BaseResumeTemplatePath = null };
            AppSettingsStore.Save(_settings);
            StatusText.Text = "Using bundled base template.";
            _ = HydrateBasePresetIfEmptyAsync();
            return;
        }

        if (!_settings.BaseResumeTemplates.ContainsKey(selected))
            return;

        _settings = _settings with { SelectedBaseResumeTemplateName = selected, BaseResumeTemplatePath = null };
        AppSettingsStore.Save(_settings);
        StatusText.Text = $"Using base template: {selected}";
        _ = HydrateBasePresetIfEmptyAsync();
    }

    private void ReloadPresetsUi(string? selectPresetName)
    {
        _suppressPresetEvents = true;
        try
        {
            var names = _settings.PresetNamesSorted();
            PresetCombo.ItemsSource = names;

            var target = (selectPresetName ?? "").Trim();
            if (target.Length == 0)
                target = (_settings.SelectedPresetName ?? "").Trim();
            if (target.Length == 0)
                target = names.FirstOrDefault() ?? "";

            if (target.Length > 0)
                PresetCombo.SelectedItem = names.FirstOrDefault(n => n.Equals(target, StringComparison.OrdinalIgnoreCase));

            _currentPresetName = (PresetCombo.SelectedItem as string) ?? "";
            SummaryTextBox.Text = _settings.GetPresetSummary(_currentPresetName);
        }
        finally
        {
            _suppressPresetEvents = false;
        }

        _ = HydrateBasePresetIfEmptyAsync();
    }

    private void ApplyZoom()
    {
        try
        {
            var zoom = Math.Clamp(ZoomSlider.Value, 0.25, 5.0);
            if (ResumeDarkWeb.CoreWebView2 is not null) ResumeDarkWeb.ZoomFactor = zoom;
            if (ResumeAtsWeb.CoreWebView2 is not null) ResumeAtsWeb.ZoomFactor = zoom;
            if (CoverLetterWeb.CoreWebView2 is not null) CoverLetterWeb.ZoomFactor = zoom;
            _ = LeftJustifyPreviewsAsync();
        }
        catch
        {
        }
    }

    private void BrowseOutput()
    {
        var dlg = new System.Windows.Forms.FolderBrowserDialog
        {
            SelectedPath = OutputDirTextBox.Text,
            Description = "Select output directory"
        };
        if (dlg.ShowDialog() == System.Windows.Forms.DialogResult.OK)
        {
            OutputDirTextBox.Text = dlg.SelectedPath;
            _settings = _settings with { OutputDirectory = dlg.SelectedPath };
            AppSettingsStore.Save(_settings);
            StatusText.Text = "Output directory saved.";
        }
    }

    private static void BrowseTool(System.Windows.Controls.TextBox target, string defaultExeName)
    {
        var dlg = new Microsoft.Win32.OpenFileDialog
        {
            Title = $"Select {defaultExeName}",
            Filter = "Executable (*.exe)|*.exe|All files (*.*)|*.*",
            FileName = defaultExeName
        };
        if (dlg.ShowDialog() == true)
            target.Text = dlg.FileName;
    }

    private void SwitchPreset()
    {
        if (_suppressPresetEvents)
            return;

        SaveCurrentPresetSummary();

        _currentPresetName = (PresetCombo.SelectedItem as string) ?? "";
        SummaryTextBox.Text = _settings.GetPresetSummary(_currentPresetName);

        if (_currentPresetName.Length > 0)
        {
            _settings = _settings with { SelectedPresetName = _currentPresetName };
            AppSettingsStore.Save(_settings);
        }

        StatusText.Text = _currentPresetName.Length > 0
            ? $"Loaded saved summary: {_currentPresetName}"
            : "Loaded summary.";

        _ = HydrateBasePresetIfEmptyAsync();
    }

    private void SaveCurrentPresetSummary()
    {
        var name = (_currentPresetName ?? "").Trim();
        if (name.Length == 0)
            name = ((PresetCombo.SelectedItem as string) ?? "").Trim();
        if (name.Length == 0)
            return;

        _settings = _settings.UpsertPreset(name, SummaryTextBox.Text ?? "");
        _settings = _settings with { SelectedPresetName = name };
        AppSettingsStore.Save(_settings);
    }

    private void CreateNewPresetFromCurrent()
    {
        SaveCurrentPresetSummary();

        var name = PromptForText("New Summary Version", "Name:", "New summary");
        if (string.IsNullOrWhiteSpace(name))
            return;

        var presetName = name.Trim();
        _settings = _settings.UpsertPreset(presetName, SummaryTextBox.Text ?? "");
        _settings = _settings with { SelectedPresetName = presetName };
        AppSettingsStore.Save(_settings);

        ReloadPresetsUi(selectPresetName: presetName);
        StatusText.Text = $"Created summary: {presetName}";
    }

    private async Task GenerateAsync()
    {
        SaveCurrentPresetSummary();

        await HydrateBasePresetIfEmptyAsync().ConfigureAwait(true);

        var summary = (SummaryTextBox.Text ?? "").Trim();
        if (summary.Length == 0)
        {
            System.Windows.MessageBox.Show("Summary is required.", "SARes", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        var jobDescription = (JobDescriptionTextBox.Text ?? "").Trim();

        _settings = _settings with
        {
            OutputDirectory = OutputDirTextBox.Text.Trim(),
            PandocPath = string.IsNullOrWhiteSpace(PandocPathTextBox.Text) ? null : PandocPathTextBox.Text.Trim(),
            ResumeTailoringMode = GetResumeTailoringModeFromUi()
        };
        AppSettingsStore.Save(_settings);

        Directory.CreateDirectory(_settings.OutputDirectory);

        try
        {
            SetBusy(true, "Validating tools...");
            var toolLocator = new ToolLocator(_settings);
            var pandoc = toolLocator.ResolvePandoc();
            var wkhtml = await WkhtmltopdfProvisioner.ResolveOrInstallAsync(s => Dispatcher.Invoke(() => SetBusy(true, s))).ConfigureAwait(true);

            SetBusy(true, "Assembling resume...");
            var assets = new AssetLocator(AppContext.BaseDirectory);
            var templatePath = assets.GetBaseResumeTemplatePath(_settings);
            var baseMd = await File.ReadAllTextAsync(templatePath).ConfigureAwait(true);

            var resumeMd = ResumeAssembler.InjectSummary(baseMd, summary);

            var companyName = JobDescriptionCompanyExtractor.ExtractCompanyName(jobDescription);
            var companySegment = ToSafeFileSegment(companyName);
            if (companySegment.Length == 0)
                companySegment = "UnknownCompany";

            var baseName = companySegment;
            var modeTag = _settings.ResumeTailoringMode switch
            {
                ResumeTailoringMode.CoverLetterOnly => "N",
                ResumeTailoringMode.Light => "L",
                ResumeTailoringMode.Heavy => "H",
                _ => "N"
            };
            var modeSuffix = "-" + modeTag;
            var outDir = _settings.OutputDirectory;

            var resumeMdPath = Path.Combine(outDir, baseName + modeSuffix + "_resume.md");
            await File.WriteAllTextAsync(resumeMdPath, resumeMd).ConfigureAwait(true);

            var renderer = new PandocPdfRenderer(pandoc, wkhtml);

            // AI tailoring (resume) runs before rendering PDFs.
            var apiKey = (Environment.GetEnvironmentVariable("OPENAI_API_KEY") ?? "").Trim();
            AiLogWindow? aiLog = null;
            if (_settings.ResumeTailoringMode != ResumeTailoringMode.CoverLetterOnly && apiKey.Length > 0 && !string.IsNullOrWhiteSpace(jobDescription))
            {
                aiLog = new AiLogWindow { Owner = this };
                aiLog.SetSubtitle("Resume tailoring");
                aiLog.Show();
                aiLog.AppendLine("Resume tailoring started.");

                try
                {
                    var (tailored, usedAi) = await ResumeTailorGenerator.TailorResumeAsync(
                        baseResumeMd: resumeMd,
                        userSummarySeed: summary,
                        jobDescription: jobDescription,
                        mode: _settings.ResumeTailoringMode,
                        log: msg => aiLog.AppendLine(msg)).ConfigureAwait(true);

                    if (usedAi)
                    {
                        resumeMd = tailored;
                        await File.WriteAllTextAsync(resumeMdPath, resumeMd).ConfigureAwait(true);
                        aiLog.AppendLine("Resume tailoring applied.");
                    }
                }
                catch (Exception ex)
                {
                    aiLog.AppendLine("Resume tailoring failed; continuing without it. Error: " + ex.Message);
                }
            }

            SetBusy(true, "Rendering resume PDFs...");
            var darkPdf = Path.Combine(outDir, baseName + modeSuffix + "_resume_dark.pdf");
            var atsPdf = Path.Combine(outDir, baseName + modeSuffix + "_resume_ats.pdf");
            await renderer.RenderMarkdownToPdfAsync(resumeMd, assets.ResumeDarkCssPath, darkPdf).ConfigureAwait(true);
            await renderer.RenderMarkdownToPdfAsync(resumeMd, assets.ResumeNorthCssPath, atsPdf).ConfigureAwait(true);

            SetBusy(true, "Generating cover letter...");
            var coverBase = await File.ReadAllTextAsync(assets.CoverLetterTemplatePath).ConfigureAwait(true);
            aiLog ??= new AiLogWindow { Owner = this };
            try
            {
                aiLog.SetSubtitle("Cover letter generation");
                if (!aiLog.IsVisible) aiLog.Show();
                aiLog.AppendLine("Cover letter request started.");

                Action<string> log = msg =>
                {
                    try { aiLog?.AppendLine(msg); } catch { }
                };

                var coverLetterMd = await CoverLetterGenerator.GenerateCoverLetterMarkdownAsync(
                    resumeMd: resumeMd,
                    coverLetterBaseMd: coverBase,
                    jobDescription: jobDescription,
                    log: log).ConfigureAwait(true);

                var coverPdf = Path.Combine(outDir, baseName + modeSuffix + "_cover_letter.pdf");
                await renderer.RenderMarkdownToPdfAsync(coverLetterMd, assets.CoverLetterCssPath, coverPdf).ConfigureAwait(true);

                aiLog?.SetCompleted("Done");

                SetBusy(true, "Rendering previews...");
                await LoadPreviewAsync(darkPdf, atsPdf, coverPdf).ConfigureAwait(true);
            }
            catch (Exception ex)
            {
                aiLog?.AppendLine("Error: " + ex.Message);
                aiLog?.SetCompleted("Error");
                throw;
            }
            finally
            {
                // Leave the window open for the user to review; they can close it.
            }

            StatusText.Text = $"Done. Wrote PDFs to: {outDir}";
        }
        catch (Exception ex)
        {
            StatusText.Text = "Error: " + ex.Message;
            System.Windows.MessageBox.Show(ex.Message, "SARes error", MessageBoxButton.OK, MessageBoxImage.Error);
        }
        finally
        {
            SetBusy(false, "");
        }
    }

    private void ApplyResumeTailoringModeToUi(ResumeTailoringMode mode)
    {
        _suppressAiModeEvents = true;
        try
        {
            AiModeCoverLetterOnlyCheckBox.IsChecked = mode == ResumeTailoringMode.CoverLetterOnly;
            AiModeLightCheckBox.IsChecked = mode == ResumeTailoringMode.Light;
            AiModeHeavyCheckBox.IsChecked = mode == ResumeTailoringMode.Heavy;
        }
        finally
        {
            _suppressAiModeEvents = false;
        }
    }

    private void SetResumeTailoringMode(ResumeTailoringMode mode)
    {
        ApplyResumeTailoringModeToUi(mode);
        _settings = _settings with { ResumeTailoringMode = mode };
        AppSettingsStore.Save(_settings);
    }

    private ResumeTailoringMode GetResumeTailoringModeFromUi()
    {
        if (AiModeHeavyCheckBox.IsChecked == true) return ResumeTailoringMode.Heavy;
        if (AiModeLightCheckBox.IsChecked == true) return ResumeTailoringMode.Light;
        return ResumeTailoringMode.CoverLetterOnly;
    }

    private void OnAiModeChecked(ResumeTailoringMode mode)
    {
        if (_suppressAiModeEvents)
            return;

        // Checkbox UI with radio-button behavior: checking one unchecks the others.
        SetResumeTailoringMode(mode);
    }

    private void OnAiModeUnchecked()
    {
        if (_suppressAiModeEvents)
            return;

        // If the user unchecks the currently-selected option leaving none selected,
        // default back to CoverLetterOnly so there's always a valid mode.
        if (AiModeCoverLetterOnlyCheckBox.IsChecked != true
            && AiModeLightCheckBox.IsChecked != true
            && AiModeHeavyCheckBox.IsChecked != true)
        {
            SetResumeTailoringMode(ResumeTailoringMode.CoverLetterOnly);
        }
        else
        {
            // If they somehow ended up with multiple checked/unchecked toggles,
            // normalize to current UI state.
            SetResumeTailoringMode(GetResumeTailoringModeFromUi());
        }
    }

    private static string ToSafeFileSegment(string value)
    {
        var s = (value ?? "").Trim();
        if (s.Length == 0)
            return "";

        var invalid = Path.GetInvalidFileNameChars();
        var cleaned = new string(s.Select(ch => invalid.Contains(ch) ? '_' : ch).ToArray());
        cleaned = string.Join("_", cleaned.Split(new[] { ' ', '\t', '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries));
        return cleaned.Length > 60 ? cleaned[..60] : cleaned;
    }

    private void TemplatesAndSummaries_Click(object sender, RoutedEventArgs e)
    {
        SaveCurrentPresetSummary();

        var dlg = new TemplatesAndSummariesWindow(_settings, () => SummaryTextBox.Text ?? "")
        {
            Owner = this
        };
        dlg.ShowDialog();
        _settings = dlg.UpdatedSettings;
        EnsureAtLeastOnePreset();
        EnsureAtLeastOneBaseTemplateChoice();

        ReloadBaseTemplatesUi(selectName: _settings.SelectedBaseResumeTemplateName);
        ReloadPresetsUi(selectPresetName: _settings.SelectedPresetName);
        StatusText.Text = "Templates/summaries updated.";
    }

    private void ImportBasePdf_Click(object sender, RoutedEventArgs e)
    {
        SaveCurrentPresetSummary();

        var dlg = new ImportPdfWindow(_settings) { Owner = this };
        dlg.ShowDialog();
        _settings = dlg.UpdatedSettings;
        EnsureAtLeastOneBaseTemplateChoice();
        ReloadBaseTemplatesUi(selectName: _settings.SelectedBaseResumeTemplateName);
        StatusText.Text = "Base resume template updated.";
    }

    private void ImportBaseMarkdown_Click(object sender, RoutedEventArgs e)
    {
        SaveCurrentPresetSummary();

        var dlg = new Microsoft.Win32.OpenFileDialog
        {
            Title = "Select base resume Markdown (.md)",
            Filter = "Markdown (*.md)|*.md|All files (*.*)|*.*"
        };
        if (dlg.ShowDialog() != true)
            return;

        try
        {
            var content = MarkdownResumeImporter.ImportMarkdownToTemplate(dlg.FileName);

            var templatesDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "SARES",
                "Templates");
            Directory.CreateDirectory(templatesDir);

            var defaultName = _settings.GetSelectedBaseTemplateNameOrDefault();
            if (string.IsNullOrWhiteSpace(defaultName))
                defaultName = "Base";

            var name = PromptDialogs.PromptForText(this, "Save Base Resume Template", "Template name:", defaultName) ?? "";
            name = name.Trim();
            if (name.Length == 0)
                return;

            var fileSegment = SafeFileNames.ToSafeFileSegment(name);
            if (fileSegment.Length == 0)
            {
                System.Windows.MessageBox.Show("Template name results in an invalid filename.", "Import failed", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            var outPath = Path.Combine(templatesDir, $"resume_{fileSegment}.md");
            File.WriteAllText(outPath, content);

            _settings = _settings.UpsertBaseTemplate(name, outPath) with { BaseResumeTemplatePath = null };
            AppSettingsStore.Save(_settings);
            EnsureAtLeastOneBaseTemplateChoice();
            ReloadBaseTemplatesUi(selectName: _settings.SelectedBaseResumeTemplateName);
            StatusText.Text = $"Imported base resume template: {name}";
        }
        catch (Exception ex)
        {
            StatusText.Text = "Import failed: " + ex.Message;
            System.Windows.MessageBox.Show(ex.Message, "Import failed", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void ManagePdfHeaderPresets_Click(object sender, RoutedEventArgs e)
    {
        SaveCurrentPresetSummary();

        var startingHeaders = _settings.PdfSectionHeaderAliases;

        var dlg = new PdfHeaderMappingWindow(
            _settings,
            startingHeaders,
            (name, headers, bulletize) =>
            {
                _settings = _settings.WithPdfPreset(name, headers, bulletize);
                AppSettingsStore.Save(_settings);
            },
            confirmButtonText: "Done")
        {
            Owner = this
        };

        if (dlg.ShowDialog() == true)
        {
            _settings = _settings with { SelectedPdfLayoutMode = dlg.SelectedLayoutMode };
            AppSettingsStore.Save(_settings);
        }
        StatusText.Text = "PDF header presets updated.";
    }

    private void Exit_Click(object sender, RoutedEventArgs e) => Close();

    private async Task LoadPreviewAsync(string darkPdf, string atsPdf, string coverPdf)
    {
        await WebViewHelpers.EnsureReadyAsync(ResumeDarkWeb);
        await WebViewHelpers.EnsureReadyAsync(ResumeAtsWeb);
        await WebViewHelpers.EnsureReadyAsync(CoverLetterWeb);

        WebViewHelpers.SetWebViewSource(ResumeDarkWeb, darkPdf);
        WebViewHelpers.SetWebViewSource(ResumeAtsWeb, atsPdf);
        WebViewHelpers.SetWebViewSource(CoverLetterWeb, coverPdf);
        ApplyZoom();

        PreviewTabs.SelectedIndex = 1;
        await Task.Delay(50).ConfigureAwait(true);
        PreviewTabs.SelectedIndex = 0;

        await LeftJustifyPreviewsAsync().ConfigureAwait(true);
    }

    private async Task LeftJustifyPreviewsAsync()
    {
        try
        {
            await WebViewHelpers.LeftJustifyWebViewAsync(ResumeDarkWeb).ConfigureAwait(true);
            await WebViewHelpers.LeftJustifyWebViewAsync(ResumeAtsWeb).ConfigureAwait(true);
            await WebViewHelpers.LeftJustifyWebViewAsync(CoverLetterWeb).ConfigureAwait(true);
        }
        catch
        {
        }
    }

    private void SetBusy(bool isBusy, string status)
    {
        GenerateButton.IsEnabled = !isBusy;
        PresetCombo.IsEnabled = !isBusy;
        NewPresetButton.IsEnabled = !isBusy;
        SavePresetButton.IsEnabled = !isBusy;
        SummaryTextBox.IsEnabled = !isBusy;
        JobDescriptionTextBox.IsEnabled = !isBusy;
        BrowseOutputButton.IsEnabled = !isBusy;
        BrowsePandocButton.IsEnabled = !isBusy;

        if (!string.IsNullOrWhiteSpace(status))
            StatusText.Text = status;
    }

    private async Task HydrateBasePresetIfEmptyAsync()
    {
        try
        {
            var name = (_currentPresetName ?? "").Trim();
            if (!name.Equals(BasePresetName, StringComparison.OrdinalIgnoreCase))
                return;

            var current = (SummaryTextBox.Text ?? "").Trim();
            if (current.Length > 0)
                return;

            // If Base preset already has saved text (but UI is empty), reload it.
            var saved = (_settings.GetPresetSummary(name) ?? "").Trim();
            if (saved.Length > 0)
            {
                SummaryTextBox.Text = saved;
                return;
            }

            // Pull Summary from the base template.
            var assets = new AssetLocator(AppContext.BaseDirectory);
            var templatePath = assets.GetBaseResumeTemplatePath(_settings);
            if (!File.Exists(templatePath))
                return;

            var md = await File.ReadAllTextAsync(templatePath).ConfigureAwait(true);
            var extracted = ResumeSummaryExtractor.ExtractSummary(md).Trim();
            if (extracted.Length == 0)
                return;

            SummaryTextBox.Text = extracted;
            _settings = _settings.UpsertPreset(name, extracted);
            _settings = _settings with { SelectedPresetName = name };
            AppSettingsStore.Save(_settings);
        }
        catch
        {
            // If extraction fails, just keep requiring user input.
        }
    }

    private static async Task EnsureWebViewReadyAsync(Microsoft.Web.WebView2.Wpf.WebView2 view)
    {
        if (view.CoreWebView2 is not null)
            return;

        await view.EnsureCoreWebView2Async();
        if (view.CoreWebView2 is null)
            return;

        view.CoreWebView2.Settings.AreDefaultContextMenusEnabled = true;
        view.CoreWebView2.Settings.AreDevToolsEnabled = false;
        view.CoreWebView2.Settings.IsZoomControlEnabled = false;
    }

    private static string? PromptForText(string title, string label, string initial)
    {
        var bg = (SolidColorBrush)new BrushConverter().ConvertFromString("#0B1220")!;
        var panel = (SolidColorBrush)new BrushConverter().ConvertFromString("#0F172A")!;
        var border = (SolidColorBrush)new BrushConverter().ConvertFromString("#334155")!;
        var fg = (SolidColorBrush)new BrushConverter().ConvertFromString("#E5E7EB")!;
        var muted = (SolidColorBrush)new BrushConverter().ConvertFromString("#94A3B8")!;

        var win = new Window
        {
            Title = title,
            Width = 420,
            Height = 170,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            ResizeMode = ResizeMode.NoResize,
            Background = bg,
            Foreground = fg,
            Owner = System.Windows.Application.Current?.MainWindow
        };

        var grid = new Grid { Margin = new Thickness(12) };
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

        var labelBlock = new TextBlock { Text = label, Margin = new Thickness(0, 0, 0, 6), Foreground = muted };
        Grid.SetRow(labelBlock, 0);
        grid.Children.Add(labelBlock);

        var textBox = new System.Windows.Controls.TextBox
        {
            Text = initial ?? "",
            Margin = new Thickness(0, 0, 0, 10),
            Background = panel,
            Foreground = fg,
            BorderBrush = border,
            BorderThickness = new Thickness(1),
            Padding = new Thickness(10, 8, 10, 8)
        };
        Grid.SetRow(textBox, 1);
        grid.Children.Add(textBox);

        var buttons = new StackPanel { Orientation = System.Windows.Controls.Orientation.Horizontal, HorizontalAlignment = System.Windows.HorizontalAlignment.Right };
        var ok = new System.Windows.Controls.Button
        {
            Content = "OK",
            Width = 90,
            Margin = new Thickness(0, 0, 8, 0),
            Background = (SolidColorBrush)new BrushConverter().ConvertFromString("#2563EB")!,
            BorderBrush = (SolidColorBrush)new BrushConverter().ConvertFromString("#1D4ED8")!,
            Foreground = System.Windows.Media.Brushes.White
        };
        var cancel = new System.Windows.Controls.Button
        {
            Content = "Cancel",
            Width = 90,
            Background = (SolidColorBrush)new BrushConverter().ConvertFromString("#111827")!,
            BorderBrush = border,
            Foreground = fg
        };
        buttons.Children.Add(ok);
        buttons.Children.Add(cancel);
        Grid.SetRow(buttons, 2);
        grid.Children.Add(buttons);

        win.Content = new Border
        {
            Background = bg,
            BorderBrush = border,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(10),
            Padding = new Thickness(8),
            Child = grid
        };

        string? result = null;
        ok.Click += (_, _) => { result = textBox.Text; win.DialogResult = true; win.Close(); };
        cancel.Click += (_, _) => { win.DialogResult = false; win.Close(); };

        win.Loaded += (_, _) => { textBox.Focus(); textBox.SelectAll(); };

        _ = win.ShowDialog();
        return result;
    }

    private void HelpChat_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var assets = new AssetLocator(AppContext.BaseDirectory);
            var win = new HelpChatWindow(assets.HelpManualPath, assets.HelpCssPath)
            {
                Owner = this
            };
            win.ShowDialog();
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(this, ex.Message, "Help Chat", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void TitleBar_MouseDown(object sender, MouseButtonEventArgs e)
    {
        if (e.ChangedButton != MouseButton.Left)
            return;

        if (e.ClickCount == 2)
        {
            WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;
            return;
        }

        if (IsClickHandledByChildControl(e.OriginalSource as DependencyObject))
            return;

        try
        {
            DragMove();
        }
        catch
        {
        }
    }

    private void TitleBar_MouseRightButtonUp(object sender, MouseButtonEventArgs e)
    {
        var screenPoint = PointToScreen(e.GetPosition(this));
        SystemCommands.ShowSystemMenu(this, screenPoint);
    }

    private void CloseWindow_Click(object sender, RoutedEventArgs e)
    {
        AppLog.Info("Main window close button invoked.");
        Close();
        AppLog.Info("Main window close requested.");
    }

    private void TitleCloseButton_PreviewMouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        AppLog.Info("Main window close button preview mouse down.");
    }

    private void MinimizeTitleButton_Click(object sender, RoutedEventArgs e)
    {
        SystemCommands.MinimizeWindow(this);
    }

    private void MaximizeTitleButton_Click(object sender, RoutedEventArgs e)
    {
        if (WindowState == WindowState.Maximized)
            SystemCommands.RestoreWindow(this);
        else
            SystemCommands.MaximizeWindow(this);
    }

    private static bool IsClickHandledByChildControl(DependencyObject? source)
    {
        while (source is not null)
        {
            if (source is System.Windows.Controls.Primitives.ButtonBase)
                return true;

            source = VisualTreeHelper.GetParent(source);
        }

        return false;
    }
}
