using System.Collections.ObjectModel;
using System.Text;
using System.Windows;

namespace SARes.ui;

public partial class ReorderSectionsWindow : Window
{
    private readonly string _originalMarkdown;
    private readonly List<SectionBlock> _originalBlocks;
    private readonly ObservableCollection<SectionBlock> _blocks;

    public ReorderSectionsWindow(string markdown)
    {
        InitializeComponent();

        _originalMarkdown = NormalizeNewlines(markdown ?? "").TrimEnd() + "\n";
        var parsed = Parse(_originalMarkdown);
        if (parsed.Blocks.Count == 0)
            throw new InvalidOperationException("No '##' sections found to reorder.");

        _originalBlocks = parsed.Blocks;
        _blocks = new ObservableCollection<SectionBlock>(_originalBlocks);
        SectionsListBox.ItemsSource = _blocks;
        SectionsListBox.DisplayMemberPath = nameof(SectionBlock.Title);
        SectionsListBox.SelectionChanged += (_, _) => UpdatePreview();

        MoveUpButton.Click += (_, _) => MoveSelected(-1);
        MoveDownButton.Click += (_, _) => MoveSelected(1);
        ResetButton.Click += (_, _) => ResetOrder();
        ApplyButton.Click += (_, _) => ApplyAndClose();

        Loaded += (_, _) =>
        {
            SectionsListBox.SelectedIndex = 0;
            UpdatePreview();
        };

        StatusText.Text = "Drag-free reorder: use Move Up/Down.";
    }

    public string ReorderedMarkdown { get; private set; } = "";

    private void MoveSelected(int direction)
    {
        if (SectionsListBox.SelectedItem is not SectionBlock block)
            return;

        var index = _blocks.IndexOf(block);
        if (index < 0)
            return;

        var target = index + direction;
        if (target < 0 || target >= _blocks.Count)
            return;

        _blocks.Move(index, target);
        SectionsListBox.SelectedIndex = target;
    }

    private void ResetOrder()
    {
        _blocks.Clear();
        foreach (var b in _originalBlocks)
            _blocks.Add(b);
        SectionsListBox.SelectedIndex = 0;
        UpdatePreview();
    }

    private void UpdatePreview()
    {
        if (SectionsListBox.SelectedItem is not SectionBlock block)
        {
            PreviewTextBox.Text = "";
            return;
        }

        var sb = new StringBuilder();
        sb.AppendLine(block.HeaderLine);
        sb.AppendLine();

        var maxLines = 24;
        var count = 0;
        foreach (var line in block.Lines)
        {
            sb.AppendLine(line);
            count++;
            if (count >= maxLines)
            {
                sb.AppendLine("…");
                break;
            }
        }

        PreviewTextBox.Text = sb.ToString().TrimEnd();
    }

    private void ApplyAndClose()
    {
        var parsed = Parse(_originalMarkdown);
        var prefix = parsed.PrefixLines;

        var outLines = new List<string>();
        outLines.AddRange(prefix);

        foreach (var block in _blocks)
        {
            AppendBlock(outLines, block);
        }

        ReorderedMarkdown = string.Join("\n", TrimEdgeBlankLines(outLines)).TrimEnd() + "\n";
        DialogResult = true;
    }

    private static void AppendBlock(List<string> output, SectionBlock block)
    {
        if (output.Count > 0 && output[^1].Length != 0)
            output.Add("");

        output.Add(block.HeaderLine);
        output.AddRange(block.Lines);
    }

    private static ParsedMarkdown Parse(string markdown)
    {
        var md = NormalizeNewlines(markdown ?? "");
        var lines = md.Split('\n').Select(l => l.TrimEnd('\r')).ToList();

        var h2 = new List<int>();
        for (var i = 0; i < lines.Count; i++)
        {
            var t = (lines[i] ?? "").TrimStart();
            if (t.StartsWith("## ", StringComparison.Ordinal))
                h2.Add(i);
        }

        if (h2.Count == 0)
            return new ParsedMarkdown(lines, new List<SectionBlock>());

        var prefix = lines.Take(h2[0]).ToList();
        var blocks = new List<SectionBlock>();
        for (var idx = 0; idx < h2.Count; idx++)
        {
            var start = h2[idx];
            var end = (idx + 1 < h2.Count) ? h2[idx + 1] : lines.Count;
            var headerLine = (lines[start] ?? "").TrimEnd();
            var title = headerLine.TrimStart().Substring(3).Trim();

            var body = lines.Skip(start + 1).Take(Math.Max(0, end - (start + 1))).ToList();
            // Preserve body as-is, but trim trailing blank lines for cleaner joins.
            while (body.Count > 0 && string.IsNullOrWhiteSpace(body[^1]))
                body.RemoveAt(body.Count - 1);

            blocks.Add(new SectionBlock(title, headerLine, body));
        }

        return new ParsedMarkdown(prefix, blocks);
    }

    private static List<string> TrimEdgeBlankLines(List<string> lines)
    {
        var output = new List<string>(lines);
        while (output.Count > 0 && string.IsNullOrWhiteSpace(output[0]))
            output.RemoveAt(0);
        while (output.Count > 0 && string.IsNullOrWhiteSpace(output[^1]))
            output.RemoveAt(output.Count - 1);
        return output;
    }

    private static string NormalizeNewlines(string text) => (text ?? "").Replace("\r\n", "\n").Replace("\r", "\n");

    private sealed record ParsedMarkdown(List<string> PrefixLines, List<SectionBlock> Blocks);
    private sealed record SectionBlock(string Title, string HeaderLine, List<string> Lines);
}

