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
