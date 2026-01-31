using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;

namespace DiskInsight.Monitoring.Providers;

internal sealed class ProcessCpuUsageSampler
{
    public static ProcessCpuUsageSampler Shared { get; } = new();

    private readonly object _gate = new();
    private readonly Dictionary<int, SampleState> _stateByPid = new();

    public double? SampleTotalCpuPercentAllProcesses()
    {
        var nowTick = Environment.TickCount64;

        Process[] processes;
        try
        {
            processes = Process.GetProcesses();
        }
        catch
        {
            return null;
        }

        var cpuCount = Math.Max(1, Environment.ProcessorCount);
        var samples = new List<(int Pid, TimeSpan TotalCpu)>(capacity: processes.Length);
        var seenPids = new HashSet<int>();

        foreach (var p in processes)
        {
            try
            {
                int pid;
                TimeSpan totalCpu;
                try
                {
                    pid = p.Id;
                    totalCpu = p.TotalProcessorTime;
                }
                catch
                {
                    // If we can't read the PID or CPU time, we can't sample it.
                    continue;
                }

                if (pid <= 0)
                {
                    continue;
                }

                seenPids.Add(pid);
                samples.Add((pid, totalCpu));
            }
            finally
            {
                p.Dispose();
            }
        }

        lock (_gate)
        {
            double sum = 0;
            var any = false;

            for (var i = 0; i < samples.Count; i++)
            {
                var (pid, totalCpu) = samples[i];

                if (!_stateByPid.TryGetValue(pid, out var state))
                {
                    _stateByPid[pid] = new SampleState(totalCpu, nowTick);
                    continue;
                }

                var elapsedMs = nowTick - state.LastTick;
                if (elapsedMs <= 0)
                {
                    _stateByPid[pid] = new SampleState(totalCpu, nowTick);
                    continue;
                }

                var deltaCpuMs = (totalCpu - state.LastTotalCpu).TotalMilliseconds;
                _stateByPid[pid] = new SampleState(totalCpu, nowTick);

                if (deltaCpuMs < 0)
                {
                    continue;
                }

                var denom = elapsedMs * cpuCount;
                var cpuPercent = (deltaCpuMs / denom) * 100d;
                if (double.IsNaN(cpuPercent) || double.IsInfinity(cpuPercent) || cpuPercent < 0)
                {
                    continue;
                }

                any = true;
                sum += Math.Clamp(cpuPercent, 0d, 100d);
            }

            if (_stateByPid.Count > 0 && seenPids.Count > 0)
            {
                // Prevent unbounded growth from short-lived processes.
                var toRemove = _stateByPid.Keys.Where(pid => !seenPids.Contains(pid)).ToArray();
                for (var i = 0; i < toRemove.Length; i++)
                {
                    _stateByPid.Remove(toRemove[i]);
                }
            }

            if (!any)
            {
                return null;
            }

            return Math.Clamp(sum, 0d, 100d);
        }
    }

    public double? SumCpuPercent(IEnumerable<int> processIds)
    {
        if (processIds is null)
        {
            return null;
        }

        var ids = processIds.Distinct().ToArray();
        if (ids.Length == 0)
        {
            return null;
        }

        double sum = 0;
        var any = false;
        for (var i = 0; i < ids.Length; i++)
        {
            var p = SampleCpuPercent(ids[i]);
            if (p is null)
            {
                continue;
            }

            any = true;
            sum += p.Value;
        }

        if (!any)
        {
            return null;
        }

        return Math.Clamp(sum, 0d, 100d);
    }

    public double? SampleCpuPercent(int processId)
    {
        if (processId <= 0)
        {
            return null;
        }

        var nowTick = Environment.TickCount64;
        TimeSpan totalCpu;

        try
        {
            using var p = Process.GetProcessById(processId);
            totalCpu = p.TotalProcessorTime;
        }
        catch
        {
            lock (_gate)
            {
                _stateByPid.Remove(processId);
            }
            return null;
        }

        lock (_gate)
        {
            if (!_stateByPid.TryGetValue(processId, out var state))
            {
                _stateByPid[processId] = new SampleState(totalCpu, nowTick);
                return null;
            }

            var elapsedMs = nowTick - state.LastTick;
            if (elapsedMs <= 0)
            {
                _stateByPid[processId] = new SampleState(totalCpu, nowTick);
                return null;
            }

            var deltaCpuMs = (totalCpu - state.LastTotalCpu).TotalMilliseconds;
            _stateByPid[processId] = new SampleState(totalCpu, nowTick);

            if (deltaCpuMs < 0)
            {
                return null;
            }

            var denom = elapsedMs * Math.Max(1, Environment.ProcessorCount);
            var cpuPercent = (deltaCpuMs / denom) * 100d;
            if (double.IsNaN(cpuPercent) || double.IsInfinity(cpuPercent))
            {
                return null;
            }

            return Math.Clamp(cpuPercent, 0d, 100d);
        }
    }

    public void Reset()
    {
        lock (_gate)
        {
            _stateByPid.Clear();
        }
    }

    private sealed record SampleState(TimeSpan LastTotalCpu, long LastTick);
}
