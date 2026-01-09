using System;
using System.Collections.Generic;
using System.Globalization;

namespace DiskInsight.Monitoring.Providers;

public sealed class CpuUsageProvider
{
    private string? _lastError;
    public string? LastError => _lastError;

    public double? ReadTotalCpuUsagePercent()
    {
        _lastError = null;
        try
        {
            var result = LibreHardwareCpuSession.Shared.Read(expectedCores: 64);
            _lastError = result.Error ?? LibreHardwareCpuSession.Shared.LastError;

            if (result.TotalLoadPercent is { } total)
            {
                return Math.Clamp(Math.Round(total, 1), 0d, 100d);
            }

            if (result.CoreLoadsPercent.Count > 0)
            {
                var avg = result.CoreLoadsPercent.Values.Average();
                return Math.Clamp(Math.Round(avg, 1), 0d, 100d);
            }

            _lastError ??= "No CPU load sensors found.";
            return null;
        }
        catch (Exception ex)
        {
            _lastError = ex.GetType().Name + ": " + ex.Message;
            return null;
        }
    }

    public IReadOnlyDictionary<int, double> ReadCoreUsagePercentById(int expectedCores)
    {
        expectedCores = Math.Clamp(expectedCores, 1, 64);

        _lastError = null;
        try
        {
            var result = LibreHardwareCpuSession.Shared.Read(expectedCores);
            _lastError = result.Error ?? LibreHardwareCpuSession.Shared.LastError;

            var cleaned = result.CoreLoadsPercent
                .Where(kvp => kvp.Key >= 0 && kvp.Key < expectedCores)
                .ToDictionary(kvp => kvp.Key, kvp => Math.Clamp(Math.Round(kvp.Value, 1), 0d, 100d));

            if (cleaned.Count == 0)
            {
                _lastError ??= "No per-core CPU load sensors found.";
            }

            return cleaned;
        }
        catch (Exception ex)
        {
            _lastError = ex.GetType().Name + ": " + ex.Message;
            return new Dictionary<int, double>();
        }
    }
}
