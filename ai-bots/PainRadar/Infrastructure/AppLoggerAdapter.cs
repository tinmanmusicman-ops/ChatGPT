namespace PainRadar.Infrastructure;

public sealed class AppLoggerAdapter : IPainRadarLogger
{
    public void Info(string message) => AppLogger.Info(message);
    public void Warn(string message) => AppLogger.Warn(message);
    public void Error(string message) => AppLogger.Error(message);
    public void Exception(Exception ex, string context) => AppLogger.Exception(ex, context);
}
