using System.IO;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using Microsoft.Win32;
using SARes.engine;

namespace SARes.ui;

public partial class SelectResumeMarkdownWindow : Window
{
    private string? _selectedFilePath;

    public SelectResumeMarkdownWindow()
    {
        InitializeComponent();
        FilePathTextBox.Text = "";
        StatusText.Text = "Select a Markdown file to import as your base template.";

        MinimizeTitleButton.Click += (_, _) => SystemCommands.MinimizeWindow(this);
        MaximizeTitleButton.Click += (_, _) =>
        {
            if (WindowState == WindowState.Maximized)
            {
                SystemCommands.RestoreWindow(this);
                return;
            }
            SystemCommands.MaximizeWindow(this);
        };
        TitleCloseButton.Click += CloseWindow_Click;
        TitleCloseButton.PreviewMouseLeftButtonDown += (_, _) => AppLog.Info("Select Markdown close button preview mouse down.");

        BrowseButton.Click += (_, _) => BrowseForMarkdown();
        ImportButton.Click += (_, _) => ImportSelectedMarkdown();
        CancelButton.Click += (_, _) => Close();
    }

    public string? SelectedFilePath => _selectedFilePath;

    private void BrowseForMarkdown()
    {
        var dlg = new Microsoft.Win32.OpenFileDialog
        {
            Title = "Select resume Markdown (.md) to store as a base template",
            Filter = "Markdown (*.md)|*.md|All files (*.*)|*.*"
        };
        if (dlg.ShowDialog(this) != true)
            return;

        if (!File.Exists(dlg.FileName))
        {
            StatusText.Text = "Selected file does not exist.";
            return;
        }

        _selectedFilePath = dlg.FileName;
        FilePathTextBox.Text = _selectedFilePath;
        ImportButton.IsEnabled = true;
        StatusText.Text = "Ready to import the selected Markdown file.";
    }

    private void ImportSelectedMarkdown()
    {
        if (string.IsNullOrWhiteSpace(_selectedFilePath) || !File.Exists(_selectedFilePath))
        {
            StatusText.Text = "Select a valid Markdown file first.";
            return;
        }

        DialogResult = true;
        Close();
    }

    private void CloseWindow_Click(object sender, RoutedEventArgs e)
    {
        AppLog.Info("Select Markdown window close button invoked.");
        Close();
        AppLog.Info("Select Markdown window close requested.");
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
        var screenPoint = PointToScreen(e.GetPosition(this));
        SystemCommands.ShowSystemMenu(this, screenPoint);
    }

    private static bool IsClickHandledByChildControl(DependencyObject? source)
    {
        while (source is not null)
        {
            if (source is System.Windows.Controls.Primitives.ButtonBase)
                return true;

            source = VisualTreeHelper.GetParent(source);
        }

        return false;
    }
}
