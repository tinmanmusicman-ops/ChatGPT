using System;
using System.IO;

namespace DiskInsight.Monitoring.Providers;

internal sealed class DriveUsageProvider
{
    public DriveUsageSnapshot Read(string driveRoot)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(driveRoot))
            {
                return new DriveUsageSnapshot(DateTimeOffset.UtcNow, driveRoot, 0, 0, 0, "Drive root is empty.");
            }

            var root = driveRoot.Trim();
            if (root.Length == 2 && root[1] == ':')
            {
                root += "\\";
            }

            var di = new DriveInfo(root);
            if (!di.IsReady)
            {
                return new DriveUsageSnapshot(DateTimeOffset.UtcNow, root, 0, 0, 0, "Drive not ready.");
            }

            var total = (ulong)di.TotalSize;
            var free = (ulong)di.AvailableFreeSpace;
            if (free > total)
            {
                free = total;
            }

            var used = total - free;
            return new DriveUsageSnapshot(DateTimeOffset.UtcNow, di.Name, total, used, free, null);
        }
        catch (Exception ex)
        {
            return new DriveUsageSnapshot(DateTimeOffset.UtcNow, driveRoot, 0, 0, 0, ex.GetType().Name + ": " + ex.Message);
        }
    }
}

internal sealed record DriveUsageSnapshot(
    DateTimeOffset TimestampUtc,
    string DriveRoot,
    ulong TotalBytes,
    ulong UsedBytes,
    ulong FreeBytes,
    string? Error);

