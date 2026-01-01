using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace DiskInsight;

internal static class DiskAnalyzer
{
    internal sealed record FileEntry(string FullPath, long SizeBytes);
    internal sealed class ExtensionStats
    {
        public long TotalBytes { get; private set; }
        public int FileCount { get; private set; }
        private readonly HashSet<string> _folders = new(StringComparer.OrdinalIgnoreCase);

        public int FolderCount => _folders.Count;

        public void AddFile(long sizeBytes, string? folderPath)
        {
            TotalBytes += sizeBytes;
            FileCount++;

            if (!string.IsNullOrWhiteSpace(folderPath))
            {
                _folders.Add(folderPath);
            }
        }
    }

    internal sealed record ScanResult(
        string[] Roots,
        List<FileEntry> Files,
        Dictionary<string, ExtensionStats> StatsByExtension);

    public static string BuildReport()
    {
        var scan = BuildScanResult();
        return BuildReport(scan);
    }

    public static ScanResult BuildScanResult()
    {
        var roots = GetScanRoots()
            .Where(Directory.Exists)
            .Where(IsOnCDrive)
            .ToArray();

        var (files, statsByExtension) = ScanRoots(roots);
        return new ScanResult(roots, files, statsByExtension);
    }

    public static string BuildReport(ScanResult scan)
    {
        var report = new StringBuilder(16_384);

        AppendDiskSummary(report);
        report.AppendLine();

        AppendLargestFiles(report, scan.Files);
        report.AppendLine();
        AppendExtensionSummary(report, scan.StatsByExtension);

        return report.ToString();
    }

    public static string BuildExtensionDetailsReport(ScanResult scan, string extension)
    {
        var normalized = NormalizeExtension(extension);
        var rows = scan.Files
            .Where(f => string.Equals(NormalizeExtension(Path.GetExtension(f.FullPath)), normalized, StringComparison.OrdinalIgnoreCase))
            .ToList();

        var report = new StringBuilder(16_384);
        report.AppendLine($"Extension Details: {normalized}");
        report.AppendLine();
        report.AppendLine($"Scan Roots: {scan.Roots.Length}");
        foreach (var root in scan.Roots.OrderBy(r => r, StringComparer.OrdinalIgnoreCase))
        {
            report.AppendLine($"  {root}");
        }

        report.AppendLine();
        report.AppendLine($"Files: {rows.Count}");

        var totalBytes = rows.Sum(r => r.SizeBytes);
        report.AppendLine($"Total Size: {FormatGb(totalBytes)}");

        var byFolder = rows
            .Select(r => new { Folder = Path.GetDirectoryName(r.FullPath) ?? "<unknown>", r.SizeBytes })
            .GroupBy(x => x.Folder, StringComparer.OrdinalIgnoreCase)
            .Select(g => new { Folder = g.Key, FileCount = g.Count(), TotalBytes = g.Sum(x => x.SizeBytes) })
            .OrderByDescending(x => x.TotalBytes)
            .ThenBy(x => x.Folder, StringComparer.OrdinalIgnoreCase)
            .Take(20)
            .ToList();

        report.AppendLine();
        report.AppendLine("Top Folders (by total size)");
        if (byFolder.Count == 0)
        {
            report.AppendLine("  (No files found.)");
        }
        else
        {
            foreach (var item in byFolder)
            {
                report.AppendLine($"  {FormatGb(item.TotalBytes),10}  {item.FileCount,6} files  {item.Folder}");
            }
        }

        var largest = rows
            .OrderByDescending(r => r.SizeBytes)
            .ThenBy(r => r.FullPath, StringComparer.OrdinalIgnoreCase)
            .Take(20)
            .ToList();

        report.AppendLine();
        report.AppendLine("Largest Files");
        if (largest.Count == 0)
        {
            report.AppendLine("  (No files found.)");
        }
        else
        {
            foreach (var file in largest)
            {
                report.AppendLine($"  {FormatGb(file.SizeBytes),10}  {file.FullPath}");
            }
        }

        return report.ToString();
    }

    private static void AppendDiskSummary(StringBuilder report)
    {
        var drive = new DriveInfo("C");
        var total = drive.TotalSize;
        var free = drive.TotalFreeSpace;
        var used = total - free;

        report.AppendLine("Disk Summary (C:\\)");
        report.AppendLine($"  Total: {FormatGb(total)}");
        report.AppendLine($"  Used : {FormatGb(used)}");
        report.AppendLine($"  Free : {FormatGb(free)}");
    }

    private static void AppendLargestFiles(StringBuilder report, List<FileEntry> files)
    {
        report.AppendLine("Top 10 Largest Files (scanned folders only)");

        var top = files
            .OrderByDescending(f => f.SizeBytes)
            .ThenBy(f => f.FullPath, StringComparer.OrdinalIgnoreCase)
            .Take(10)
            .ToList();

        if (top.Count == 0)
        {
            report.AppendLine("  (No files found in the scan scope.)");
            return;
        }

        foreach (var file in top)
        {
            report.AppendLine($"  {FormatGb(file.SizeBytes),10}  {file.FullPath}");
        }
    }

