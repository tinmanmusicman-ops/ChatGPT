namespace PainRadar.Infrastructure;

public interface IPainRadarLogger
{
    void Info(string message);
    void Warn(string message);
    void Error(string message);
    void Exception(Exception ex, string context);
}

public sealed class NullPainRadarLogger : IPainRadarLogger
{
    public static readonly NullPainRadarLogger Instance = new();

    private NullPainRadarLogger()
    {
    }

    public void Info(string message) { }
    public void Warn(string message) { }
    public void Error(string message) { }
    public void Exception(Exception ex, string context) { }
}

