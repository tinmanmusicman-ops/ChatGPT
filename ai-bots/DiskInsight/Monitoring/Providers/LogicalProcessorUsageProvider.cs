using System;
using System.Runtime.InteropServices;

namespace DiskInsight.Monitoring.Providers;

internal sealed class LogicalProcessorUsageProvider
{
    private SystemProcessorPerfInfo[]? _last;

    public double?[] ReadUsagePercentPerLogicalProcessor()
    {
        var current = ReadCurrent();
        if (current.Length == 0)
        {
            return Array.Empty<double?>();
        }

        var result = new double?[current.Length];
        if (_last is null || _last.Length != current.Length)
        {
            _last = current;
            return result;
        }

        for (var i = 0; i < current.Length; i++)
        {
            var prev = _last[i];
            var cur = current[i];

            var idle = cur.IdleTime - prev.IdleTime;
            var kernel = cur.KernelTime - prev.KernelTime;
            var user = cur.UserTime - prev.UserTime;

            var total = kernel + user;
            if (total <= 0)
            {
                continue;
            }

            // KernelTime includes IdleTime.
            var busy = total - idle;
            if (busy < 0)
            {
                busy = 0;
            }

            var pct = (busy * 100d) / total;
            if (double.IsNaN(pct) || double.IsInfinity(pct))
            {
                continue;
            }

            result[i] = Math.Clamp(Math.Round(pct, 1), 0d, 100d);
        }

        _last = current;
        return result;
    }

    private static SystemProcessorPerfInfo[] ReadCurrent()
    {
        var count = Math.Clamp(Environment.ProcessorCount, 1, 256);
        var size = Marshal.SizeOf<SystemProcessorPerfInfo>();
        var bufferSize = size * count;

        var buffer = IntPtr.Zero;
        try
        {
            buffer = Marshal.AllocHGlobal(bufferSize);
            var status = NtQuerySystemInformation(
                systemInformationClass: 8, // SystemProcessorPerformanceInformation
                systemInformation: buffer,
                systemInformationLength: bufferSize,
                returnLength: out _);

            if (status != 0)
            {
                return Array.Empty<SystemProcessorPerfInfo>();
            }

            var infos = new SystemProcessorPerfInfo[count];
            for (var i = 0; i < count; i++)
            {
                infos[i] = Marshal.PtrToStructure<SystemProcessorPerfInfo>(buffer + (i * size));
            }
            return infos;
        }
        catch
        {
            return Array.Empty<SystemProcessorPerfInfo>();
        }
        finally
        {
            if (buffer != IntPtr.Zero)
            {
                try
                {
                    Marshal.FreeHGlobal(buffer);
                }
                catch
                {
                }
            }
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private readonly struct SystemProcessorPerfInfo
    {
        public readonly long IdleTime;
        public readonly long KernelTime;
        public readonly long UserTime;
        public readonly long DpcTime;
        public readonly long InterruptTime;
        public readonly uint InterruptCount;
    }

    [DllImport("ntdll.dll")]
    private static extern int NtQuerySystemInformation(
        int systemInformationClass,
        IntPtr systemInformation,
        int systemInformationLength,
        out int returnLength);
}

