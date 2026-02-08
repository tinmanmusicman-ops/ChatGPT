using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Navigation;
using UglyToad.PdfPig;

namespace Jitterbug;

public partial class MainWindow : Window
{
    private readonly string _assetsDir;
    private readonly List<string> _availableAssets;
    private readonly List<PdfPageText> _pdfPages;
    private string? _selectedAssetPath;

    private const string HelpChatNoMatch = "No documentation matches that term.";
    private const int HelpChatMaxMatches = 10;
    private static readonly SolidColorBrush HelpHeaderBrush = new(Color.FromRgb(34, 197, 94));
    private static readonly SolidColorBrush HelpBoldBrush = new(Color.FromRgb(59, 130, 246));
    private static readonly System.Text.RegularExpressions.Regex BoldNumberMarkerRegex =
        new(@"(?i)([^\n\-•])\s+(Step\s+\*\*\d+\.\*\*|\*\*\d+\.\*\*)", System.Text.RegularExpressions.RegexOptions.Compiled);

    private static string InsertLineBreaksBeforeBoldNumberMarkers(string text)
    {
        if (string.IsNullOrEmpty(text))
            return text ?? "";

        // Insert a newline before mid-line "Step **N.**" and "**N.**" markers so they don't render inline.
        return BoldNumberMarkerRegex.Replace(text, "$1\n$2");
    }

    public static string NormalizeToken(string token)
    {
        if (string.IsNullOrWhiteSpace(token))
            return "";

        var lower = token.ToLowerInvariant();
        var sb = new StringBuilder(lower.Length);
        foreach (var ch in lower)
        {
            if (char.IsLetterOrDigit(ch))
                sb.Append(ch);
        }

        var t = sb.ToString();
        if (t.Length == 0)
            return "";

        // Plural / 3rd-person singular.
        if (t.Length > 3 && t.EndsWith("ies", StringComparison.Ordinal))
            t = t[..^3] + "y";
        else if (t.Length > 3 && t.EndsWith("es", StringComparison.Ordinal))
            t = t[..^2];
        else if (t.Length > 3 && t.EndsWith("s", StringComparison.Ordinal) && !t.EndsWith("ss", StringComparison.Ordinal))
            t = t[..^1];

        // Past tense.
        if (t.Length > 4 && t.EndsWith("ied", StringComparison.Ordinal))
            t = t[..^3] + "y";
        else if (t.Length > 3 && t.EndsWith("ed", StringComparison.Ordinal))
            t = t[..^2];

        // Gerund.
        if (t.Length > 5 && t.EndsWith("ing", StringComparison.Ordinal))
            t = t[..^3];

        // Porter-ish cleanup for common verb forms.
        if (t.EndsWith("at", StringComparison.Ordinal) || t.EndsWith("bl", StringComparison.Ordinal) || t.EndsWith("iz", StringComparison.Ordinal))
            t += "e";
        else if (EndsWithDoubleConsonant(t) && !EndsWithOneOf(t, "l", "s", "z"))
            t = t[..^1];

        // Light stemming: collapse terminal silent-e for deterministic matching.
        if (t.Length > 3 && t.EndsWith("e", StringComparison.Ordinal))
            t = t[..^1];

        return t;

        static bool EndsWithOneOf(string s, params string[] suffixes)
        {
            foreach (var suffix in suffixes)
            {
                if (s.EndsWith(suffix, StringComparison.Ordinal))
                    return true;
            }
            return false;
        }

        static bool EndsWithDoubleConsonant(string s)
        {
            if (s.Length < 2)
                return false;
            var a = s[^1];
            var b = s[^2];
            if (a != b)
                return false;
            return IsConsonant(a);
        }

        static bool IsConsonant(char c)
        {
            c = char.ToLowerInvariant(c);
            if (c is 'a' or 'e' or 'i' or 'o' or 'u')
                return false;
            return char.IsLetter(c);
        }
    }

