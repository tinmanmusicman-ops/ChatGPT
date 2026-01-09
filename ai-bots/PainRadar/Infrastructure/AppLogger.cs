using System.Diagnostics;
using System.IO;
using System.Text;

namespace PainRadar.Infrastructure;

public static class AppLogger
{
    private static readonly object Gate = new();
    private static string? _logPath;
    private static int _initialized;

    public static string LogPath => _logPath ?? "";

    public static void Initialize(string? preferredPath = null)
    {
        if (Interlocked.Exchange(ref _initialized, 1) != 0)
            return;

        try
        {
            Debug.AutoFlush = true;
            Trace.AutoFlush = true;
        }
        catch
        {
        }

        var envPath = Environment.GetEnvironmentVariable("PAINRADAR_LOG_PATH");
        if (!string.IsNullOrWhiteSpace(envPath))
        {
            _logPath = envPath.Trim();
            EnsureDirectory(_logPath);
            Info($"Logging initialized (PAINRADAR_LOG_PATH): {_logPath}");
            return;
        }

        if (!string.IsNullOrWhiteSpace(preferredPath))
        {
            _logPath = preferredPath.Trim();
            EnsureDirectory(_logPath);
            Info($"Logging initialized (preferred): {_logPath}");
            return;
        }

        _logPath = Path.Combine(Environment.CurrentDirectory, "painradar.log");
        EnsureDirectory(_logPath);
        Info($"Logging initialized (cwd): {_logPath}");
    }

    public static void Info(string message) => Write("INFO", message);
    public static void Warn(string message) => Write("WARN", message);
    public static void Error(string message) => Write("ERROR", message);

    public static void Exception(Exception ex, string context)
    {
        var sb = new StringBuilder();
        sb.AppendLine($"{context}: {ex.GetType().FullName}: {ex.Message}");
        sb.AppendLine(ex.StackTrace ?? "");
        if (ex.InnerException is not null)
        {
            sb.AppendLine("InnerException:");
            sb.AppendLine($"{ex.InnerException.GetType().FullName}: {ex.InnerException.Message}");
            sb.AppendLine(ex.InnerException.StackTrace ?? "");
        }
        Write("EX", sb.ToString().TrimEnd());
    }

    private static void Write(string level, string message)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(_logPath))
                return;

            var line = $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff}] {level} {message}{Environment.NewLine}";
            lock (Gate)
            {
                File.AppendAllText(_logPath!, line, Encoding.UTF8);
            }
            Debug.Write(line);
            Trace.Write(line);
            try { Console.Error.Write(line); } catch { }
        }
        catch
        {
        }
    }

    private static void EnsureDirectory(string path)
    {
        try
        {
            var dir = Path.GetDirectoryName(path);
            if (!string.IsNullOrWhiteSpace(dir))
                Directory.CreateDirectory(dir);
        }
        catch
        {
        }
    }
}
