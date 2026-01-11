using System;
using Hwinfo.SharedMemory;

namespace DiskInsight.Monitoring.Providers;

public sealed class HwinfoFanSpeedProvider
{
    private string? _lastError;
    public string? LastError => _lastError;

    public HwinfoFanSpeedSnapshot Read()
    {
        _lastError = null;
        try
        {
            var read = HwinfoSharedMemorySession.Shared.ReadLocal();
            _lastError = read.Error ?? HwinfoSharedMemorySession.Shared.LastError;
            if (read.Sensors.Count == 0)
            {
                return new HwinfoFanSpeedSnapshot(CpuFanRpm: null, GpuFanRpm: null);
            }

            var bestCpu = (rpm: (int?)null, score: int.MinValue);
            var bestGpu = (rpm: (int?)null, score: int.MinValue);

            foreach (var sensor in read.Sensors)
            {
                if (sensor.Type != SensorType.SensorTypeFan)
                {
                    continue;
                }

                var value = sensor.Value;
                if (double.IsNaN(value) || double.IsInfinity(value) || value < 0)
                {
                    continue;
                }

                var rpm = (int)Math.Round(value, MidpointRounding.AwayFromZero);
                if (rpm > 20_000)
                {
                    continue;
                }

                var label = (sensor.LabelUser ?? sensor.LabelOrig ?? string.Empty).Trim();
                var group = (sensor.GroupLabelUser ?? sensor.GroupLabelOrig ?? string.Empty).Trim();
                var hay = (label + " | " + group).Trim();
                if (hay.Length == 0)
                {
                    continue;
                }

                var text = hay.ToLowerInvariant();
                if (!text.Contains("fan"))
                {
                    continue;
                }

                var cpuScore = Score(text, kind: "cpu");
                if (cpuScore > bestCpu.score)
                {
                    bestCpu = (rpm, cpuScore);
                }

                var gpuScore = Score(text, kind: "gpu");
                if (gpuScore > bestGpu.score)
                {
                    bestGpu = (rpm, gpuScore);
                }
            }

            if (bestCpu.score < 200)
            {
                bestCpu.rpm = null;
            }

            if (bestGpu.score < 200)
            {
                bestGpu.rpm = null;
            }

            return new HwinfoFanSpeedSnapshot(CpuFanRpm: bestCpu.rpm, GpuFanRpm: bestGpu.rpm);
        }
        catch (Exception ex)
        {
            _lastError = ex.GetType().Name + ": " + ex.Message;
            return new HwinfoFanSpeedSnapshot(CpuFanRpm: null, GpuFanRpm: null);
        }
    }

    private static int Score(string text, string kind)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return int.MinValue;
        }

        var s = 0;

        if (text.Contains("msi ec"))
        {
            s += 50;
        }

        if (text.Contains("fan"))
        {
            s += 100;
        }

        if (text.Contains("rpm"))
        {
            s += 20;
        }

        if (kind == "cpu")
        {
            if (text.Contains("(cpu)") || text.Contains(" cpu"))
            {
                s += 300;
            }

            if (text.Contains("fan 1"))
            {
                s += 120;
            }
        }
        else if (kind == "gpu")
        {
            if (text.Contains("(gpu)") || text.Contains(" gpu") || text.Contains("vga"))
            {
                s += 300;
            }

            if (text.Contains("fan 2"))
            {
                s += 120;
            }
        }

        return s;
    }
}

public sealed record HwinfoFanSpeedSnapshot(
    int? CpuFanRpm,
    int? GpuFanRpm);