    public MainWindow()
    {
        InitializeComponent();
        _assetsDir = Path.Combine(AppContext.BaseDirectory, "Assets");
        _availableAssets = new();
        _pdfPages = LoadPdfPages();

        RefreshListButton.Click += (_, _) => RefreshAssetList();
        MarkdownList.SelectionChanged += MarkdownList_SelectionChanged;
        SendButton.Click += (_, _) => AskQuestion();
        ClearButton.Click += (_, _) => ClearConversation();
        QueryTextBox.KeyDown += QueryTextBox_KeyDown;

        FontFamily defaultFamily = new("Segoe UI");
        MarkdownSnippet.FontFamily = defaultFamily;
        MarkdownStubText("Select a file to load markdown text.");
        RefreshAssetList();
    }

    private void RefreshAssetList()
    {
        _availableAssets.Clear();
        if (Directory.Exists(_assetsDir))
        {
            var mdFiles = Directory.GetFiles(_assetsDir, "*.md", SearchOption.TopDirectoryOnly)
                .OrderBy(Path.GetFileName, StringComparer.OrdinalIgnoreCase);
            _availableAssets.AddRange(mdFiles);

            var pdfFiles = Directory.GetFiles(_assetsDir, "*.pdf", SearchOption.TopDirectoryOnly)
                .OrderBy(Path.GetFileName, StringComparer.OrdinalIgnoreCase);
            _availableAssets.AddRange(pdfFiles);
        }

        MarkdownList.ItemsSource = null;
        MarkdownList.ItemsSource = _availableAssets.Select(path => new FileInfo(path).Name);
        var count = _availableAssets.Count;
        StatusText.Text = count > 0 ? "Sources refreshed." : "No assets found.";
        MarkdownSnippet.Text = "";
        FilePathText.Text = "No file selected";
        _selectedAssetPath = null;
        ConversationPanel.Children.Clear();
    }

    private void MarkdownList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (MarkdownList.SelectedIndex < 0 || MarkdownList.SelectedIndex >= _availableAssets.Count)
        {
            _selectedAssetPath = null;
            FilePathText.Text = "No file selected";
            MarkdownSnippet.Text = "";
            return;
        }

