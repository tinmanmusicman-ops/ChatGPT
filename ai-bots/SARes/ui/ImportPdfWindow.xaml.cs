using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;
using Microsoft.Web.WebView2.Wpf;
using SARes.engine;
using SARes.ui;
using System.Windows.Input;

namespace SARes.ui;

public partial class ImportPdfWindow : Window
{
    private AppSettings _updated;
    private PdfHeaderMappingWindow? _mappingWindow;
    private bool _pdfSelectionTrackingInitialized;
    private string? _lastPdfSelection;

    public ImportPdfWindow(AppSettings settings)
    {
        InitializeComponent();
        _updated = settings;
        AppLog.Info($"ImportPdfWindow created. Log={AppLog.LogPath}");

        SelectPdfButton.Click += async (_, _) => await SelectPdfAsync();
        AddSelectionButton.PreviewMouseLeftButtonDown += async (_, e) =>
        {
            e.Handled = true;
            AppLog.Info("AddSelectionButton clicked.");
            await AddSelectionAsHeaderAsync();
        };
        ReorderSectionsButton.Click += (_, _) => ReorderSections();
        SaveButton.Click += (_, _) => SaveTemplate();
        CloseButton.Click += (_, _) => Close();

        Loaded += async (_, _) =>
        {
            try
            {
                await WebViewHelpers.EnsureReadyAsync(PdfWeb);
                InitializePdfSelectionTracking();
                AppLog.Info("PdfWeb ready; selection tracking initialized.");
            }
            catch
            {
                AppLog.Warn("PdfWeb EnsureReadyAsync failed on window load.");
            }
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
            InitializePdfSelectionTracking();
            AppLog.Info($"PDF selected: {pdfPath}");
            PdfWeb.Source = new Uri(pdfPath);
            PdfWeb.ZoomFactor = 2.10;
            StatusText.Text = "Preview ready. Highlight a header, then click Add selection to header map.";
            await TopLeftJustifyWebViewAsync(PdfWeb);
        }
        catch
        {
            StatusText.Text = "Preview load failed.";
            AppLog.Error("Preview load failed.");
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
        var startingHeaders = Array.Empty<string>();
        var headerWindow = new PdfHeaderMappingWindow(
            _updated,
            startingHeaders,
            (name, headers, bulletize) =>
            {
                _updated = _updated.WithPdfPreset(name, headers, bulletize);
                AppSettingsStore.Save(_updated);
            },
            startEmpty: true);
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
        AppLog.Info("Header mapping window opened; AddSelectionButton enabled.");
        headerWindow.Show();

        var result = await tcs.Task;

        headerWindow.MappingConfirmed -= OnConfirmed;
        headerWindow.MappingCanceled -= OnCanceled;
        headerWindow.Closed -= OnClosed;
        _mappingWindow = null;
        AddSelectionButton.IsEnabled = false;
        AppLog.Info("Header mapping window closed; AddSelectionButton disabled.");

        return result;
    }

    private async Task AddSelectionAsHeaderAsync()
    {
        if (_mappingWindow is null)
        {
            StatusText.Text = "Open the header map window first.";
            AppLog.Warn("AddSelection requested with no mapping window.");
            return;
        }

        // Give the PDF viewer a moment to finalize selection before copying.
        await Task.Delay(40);

        var fromScript = await CaptureSelectionTextAsync();
        var fromTracked = _lastPdfSelection;
        var fromClipboard = await TryCopyPdfSelectionToClipboardAsync();

        var candidates = new (string Source, string? Text)[]
        {
            ("ExecuteScriptAsync", fromScript),
            ("Tracked", fromTracked),
            ("ClipboardAfterCtrlC", fromClipboard),
        };

        var header = "";
        var sourceUsed = "";

        foreach (var candidate in candidates)
        {
            var ok = TryExtractHeaderLine(candidate.Text, out var parsed, out var nonEmptyLines);
            AppLog.Info($"Candidate {candidate.Source} len={(candidate.Text ?? "").Length} nonEmptyLines={nonEmptyLines} ok={ok} preview={TruncateForLog(candidate.Text)}");
            if (!ok)
                continue;

            header = parsed;
            sourceUsed = candidate.Source;
            break;
        }

        if (header.Length == 0)
        {
            StatusText.Text = "Select a header line in the PDF first.";
            AppLog.Warn("Selection rejected: no usable text.");
            return;
        }

        try
        {
            System.Windows.Clipboard.SetText(header);
            AppLog.Info($"Clipboard set to: {header}");
        }
        catch
        {
            AppLog.Warn("Clipboard.SetText failed.");
        }

        try
        {
            _mappingWindow.Activate();
            AppLog.Info("Activated mapping window.");
        }
        catch
        {
            AppLog.Warn("Failed to activate mapping window.");
        }

        _mappingWindow.AddHeaderFromSelection(header);
        AppLog.Info($"Sent header to mapping window: {header} (source={sourceUsed})");
        StatusText.Text = $"Added header: {header}";
    }

    private void InitializePdfSelectionTracking()
    {
        if (PdfWeb.CoreWebView2 is null || _pdfSelectionTrackingInitialized)
            return;

        PdfWeb.CoreWebView2.WebMessageReceived += (_, e) =>
        {
            try
            {
                var raw = e.TryGetWebMessageAsString();
                if (string.IsNullOrWhiteSpace(raw))
                    return;

                using var doc = JsonDocument.Parse(raw);
                if (!doc.RootElement.TryGetProperty("type", out var typeEl))
                    return;
                if (!string.Equals(typeEl.GetString(), "sares_pdf_selection", StringComparison.Ordinal))
                    return;
                if (!doc.RootElement.TryGetProperty("text", out var textEl))
                    return;

                var text = (textEl.GetString() ?? "").Trim();
                if (text.Length == 0)
                    return;
                _lastPdfSelection = text;
                AppLog.Info($"Tracked PDF selection updated: {SanitizeForLog(text)}");
            }
            catch
            {
            }
        };

        const string script = """
            (function(){
              try {
                function sendSelection() {
                  try {
                    var t = (window.getSelection && window.getSelection().toString) ? window.getSelection().toString() : '';
                    t = (t || '').trim();
                    if (!t) return;
                    if (window.chrome && window.chrome.webview) {
                      window.chrome.webview.postMessage(JSON.stringify({ type: 'sares_pdf_selection', text: t }));
                    }
                  } catch (e) {}
                }
                document.addEventListener('selectionchange', sendSelection, true);
                document.addEventListener('mouseup', sendSelection, true);
                document.addEventListener('keyup', sendSelection, true);
              } catch (e) {}
            })();
            """;
        _ = PdfWeb.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(script);
        _pdfSelectionTrackingInitialized = true;
    }

    private async Task<string?> TryCopyPdfSelectionToClipboardAsync()
    {
        try
        {
            var lastClipboardText = "";
            var marker = "__SARES_PDF_SELECTION__" + Guid.NewGuid().ToString("N");
            try
            {
                if (System.Windows.Clipboard.ContainsText())
                    lastClipboardText = System.Windows.Clipboard.GetText() ?? "";
            }
            catch
            {
            }

            // Set a marker so we can detect whether the PDF viewer actually copied anything.
            try
            {
                System.Windows.Clipboard.SetText(marker);
                lastClipboardText = marker;
            }
            catch
            {
                marker = string.Empty;
            }

            try
            {
                Activate();
            }
            catch
            {
            }

            PdfWeb.Focus();
            await Task.Delay(35);

            async Task<string?> CopyAttemptAsync(string attemptName, Action sendKeys)
            {
                AppLog.Info($"Clipboard copy attempt: {attemptName}");
                try { sendKeys(); } catch { }

                // Wait for clipboard to change (up to ~1s).
                for (var i = 0; i < 20; i++)
                {
                    await Task.Delay(50);
                    try
                    {
                        if (!System.Windows.Clipboard.ContainsText())
                            continue;
                        var now = System.Windows.Clipboard.GetText() ?? "";
                        if (!string.Equals(now, lastClipboardText, StringComparison.Ordinal) && now.Trim().Length > 0)
                        {
                            lastClipboardText = now;
                            return now;
                        }
                    }
                    catch
                    {
                    }
                }

                // If nothing changed, treat as failure to avoid using unrelated clipboard contents.
                try
                {
                    if (!System.Windows.Clipboard.ContainsText())
                        return null;
                    var now = System.Windows.Clipboard.GetText() ?? "";
                    if (now.Trim().Length == 0)
                        return null;
                    if (!string.IsNullOrEmpty(marker) && string.Equals(now, marker, StringComparison.Ordinal))
                        return null;
                    if (string.Equals(now, lastClipboardText, StringComparison.Ordinal))
                        return null;
                    return now;
                }
                catch
                {
                    return null;
                }
            }

            var attempt1 = await CopyAttemptAsync("Ctrl+C", () => System.Windows.Forms.SendKeys.SendWait("^c"));
            var attempt2 = await CopyAttemptAsync("Ctrl+Insert", () => System.Windows.Forms.SendKeys.SendWait("^{INSERT}"));
            var attempt3 = await CopyAttemptAsync("Shift+End then Ctrl+C", () =>
            {
                System.Windows.Forms.SendKeys.SendWait("+{END}");
                System.Windows.Forms.SendKeys.SendWait("^c");
            });
            var attempt4 = await CopyAttemptAsync("Shift+Home then Shift+End then Ctrl+C", () =>
            {
                System.Windows.Forms.SendKeys.SendWait("+{HOME}");
                System.Windows.Forms.SendKeys.SendWait("+{END}");
                System.Windows.Forms.SendKeys.SendWait("^c");
            });

            var best = new[] { attempt1, attempt2, attempt3, attempt4 }
                .Where(s => !string.IsNullOrWhiteSpace(s))
                .OrderByDescending(s => (s ?? "").Length)
                .FirstOrDefault();

            AppLog.Info($"Clipboard copy best length={(best ?? "").Length} preview={TruncateForLog(best)}");
            return best;
        }
        catch
        {
            return null;
        }
    }

    private static string SanitizeForLog(string? text)
        => (text ?? "")
            .Replace("\r", "")
            .Replace("\n", "\\n");

    private static string TruncateForLog(string? text)
    {
        var sanitized = SanitizeForLog(text);
        const int max = 180;
        if (sanitized.Length <= max)
            return sanitized;
        return sanitized[..max] + "...";
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

    private static bool TryExtractHeaderLine(string? text, out string header, out int nonEmptyLineCount)
    {
        header = string.Empty;
        nonEmptyLineCount = 0;
        if (string.IsNullOrWhiteSpace(text))
            return false;

        var foundHeader = false;
        foreach (var line in text.Replace("\r", "").Split('\n'))
        {
            var trimmed = line.Trim();
            if (trimmed.Length == 0)
                continue;

            nonEmptyLineCount++;
            if (!foundHeader)
            {
                header = trimmed;
                foundHeader = true;
            }
        }

        return foundHeader;
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
                + "var h=(document.head||de||b);"
                + "var sid='sares_pdf_viewer_style';"
                + "if(h && !document.getElementById(sid)){"
                + "var st=document.createElement('style'); st.id=sid;"
                + "st.textContent="
                + "'@media (forced-colors: active){*{forced-color-adjust:none !important;}}"
                + " ::selection{background: rgba(255,255,0,0.78) !important; color:#000 !important;}"
                + " .textLayer ::selection{background: rgba(255,255,0,0.78) !important; color:#000 !important;}'"
                + "; h.appendChild(st);}"
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

    private void TitleBar_MouseDown(object sender, MouseButtonEventArgs e)
    {
        if (e.ChangedButton != MouseButton.Left)
            return;

        if (e.ClickCount == 2)
        {
            WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;
            return;
        }

        try
        {
            DragMove();
        }
        catch
        {
        }
    }
}
