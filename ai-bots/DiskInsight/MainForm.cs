using System;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace DiskInsight;

internal sealed class MainForm : Form
{
    private enum ContentMode
    {
        None,
        DiskReport,
        RunningProcesses,
    }

    private readonly TextBox _output;
    private readonly ToolStripMenuItem _viewFontSizeMenu;
    private readonly ToolStripMenuItem _functionsDiskReportMenuItem;
    private readonly ToolStripMenuItem _toolsRunningProcessesMenuItem;
    private float _outputFontSizePt;
    private Font? _outputFont;
    private bool _hoveringPath;
    private bool _isRunning;
    private ContentMode _contentMode;
    private List<ProcessScanner.ProcessGroupSnapshot>? _processGroupsSnapshot;
    private readonly HashSet<string> _expandedProcessGroups = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<int, string> _processGroupLineToName = new();

    public MainForm()
    {
        Text = "Disk Insight – Review Only";
        StartPosition = FormStartPosition.CenterScreen;
        Width = 900;
        Height = 700;
        MinimizeBox = true;
        MaximizeBox = true;

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
        var functions = new ToolStripMenuItem("&Functions");
        _functionsDiskReportMenuItem = new ToolStripMenuItem("Disk Report (Read-Only Scan)");
        _functionsDiskReportMenuItem.Click += async (_, _) => await RunDiskReportAsync();
        functions.DropDownItems.Add(_functionsDiskReportMenuItem);

        var tools = new ToolStripMenuItem("&Tools");
        _toolsRunningProcessesMenuItem = new ToolStripMenuItem("Running Processes");
        _toolsRunningProcessesMenuItem.Click += async (_, _) => await RunRunningProcessesAsync();
        tools.DropDownItems.Add(_toolsRunningProcessesMenuItem);

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

        Controls.Add(_output);
        Controls.Add(menu);

        _output.ContextMenuStrip = CreateOutputContextMenu();
        _output.MouseDown += OutputOnMouseDown;
        _output.MouseMove += OutputOnMouseMove;
        _output.MouseLeave += (_, _) => SetOutputHoverCursor(false);
        _output.MouseDoubleClick += OutputOnMouseDoubleClick;

        _outputFontSizePt = ClampFontSize(UserSettings.LoadOutputFontSizePt());
        ApplyOutputFont(persist: false);

        _output.Text =
            "Ready.\r\n\r\n" +
            "Use Functions -> Disk Report (Read-Only Scan) to generate the report.\r\n" +
            "Use Tools -> Running Processes to list running processes.\r\n";
    }

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
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

        var openPath = new ToolStripMenuItem("Open in Explorer");
        openPath.Click += (_, _) =>
        {
            if (TryGetPathAtCharIndex(_output.SelectionStart, out var path))
            {
                OpenPathInExplorer(path);
            }
        };

        var openContainingFolder = new ToolStripMenuItem("Open Containing Folder");
        openContainingFolder.Click += (_, _) =>
        {
            if (TryGetPathAtCharIndex(_output.SelectionStart, out var path))
            {
                OpenContainingFolderInExplorer(path);
            }
        };

        menu.Opening += (_, e) =>
        {
            var enabled = TryGetPathAtCharIndex(_output.SelectionStart, out var path) && CanOpenPath(path);
            openPath.Enabled = enabled;
            openContainingFolder.Enabled = enabled;
            if (!enabled)
            {
                e.Cancel = false;
            }
        };

        menu.Items.Add(openPath);
        menu.Items.Add(openContainingFolder);
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Increase Font Size", null, (_, _) => AdjustFontSize(+1f));
        menu.Items.Add("Decrease Font Size", null, (_, _) => AdjustFontSize(-1f));
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Reset Font Size", null, (_, _) => ResetFontSize());
        return menu;
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
        if (e.Button == MouseButtons.Right)
        {
            _output.SelectionStart = _output.GetCharIndexFromPosition(e.Location);
            _output.SelectionLength = 0;
        }
    }

    private void OutputOnMouseMove(object? sender, MouseEventArgs e)
    {
        var charIndex = _output.GetCharIndexFromPosition(e.Location);
        SetOutputHoverCursor(
            TryGetProcessGroupAtCharIndex(charIndex, out _) ||
            TryGetPathAtCharIndex(charIndex, out _));
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
            _output.Text = "Scanning (read-only)...\r\nThis may take a moment.\r\n";
            var report = await Task.Run(DiskAnalyzer.BuildReport);
            _output.Text = report;
            _output.SelectionStart = 0;
            _output.SelectionLength = 0;
            _contentMode = ContentMode.DiskReport;
            _processGroupsSnapshot = null;
            _expandedProcessGroups.Clear();
            _processGroupLineToName.Clear();
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
        Cursor = Cursors.WaitCursor;

        try
        {
            _output.Text = "Enumerating running processes...\r\n";
            _processGroupsSnapshot = await Task.Run(ProcessScanner.GetGroupedSnapshot);
            _expandedProcessGroups.Clear();
            _contentMode = ContentMode.RunningProcesses;
            RenderProcessGroups();
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
            _isRunning = false;
        }
    }

    private void RenderProcessGroups()
    {
        if (_processGroupsSnapshot is null)
        {
            return;
        }

        _processGroupLineToName.Clear();
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
                report.AppendLine($"      {pid,7}  {ws,8}  {cpuUsage,6}  {cpu,12}  {start,19}");
                lineIndex++;
            }
        }

        _output.Text = report.ToString();
        _output.SelectionStart = 0;
        _output.SelectionLength = 0;
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

        RenderProcessGroups();
    }
}
