using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Threading;

namespace DiskInsight;

internal static class ProcessScanner
{
    internal sealed record ProcessInstanceSnapshot(
        int? Pid,
        long? WorkingSetBytes,
        double? CpuUsagePercent,
        TimeSpan? TotalCpuTime,
        DateTime? StartTime);

    internal sealed record ProcessGroupSnapshot(
        string Name,
        int InstanceCount,
        long TotalWorkingSetBytes,
        double? TotalCpuUsagePercent,
        List<ProcessInstanceSnapshot> Instances)
    {
        public string DisplayName => Name == UnknownProcessName ? Name : $"{Name}.exe";
    }

    private sealed record ProcessRow(
        string? Name,
        int? Pid,
        long? WorkingSetBytes,
        double? CpuUsagePercent,
        TimeSpan? TotalCpuTime,
        DateTime? StartTime);

    private const string UnknownProcessName = "<unknown>";

    public static string BuildReport()
    {
        var rows = GetProcessRows()
            .OrderByDescending(r => r.WorkingSetBytes ?? -1)
            .ThenBy(r => r.Name ?? string.Empty, StringComparer.OrdinalIgnoreCase)
            .ThenBy(r => r.Pid ?? int.MaxValue)
            .ToList();

        var report = new StringBuilder(capacity: 32_768);
        report.AppendLine("Running Processes");
        report.AppendLine();
        report.AppendLine($"Count: {rows.Count.ToString(CultureInfo.InvariantCulture)}");
        report.AppendLine();
        report.AppendLine($"  {"WS(MB)",8}  {"CPU Time",12}  {"Start Time",19}  {"PID",7}  Name");

        foreach (var row in rows)
        {
            var wsMb = row.WorkingSetBytes is { } bytes ? $"{bytes / (1024d * 1024d):0.00}" : "n/a";
            var cpu = row.TotalCpuTime is { } cpuTime ? FormatCpuTime(cpuTime) : "n/a";
            var start = row.StartTime is { } startTime
                ? startTime.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture)
                : "n/a";
            var pid = row.Pid?.ToString(CultureInfo.InvariantCulture) ?? "n/a";
            var name = string.IsNullOrWhiteSpace(row.Name) ? "n/a" : row.Name;

            report.AppendLine($"  {wsMb,8}  {cpu,12}  {start,19}  {pid,7}  {name}");
        }

