using System.IO;
using System.Net.Http;
using SharpCompress.Archives;
using SharpCompress.Common;

namespace SARes.renderer;

public static class WkhtmltopdfProvisioner
{
    // Source: wkhtmltopdf official packaging repo (Windows cross-build archive).
    private const string DefaultWkhtml7zUrl =
        "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox-0.12.6-1.mxe-cross-win64.7z";

    public static async Task<string> ResolveOrInstallAsync(Action<string>? status = null)
    {
        // Allow power users to override via env var.
        var env = (Environment.GetEnvironmentVariable("SARES_WKHTMLTOPDF_PATH") ?? "").Trim();
        if (env.Length > 0)
        {
            if (File.Exists(env))
                return env;
            throw new FileNotFoundException("wkhtmltopdf not found at SARES_WKHTMLTOPDF_PATH: " + env);
        }

        // If already provisioned, use it.
        var existing = TryFindProvisionedBinary();
        if (existing is not null)
            return existing;

        // If installed on PATH, use it.
        var fromPath = ToolLocator.TryFindOnPath("wkhtmltopdf.exe");
        if (fromPath is not null)
            return fromPath;

        status?.Invoke("Downloading wkhtmltopdf (one-time)...");
        var toolsDir = ToolsDir();
        Directory.CreateDirectory(toolsDir);

        var downloadPath = Path.Combine(toolsDir, "wkhtmltox-win64.7z");
        await DownloadAsync(DefaultWkhtml7zUrl, downloadPath).ConfigureAwait(false);

        status?.Invoke("Extracting wkhtmltopdf...");
        var extractDir = Path.Combine(toolsDir, "wkhtmltox");
        Directory.CreateDirectory(extractDir);

        ExtractArchiveToDirectory(downloadPath, extractDir);

        var wk = FindWkhtmltopdfExe(extractDir);
        if (wk is null)
            throw new FileNotFoundException("wkhtmltopdf.exe not found after extraction.");

        return wk;
    }

    private static string? TryFindProvisionedBinary()
    {
        var toolsDir = ToolsDir();
        if (!Directory.Exists(toolsDir))
            return null;

        var extractDir = Path.Combine(toolsDir, "wkhtmltox");
        return FindWkhtmltopdfExe(extractDir);
    }

    private static string? FindWkhtmltopdfExe(string root)
    {
        if (!Directory.Exists(root))
            return null;

        // Common path inside the wkhtmltox distribution.
        var common = Path.Combine(root, "bin", "wkhtmltopdf.exe");
        if (File.Exists(common))
            return common;

        // Fallback: search recursively.
        return Directory.GetFiles(root, "wkhtmltopdf.exe", SearchOption.AllDirectories).FirstOrDefault();
    }

    private static string ToolsDir()
    {
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        return Path.Combine(local, "SARES", "Tools");
    }

    private static async Task DownloadAsync(string url, string destinationPath)
    {
        // If already downloaded, reuse.
        if (File.Exists(destinationPath) && new FileInfo(destinationPath).Length > 1024 * 1024)
            return;

        using var http = new HttpClient();
        using var resp = await http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead).ConfigureAwait(false);
        resp.EnsureSuccessStatusCode();

        await using var fs = new FileStream(destinationPath, FileMode.Create, FileAccess.Write, FileShare.None);
        await resp.Content.CopyToAsync(fs).ConfigureAwait(false);
    }

    private static void ExtractArchiveToDirectory(string archivePath, string outputDir)
    {
        using var archive = ArchiveFactory.Open(archivePath);
        foreach (var entry in archive.Entries.Where(e => !e.IsDirectory))
        {
            entry.WriteToDirectory(outputDir, new ExtractionOptions
            {
                ExtractFullPath = true,
                Overwrite = true
            });
        }
    }
}

