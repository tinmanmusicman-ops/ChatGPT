using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Windows;
using System.Windows.Input;
using Markdig;
using Microsoft.Web.WebView2.Wpf;
using SARes.engine;

namespace SARes.ui;

public partial class HelpChatWindow : Window
{
    private readonly IReadOnlyList<HelpManual.Section> _sections;
    private readonly string _css;
    private readonly MarkdownPipeline _markdownPipeline;
    private bool _busy;
    private readonly List<MessageMeta> _messages = new();
    private readonly SemaphoreSlim _renderLock = new(1, 1);
    private bool _webReady;

    public HelpChatWindow(string manualPath, string? cssPath = null)
    {
        InitializeComponent();

        CloseButton.Click += (_, _) => Close();
        ClearButton.Click += (_, _) => ClearMessages();
        SendButton.Click += async (_, _) => await SendAsync().ConfigureAwait(true);

        QuestionTextBox.KeyDown += async (_, e) =>
        {
            if (e.Key == System.Windows.Input.Key.Enter)
            {
                e.Handled = true;
                await SendAsync().ConfigureAwait(true);
            }
        };

        HideTagsCheckBox.Checked += async (_, _) => await RenderTranscriptAsync(scrollToBottom: false).ConfigureAwait(true);
        HideTagsCheckBox.Unchecked += async (_, _) => await RenderTranscriptAsync(scrollToBottom: false).ConfigureAwait(true);

        _sections = LoadManualOrThrow(manualPath);
        _css = LoadCssOrEmpty(cssPath);
        _markdownPipeline = new MarkdownPipelineBuilder().UseAdvancedExtensions().DisableHtml().Build();

        StatusText.Text = "Tip: try keywords like \"import\", \"pdf\", \"headers\", \"summary\", \"output\", or \"pandoc\".";
        AppendAssistant("Ask me how to use SARes. I can only answer using the operator manual.");

        Loaded += async (_, _) =>
        {
            await EnsureChatWebReadyAsync(ChatWeb).ConfigureAwait(true);
            _webReady = true;
            await RenderTranscriptAsync(scrollToBottom: true).ConfigureAwait(true);
            QuestionTextBox.Focus();
            QuestionTextBox.SelectAll();
        };
    }

    private static string LoadCssOrEmpty(string? cssPath)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(cssPath))
                return "";
            if (!File.Exists(cssPath))
                return "";
            return File.ReadAllText(cssPath);
        }
        catch
        {
            return "";
        }
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
        _messages.Clear();
        StatusText.Text = "Cleared.";
        _ = RenderTranscriptAsync(scrollToBottom: false);
    }

    private void AppendUser(string text) => AppendMessage("You", text, isUser: true);

    private void AppendAssistant(string text)
    {
        AppendMessage("SARes", text ?? "", isUser: false);
    }

    private void AppendMessage(string header, string text, bool isUser)
    {
        _messages.Add(new MessageMeta(isUser, header ?? "", text ?? ""));
        _ = RenderTranscriptAsync(scrollToBottom: true);
    }

    private sealed record MessageMeta(bool IsUser, string Header, string RawText);

    private static async Task EnsureChatWebReadyAsync(WebView2 view)
    {
        await WebViewHelpers.EnsureReadyAsync(view).ConfigureAwait(true);
        if (view.CoreWebView2 is null)
            return;

        view.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
        view.CoreWebView2.Settings.AreDevToolsEnabled = false;
        view.CoreWebView2.Settings.IsZoomControlEnabled = false;

        view.CoreWebView2.NavigationStarting += (_, e) =>
        {
            try
            {
                var uri = e.Uri ?? "";
                if (string.Equals(uri, "about:blank", StringComparison.OrdinalIgnoreCase))
                    return;

                e.Cancel = true;
                if (uri.StartsWith("http://", StringComparison.OrdinalIgnoreCase) ||
                    uri.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
                {
                    _ = System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(uri) { UseShellExecute = true });
                }
            }
            catch
            {
                e.Cancel = true;
            }
        };
    }

    private async Task RenderTranscriptAsync(bool scrollToBottom)
    {
        if (!_webReady)
            return;

        await _renderLock.WaitAsync().ConfigureAwait(true);
        try
        {
            var html = BuildTranscriptHtml();
            ChatWeb.NavigateToString(html);

            if (scrollToBottom && ChatWeb.CoreWebView2 is not null)
            {
                await Task.Delay(50).ConfigureAwait(true);
                await ChatWeb.CoreWebView2.ExecuteScriptAsync("window.scrollTo(0, document.body.scrollHeight);").ConfigureAwait(true);
            }
        }
        finally
        {
            _renderLock.Release();
        }
    }

    private string BuildTranscriptHtml()
    {
        var sb = new StringBuilder();
        sb.AppendLine("<!doctype html>");
        sb.AppendLine("<html lang=\"en\">");
        sb.AppendLine("<head>");
        sb.AppendLine("<meta charset=\"utf-8\" />");
        sb.AppendLine("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />");
        sb.AppendLine("<style>");
        sb.AppendLine(_css);
        sb.AppendLine(@"
body { background: transparent; }
.chat { padding: 0; margin: 0; }
.msg { border: 1px solid #334155; border-radius: 10px; padding: 10px; margin: 0 0 10px 0; }
.msg.user { background: #111827; }
.msg.assistant { background: #0B162B; }
.hdr { color: #94A3B8; font-weight: 600; margin: 0 0 6px 0; }
.content { color: #E5E7EB; }
.content p { margin: 0 0 10px 0; }
.content pre { white-space: pre-wrap; word-break: break-word; background: rgba(255,255,255,0.06); padding: 10px; border-radius: 10px; overflow: hidden; }
");
        sb.AppendLine("</style>");
        sb.AppendLine("</head>");
        sb.AppendLine("<body>");
        sb.AppendLine("<div class=\"chat\">");

        foreach (var message in _messages)
        {
            sb.AppendLine(message.IsUser ? "<div class=\"msg user\">" : "<div class=\"msg assistant\">");
            sb.Append("<div class=\"hdr\">").Append(WebUtility.HtmlEncode(message.Header)).AppendLine("</div>");
            sb.AppendLine("<div class=\"content\">");

            if (message.IsUser)
            {
                var encoded = WebUtility.HtmlEncode(message.RawText ?? "").Replace("\r\n", "\n").Replace("\r", "\n").Replace("\n", "<br/>");
                sb.AppendLine("<div>" + encoded + "</div>");
            }
            else
            {
                var raw = message.RawText ?? "";
                var markdown = HideTagsCheckBox.IsChecked == true ? HelpManual.FilterTagLines(raw) : raw;
                var rendered = Markdig.Markdown.ToHtml(markdown, _markdownPipeline);
                sb.AppendLine(rendered);
            }

            sb.AppendLine("</div>");
            sb.AppendLine("</div>");
        }

        sb.AppendLine("</div>");
        sb.AppendLine("</body>");
        sb.AppendLine("</html>");
        return sb.ToString();
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

        try
        {
            DragMove();
        }
        catch
        {
        }
    }
}
