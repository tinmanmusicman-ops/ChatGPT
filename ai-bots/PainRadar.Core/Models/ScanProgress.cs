namespace PainRadar.Models;

public sealed record ScanProgress(
    string Stage,
    int Completed,
    int Total
)
{
    public double Percent => Total <= 0 ? 0 : (double)Completed / Total * 100.0;
}
