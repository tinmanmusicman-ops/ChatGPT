using System;
using System.Drawing;
using System.Net;
using System.Text;
using System.Windows.Forms;

namespace DiskInsight;

internal sealed class EiCommentaryDialog : Form
{
    public EiCommentaryDialog(string commentaryText)
    {
        Text = "EI Commentary (Advisory Only)";
        StartPosition = FormStartPosition.CenterParent;
        Width = 900;
        Height = 650;
        MinimizeBox = false;
        MaximizeBox = true;

        var header = new Label
        {
            Dock = DockStyle.Top,
            AutoSize = false,
            Height = 30,
            TextAlign = ContentAlignment.MiddleLeft,
            Text = "EI Commentary (Advisory Only)",
            Padding = new Padding(10, 5, 10, 5),
        };

        var tabs = new TabControl { Dock = DockStyle.Fill };

        var renderedTab = new TabPage("Rendered");
        var rawTab = new TabPage("Raw");

        var browser = new WebBrowser
        {
            Dock = DockStyle.Fill,
            AllowWebBrowserDrop = false,
            ScriptErrorsSuppressed = true,
            WebBrowserShortcutsEnabled = true,
        };
        browser.Navigating += (_, e) =>
        {
            try
            {
                // Allow the internal about:blank navigation used by DocumentText, and in-page anchors.
                if (e.Url is null || string.Equals(e.Url.Scheme, "about", StringComparison.OrdinalIgnoreCase))
                {
                    return;
                }

                // Prevent external navigation; this dialog is for local rendering only.
                e.Cancel = true;
            }
            catch
            {
                e.Cancel = true;
            }
        };
        browser.NewWindow += (_, e) => e.Cancel = true;

        var raw = new TextBox
        {
            Multiline = true,
            ReadOnly = true,
            ScrollBars = ScrollBars.Both,
            Dock = DockStyle.Fill,
            WordWrap = true,
            Font = new Font("Consolas", 10f),
            Text = commentaryText ?? string.Empty,
        };

        renderedTab.Controls.Add(browser);
        rawTab.Controls.Add(raw);
        tabs.TabPages.Add(renderedTab);
        tabs.TabPages.Add(rawTab);

        var close = new Button
        {
            Text = "Close",
            DialogResult = DialogResult.OK,
            Anchor = AnchorStyles.Right | AnchorStyles.Bottom,
            Width = 100,
            Height = 28,
        };

        var copy = new Button
        {
            Text = "Copy",
            Anchor = AnchorStyles.Left | AnchorStyles.Bottom,
            Width = 100,
            Height = 28,
        };
        copy.Click += (_, _) =>
        {
            try
            {
                Clipboard.SetText(commentaryText ?? string.Empty);
            }
            catch
            {
            }
        };

        var bottom = new Panel { Dock = DockStyle.Bottom, Height = 44, Padding = new Padding(10) };
        copy.Left = 10;
        copy.Top = 8;
        copy.Anchor = AnchorStyles.Left | AnchorStyles.Top;

        close.Left = bottom.Width - close.Width - 10;
        close.Top = 8;
        close.Anchor = AnchorStyles.Right | AnchorStyles.Top;
        bottom.Controls.Add(close);
        bottom.Controls.Add(copy);

        AcceptButton = close;
        CancelButton = close;

        Controls.Add(tabs);
        Controls.Add(bottom);
        Controls.Add(header);

        browser.DocumentText = WrapHtml(MarkdownToHtml(commentaryText ?? string.Empty));
    }

    private static string WrapHtml(string bodyHtml)
    {
        var css = @"
            body { font-family: Segoe UI, Arial, sans-serif; font-size: 12pt; margin: 16px; }
            h1, h2, h3 { margin: 0.6em 0 0.3em; }
            p { margin: 0.4em 0; line-height: 1.35; }
            ul { margin: 0.4em 0 0.8em 1.2em; }
            code, pre { font-family: Consolas, 'Courier New', monospace; }
            pre { background: #f6f8fa; padding: 10px; border-radius: 6px; overflow-x: auto; }
            .box { border: 1px solid #ddd; border-radius: 8px; padding: 12px; background: #fff; }
        ";

        return $"""
                <!doctype html>
                <html>
                  <head>
                    <meta http-equiv="X-UA-Compatible" content="IE=edge" />
                    <meta charset="utf-8" />
                    <style>{css}</style>
                  </head>
                  <body>
                    <div class="box">
                      {bodyHtml}
                    </div>
                  </body>
                </html>
                """;
    }

    private static string MarkdownToHtml(string markdown)
    {
        // Minimal, safe markdown renderer (escapes all input; supports headings, lists, and fenced code blocks).
        var lines = markdown.Replace("\r\n", "\n").Replace("\r", "\n").Split('\n');
        var sb = new StringBuilder(markdown.Length + 512);

        var inList = false;
        var inCode = false;

        void CloseList()
        {
            if (!inList)
            {
                return;
            }
            sb.AppendLine("</ul>");
            inList = false;
        }

        void CloseCode()
        {
            if (!inCode)
            {
                return;
            }
            sb.AppendLine("</code></pre>");
            inCode = false;
        }

        foreach (var rawLine in lines)
        {
            var line = rawLine ?? string.Empty;

            if (line.TrimStart().StartsWith("```", StringComparison.Ordinal))
            {
                if (inCode)
                {
                    CloseCode();
                }
                else
                {
                    CloseList();
                    sb.AppendLine("<pre><code>");
                    inCode = true;
                }
                continue;
            }

            if (inCode)
            {
                sb.AppendLine(WebUtility.HtmlEncode(line));
                continue;
            }

            var trimmed = line.Trim();
            if (trimmed.Length == 0)
            {
                CloseList();
                sb.AppendLine("<p></p>");
                continue;
            }

            if (trimmed.StartsWith("#", StringComparison.Ordinal))
            {
                CloseList();
                var level = 0;
                while (level < trimmed.Length && trimmed[level] == '#')
                {
                    level++;
                }
                level = Math.Clamp(level, 1, 3);
                var text = trimmed[level..].Trim();
                sb.AppendLine($"<h{level}>{WebUtility.HtmlEncode(text)}</h{level}>");
                continue;
            }

            if (trimmed.StartsWith("- ", StringComparison.Ordinal) || trimmed.StartsWith("* ", StringComparison.Ordinal))
            {
                if (!inList)
                {
                    sb.AppendLine("<ul>");
                    inList = true;
                }
                var item = trimmed[2..].Trim();
                sb.AppendLine($"<li>{WebUtility.HtmlEncode(item)}</li>");
                continue;
            }

            CloseList();
            sb.AppendLine($"<p>{WebUtility.HtmlEncode(trimmed)}</p>");
        }

        CloseCode();
        CloseList();

        if (sb.Length == 0)
        {
            return "<p>(No content)</p>";
        }

        return sb.ToString();
    }
}