        return report.ToString();
    }

    public static List<ProcessGroupSnapshot> GetGroupedSnapshot()
    {
        var rows = GetProcessRowsWithCpuUsage(sampleInterval: TimeSpan.FromMilliseconds(500)).ToList();

        return rows
            .GroupBy(r => r.Name ?? UnknownProcessName, StringComparer.OrdinalIgnoreCase)
            .Select(group =>
            {
                var instances = group
                    .Select(r => new ProcessInstanceSnapshot(
                        Pid: r.Pid,
                        WorkingSetBytes: r.WorkingSetBytes,
                        CpuUsagePercent: r.CpuUsagePercent,
                        TotalCpuTime: r.TotalCpuTime,
                        StartTime: r.StartTime))
                    .OrderByDescending(i => i.WorkingSetBytes ?? -1)
                    .ThenBy(i => i.Pid ?? int.MaxValue)
                    .ToList();

                var totalBytes = group.Sum(r => r.WorkingSetBytes ?? 0);
                var anyCpu = group.Any(r => r.CpuUsagePercent is not null);
                var totalCpuUsagePercent = anyCpu ? (double?)group.Sum(r => r.CpuUsagePercent ?? 0) : null;
                return new ProcessGroupSnapshot(
                    Name: group.Key,
                    InstanceCount: group.Count(),
                    TotalWorkingSetBytes: totalBytes,
                    TotalCpuUsagePercent: totalCpuUsagePercent,
                    Instances: instances);
            })
            .OrderByDescending(g => g.TotalWorkingSetBytes)
            .ThenBy(g => g.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    public static string FormatWorkingSetMb(long bytes)
        => (bytes / (1024d * 1024d)).ToString("0.00", CultureInfo.InvariantCulture);

    public static string FormatCpuUsagePercentOrNa(double? cpuUsagePercent)
        => cpuUsagePercent is { } cpu ? cpu.ToString("0.0", CultureInfo.InvariantCulture) : "n/a";

    public static string FormatCpuTimeOrNa(TimeSpan? time)
        => time is { } t ? FormatCpuTime(t) : "n/a";

    public static string FormatStartTimeOrNa(DateTime? startTime)
        => startTime is { } t ? t.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture) : "n/a";

    private static IEnumerable<ProcessRow> GetProcessRows()
    {
        Process[] processes;
        try
        {
            processes = Process.GetProcesses();
        }
        catch
        {
            yield break;
        }

        foreach (var process in processes)
        {
            try
            {
                yield return new ProcessRow(
                    Name: TryGetString(() => process.ProcessName),
                    Pid: TryGetInt(() => process.Id),
                    WorkingSetBytes: TryGetLong(() => process.WorkingSet64),
                    CpuUsagePercent: null,
                    TotalCpuTime: TryGetTimeSpan(() => process.TotalProcessorTime),
                    StartTime: TryGetDateTime(() => process.StartTime));
            }
            finally
            {
                process.Dispose();
            }
        }
    }

    private static IEnumerable<ProcessRow> GetProcessRowsWithCpuUsage(TimeSpan sampleInterval)
    {
        if (sampleInterval <= TimeSpan.Zero)
        {
            sampleInterval = TimeSpan.FromMilliseconds(250);
        }

        Process[] processes;
        try
        {
            processes = Process.GetProcesses();
        }
        catch
        {
            yield break;
        }

        var samples = new List<(Process Process, string? Name, int? Pid, TimeSpan? Cpu0)>(processes.Length);
        foreach (var process in processes)
        {
            var name = TryGetString(() => process.ProcessName);
            var pid = TryGetInt(() => process.Id);
            var cpu0 = TryGetTimeSpan(() => process.TotalProcessorTime);
            samples.Add((process, name, pid, cpu0));
        }

        var stopwatch = Stopwatch.StartNew();
        Thread.Sleep(sampleInterval);
        stopwatch.Stop();
        var elapsed = stopwatch.Elapsed;
        if (elapsed <= TimeSpan.Zero)
        {
            elapsed = sampleInterval;
        }

        foreach (var (process, name0, pid0, cpu0) in samples)
        {
            try
            {
                var name = name0 ?? TryGetString(() => process.ProcessName);
                var pid = pid0 ?? TryGetInt(() => process.Id);
                var cpu1 = TryGetTimeSpan(() => process.TotalProcessorTime);
                var workingSet = TryGetLong(() => process.WorkingSet64);
                var startTime = TryGetDateTime(() => process.StartTime);

                yield return new ProcessRow(
                    Name: name,
                    Pid: pid,
                    WorkingSetBytes: workingSet,
                    CpuUsagePercent: ComputeCpuUsagePercent(cpu0, cpu1, elapsed),
                    TotalCpuTime: cpu1,
                    StartTime: startTime);
            }
            finally
            {
                process.Dispose();
            }
        }
    }

    private static double? ComputeCpuUsagePercent(TimeSpan? cpu0, TimeSpan? cpu1, TimeSpan interval)
    {
        if (cpu0 is null || cpu1 is null || interval <= TimeSpan.Zero)
        {
            return null;
        }

        var delta = cpu1.Value - cpu0.Value;
        if (delta < TimeSpan.Zero)
        {
            return null;
        }

        var cpuCount = Environment.ProcessorCount;
        if (cpuCount <= 0)
        {
            return null;
        }

        var percent = delta.TotalMilliseconds / (interval.TotalMilliseconds * cpuCount) * 100d;
        if (double.IsNaN(percent) || double.IsInfinity(percent) || percent < 0)
        {
            return null;
        }

        return Math.Clamp(percent, 0d, 100d);
    }

    private static string FormatCpuTime(TimeSpan time)
    {
        if (time.TotalDays >= 1)
        {
            var days = ((int)time.TotalDays).ToString(CultureInfo.InvariantCulture);
            return $"{days}.{time:hh\\:mm\\:ss}";
        }

        return time.ToString("hh\\:mm\\:ss", CultureInfo.InvariantCulture);
    }

    private static string? TryGetString(Func<string> get)
    {
        try
        {
            return get();
        }
        catch
        {
            return null;
        }
    }

    private static int? TryGetInt(Func<int> get)
    {
        try
        {
            return get();
        }
        catch
        {
            return null;
        }
    }

    private static long? TryGetLong(Func<long> get)
    {
        try
        {
            return get();
        }
        catch
        {
            return null;
        }
    }

    private static TimeSpan? TryGetTimeSpan(Func<TimeSpan> get)
    {
        try
        {
            return get();
        }
        catch
        {
            return null;
        }
    }

    private static DateTime? TryGetDateTime(Func<DateTime> get)
    {
        try
        {
            return get();
        }
        catch
        {
            return null;
        }
    }
}