        _selectedAssetPath = _availableAssets[MarkdownList.SelectedIndex];
        FilePathText.Text = _selectedAssetPath;
        LoadSnippetPreview();
        StatusText.Text = $"Loaded {_selectedAssetPath} for querying.";
    }

    private void LoadSnippetPreview()
    {
        if (string.IsNullOrWhiteSpace(_selectedAssetPath) || !File.Exists(_selectedAssetPath))
        {
            MarkdownSnippet.Text = "";
            return;
        }

        if (IsPdfAsset(_selectedAssetPath))
        {
            MarkdownSnippet.Text = "PDF content will be searched directly; results will show the exact section.";
            return;
        }

        var lines = File.ReadLines(_selectedAssetPath)
                        .Take(20)
                        .ToArray();
        MarkdownSnippet.Text = string.Join("\n", lines);
    }

    private void AskQuestion()
    {
        var query = QueryTextBox.Text?.Trim();
        if (string.IsNullOrWhiteSpace(query))
        {
            StatusText.Text = "Type a question before sending.";
            return;
        }

        if (string.IsNullOrWhiteSpace(_selectedAssetPath))
        {
            StatusText.Text = "Select a source file first.";
            return;
        }

        AddMessage(isUser: true, text: query);
        var responseText = BuildMarkdownResponse(query);
        AddMessage(isUser: false, text: responseText);
        QueryTextBox.Text = "";
        StatusText.Text = "Answer added.";
    }

    private string BuildMarkdownResponse(string query)
    {
        if (string.IsNullOrWhiteSpace(_selectedAssetPath))
            return "No source selected.";

        if (IsPdfAsset(_selectedAssetPath))
            return BuildPdfResponse(query);

        return BuildMarkdownAssetResponse(query);
    }

    private string BuildPdfResponse(string query)
    {
        if (_pdfPages.Count == 0)
            return "PDF content is unavailable.";

        var terms = NormalizeWords(query).ToArray();
        if (terms.Length == 0)
            return "Type a question before sending.";

        var best = _pdfPages
            .Select(page => new { page, score = ScorePdfPage(page, terms) })
            .Where(entry => entry.score > 0)
            .OrderByDescending(entry => entry.score)
            .FirstOrDefault();

        if (best == null)
            return "No matches found in the PDF.";

        var snippet = ExtractPdfSnippet(best.page, terms);
        return $"### From PDF page {best.page.PageNumber}\n\n{snippet}";
    }

    private static int ScorePdfPage(PdfPageText page, string[] terms)
    {
        var lowerText = page.LowerText;
        return terms.Count(term => lowerText.Contains(term));
    }

    private static string ExtractPdfSnippet(PdfPageText page, string[] terms)
    {
        var lowerTerms = terms.Select(t => t.ToLowerInvariant()).ToArray();
        var lines = page.Text.Split('\n');
        for (var idx = 0; idx < lines.Length; idx++)
        {
            var line = lines[idx];
            if (lowerTerms.Any(term => line.IndexOf(term, StringComparison.OrdinalIgnoreCase) >= 0))
            {
                var start = Math.Max(0, idx - 2);
                var end = Math.Min(lines.Length - 1, idx + 2);
                var snippetLines = lines.Skip(start).Take(end - start + 1).ToArray();
                return string.Join("\n", snippetLines).Trim();
            }
        }

        return page.Text.Trim();
    }

    private string BuildMarkdownAssetResponse(string query)
    {
        if (string.IsNullOrWhiteSpace(_selectedAssetPath))
            return "No Markdown selected.";

        var lines = File.ReadAllLines(_selectedAssetPath);
        var sections = ParseHelpManualSections(lines);
        if (sections.Count == 0)
            return "No Markdown sections found.";

        var result = KeywordLookupHelp(query, sections);
        return string.IsNullOrWhiteSpace(result) ? HelpChatNoMatch : result;
    }

    private sealed record HelpSection(string Title, IReadOnlyList<string> Tags, string Body);

    private static IReadOnlyList<HelpSection> ParseHelpManualSections(string[] lines)
    {
        var sections = new List<HelpSection>();
        var normalizedLines = (lines ?? Array.Empty<string>()).Select(l => (l ?? "").Replace("\r", "")).ToArray();

        string? currentTitle = null;
        List<string>? currentBody = null;
        List<string>? currentTags = null;

        void Flush()
        {
            if (currentBody is null)
                return;

            var body = string.Join("\n", currentBody).Trim();
            if (body.Length == 0)
            {
                currentTitle = null;
                currentBody = null;
                currentTags = null;
                return;
            }

            sections.Add(new HelpSection(
                Title: currentTitle ?? "",
                Tags: (currentTags ?? new List<string>())
                    .Select(t => NormalizeToken(t ?? ""))
                    .Where(t => t.Length > 0)
                    .ToArray(),
                Body: body));

            currentTitle = null;
            currentBody = null;
            currentTags = null;
        }

        static bool IsSectionHeader(string line)
            => line.StartsWith("## ", StringComparison.Ordinal) || line.StartsWith("### ", StringComparison.Ordinal);

        for (var i = 0; i < normalizedLines.Length; i++)
        {
            var line = normalizedLines[i];
            if (IsSectionHeader(line))
            {
                Flush();
                currentTitle = line.Trim();
                currentBody = new List<string> { line.TrimEnd() };
                currentTags = new List<string>();

                var j = i + 1;
                while (j < normalizedLines.Length && string.IsNullOrWhiteSpace(normalizedLines[j]))
                {
                    currentBody.Add(normalizedLines[j].TrimEnd());
                    j++;
                }

                if (j < normalizedLines.Length)
                {
                    var maybeTags = normalizedLines[j].Trim();
                    if (maybeTags.StartsWith("[tags:", StringComparison.OrdinalIgnoreCase))
                    {
                        currentBody.Add(normalizedLines[j].TrimEnd());
                        var payload = maybeTags;
                        payload = payload[6..]; // after "[tags:"
                        if (payload.EndsWith("]", StringComparison.Ordinal))
                            payload = payload[..^1];
                        payload = payload.Trim();
                        foreach (var tag in payload.Split(',').Select(t => t.Trim()).Where(t => t.Length > 0))
                            currentTags.Add(tag);
                        i = j;
                    }
                }

                continue;
            }

            if (currentBody is not null)
                currentBody.Add(line.TrimEnd());
        }

        Flush();
        return sections;
    }

    private static string? KeywordLookupHelp(string query, IReadOnlyList<HelpSection> sections)
    {
        var rawWords = TokenizeHelpQuery(query);
        if (rawWords.Count == 0)
            return null;

        var vocab = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var section in sections)
        {
            foreach (var t in section.Tags ?? Array.Empty<string>())
            {
                var tag = (t ?? "").Trim().ToLowerInvariant();
                if (tag.Length > 0)
                    vocab.Add(tag);
            }
        }

        if (vocab.Count == 0)
            return null;

        var vocabList = vocab.ToArray();
        var corrected = rawWords.Select(w => vocab.Contains(w) ? w : CorrectToVocab(w, vocabList)).ToArray();
        var keywords = corrected.Where(vocab.Contains).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        if (keywords.Length == 0)
            return null;

        var matches = sections.Where(section =>
        {
            var tags = new HashSet<string>((section.Tags ?? Array.Empty<string>())
                .Select(t => (t ?? "").Trim().ToLowerInvariant())
                .Where(t => t.Length > 0));

            if (tags.Count == 0)
                return false;

            if (keywords.Length == 1)
                return tags.Contains(keywords[0]);

            return keywords.All(tags.Contains);
        }).Take(Math.Max(1, HelpChatMaxMatches)).Select(s => s.Body).Where(b => !string.IsNullOrWhiteSpace(b)).ToArray();

        if (matches.Length == 0)
            return null;

        return string.Join("\n\n---\n\n", matches);
    }

    private static List<string> TokenizeHelpQuery(string text)
    {
        var matches = System.Text.RegularExpressions.Regex.Matches((text ?? "").ToLowerInvariant(), @"[a-z0-9][a-z0-9'-]+");
        var tokens = new List<string>(matches.Count);
        foreach (System.Text.RegularExpressions.Match match in matches)
        {
            var token = NormalizeToken(match.Value);
            if (token.Length > 0)
                tokens.Add(token);
        }
        return tokens;
    }

    private static string CorrectToVocab(string word, IReadOnlyList<string> vocab)
    {
        if (word.Length == 0)
            return word;

        string best = word;
        double bestScore = 0;
        foreach (var candidate in vocab)
        {
            var score = Similarity(word, candidate);
            if (score > bestScore)
            {
                bestScore = score;
                best = candidate;
            }
        }

        return bestScore >= 0.8 ? best : word;
    }

    private static double Similarity(string a, string b)
    {
        var maxLen = Math.Max(a.Length, b.Length);
        if (maxLen == 0)
            return 1.0;
        var dist = LevenshteinDistance(a, b);
        return 1.0 - (double)dist / maxLen;
    }

    private static int LevenshteinDistance(string a, string b)
    {
        var rows = a.Length + 1;
        var cols = b.Length + 1;
        var dist = new int[rows, cols];

        for (var i = 0; i < rows; i++)
            dist[i, 0] = i;
        for (var j = 0; j < cols; j++)
            dist[0, j] = j;

        for (var i = 1; i < rows; i++)
        {
            for (var j = 1; j < cols; j++)
            {
                var cost = a[i - 1] == b[j - 1] ? 0 : 1;
                dist[i, j] = Math.Min(
                    Math.Min(dist[i - 1, j] + 1, dist[i, j - 1] + 1),
                    dist[i - 1, j - 1] + cost);
            }
        }

        return dist[rows - 1, cols - 1];
    }

    private static double ScoreSection(MarkdownSection section, string[] queryWords, string[] lines)
    {
        var headingWords = NormalizeWords(section.HeadingLine).ToArray();
        var headingSet = new HashSet<string>(headingWords, StringComparer.OrdinalIgnoreCase);
        var blockText = string.Join(" ", lines.AsSpan(section.StartLineIndex, section.EndLineIndex - section.StartLineIndex).ToArray());
        var blockWords = NormalizeWords(blockText).ToArray();
        var blockSet = new HashSet<string>(blockWords, StringComparer.OrdinalIgnoreCase);

        var headingMatches = queryWords.Count(word => headingSet.Contains(word));
        var blockMatches = queryWords.Count(word => blockSet.Contains(word));

        double score = headingMatches * 10 + blockMatches;
        if (headingMatches > 0)
            score += 0.5;
        return score;
    }

    private static IReadOnlyList<MarkdownSection> ParseMarkdownSections(string[] lines)
    {
        var sections = new List<MarkdownSection>();

        for (var i = 0; i < lines.Length; i++)
        {
            var line = lines[i];
            var trimmedStart = line.TrimStart();
            if (!trimmedStart.StartsWith("#"))
                continue;

            var level = 0;
            while (level < trimmedStart.Length && trimmedStart[level] == '#')
                level++;
            if (level == 0 || level >= trimmedStart.Length || trimmedStart[level] != ' ')
                continue;

            sections.Add(new MarkdownSection
            {
                Level = level,
                HeadingLine = line,
                StartLineIndex = i,
                EndLineIndex = lines.Length
            });
        }

        for (var i = 0; i < sections.Count; i++)
        {
            var current = sections[i];
            for (var j = i + 1; j < sections.Count; j++)
            {
                if (sections[j].Level <= current.Level)
                {
                    current.EndLineIndex = sections[j].StartLineIndex;
                    break;
                }
            }
            sections[i] = current;
        }

        return sections;
    }

    private static IEnumerable<string> NormalizeWords(string text)
    {
        var normalized = (text ?? "")
            .ToLowerInvariant()
            .Replace("\r", " ")
            .Replace("\n", " ");

        var builder = new StringBuilder();
        foreach (var ch in normalized)
        {
            builder.Append(char.IsLetterOrDigit(ch) ? ch : ' ');
        }

        return builder.ToString()
            .Split(' ', StringSplitOptions.RemoveEmptyEntries)
            .Select(word => word.Trim())
            .Where(word => word.Length > 0);
    }

    private sealed class MarkdownSection
    {
        public int Level { get; set; }
        public string HeadingLine { get; set; } = "";
        public int StartLineIndex { get; set; }
        public int EndLineIndex { get; set; }
    }

    private sealed record PdfPageText(int PageNumber, string Text, string LowerText);

    private static List<PdfPageText> LoadPdfPages()
    {
        var assetsDir = Path.Combine(AppContext.BaseDirectory, "Assets");
        var pdfPath = Path.Combine(assetsDir, "jitterbug-flip2-user-guide.pdf");
        if (!File.Exists(pdfPath))
            return new List<PdfPageText>();

        using var document = PdfDocument.Open(pdfPath);
        var pages = new List<PdfPageText>();
        foreach (var page in document.GetPages())
        {
            var text = page.Text ?? string.Empty;
            pages.Add(new PdfPageText(page.Number, text, text.ToLowerInvariant()));
        }

        return pages;
    }

    private static bool IsPdfAsset(string path)
        => Path.GetExtension(path).Equals(".pdf", StringComparison.OrdinalIgnoreCase);

    private void AddMessage(bool isUser, string text)
    {
        var bg = isUser ? new SolidColorBrush(Color.FromRgb(31, 41, 55)) : new SolidColorBrush(Color.FromRgb(15, 15, 20));
        var fg = Brushes.White;
        var border = new Border
        {
            Background = bg,
            CornerRadius = new CornerRadius(10),
            Padding = new Thickness(10),
            Margin = new Thickness(0, 0, 0, 10)
        };

        var stack = new StackPanel();
        stack.Children.Add(new TextBlock
        {
            Text = isUser ? "You" : "Assistant",
            FontWeight = FontWeights.SemiBold,
            Foreground = fg,
            Margin = new Thickness(0, 0, 0, 4)
        });
        stack.Children.Add(isUser
            ? new TextBlock
            {
                Text = text,
                TextWrapping = TextWrapping.Wrap,
                Foreground = fg
            }
            : BuildMarkdownContent(text, fg));
        border.Child = stack;
        ConversationPanel.Children.Add(border);
        ConversationScroll.ScrollToEnd();
    }

    private void ClearConversation()
    {
        ConversationPanel.Children.Clear();
        StatusText.Text = "Conversation cleared.";
    }

    private UIElement BuildMarkdownContent(string markdown, Brush textBrush)
    {
        var stack = new StackPanel();
        foreach (var node in RenderMarkdown(markdown ?? "", textBrush))
            stack.Children.Add(node);
        if (stack.Children.Count == 0)
            stack.Children.Add(new TextBlock { Text = "", TextWrapping = TextWrapping.Wrap, Foreground = textBrush });

        return stack;
    }

    private static IEnumerable<FrameworkElement> RenderMarkdown(string markdown, Brush textBrush)
    {
        var mutedBrush = Brushes.LightGray;
        var linkBrush = Brushes.LightSkyBlue;
        var lines = (markdown ?? "").Replace("\r\n", "\n").Replace("\r", "\n").Split('\n');

        static bool IsHeader(string line)
            => line.StartsWith("# ", StringComparison.Ordinal)
               || line.StartsWith("## ", StringComparison.Ordinal)
               || line.StartsWith("### ", StringComparison.Ordinal);

        static bool IsBullet(string line)
            => line.TrimStart().StartsWith("- ", StringComparison.Ordinal);

        static bool IsNumbered(string line)
        {
            var s = line.TrimStart();
            var dot = s.IndexOf('.');
            if (dot <= 0 || dot > 3)
                return false;
            for (var i = 0; i < dot; i++)
            {
                if (!char.IsDigit(s[i]))
                    return false;
            }
            return dot + 1 < s.Length && s[dot + 1] == ' ';
        }

        static bool IsHr(string line)
            => string.Equals(line.Trim(), "---", StringComparison.Ordinal);

        var i = 0;
        while (i < lines.Length)
        {
            var raw = lines[i].TrimEnd();
            var line = raw.Trim();

            if (line.Length == 0)
            {
                i++;
                continue;
            }

            if (IsHr(line))
            {
                yield return new Border
                {
                    Height = 1,
                    Background = mutedBrush,
                    Opacity = 0.5,
                    Margin = new Thickness(0, 8, 0, 8)
                };
                i++;
                continue;
            }

            if (line.StartsWith("### ", StringComparison.Ordinal))
            {
                yield return MakeHeader(line[4..], 14, textBrush);
                i++;
                continue;
            }
            if (line.StartsWith("## ", StringComparison.Ordinal))
            {
                yield return MakeHeader(line[3..], 16, textBrush);
                i++;
                continue;
            }
            if (line.StartsWith("# ", StringComparison.Ordinal))
            {
                yield return MakeHeader(line[2..], 18, textBrush);
                i++;
                continue;
            }

            if (IsBullet(raw))
            {
                var items = new List<string>();
                while (i < lines.Length && IsBullet(lines[i]))
                {
                    var t = lines[i].TrimStart();
                    items.Add(t.Length >= 2 ? t[2..].Trim() : "");
                    i++;
                }

                foreach (var item in items.Where(x => x.Length > 0))
                {
                    var renderInline = true;
                    if (renderInline)
                    {
                        var tb = new TextBlock
                        {
                            TextWrapping = TextWrapping.Wrap,
                            Margin = new Thickness(16, 0, 0, 4),
                            Foreground = textBrush
                        };
                        tb.Inlines.Add(new Run("• ") { Foreground = textBrush });
                        tb.Inlines.Clear();
                        tb.Inlines.Add(new Run("\u2022 ") { Foreground = textBrush });
                        AppendInlines(tb.Inlines, InsertLineBreaksBeforeBoldNumberMarkers(item), textBrush, linkBrush);
                        yield return tb;
                    }
                    else
                        yield return new TextBlock
                    {
                        Text = "• " + item,
                        TextWrapping = TextWrapping.Wrap,
                        Margin = new Thickness(16, 0, 0, 4),
                        Foreground = textBrush
                    };
                }
                continue;
            }

            if (IsNumbered(raw))
            {
                var items = new List<string>();
                while (i < lines.Length && IsNumbered(lines[i]))
                {
                    items.Add(lines[i].Trim());
                    i++;
                }

                foreach (var item in items.Where(x => x.Length > 0))
                {
                    var tb = new TextBlock
                    {
                        TextWrapping = TextWrapping.Wrap,
                        Margin = new Thickness(16, 0, 0, 4),
                        Foreground = textBrush
                    };
                    AppendInlines(tb.Inlines, InsertLineBreaksBeforeBoldNumberMarkers(item), textBrush, linkBrush);
                    yield return tb;
                }
                continue;
            }

            var paragraphLines = new List<string>();
            while (i < lines.Length)
            {
                var candidate = lines[i].TrimEnd();
                var trimmed = candidate.Trim();
                if (trimmed.Length == 0)
                    break;
                if (IsHr(trimmed) || IsHeader(trimmed) || IsBullet(candidate) || IsNumbered(candidate))
                    break;
                paragraphLines.Add(trimmed);
                i++;
            }

            var paragraph = string.Join(" ", paragraphLines.Where(x => x.Length > 0)).Trim();
            if (paragraph.Length > 0)
            {
                var tb = new TextBlock
                {
                    TextWrapping = TextWrapping.Wrap,
                    Margin = new Thickness(0, 0, 0, 8),
                    Foreground = textBrush
                };
                AppendInlines(tb.Inlines, InsertLineBreaksBeforeBoldNumberMarkers(paragraph), textBrush, linkBrush);
                yield return tb;
            }

            while (i < lines.Length && string.IsNullOrWhiteSpace(lines[i]))
                i++;
        }

        static TextBlock MakeHeader(string text, double size, Brush foreground)
            => new()
            {
                Text = text.Trim(),
                FontSize = size,
                FontWeight = FontWeights.Bold,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 6, 0, 8),
                Foreground = HelpHeaderBrush
            };

        static void AppendInlines(InlineCollection target, string text, Brush textBrush, Brush linkBrush)
        {
            text ??= "";
            var index = 0;

            void AppendPlain(string s)
            {
                if (s.Length == 0)
                    return;
                target.Add(new Run(s) { Foreground = textBrush });
            }

            while (index < text.Length)
            {
                if (text[index] == '\n')
                {
                    target.Add(new LineBreak());
                    index++;
                    continue;
                }

                if (text[index] == '`')
                {
                    var end = text.IndexOf('`', index + 1);
                    if (end > index + 1)
                    {
                        var codeText = text.Substring(index + 1, end - index - 1);
                        var span = new Span(new Run(codeText) { Foreground = textBrush })
                        {
                            FontFamily = new FontFamily("Consolas"),
                            Background = new SolidColorBrush(Color.FromArgb(32, 255, 255, 255))
                        };
                        target.Add(span);
                        index = end + 1;
                        continue;
                    }
                }

                if (index + 1 < text.Length && text[index] == '*' && text[index + 1] == '*')
                {
                    var end = text.IndexOf("**", index + 2, StringComparison.Ordinal);
                    if (end > index + 2)
                    {
                        var inner = text.Substring(index + 2, end - index - 2);
                        var span = new Span { FontWeight = FontWeights.Bold, Foreground = HelpBoldBrush };
                        AppendInlines(span.Inlines, inner, HelpBoldBrush, linkBrush);
                        target.Add(span);
                        index = end + 2;
                        continue;
                    }
                }

                if (text[index] == '*' && (index + 1 >= text.Length || text[index + 1] != '*'))
                {
                    var end = text.IndexOf('*', index + 1);
                    if (end > index + 1)
                    {
                        var inner = text.Substring(index + 1, end - index - 1);
                        var span = new Span { FontStyle = FontStyles.Italic };
                        AppendInlines(span.Inlines, inner, textBrush, linkBrush);
                        target.Add(span);
                        index = end + 1;
                        continue;
                    }
                }

                if (text[index] == '[')
                {
                    var closeBracket = text.IndexOf(']', index + 1);
                    if (closeBracket > index + 1 && closeBracket + 1 < text.Length && text[closeBracket + 1] == '(')
                    {
                        var closeParen = text.IndexOf(')', closeBracket + 2);
                        if (closeParen > closeBracket + 2)
                        {
                            var label = text.Substring(index + 1, closeBracket - index - 1);
                            var url = text.Substring(closeBracket + 2, closeParen - closeBracket - 2);
                            if (Uri.TryCreate(url, UriKind.Absolute, out var uri))
                            {
                                var link = new Hyperlink(new Run(label) { Foreground = linkBrush })
                                {
                                    NavigateUri = uri,
                                    Foreground = linkBrush
                                };
                                link.RequestNavigate += static (_, e) =>
                                {
                                    try
                                    {
                                        Process.Start(new ProcessStartInfo(e.Uri.AbsoluteUri) { UseShellExecute = true });
                                    }
                                    catch
                                    {
                                    }
                                    e.Handled = true;
                                };
                                target.Add(link);
                                index = closeParen + 1;
                                continue;
                            }
                        }
                    }
                }

                var next = NextSpecialIndex(text, index);
                AppendPlain(text.Substring(index, next - index));
                index = next;
            }

            static int NextSpecialIndex(string s, int start)
            {
                var best = -1;

                void Consider(int candidate)
                {
                    if (candidate < 0 || candidate <= start)
                        return;
                    if (best < 0 || candidate < best)
                        best = candidate;
                }

                Consider(s.IndexOf('`', start));
                Consider(s.IndexOf("**", start, StringComparison.Ordinal));
                Consider(s.IndexOf('*', start));
                Consider(s.IndexOf('[', start));
                Consider(s.IndexOf('\n', start));

                return best < 0 ? s.Length : best;
            }
        }
    }

    private void QueryTextBox_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && (Keyboard.Modifiers & ModifierKeys.Shift) == 0)
        {
            e.Handled = true;
            AskQuestion();
        }
    }

    private void MinimizeTitleButton_Click(object sender, RoutedEventArgs e)
        => SystemCommands.MinimizeWindow(this);

    private void MaximizeTitleButton_Click(object sender, RoutedEventArgs e)
    {
        if (WindowState == WindowState.Maximized)
        {
            SystemCommands.RestoreWindow(this);
            return;
        }

        SystemCommands.MaximizeWindow(this);
    }

    private void CloseTitleButton_Click(object sender, RoutedEventArgs e)
        => Close();

    private void TitleCloseButton_PreviewMouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        // Placeholder for logging in future.
    }

    private void TitleBar_MouseDown(object sender, MouseButtonEventArgs e)
    {
        if (e.ChangedButton != MouseButton.Left)
            return;

        if (e.ClickCount == 2)
        {
            WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;
            return;
        }

        if (IsClickHandledByChildControl(e.OriginalSource as DependencyObject))
            return;

        try
        {
            DragMove();
        }
        catch
        {
        }
    }

    private void TitleBar_MouseRightButtonUp(object sender, MouseButtonEventArgs e)
    {
        var point = PointToScreen(e.GetPosition(this));
        SystemCommands.ShowSystemMenu(this, point);
    }

    private static bool IsClickHandledByChildControl(DependencyObject? source)
    {
        while (source is not null)
        {
            if (source is ButtonBase)
                return true;

            source = VisualTreeHelper.GetParent(source);
        }

        return false;
    }

    private void MarkdownStubText(string text)
    {
        MarkdownSnippet.Text = text;
    }

}
