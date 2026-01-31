using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;
using SARes.engine;
using SARes.ui;

namespace SARes.ui;

public partial class ImportPdfWindow : Window
{
    private AppSettings _updated;
    private readonly List<string> _currentHeaderAliases = new();
    private readonly List<string> _currentBulletizedSections = new();
    private string? _currentPdfPath;
    private PdfLayoutMode _currentLayoutMode = PdfLayoutMode.SingleColumn;
    private bool _contextMenuInitialized;
    private bool _isImporting;
    private readonly string? _initialPdfPath;

    public ImportPdfWindow(AppSettings settings, string? initialPdfPath = null)
    {
        InitializeComponent();
        _updated = settings;
        _initialPdfPath = initialPdfPath;

        SelectPdfButton.Click += async (_, _) => await SelectPdfAsync();
        ImportButton.Click += async (_, _) => await RunImportAsync();
        ReorderSectionsButton.Click += (_, _) => ReorderSections();
        ManageHeadersButton.Click += (_, _) => OpenHeaderMappingWindow(runImportAfterClose: false);
        SaveMapButton.Click += (_, _) => BuildMap();
        SaveButton.Click += (_, _) => SaveTemplate();
        CloseButton.Click += (_, _) => Close();

        Loaded += async (_, _) =>
        {
            try
            {
                await WebViewHelpers.EnsureReadyAsync(PdfWeb);
                InitializePdfContextMenu();

                if (!string.IsNullOrWhiteSpace(_initialPdfPath) && File.Exists(_initialPdfPath))
                    await LoadPdfAsync(_initialPdfPath).ConfigureAwait(true);
            }
            catch
            {
            }
        };

        ManageHeadersButton.IsEnabled = true;
        SaveMapButton.IsEnabled = true;
        HeaderMapListBox.MouseDoubleClick += (_, _) => RemoveSelectedHeaderFromList();

        LayoutModeComboBox.ItemsSource = new[]
        {
            new LayoutChoice("Single column (top-to-bottom)", PdfLayoutMode.SingleColumn),
            new LayoutChoice("2 columns (left then right)", PdfLayoutMode.TwoColumnsLeftToRight),
            new LayoutChoice("2 columns (right then left)", PdfLayoutMode.TwoColumnsRightToLeft),
        };
        LayoutModeComboBox.DisplayMemberPath = nameof(LayoutChoice.Label);
        LayoutModeComboBox.SelectedValuePath = nameof(LayoutChoice.Mode);
        LayoutModeComboBox.SelectionChanged += (_, _) =>
        {
            if (LayoutModeComboBox.SelectedValue is PdfLayoutMode mode)
                _currentLayoutMode = mode;
        };

        ResetHeaderState();
        LayoutModeComboBox.SelectedValue = _currentLayoutMode;
        StatusText.Text = "Select a PDF to import.";
    }

    public AppSettings UpdatedSettings => _updated;

    private static string? ToSingleLineOrNull(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return null;

        foreach (var line in text.Replace("\r", "").Split('\n'))
        {
            var trimmed = line.Trim();
            if (trimmed.Length > 0)
                return trimmed;
        }

        return null;
    }

    private async Task SelectPdfAsync()
    {
        var dlg = new Microsoft.Win32.OpenFileDialog
        {
            Title = "Select base resume PDF",
            Filter = "PDF (*.pdf)|*.pdf|All files (*.*)|*.*"
        };
        if (dlg.ShowDialog() != true)
            return;

        var pdfPath = dlg.FileName;
        if (!File.Exists(pdfPath))
            return;

        await LoadPdfAsync(pdfPath).ConfigureAwait(true);
    }

    private async Task LoadPdfAsync(string pdfPath)
    {
        StatusText.Text = "Loading preview...";
        try
        {
            await WebViewHelpers.EnsureReadyAsync(PdfWeb);
            PdfWeb.Source = new Uri(pdfPath);
            PdfWeb.ZoomFactor = 1.25;
            StatusText.Text = "Preview ready. Use Manage headers or Build Map to adjust mapping.";
            await TopLeftJustifyWebViewAsync(PdfWeb);
        }
        catch
        {
            StatusText.Text = "Preview load failed.";
        }

        _currentPdfPath = pdfPath;
        TemplateTextBox.Text = "";
    }

