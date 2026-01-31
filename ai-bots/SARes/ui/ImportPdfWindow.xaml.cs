using System.IO;
using System.Windows;
using Microsoft.Web.WebView2.Wpf;
using SARes.engine;
using SARes.ui;

namespace SARes.ui;

public partial class ImportPdfWindow : Window
{
    private AppSettings _updated;

    public ImportPdfWindow(AppSettings settings)
    {
        InitializeComponent();
        _updated = settings;

        SelectPdfButton.Click += async (_, _) => await SelectPdfAsync();
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
                StatusText.Text = "Preview ready. Confirm headers before importing.";
                await TopLeftJustifyWebViewAsync(PdfWeb);
            }
        catch
        {
            StatusText.Text = "Preview load failed.";
        }

        var defaultHeaders = _updated.GetPdfHeaderPreset(_updated.SelectedPdfHeaderPresetName);

        var headerWindow = new PdfHeaderMappingWindow(
            _updated,
            defaultHeaders,
            (name, headers, bulletize) =>
            {
                _updated = _updated.WithPdfPreset(name, headers, bulletize);
                AppSettingsStore.Save(_updated);
            });
        headerWindow.Owner = this;
        if (headerWindow.ShowDialog() != true)
        {
            StatusText.Text = "Import canceled.";
            return;
        }

        var customHeaders = headerWindow.ConfirmedHeaders;
        _updated = _updated.WithPdfSectionHeaderAliases(customHeaders);
        var bulletize = headerWindow.BulletizedSectionTitles;
        var layoutMode = headerWindow.SelectedLayoutMode;
        // Do not persist ad-hoc header edits automatically; only save when the user names/saves a preset.
        // Persist the last selected preset for convenience.
        var selectedPreset = (headerWindow.SelectedPresetName ?? "").Trim();
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
