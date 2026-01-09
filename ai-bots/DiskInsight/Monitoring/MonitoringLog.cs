using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;

namespace DiskInsight.Monitoring;

internal static class MonitoringLog
{
    private static readonly object Gate = new();

    private static readonly string LogPath = ResolveLogPath();

    public static bool RawLibreEnabled =>
        string.Equals(Environment.GetEnvironmentVariable("DISKINSIGHT_LHM_RAW"), "1", StringComparison.OrdinalIgnoreCase);

    private static string ResolveLogPath()
    {
        try
        {
            var explicitDir = Environment.GetEnvironmentVariable("DISKINSIGHT_LOG_DIR");
            if (!string.IsNullOrWhiteSpace(explicitDir))
            {
                return Path.Combine(explicitDir.Trim(), "monitoring.log");
            }

            // Prefer repository/project root (dev scenario) so logs land in the root folder.
            var root = TryFindProjectRoot(AppContext.BaseDirectory)
                       ?? TryFindProjectRoot(Environment.CurrentDirectory);
            if (!string.IsNullOrWhiteSpace(root))
            {
                return Path.Combine(root!, "monitoring.log");
            }

            // Fallback to executable directory (publish/installed scenario).
            if (!string.IsNullOrWhiteSpace(AppContext.BaseDirectory))
            {
                return Path.Combine(AppContext.BaseDirectory, "monitoring.log");
            }
        }
        catch
        {
        }

        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "DiskInsight",
            "monitoring.log");
    }

    private static string? TryFindProjectRoot(string? startDir)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(startDir))
            {
                return null;
            }

            var dir = new DirectoryInfo(startDir);
            while (dir is not null)
            {
                if (File.Exists(Path.Combine(dir.FullName, "DiskInsight.sln")) ||
                    File.Exists(Path.Combine(dir.FullName, "DiskInsight.csproj")) ||
                    Directory.Exists(Path.Combine(dir.FullName, ".git")))
                {
                    return dir.FullName;
                }

                dir = dir.Parent;
            }
        }
        catch
        {
        }

        return null;
    }

    public static void WriteLine(string message)
    {
        try
        {
            var line = $"[{DateTimeOffset.Now:O}] {message}";

            lock (Gate)
            {
                var dir = Path.GetDirectoryName(LogPath);
                if (!string.IsNullOrWhiteSpace(dir))
                {
                    Directory.CreateDirectory(dir);
                }

                RotateIfTooLarge();
                File.AppendAllText(LogPath, line + Environment.NewLine, Encoding.UTF8);
            }

            try
            {
                Debug.WriteLine(line);
            }
            catch
            {
            }
        }
        catch
        {
        }
    }

    private static void RotateIfTooLarge()
    {
        try
        {
            var fi = new FileInfo(LogPath);
            if (!fi.Exists)
            {
                return;
            }

            const long maxBytes = 5 * 1024 * 1024;
            if (fi.Length < maxBytes)
            {
                return;
            }

            var rotated = LogPath + ".1";
            try
            {
                if (File.Exists(rotated))
                {
                    File.Delete(rotated);
                }
            }
            catch
            {
            }

            try
            {
                File.Move(LogPath, rotated);
            }
            catch
            {
            }
        }
        catch
        {
        }
    }
}