    private void ResetHeaderState()
    {
        _currentHeaderAliases.Clear();
        var saved = (_updated.PdfSectionHeaderAliases ?? Array.Empty<string>())
            .Select(h => (h ?? "").Trim())
            .Where(h => h.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        if (saved.Count > 0)
            _currentHeaderAliases.AddRange(saved);
        else
            _currentHeaderAliases.AddRange(_updated.GetPdfHeaderPreset(_updated.SelectedPdfHeaderPresetName));

        _currentBulletizedSections.Clear();
        _currentBulletizedSections.AddRange(_updated.GetPdfBulletizePreset(_updated.SelectedPdfHeaderPresetName));
        _currentLayoutMode = _updated.SelectedPdfLayoutMode;
        RefreshHeaderList();
    }

    private void RefreshHeaderList()
    {
        HeaderMapListBox.Items.Clear();
        foreach (var header in _currentHeaderAliases)
        {
            var isBulletized = _currentBulletizedSections.Any(b => b.Equals(header, StringComparison.OrdinalIgnoreCase));

            var checkBox = new System.Windows.Controls.CheckBox
            {
                IsChecked = isBulletized,
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(0, 0, 8, 0),
                ToolTip = "Force bullets under this header"
            };
            checkBox.Checked += (_, _) => SetHeaderBulletize(header, enabled: true);
            checkBox.Unchecked += (_, _) => SetHeaderBulletize(header, enabled: false);

            var text = new System.Windows.Controls.TextBlock
            {
                Text = header,
                VerticalAlignment = VerticalAlignment.Center
            };

            var panel = new System.Windows.Controls.StackPanel
            {
                Orientation = System.Windows.Controls.Orientation.Horizontal
            };
            panel.Children.Add(checkBox);
            panel.Children.Add(text);

            HeaderMapListBox.Items.Add(new System.Windows.Controls.ListBoxItem { Content = panel, Tag = header });
        }
    }

    private void SetHeaderBulletize(string header, bool enabled)
    {
        var normalized = (header ?? "").Trim();
        if (normalized.Length == 0)
            return;

        var existingIdx = _currentBulletizedSections.FindIndex(h => h.Equals(normalized, StringComparison.OrdinalIgnoreCase));

        if (enabled)
        {
            if (existingIdx < 0)
                _currentBulletizedSections.Add(normalized);
            return;
        }

        if (existingIdx >= 0)
            _currentBulletizedSections.RemoveAt(existingIdx);
    }

    private void RemoveSelectedHeaderFromList()
    {
        if (HeaderMapListBox.SelectedItem is System.Windows.Controls.ListBoxItem item && item.Tag is string header)
        {
            _currentHeaderAliases.Remove(header);
            _currentBulletizedSections.RemoveAll(h => h.Equals(header, StringComparison.OrdinalIgnoreCase));
            RefreshHeaderList();
            StatusText.Text = $"Removed header hint: {header}";
        }
    }

    private void InitializePdfContextMenu()
    {
        if (PdfWeb.CoreWebView2 is null || _contextMenuInitialized)
            return;

        PdfWeb.CoreWebView2.ContextMenuRequested += PdfWeb_ContextMenuRequested;
        _contextMenuInitialized = true;
    }

    private void PdfWeb_ContextMenuRequested(object? sender, CoreWebView2ContextMenuRequestedEventArgs args)
    {
        if (PdfWeb.CoreWebView2 is null)
            return;

        try
        {
            var env = PdfWeb.CoreWebView2.Environment;
            var capturedArgs = args;
            var tagItem = env.CreateContextMenuItem("Tag selection as header", null, CoreWebView2ContextMenuItemKind.Command);
            tagItem.CustomItemSelected += (_, _) => _ = TagSelectionAsHeaderAsync(capturedArgs);

            var manageItem = env.CreateContextMenuItem("Manage header mapping...", null, CoreWebView2ContextMenuItemKind.Command);
            manageItem.CustomItemSelected += (_, _) => Dispatcher.Invoke(() => OpenHeaderMappingWindow(runImportAfterClose: false));

            args.MenuItems.Insert(0, tagItem);
            args.MenuItems.Insert(1, manageItem);
        }
        catch
        {
        }
    }

    private async Task TagSelectionAsHeaderAsync(CoreWebView2ContextMenuRequestedEventArgs? args = null)
    {
        var selection = args?.ContextMenuTarget.SelectionText;
        if (string.IsNullOrWhiteSpace(selection))
            selection = await CaptureSelectionTextAsync().ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(selection) && args is not null)
            selection = await CaptureTextAtPointAsync(new System.Windows.Point(args.Location.X, args.Location.Y)).ConfigureAwait(false);
        selection = ToSingleLineOrNull(selection);
        if (string.IsNullOrWhiteSpace(selection))
        {
            Dispatcher.Invoke(() => StatusText.Text = "No text selected.");
            return;
        }

        Dispatcher.Invoke(() => AddHeaderAlias(selection));
    }

