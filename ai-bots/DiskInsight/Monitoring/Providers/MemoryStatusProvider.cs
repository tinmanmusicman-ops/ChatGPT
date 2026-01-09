using System;
using System.Globalization;
using System.Management;
using System.Runtime.InteropServices;

namespace DiskInsight.Monitoring.Providers;

internal sealed class MemoryStatusProvider
{
    public MemoryStatusSnapshot Read()
    {
        try
        {
            if (!TryReadGlobalMemoryStatus(out var totalBytes, out var availBytes))
            {
                return new MemoryStatusSnapshot(
                    TimestampUtc: DateTimeOffset.UtcNow,
                    TotalBytes: 0,
                    UsedBytes: 0,
                    ModifiedBytes: 0,
                    FreeBytes: 0,
                    Error: "GlobalMemoryStatusEx failed.");
            }

            var modifiedBytes = ReadModifiedPageListBytesOrZero();

            // Task Manager model:
            // - Available = Standby + Free (we treat as "Free" for the bar)
            // - Total - Available = InUse + Modified
            // So: Used = Total - Available - Modified
            var inUsePlusModified = totalBytes > availBytes ? (totalBytes - availBytes) : 0UL;
            if (modifiedBytes > inUsePlusModified)
            {
                modifiedBytes = inUsePlusModified;
            }

            var usedBytes = inUsePlusModified - modifiedBytes;
            var freeBytes = availBytes;

            return new MemoryStatusSnapshot(
                TimestampUtc: DateTimeOffset.UtcNow,
                TotalBytes: totalBytes,
                UsedBytes: usedBytes,
                ModifiedBytes: modifiedBytes,
                FreeBytes: freeBytes,
                Error: null);
        }
        catch (Exception ex)
        {
            return new MemoryStatusSnapshot(
                TimestampUtc: DateTimeOffset.UtcNow,
                TotalBytes: 0,
                UsedBytes: 0,
                ModifiedBytes: 0,
                FreeBytes: 0,
                Error: ex.GetType().Name + ": " + ex.Message);
        }
    }

    private static ulong ReadModifiedPageListBytesOrZero()
    {
        try
        {
            using var searcher = new ManagementObjectSearcher(
                scope: new ManagementScope(@"\\.\root\cimv2"),
                query: new ObjectQuery("SELECT ModifiedPageListBytes FROM Win32_PerfRawData_PerfOS_Memory"));

            foreach (ManagementObject obj in searcher.Get())
            {
                try
                {
                    var raw = obj["ModifiedPageListBytes"];
                    if (raw is null)
                    {
                        continue;
                    }

                    var v = Convert.ToDouble(raw, CultureInfo.InvariantCulture);
                    if (double.IsNaN(v) || double.IsInfinity(v) || v < 0)
                    {
                        continue;
                    }

                    return (ulong)Math.Round(v);
                }
                catch
                {
                }
            }
        }
        catch
        {
        }

        return 0;
    }

    private static bool TryReadGlobalMemoryStatus(out ulong totalBytes, out ulong availBytes)
    {
        totalBytes = 0;
        availBytes = 0;

        try
        {
            var s = new MEMORYSTATUSEX();
            s.dwLength = (uint)Marshal.SizeOf<MEMORYSTATUSEX>();
            if (!GlobalMemoryStatusEx(ref s))
            {
                return false;
            }

            totalBytes = s.ullTotalPhys;
            availBytes = s.ullAvailPhys;
            return totalBytes > 0;
        }
        catch
        {
            return false;
        }
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Auto)]
    private struct MEMORYSTATUSEX
    {
        public uint dwLength;
        public uint dwMemoryLoad;
        public ulong ullTotalPhys;
        public ulong ullAvailPhys;
        public ulong ullTotalPageFile;
        public ulong ullAvailPageFile;
        public ulong ullTotalVirtual;
        public ulong ullAvailVirtual;
        public ulong ullAvailExtendedVirtual;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    private static extern bool GlobalMemoryStatusEx(ref MEMORYSTATUSEX lpBuffer);
}

internal sealed record MemoryStatusSnapshot(
    DateTimeOffset TimestampUtc,
    ulong TotalBytes,
    ulong UsedBytes,
    ulong ModifiedBytes,
    ulong FreeBytes,
    string? Error);

