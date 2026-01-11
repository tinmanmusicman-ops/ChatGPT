using System;
using System.Globalization;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using LibreHardwareMonitor.Hardware;
using DiskInsight.Monitoring;

namespace DiskInsight.Monitoring.Providers;

internal sealed class LibreHardwareGpuSession : IDisposable
{
    public static LibreHardwareGpuSession Shared { get; } = new();

    private readonly object _gate = new();
    private Computer? _computer;
    private IHardware[]? _gpus;

    private long _lastReadTick;
    private GpuReadResult? _lastRead;
    private string? _lastError;
    private long _lastSummaryLogTick;
    private long _lastRawLogTick;

    public string? LastError
    {
        get
        {
            lock (_gate)
            {
                return _lastError;
            }
        }
    }

    public void Reset()
    {
        lock (_gate)
        {
            try
            {
                _computer?.Close();
            }
            catch
            {
            }

            _computer = null;
            _gpus = null;
            _lastRead = null;
            _lastError = null;
            _lastReadTick = 0;
            _lastSummaryLogTick = 0;
            _lastRawLogTick = 0;
        }
    }

    public GpuReadResult ReadAll()
    {
        lock (_gate)
        {
            var now = Environment.TickCount64;
            if (_lastRead is not null && (now - _lastReadTick) < 250)
            {
                return _lastRead;
            }

            try
            {
                EnsureOpenGpus();
                if (_gpus is null || _gpus.Length == 0)
                {
                    _lastError = "No GPU hardware found.";
                    return Cache(new GpuReadResult(
                        Devices: Array.Empty<GpuDeviceReadResult>(),
                        Error: _lastError));
                }

                var devices = new GpuDeviceReadResult[_gpus.Length];
                for (var i = 0; i < _gpus.Length; i++)
                {
                    var gpu = _gpus[i];
                    UpdateHardwareRecursive(gpu);

                    double? bestLoad = null;
                    var bestLoadScore = int.MinValue;

                    double? bestTemp = null;
                    var bestTempScore = int.MinValue;

                    ReadGpuSensorsRecursive(gpu, ref bestLoad, ref bestLoadScore, ref bestTemp, ref bestTempScore);
                    devices[i] = new GpuDeviceReadResult(
                        Name: gpu.Name,
                        HardwareType: gpu.HardwareType,
                        CoreLoadPercent: bestLoad,
                        CoreTempC: bestTemp);
                }
                TryLog(now, _gpus, devices);

                _lastError = null;
                return Cache(new GpuReadResult(
                    Devices: devices,
                    Error: null));
            }
            catch (Exception ex)
            {
                _lastError = ex.GetType().Name + ": " + ex.Message;
                TryLog(now, _gpus, Array.Empty<GpuDeviceReadResult>(), error: _lastError);
                return Cache(new GpuReadResult(
                    Devices: Array.Empty<GpuDeviceReadResult>(),
                    Error: _lastError));
            }
        }
    }

    private void TryLog(long nowTick, IHardware[]? hardware, IReadOnlyList<GpuDeviceReadResult> devices, string? error = null)
    {
        try
        {
            const int summaryEveryMs = 5_000;
            const int rawEveryMs = 10_000;

            if (nowTick - _lastSummaryLogTick >= summaryEveryMs)
            {
                _lastSummaryLogTick = nowTick;
                var sb = new StringBuilder(512);
                sb.Append("LHM GPU summary: ");
                if (!string.IsNullOrWhiteSpace(error))
                {
                    sb.Append("error=").Append(error).Append(" ");
                }

                if (devices.Count == 0)
                {
                    sb.Append("devices=0");
                }
                else
                {
                    sb.Append("devices=").Append(devices.Count).Append(" ");
                    for (var i = 0; i < devices.Count; i++)
                    {
                        var d = devices[i];
                        sb.Append('[').Append(i).Append("] ");
                        sb.Append(d.HardwareType).Append(' ');
                        sb.Append('"').Append(d.Name ?? "n/a").Append('"').Append(' ');
                        sb.Append("load=").Append(d.CoreLoadPercent?.ToString("0.0", CultureInfo.InvariantCulture) ?? "n/a").Append("% ");
                        sb.Append("tempC=").Append(d.CoreTempC?.ToString("0.0", CultureInfo.InvariantCulture) ?? "n/a");
                        if (i < devices.Count - 1)
                        {
                            sb.Append(" | ");
                        }
                    }
                }

                MonitoringLog.WriteLine(sb.ToString());
            }

            if (MonitoringLog.RawLibreEnabled && nowTick - _lastRawLogTick >= rawEveryMs)
            {
                _lastRawLogTick = nowTick;
                if (hardware is null || hardware.Length == 0)
                {
                    MonitoringLog.WriteLine("LHM GPU raw: no hardware");
                    return;
                }

                var sb = new StringBuilder(8_192);
                sb.AppendLine("LHM GPU raw dump:");
                for (var i = 0; i < hardware.Length; i++)
                {
                    var hw = hardware[i];
                    sb.AppendLine($"--- GPU[{i}] name=\"{hw.Name}\" type={hw.HardwareType} id={hw.Identifier} ---");
                    AppendHardwareDump(sb, hw, indent: "  ");
                }

                MonitoringLog.WriteLine(sb.ToString().TrimEnd());
            }
        }
        catch
        {
        }
    }

