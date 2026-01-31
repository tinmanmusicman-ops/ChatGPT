using System;
using System.IO;

namespace SARes.engine;

public static class MarkdownResumeImporter
{
    public static string ImportMarkdownToTemplate(string mdPath)
    {
        if (string.IsNullOrWhiteSpace(mdPath) || !File.Exists(mdPath))
            throw new FileNotFoundException("Markdown file not found: " + mdPath);

        var md = File.ReadAllText(mdPath);
        return md.Replace("\r\n", "\n").Replace("\r", "\n").TrimEnd() + "\n";
    }
}
