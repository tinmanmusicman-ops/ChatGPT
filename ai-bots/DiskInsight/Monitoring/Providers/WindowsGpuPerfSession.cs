using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using System.Management;
using System.Text;
using System.Text.RegularExpressions;
using DiskInsight.Monitoring;

namespace DiskInsight.Monitoring.Providers;

internal sealed class WindowsGpuPerfSession
{
    public static WindowsGpuPerfSession Shared { get; } = new();

    private static readonly Regex LuidRegex = new(
        // Note: GPU Engine instance names look like "pid_1234_luid_0x00000000_0x0001303E_phys_0_eng_0_engtype_3D",
        // so "luid_" is often preceded by "_" (a word char), meaning \b won't match reliably.
        pattern: @"luid_0x([0-9a-fA-F]+)_0x([0-9a-fA-F]+)",
        options: RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);

    private readonly object _gate = new();

    private long _lastReadTick;
    private WindowsGpuPerfReadResult? _lastRead;
    private string? _lastError;
    private long _lastSummaryLogTick;

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

    public WindowsGpuPerfReadResult Read()
    {
        lock (_gate)
        {
            var now = Environment.TickCount64;
            if (_lastRead is not null && (now - _lastReadTick) < 500)
            {
                return _lastRead;
            }

            try
            {
                var controllers = ReadControllers();
                var adapterMemory = ReadAdapterMemoryByLuid();
                var engine = ReadEngineTelemetry();

                var (integratedLuid, discreteLuid, usbOrOtherLuid) = InferPrimaryLuids(adapterMemory);

                var sampler = ProcessCpuUsageSampler.Shared;

                double? integratedLoad = null;
                if (integratedLuid is not null && engine.Max3DByLuid.TryGetValue(integratedLuid, out var il))
                {
                    integratedLoad = il;
                }

                double? discreteLoad = null;
                if (discreteLuid is not null && engine.Max3DByLuid.TryGetValue(discreteLuid, out var dl))
                {
                    discreteLoad = dl;
                }

                double? usbOrOtherLoad = null;
                if (usbOrOtherLuid is not null && engine.Max3DByLuid.TryGetValue(usbOrOtherLuid, out var ul))
                {
                    usbOrOtherLoad = ul;
                }

                var processes = new List<WindowsGpuPerfProcessUsage>(capacity: 16);
                if (integratedLuid is not null)
                {
                    processes.AddRange(BuildTopProcesses(
                        gpuLabel: "Intel",
                        luidKey: integratedLuid,
                        engine: engine,
                        sampler: sampler,
                        topN: 5));
                }

                if (discreteLuid is not null)
                {
                    processes.AddRange(BuildTopProcesses(
                        gpuLabel: "NVIDIA",
                        luidKey: discreteLuid,
                        engine: engine,
                        sampler: sampler,
                        topN: 5));
                }

                // USB proxy: keep simple (no process scan) to avoid stalling the UI loop.
                var usbProxyLoad = usbOrOtherLoad;
                var usbVideoActivityBytesPerSec = 0d;

                // CPU percent (sampled): sum CPU% of processes currently using each adapter's engines.
                double? intelCpu = integratedLuid is not null && engine.ActivePidsByLuid.TryGetValue(integratedLuid, out var ipids)
                    ? sampler.SumCpuPercent(ipids)
                    : null;

                double? discreteCpu = discreteLuid is not null && engine.ActivePidsByLuid.TryGetValue(discreteLuid, out var dpids)
                    ? sampler.SumCpuPercent(dpids)
                    : null;

                double? usbDriverCpu = null;

                var devices = new List<WindowsGpuPerfDevice>(capacity: 3);

                if (controllers.TryGetValue(0x8086, out var intelName))
                {
                    devices.Add(new WindowsGpuPerfDevice(
                        VendorId: 0x8086,
                        VendorName: "Intel",
                        Name: intelName,
                        Load3DPercent: integratedLoad,
                        CpuPercent: intelCpu,
                        Kind: WindowsGpuPerfDeviceKind.Integrated));
                }

                if (controllers.TryGetValue(0x10DE, out var nvidiaName))
                {
                    devices.Add(new WindowsGpuPerfDevice(
                        VendorId: 0x10DE,
                        VendorName: "NVIDIA",
                        Name: nvidiaName,
                        Load3DPercent: discreteLoad,
                        CpuPercent: discreteCpu,
                        Kind: WindowsGpuPerfDeviceKind.Discrete));
                }
                else if (controllers.TryGetValue(0x1002, out var amdName))
                {
                    devices.Add(new WindowsGpuPerfDevice(
                        VendorId: 0x1002,
                        VendorName: "AMD",
                        Name: amdName,
                        Load3DPercent: discreteLoad,
                        CpuPercent: discreteCpu,
                        Kind: WindowsGpuPerfDeviceKind.Discrete));
                }

                var otherController = controllers
                    .Where(kvp => kvp.Key != 0x8086 && kvp.Key != 0x10DE && kvp.Key != 0x1002)
                    .Select(kvp => kvp.Value)
                    .FirstOrDefault(s => !string.IsNullOrWhiteSpace(s));

                if (!string.IsNullOrWhiteSpace(otherController))
                {
                    devices.Add(new WindowsGpuPerfDevice(
                        VendorId: -1,
                        VendorName: "USB/Other",
                        Name: otherController,
                        Load3DPercent: usbOrOtherLoad,
                        CpuPercent: usbDriverCpu,
                        Kind: WindowsGpuPerfDeviceKind.UsbOrOther));
                }

                _lastError = null;
                var result = new WindowsGpuPerfReadResult(
                    Devices: devices.ToArray(),
                    UsbProxyLoadPercent: usbProxyLoad,
                    UsbVideoActivityBytesPerSec: usbVideoActivityBytesPerSec,
                    Processes: processes,
                    Error: null);
                _lastRead = result;
                _lastReadTick = now;

                TryLog(now, result);
                return result;
            }
            catch (Exception ex)
            {
                _lastError = ex.GetType().Name + ": " + ex.Message;
                var result = new WindowsGpuPerfReadResult(
                    Devices: Array.Empty<WindowsGpuPerfDevice>(),
                    UsbProxyLoadPercent: null,
                    UsbVideoActivityBytesPerSec: 0d,
                    Processes: Array.Empty<WindowsGpuPerfProcessUsage>(),
                    Error: _lastError);
                _lastRead = result;
                _lastReadTick = now;
                TryLog(now, result);
                return result;
            }
        }
    }

