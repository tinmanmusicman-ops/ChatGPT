using System;
using Hwinfo.SharedMemory;

namespace DiskInsight.Monitoring.Providers;

public sealed class HwinfoGpuTemperatureProvider
{
    private string? _lastError;
    public string? LastError => _lastError;

    public double? ReadIntelGpuTempC()
    {
        _lastError = null;
        try
        {
            var read = HwinfoSharedMemorySession.Shared.ReadLocal();
            _lastError = read.Error ?? HwinfoSharedMemorySession.Shared.LastError;
            if (read.Sensors.Count == 0)
            {
                return null;
            }

            double? best = null;
            var bestScore = int.MinValue;

            foreach (var s in read.Sensors)
            {
                var unit = s.Unit ?? string.Empty;
                if (!TryToCelsius(unit, s.Value, out var tempC))
                {
                    continue;
                }

                if (tempC is < -40 or > 150)
                {
                    continue;
                }

                var label = s.LabelUser ?? s.LabelOrig ?? string.Empty;
                var group = s.GroupLabelUser ?? s.GroupLabelOrig ?? string.Empty;
                var score = ScoreIntelGpuTemp(label, group);
                if (score > bestScore)
                {
                    bestScore = score;
                    best = Math.Round(tempC, 1, MidpointRounding.AwayFromZero);
                }
            }

            if (bestScore < 120)
            {
                return null;
            }

            return best;
        }
        catch (Exception ex)
        {
            _lastError = ex.GetType().Name + ": " + ex.Message;
            return null;
        }
    }

    private static bool TryToCelsius(string unit, double value, out double celsius)
    {
        celsius = default;

        if (string.IsNullOrWhiteSpace(unit))
        {
            return false;
        }

        if (unit.IndexOf("c", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            celsius = value;
            return true;
        }

        if (unit.IndexOf("f", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            celsius = (value - 32d) * (5d / 9d);
            return true;
        }

        return false;
    }

    private static int ScoreIntelGpuTemp(string label, string group)
    {
        var hay = (label + " | " + group).Trim();
        if (hay.Length == 0)
        {
            return 0;
        }

        if (!LooksLikeGpu(hay))
        {
            return 0;
        }

        var s = 0;

        if (hay.IndexOf("intel", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            s += 400;
        }

        if (hay.IndexOf("igpu", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            s += 120;
        }

        if (hay.IndexOf("nvidia", StringComparison.OrdinalIgnoreCase) >= 0 ||
            hay.IndexOf("geforce", StringComparison.OrdinalIgnoreCase) >= 0 ||
            hay.IndexOf("amd", StringComparison.OrdinalIgnoreCase) >= 0 ||
            hay.IndexOf("radeon", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            s -= 1000;
        }

        if (hay.IndexOf("temperature", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            s += 120;
        }

        if (hay.IndexOf("core", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            s += 60;
        }

        if (hay.IndexOf("hot spot", StringComparison.OrdinalIgnoreCase) >= 0 ||
            hay.IndexOf("hotspot", StringComparison.OrdinalIgnoreCase) >= 0 ||
            hay.IndexOf("memory", StringComparison.OrdinalIgnoreCase) >= 0 ||
            hay.IndexOf("junction", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            s -= 200;
        }

        return s;
    }

    private static bool LooksLikeGpu(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return false;
        }

        if (text.IndexOf("gpu", StringComparison.OrdinalIgnoreCase) >= 0 ||
            text.IndexOf("igpu", StringComparison.OrdinalIgnoreCase) >= 0 ||
            text.IndexOf("graphics", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            return true;
        }

        if (text.IndexOf("gt", StringComparison.OrdinalIgnoreCase) >= 0 &&
            (text.IndexOf("temp", StringComparison.OrdinalIgnoreCase) >= 0 || text.IndexOf("temperature", StringComparison.OrdinalIgnoreCase) >= 0))
        {
            return true;
        }

        return false;
    }
}