    private static void AppendHardwareDump(StringBuilder sb, IHardware hardware, string indent)
    {
        try
        {
            foreach (var sensor in hardware.Sensors)
            {
                var value = sensor.Value is null ? "null" : sensor.Value.Value.ToString("0.###", CultureInfo.InvariantCulture);
                var min = sensor.Min is null ? "null" : sensor.Min.Value.ToString("0.###", CultureInfo.InvariantCulture);
                var max = sensor.Max is null ? "null" : sensor.Max.Value.ToString("0.###", CultureInfo.InvariantCulture);
                sb.Append(indent)
                    .Append("sensor type=").Append(sensor.SensorType)
                    .Append(" name=\"").Append(sensor.Name).Append('"')
                    .Append(" value=").Append(value)
                    .Append(" min=").Append(min)
                    .Append(" max=").Append(max)
                    .Append(" id=").Append(sensor.Identifier)
                    .AppendLine();
            }
        }
        catch
        {
        }

        try
        {
            foreach (var sub in hardware.SubHardware)
            {
                sb.Append(indent).Append("subhw name=\"").Append(sub.Name).Append("\" type=").Append(sub.HardwareType).Append(" id=").Append(sub.Identifier).AppendLine();
                AppendHardwareDump(sb, sub, indent + "  ");
            }
        }
        catch
        {
        }
    }

    private GpuReadResult Cache(GpuReadResult result)
    {
        _lastRead = result;
        _lastReadTick = Environment.TickCount64;
        return result;
    }

    private void EnsureOpenGpus()
    {
        if (_computer is null)
        {
            _computer = new Computer
            {
                // Some systems expose the Intel iGPU under/alongside CPU hardware; enable CPU so it can be discovered.
                IsCpuEnabled = true,
                IsGpuEnabled = true,
                IsMemoryEnabled = false,
                IsMotherboardEnabled = false,
                IsControllerEnabled = false,
                IsNetworkEnabled = false,
                IsStorageEnabled = false,
            };
        }

        if (_gpus is not null)
        {
            return;
        }

        try
        {
            _computer.Open();
        }
        catch
        {
        }

        try
        {
            var gpus = new List<IHardware>(capacity: 4);
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            try
            {
                foreach (var root in _computer.Hardware)
                {
                    // Ensure sub-hardware (e.g., Intel iGPU under CPU) is materialized before discovery.
                    UpdateHardwareRecursive(root);
                    CollectGpusRecursive(root, gpus, seen);
                }
            }
            catch
            {
            }

            _gpus = gpus
                // Prefer iGPU first to better match common OS labeling (GPU0=iGPU).
                .OrderByDescending(h => h.HardwareType == HardwareType.GpuIntel)
                .ThenByDescending(h => h.HardwareType == HardwareType.GpuAmd)
                .ThenByDescending(h => h.HardwareType == HardwareType.GpuNvidia)
                .ThenBy(h => h.Name ?? string.Empty, StringComparer.OrdinalIgnoreCase)
                .ToArray();
        }
        catch
        {
            _gpus = null;
        }
    }

