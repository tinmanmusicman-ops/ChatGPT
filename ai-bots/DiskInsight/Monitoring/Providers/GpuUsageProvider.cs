using System;
using System.Collections.Generic;
using System.Linq;

namespace DiskInsight.Monitoring.Providers;

public sealed class GpuUsageProvider
{
    private string? _lastError;
    public string? LastError => _lastError;
    private readonly HwinfoGpuTemperatureProvider _hwinfoIntelTemp = new();

    public GpuSnapshot Read()
    {
        _lastError = null;
        try
        {
            // Use Windows GPU performance counters for load (no kernel driver required).
            var win = WindowsGpuPerfSession.Shared.Read();

            // Use LibreHardwareMonitor when available for temperatures (and as a secondary source for names).
            var lhm = LibreHardwareGpuSession.Shared.ReadAll();
            _lastError = lhm.Error ?? LibreHardwareGpuSession.Shared.LastError ?? win.Error ?? WindowsGpuPerfSession.Shared.LastError;

            var intel = Merge(
                fromLhm: Pick(lhm, prefer: LibreHardwareMonitor.Hardware.HardwareType.GpuIntel, nameHint: "intel"),
                fromWin: PickWin(win, vendorId: 0x8086),
                preferWindowsLoad: true);

            var nvidia = Merge(
                fromLhm: Pick(lhm, prefer: LibreHardwareMonitor.Hardware.HardwareType.GpuNvidia, nameHint: "nvidia"),
                fromWin: PickWin(win, vendorId: 0x10DE),
                preferWindowsLoad: true);

            var usb = BuildUsbSnapshot(win);

            var intelTempC = _hwinfoIntelTemp.ReadIntelGpuTempC();
            if (intelTempC is not null && intel is not null)
            {
                intel = intel with { CoreTempC = intelTempC };
            }

            return new GpuSnapshot(
                Intel: intel,
                Nvidia: nvidia,
                Usb: usb,
                Processes: win.Processes
                    .Select(p => new GpuProcessSnapshot(
                        GpuLabel: p.GpuLabel,
                        ProcessId: p.ProcessId,
                        ProcessName: p.ProcessName,
                        EngineType: p.EngineType,
                        GpuPercent: p.GpuPercent,
                        CpuPercent: p.CpuPercent))
                    .ToArray(),
                Error: _lastError);
        }
        catch (Exception ex)
        {
            _lastError = ex.GetType().Name + ": " + ex.Message;
            return new GpuSnapshot(
                Intel: null,
                Nvidia: null,
                Usb: null,
                Processes: Array.Empty<GpuProcessSnapshot>(),
                Error: _lastError);
        }
    }

    private static GpuDeviceSnapshot? Pick(GpuReadResult read, LibreHardwareMonitor.Hardware.HardwareType prefer, string nameHint)
    {
        var candidates = read.Devices;
        if (candidates is null || candidates.Count == 0)
        {
            return null;
        }

        var match = candidates.FirstOrDefault(d => d.HardwareType == prefer)
                    ?? candidates.FirstOrDefault(d => (d.Name ?? "").IndexOf(nameHint, StringComparison.OrdinalIgnoreCase) >= 0);
        if (match is null)
        {
            return null;
        }

        var load = match.CoreLoadPercent is { } p ? Math.Clamp(Math.Round(p, 1), 0d, 100d) : (double?)null;
        var tempC = match.CoreTempC is { } t ? Math.Round(t, 1) : (double?)null;
        return new GpuDeviceSnapshot(Name: match.Name, CoreLoadPercent: load, CoreTempC: tempC, CpuPercent: null, IoBytesPerSec: null);
    }

    private static GpuDeviceSnapshot? PickWin(WindowsGpuPerfReadResult read, int vendorId)
    {
        var candidates = read.Devices;
        if (candidates is null || candidates.Count == 0)
        {
            return null;
        }

        var match = candidates.FirstOrDefault(d => d.VendorId == vendorId);
        if (match is null)
        {
            return null;
        }

        var load = match.Load3DPercent is { } p ? Math.Clamp(Math.Round(p, 1), 0d, 100d) : (double?)null;
        var cpu = match.CpuPercent is { } c ? Math.Clamp(Math.Round(c, 1), 0d, 100d) : (double?)null;
        return new GpuDeviceSnapshot(Name: match.Name, CoreLoadPercent: load, CoreTempC: null, CpuPercent: cpu, IoBytesPerSec: null);
    }

    private static GpuDeviceSnapshot? Merge(GpuDeviceSnapshot? fromLhm, GpuDeviceSnapshot? fromWin, bool preferWindowsLoad)
    {
        if (fromLhm is null)
        {
            return fromWin;
        }

        if (fromWin is null)
        {
            return fromLhm;
        }

        var load = preferWindowsLoad ? (fromWin.CoreLoadPercent ?? fromLhm.CoreLoadPercent) : (fromLhm.CoreLoadPercent ?? fromWin.CoreLoadPercent);
        return new GpuDeviceSnapshot(
            Name: fromLhm.Name ?? fromWin.Name,
            CoreLoadPercent: load,
            CoreTempC: fromLhm.CoreTempC ?? fromWin.CoreTempC,
            CpuPercent: fromWin.CpuPercent ?? fromLhm.CpuPercent,
            IoBytesPerSec: fromWin.IoBytesPerSec ?? fromLhm.IoBytesPerSec);
    }

    private static GpuDeviceSnapshot BuildUsbSnapshot(WindowsGpuPerfReadResult win)
    {
        var usbLoad = win.UsbProxyLoadPercent is { } p ? Math.Clamp(Math.Round(p, 1), 0d, 100d) : 0d;
        var usbIo = Math.Max(0d, win.UsbVideoActivityBytesPerSec);
        return new GpuDeviceSnapshot(
            Name: "USB",
            CoreLoadPercent: usbLoad,
            CoreTempC: null,
            CpuPercent: 0d,
            IoBytesPerSec: usbIo);
    }
}

public sealed record GpuSnapshot(
    GpuDeviceSnapshot? Intel,
    GpuDeviceSnapshot? Nvidia,
    GpuDeviceSnapshot? Usb,
    IReadOnlyList<GpuProcessSnapshot> Processes,
    string? Error);

public sealed record GpuProcessSnapshot(
    string GpuLabel,
    int ProcessId,
    string? ProcessName,
    string EngineType,
    double GpuPercent,
    double? CpuPercent);

public sealed record GpuDeviceSnapshot(
    string? Name,
    double? CoreLoadPercent,
    double? CoreTempC,
    double? CpuPercent,
    double? IoBytesPerSec);
