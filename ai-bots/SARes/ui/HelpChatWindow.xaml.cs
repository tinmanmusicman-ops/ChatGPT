using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using SARes.engine;

namespace SARes.ui;

public partial class HelpChatWindow : Window
{
    private readonly IReadOnlyList<HelpManual.Section> _sections;
    private bool _busy;

    public HelpChatWindow(string manualPath)
    {
        InitializeComponent();

        CloseButton.Click += (_, _) => Close();
        ClearButton.Click += (_, _) => ClearMessages();
        SendButton.Click += async (_, _) => await SendAsync();

        QuestionTextBox.KeyDown += async (_, e) =>
        {
            if (e.Key == System.Windows.Input.Key.Enter)
            {
                e.Handled = true;
                await SendAsync();
            }
        };

        HideTagsCheckBox.Checked += (_, _) => RefreshAssistantMessages();
        HideTagsCheckBox.Unchecked += (_, _) => RefreshAssistantMessages();

        _sections = LoadManualOrThrow(manualPath);

        StatusText.Text = "Tip: try keywords like \"import\", \"pdf\", \"headers\", \"summary\", \"output\", or \"pandoc\".";
        AppendAssistant("Ask me how to use SARes. I can only answer using the operator manual.");

        Loaded += (_, _) =>
        {
            QuestionTextBox.Focus();
            QuestionTextBox.SelectAll();
        };
    }

    private static IReadOnlyList<HelpManual.Section> LoadManualOrThrow(string manualPath)
    {
        if (string.IsNullOrWhiteSpace(manualPath))
            throw new FileNotFoundException("Help manual path is empty.");
        if (!File.Exists(manualPath))
            throw new FileNotFoundException("Help manual not found: " + manualPath);

        var text = File.ReadAllText(manualPath);
        var sections = HelpManual.ParseSections(text);
        if (sections.Count == 0)
            throw new InvalidDataException("Help manual has no parsable sections (requires '## ' section headers).");
        return sections;
    }

    private async Task SendAsync()
    {
        if (_busy)
            return;

        var q = (QuestionTextBox.Text ?? "").Trim();
        if (q.Length == 0)
            return;

        QuestionTextBox.Text = "";
        AppendUser(q);

        try
        {
            SetBusy(true, "Searching manual...");
            await Task.Yield();

            var result = HelpManual.Search(q, _sections, maxMatches: 10) ?? "No documentation matches that term.";
            AppendAssistant(result);
            StatusText.Text = "";
        }
        catch (Exception ex)
        {
            AppendAssistant("Help manual error: " + ex.Message);
        }
        finally
        {
            SetBusy(false, "");
            QuestionTextBox.Focus();
        }
    }

    private void SetBusy(bool busy, string status)
    {
        _busy = busy;
        QuestionTextBox.IsEnabled = !busy;
        SendButton.IsEnabled = !busy;
        ClearButton.IsEnabled = !busy;
        StatusText.Text = status;
    }

    private void ClearMessages()
    {
        MessagesPanel.Children.Clear();
        StatusText.Text = "Cleared.";
    }

    private void AppendUser(string text) => AppendMessage("You", text, isUser: true);

    private void AppendAssistant(string text)
    {
        var content = text ?? "";
        if (HideTagsCheckBox.IsChecked == true)
            content = HelpManual.FilterTagLines(content);
        AppendMessage("SARes", content, isUser: false);
    }

    private void RefreshAssistantMessages()
    {
        // Re-render assistant messages based on Hide tags toggle.
        foreach (var child in MessagesPanel.Children)
        {
            if (child is not Border border)
                continue;
            if (border.Tag is not MessageMeta meta)
                continue;
            if (meta.IsUser)
                continue;

            if (border.Child is not StackPanel panel)
                continue;
            if (panel.Children.Count < 2)
                continue;

            var raw = meta.RawText ?? "";
            var content = HideTagsCheckBox.IsChecked == true ? HelpManual.FilterTagLines(raw) : raw;
            panel.Children[1] = BuildMarkdownContent(content);
        }
    }