    private void TryLog(long nowTick, WindowsGpuPerfReadResult read)
    {
        try
        {
            const int summaryEveryMs = 5_000;
            if (nowTick - _lastSummaryLogTick < summaryEveryMs)
            {
                return;
            }

            _lastSummaryLogTick = nowTick;
            var sb = new StringBuilder(256);
            sb.Append("WinPerf GPU summary: ");
            if (!string.IsNullOrWhiteSpace(read.Error))
            {
                sb.Append("error=").Append(read.Error).Append(' ');
            }

            sb.Append("devices=").Append(read.Devices.Count).Append(' ');
            for (var i = 0; i < read.Devices.Count; i++)
            {
                var d = read.Devices[i];
                sb.Append('[').Append(i).Append("] ");
                sb.Append('"').Append(d.Name ?? "n/a").Append('"').Append(' ');
                sb.Append("load=").Append(d.Load3DPercent?.ToString("0.0", CultureInfo.InvariantCulture) ?? "n/a").Append('%');
                if (d.CpuPercent is { } cpu)
                {
                    sb.Append(" cpu=").Append(cpu.ToString("0.0", CultureInfo.InvariantCulture)).Append('%');
                }
                if (i < read.Devices.Count - 1)
                {
                    sb.Append(" | ");
                }
            }

            if (read.UsbProxyLoadPercent is { } proxy)
            {
                sb.Append(" usbProxy=").Append(proxy.ToString("0.0", CultureInfo.InvariantCulture)).Append('%');
            }

            if (read.UsbVideoActivityBytesPerSec > 0d)
            {
                sb.Append(" usbVideoBps=").Append(Math.Round(read.UsbVideoActivityBytesPerSec, 0).ToString("0", CultureInfo.InvariantCulture));
            }

            MonitoringLog.WriteLine(sb.ToString().TrimEnd());
        }
        catch
        {
        }
    }

