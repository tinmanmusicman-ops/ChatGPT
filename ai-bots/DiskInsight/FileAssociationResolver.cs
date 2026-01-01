using System;
using System.Collections.Generic;
using System.IO;
using Microsoft.Win32;

namespace DiskInsight;

internal static class FileAssociationResolver
{
    internal sealed record AssociationInfo(
        string? ProgId,
        string? ExecutableName);

    internal sealed record ExtensionAssociationDetails(
        string Extension,
        string? UserChoiceProgId,
        string? DefaultProgId,
        string? OpenCommandExecutableName,
        string? PerceivedType,
        string? ContentType,
        string[] OpenWithExecutableNames,
        string[] OpenWithProgIds);

    public static AssociationInfo GetAssociation(string extension)
    {
        try
        {
            var normalized = NormalizeExtension(extension);
            if (normalized is null)
            {
                return new AssociationInfo(null, null);
            }

            var progId = TryGetProgId(normalized);
            var exeName = progId is null ? null : TryGetOpenCommandExecutableName(progId);
            return new AssociationInfo(progId, exeName);
        }
        catch
        {
            return new AssociationInfo(null, null);
        }
    }

    public static string[] GetAssociatedApplicationNames(string extension)
    {
        var list = new List<string>(capacity: 4);
        try
        {
            var details = GetExtensionAssociationDetails(extension);

            if (!string.IsNullOrWhiteSpace(details.OpenCommandExecutableName))
            {
                list.Add(details.OpenCommandExecutableName);
            }

            if (!string.IsNullOrWhiteSpace(details.UserChoiceProgId))
            {
                list.Add("UserChoice ProgId: " + details.UserChoiceProgId);
            }

            if (!string.IsNullOrWhiteSpace(details.DefaultProgId))
            {
                list.Add("Default ProgId: " + details.DefaultProgId);
            }

            foreach (var exe in details.OpenWithExecutableNames)
            {
                if (!string.IsNullOrWhiteSpace(exe))
                {
                    list.Add("OpenWith: " + exe);
                }
            }

            foreach (var progId in details.OpenWithProgIds)
            {
                if (!string.IsNullOrWhiteSpace(progId))
                {
                    list.Add("OpenWith ProgId: " + progId);
                }
            }

            if (!string.IsNullOrWhiteSpace(details.ContentType))
            {
                list.Add("ContentType: " + details.ContentType);
            }

            if (!string.IsNullOrWhiteSpace(details.PerceivedType))
            {
                list.Add("PerceivedType: " + details.PerceivedType);
            }
        }
        catch
        {
        }

        return list.Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
    }

    public static ExtensionAssociationDetails GetExtensionAssociationDetails(string extension)
    {
        var normalized = NormalizeExtension(extension) ?? string.Empty;

        var userChoiceProgId = TryGetUserChoiceProgId(normalized);
        var defaultProgId = TryGetProgId(normalized);

        var openWithExecutables = TryGetOpenWithListExecutables(normalized);
        var openWithProgIds = TryGetOpenWithProgIds(normalized);

        var perceivedType = TryGetExtensionStringValue(normalized, "PerceivedType");
        var contentType = TryGetExtensionStringValue(normalized, "Content Type");

        // Prefer UserChoice ProgId, otherwise default ProgId for the open command.
        var openCommandExe =
            (!string.IsNullOrWhiteSpace(userChoiceProgId) ? TryGetOpenCommandExecutableName(userChoiceProgId) : null) ??
            (!string.IsNullOrWhiteSpace(defaultProgId) ? TryGetOpenCommandExecutableName(defaultProgId) : null);

        return new ExtensionAssociationDetails(
            Extension: normalized,
            UserChoiceProgId: userChoiceProgId,
            DefaultProgId: defaultProgId,
            OpenCommandExecutableName: openCommandExe,
            PerceivedType: perceivedType,
            ContentType: contentType,
            OpenWithExecutableNames: openWithExecutables,
            OpenWithProgIds: openWithProgIds);
    }

