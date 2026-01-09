using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;
using LibreHardwareMonitor.Hardware;

namespace DiskInsight.Monitoring.Providers;

internal sealed class LibreHardwareCpuSession : IDisposable
{
    private static readonly Regex CoreIndexRegex = new(
        pattern: @"\bCore\s*#?\s*(\d+)\b",
        options: RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);

    public static LibreHardwareCpuSession Shared { get; } = new();

    private readonly object _gate = new();
    private Computer? _computer;
    private IHardware? _cpu;

    private long _lastReadTick;
    private CpuReadResult? _lastRead;
    private string? _lastError;

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

    public CpuReadResult Read(int expectedCores)
    {
        expectedCores = Math.Clamp(expectedCores, 1, 64);

        lock (_gate)
        {
            // If multiple providers call within the same UI tick, avoid repeating hardware updates.
            var now = Environment.TickCount64;
            if (_lastRead is not null && (now - _lastReadTick) < 250)
            {
                return _lastRead;
            }

            try
            {
                EnsureOpenCpu();
                if (_cpu is null)
                {
                    _lastError = "No CPU hardware found.";
                    return Cache(new CpuReadResult(
                        CoreTempsC: new Dictionary<int, double>(),
                        PackageTempC: null,
                        CoreLoadsPercent: new Dictionary<int, double>(),
                        TotalLoadPercent: null,
                        Error: _lastError));
                }

                UpdateHardwareRecursive(_cpu);

                var tempZeroBased = DetectZeroBasedIndexing(_cpu, SensorType.Temperature);
                var loadZeroBased = DetectZeroBasedIndexing(_cpu, SensorType.Load);

                var coreTemps = new Dictionary<int, double>(capacity: expectedCores);
                var coreLoads = new Dictionary<int, double>(capacity: expectedCores);
                double? packageTempC = null;
                double? totalLoad = null;

                ReadCpuSensorsRecursive(
                    _cpu,
                    expectedCores,
                    tempZeroBased,
                    loadZeroBased,
                    coreTemps,
                    coreLoads,
                    ref packageTempC,
                    ref totalLoad);

                _lastError = null;
                return Cache(new CpuReadResult(
                    CoreTempsC: coreTemps,
                    PackageTempC: packageTempC,
                    CoreLoadsPercent: coreLoads,
                    TotalLoadPercent: totalLoad,
                    Error: null));
            }
            catch (Exception ex)
            {
                _lastError = ex.GetType().Name + ": " + ex.Message;
                return Cache(new CpuReadResult(
                    CoreTempsC: new Dictionary<int, double>(),
                    PackageTempC: null,
                    CoreLoadsPercent: new Dictionary<int, double>(),
                    TotalLoadPercent: null,
                    Error: _lastError));
            }
        }
    }

    private CpuReadResult Cache(CpuReadResult result)
    {
        _lastRead = result;
        _lastReadTick = Environment.TickCount64;
        return result;
    }