    private static void AppendExtensionSummary(StringBuilder report, Dictionary<string, ExtensionStats> statsByExtension)
    {
        report.AppendLine("File-Type Summary (by extension, scanned folders only)");

        if (statsByExtension.Count == 0)
        {
            report.AppendLine("  (No files found in the scan scope.)");
            return;
        }

        foreach (var (ext, stats) in statsByExtension
                     .OrderByDescending(kv => kv.Value.TotalBytes)
                     .ThenBy(kv => kv.Key, StringComparer.OrdinalIgnoreCase))
        {
            report.AppendLine($"  {FormatGb(stats.TotalBytes),10}  {stats.FileCount,8} files  {stats.FolderCount,6} folders  {ext}");
        }
    }

    private static (List<FileEntry> Files, Dictionary<string, ExtensionStats> StatsByExtension) ScanRoots(string[] roots)
    {
        var files = new List<FileEntry>(capacity: 8192);
        var statsByExt = new Dictionary<string, ExtensionStats>(StringComparer.OrdinalIgnoreCase);

        foreach (var root in roots.OrderBy(p => p, StringComparer.OrdinalIgnoreCase))
        {
            ScanDirectoryTree(root, files, statsByExt);
        }

        return (files, statsByExt);
    }

    private static void ScanDirectoryTree(string root, List<FileEntry> files, Dictionary<string, ExtensionStats> statsByExtension)
    {
        var pending = new Stack<string>();
        pending.Push(root);

        while (pending.Count > 0)
        {
            var current = pending.Pop();

            IEnumerable<string> subDirs;
            try
            {
                subDirs = Directory.EnumerateDirectories(current);
            }
            catch (UnauthorizedAccessException)
            {
                continue;
            }
            catch (IOException)
            {
                continue;
            }

            foreach (var subDir in subDirs)
            {
                if (ShouldSkipDirectory(subDir))
                {
                    continue;
                }
                pending.Push(subDir);
            }

            IEnumerable<string> filePaths;
            try
            {
                filePaths = Directory.EnumerateFiles(current);
            }
            catch (UnauthorizedAccessException)
            {
                continue;
            }
            catch (IOException)
            {
                continue;
            }

            foreach (var path in filePaths)
            {
                TryAddFile(path, files, statsByExtension);
            }
        }
    }

    private static void TryAddFile(string path, List<FileEntry> files, Dictionary<string, ExtensionStats> statsByExtension)
    {
        try
        {
            var info = new FileInfo(path);
            var size = info.Length;
            files.Add(new FileEntry(info.FullName, size));

            var ext = info.Extension;
            if (string.IsNullOrWhiteSpace(ext))
            {
                ext = "<no extension>";
            }
            else
            {
                ext = ext.ToLowerInvariant();
            }

            if (!statsByExtension.TryGetValue(ext, out var stats))
            {
                stats = new ExtensionStats();
                statsByExtension[ext] = stats;
            }

            stats.AddFile(size, info.DirectoryName);
        }
        catch (UnauthorizedAccessException)
        {
        }
        catch (IOException)
        {
        }
        catch (SystemException)
        {
        }
    }

    private static IEnumerable<string> GetScanRoots()
    {
        var userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);

        // Downloads has no reliable SpecialFolder on older frameworks; use the conventional path.
        var downloads = Path.Combine(userProfile, "Downloads");

        return new[]
        {
            Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
            downloads,
            Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
            Environment.GetFolderPath(Environment.SpecialFolder.MyVideos),
            Environment.GetFolderPath(Environment.SpecialFolder.MyPictures),
        }.Where(p => !string.IsNullOrWhiteSpace(p));
    }

    private static bool IsOnCDrive(string path)
    {
        try
        {
            return string.Equals(Path.GetPathRoot(path), @"C:\", StringComparison.OrdinalIgnoreCase);
        }
        catch
        {
            return false;
        }
    }

    private static bool ShouldSkipDirectory(string path)
    {
        try
        {
            var attrs = File.GetAttributes(path);
            return (attrs & FileAttributes.ReparsePoint) == FileAttributes.ReparsePoint;
        }
        catch
        {
            return true;
        }
    }

    private static string FormatGb(long bytes)
        => $"{bytes / (1024d * 1024d * 1024d):0.00} GB";

    private static string NormalizeExtension(string? ext)
    {
        if (string.IsNullOrWhiteSpace(ext))
        {
            return "<no extension>";
        }

        if (ext == "<no extension>")
        {
            return ext;
        }

        return ext.StartsWith('.') ? ext.ToLowerInvariant() : "." + ext.ToLowerInvariant();
    }
}