    private static Dictionary<int, string> ReadControllersByVendor()
    {
        var vendors = new Dictionary<int, string>(capacity: 6);
        try
        {
            using var searcher = new ManagementObjectSearcher(
                scope: new ManagementScope(@"\\.\root\cimv2"),
                query: new ObjectQuery("SELECT Name, PNPDeviceID, AdapterCompatibility FROM Win32_VideoController"));

            foreach (ManagementObject obj in searcher.Get())
            {
                try
                {
                    var name = (obj["Name"] as string)?.Trim();
                    if (string.IsNullOrWhiteSpace(name))
                    {
                        continue;
                    }

                    // Skip common virtual/basic adapters.
                    if (name.IndexOf("Microsoft Basic", StringComparison.OrdinalIgnoreCase) >= 0)
                    {
                        continue;
                    }

                    var pnp = (obj["PNPDeviceID"] as string) ?? string.Empty;
                    var compat = (obj["AdapterCompatibility"] as string) ?? string.Empty;
                    var vendor = TryParseVendorIdFromPnpDeviceId(pnp)
                                 ?? TryParseVendorIdFromText(compat)
                                 ?? TryParseVendorIdFromText(name);
                    if (vendor is null)
                    {
                        vendor = -1;
                    }

                    vendors.TryAdd(vendor.Value, name);
                }
                catch
                {
                }
            }
        }
        catch
        {
        }

        return vendors;
    }

    private static Dictionary<int, string> ReadControllers()
    {
        return ReadControllersByVendor();
    }

    private static Dictionary<string, (ulong Dedicated, ulong Shared)> ReadAdapterMemoryByLuid()
    {
        var mem = new Dictionary<string, (ulong Dedicated, ulong Shared)>(StringComparer.OrdinalIgnoreCase);
        try
        {
            using var searcher = new ManagementObjectSearcher(
                scope: new ManagementScope(@"\\.\root\cimv2"),
                query: new ObjectQuery("SELECT Name, DedicatedUsage, SharedUsage FROM Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory"));

            foreach (ManagementObject obj in searcher.Get())
            {
                try
                {
                    var name = (obj["Name"] as string) ?? string.Empty;
                    if (!TryParseLuidKey(name, out var key))
                    {
                        continue;
                    }

                    var dedicatedRaw = obj["DedicatedUsage"];
                    var sharedRaw = obj["SharedUsage"];

                    var dedicated = dedicatedRaw is null ? 0UL : Convert.ToUInt64(dedicatedRaw, CultureInfo.InvariantCulture);
                    var shared = sharedRaw is null ? 0UL : Convert.ToUInt64(sharedRaw, CultureInfo.InvariantCulture);

                    mem[key] = (Dedicated: dedicated, Shared: shared);
                }
                catch
                {
                }
            }
        }
        catch
        {
        }

        return mem;
    }

    private static (string? IntegratedLuidKey, string? DiscreteLuidKey, string? UsbOrOtherLuidKey) InferPrimaryLuids(
        Dictionary<string, (ulong Dedicated, ulong Shared)> adapterMemory)
    {
        if (adapterMemory.Count == 0)
        {
            return (IntegratedLuidKey: null, DiscreteLuidKey: null, UsbOrOtherLuidKey: null);
        }

        var discrete = adapterMemory
            .OrderByDescending(kvp => kvp.Value.Dedicated)
            .ThenByDescending(kvp => kvp.Value.Shared)
            .First();

        var discreteKey = discrete.Value.Dedicated > 0 ? discrete.Key : null;

        var integrated = adapterMemory
            .Where(kvp => !string.Equals(kvp.Key, discreteKey, StringComparison.OrdinalIgnoreCase))
            .OrderByDescending(kvp => kvp.Value.Shared)
            .ThenBy(kvp => kvp.Value.Dedicated)
            .FirstOrDefault();

        var integratedKey = integrated.Key;
        if (string.IsNullOrWhiteSpace(integratedKey))
        {
            integratedKey = null;
        }

        var usbOrOtherKey = adapterMemory
            .Where(kvp => !string.Equals(kvp.Key, discreteKey, StringComparison.OrdinalIgnoreCase) &&
                          !string.Equals(kvp.Key, integratedKey, StringComparison.OrdinalIgnoreCase))
            .OrderBy(kvp => kvp.Value.Dedicated + kvp.Value.Shared)
            .Select(kvp => kvp.Key)
            .FirstOrDefault();

        if (string.IsNullOrWhiteSpace(usbOrOtherKey))
        {
            usbOrOtherKey = null;
        }

        return (IntegratedLuidKey: integratedKey, DiscreteLuidKey: discreteKey, UsbOrOtherLuidKey: usbOrOtherKey);
    }