    private static string? TryGetProgId(string normalizedExtension)
    {
        try
        {
            using var key = Registry.ClassesRoot.OpenSubKey(normalizedExtension);
            return key?.GetValue(null) as string;
        }
        catch
        {
            return null;
        }
    }

    private static string? TryGetExtensionStringValue(string normalizedExtension, string valueName)
    {
        try
        {
            using var key = Registry.ClassesRoot.OpenSubKey(normalizedExtension);
            return key?.GetValue(valueName) as string;
        }
        catch
        {
            return null;
        }
    }

    private static string? TryGetUserChoiceProgId(string normalizedExtension)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(normalizedExtension))
            {
                return null;
            }

            var keyPath = @"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\" + normalizedExtension + @"\UserChoice";
            using var key = Registry.CurrentUser.OpenSubKey(keyPath);
            return key?.GetValue("ProgId") as string;
        }
        catch
        {
            return null;
        }
    }

    private static string[] TryGetOpenWithListExecutables(string normalizedExtension)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(normalizedExtension))
            {
                return Array.Empty<string>();
            }

            var keyPath = @"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\" + normalizedExtension + @"\OpenWithList";
            using var key = Registry.CurrentUser.OpenSubKey(keyPath);
            if (key is null)
            {
                return Array.Empty<string>();
            }

            var values = new List<string>(capacity: 8);
            foreach (var valueName in key.GetValueNames())
            {
                if (string.Equals(valueName, "MRUList", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                if (key.GetValue(valueName) is string exe && !string.IsNullOrWhiteSpace(exe))
                {
                    values.Add(exe);
                }
            }

            return values.Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        }
        catch
        {
            return Array.Empty<string>();
        }
    }

    private static string[] TryGetOpenWithProgIds(string normalizedExtension)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(normalizedExtension))
            {
                return Array.Empty<string>();
            }

            var keyPath = @"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\" + normalizedExtension + @"\OpenWithProgids";
            using var key = Registry.CurrentUser.OpenSubKey(keyPath);
            if (key is null)
            {
                return Array.Empty<string>();
            }

            var names = key.GetValueNames();
            return names.Length == 0 ? Array.Empty<string>() : names;
        }
        catch
        {
            return Array.Empty<string>();
        }
    }

    private static string? TryGetOpenCommandExecutableName(string progId)
    {
        try
        {
            using var key = Registry.ClassesRoot.OpenSubKey(progId + "\\shell\\open\\command");
            var command = key?.GetValue(null) as string;
            if (string.IsNullOrWhiteSpace(command))
            {
                return null;
            }

            var exePath = ExtractExecutablePath(command);
            if (string.IsNullOrWhiteSpace(exePath))
            {
                return null;
            }

            var fileName = Path.GetFileName(exePath);
            return string.IsNullOrWhiteSpace(fileName) ? null : fileName;
        }
        catch
        {
            return null;
        }
    }

    private static string? ExtractExecutablePath(string command)
    {
        var trimmed = command.Trim();
        if (trimmed.Length == 0)
        {
            return null;
        }

        // Typical: "\"C:\\Program Files\\App\\app.exe\" \"%1\""
        if (trimmed[0] == '"')
        {
            var end = trimmed.IndexOf('"', startIndex: 1);
            if (end <= 1)
            {
                return null;
            }

            return trimmed.Substring(1, end - 1);
        }

        // Fallback: "C:\\Path\\app.exe %1"
        var space = trimmed.IndexOf(' ');
        return space > 0 ? trimmed[..space] : trimmed;
    }

    private static string? NormalizeExtension(string extension)
    {
        if (string.IsNullOrWhiteSpace(extension))
        {
            return null;
        }

        var ext = extension.Trim();
        if (ext == "<no extension>")
        {
            return null;
        }

        return ext.StartsWith('.') ? ext : "." + ext;
    }
}
