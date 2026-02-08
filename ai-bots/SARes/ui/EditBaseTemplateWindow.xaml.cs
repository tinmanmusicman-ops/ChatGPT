using System.IO;
using System.Windows;
using System.Windows.Input;
using SARes.engine;
using SARes.ui;

namespace SARes.ui;

public partial class EditBaseTemplateWindow : Window
{
    private AppSettings _updated;
    private readonly string _internalTemplatePath;
    private readonly string _templateName;

    public EditBaseTemplateWindow(AppSettings settings)
    {
        InitializeComponent();
        _updated = settings;

        var templatesDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "SARES",
            "Templates");
        Directory.CreateDirectory(templatesDir);

        _templateName = _updated.GetSelectedBaseTemplateNameOrDefault();
        if (string.IsNullOrWhiteSpace(_templateName))
            _templateName = "Base";

        var fileSegment = SafeFileNames.ToSafeFileSegment(_templateName);
        if (fileSegment.Length == 0)
            fileSegment = "Base";

        _internalTemplatePath = Path.Combine(templatesDir, $"resume_{fileSegment}.md");

        SaveButton.Click += (_, _) => Save();
        CloseButton.Click += CloseWindow_Click;

        LoadIntoInternalAndOpen();
    }

    public AppSettings UpdatedSettings => _updated;

    private void LoadIntoInternalAndOpen()
    {
        try
        {
            // Determine current base template (bundled/external/internal) and copy it into internal storage for editing.
            var assets = new AssetLocator(AppContext.BaseDirectory);
            var currentPath = assets.GetBaseResumeTemplatePath(_updated);

            var md = File.Exists(currentPath) ? File.ReadAllText(currentPath) : "";
            if (md.Length == 0)
                md = "# Resume\n\n";

            File.WriteAllText(_internalTemplatePath, md.TrimEnd() + "\n");
            _updated = _updated.UpsertBaseTemplate(_templateName, _internalTemplatePath) with { BaseResumeTemplatePath = null };
            AppSettingsStore.Save(_updated);

            PathText.Text = $"{_templateName}  |  {_internalTemplatePath}";
            TemplateTextBox.Text = md;
            StatusText.Text = "Ready";
        }
        catch (Exception ex)
        {
            StatusText.Text = "Load failed: " + ex.Message;
        }
    }

    private void Save()
    {
        try
        {
            var content = (TemplateTextBox.Text ?? "").Trim();
            if (content.Length == 0)
            {
                System.Windows.MessageBox.Show("Template text is empty.", "SARes", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            File.WriteAllText(_internalTemplatePath, content.TrimEnd() + "\n");

            _updated = _updated.UpsertBaseTemplate(_templateName, _internalTemplatePath) with { BaseResumeTemplatePath = null };
            AppSettingsStore.Save(_updated);

            StatusText.Text = "Saved.";
        }
        catch (Exception ex)
        {
            StatusText.Text = "Save failed: " + ex.Message;
        }
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

    private void TitleBar_MouseRightButtonUp(object sender, MouseButtonEventArgs e)
    {
        var screenPoint = PointToScreen(e.GetPosition(this));
        SystemCommands.ShowSystemMenu(this, screenPoint);
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

    private void CloseWindow_Click(object sender, RoutedEventArgs e)
    {
        AppLog.Info("Edit template window close button invoked.");
        Close();
        AppLog.Info("Edit template window close requested.");
    }

    private void TitleCloseButton_PreviewMouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        AppLog.Info("Edit template window close button preview mouse down.");
    }
}