    private void AddHeaderAlias(string header)
    {
        if (_currentHeaderAliases.Any(h => h.Equals(header, StringComparison.OrdinalIgnoreCase)))
        {
            StatusText.Text = $"Header already tracked: {header}";
            return;
        }

        _currentHeaderAliases.Add(header);
        RefreshHeaderList();
        StatusText.Text = $"Added header hint: {header}. Open Manage headers to review or save.";
    }

    private async Task<string?> CaptureSelectionTextAsync()
    {
        if (PdfWeb.CoreWebView2 is null)
            return null;

        try
        {
            var raw = await PdfWeb.CoreWebView2.ExecuteScriptAsync("window.getSelection().toString()").ConfigureAwait(false);
            if (string.IsNullOrWhiteSpace(raw))
                return null;

            return JsonSerializer.Deserialize<string>(raw);
        }
        catch
        {
            return null;
        }
    }

    private async Task<string?> CaptureTextAtPointAsync(System.Windows.Point location)
    {
        if (PdfWeb.CoreWebView2 is null)
            return null;

        try
        {
            var script = $$"""
 (function(){
     var scale = window.devicePixelRatio || 1;
     var x = {{location.X}} / scale;
     var y = {{location.Y}} / scale;
     var el = document.elementFromPoint(x, y);
     while (el && el.textContent.trim().length === 0 && el.parentElement)
         el = el.parentElement;
     if (!el)
         return "";
     var text = (el.textContent || el.innerText || "").trim();
     if (!text)
         return "";
     return text.split(/\\r?\\n/)[0];
 })()
 """;
            var result = await PdfWeb.CoreWebView2.ExecuteScriptAsync(script).ConfigureAwait(false);
            if (string.IsNullOrWhiteSpace(result))
                return null;
            return JsonSerializer.Deserialize<string>(result);
        }
        catch
        {
            return null;
        }
    }

    private void OpenHeaderMappingWindow(bool runImportAfterClose)
    {
        var initialHeaders = _currentHeaderAliases.Count > 0
            ? (IEnumerable<string>)_currentHeaderAliases
            : _updated.GetPdfHeaderPreset(_updated.SelectedPdfHeaderPresetName);

        var headerWindow = new PdfHeaderMappingWindow(
            _updated,
            initialHeaders,
            SaveHeaderPreset,
            confirmButtonText: "Done")
        {
            Owner = this
        };

        if (headerWindow.ShowDialog() != true)
        {
            StatusText.Text = "Header mapping canceled.";
            return;
        }

        _currentHeaderAliases.Clear();
        _currentHeaderAliases.AddRange(headerWindow.ConfirmedHeaders);

        _currentBulletizedSections.Clear();
        _currentBulletizedSections.AddRange(headerWindow.BulletizedSectionTitles);
        _currentLayoutMode = headerWindow.SelectedLayoutMode;
        LayoutModeComboBox.SelectedValue = _currentLayoutMode;
        RefreshHeaderList();

        var selectedPreset = (headerWindow.SelectedPresetName ?? "").Trim();
        if (selectedPreset.Length > 0)
        {
            _updated = _updated with { SelectedPdfHeaderPresetName = selectedPreset, SelectedPdfLayoutMode = _currentLayoutMode };
        }
        else
        {
            _updated = _updated with { SelectedPdfLayoutMode = _currentLayoutMode };
        }
        AppSettingsStore.Save(_updated);

        StatusText.Text = "Headers updated. You can now import or save the template.";
    }

    private void SaveHeaderPreset(string name, IReadOnlyList<string> headers, IReadOnlyList<string> bulletize)
    {
        _updated = _updated.WithPdfPreset(name, headers, bulletize);
        AppSettingsStore.Save(_updated);
        StatusText.Text = $"Header preset saved: {name}.";
    }

