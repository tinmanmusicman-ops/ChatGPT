using System;
using System.Linq;
using System.Net.NetworkInformation;

namespace DiskInsight.Monitoring.Providers;

internal sealed class NetworkUsageProvider
{
    private string? _selectedId;
    private long _lastTotalBytes;
    private DateTimeOffset _lastTimestamp;

    public NetworkUsageSnapshot Read()
    {
        try
        {
            var ni = SelectNetworkInterface();
            if (ni is null)
            {
                return new NetworkUsageSnapshot(DateTimeOffset.UtcNow, null, 0, null, "No active network interface found.");
            }

            var speedBits = ni.Speed;
            if (speedBits <= 0)
            {
                return new NetworkUsageSnapshot(DateTimeOffset.UtcNow, ni.Name, 0, null, "Interface speed unavailable.");
            }

            var stats = ni.GetIPv4Statistics();
            var totalBytes = (long)stats.BytesReceived + (long)stats.BytesSent;
            var now = DateTimeOffset.UtcNow;

            double? usedMbps = null;
            if (_selectedId == ni.Id && _lastTotalBytes > 0)
            {
                var deltaBytes = totalBytes - _lastTotalBytes;
                var deltaSec = (now - _lastTimestamp).TotalSeconds;
                if (deltaBytes >= 0 && deltaSec > 0.25)
                {
                    var bitsPerSec = (deltaBytes * 8d) / deltaSec;
                    usedMbps = bitsPerSec / 1_000_000d;
                    if (double.IsNaN(usedMbps.Value) || double.IsInfinity(usedMbps.Value) || usedMbps.Value < 0)
                    {
                        usedMbps = null;
                    }
                }
            }

            _selectedId = ni.Id;
            _lastTotalBytes = totalBytes;
            _lastTimestamp = now;

            var totalMbps = speedBits / 1_000_000d;
            return new NetworkUsageSnapshot(now, ni.Name, totalMbps, usedMbps, null);
        }
        catch (Exception ex)
        {
            return new NetworkUsageSnapshot(DateTimeOffset.UtcNow, null, 0, null, ex.GetType().Name + ": " + ex.Message);
        }
    }

    private NetworkInterface? SelectNetworkInterface()
    {
        try
        {
            var all = NetworkInterface.GetAllNetworkInterfaces();
            var candidates = all
                .Where(n =>
                    n.OperationalStatus == OperationalStatus.Up &&
                    n.NetworkInterfaceType is not NetworkInterfaceType.Loopback and not NetworkInterfaceType.Tunnel &&
                    n.Speed > 0)
                .ToList();

            if (_selectedId is not null)
            {
                var existing = candidates.FirstOrDefault(n => string.Equals(n.Id, _selectedId, StringComparison.OrdinalIgnoreCase));
                if (existing is not null)
                {
                    return existing;
                }
            }

            return candidates
                .OrderByDescending(n => n.Speed)
                .FirstOrDefault();
        }
        catch
        {
            return null;
        }
    }
}

internal sealed record NetworkUsageSnapshot(
    DateTimeOffset TimestampUtc,
    string? InterfaceName,
    double TotalMbps,
    double? UsedMbpsPerSecond,
    string? Error);

