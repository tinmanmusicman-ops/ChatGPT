using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using Microsoft.Win32;

namespace DiskInsight;

internal static class StartupAppScanner
{
    private const string HsstTaskDescription = "HSST";

    internal sealed record StartupSnapshot(
        List<StartupItem> All,
        List<StartupItem> Filtered);

    internal sealed record StartupItem(
        string Name,
        string Source,
        string Command,
        bool? Enabled,
        string? Description,
        string? LocationHint);

    public static List<StartupItem> GetCurrentUserStartupItems()
        => GetCurrentUserStartupItemsSnapshot().Filtered;

    public static StartupSnapshot GetCurrentUserStartupItemsSnapshot()
    {
        var items = new List<StartupItem>(capacity: 64);

        // Registry sources (Task Manager Startup combines multiple sources).
        AddRegistryRunItems(Registry.CurrentUser, items, @"Software\Microsoft\Windows\CurrentVersion\Run", source: "HKCU Run", locationPrefix: @"HKCU\Software\Microsoft\Windows\CurrentVersion\Run");
        AddRegistryRunItems(Registry.CurrentUser, items, @"Software\Microsoft\Windows\CurrentVersion\RunOnce", source: "HKCU RunOnce", locationPrefix: @"HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce");
        AddRegistryRunItems(Registry.CurrentUser, items, @"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer\Run", source: "HKCU Policies Run", locationPrefix: @"HKCU\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer\Run");

        AddRegistryRunItems(Registry.LocalMachine, items, @"Software\Microsoft\Windows\CurrentVersion\Run", source: "HKLM Run", locationPrefix: @"HKLM\Software\Microsoft\Windows\CurrentVersion\Run");
        AddRegistryRunItems(Registry.LocalMachine, items, @"Software\Microsoft\Windows\CurrentVersion\RunOnce", source: "HKLM RunOnce", locationPrefix: @"HKLM\Software\Microsoft\Windows\CurrentVersion\RunOnce");
        AddRegistryRunItems(Registry.LocalMachine, items, @"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer\Run", source: "HKLM Policies Run", locationPrefix: @"HKLM\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer\Run");

        // 32-bit view entries (common for older installers).
        AddRegistryRunItems(RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry32), items, @"Software\Microsoft\Windows\CurrentVersion\Run", source: "HKLM32 Run", locationPrefix: @"HKLM32\Software\Microsoft\Windows\CurrentVersion\Run");
        AddRegistryRunItems(RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry32), items, @"Software\Microsoft\Windows\CurrentVersion\RunOnce", source: "HKLM32 RunOnce", locationPrefix: @"HKLM32\Software\Microsoft\Windows\CurrentVersion\RunOnce");

        // Startup folder(s).
        AddStartupFolderItems(items, Environment.SpecialFolder.Startup, source: "Startup Folder (User)");
        AddStartupFolderItems(items, Environment.SpecialFolder.CommonStartup, source: "Startup Folder (All Users)");

        // Scheduled tasks (for HSST-tagged automation).
        AddScheduledTaskItems(items, requiredDescription: HsstTaskDescription);

        var all = items
            .OrderBy(i => i.Name, StringComparer.OrdinalIgnoreCase)
            .ThenBy(i => i.Source, StringComparer.OrdinalIgnoreCase)
            .ToList();

        var filtered = all.Where(ShouldIncludeStartupItem).ToList();
        return new StartupSnapshot(all, filtered);
    }

    public static string BuildReport(List<StartupItem> items)
    {
        var snapshot = new StartupSnapshot(All: items, Filtered: items);
        return BuildReport(snapshot, filtered: true);
    }

    public static string BuildReport(StartupSnapshot snapshot, bool filtered)
    {
        var items = filtered ? snapshot.Filtered : snapshot.All;

        var report = new StringBuilder(capacity: 16_384);
        report.AppendLine(filtered
            ? "Startup Apps (Filtered)"
            : "Startup Apps (All)");
        report.AppendLine();
        report.AppendLine($"Total startup entries found: {snapshot.All.Count.ToString(CultureInfo.InvariantCulture)}");
        report.AppendLine($"Matches shown: {items.Count.ToString(CultureInfo.InvariantCulture)}");
        if (filtered)
        {
            report.AppendLine();
            report.AppendLine("Filter: command contains C:\\ChatGPT (or C:/ChatGPT) OR launches Python (python/py/pythonw) OR task description equals HSST.");
        }
        report.AppendLine();

        if (filtered && items.Count == 0)
        {
            report.AppendLine("(No matching startup items were found.)");
            report.AppendLine("Tip: Use Tools -> User Startup Apps (All) to see everything this scanner found.");
            report.AppendLine();
        }

        report.AppendLine($"  {"Enabled",7}  {"Source",-18}  Name");
        report.AppendLine();

        foreach (var item in items)
        {
            var enabled = item.Enabled switch
            {
                true => "Yes",
                false => "No",
                null => "n/a",
            };

            report.AppendLine($"  {enabled,7}  {TrimTo(item.Source, 18),-18}  {item.Name}");
            report.AppendLine($"           Command: {item.Command}");
            if (!string.IsNullOrWhiteSpace(item.Description))
            {
                report.AppendLine($"       Description: {item.Description}");
            }
            if (!string.IsNullOrWhiteSpace(item.LocationHint))
            {
                report.AppendLine($"           Location: {item.LocationHint}");
            }

            report.AppendLine();
        }

        return report.ToString();
    }

    private static void AddRegistryRunItems(RegistryKey root, List<StartupItem> items, string subKeyPath, string source, string locationPrefix)
    {
        try
        {
            using var key = root.OpenSubKey(subKeyPath, writable: false);
            if (key is null)
            {
                return;
            }

            foreach (var valueName in key.GetValueNames())
            {
                try
                {
                    var raw = key.GetValue(valueName);
                    var command = raw switch
                    {
                        string s => s,
                        string[] a => string.Join(" ", a),
                        _ => raw?.ToString() ?? string.Empty,
                    };

                    if (string.IsNullOrWhiteSpace(command))
                    {
                        continue;
                    }

                    command = ExpandEnv(command.Trim());
                    var enabled = TryGetStartupApprovedEnabled(sourceKey: "Run", valueName) ??
                                  TryGetStartupApprovedEnabled(sourceKey: "Run32", valueName);
                    items.Add(new StartupItem(
                        Name: valueName,
                        Source: source,
                        Command: command,
                        Enabled: enabled,
                        Description: null,
                        LocationHint: locationPrefix));
                }
                catch
                {
                }
            }
        }
        catch
        {
        }
    }

    private static void AddStartupFolderItems(List<StartupItem> items, Environment.SpecialFolder folderKind, string source)
    {
        string folder;
        try
        {
            folder = Environment.GetFolderPath(folderKind);
        }
        catch
        {
            return;
        }

        if (string.IsNullOrWhiteSpace(folder) || !Directory.Exists(folder))
        {
            return;
        }

        string[] files;
        try
        {
            files = Directory.GetFiles(folder);
        }
        catch
        {
            return;
        }

        foreach (var file in files.OrderBy(p => p, StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                var name = Path.GetFileNameWithoutExtension(file);
                if (string.IsNullOrWhiteSpace(name))
                {
                    name = Path.GetFileName(file);
                }

                var enabled = TryGetStartupApprovedEnabled(sourceKey: "StartupFolder", name) ??
                              TryGetStartupApprovedEnabled(sourceKey: "StartupFolder32", name);
                var command = file;
                if (file.EndsWith(".lnk", StringComparison.OrdinalIgnoreCase) &&
                    ShortcutResolver.TryResolve(file, out var target, out var args))
                {
                    command = string.IsNullOrWhiteSpace(args) ? target : $"\"{target}\" {args}";
                }

                command = ExpandEnv(command.Trim());
                items.Add(new StartupItem(
                    Name: name,
                    Source: source,
                    Command: command,
                    Enabled: enabled,
                    Description: null,
                    LocationHint: file));
            }
            catch
            {
            }
        }
    }

    private static void AddScheduledTaskItems(List<StartupItem> items, string requiredDescription)
    {
        try
        {
            var script = $@"
$ErrorActionPreference = 'Stop'
$desc = '{requiredDescription.Replace("'", "''")}'
Get-ScheduledTask |
  Where-Object {{ $_.Description -eq $desc }} |
  ForEach-Object {{
    $a = $_.Actions | Select-Object -First 1
    [pscustomobject]@{{
      TaskName = $_.TaskName
      TaskPath = $_.TaskPath
      State = [string]$_.State
      Author = $_.Author
      Description = $_.Description
      Execute = $a.Execute
      Arguments = $a.Arguments
      WorkingDirectory = $a.WorkingDirectory
    }}
  }} |
  ConvertTo-Json -Depth 6
".Trim();

            var json = RunPowerShellJson(script);
            if (string.IsNullOrWhiteSpace(json))
            {
                return;
            }

            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;

            if (root.ValueKind == JsonValueKind.Object)
            {
                TryAddScheduledTaskItem(items, root);
                return;
            }

            if (root.ValueKind != JsonValueKind.Array)
            {
                return;
            }

            foreach (var element in root.EnumerateArray())
            {
                TryAddScheduledTaskItem(items, element);
            }
        }
        catch
        {
        }
    }

    private static void TryAddScheduledTaskItem(List<StartupItem> items, JsonElement element)
    {
        if (element.ValueKind != JsonValueKind.Object)
        {
            return;
        }

        var taskName = GetJsonString(element, "TaskName");
        var taskPath = GetJsonString(element, "TaskPath") ?? "\\";
        if (string.IsNullOrWhiteSpace(taskName))
        {
            return;
        }

        var execute = GetJsonString(element, "Execute");
        var arguments = GetJsonString(element, "Arguments");
        var command = BuildCommand(execute, arguments);
        if (string.IsNullOrWhiteSpace(command))
        {
            command = taskName;
        }

        var stateText = GetJsonString(element, "State");
        bool? enabled = stateText?.Trim() switch
        {
            "Disabled" => false,
            "Ready" => true,
            "Running" => true,
            "Queued" => true,
            _ => null,
        };

        var description = GetJsonString(element, "Description");
        var fullPath = taskPath.EndsWith("\\", StringComparison.Ordinal) ? taskPath + taskName : taskPath + "\\" + taskName;

        items.Add(new StartupItem(
            Name: taskName,
            Source: "Task Scheduler",
            Command: command,
            Enabled: enabled,
            Description: description,
            LocationHint: fullPath));
    }

    private static string BuildCommand(string? execute, string? arguments)
    {
        execute = (execute ?? string.Empty).Trim();
        arguments = (arguments ?? string.Empty).Trim();
        if (string.IsNullOrWhiteSpace(execute))
        {
            return string.Empty;
        }

        return string.IsNullOrWhiteSpace(arguments) ? execute : execute + " " + arguments;
    }

    private static string? GetJsonString(JsonElement element, string propertyName)
    {
        if (!element.TryGetProperty(propertyName, out var prop))
        {
            return null;
        }

        if (prop.ValueKind == JsonValueKind.String)
        {
            return prop.GetString();
        }

        if (prop.ValueKind == JsonValueKind.Number)
        {
            return prop.GetRawText();
        }

        if (prop.ValueKind == JsonValueKind.True)
        {
            return "true";
        }

        if (prop.ValueKind == JsonValueKind.False)
        {
            return "false";
        }

        return prop.GetRawText();
    }

    private static string RunPowerShellJson(string script)
    {
        var encoded = Convert.ToBase64String(Encoding.Unicode.GetBytes(script));

        var startInfo = new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand " + encoded,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };

        using var process = Process.Start(startInfo);
        if (process is null)
        {
            return string.Empty;
        }

        var stdout = process.StandardOutput.ReadToEnd();
        var stderr = process.StandardError.ReadToEnd();
        process.WaitForExit(milliseconds: 10_000);

        if (process.ExitCode != 0)
        {
            return string.Empty;
        }

        // ConvertTo-Json emits nothing for empty pipelines; keep it as empty.
        return string.IsNullOrWhiteSpace(stderr) ? stdout.Trim() : stdout.Trim();
    }

    private static bool? TryGetStartupApprovedEnabled(string sourceKey, string itemName)
    {
        // Task Manager stores enable/disable for startup items here.
        // Values are binary blobs; commonly:
        //  - 0x02 => enabled
        //  - 0x03 => disabled
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(
                $@"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\{sourceKey}",
                writable: false);
            if (key is null)
            {
                return null;
            }

            var bytes = key.GetValue(itemName) as byte[];
            if (bytes is null || bytes.Length == 0)
            {
                return null;
            }

            return bytes[0] switch
            {
                0x02 => true,
                0x03 => false,
                _ => null,
            };
        }
        catch
        {
            return null;
        }
    }

    private static string TrimTo(string value, int maxLen)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return string.Empty;
        }

        var v = value.Trim();
        if (v.Length <= maxLen)
        {
            return v;
        }

        return v[..Math.Max(0, maxLen - 1)] + "...";
    }

    private static bool ShouldIncludeStartupItem(StartupItem item)
    {
        if (string.Equals(item.Description, HsstTaskDescription, StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        var command = ExpandEnv(item.Command ?? string.Empty);
        var normalized = command.Replace('/', '\\');
        if (normalized.IndexOf(@"C:\ChatGPT", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            return true;
        }

        return LooksLikePythonCommand(command) ||
               command.IndexOf("python", StringComparison.OrdinalIgnoreCase) >= 0;
    }

    private static bool LooksLikePythonCommand(string command)
    {
        if (string.IsNullOrWhiteSpace(command))
        {
            return false;
        }

        var exeToken = TryGetFirstCommandToken(command);
        if (string.IsNullOrWhiteSpace(exeToken))
        {
            return false;
        }

        exeToken = exeToken.Trim().Trim('"');
        var exeName = exeToken;
        try
        {
            // If this is a full path, reduce to filename.
            exeName = Path.GetFileName(exeToken);
        }
        catch
        {
        }

        return exeName.Equals("python", StringComparison.OrdinalIgnoreCase) ||
               exeName.Equals("python.exe", StringComparison.OrdinalIgnoreCase) ||
               exeName.Equals("pythonw.exe", StringComparison.OrdinalIgnoreCase) ||
               exeName.Equals("py", StringComparison.OrdinalIgnoreCase) ||
               exeName.Equals("py.exe", StringComparison.OrdinalIgnoreCase);
    }

    private static string? TryGetFirstCommandToken(string command)
    {
        try
        {
            var s = command.TrimStart();
            if (s.Length == 0)
            {
                return null;
            }

            if (s[0] == '"')
            {
                var end = s.IndexOf('"', startIndex: 1);
                if (end > 1)
                {
                    return s.Substring(1, end - 1);
                }

                return null;
            }

            var space = s.IndexOfAny(new[] { ' ', '\t', '\r', '\n' });
            if (space < 0)
            {
                return s;
            }

            return s[..space];
        }
        catch
        {
            return null;
        }
    }

    private static string ExpandEnv(string value)
    {
        try
        {
            return Environment.ExpandEnvironmentVariables(value);
        }
        catch
        {
            return value;
        }
    }

    private static class ShortcutResolver
    {
        public static bool TryResolve(string lnkPath, out string targetPath, out string? arguments)
        {
            targetPath = string.Empty;
            arguments = null;

            try
            {
                var link = (IShellLinkW)new ShellLink();
                var file = (IPersistFile)link;
                file.Load(lnkPath, 0);

                try
                {
                    link.Resolve(IntPtr.Zero, 0);
                }
                catch
                {
                }

                var sb = new StringBuilder(1024);
                link.GetPath(sb, sb.Capacity, out _, 0);
                var target = sb.ToString().TrimEnd('\0').Trim();
                if (string.IsNullOrWhiteSpace(target))
                {
                    return false;
                }

                var args = new StringBuilder(2048);
                link.GetArguments(args, args.Capacity);

                targetPath = target;
                arguments = args.ToString().TrimEnd('\0').Trim();
                return true;
            }
            catch
            {
                return false;
            }
        }

        [ComImport]
        [Guid("00021401-0000-0000-C000-000000000046")]
        private class ShellLink
        {
        }

        [ComImport]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        [Guid("000214F9-0000-0000-C000-000000000046")]
        private interface IShellLinkW
        {
            void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszFile, int cchMaxPath, out WIN32_FIND_DATAW pfd, uint fFlags);
            void GetIDList(out IntPtr ppidl);
            void SetIDList(IntPtr pidl);
            void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszName, int cchMaxName);
            void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string pszName);
            void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszDir, int cchMaxPath);
            void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string pszDir);
            void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszArgs, int cchMaxPath);
            void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string pszArgs);
            void GetHotkey(out short pwHotkey);
            void SetHotkey(short wHotkey);
            void GetShowCmd(out int piShowCmd);
            void SetShowCmd(int iShowCmd);
            void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszIconPath, int cchIconPath, out int piIcon);
            void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string pszIconPath, int iIcon);
            void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string pszPathRel, uint dwReserved);
            void Resolve(IntPtr hwnd, uint fFlags);
            void SetPath([MarshalAs(UnmanagedType.LPWStr)] string pszFile);
        }

        [ComImport]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        [Guid("0000010b-0000-0000-C000-000000000046")]
        private interface IPersistFile
        {
            void GetClassID(out Guid pClassID);
            [PreserveSig] int IsDirty();
            void Load([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, uint dwMode);
            void Save([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, bool fRemember);
            void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string pszFileName);
            void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string ppszFileName);
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct WIN32_FIND_DATAW
        {
            public uint dwFileAttributes;
            public System.Runtime.InteropServices.ComTypes.FILETIME ftCreationTime;
            public System.Runtime.InteropServices.ComTypes.FILETIME ftLastAccessTime;
            public System.Runtime.InteropServices.ComTypes.FILETIME ftLastWriteTime;
            public uint nFileSizeHigh;
            public uint nFileSizeLow;
            public uint dwReserved0;
            public uint dwReserved1;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
            public string cFileName;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 14)]
            public string cAlternateFileName;
        }
    }
}
