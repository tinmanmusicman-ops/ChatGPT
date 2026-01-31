using System;
using System.IO;
using System.Threading.Tasks;
using System.Windows;
using Markdig;
using SARes.engine;

namespace SARes.ui;

public partial class StartHereFloatingWindow : Window
{
    private readonly string _defaultMarkdownPath;
    private readonly string _cssPath;
    private readonly string _userMarkdownPath;

    public StartHereFloatingWindow(string markdownPath, string cssPath)
    {
        InitializeComponent();
        _defaultMarkdownPath = markdownPath;
        _cssPath = cssPath;
        _userMarkdownPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "SARes", "start_here.md");

        Loaded += async (_, _) => await LoadMarkdownAsync();
        CloseButton.Click += (_, _) => Close();
        MouseEnter += (_, _) => Activate();
    }

    private async Task LoadMarkdownAsync()
    {
        var markdownToLoad = EnsureUserMarkdownCopy();
        if (markdownToLoad is null)
        {
            System.Windows.MessageBox.Show("Start Here markdown missing.", "Start Here", MessageBoxButton.OK, MessageBoxImage.Warning);
            Close();
            return;
        }

        try
        {
            var markdown = await File.ReadAllTextAsync(markdownToLoad).ConfigureAwait(true);
            var css = File.Exists(_cssPath) ? await File.ReadAllTextAsync(_cssPath).ConfigureAwait(true) : string.Empty;
            var html = BuildHtml(markdown, css);

            await WebViewHelpers.EnsureReadyAsync(StartHereWeb).ConfigureAwait(true);
            StartHereWeb.NavigateToString(html);
            await WebViewHelpers.LeftJustifyWebViewAsync(StartHereWeb).ConfigureAwait(true);
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show("Unable to render Start Here guide: " + ex.Message, "Start Here", MessageBoxButton.OK, MessageBoxImage.Error);
            Close();
        }
    }

    private const string StartHerePlaceholderMarker = "SARes start here placeholder (do not edit)";

    private string? EnsureUserMarkdownCopy()
    {
        try
        {
            var dir = Path.GetDirectoryName(_userMarkdownPath);
            if (dir is not null && !Directory.Exists(dir))
                Directory.CreateDirectory(dir);

            var defaultSource = LocateDefaultMarkdownSource();
            if (defaultSource is null)
                return null;

            if (!File.Exists(_userMarkdownPath))
                File.Copy(defaultSource, _userMarkdownPath, overwrite: true);

            if (string.Equals(defaultSource, _defaultMarkdownPath, StringComparison.OrdinalIgnoreCase)
                && !IsPlaceholderFile(_defaultMarkdownPath))
            {
                ArchiveDefaultMarkdownSource();
            }

            return _userMarkdownPath;
        }
        catch
        {
            return null;
        }
    }

    private string? LocateDefaultMarkdownSource()
    {
        if (File.Exists(_defaultMarkdownPath) && !IsPlaceholderFile(_defaultMarkdownPath))
            return _defaultMarkdownPath;

        var archivedPath = _defaultMarkdownPath + ".source";
        if (File.Exists(archivedPath))
            return archivedPath;

        return File.Exists(_defaultMarkdownPath) ? _defaultMarkdownPath : null;
    }

    private static bool IsPlaceholderFile(string path)
    {
        try
        {
            foreach (var line in File.ReadLines(path))
            {
                if (line.Contains(StartHerePlaceholderMarker, StringComparison.Ordinal))
                    return true;
                if (!string.IsNullOrWhiteSpace(line))
                    break;
            }
        }
        catch
        {
        }

        return false;
    }

    private void ArchiveDefaultMarkdownSource()
    {
        var archivedPath = _defaultMarkdownPath + ".source";
        try
        {
            if (!File.Exists(_defaultMarkdownPath))
                return;

            if (File.Exists(archivedPath))
                File.Delete(archivedPath);

            File.Move(_defaultMarkdownPath, archivedPath);

            var appDataPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "SARes");
            var placeholderText = $"""
<!-- {StartHerePlaceholderMarker} -->
This file is a placeholder only. The real Start Here content lives in
{Path.Combine(appDataPath, "start_here.md")}
""";
            File.WriteAllText(_defaultMarkdownPath, placeholderText);
        }
        catch
        {
        }
    }

    private static string BuildHtml(string markdown, string css)
    {
            var body = Markdown.ToHtml(markdown ?? string.Empty);
        return $"""
            <!doctype html>
            <html lang="en">
            <head>
              <meta charset="utf-8" />
              <meta name="viewport" content="width=device-width, initial-scale=1" />
              <style>{css}</style>
            </head>
            <body>
              {body}
            </body>
            </html>
            """;
    }
}