    private static void CollectGpusRecursive(IHardware hardware, List<IHardware> gpus, HashSet<string> seen)
    {
        try
        {
            if (hardware.HardwareType is HardwareType.GpuIntel or HardwareType.GpuAmd or HardwareType.GpuNvidia)
            {
                var id = hardware.Identifier?.ToString() ?? hardware.Name ?? Guid.NewGuid().ToString("N");
                if (seen.Add(id))
                {
                    gpus.Add(hardware);
                }
            }
        }
        catch
        {
        }

        try
        {
            foreach (var sub in hardware.SubHardware)
            {
                CollectGpusRecursive(sub, gpus, seen);
            }
        }
        catch
        {
        }
    }

    private static void UpdateHardwareRecursive(IHardware hardware)
    {
        try
        {
            hardware.Update();
        }
        catch
        {
        }

        try
        {
            foreach (var sub in hardware.SubHardware)
            {
                UpdateHardwareRecursive(sub);
            }
        }
        catch
        {
        }
    }

    private static void ReadGpuSensorsRecursive(
        IHardware hardware,
        ref double? bestLoad,
        ref int bestLoadScore,
        ref double? bestTemp,
        ref int bestTempScore)
    {
        try
        {
            foreach (var sensor in hardware.Sensors)
            {
                if (sensor.Value is null)
                {
                    continue;
                }

                var name = sensor.Name ?? string.Empty;

                if (sensor.SensorType == SensorType.Load)
                {
                    var p = Math.Clamp(sensor.Value.Value, 0f, 100f);
                    var score = ScoreGpuLoadSensorName(name);
                    if (score > bestLoadScore)
                    {
                        bestLoadScore = score;
                        bestLoad = Math.Round(p, 1, MidpointRounding.AwayFromZero);
                    }
                }

                if (sensor.SensorType == SensorType.Temperature)
                {
                    var c = Convert.ToDouble(sensor.Value.Value, CultureInfo.InvariantCulture);
                    if (c is < -40 or > 150)
                    {
                        continue;
                    }

                    var score = ScoreGpuTempSensorName(name);
                    if (score > bestTempScore)
                    {
                        bestTempScore = score;
                        bestTemp = Math.Round(c, 1, MidpointRounding.AwayFromZero);
                    }
                }
            }
        }
        catch
        {
        }

        try
        {
            foreach (var sub in hardware.SubHardware)
            {
                ReadGpuSensorsRecursive(sub, ref bestLoad, ref bestLoadScore, ref bestTemp, ref bestTempScore);
            }
        }
        catch
        {
        }
    }

    private static int ScoreGpuLoadSensorName(string name)
    {
        if (string.IsNullOrWhiteSpace(name))
        {
            return 0;
        }

        var s = 0;
        if (name.IndexOf("GPU", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            s += 20;
        }

        if (name.IndexOf("Core", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            s += 30;
        }

        if (name.IndexOf("Total", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            s += 15;
        }

        if (name.IndexOf("3D", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            s += 10;
        }

        if (name.IndexOf("Memory", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            s -= 40;
        }

        return s;
    }

    private static int ScoreGpuTempSensorName(string name)
    {
        if (string.IsNullOrWhiteSpace(name))
        {
            return 0;
        }

        var s = 0;
        if (name.IndexOf("GPU", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            s += 20;
        }

        if (name.IndexOf("Core", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            s += 30;
        }

        if (name.IndexOf("Hot Spot", StringComparison.OrdinalIgnoreCase) >= 0 ||
            name.IndexOf("HotSpot", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            s -= 5;
        }

        if (name.IndexOf("Memory", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            s -= 40;
        }

        return s;
    }

    public void Dispose()
    {
        lock (_gate)
        {
            try
            {
                _computer?.Close();
            }
            catch
            {
            }

            _gpus = null;
            _computer = null;
            _lastRead = null;
        }
    }
}

internal sealed record GpuReadResult(
    IReadOnlyList<GpuDeviceReadResult> Devices,
    string? Error);

internal sealed record GpuDeviceReadResult(
    string? Name,
    HardwareType HardwareType,
    double? CoreLoadPercent,
    double? CoreTempC);
