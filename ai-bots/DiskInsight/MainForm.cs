using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using DiskInsight.Monitoring.Ui;

namespace DiskInsight;

internal sealed class MainForm : Form
{
    private enum ContentMode
    {
        None,
        DiskReport,
        RunningProcesses,
        StartupApps,
    }

    private readonly TabControl _tabs;
    private readonly TabPage _outputTab;
    private readonly TabPage _monitoringTab;
    private readonly TextBox _output;
    private readonly ToolStrip _navigationStrip;
    private readonly ToolStripButton _backToDiskSummaryButton;
    private readonly ToolStripMenuItem _viewFontSizeMenu;
    private readonly ToolStripMenuItem _functionsDiskReportMenuItem;
    private readonly ToolStripMenuItem _functionsDiskReportSummaryMenuItem;
    private readonly ToolStripMenuItem _toolsRunningProcessesMenuItem;
    private readonly ToolStripMenuItem _toolsUserStartupAppsMenuItem;
    private readonly ToolStripMenuItem _toolsUserStartupAppsAllMenuItem;
    private readonly IEiCommentaryService _eiCommentaryService;
    private float _outputFontSizePt;
    private Font? _outputFont;
    private Font? _menuFont;
    private bool _hoveringPath;
    private bool _isRunning;
    private ContentMode _contentMode;
    private List<ProcessScanner.ProcessGroupSnapshot>? _processGroupsSnapshot;
    private DiskAnalyzer.ScanResult? _diskScanResult;
    private StartupAppScanner.StartupSnapshot? _startupAppsSnapshot;
    private bool _startupAppsShowAll;
    private readonly Dictionary<int, StartupAppScanner.StartupItem> _startupAppLineToItem = new();
    private bool _showingDiskExtensionDetails;
    private readonly HashSet<string> _expandedExtensions = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<int, string> _extensionLineToExtension = new();
    private readonly HashSet<string> _expandedProcessGroups = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<int, string> _processGroupLineToName = new();
    private readonly Dictionary<int, (string GroupName, ProcessScanner.ProcessInstanceSnapshot Instance)> _processInstanceLineToInstance = new();
    private int _lastContextMenuCharIndex = -1;
    private int _leftMouseDownCharIndex = -1;

    public MainForm(IEiCommentaryService eiCommentaryService)
    {
        _eiCommentaryService = eiCommentaryService;

        Text = "Disk Insight – Review Only";
        StartPosition = FormStartPosition.CenterScreen;
        Width = 900;
        Height = 700;
        MinimizeBox = true;
        MaximizeBox = true;

        _navigationStrip = new ToolStrip { Dock = DockStyle.Top, GripStyle = ToolStripGripStyle.Hidden };
        _backToDiskSummaryButton = new ToolStripButton("Return to Disk Report Summary")
        {
            Enabled = false,
            DisplayStyle = ToolStripItemDisplayStyle.Text,
        };
        _backToDiskSummaryButton.Click += (_, _) => ShowDiskReportSummary();
        _navigationStrip.Items.Add(_backToDiskSummaryButton);

        _output = new TextBox
        {
            Multiline = true,
            ReadOnly = true,
            ScrollBars = ScrollBars.Both,
            Dock = DockStyle.Fill,
            WordWrap = false,
            BackColor = SystemColors.Window,
        };

        var menu = new MenuStrip { Dock = DockStyle.Top };
        _menuFont = new Font(menu.Font.FontFamily, 14f, menu.Font.Style);
        menu.Font = _menuFont;
        var functions = new ToolStripMenuItem("&Functions");
        _functionsDiskReportMenuItem = new ToolStripMenuItem("Disk Report (Read-Only Scan)");
        _functionsDiskReportMenuItem.Click += async (_, _) => await RunDiskReportAsync();
        functions.DropDownItems.Add(_functionsDiskReportMenuItem);
        functions.DropDownItems.Add(new ToolStripSeparator());

        _functionsDiskReportSummaryMenuItem = new ToolStripMenuItem("Disk Report Summary (Last Scan)") { Enabled = false };
        _functionsDiskReportSummaryMenuItem.Click += (_, _) => ShowDiskReportSummary();
        functions.DropDownItems.Add(_functionsDiskReportSummaryMenuItem);

        var tools = new ToolStripMenuItem("&Tools");
        _toolsRunningProcessesMenuItem = new ToolStripMenuItem("Running Processes");
        _toolsRunningProcessesMenuItem.Click += async (_, _) => await RunRunningProcessesAsync();
        tools.DropDownItems.Add(_toolsRunningProcessesMenuItem);
        tools.DropDownItems.Add(new ToolStripSeparator());

        _toolsUserStartupAppsMenuItem = new ToolStripMenuItem("User Startup Apps");
        _toolsUserStartupAppsMenuItem.Click += async (_, _) => await RunUserStartupAppsAsync(showAll: false);
        tools.DropDownItems.Add(_toolsUserStartupAppsMenuItem);

        _toolsUserStartupAppsAllMenuItem = new ToolStripMenuItem("User Startup Apps (All)");
        _toolsUserStartupAppsAllMenuItem.Click += async (_, _) => await RunUserStartupAppsAsync(showAll: true);
        tools.DropDownItems.Add(_toolsUserStartupAppsAllMenuItem);

        var view = new ToolStripMenuItem("&View");

        var increaseFont = CreateFontStepMenuItem("Increase Font Size", +1f);
        increaseFont.ShortcutKeys = Keys.Control | Keys.Oemplus;
        view.DropDownItems.Add(increaseFont);

        var decreaseFont = CreateFontStepMenuItem("Decrease Font Size", -1f);
        decreaseFont.ShortcutKeys = Keys.Control | Keys.OemMinus;
        view.DropDownItems.Add(decreaseFont);
        view.DropDownItems.Add(new ToolStripSeparator());

        _viewFontSizeMenu = new ToolStripMenuItem("Font Size");
        _viewFontSizeMenu.DropDownItems.Add(CreateFontSizeMenuItem(10f));
        _viewFontSizeMenu.DropDownItems.Add(CreateFontSizeMenuItem(12f));
        _viewFontSizeMenu.DropDownItems.Add(CreateFontSizeMenuItem(14f));
        _viewFontSizeMenu.DropDownItems.Add(CreateFontSizeMenuItem(16f));
        _viewFontSizeMenu.DropDownItems.Add(new ToolStripSeparator());
        _viewFontSizeMenu.DropDownItems.Add(CreateFontResetMenuItem());
        view.DropDownItems.Add(_viewFontSizeMenu);

        menu.Items.Add(functions);
        menu.Items.Add(tools);
        menu.Items.Add(view);
        MainMenuStrip = menu;

        _outputTab = new TabPage("Output");
        _outputTab.Controls.Add(_output);
        _outputTab.Controls.Add(_navigationStrip);

        _monitoringTab = new TabPage("Monitoring");
        _monitoringTab.Controls.Add(new MonitoringDashboardTab());

        _tabs = new TabControl
        {
            Dock = DockStyle.Fill,
        };
        _tabs.TabPages.Add(_outputTab);
        _tabs.TabPages.Add(_monitoringTab);

        Controls.Add(_tabs);
        Controls.Add(menu);

        _output.ContextMenuStrip = CreateOutputContextMenu();
        _output.MouseDown += OutputOnMouseDown;
        _output.MouseUp += OutputOnMouseUp;
        _output.MouseMove += OutputOnMouseMove;
        _output.MouseLeave += (_, _) => SetOutputHoverCursor(false);
        _output.MouseDoubleClick += OutputOnMouseDoubleClick;
        _output.KeyDown += OutputOnKeyDown;

        _outputFontSizePt = ClampFontSize(UserSettings.LoadOutputFontSizePt());
        ApplyOutputFont(persist: false);

        _output.Text =
            "Ready.\r\n\r\n" +
            "Use Functions -> Disk Report (Read-Only Scan) to generate the report.\r\n" +
            "Use Tools -> Running Processes to list running processes.\r\n" +
            "Right-click a process group or instance row to Analyze with EI.\r\n";

        UpdateNavigationUi();
    }

