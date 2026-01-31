using System.Diagnostics;
using System.IO;
using SARes.engine;

namespace SARes.renderer;

public sealed class ToolLocator
{
    private readonly AppSettings _settings;

    public ToolLocator(AppSettings settings) => _settings = settings;

    public string ResolvePandoc()
        => ResolveTool("pandoc", _settings.PandocPath, defaultExe: "pandoc.exe");

    private static string ResolveTool(string displayName, string? configuredPath, string defaultExe)
    {
        if (!string.IsNullOrWhiteSpace(configuredPath))
        {
            var p = configuredPath.Trim();
            if (File.Exists(p))
                return p;
            throw new FileNotFoundException($"{displayName} not found at configured path: {p}");
        }

        var fromPath = TryFindOnPath(defaultExe);
        if (fromPath is not null)
            return fromPath;

        throw new FileNotFoundException($"{displayName} not found. Install it or set its path in the app.");
    }

    internal static string? TryFindOnPath(string exeName)
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "where",
                Arguments = exeName,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };
            using var p = Process.Start(psi);
            if (p is null)
                return null;
            var stdout = p.StandardOutput.ReadToEnd();
            p.WaitForExit(2000);
            var first = (stdout ?? "").Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries).FirstOrDefault();
            return string.IsNullOrWhiteSpace(first) ? null : first.Trim();
        }
        catch
        {
            return null;
        }
    }
}
