using System;
using System.Text;
using System.Windows;

namespace SARes.ui;

public partial class AiLogWindow : Window
{
    private readonly StringBuilder _log = new();
    private bool _completed;

    public AiLogWindow()
    {
        InitializeComponent();
        SubtitleText.Text = "Running...";
        StatusText.Text = "Running...";

        CloseButton.Click += (_, _) => Close();

        Closing += (_, e) =>
        {
            if (!_completed)
                e.Cancel = true;
        };
    }

    public void SetSubtitle(string subtitle)
    {
        if (Dispatcher.CheckAccess())
        {
            SubtitleText.Text = subtitle ?? "";
            return;
        }
        _ = Dispatcher.InvokeAsync(() => SubtitleText.Text = subtitle ?? "");
    }

    public void AppendLine(string message)
    {
        if (Dispatcher.CheckAccess())
        {
            AppendLineUi(message);
            return;
        }

        _ = Dispatcher.InvokeAsync(() => AppendLineUi(message));
    }

    public void SetCompleted(string finalStatus)
    {
        if (Dispatcher.CheckAccess())
        {
            SetCompletedUi(finalStatus);
            return;
        }

        _ = Dispatcher.InvokeAsync(() => SetCompletedUi(finalStatus));
    }

    private void AppendLineUi(string message)
    {
        var line = $"{DateTime.Now:HH:mm:ss}  {message}";
        _log.AppendLine(line);
        LogTextBox.Text = _log.ToString();
        LogTextBox.ScrollToEnd();
    }

    private void SetCompletedUi(string finalStatus)
    {
        _completed = true;
        Progress.IsIndeterminate = false;
        Progress.Value = 100;
        StatusText.Text = string.IsNullOrWhiteSpace(finalStatus) ? "Done" : finalStatus;
        CloseButton.IsEnabled = true;
    }
}
