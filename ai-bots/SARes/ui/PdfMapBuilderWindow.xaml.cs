using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;
using SARes.engine;

namespace SARes.ui;

public partial class PdfMapBuilderWindow : Window
{
    private AppSettings _updated;
    private readonly List<string> _headers = new();
    private readonly List<string> _bulletizedSections = new();
    private bool _contextMenuInitialized;
    private string? _selectedPdfPath;

    public PdfMapBuilderWindow(AppSettings settings)
    {
        InitializeComponent();
        _updated = settings;

        // Start from saved map if present (supports "rebuild map").
        _headers.AddRange((_updated.PdfSectionHeaderAliases ?? Array.Empty<string>()).Where(x => !string.IsNullOrWhiteSpace(x)));
        _bulletizedSections.AddRange(_updated.GetPdfBulletizePreset(_updated.SelectedPdfHeaderPresetName));
        RefreshHeaderList();

        SelectPdfButton.Click += async (_, _) => await SelectPdfAsync();
        SaveMapButton.Click += (_, _) => SaveMap();
        CancelButton.Click += (_, _) => Close();

        Loaded += async (_, _) =>
        {
            try
            {
                await WebViewHelpers.EnsureReadyAsync(PdfWeb);
                InitializePdfContextMenu();
            }
            catch
            {
            }
        };

        HeaderMapListBox.MouseDoubleClick += (_, _) => RemoveSelectedHeaderFromList();
        StatusText.Text = "Select a PDF to begin.";
    }

    public AppSettings UpdatedSettings => _updated;
    public string? SelectedPdfPath => _selectedPdfPath;

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

        _selectedPdfPath = pdfPath;

        StatusText.Text = "Loading preview...";
        try
        {
            await WebViewHelpers.EnsureReadyAsync(PdfWeb);
            PdfWeb.Source = new System.Uri(pdfPath);
            PdfWeb.ZoomFactor = 1.25;
            StatusText.Text = "Preview ready. Right-click the PDF to tag headers.";
            await TopLeftJustifyWebViewAsync(PdfWeb);
        }
        catch
        {
            StatusText.Text = "Preview load failed.";
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
            args.MenuItems.Insert(0, tagItem);
        }
        catch
        {
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

        Dispatcher.Invoke(() => AddHeader(selection));
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
     return text.split(/\r?\n/)[0];
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

    private void AddHeader(string header)
    {
        var normalized = (header ?? "").Trim();
        if (normalized.Length == 0)
            return;

        if (_headers.Any(h => h.Equals(normalized, StringComparison.OrdinalIgnoreCase)))
        {
            StatusText.Text = $"Header already tracked: {normalized}";
            return;
        }

        _headers.Add(normalized);
        RefreshHeaderList();
        StatusText.Text = $"Added header: {normalized}";
    }

    private void RefreshHeaderList()
    {
        HeaderMapListBox.Items.Clear();
        foreach (var header in _headers)
        {
            var isBulletized = _bulletizedSections.Any(b => b.Equals(header, StringComparison.OrdinalIgnoreCase));

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

        var existingIdx = _bulletizedSections.FindIndex(h => h.Equals(normalized, StringComparison.OrdinalIgnoreCase));

        if (enabled)
        {
            if (existingIdx < 0)
                _bulletizedSections.Add(normalized);
            return;
        }

        if (existingIdx >= 0)
            _bulletizedSections.RemoveAt(existingIdx);
    }

    private void RemoveSelectedHeaderFromList()
    {
        if (HeaderMapListBox.SelectedItem is System.Windows.Controls.ListBoxItem item && item.Tag is string header)
        {
            _headers.RemoveAll(h => h.Equals(header, StringComparison.OrdinalIgnoreCase));
            _bulletizedSections.RemoveAll(h => h.Equals(header, StringComparison.OrdinalIgnoreCase));
            RefreshHeaderList();
            StatusText.Text = $"Removed header: {header}";
        }
    }

    private void SaveMap()
    {
        if (_headers.Count == 0)
        {
            System.Windows.MessageBox.Show("Add at least one header before saving.", "SARes", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        if (string.IsNullOrWhiteSpace(_selectedPdfPath))
        {
            System.Windows.MessageBox.Show("Select a PDF before saving.", "SARes", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        var presetName = (_updated.SelectedPdfHeaderPresetName ?? "").Trim();
        if (presetName.Length == 0)
            presetName = "Default";

        _updated = _updated
            .WithPdfSectionHeaderAliases(_headers)
            .WithPdfBulletizePreset(presetName, _bulletizedSections);
        AppSettingsStore.Save(_updated);

        StatusText.Text = "Map saved.";
        DialogResult = true;
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

