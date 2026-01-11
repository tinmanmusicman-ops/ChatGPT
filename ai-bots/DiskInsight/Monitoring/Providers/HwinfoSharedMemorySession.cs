using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using DiskInsight.Monitoring;
using Hwinfo.SharedMemory;

namespace DiskInsight.Monitoring.Providers;

internal sealed class HwinfoSharedMemorySession : IDisposable
{
    public static HwinfoSharedMemorySession Shared { get; } = new();

    private readonly object _gate = new();
    private SharedMemoryReader? _reader;

    private long _lastReadTick;
    private HwinfoReadResult? _lastRead;
    private string? _lastError;
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

    public HwinfoReadResult ReadLocal()
    {
        lock (_gate)
        {
            var now = Environment.TickCount64;
            if (_lastRead is not null && (now - _lastReadTick) < 750)
            {
                return _lastRead;
            }

            try
            {
                _reader ??= new SharedMemoryReader(mutexTimeout: 50);
                var readings = _reader.ReadLocal();
                var list = readings?.ToList() ?? new List<SensorReading>();

                TryLogRaw(now, list);

                _lastError = null;
                return Cache(new HwinfoReadResult(Sensors: list, Error: null));
            }
            catch (FileNotFoundException)
            {
                _lastError = "HWiNFO shared memory not found (is HWiNFO running with Shared Memory enabled?).";
                return Cache(new HwinfoReadResult(Sensors: Array.Empty<SensorReading>(), Error: _lastError));
            }
            catch (UnauthorizedAccessException)
            {
                _lastError = "Access denied reading HWiNFO shared memory.";
                return Cache(new HwinfoReadResult(Sensors: Array.Empty<SensorReading>(), Error: _lastError));
            }
            catch (InvalidDataException ex)
            {
                _lastError = "Invalid HWiNFO shared memory data: " + ex.Message;
                return Cache(new HwinfoReadResult(Sensors: Array.Empty<SensorReading>(), Error: _lastError));
            }
            catch (Exception ex)
            {
                _lastError = ex.GetType().Name + ": " + ex.Message;
                return Cache(new HwinfoReadResult(Sensors: Array.Empty<SensorReading>(), Error: _lastError));
            }
        }
    }

    private void TryLogRaw(long nowTick, IReadOnlyList<SensorReading> sensors)
    {
        try
        {
            if (string.Equals(Environment.GetEnvironmentVariable("DISKINSIGHT_HWINFO_RAW"), "0", StringComparison.OrdinalIgnoreCase))
            {
                return;
            }

            const int rawEveryMs = 10_000;
            if (nowTick - _lastRawLogTick < rawEveryMs)
            {
                return;
            }

            _lastRawLogTick = nowTick;
            MonitoringLog.WriteLine($"HWiNFO raw: sensors={sensors.Count}");

            foreach (var s in sensors.Take(250))
            {
                var group = (s.GroupLabelUser ?? s.GroupLabelOrig) ?? string.Empty;
                var label = (s.LabelUser ?? s.LabelOrig) ?? string.Empty;
                var unit = s.Unit ?? string.Empty;
                MonitoringLog.WriteLine($"HWiNFO raw: type={s.Type} group=\"{group}\" label=\"{label}\" value={s.Value:0.###} unit=\"{unit}\"");
            }
        }
        catch
        {
        }
    }

    private HwinfoReadResult Cache(HwinfoReadResult result)
    {
        _lastRead = result;
        _lastReadTick = Environment.TickCount64;
        return result;
    }

    public void Dispose()
    {
        lock (_gate)
        {
            try
            {
                _reader?.Dispose();
            }
            catch
            {
            }

            _reader = null;
            _lastRead = null;
        }
    }

    public void Reset()
    {
        lock (_gate)
        {
            try
            {
                _reader?.Dispose();
            }
            catch
            {
            }

            _reader = null;
            _lastRead = null;
            _lastReadTick = 0;
            _lastError = null;
            _lastRawLogTick = 0;
        }
    }
}

internal sealed record HwinfoReadResult(
    IReadOnlyList<SensorReading> Sensors,
    string? Error);