    private static EngineTelemetry ReadEngineTelemetry()
    {
        // Heuristic: per adapter, take the max UtilizationPercentage among 3D engines (preferred),
        // and also capture copy/video-processing for the iGPU->USB-display proxy.
        var max3d = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);
        var maxAny = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);
        var maxCopy = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);
        var maxVideoProcessing = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);
        var max3dByPid = new Dictionary<string, Dictionary<int, double>>(StringComparer.OrdinalIgnoreCase);
        var maxCopyByPid = new Dictionary<string, Dictionary<int, double>>(StringComparer.OrdinalIgnoreCase);
        var maxVideoProcessingByPid = new Dictionary<string, Dictionary<int, double>>(StringComparer.OrdinalIgnoreCase);
        var maxAnyByPid = new Dictionary<string, Dictionary<int, double>>(StringComparer.OrdinalIgnoreCase);
        var maxAnyEngTypeByPid = new Dictionary<string, Dictionary<int, string>>(StringComparer.OrdinalIgnoreCase);
        var activePids = new Dictionary<string, HashSet<int>>(StringComparer.OrdinalIgnoreCase);

        try
        {
            using var searcher = new ManagementObjectSearcher(
                scope: new ManagementScope(@"\\.\root\cimv2"),
                query: new ObjectQuery("SELECT Name, UtilizationPercentage FROM Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine"));

            foreach (ManagementObject obj in searcher.Get())
            {
                try
                {
                    var name = (obj["Name"] as string) ?? string.Empty;
                    if (!TryParseLuidKey(name, out var key))
                    {
                        continue;
                    }

                    var raw = obj["UtilizationPercentage"];
                    if (raw is null)
                    {
                        continue;
                    }

                    var p = Convert.ToDouble(raw, CultureInfo.InvariantCulture);
                    p = Math.Clamp(p, 0d, 100d);

                    if (!maxAny.TryGetValue(key, out var existingAny) || p > existingAny)
                    {
                        maxAny[key] = p;
                    }

                    var engType = ExtractEngType(name);
                    var hasPid = TryParsePid(name, out var processId);

                    if (hasPid)
                    {
                        if (!maxAnyByPid.TryGetValue(key, out var anyByPid))
                        {
                            anyByPid = new Dictionary<int, double>();
                            maxAnyByPid[key] = anyByPid;
                        }

                        if (!anyByPid.TryGetValue(processId, out var curAny) || p > curAny)
                        {
                            anyByPid[processId] = p;

                            if (!maxAnyEngTypeByPid.TryGetValue(key, out var anyEngByPid))
                            {
                                anyEngByPid = new Dictionary<int, string>();
                                maxAnyEngTypeByPid[key] = anyEngByPid;
                            }

                            anyEngByPid[processId] = string.IsNullOrWhiteSpace(engType) ? "Unknown" : engType;
                        }
                    }

                    if (string.Equals(engType, "3d", StringComparison.OrdinalIgnoreCase))
                    {
                        if (!max3d.TryGetValue(key, out var existing3d) || p > existing3d)
                        {
                            max3d[key] = p;
                        }

                        if (hasPid)
                        {
                            if (!max3dByPid.TryGetValue(key, out var byPid))
                            {
                                byPid = new Dictionary<int, double>();
                                max3dByPid[key] = byPid;
                            }

                            if (!byPid.TryGetValue(processId, out var cur) || p > cur)
                            {
                                byPid[processId] = p;
                            }
                        }
                    }

                    if (string.Equals(engType, "copy", StringComparison.OrdinalIgnoreCase))
                    {
                        if (!maxCopy.TryGetValue(key, out var existingCopy) || p > existingCopy)
                        {
                            maxCopy[key] = p;
                        }

                        if (hasPid)
                        {
                            if (!maxCopyByPid.TryGetValue(key, out var byPid))
                            {
                                byPid = new Dictionary<int, double>();
                                maxCopyByPid[key] = byPid;
                            }

                            if (!byPid.TryGetValue(processId, out var cur) || p > cur)
                            {
                                byPid[processId] = p;
                            }
                        }
                    }

                    if (string.Equals(engType, "videoprocessing", StringComparison.OrdinalIgnoreCase))
                    {
                        if (!maxVideoProcessing.TryGetValue(key, out var existingVp) || p > existingVp)
                        {
                            maxVideoProcessing[key] = p;
                        }

                        if (hasPid)
                        {
                            if (!maxVideoProcessingByPid.TryGetValue(key, out var byPid))
                            {
                                byPid = new Dictionary<int, double>();
                                maxVideoProcessingByPid[key] = byPid;
                            }

                            if (!byPid.TryGetValue(processId, out var cur) || p > cur)
                            {
                                byPid[processId] = p;
                            }
                        }
                    }

                    // Consider the PID "active" for CPU attribution if it shows any engine activity.
                    if (p > 0.1 && hasPid)
                    {
                        if (!activePids.TryGetValue(key, out var set))
                        {
                            set = new HashSet<int>();
                            activePids[key] = set;
                        }

                        set.Add(processId);
                    }
                }
                catch
                {
                }
            }
        }
        catch
        {
        }

        // Prefer 3D when present; otherwise fall back to maxAny for that adapter.
        var max3dOrAny = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);
        foreach (var kvp in maxAny)
        {
            max3dOrAny[kvp.Key] = kvp.Value;
        }

        foreach (var kvp in max3d)
        {
            max3dOrAny[kvp.Key] = kvp.Value;
        }

        return new EngineTelemetry(
            Max3DByLuid: max3dOrAny,
            MaxCopyByLuid: maxCopy,
            MaxVideoProcessingByLuid: maxVideoProcessing,
            Max3DByLuidPid: max3dByPid,
            MaxCopyByLuidPid: maxCopyByPid,
            MaxVideoProcessingByLuidPid: maxVideoProcessingByPid,
            MaxAnyByLuidPid: maxAnyByPid,
            MaxAnyEngTypeByLuidPid: maxAnyEngTypeByPid,
            ActivePidsByLuid: activePids);
    }

    private static IReadOnlyList<WindowsGpuPerfProcessUsage> BuildTopProcesses(
        string gpuLabel,
        string luidKey,
        EngineTelemetry engine,
        ProcessCpuUsageSampler sampler,
        int topN)
    {
        if (topN <= 0)
        {
            return Array.Empty<WindowsGpuPerfProcessUsage>();
        }

        if (!engine.MaxAnyByLuidPid.TryGetValue(luidKey, out var byPid) || byPid.Count == 0)
        {
            return Array.Empty<WindowsGpuPerfProcessUsage>();
        }

        engine.MaxAnyEngTypeByLuidPid.TryGetValue(luidKey, out var engByPid);

        var top = byPid
            .Where(kvp => kvp.Value > 0.1)
            .OrderByDescending(kvp => kvp.Value)
            .Take(topN)
            .Select(kvp =>
            {
                var pid = kvp.Key;
                var gpu = Math.Clamp(kvp.Value, 0d, 100d);
                var eng = engByPid is not null && engByPid.TryGetValue(pid, out var e) && !string.IsNullOrWhiteSpace(e) ? e : "Unknown";
                var name = TryGetProcessName(pid);
                var cpu = sampler.SampleCpuPercent(pid);
                return new WindowsGpuPerfProcessUsage(
                    GpuLabel: gpuLabel,
                    ProcessId: pid,
                    ProcessName: name,
                    EngineType: eng,
                    GpuPercent: gpu,
                    CpuPercent: cpu);
            })
            .ToList();

        return top;
    }

    private static string? TryGetProcessName(int processId)
    {
        if (processId <= 0)
        {
            return null;
        }

        try
        {
            using var p = Process.GetProcessById(processId);
            var name = (p.ProcessName ?? "").Trim();
            if (string.IsNullOrWhiteSpace(name))
            {
                return null;
            }

            if (!name.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
            {
                name += ".exe";
            }

            return name;
        }
        catch
        {
            return null;
        }
    }

    private static bool TryParsePid(string name, out int pid)
    {
        pid = 0;
        try
        {
            // Example: pid_12056_luid_0x00000000_0x0001303E_phys_0_eng_0_engtype_3D
            if (!name.StartsWith("pid_", StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }

            var underscore = name.IndexOf('_', startIndex: 4);
            if (underscore < 0)
            {
                return false;
            }

            var span = name.Substring(4, underscore - 4);
            return int.TryParse(span, NumberStyles.Integer, CultureInfo.InvariantCulture, out pid) && pid > 0;
        }
        catch
        {
            return false;
        }
    }

    private static string ExtractEngType(string name)
    {
        try
        {
            // Example: "..._engtype_3D" or "..._engtype_VideoProcessing"
            var idx = name.LastIndexOf("engtype_", StringComparison.OrdinalIgnoreCase);
            if (idx < 0)
            {
                return string.Empty;
            }

            return name.Substring(idx + "engtype_".Length);
        }
        catch
        {
            return string.Empty;
        }
    }

    private static bool TryParseLuidKey(string text, out string key)
    {
        key = string.Empty;
        if (string.IsNullOrWhiteSpace(text))
        {
            return false;
        }

        var m = LuidRegex.Match(text);
        if (!m.Success)
        {
            return false;
        }

        if (!uint.TryParse(m.Groups[1].Value, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var high) ||
            !uint.TryParse(m.Groups[2].Value, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var low))
        {
            return false;
        }

        key = $"{high:x8}-{low:x8}";
        return true;
    }

    private static int? TryParseVendorIdFromPnpDeviceId(string pnp)
    {
        try
        {
            var idx = pnp.IndexOf("VEN_", StringComparison.OrdinalIgnoreCase);
            if (idx < 0 || idx + 8 > pnp.Length)
            {
                return null;
            }

            var hex = pnp.Substring(idx + 4, 4);
            return int.TryParse(hex, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var id) ? id : null;
        }
        catch
        {
            return null;
        }
    }

    private static int? TryParseVendorIdFromText(string text)
    {
        if (text.IndexOf("Intel", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            return 0x8086;
        }

        if (text.IndexOf("NVIDIA", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            return 0x10DE;
        }

        if (text.IndexOf("AMD", StringComparison.OrdinalIgnoreCase) >= 0 ||
            text.IndexOf("Radeon", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            return 0x1002;
        }

        return null;
    }
}

internal sealed record WindowsGpuPerfReadResult(
    IReadOnlyList<WindowsGpuPerfDevice> Devices,
    double? UsbProxyLoadPercent,
    double UsbVideoActivityBytesPerSec,
    IReadOnlyList<WindowsGpuPerfProcessUsage> Processes,
    string? Error);

internal sealed record WindowsGpuPerfProcessUsage(
    string GpuLabel,
    int ProcessId,
    string? ProcessName,
    string EngineType,
    double GpuPercent,
    double? CpuPercent);

internal sealed record WindowsGpuPerfDevice(
    int VendorId,
    string VendorName,
    string? Name,
    double? Load3DPercent,
    double? CpuPercent,
    WindowsGpuPerfDeviceKind Kind);

internal enum WindowsGpuPerfDeviceKind
{
    Integrated = 0,
    Discrete = 1,
    UsbOrOther = 2,
}

internal sealed record EngineTelemetry(
    IReadOnlyDictionary<string, double> Max3DByLuid,
    IReadOnlyDictionary<string, double> MaxCopyByLuid,
    IReadOnlyDictionary<string, double> MaxVideoProcessingByLuid,
    IReadOnlyDictionary<string, Dictionary<int, double>> Max3DByLuidPid,
    IReadOnlyDictionary<string, Dictionary<int, double>> MaxCopyByLuidPid,
    IReadOnlyDictionary<string, Dictionary<int, double>> MaxVideoProcessingByLuidPid,
    IReadOnlyDictionary<string, Dictionary<int, double>> MaxAnyByLuidPid,
    IReadOnlyDictionary<string, Dictionary<int, string>> MaxAnyEngTypeByLuidPid,
    IReadOnlyDictionary<string, HashSet<int>> ActivePidsByLuid);