    private void OutputOnKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.KeyCode == Keys.Escape && _contentMode == ContentMode.DiskReport && _diskScanResult is not null && _showingDiskExtensionDetails)
        {
            ShowDiskReportSummary();
            e.Handled = true;
            e.SuppressKeyPress = true;
        }
    }

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        if (keyData == Keys.Escape)
        {
            if (_contentMode == ContentMode.DiskReport && _diskScanResult is not null && _showingDiskExtensionDetails)
            {
                ShowDiskReportSummary();
                return true;
            }
        }

        if ((keyData & Keys.Control) == Keys.Control)
        {
            var key = keyData & ~Keys.Control;
            if (key is Keys.Oemplus or Keys.Add)
            {
                AdjustFontSize(+1f);
                return true;
            }

            if (key is Keys.OemMinus or Keys.Subtract)
            {
                AdjustFontSize(-1f);
                return true;
            }

            if (key is Keys.D0 or Keys.NumPad0)
            {
                ResetFontSize();
                return true;
            }
        }

        return base.ProcessCmdKey(ref msg, keyData);
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _outputFont?.Dispose();
            _menuFont?.Dispose();
        }

        base.Dispose(disposing);
    }

    private ToolStripMenuItem CreateFontStepMenuItem(string text, float stepPt)
    {
        var item = new ToolStripMenuItem(text);
        item.Click += (_, _) => AdjustFontSize(stepPt);
        return item;
    }

    private ToolStripMenuItem CreateFontSizeMenuItem(float sizePt)
    {
        var item = new ToolStripMenuItem($"{sizePt.ToString("0", CultureInfo.InvariantCulture)} pt") { Tag = sizePt };
        item.Click += (_, _) => SetFontSize(sizePt);
        return item;
    }

    private ToolStripMenuItem CreateFontResetMenuItem()
    {
        var item = new ToolStripMenuItem("Reset (10 pt)");
        item.Click += (_, _) => ResetFontSize();
        return item;
    }

    private ContextMenuStrip CreateOutputContextMenu()
    {
        var menu = new ContextMenuStrip();

        var analyzeEi = new ToolStripMenuItem("Analyze with EI...");
        analyzeEi.Click += async (_, _) => await AnalyzeSelectionWithEiAsync();

        var stopProcess = new ToolStripMenuItem("Stop Process (Terminate)");
        stopProcess.Click += async (_, _) => await StopSelectedProcessAsync();

        var runScheduledTask = new ToolStripMenuItem("Run Scheduled Task Now");
        runScheduledTask.Click += async (_, _) => await RunSelectedScheduledTaskAsync();

        var enableScheduledTask = new ToolStripMenuItem("Enable Scheduled Task");
        enableScheduledTask.Click += async (_, _) => await SetSelectedScheduledTaskEnabledAsync(enabled: true);

        var disableScheduledTask = new ToolStripMenuItem("Disable Scheduled Task");
        disableScheduledTask.Click += async (_, _) => await SetSelectedScheduledTaskEnabledAsync(enabled: false);

        var backToDiskSummary = new ToolStripMenuItem("Back to Disk Report Summary");
        backToDiskSummary.Click += (_, _) =>
        {
            if (_diskScanResult is null)
            {
                MessageBox.Show(this, "Run Functions -> Disk Report (Read-Only Scan) first.", "Disk Report", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            ShowDiskReportSummary();
        };

        var extensionDetails = new ToolStripMenuItem("Show Extension Details");
        extensionDetails.Click += (_, _) =>
        {
            var charIndex = _output.SelectionLength > 0 ? _output.SelectionStart : GetContextCharIndex();
            if (_diskScanResult is null)
            {
                MessageBox.Show(this, "Run Functions -> Disk Report (Read-Only Scan) first.", "Extension Details", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            if (!TryGetExtensionSummaryAtCharIndex(charIndex, out var ext, out _, out _, out _))
            {
                MessageBox.Show(this, "Select a file-extension summary row first.", "Extension Details", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            ShowExtensionDetailsReport(ext);
        };

        var openPath = new ToolStripMenuItem("Open in Explorer");
        openPath.Click += (_, _) =>
        {
            if (TryGetPathAtCharIndex(GetContextCharIndex(), out var path))
            {
                OpenPathInExplorer(path);
            }
        };

        var openContainingFolder = new ToolStripMenuItem("Open Containing Folder");
        openContainingFolder.Click += (_, _) =>
        {
            if (TryGetPathAtCharIndex(GetContextCharIndex(), out var path))
            {
                OpenContainingFolderInExplorer(path);
            }
        };

        menu.Opening += (_, e) =>
        {
            var charIndex = _output.SelectionStart;

            // Use the current mouse position for right-click context actions so enablement follows the clicked line.
            try
            {
                // If there's an explicit selection (row), prefer it.
                if (_output.SelectionLength == 0)
                {
                    var client = _output.PointToClient(Control.MousePosition);
                    var mouseCharIndex = _output.GetCharIndexFromPosition(client);
                    if (mouseCharIndex >= 0 && mouseCharIndex < _output.TextLength)
                    {
                        charIndex = mouseCharIndex;
                    }
                }
            }
            catch
            {
            }

            if (_lastContextMenuCharIndex >= 0 && _lastContextMenuCharIndex < _output.TextLength)
            {
                // If a row is selected, keep using it; otherwise use the last right-click position.
                if (_output.SelectionLength == 0)
                {
                    charIndex = _lastContextMenuCharIndex;
                }
            }
            _lastContextMenuCharIndex = charIndex;

            analyzeEi.Visible = true;
            analyzeEi.Enabled = true;

            stopProcess.Visible = _contentMode == ContentMode.RunningProcesses;
            stopProcess.Enabled = _contentMode == ContentMode.RunningProcesses &&
                                  TryGetProcessInstanceAtCharIndex(charIndex, out var ignoredGroupName, out var instance) &&
                                  instance.Pid is not null;

            var canManageTask = _contentMode == ContentMode.StartupApps &&
                                TryGetStartupAppAtCharIndex(charIndex, out var startupItem) &&
                                IsTaskSchedulerItem(startupItem);

            runScheduledTask.Visible = _contentMode == ContentMode.StartupApps;
            enableScheduledTask.Visible = _contentMode == ContentMode.StartupApps;
            disableScheduledTask.Visible = _contentMode == ContentMode.StartupApps;

            runScheduledTask.Enabled = canManageTask;
            enableScheduledTask.Enabled = canManageTask;
            disableScheduledTask.Enabled = canManageTask;

            backToDiskSummary.Visible = _contentMode == ContentMode.DiskReport;
            backToDiskSummary.Enabled = _contentMode == ContentMode.DiskReport && _diskScanResult is not null;

            extensionDetails.Visible = _contentMode == ContentMode.DiskReport;
            extensionDetails.Enabled = _contentMode == ContentMode.DiskReport && !_showingDiskExtensionDetails;

            var enabled = TryGetPathAtCharIndex(charIndex, out var path) && CanOpenPath(path);
            openPath.Enabled = enabled;
            openContainingFolder.Enabled = enabled;
            if (!enabled)
            {
                e.Cancel = false;
            }
        };

        menu.Items.Add(analyzeEi);
        menu.Items.Add(stopProcess);
        menu.Items.Add(runScheduledTask);
        menu.Items.Add(enableScheduledTask);
        menu.Items.Add(disableScheduledTask);
        menu.Items.Add(backToDiskSummary);
        menu.Items.Add(extensionDetails);
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(openPath);
        menu.Items.Add(openContainingFolder);
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Increase Font Size", null, (_, _) => AdjustFontSize(+1f));
        menu.Items.Add("Decrease Font Size", null, (_, _) => AdjustFontSize(-1f));
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Reset Font Size", null, (_, _) => ResetFontSize());
        return menu;
    }

    private static bool IsTaskSchedulerItem(StartupAppScanner.StartupItem item)
    {
        return string.Equals(item.Source, "Task Scheduler", StringComparison.OrdinalIgnoreCase) &&
               !string.IsNullOrWhiteSpace(item.LocationHint) &&
               item.LocationHint.TrimStart().StartsWith("\\", StringComparison.Ordinal);
    }

    private bool TryGetStartupAppAtCharIndex(int charIndex, out StartupAppScanner.StartupItem item)
    {
        item = default!;
        if (_contentMode != ContentMode.StartupApps)
        {
            return false;
        }

        if (charIndex < 0 || charIndex >= _output.TextLength)
        {
            return false;
        }

        var lineIndex = _output.GetLineFromCharIndex(charIndex);
        if (lineIndex < 0)
        {
            return false;
        }

        if (!_startupAppLineToItem.TryGetValue(lineIndex, out var found) || found is null)
        {
            return false;
        }

        item = found;
        return true;
    }

    private bool TryGetSelectedStartupApp(out StartupAppScanner.StartupItem item)
    {
        item = default!;
        var charIndex = _output.SelectionLength > 0 ? _output.SelectionStart : GetContextCharIndex();
        return TryGetStartupAppAtCharIndex(charIndex, out item);
    }

    private static string? GetSchtasksTaskName(StartupAppScanner.StartupItem item)
    {
        return IsTaskSchedulerItem(item) ? item.LocationHint?.Trim() : null;
    }

    private async Task RunSelectedScheduledTaskAsync()
    {
        if (!TryGetSelectedStartupApp(out var item) || !IsTaskSchedulerItem(item))
        {
            MessageBox.Show(this, "Select a Task Scheduler entry first.", "Scheduled Task", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }

        var taskName = GetSchtasksTaskName(item);
        if (string.IsNullOrWhiteSpace(taskName))
        {
            MessageBox.Show(this, "Unable to determine scheduled task path.", "Scheduled Task", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        var confirm = MessageBox.Show(
            this,
            $"Run scheduled task now?\r\n\r\n{taskName}",
            "Confirm Run Scheduled Task",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Warning,
            MessageBoxDefaultButton.Button2);

        if (confirm != DialogResult.Yes)
        {
            return;
        }

        await RunSchtasksAsync($"/Run /TN \"{taskName}\"", actionLabel: "Run");
        await RefreshStartupAppsAsync();
    }

    private async Task SetSelectedScheduledTaskEnabledAsync(bool enabled)
    {
        if (!TryGetSelectedStartupApp(out var item) || !IsTaskSchedulerItem(item))
        {
            MessageBox.Show(this, "Select a Task Scheduler entry first.", "Scheduled Task", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }

        var taskName = GetSchtasksTaskName(item);
        if (string.IsNullOrWhiteSpace(taskName))
        {
            MessageBox.Show(this, "Unable to determine scheduled task path.", "Scheduled Task", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        var confirm = MessageBox.Show(
            this,
            $"{(enabled ? "Enable" : "Disable")} scheduled task?\r\n\r\n{taskName}",
            "Confirm Scheduled Task Change",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Warning,
            MessageBoxDefaultButton.Button2);

        if (confirm != DialogResult.Yes)
        {
            return;
        }

        var switchArg = enabled ? "/ENABLE" : "/DISABLE";
        await RunSchtasksAsync($"/Change /TN \"{taskName}\" {switchArg}", actionLabel: enabled ? "Enable" : "Disable");
        await RefreshStartupAppsAsync();
    }

    private async Task RefreshStartupAppsAsync()
    {
        if (_contentMode != ContentMode.StartupApps)
        {
            return;
        }

        try
        {
            var snapshot = await Task.Run(StartupAppScanner.GetCurrentUserStartupItemsSnapshot);
            _startupAppsSnapshot = snapshot;
            RenderStartupAppsReport(snapshot, filtered: !_startupAppsShowAll, resetScrollToTop: false);
        }
        catch
        {
        }
    }

    private async Task RunSchtasksAsync(string args, string actionLabel)
    {
        Cursor = Cursors.WaitCursor;
        try
        {
            var result = await Task.Run(() => RunProcessWithOutput("schtasks.exe", args, timeoutMs: 10_000));
            if (result.ExitCode != 0)
            {
                MessageBox.Show(
                    this,
                    $"{actionLabel} failed.\r\n\r\nExit code: {result.ExitCode}\r\n\r\n{result.StdErr}".Trim(),
                    "Scheduled Task",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
                return;
            }

            var detail = string.IsNullOrWhiteSpace(result.StdOut) ? "OK." : result.StdOut.Trim();
            MessageBox.Show(this, detail, "Scheduled Task", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        finally
        {
            Cursor = Cursors.Default;
        }
    }

    private readonly record struct ProcessResult(int ExitCode, string StdOut, string StdErr);

    private static ProcessResult RunProcessWithOutput(string fileName, string arguments, int timeoutMs)
    {
        using var process = new Process
        {
            StartInfo = new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true,
            }
        };

        process.Start();
        var stdout = process.StandardOutput.ReadToEnd();
        var stderr = process.StandardError.ReadToEnd();
        if (!process.WaitForExit(timeoutMs))
        {
            try
            {
                process.Kill(entireProcessTree: true);
            }
            catch
            {
            }
            return new ProcessResult(ExitCode: -1, StdOut: stdout, StdErr: "Timed out waiting for schtasks.exe.");
        }

        return new ProcessResult(process.ExitCode, stdout, stderr);
    }

    private void UpdateNavigationUi()
    {
        _backToDiskSummaryButton.Enabled = _contentMode == ContentMode.DiskReport && _diskScanResult is not null && _showingDiskExtensionDetails;
    }

    private const int EM_GETFIRSTVISIBLELINE = 0x00CE;
    private const int EM_LINESCROLL = 0x00B6;

    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    private static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, IntPtr lParam);

    private int GetFirstVisibleLineSafe()
    {
        try
        {
            if (!_output.IsHandleCreated)
            {
                return 0;
            }

            return (int)SendMessage(_output.Handle, EM_GETFIRSTVISIBLELINE, IntPtr.Zero, IntPtr.Zero);
        }
        catch
        {
            return 0;
        }
    }

    private void SetFirstVisibleLineSafe(int targetFirstLine)
    {
        try
        {
            if (!_output.IsHandleCreated)
            {
                return;
            }

            var current = GetFirstVisibleLineSafe();
            var delta = targetFirstLine - current;
            if (delta == 0)
            {
                return;
            }

            SendMessage(_output.Handle, EM_LINESCROLL, IntPtr.Zero, (IntPtr)delta);
        }
        catch
        {
        }
    }

    private (int FirstVisibleLine, int SelectionStart, int SelectionLength) CaptureOutputViewState()
        => (GetFirstVisibleLineSafe(), _output.SelectionStart, _output.SelectionLength);

    private void RestoreOutputViewState((int FirstVisibleLine, int SelectionStart, int SelectionLength) state)
    {
        try
        {
            var start = Math.Clamp(state.SelectionStart, 0, Math.Max(0, _output.TextLength));
            var length = Math.Clamp(state.SelectionLength, 0, Math.Max(0, _output.TextLength - start));
            _output.SelectionStart = start;
            _output.SelectionLength = length;
        }
        catch
        {
        }

        SetFirstVisibleLineSafe(Math.Max(0, state.FirstVisibleLine));
    }

    private bool TryGetDiskExtensionGroupAtCharIndex(int charIndex, out string extension)
    {
        extension = string.Empty;
        if (_contentMode != ContentMode.DiskReport || _diskScanResult is null || _showingDiskExtensionDetails)
        {
            return false;
        }

        if (charIndex < 0 || charIndex >= _output.TextLength)
        {
            return false;
        }

        var lineIndex = _output.GetLineFromCharIndex(charIndex);
        if (!_extensionLineToExtension.TryGetValue(lineIndex, out var ext) || string.IsNullOrWhiteSpace(ext))
        {
            return false;
        }

        extension = ext;
        return true;
    }

    private void ToggleDiskExtensionGroup(string extension)
    {
        if (_diskScanResult is null)
        {
            return;
        }

        var firstVisibleLine = GetFirstVisibleLineSafe();
        if (_expandedExtensions.Contains(extension))
        {
            _expandedExtensions.Remove(extension);
        }
        else
        {
            _expandedExtensions.Add(extension);
        }

        RenderDiskReport(resetScrollToTop: false);
        TrySelectExtensionLine(extension);
        SetFirstVisibleLineSafe(firstVisibleLine);
    }

    private void TrySelectExtensionLine(string extension)
    {
        try
        {
            foreach (var kvp in _extensionLineToExtension)
            {
                if (!string.Equals(kvp.Value, extension, StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                var lineStart = _output.GetFirstCharIndexFromLine(kvp.Key);
                if (lineStart < 0)
                {
                    return;
                }

                _output.SelectionStart = lineStart;
                _output.SelectionLength = _output.Lines[kvp.Key].Length;
                return;
            }
        }
        catch
        {
        }
    }

    private void AdjustFontSize(float deltaPt) => SetFontSize(_outputFontSizePt + deltaPt);

    private void ResetFontSize() => SetFontSize(10f);

    private void SetFontSize(float sizePt)
    {
        var clamped = ClampFontSize(sizePt);
        if (Math.Abs(_outputFontSizePt - clamped) < 0.01f)
        {
            UpdateFontSizeMenuChecks();
            return;
        }

        _outputFontSizePt = clamped;
        ApplyOutputFont(persist: true);
    }

    private void ApplyOutputFont(bool persist)
    {
        var newFont = new Font("Consolas", _outputFontSizePt);
        _output.Font = newFont;

        _outputFont?.Dispose();
        _outputFont = newFont;

        if (persist)
        {
            UserSettings.SaveOutputFontSizePt(_outputFontSizePt);
        }

        UpdateFontSizeMenuChecks();
    }

    private void UpdateFontSizeMenuChecks()
    {
        foreach (var item in _viewFontSizeMenu.DropDownItems)
        {
            if (item is not ToolStripMenuItem menuItem || menuItem.Tag is not float sizePt)
            {
                continue;
            }

            menuItem.Checked = Math.Abs(sizePt - _outputFontSizePt) < 0.01f;
        }
    }

    private static float ClampFontSize(float sizePt) => Math.Clamp(sizePt, 8f, 28f);

    private void OutputOnMouseDown(object? sender, MouseEventArgs e)
    {
        if (e.Button == MouseButtons.Left)
        {
            _leftMouseDownCharIndex = _output.GetCharIndexFromPosition(e.Location);
        }

        if (e.Button == MouseButtons.Right)
        {
            var clickCharIndex = _output.GetCharIndexFromPosition(e.Location);
            if (clickCharIndex < 0 || clickCharIndex >= _output.TextLength)
            {
                return;
            }

            // If a row is already selected and the click is on the same line, keep the selection for actions.
            if (_output.SelectionLength > 0)
            {
                try
                {
                    var selectionLine = _output.GetLineFromCharIndex(_output.SelectionStart);
                    var clickLine = _output.GetLineFromCharIndex(clickCharIndex);
                    if (selectionLine == clickLine)
                    {
                        _lastContextMenuCharIndex = _output.SelectionStart;
                        return;
                    }
                }
                catch
                {
                }
            }

            _lastContextMenuCharIndex = clickCharIndex;
            TrySelectLineAtCharIndex(clickCharIndex);
        }
    }

    private void OutputOnMouseUp(object? sender, MouseEventArgs e)
    {
        if (e.Button != MouseButtons.Left)
        {
            return;
        }

        // If the user dragged to select text, don't override it.
        var mouseUpCharIndex = _output.GetCharIndexFromPosition(e.Location);
        if (_output.SelectionLength > 0 || mouseUpCharIndex != _leftMouseDownCharIndex)
        {
            return;
        }

        TrySelectLineAtCharIndex(mouseUpCharIndex);
    }

    private void TrySelectLineAtCharIndex(int charIndex)
    {
        if (charIndex < 0 || charIndex >= _output.TextLength)
        {
            return;
        }

        var lineIndex = _output.GetLineFromCharIndex(charIndex);
        if (lineIndex < 0)
        {
            return;
        }

        var lineStart = _output.GetFirstCharIndexFromLine(lineIndex);
        if (lineStart < 0)
        {
            return;
        }

        var lines = _output.Lines;
        if (lineIndex >= lines.Length)
        {
            return;
        }

        var lineLength = lines[lineIndex].Length;
        _output.SelectionStart = lineStart;
        _output.SelectionLength = lineLength;
    }

    private int GetContextCharIndex()
    {
        if (_lastContextMenuCharIndex >= 0 && _lastContextMenuCharIndex < _output.TextLength)
        {
            return _lastContextMenuCharIndex;
        }

        return _output.SelectionStart;
    }

    private void OutputOnMouseMove(object? sender, MouseEventArgs e)
    {
        var charIndex = _output.GetCharIndexFromPosition(e.Location);
        SetOutputHoverCursor(
            TryGetProcessGroupAtCharIndex(charIndex, out _) ||
            TryGetPathAtCharIndex(charIndex, out _) ||
            TryGetDiskExtensionGroupAtCharIndex(charIndex, out _));
    }

    private void SetOutputHoverCursor(bool hovering)
    {
        if (_hoveringPath == hovering)
        {
            return;
        }

        _hoveringPath = hovering;
        _output.Cursor = hovering ? Cursors.Hand : Cursors.IBeam;
    }

    private void OutputOnMouseDoubleClick(object? sender, MouseEventArgs e)
    {
        if (e.Button != MouseButtons.Left)
        {
            return;
        }

        var charIndex = _output.GetCharIndexFromPosition(e.Location);
        if (TryGetDiskExtensionGroupAtCharIndex(charIndex, out var ext))
        {
            ToggleDiskExtensionGroup(ext);
            return;
        }

        if (TryGetProcessGroupAtCharIndex(charIndex, out var groupName))
        {
            ToggleProcessGroup(groupName);
            return;
        }

        if (TryGetPathAtCharIndex(charIndex, out var path) && CanOpenPath(path))
        {
            OpenPathInExplorer(path);
        }
    }

    private bool TryGetPathAtCharIndex(int charIndex, out string path)
    {
        path = string.Empty;
        if (charIndex < 0 || charIndex >= _output.TextLength)
        {
            return false;
        }

        var lineIndex = _output.GetLineFromCharIndex(charIndex);
        var lines = _output.Lines;
        if (lineIndex < 0 || lineIndex >= lines.Length)
        {
            return false;
        }

        var lineText = lines[lineIndex];
        var pathStartInLine = FindDriveRootIndex(lineText);
        if (pathStartInLine < 0)
        {
            return false;
        }

        var firstCharIndex = _output.GetFirstCharIndexFromLine(lineIndex);
        var column = charIndex - firstCharIndex;
        if (column < pathStartInLine)
        {
            return false;
        }

        var candidate = lineText[pathStartInLine..].Trim();
        candidate = candidate.TrimEnd(')', '.', ',', ';', ':');
        candidate = candidate.Trim().Trim('"');

        if (candidate.Length < 3)
        {
            return false;
        }

        path = candidate;
        return true;
    }

    private static int FindDriveRootIndex(string line)
    {
        for (var i = 0; i < line.Length - 2; i++)
        {
            if (char.IsLetter(line[i]) && line[i + 1] == ':' && line[i + 2] == '\\')
            {
                return i;
            }
        }

        return -1;
    }

    private static bool CanOpenPath(string path)
    {
        if (File.Exists(path) || Directory.Exists(path))
        {
            return true;
        }

        try
        {
            var directory = Path.GetDirectoryName(path);
            return !string.IsNullOrWhiteSpace(directory) && Directory.Exists(directory);
        }
        catch
        {
            return false;
        }
    }

    private static void OpenPathInExplorer(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{path}\"") { UseShellExecute = true });
                return;
            }

            if (Directory.Exists(path))
            {
                Process.Start(new ProcessStartInfo("explorer.exe", $"\"{path}\"") { UseShellExecute = true });
                return;
            }

            OpenContainingFolderInExplorer(path);
        }
        catch
        {
        }
    }

    private static void OpenContainingFolderInExplorer(string path)
    {
        try
        {
            var folder = Directory.Exists(path) ? path : Path.GetDirectoryName(path);
            if (string.IsNullOrWhiteSpace(folder) || !Directory.Exists(folder))
            {
                return;
            }

            Process.Start(new ProcessStartInfo("explorer.exe", $"\"{folder}\"") { UseShellExecute = true });
        }
        catch
        {
        }
    }

    private void ShowDiskReportSummary()
    {
        if (_diskScanResult is null)
        {
            return;
        }

        _expandedExtensions.Clear();
        _showingDiskExtensionDetails = false;
        _functionsDiskReportSummaryMenuItem.Enabled = true;
        UpdateNavigationUi();
        RenderDiskReport(resetScrollToTop: true);
    }

    private void ShowExtensionDetailsReport(string extension)
    {
        if (_diskScanResult is null)
        {
            return;
        }

        var details = DiskAnalyzer.BuildExtensionDetailsReport(_diskScanResult, extension);
        _output.Text = "Tip: Press Esc (or right-click) to return to Disk Report Summary.\r\n\r\n" + details;
        _output.SelectionStart = 0;
        _output.SelectionLength = 0;
        _contentMode = ContentMode.DiskReport;
        _showingDiskExtensionDetails = true;
        _functionsDiskReportSummaryMenuItem.Enabled = true;
        UpdateNavigationUi();
        _extensionLineToExtension.Clear();
    }

    private async Task RunDiskReportAsync()
    {
        if (_isRunning)
        {
            return;
        }

        _isRunning = true;
        _functionsDiskReportMenuItem.Enabled = false;
        _toolsRunningProcessesMenuItem.Enabled = false;
        Cursor = Cursors.WaitCursor;

        try
        {
            _contentMode = ContentMode.None;
            _processGroupsSnapshot = null;
            _expandedProcessGroups.Clear();
            _processGroupLineToName.Clear();
            _processInstanceLineToInstance.Clear();
            _diskScanResult = null;
            _showingDiskExtensionDetails = false;
            _expandedExtensions.Clear();
            _extensionLineToExtension.Clear();
            _functionsDiskReportSummaryMenuItem.Enabled = false;
            UpdateNavigationUi();

            _output.Text = "Scanning (read-only)...\r\nThis may take a moment.\r\n";
            _diskScanResult = await Task.Run(DiskAnalyzer.BuildScanResult);
            _contentMode = ContentMode.DiskReport;
            _processGroupsSnapshot = null;
            _expandedProcessGroups.Clear();
            _processGroupLineToName.Clear();
            _processInstanceLineToInstance.Clear();
            _showingDiskExtensionDetails = false;
            _expandedExtensions.Clear();
            _functionsDiskReportSummaryMenuItem.Enabled = true;
            UpdateNavigationUi();
            RenderDiskReport(resetScrollToTop: true);
        }
        catch (Exception ex)
        {
            _output.Text = "Disk Insight failed unexpectedly.\r\n\r\n" + ex;
        }
        finally
        {
            Cursor = Cursors.Default;
            _functionsDiskReportMenuItem.Enabled = true;
            _toolsRunningProcessesMenuItem.Enabled = true;
            _isRunning = false;
        }
    }

    private async Task RunRunningProcessesAsync()
    {
        if (_isRunning)
        {
            return;
        }

        _isRunning = true;
        _functionsDiskReportMenuItem.Enabled = false;
        _toolsRunningProcessesMenuItem.Enabled = false;
        _toolsUserStartupAppsMenuItem.Enabled = false;
        _toolsUserStartupAppsAllMenuItem.Enabled = false;
        Cursor = Cursors.WaitCursor;

        try
        {
            _contentMode = ContentMode.None;
            _processGroupsSnapshot = null;
            _expandedProcessGroups.Clear();
            _processGroupLineToName.Clear();
            _processInstanceLineToInstance.Clear();
            _diskScanResult = null;
            _showingDiskExtensionDetails = false;
            _expandedExtensions.Clear();
            _extensionLineToExtension.Clear();
            _functionsDiskReportSummaryMenuItem.Enabled = false;
            UpdateNavigationUi();

            _output.Text = "Enumerating running processes...\r\n";
            _processGroupsSnapshot = await Task.Run(ProcessScanner.GetGroupedSnapshot);
            _expandedProcessGroups.Clear();
            _contentMode = ContentMode.RunningProcesses;
            _diskScanResult = null;
            UpdateNavigationUi();
            RenderProcessGroups(resetScrollToTop: true);
        }
        catch (Exception ex)
        {
            _output.Text = "Running Processes failed unexpectedly.\r\n\r\n" + ex;
        }
        finally
        {
            Cursor = Cursors.Default;
            _functionsDiskReportMenuItem.Enabled = true;
            _toolsRunningProcessesMenuItem.Enabled = true;
            _toolsUserStartupAppsMenuItem.Enabled = true;
            _toolsUserStartupAppsAllMenuItem.Enabled = true;
            _isRunning = false;
        }
    }

    private async Task RunUserStartupAppsAsync(bool showAll)
    {
        if (_isRunning)
        {
            return;
        }

        _isRunning = true;
        _functionsDiskReportMenuItem.Enabled = false;
        _toolsRunningProcessesMenuItem.Enabled = false;
        _toolsUserStartupAppsMenuItem.Enabled = false;
        _toolsUserStartupAppsAllMenuItem.Enabled = false;
        Cursor = Cursors.WaitCursor;

        try
        {
            _contentMode = ContentMode.None;
            _processGroupsSnapshot = null;
            _expandedProcessGroups.Clear();
            _processGroupLineToName.Clear();
            _processInstanceLineToInstance.Clear();
            _diskScanResult = null;
            _startupAppsSnapshot = null;
            _startupAppsShowAll = showAll;
            _startupAppLineToItem.Clear();
            _showingDiskExtensionDetails = false;
            _expandedExtensions.Clear();
            _extensionLineToExtension.Clear();
            _functionsDiskReportSummaryMenuItem.Enabled = false;
            UpdateNavigationUi();

            _output.Text = "Reading current-user startup entries...\r\n";
            var snapshot = await Task.Run(StartupAppScanner.GetCurrentUserStartupItemsSnapshot);
            _startupAppsSnapshot = snapshot;
            _contentMode = ContentMode.StartupApps;
            RenderStartupAppsReport(snapshot, filtered: !showAll, resetScrollToTop: true);
            UpdateNavigationUi();
        }
        catch (Exception ex)
        {
            _output.Text = "User Startup Apps failed unexpectedly.\r\n\r\n" + ex;
        }
        finally
        {
            Cursor = Cursors.Default;
            _functionsDiskReportMenuItem.Enabled = true;
            _toolsRunningProcessesMenuItem.Enabled = true;
            _toolsUserStartupAppsMenuItem.Enabled = true;
            _toolsUserStartupAppsAllMenuItem.Enabled = true;
            _isRunning = false;
        }
    }

    private static string TrimTo(string value, int maxLen)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return string.Empty;
        }

        var v = value.Trim();
        if (v.Length <= maxLen)
        {
            return v;
        }

        return v[..Math.Max(0, maxLen - 1)] + "...";
    }

    private void RenderStartupAppsReport(StartupAppScanner.StartupSnapshot snapshot, bool filtered, bool resetScrollToTop)
    {
        var viewState = resetScrollToTop ? default : CaptureOutputViewState();

        _startupAppLineToItem.Clear();
        var items = filtered ? snapshot.Filtered : snapshot.All;

        var report = new StringBuilder(capacity: 16_384);
        var lineIndex = 0;

        report.AppendLine(filtered ? "Startup Apps (Filtered)" : "Startup Apps (All)");
        lineIndex++;
        report.AppendLine();
        lineIndex++;
        report.AppendLine($"Total startup entries found: {snapshot.All.Count.ToString(CultureInfo.InvariantCulture)}");
        lineIndex++;
        report.AppendLine($"Matches shown: {items.Count.ToString(CultureInfo.InvariantCulture)}");
        lineIndex++;

        if (filtered)
        {
            report.AppendLine();
            lineIndex++;
            report.AppendLine("Filter: command contains C:\\ChatGPT (or C:/ChatGPT) OR launches Python (python/py/pythonw) OR task description equals HSST.");
            lineIndex++;
        }

        report.AppendLine();
        lineIndex++;

        if (filtered && items.Count == 0)
        {
            report.AppendLine("(No matching startup items were found.)");
            lineIndex++;
            report.AppendLine("Tip: Use Tools -> User Startup Apps (All) to see everything this scanner found.");
            lineIndex++;
            report.AppendLine();
            lineIndex++;
        }

        report.AppendLine($"  {"Enabled",7}  {"Source",-18}  Name");
        lineIndex++;
        report.AppendLine();
        lineIndex++;

        foreach (var item in items)
        {
            var enabled = item.Enabled switch
            {
                true => "Yes",
                false => "No",
                null => "n/a",
            };

            _startupAppLineToItem[lineIndex] = item;
            report.AppendLine($"  {enabled,7}  {TrimTo(item.Source, 18),-18}  {item.Name}");
            lineIndex++;

            _startupAppLineToItem[lineIndex] = item;
            report.AppendLine($"           Command: {item.Command}");
            lineIndex++;

            if (!string.IsNullOrWhiteSpace(item.Description))
            {
                _startupAppLineToItem[lineIndex] = item;
                report.AppendLine($"       Description: {item.Description}");
                lineIndex++;
            }

            if (!string.IsNullOrWhiteSpace(item.LocationHint))
            {
                _startupAppLineToItem[lineIndex] = item;
                report.AppendLine($"           Location: {item.LocationHint}");
                lineIndex++;
            }

            report.AppendLine();
            lineIndex++;
        }

        _output.Text = report.ToString();
        if (resetScrollToTop)
        {
            _output.SelectionStart = 0;
            _output.SelectionLength = 0;
            SetFirstVisibleLineSafe(0);
        }
        else
        {
            RestoreOutputViewState(viewState);
        }
    }

    private void RenderProcessGroups(bool resetScrollToTop)
    {
        if (_processGroupsSnapshot is null)
        {
            return;
        }

        var viewState = resetScrollToTop ? default : CaptureOutputViewState();

        _processGroupLineToName.Clear();
        _processInstanceLineToInstance.Clear();
        var report = new StringBuilder(capacity: 32_768);
        var lineIndex = 0;

        report.AppendLine("Running Processes (grouped by name)");
        lineIndex++;
        report.AppendLine();
        lineIndex++;
        report.AppendLine("Double-click a group to expand/collapse.");
        lineIndex++;
        report.AppendLine();
        lineIndex++;

        report.AppendLine($"  {"Total(MB)",9}  {"CPU(%)",6}  {"Count",5}  Name");
        lineIndex++;

        foreach (var group in _processGroupsSnapshot)
        {
            var expanded = _expandedProcessGroups.Contains(group.Name);
            var marker = expanded ? "[-]" : "[+]";
            var totalMb = ProcessScanner.FormatWorkingSetMb(group.TotalWorkingSetBytes);
            var totalCpu = ProcessScanner.FormatCpuUsagePercentOrNa(group.TotalCpuUsagePercent);

            _processGroupLineToName[lineIndex] = group.Name;
            report.AppendLine($"{marker} {totalMb,9}  {totalCpu,6}  {group.InstanceCount,5}  {group.DisplayName}");
            lineIndex++;

            if (!expanded)
            {
                continue;
            }

            report.AppendLine($"      {"PID",7}  {"WS(MB)",8}  {"CPU(%)",6}  {"CPU Time",12}  {"Start Time",19}");
            lineIndex++;

            foreach (var instance in group.Instances)
            {
                var pid = instance.Pid?.ToString(CultureInfo.InvariantCulture) ?? "n/a";
                var ws = instance.WorkingSetBytes is { } bytes ? ProcessScanner.FormatWorkingSetMb(bytes) : "n/a";
                var cpuUsage = ProcessScanner.FormatCpuUsagePercentOrNa(instance.CpuUsagePercent);
                var cpu = ProcessScanner.FormatCpuTimeOrNa(instance.TotalCpuTime);
                var start = ProcessScanner.FormatStartTimeOrNa(instance.StartTime);
                _processInstanceLineToInstance[lineIndex] = (group.Name, instance);
                report.AppendLine($"      {pid,7}  {ws,8}  {cpuUsage,6}  {cpu,12}  {start,19}");
                lineIndex++;
            }
        }

        _output.Text = report.ToString();
        if (resetScrollToTop)
        {
            _output.SelectionStart = 0;
            _output.SelectionLength = 0;
            SetFirstVisibleLineSafe(0);
        }
        else
        {
            RestoreOutputViewState(viewState);
        }
    }

    private void RenderDiskReport(bool resetScrollToTop)
    {
        if (_diskScanResult is null)
        {
            return;
        }

        var viewState = resetScrollToTop ? default : CaptureOutputViewState();

        _contentMode = ContentMode.DiskReport;
        _processGroupsSnapshot = null;
        _expandedProcessGroups.Clear();
        _processGroupLineToName.Clear();
        _processInstanceLineToInstance.Clear();
        _extensionLineToExtension.Clear();

        var full = DiskAnalyzer.BuildReport(_diskScanResult);
        var header = "File-Type Summary (by extension, scanned folders only)";
        var idx = full.IndexOf(header, StringComparison.Ordinal);
        if (idx < 0)
        {
            _output.Text = full;
            if (resetScrollToTop)
            {
                _output.SelectionStart = 0;
                _output.SelectionLength = 0;
                SetFirstVisibleLineSafe(0);
            }

            var fallbackLines = _output.Lines;
            for (var i = 0; i < fallbackLines.Length; i++)
            {
                if (TryParseExtensionSummaryLine(fallbackLines[i], out var ext, out _, out _, out _))
                {
                    _extensionLineToExtension[i] = ext;
                }
            }

            if (!resetScrollToTop)
            {
                RestoreOutputViewState(viewState);
            }
            return;
        }

        var prefix = full[..idx];

        var report = new StringBuilder(full.Length + 16_384);
        report.Append(prefix);
        if (prefix.Length > 0 && !prefix.EndsWith("\r\n", StringComparison.Ordinal))
        {
            report.AppendLine();
        }

        report.AppendLine(header);
        report.AppendLine();
        report.AppendLine("Double-click a file type row to expand/collapse.");
        report.AppendLine();

        if (_diskScanResult.StatsByExtension.Count == 0)
        {
            report.AppendLine("  (No files found in the scan scope.)");
        }
        else
        {
            foreach (var (ext, stats) in _diskScanResult.StatsByExtension
                         .OrderByDescending(kv => kv.Value.TotalBytes)
                         .ThenBy(kv => kv.Key, StringComparer.OrdinalIgnoreCase))
            {
                var expanded = _expandedExtensions.Contains(ext);
                var marker = expanded ? "[-]" : "[+]";
                report.AppendLine($"{marker} {FormatGb(stats.TotalBytes),10}  {stats.FileCount,8} files  {stats.FolderCount,6} folders  {ext}");

                if (expanded)
                {
                    AppendExtensionInlineDetails(report, ext);
                }
            }
        }

        _output.Text = report.ToString();
        if (resetScrollToTop)
        {
            _output.SelectionStart = 0;
            _output.SelectionLength = 0;
            SetFirstVisibleLineSafe(0);
        }

        var lines = _output.Lines;
        for (var i = 0; i < lines.Length; i++)
        {
            if (TryParseExtensionSummaryLine(lines[i], out var ext, out _, out _, out _))
            {
                _extensionLineToExtension[i] = ext;
            }
        }

        if (!resetScrollToTop)
        {
            RestoreOutputViewState(viewState);
        }
    }

    private static string FormatGb(long bytes)
        => $"{bytes / (1024d * 1024d * 1024d):0.00} GB";

    private void AppendExtensionInlineDetails(StringBuilder report, string extension)
    {
        if (_diskScanResult is null)
        {
            return;
        }

        var normalized = NormalizeExtension(extension);
        var rows = _diskScanResult.Files
            .Where(f => string.Equals(NormalizeExtension(Path.GetExtension(f.FullPath)), normalized, StringComparison.OrdinalIgnoreCase))
            .ToList();

        report.AppendLine("      Top Folders (by total size)");

        var byFolder = rows
            .Select(r => new { Folder = Path.GetDirectoryName(r.FullPath) ?? "<unknown>", r.SizeBytes })
            .GroupBy(x => x.Folder, StringComparer.OrdinalIgnoreCase)
            .Select(g => new { Folder = g.Key, FileCount = g.Count(), TotalBytes = g.Sum(x => x.SizeBytes) })
            .OrderByDescending(x => x.TotalBytes)
            .ThenBy(x => x.Folder, StringComparer.OrdinalIgnoreCase)
            .Take(10)
            .ToList();

        if (byFolder.Count == 0)
        {
            report.AppendLine("        (No files found.)");
        }
        else
        {
            report.AppendLine($"        {"Total",10}  {"Files",6}  Folder");
            foreach (var item in byFolder)
            {
                report.AppendLine($"        {FormatGb(item.TotalBytes),10}  {item.FileCount,6}  {item.Folder}");
            }
        }

        report.AppendLine();
        report.AppendLine("      Largest Files");

        var largest = rows
            .OrderByDescending(r => r.SizeBytes)
            .ThenBy(r => r.FullPath, StringComparer.OrdinalIgnoreCase)
            .Take(10)
            .ToList();

        if (largest.Count == 0)
        {
            report.AppendLine("        (No files found.)");
        }
        else
        {
            foreach (var item in largest)
            {
                report.AppendLine($"        {FormatGb(item.SizeBytes),10}  {item.FullPath}");
            }
        }

        report.AppendLine();
    }

    private async Task StopSelectedProcessAsync()
    {
        var charIndex = _output.SelectionLength > 0 ? _output.SelectionStart : GetContextCharIndex();
        if (!TryGetProcessInstanceAtCharIndex(charIndex, out var groupName, out var instance) || instance.Pid is not { } pid)
        {
            MessageBox.Show(this, "Select an individual process row (PID) first.", "Stop Process", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }

        if (pid == Environment.ProcessId)
        {
            MessageBox.Show(this, "Cannot stop DiskInsight itself from this action.", "Stop Process", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }

        var displayName = string.IsNullOrWhiteSpace(groupName) ? "process" : $"{groupName}.exe";
        var confirm = MessageBox.Show(
            this,
            $"Terminate {displayName} (PID {pid})?",
            "Confirm Stop Process",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Warning,
            MessageBoxDefaultButton.Button2);

        if (confirm != DialogResult.Yes)
        {
            return;
        }

        Cursor = Cursors.WaitCursor;
        try
        {
            using var process = Process.GetProcessById(pid);

            // Try a polite close first (works for many GUI apps without admin rights).
            try
            {
                if (process.CloseMainWindow())
                {
                    try
                    {
                        process.WaitForExit(2000);
                    }
                    catch
                    {
                    }
                }
            }
            catch
            {
            }

            if (!process.HasExited)
            {
                try
                {
                    process.Kill(entireProcessTree: true);
                }
                catch (Win32Exception ex) when (ex.NativeErrorCode == 5)
                {
                    MessageBox.Show(
                        this,
                        "Access denied stopping this process.\r\n\r\n" +
                        "This usually means the process is elevated, owned by another user/session, or protected by Windows.\r\n" +
                        "Try running DiskInsight as Administrator, or stop a non-system process you own.",
                        "Stop Process (Access Denied)",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Warning);
                    return;
                }
                catch (Exception ex)
                {
                    MessageBox.Show(this, ex.Message, "Stop Process Failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }
            }

            try
            {
                process.WaitForExit(2000);
            }
            catch
            {
            }

            await RunRunningProcessesAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Stop Process Failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally
        {
            Cursor = Cursors.Default;
        }
    }

    private static string NormalizeExtension(string? ext)
    {
        if (string.IsNullOrWhiteSpace(ext))
        {
            return "<no extension>";
        }

        if (ext == "<no extension>")
        {
            return ext;
        }

        return ext.StartsWith('.') ? ext.ToLowerInvariant() : "." + ext.ToLowerInvariant();
    }

    private bool TryGetProcessGroupAtCharIndex(int charIndex, out string groupName)
    {
        groupName = string.Empty;
        if (_contentMode != ContentMode.RunningProcesses)
        {
            return false;
        }

        if (charIndex < 0 || charIndex >= _output.TextLength)
        {
            return false;
        }

        var lineIndex = _output.GetLineFromCharIndex(charIndex);
        if (!_processGroupLineToName.TryGetValue(lineIndex, out var name) || string.IsNullOrWhiteSpace(name))
        {
            return false;
        }

        groupName = name;
        return true;
    }

    private void ToggleProcessGroup(string groupName)
    {
        if (_contentMode != ContentMode.RunningProcesses || _processGroupsSnapshot is null)
        {
            return;
        }

        if (_expandedProcessGroups.Contains(groupName))
        {
            _expandedProcessGroups.Remove(groupName);
        }
        else
        {
            _expandedProcessGroups.Add(groupName);
        }

        RenderProcessGroups(resetScrollToTop: false);
    }

    private async Task AnalyzeSelectionWithEiAsync()
    {
        // Prefer explicit row selection if present.
        var charIndex = _output.SelectionLength > 0 ? _output.SelectionStart : GetContextCharIndex();
        if (!TryCreateEiRequestForCharIndex(charIndex, out var request) || request is null)
        {
            MessageBox.Show(this, "Select a supported row first (process group / process instance / file-extension summary).", "EI", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }

        Cursor = Cursors.WaitCursor;
        try
        {
            var commentary = await _eiCommentaryService.GetCommentaryAsync(request, CancellationToken.None);
            using var dialog = new EiCommentaryDialog(commentary);
            dialog.ShowDialog(this);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "EI Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally
        {
            Cursor = Cursors.Default;
        }
    }

    private bool TryCreateEiRequestForCharIndex(int charIndex, out EiCommentaryRequest? request)
    {
        request = null;

        if (_contentMode == ContentMode.RunningProcesses && _processGroupsSnapshot is not null)
        {
            if (TryGetProcessInstanceAtCharIndex(charIndex, out var instanceGroupName, out var processInstance))
            {
                var group = FindProcessGroup(instanceGroupName);
                if (group is null)
                {
                    return false;
                }

                request = new EiCommentaryRequest(
                    TargetType: "ProcessInstance",
                    TargetName: group.DisplayName,
                    InstanceCount: null,
                    FileCount: null,
                    FolderCount: null,
                    TotalWorkingSetMb: processInstance.WorkingSetBytes is { } wsBytes ? wsBytes / (1024d * 1024d) : null,
                    TotalSizeMb: null,
                    ContextHint: null,
                    LocationHints: null,
                    BrandHints: null,
                    AssociatedApplications: null,
                    TotalCpuTime: processInstance.TotalCpuTime,
                    StartTimeEarliest: processInstance.StartTime,
                    StartTimeLatest: processInstance.StartTime,
                    OsVersion: Environment.OSVersion.VersionString);

                return true;
            }

            if (TryGetProcessGroupAtCharIndex(charIndex, out var groupName))
            {
                var group = FindProcessGroup(groupName);
                if (group is null)
                {
                    return false;
                }

                TimeSpan? totalCpu = null;
                long totalCpuTicks = 0;
                var hasCpu = false;
                foreach (var groupInstance in group.Instances)
                {
                    if (groupInstance.TotalCpuTime is not { } cpu)
                    {
                        continue;
                    }
                    hasCpu = true;
                    totalCpuTicks += cpu.Ticks;
                }
                if (hasCpu)
                {
                    totalCpu = TimeSpan.FromTicks(totalCpuTicks);
                }

                DateTime? earliest = null;
                DateTime? latest = null;
                foreach (var groupInstance in group.Instances)
                {
                    if (groupInstance.StartTime is not { } start)
                    {
                        continue;
                    }

                    earliest = earliest is null || start < earliest ? start : earliest;
                    latest = latest is null || start > latest ? start : latest;
                }

                request = new EiCommentaryRequest(
                    TargetType: "ProcessGroup",
                    TargetName: group.DisplayName,
                    InstanceCount: group.InstanceCount,
                    FileCount: null,
                    FolderCount: null,
                    TotalWorkingSetMb: group.TotalWorkingSetBytes / (1024d * 1024d),
                    TotalSizeMb: null,
                    ContextHint: null,
                    LocationHints: null,
                    BrandHints: null,
                    AssociatedApplications: null,
                    TotalCpuTime: totalCpu,
                    StartTimeEarliest: earliest,
                    StartTimeLatest: latest,
                    OsVersion: Environment.OSVersion.VersionString);

                return true;
            }
        }

        if (_contentMode == ContentMode.DiskReport && TryGetExtensionSummaryAtCharIndex(charIndex, out var ext, out var totalSizeMb, out var fileCount, out var folderCount))
        {
            var contextHint = TryBuildExtensionContextHint(ext);
            var locationHints = TryBuildExtensionLocationHints(ext);
            var brandHints = TryBuildExtensionBrandHints(ext);
            var associatedApplications = FileAssociationResolver.GetAssociatedApplicationNames(ext);
            request = new EiCommentaryRequest(
                TargetType: "FileExtensionGroup",
                TargetName: ext,
                InstanceCount: null,
                FileCount: fileCount,
                FolderCount: folderCount,
                TotalWorkingSetMb: null,
                TotalSizeMb: totalSizeMb,
                ContextHint: contextHint,
                LocationHints: locationHints,
                BrandHints: brandHints,
                AssociatedApplications: associatedApplications,
                TotalCpuTime: null,
                StartTimeEarliest: null,
                StartTimeLatest: null,
                OsVersion: Environment.OSVersion.VersionString);
            return true;
        }

        return false;
    }

    private bool TryGetExtensionSummaryAtCharIndex(int charIndex, out string extension, out double totalSizeMb, out int fileCount, out int folderCount)
    {
        extension = string.Empty;
        totalSizeMb = 0;
        fileCount = 0;
        folderCount = 0;

        if (charIndex < 0 || charIndex >= _output.TextLength)
        {
            return false;
        }

        var lineIndex = _output.GetLineFromCharIndex(charIndex);
        var lines = _output.Lines;
        if (lineIndex < 0 || lineIndex >= lines.Length)
        {
            return false;
        }

        return TryParseExtensionSummaryLine(lines[lineIndex], out extension, out totalSizeMb, out fileCount, out folderCount);
    }

    private static bool TryParseExtensionSummaryLine(string line, out string extension, out double totalSizeMb, out int fileCount, out int folderCount)
    {
        extension = string.Empty;
        totalSizeMb = 0;
        fileCount = 0;
        folderCount = 0;

        // Expected formats:
        // "  {sizeGB,10}  {files,8} files  {folders,6} folders  {ext}"
        // "[+] {sizeGB,10}  {files,8} files  {folders,6} folders  {ext}"
        // "[-] {sizeGB,10}  {files,8} files  {folders,6} folders  {ext}"
        var trimmed = (line ?? string.Empty).Trim();
        if (!trimmed.Contains(" files ", StringComparison.OrdinalIgnoreCase) || !trimmed.Contains(" folders ", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        var parts = trimmed.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length < 7)
        {
            return false;
        }

        var start = 0;
        if (parts[0] is "[+]" or "[-]")
        {
            start = 1;
        }

        if (parts.Length < start + 7)
        {
            return false;
        }

        if (!double.TryParse(parts[start + 0], NumberStyles.Float, CultureInfo.InvariantCulture, out var sizeValue) &&
            !double.TryParse(parts[start + 0], NumberStyles.Float, CultureInfo.CurrentCulture, out sizeValue))
        {
            return false;
        }

        var unit = parts[start + 1];
        if (!unit.Equals("GB", StringComparison.OrdinalIgnoreCase) && !unit.Equals("MB", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        if (!int.TryParse(parts[start + 2], NumberStyles.Integer, CultureInfo.InvariantCulture, out fileCount))
        {
            return false;
        }

        if (!parts[start + 3].Equals("files", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        if (!int.TryParse(parts[start + 4], NumberStyles.Integer, CultureInfo.InvariantCulture, out folderCount))
        {
            return false;
        }

        if (!parts[start + 5].Equals("folders", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        extension = string.Join(" ", parts, startIndex: start + 6, count: parts.Length - (start + 6)).Trim();
        if (string.IsNullOrWhiteSpace(extension))
        {
            return false;
        }

        totalSizeMb = unit.Equals("GB", StringComparison.OrdinalIgnoreCase) ? sizeValue * 1024d : sizeValue;
        return true;
    }

    private string? TryBuildExtensionContextHint(string extension)
    {
        if (_diskScanResult is null)
        {
            return null;
        }

        try
        {
            var normalized = (extension ?? string.Empty).Trim();
            if (string.IsNullOrWhiteSpace(normalized))
            {
                return null;
            }

            // Use only folder NAMES (not full paths) as privacy-safe hints.
            var topFolderNames = _diskScanResult.Files
                .Where(f => string.Equals(Path.GetExtension(f.FullPath) ?? string.Empty, normalized, StringComparison.OrdinalIgnoreCase))
                .Select(f => Path.GetDirectoryName(f.FullPath))
                .Where(p => !string.IsNullOrWhiteSpace(p))
                .Select(p => Path.GetFileName(p!.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)))
                .Where(n => !string.IsNullOrWhiteSpace(n))
                .GroupBy(n => n!, StringComparer.OrdinalIgnoreCase)
                .Select(g => new { Name = g.Key, Count = g.Count() })
                .OrderByDescending(x => x.Count)
                .ThenBy(x => x.Name, StringComparer.OrdinalIgnoreCase)
                .Take(5)
                .Select(x => $"{x.Name} ({x.Count})")
                .ToList();

            if (topFolderNames.Count == 0)
            {
                return null;
            }

            return "Top folder names: " + string.Join(", ", topFolderNames);
        }
        catch
        {
            return null;
        }
    }

    private string[]? TryBuildExtensionLocationHints(string extension)
    {
        if (_diskScanResult is null)
        {
            return null;
        }

        try
        {
            var normalized = (extension ?? string.Empty).Trim();
            if (string.IsNullOrWhiteSpace(normalized) || normalized == "<no extension>")
            {
                return null;
            }

            // Provide "location" hints without sending full paths: last 2 folder segments only.
            var top = _diskScanResult.Files
                .Where(f => string.Equals(Path.GetExtension(f.FullPath) ?? string.Empty, normalized, StringComparison.OrdinalIgnoreCase))
                .Select(f => Path.GetDirectoryName(f.FullPath))
                .Where(p => !string.IsNullOrWhiteSpace(p))
                .Select(p => RedactPathToTail(p!, segments: 3))
                .Where(p => !string.IsNullOrWhiteSpace(p))
                .GroupBy(p => p!, StringComparer.OrdinalIgnoreCase)
                .Select(g => new { Hint = g.Key, Count = g.Count() })
                .OrderByDescending(x => x.Count)
                .ThenBy(x => x.Hint, StringComparer.OrdinalIgnoreCase)
                .Take(10)
                .Select(x => $"{x.Hint} ({x.Count})")
                .ToArray();

            return top.Length == 0 ? null : top;
        }
        catch
        {
            return null;
        }
    }

    private string[]? TryBuildExtensionBrandHints(string extension)
    {
        if (_diskScanResult is null)
        {
            return null;
        }

        try
        {
            var normalized = (extension ?? string.Empty).Trim();
            if (string.IsNullOrWhiteSpace(normalized) || normalized == "<no extension>")
            {
                return null;
            }

            // Extract likely vendor/product names from the last 2 folder segments (no full paths).
            var hints = _diskScanResult.Files
                .Where(f => string.Equals(Path.GetExtension(f.FullPath) ?? string.Empty, normalized, StringComparison.OrdinalIgnoreCase))
                .Select(f => Path.GetDirectoryName(f.FullPath))
                .Where(p => !string.IsNullOrWhiteSpace(p))
                .SelectMany(p => GetTailFolderNames(p!, segments: 3))
                .Where(n => !string.IsNullOrWhiteSpace(n))
                .Where(n => n!.Length >= 3 && n.Length <= 32)
                .Where(n => !IsGenericFolderName(n!))
                .GroupBy(n => n!, StringComparer.OrdinalIgnoreCase)
                .Select(g => new { Name = g.Key, Count = g.Count() })
                .OrderByDescending(x => x.Count)
                .ThenBy(x => x.Name, StringComparer.OrdinalIgnoreCase)
                .Take(8)
                .Select(x => $"{x.Name} ({x.Count})")
                .ToArray();

            return hints.Length == 0 ? null : hints;
        }
        catch
        {
            return null;
        }
    }

    private static string[] GetTailFolderNames(string path, int segments)
    {
        try
        {
            if (segments <= 0)
            {
                return Array.Empty<string>();
            }

            var cleaned = path.Trim().TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            if (cleaned.Length == 0)
            {
                return Array.Empty<string>();
            }

            var parts = cleaned.Split(new[] { Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar }, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length == 0)
            {
                return Array.Empty<string>();
            }

            var take = Math.Min(segments, parts.Length);
            var result = new string[take];
            Array.Copy(parts, parts.Length - take, result, 0, take);
            return result;
        }
        catch
        {
            return Array.Empty<string>();
        }
    }

    private static bool IsGenericFolderName(string name)
    {
        return name.Equals("users", StringComparison.OrdinalIgnoreCase) ||
               name.Equals("program files", StringComparison.OrdinalIgnoreCase) ||
               name.Equals("program files (x86)", StringComparison.OrdinalIgnoreCase) ||
               name.Equals("programdata", StringComparison.OrdinalIgnoreCase) ||
               name.Equals("windows", StringComparison.OrdinalIgnoreCase) ||
               name.Equals("appdata", StringComparison.OrdinalIgnoreCase) ||
               name.Equals("local", StringComparison.OrdinalIgnoreCase) ||
               name.Equals("roaming", StringComparison.OrdinalIgnoreCase) ||
               name.Equals("documents", StringComparison.OrdinalIgnoreCase) ||
               name.Equals("downloads", StringComparison.OrdinalIgnoreCase) ||
               name.Equals("desktop", StringComparison.OrdinalIgnoreCase) ||
               name.Equals("separations", StringComparison.OrdinalIgnoreCase) ||
               name.Equals("cache", StringComparison.OrdinalIgnoreCase) ||
               name.Equals("caches", StringComparison.OrdinalIgnoreCase) ||
               name.Equals("temp", StringComparison.OrdinalIgnoreCase) ||
               name.Equals("tmp", StringComparison.OrdinalIgnoreCase);
    }

    private static string? RedactPathToTail(string path, int segments)
    {
        try
        {
            if (segments <= 0)
            {
                return null;
            }

            var cleaned = path.Trim().TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            if (cleaned.Length == 0)
            {
                return null;
            }

            var parts = cleaned.Split(new[] { Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar }, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length == 0)
            {
                return null;
            }

            var take = Math.Min(segments, parts.Length);
            var tail = string.Join(Path.DirectorySeparatorChar, parts, parts.Length - take, take);
            return "...\\" + tail;
        }
        catch
        {
            return null;
        }
    }

    private bool TryGetProcessInstanceAtCharIndex(int charIndex, out string groupName, out ProcessScanner.ProcessInstanceSnapshot instance)
    {
        groupName = string.Empty;
        instance = null!;
        if (_contentMode != ContentMode.RunningProcesses)
        {
            return false;
        }

        if (charIndex < 0 || charIndex >= _output.TextLength)
        {
            return false;
        }

        var lineIndex = _output.GetLineFromCharIndex(charIndex);
        if (!_processInstanceLineToInstance.TryGetValue(lineIndex, out var hit))
        {
            return false;
        }

        groupName = hit.GroupName;
        instance = hit.Instance;
        return true;
    }

    private ProcessScanner.ProcessGroupSnapshot? FindProcessGroup(string groupName)
    {
        if (_processGroupsSnapshot is null)
        {
            return null;
        }

        foreach (var group in _processGroupsSnapshot)
        {
            if (string.Equals(group.Name, groupName, StringComparison.OrdinalIgnoreCase))
            {
                return group;
            }
        }

        return null;
    }
}