    private void BuildMap()
    {
        var dlg = new PdfMapBuilderWindow(_updated) { Owner = this };
        if (dlg.ShowDialog() != true)
            return;

        _updated = dlg.UpdatedSettings;
        ResetHeaderState();

        if (!string.IsNullOrWhiteSpace(dlg.SelectedPdfPath) && File.Exists(dlg.SelectedPdfPath))
            _ = LoadPdfAsync(dlg.SelectedPdfPath);

        StatusText.Text = "Header map updated.";
    }

    private async Task RunImportAsync()
    {
        if (_isImporting || string.IsNullOrWhiteSpace(_currentPdfPath))
            return;

        _isImporting = true;
        ImportButton.IsEnabled = false;

        try
        {
            var headersToUse = _currentHeaderAliases.Count > 0
                ? _currentHeaderAliases.ToArray()
                : _updated.GetPdfHeaderPreset(_updated.SelectedPdfHeaderPresetName);

            var bulletize = _currentBulletizedSections.ToArray();

            StatusText.Text = "Extracting text from PDF...";
            var template = await Task.Run(() => PdfResumeImporter.ImportPdfToTemplateMarkdown(_currentPdfPath!, headersToUse, _currentLayoutMode, bulletize));

            TemplateTextBox.Text = template;
            StatusText.Text = "Imported. Review/edit the extracted text, then Save Template.";
        }
        catch (Exception ex)
        {
            StatusText.Text = "Import failed: " + ex.Message;
            System.Windows.MessageBox.Show(ex.Message, "Import failed", MessageBoxButton.OK, MessageBoxImage.Error);
        }
        finally
        {
            _isImporting = false;
            ImportButton.IsEnabled = true;
        }
    }

    private void SaveTemplate()
    {
        try
        {
            var content = (TemplateTextBox.Text ?? "").Trim();
            if (content.Length == 0)
            {
                System.Windows.MessageBox.Show("Template text is empty.", "SARes", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            var defaultName = _updated.GetSelectedBaseTemplateNameOrDefault();
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
            {
                System.Windows.MessageBox.Show("Template name results in an invalid filename.", "SARes", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            var outPath = Path.Combine(templatesDir, $"resume_{fileSegment}.md");
            File.WriteAllText(outPath, content.TrimEnd() + "\n");

            _updated = _updated.UpsertBaseTemplate(name, outPath) with { BaseResumeTemplatePath = null };
            AppSettingsStore.Save(_updated);

            StatusText.Text = $"Saved base resume template \"{name}\": {outPath}";
        }
        catch (Exception ex)
        {
            StatusText.Text = "Save failed: " + ex.Message;
        }
    }

    private void ReorderSections()
    {
        try
        {
            var md = (TemplateTextBox.Text ?? "").Trim();
            if (md.Length == 0)
            {
                System.Windows.MessageBox.Show("No extracted template to reorder yet.", "SARes", MessageBoxButton.OK, MessageBoxImage.Information);
                return;
            }

            var dlg = new ReorderSectionsWindow(md) { Owner = this };
            if (dlg.ShowDialog() == true)
            {
                TemplateTextBox.Text = dlg.ReorderedMarkdown;
                StatusText.Text = "Section order updated. Review, then Save Template.";
            }
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(ex.Message, "Reorder failed", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private static async Task TopLeftJustifyWebViewAsync(WebView2 view)
    {
        try
        {
            if (view.CoreWebView2 is null)
                return;

            const string script =
                "(function(){try{"
                + "var de=document.documentElement; var b=document.body;"
                + "if(de){de.style.margin='0';de.style.padding='0';de.scrollLeft=0;de.scrollTop=0;}"
                + "if(b){b.style.margin='0';b.style.padding='0';b.scrollLeft=0;b.scrollTop=0;}"
                + "var ids=['outerContainer','mainContainer','viewerContainer'];"
                + "for(var i=0;i<ids.length;i++){var el=document.getElementById(ids[i]); if(el){el.style.margin='0';el.style.padding='0';}}"
                + "var sc=document.scrollingElement||de||b;"
                + "if(sc){sc.scrollLeft=0;sc.scrollTop=0;}"
                + "var vc=document.getElementById('viewerContainer'); if(vc){vc.scrollLeft=0;vc.scrollTop=0;}"
                + "}catch(e){}})();";

            await view.CoreWebView2.ExecuteScriptAsync(script);
            await Task.Delay(75);
            await view.CoreWebView2.ExecuteScriptAsync(script);
        }
        catch
        {
        }
    }

    private sealed record LayoutChoice(string Label, PdfLayoutMode Mode);
}
