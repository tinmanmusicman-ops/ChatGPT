using System;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Text;
using System.Threading;
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
    private readonly IEiCommentaryService _eiCommentaryService;
    private float _outputFontSizePt;
    private Font? _outputFont;
    private bool _hoveringPath;
    private bool _isRunning;
    private ContentMode _contentMode;
    private List<ProcessScanner.ProcessGroupSnapshot>? _processGroupsSnapshot;
    private DiskAnalyzer.ScanResult? _diskScanResult;
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
        _output.MouseUp += OutputOnMouseUp;
        _output.MouseMove += OutputOnMouseMove;
        _output.MouseLeave += (_, _) => SetOutputHoverCursor(false);
        _output.MouseDoubleClick += OutputOnMouseDoubleClick;

        _outputFontSizePt = ClampFontSize(UserSettings.LoadOutputFontSizePt());
        ApplyOutputFont(persist: false);

        _output.Text =
            "Ready.\r\n\r\n" +
            "Use Functions -> Disk Report (Read-Only Scan) to generate the report.\r\n" +
            "Use Tools -> Running Processes to list running processes.\r\n" +
            "Right-click a process group or instance row to Analyze with EI.\r\n";
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

        var analyzeEi = new ToolStripMenuItem("Analyze with EI...");
        analyzeEi.Click += async (_, _) => await AnalyzeSelectionWithEiAsync();

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

            _output.Text = DiskAnalyzer.BuildExtensionDetailsReport(_diskScanResult, ext);
            _output.SelectionStart = 0;
            _output.SelectionLength = 0;
            _contentMode = ContentMode.DiskReport;
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

            extensionDetails.Visible = true;
            extensionDetails.Enabled = true;

            var enabled = TryGetPathAtCharIndex(charIndex, out var path) && CanOpenPath(path);
            openPath.Enabled = enabled;
            openContainingFolder.Enabled = enabled;
            if (!enabled)
            {
                e.Cancel = false;
            }
        };

        menu.Items.Add(analyzeEi);
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
            _contentMode = ContentMode.None;
            _processGroupsSnapshot = null;
            _expandedProcessGroups.Clear();
            _processGroupLineToName.Clear();
            _processInstanceLineToInstance.Clear();
            _diskScanResult = null;

            _output.Text = "Scanning (read-only)...\r\nThis may take a moment.\r\n";
            _diskScanResult = await Task.Run(DiskAnalyzer.BuildScanResult);
            var report = DiskAnalyzer.BuildReport(_diskScanResult);
            _output.Text = report;
            _output.SelectionStart = 0;
            _output.SelectionLength = 0;
            _contentMode = ContentMode.DiskReport;
            _processGroupsSnapshot = null;
            _expandedProcessGroups.Clear();
            _processGroupLineToName.Clear();
            _processInstanceLineToInstance.Clear();
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
            _contentMode = ContentMode.None;
            _processGroupsSnapshot = null;
            _expandedProcessGroups.Clear();
            _processGroupLineToName.Clear();
            _processInstanceLineToInstance.Clear();
            _diskScanResult = null;

            _output.Text = "Enumerating running processes...\r\n";
            _processGroupsSnapshot = await Task.Run(ProcessScanner.GetGroupedSnapshot);
            _expandedProcessGroups.Clear();
            _contentMode = ContentMode.RunningProcesses;
            _diskScanResult = null;
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

        // Expected format from DiskAnalyzer:
        // "  {sizeGB,10}  {files,8} files  {folders,6} folders  {ext}"
        var line = lines[lineIndex].Trim();
        if (!line.Contains(" files ", StringComparison.OrdinalIgnoreCase) || !line.Contains(" folders ", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        // Parse via simple token scanning (invariant).
        // Example: "1.23 GB 123 files 45 folders .txt"
        var parts = line.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length < 7)
        {
            return false;
        }

        if (!double.TryParse(parts[0], NumberStyles.Float, CultureInfo.InvariantCulture, out var sizeValue) &&
            !double.TryParse(parts[0], NumberStyles.Float, CultureInfo.CurrentCulture, out sizeValue))
        {
            return false;
        }

        var unit = parts[1];
        if (!unit.Equals("GB", StringComparison.OrdinalIgnoreCase) && !unit.Equals("MB", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        if (!int.TryParse(parts[2], NumberStyles.Integer, CultureInfo.InvariantCulture, out fileCount))
        {
            return false;
        }

        if (!parts[3].Equals("files", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        if (!int.TryParse(parts[4], NumberStyles.Integer, CultureInfo.InvariantCulture, out folderCount))
        {
            return false;
        }

        if (!parts[5].Equals("folders", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        extension = string.Join(" ", parts, startIndex: 6, count: parts.Length - 6).Trim();
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
