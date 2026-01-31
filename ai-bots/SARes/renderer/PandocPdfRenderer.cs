using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;

namespace SARes.renderer;

public sealed class PandocPdfRenderer
{
    private readonly string _pandocPath;
    private readonly string _wkhtmltopdfPath;

    public PandocPdfRenderer(string pandocPath, string wkhtmltopdfPath)
    {
        _pandocPath = pandocPath;
        _wkhtmltopdfPath = wkhtmltopdfPath;
    }

    public async Task RenderMarkdownToPdfAsync(string markdown, string cssPath, string outputPdfPath)
    {
        if (string.IsNullOrWhiteSpace(markdown))
            throw new ArgumentException("Markdown is empty.", nameof(markdown));
        if (string.IsNullOrWhiteSpace(cssPath) || !File.Exists(cssPath))
            throw new FileNotFoundException("CSS file not found: " + cssPath);

        Directory.CreateDirectory(Path.GetDirectoryName(outputPdfPath)!);

        var tempDir = Path.Combine(Path.GetTempPath(), "SARES", "render");
        Directory.CreateDirectory(tempDir);
        var mdPath = Path.Combine(tempDir, Guid.NewGuid().ToString("N") + ".md");
        await File.WriteAllTextAsync(mdPath, markdown, Encoding.UTF8).ConfigureAwait(false);

        try
        {
            var args = new StringBuilder();
            args.Append($"\"{mdPath}\" ");
            args.Append("--standalone ");
            args.Append("--from=gfm ");
            args.Append($"--css=\"{cssPath}\" ");
            args.Append($"--pdf-engine=\"{_wkhtmltopdfPath}\" ");
            args.Append($"-o \"{outputPdfPath}\"");

            var environmentOverrides = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                ["TMP"] = tempDir,
                ["TEMP"] = tempDir
            };

            var result = await RunAsync(_pandocPath, args.ToString(), tempDir, environmentOverrides).ConfigureAwait(false);
            if (result.ExitCode != 0)
                throw new InvalidOperationException($"Pandoc failed ({result.ExitCode}): {result.StdErr}\n{result.StdOut}".Trim());
        }
        finally
        {
            try { File.Delete(mdPath); } catch { }
        }
    }

    private static async Task<(int ExitCode, string StdOut, string StdErr)> RunAsync(
        string fileName,
        string arguments,
        string? workingDirectory = null,
        IDictionary<string, string>? environment = null)
    {
        var psi = new ProcessStartInfo
        {
            FileName = fileName,
            Arguments = arguments,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        };

        if (!string.IsNullOrWhiteSpace(workingDirectory))
            psi.WorkingDirectory = workingDirectory;

        if (environment is not null)
        {
            foreach (var kvp in environment)
            {
                if (kvp.Value is null)
                    psi.Environment.Remove(kvp.Key);
                else
                    psi.Environment[kvp.Key] = kvp.Value;
            }
        }

        using var proc = Process.Start(psi);
        if (proc is null)
            throw new InvalidOperationException("Failed to start process: " + fileName);

        var stdout = await proc.StandardOutput.ReadToEndAsync().ConfigureAwait(false);
        var stderr = await proc.StandardError.ReadToEndAsync().ConfigureAwait(false);
        await proc.WaitForExitAsync().ConfigureAwait(false);
        return (proc.ExitCode, stdout, stderr);
    }
}