    private void EnsureOpenCpu()
    {
        if (_computer is null)
        {
            _computer = new Computer
            {
                IsCpuEnabled = true,
                IsGpuEnabled = false,
                IsMemoryEnabled = false,
                IsMotherboardEnabled = false,
                IsControllerEnabled = false,
                IsNetworkEnabled = false,
                IsStorageEnabled = false,
            };
        }

        if (_cpu is not null)
        {
            return;
        }

        try
        {
            _computer.Open();
        }
        catch
        {
            // If open fails, we'll report it at the call site.
        }

        try
        {
            foreach (var hardware in _computer.Hardware)
            {
                if (hardware.HardwareType == HardwareType.Cpu)
                {
                    _cpu = hardware;
                    break;
                }
            }
        }
        catch
        {
            _cpu = null;
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

    private static bool DetectZeroBasedIndexing(IHardware hardware, SensorType type)
    {
        try
        {
            foreach (var sensor in hardware.Sensors)
            {
                if (sensor.SensorType != type)
                {
                    continue;
                }

                var name = sensor.Name ?? string.Empty;
                if (!LooksLikeCoreSensorName(name))
                {
                    continue;
                }

                var m = CoreIndexRegex.Match(name);
                if (!m.Success)
                {
                    continue;
                }

                if (int.TryParse(m.Groups[1].Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var idx) && idx == 0)
                {
                    return true;
                }
            }
        }
        catch
        {
        }

        return false;
    }

    private static void ReadCpuSensorsRecursive(
        IHardware hardware,
        int expectedCores,
        bool tempZeroBased,
        bool loadZeroBased,
        Dictionary<int, double> coreTempsC,
        Dictionary<int, double> coreLoadsPercent,
        ref double? packageTempC,
        ref double? totalLoadPercent)
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

                if (sensor.SensorType == SensorType.Temperature)
                {
                    var c = Math.Round(sensor.Value.Value, 1);

                    if (packageTempC is null && LooksLikePackageTempSensor(name))
                    {
                        packageTempC = c;
                        continue;
                    }

                    if (TryParseCoreId(name, tempZeroBased, out var coreId) && coreId >= 0 && coreId < expectedCores)
                    {
                        coreTempsC[coreId] = c;
                    }

                    continue;
                }

                if (sensor.SensorType == SensorType.Load)
                {
                    var p = Math.Clamp(Math.Round(sensor.Value.Value, 1), 0d, 100d);

                    // Prefer a stable total sensor when present.
                    if (totalLoadPercent is null &&
                        (string.Equals(name, "CPU Total", StringComparison.OrdinalIgnoreCase) ||
                         (name.IndexOf("Total", StringComparison.OrdinalIgnoreCase) >= 0 && name.IndexOf("Core", StringComparison.OrdinalIgnoreCase) < 0)))
                    {
                        totalLoadPercent = p;
                        continue;
                    }

                    if (TryParseCoreId(name, loadZeroBased, out var coreId) && coreId >= 0 && coreId < expectedCores)
                    {
                        coreLoadsPercent[coreId] = p;
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
                ReadCpuSensorsRecursive(sub, expectedCores, tempZeroBased, loadZeroBased, coreTempsC, coreLoadsPercent, ref packageTempC, ref totalLoadPercent);
            }
        }
        catch
        {
        }
    }

    private static bool LooksLikePackageTempSensor(string name)
    {
        return name.IndexOf("Package", StringComparison.OrdinalIgnoreCase) >= 0 ||
               name.IndexOf("Tctl", StringComparison.OrdinalIgnoreCase) >= 0 ||
               name.IndexOf("Tdie", StringComparison.OrdinalIgnoreCase) >= 0;
    }

    private static bool LooksLikeCoreSensorName(string sensorName)
    {
        if (string.IsNullOrWhiteSpace(sensorName))
        {
            return false;
        }

        if (sensorName.IndexOf("Core", StringComparison.OrdinalIgnoreCase) < 0)
        {
            return false;
        }

        if (sensorName.IndexOf("Effective", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            return false;
        }

        if (sensorName.IndexOf("Distance", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            return false;
        }

        return true;
    }

    private static bool TryParseCoreId(string sensorName, bool zeroBased, out int coreId)
    {
        coreId = 0;
        if (!LooksLikeCoreSensorName(sensorName))
        {
            return false;
        }

        var m = CoreIndexRegex.Match(sensorName);
        if (!m.Success)
        {
            return false;
        }

        if (!int.TryParse(m.Groups[1].Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var n))
        {
            return false;
        }

        var mapped = zeroBased ? n : n - 1;
        if (mapped < 0)
        {
            return false;
        }

        coreId = mapped;
        return true;
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

            _cpu = null;
            _computer = null;
            _lastRead = null;
        }
    }
}

internal sealed record CpuReadResult(
    IReadOnlyDictionary<int, double> CoreTempsC,
    double? PackageTempC,
    IReadOnlyDictionary<int, double> CoreLoadsPercent,
    double? TotalLoadPercent,
    string? Error);

