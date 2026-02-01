using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;
using Microsoft.Web.WebView2.Wpf;
using SARes.engine;
using SARes.ui;

namespace SARes.ui;

public partial class ImportPdfWindow : Window
{
    private AppSettings _updated;
    private PdfHeaderMappingWindow? _mappingWindow;

    public ImportPdfWindow(AppSettings settings)
    {
        InitializeComponent();
        _updated = settings;

        SelectPdfButton.Click += async (_, _) => await SelectPdfAsync();
        AddSelectionButton.Click += async (_, _) => await AddSelectionAsHeaderAsync();
        ReorderSectionsButton.Click += (_, _) => ReorderSections();
        SaveButton.Click += (_, _) => SaveTemplate();
        CloseButton.Click += (_, _) => Close();

        Loaded += async (_, _) =>
        {
            try { await WebViewHelpers.EnsureReadyAsync(PdfWeb); } catch { }
        };

        StatusText.Text = "Select a PDF to import.";
    }

    public AppSettings UpdatedSettings => _updated;

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

        StatusText.Text = "Loading preview...";
        try
        {
            await WebViewHelpers.EnsureReadyAsync(PdfWeb);
            PdfWeb.Source = new Uri(pdfPath);
            PdfWeb.ZoomFactor = 1.35;
            StatusText.Text = "Preview ready. Confirm headers before importing.";
            await TopLeftJustifyWebViewAsync(PdfWeb);
        }
        catch
        {
            StatusText.Text = "Preview load failed.";
        }

        var mappingResult = await PromptForHeaderMappingAsync();
        if (mappingResult is null)
        {
            StatusText.Text = "Import canceled.";
            return;
        }

        var customHeaders = mappingResult.Headers;
        _updated = _updated.WithPdfSectionHeaderAliases(customHeaders);
        var bulletize = mappingResult.BulletizedSectionTitles;
        var layoutMode = mappingResult.LayoutMode;
        // Do not persist ad-hoc header edits automatically; only save when the user names/saves a preset.
        // Persist the last selected preset for convenience.
        var selectedPreset = (mappingResult.SelectedPresetName ?? "").Trim();
        if (selectedPreset.Length > 0)
        {
            _updated = _updated with { SelectedPdfHeaderPresetName = selectedPreset, SelectedPdfLayoutMode = layoutMode };
            AppSettingsStore.Save(_updated);
        }
        else
        {
            _updated = _updated with { SelectedPdfLayoutMode = layoutMode };
            AppSettingsStore.Save(_updated);
        }

        try
        {
            StatusText.Text = "Extracting text from PDF...";
            var template = PdfResumeImporter.ImportPdfToTemplateMarkdown(pdfPath, customHeaders, layoutMode, bulletize);
            TemplateTextBox.Text = template;

            StatusText.Text = "Imported. Review/edit the extracted text, then Save Template.";
        }
        catch (Exception ex)
        {
            StatusText.Text = "Import failed: " + ex.Message;
            System.Windows.MessageBox.Show(ex.Message, "Import failed", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private async Task<PdfHeaderMappingWindow.HeaderMappingResult?> PromptForHeaderMappingAsync()
    {
        var headerWindow = new PdfHeaderMappingWindow(
            _updated,
            Array.Empty<string>(),
            (name, headers, bulletize) =>
            {
                _updated = _updated.WithPdfPreset(name, headers, bulletize);
                AppSettingsStore.Save(_updated);
            });
        headerWindow.Owner = this;

        var tcs = new TaskCompletionSource<PdfHeaderMappingWindow.HeaderMappingResult?>();

        void OnConfirmed(object? _, PdfHeaderMappingWindow.HeaderMappingResult result)
        {
            if (tcs.TrySetResult(result))
                headerWindow.Close();
        }

        void OnCanceled(object? _, System.EventArgs args)
        {
            if (tcs.TrySetResult(null))
                headerWindow.Close();
        }

        void OnClosed(object? _, System.EventArgs args)
        {
            if (!tcs.Task.IsCompleted)
                tcs.TrySetResult(null);
        }

        headerWindow.MappingConfirmed += OnConfirmed;
        headerWindow.MappingCanceled += OnCanceled;
        headerWindow.Closed += OnClosed;

        _mappingWindow = headerWindow;
        AddSelectionButton.IsEnabled = true;
        headerWindow.Show();

        var result = await tcs.Task;

        headerWindow.MappingConfirmed -= OnConfirmed;
        headerWindow.MappingCanceled -= OnCanceled;
        headerWindow.Closed -= OnClosed;
        _mappingWindow = null;
        AddSelectionButton.IsEnabled = false;

        return result;
    }

    private async Task AddSelectionAsHeaderAsync()
    {
        if (_mappingWindow is null)
        {
            StatusText.Text = "Open the header map window first.";
            return;
        }

        var selection = await CaptureSelectionTextAsync();
        var header = ToSingleLineOrNull(selection);
        if (string.IsNullOrWhiteSpace(header))
        {
            StatusText.Text = "Select a header line before clicking.";
            return;
        }

        _mappingWindow.AddHeaderFromSelection(header);
        StatusText.Text = $"Added header: {header}";
    }

    private async Task<string?> CaptureSelectionTextAsync()
    {
        if (PdfWeb.CoreWebView2 is null)
            return null;

        try
        {
            var raw = await PdfWeb.CoreWebView2.ExecuteScriptAsync("window.getSelection().toString()");
            if (string.IsNullOrWhiteSpace(raw))
                return null;

            return JsonSerializer.Deserialize<string>(raw);
        }
        catch
        {
            return null;
        }
    }

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
}