    private void AppendMessage(string header, string text, bool isUser)
    {
        var borderBrush = (SolidColorBrush)FindResource("Border");
        var muted = (SolidColorBrush)FindResource("MutedText");
        var userBg = (SolidColorBrush)FindResource("UserBg");
        var assistantBg = (SolidColorBrush)FindResource("AssistantBg");

        var container = new Border
        {
            BorderBrush = borderBrush,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(10),
            Padding = new Thickness(10),
            Margin = new Thickness(0, 0, 0, 10),
            Background = isUser ? userBg : assistantBg,
            Tag = new MessageMeta(isUser, text)
        };

        var panel = new StackPanel();

        panel.Children.Add(new TextBlock
        {
            Text = header,
            Foreground = muted,
            FontWeight = FontWeights.SemiBold,
            Margin = new Thickness(0, 0, 0, 6)
        });

        panel.Children.Add(isUser
            ? new TextBlock { Text = text ?? "", TextWrapping = TextWrapping.Wrap }
            : BuildMarkdownContent(text ?? ""));

        container.Child = panel;
        MessagesPanel.Children.Add(container);

        MessagesScroll.ScrollToEnd();
    }

    private UIElement BuildMarkdownContent(string markdown)
    {
        var muted = (SolidColorBrush)FindResource("MutedText");

        var stack = new StackPanel();
        foreach (var el in RenderMarkdown(markdown ?? "", muted))
            stack.Children.Add(el);
        if (stack.Children.Count == 0)
            stack.Children.Add(new TextBlock { Text = "", TextWrapping = TextWrapping.Wrap });

        return stack;
    }

    private static IEnumerable<FrameworkElement> RenderMarkdown(string markdown, System.Windows.Media.Brush muted)
    {
        var text = (markdown ?? "").Replace("\r\n", "\n").Replace("\r", "\n");
        var lines = text.Split('\n');

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

        int i = 0;
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
                    Background = muted,
                    Opacity = 0.5,
                    Margin = new Thickness(0, 8, 0, 8)
                };
                i++;
                continue;
            }

            if (line.StartsWith("### ", StringComparison.Ordinal))
            {
                yield return MakeHeader(line[4..], 14);
                i++;
                continue;
            }
            if (line.StartsWith("## ", StringComparison.Ordinal))
            {
                yield return MakeHeader(line[3..], 16);
                i++;
                continue;
            }
            if (line.StartsWith("# ", StringComparison.Ordinal))
            {
                yield return MakeHeader(line[2..], 18);
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
                    yield return new TextBlock
                    {
                        Text = "• " + item,
                        TextWrapping = TextWrapping.Wrap,
                        Margin = new Thickness(16, 0, 0, 4)
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
                    yield return new TextBlock
                    {
                        Text = item,
                        TextWrapping = TextWrapping.Wrap,
                        Margin = new Thickness(16, 0, 0, 4)
                    };
                }
                continue;
            }

            // Paragraph: join lines until a structural boundary.
            var paraLines = new List<string>();
            while (i < lines.Length)
            {
                var lRaw = lines[i].TrimEnd();
                var l = lRaw.Trim();
                if (l.Length == 0)
                    break;
                if (IsHr(l) || IsHeader(l) || IsBullet(lRaw) || IsNumbered(lRaw))
                    break;
                paraLines.Add(l);
                i++;
            }

            var paragraph = string.Join(" ", paraLines.Where(x => x.Length > 0)).Trim();
            if (paragraph.Length > 0)
            {
                yield return new TextBlock
                {
                    Text = paragraph,
                    TextWrapping = TextWrapping.Wrap,
                    Margin = new Thickness(0, 0, 0, 8)
                };
            }

            // Consume any blank line(s).
            while (i < lines.Length && string.IsNullOrWhiteSpace(lines[i]))
                i++;
        }

        static TextBlock MakeHeader(string text, double size)
            => new()
            {
                Text = text.Trim(),
                FontSize = size,
                FontWeight = FontWeights.SemiBold,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 6, 0, 8)
            };
    }

    private sealed record MessageMeta(bool IsUser, string RawText);
}
