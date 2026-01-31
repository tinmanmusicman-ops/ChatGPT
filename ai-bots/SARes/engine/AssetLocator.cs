using System.IO;

namespace SARes.engine;

public sealed class AssetLocator
{
    private readonly string _baseDir;

    public AssetLocator(string baseDirectory)
    {
        _baseDir = baseDirectory;
    }

    public string ResumeDarkCssPath => Path.Combine(_baseDir, "assets", "css", "resume-dark.css");
    public string ResumeNorthCssPath => Path.Combine(_baseDir, "assets", "css", "resume-north.css");
    public string CoverLetterCssPath => Path.Combine(_baseDir, "assets", "css", "cover-letter.css");
    public string HelpCssPath => Path.Combine(_baseDir, "assets", "css", "help.css");

    public string CoverLetterTemplatePath => Path.Combine(_baseDir, "assets", "templates", "cover_letter_target.md");
    public string HelpManualPath => Path.Combine(_baseDir, "assets", "help", "sares_operator_manual.md");
    public string StartHereMarkdownPath => Path.Combine(_baseDir, "assets", "help", "start_here.md");
    public string StartHerePdfPath => Path.Combine(_baseDir, "assets", "help", "start_here.pdf");

    public string GetBaseResumeTemplatePath(AppSettings? settings = null)
    {
        if (settings is not null)
            return settings.ResolveBaseTemplatePath(_baseDir);

        return Path.Combine(_baseDir, "assets", "resume", "resume1.md");
    }
}
