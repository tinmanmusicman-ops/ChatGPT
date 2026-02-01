using System.IO;

namespace SARes.engine;

public static class AppLog
{
    private static readonly object Gate = new();

    public static string LogPath { get; } = ResolveLogPath();

    public static void Info(string message) => Write("INFO", message, null);

    public static void Warn(string message) => Write("WARN", message, null);

    public static void Error(string message, Exception? ex = null) => Write("ERROR", message, ex);

    private static void Write(string level, string message, Exception? ex)
    {
        try
        {
            var line = $"{DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss.fff zzz} [{level}] {message}";
            if (ex is not null)
                line += $" | {ex.GetType().Name}: {ex.Message}";

            lock (Gate)
            {
                var dir = Path.GetDirectoryName(LogPath) ?? "";
                if (dir.Length > 0)
                    Directory.CreateDirectory(dir);

                File.AppendAllText(LogPath, line + Environment.NewLine, System.Text.Encoding.UTF8);
            }
        }
        catch
        {
        }
    }

    private static string ResolveLogPath()
    {
        var root = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        var dir = Path.Combine(root, "SARES", "Logs");
        return Path.Combine(dir, "pdf-header-mapping.log");
    }
}
