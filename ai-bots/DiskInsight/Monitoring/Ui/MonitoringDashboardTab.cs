using System;
using System.Drawing;
using System.Linq;
using System.Threading.Tasks;
using DiskInsight.Monitoring.Providers;
using DiskInsight.Ui.Controls;

namespace DiskInsight.Monitoring.Ui;

public sealed class MonitoringDashboardTab : UserControl
{
    private readonly TabControl _metricTabs;
    private readonly Button _cpuSnapshotButton;
    private readonly GroupedBarChartControl _cpuCoreBars;
    private readonly GroupedBarChartControl _gpuBars;
    private readonly ListView _gpuProcessList;
    private readonly GaugeControl[] _threadGauges = new GaugeControl[8];
    private readonly StackedBarControl _memoryBar;
    private readonly StackedBarControl _cDriveBar;
    private readonly StackedBarControl _dDriveBar;
    private readonly StackedBarControl _networkBar;
    private readonly Label _cpuStatusLabel;
    private readonly Label _gpuStatusLabel;
    private readonly Label _intelGpuNameLabel;
    private readonly Label _nvidiaGpuNameLabel;
    private readonly CpuTemperatureProvider _cpuProvider = new();
    private readonly CpuUsageProvider _cpuUsageProvider = new();
    private readonly GpuUsageProvider _gpuUsageProvider = new();
    private readonly LogicalProcessorUsageProvider _logicalCpuProvider = new();
    private readonly MemoryStatusProvider _memoryProvider = new();
    private readonly DriveUsageProvider _driveProvider = new();
    private readonly NetworkUsageProvider _networkProvider = new();
    private readonly HwinfoFanSpeedProvider _fanSpeedProvider = new();
    private readonly System.Windows.Forms.Timer _refreshTimer;
    private readonly System.Windows.Forms.Timer _memoryTimer;
    private readonly System.Windows.Forms.Timer _networkTimer;
    private volatile bool _snapshotInFlight;
    private volatile bool _memoryInFlight;
    private volatile bool _drivesInFlight;
    private volatile bool _networkInFlight;
    private readonly double?[] _lastCoreUsage = new double?[4];
    private readonly double?[] _lastCoreTempC = new double?[4];
    private readonly double?[] _lastThreadUsage = new double?[8];
    private double? _lastIntelGpuUsage;
    private double? _lastIntelGpuTempC;
    private double? _lastIntelGpuCpu;
    private double? _lastNvidiaGpuUsage;
    private double? _lastNvidiaGpuTempC;
    private double? _lastNvidiaGpuCpu;
    private double? _lastUsbProxyUsage;
    private double? _lastUsbDriverCpu;
    private double? _lastUsbIoMBps;
    private MemoryStatusSnapshot? _lastMemory;
    private DriveUsageSnapshot? _lastCDrive;
    private DriveUsageSnapshot? _lastDDrive;
    private NetworkUsageSnapshot? _lastNetwork;

    public MonitoringDashboardTab()
    {
        Dock = DockStyle.Fill;

        _refreshTimer = new System.Windows.Forms.Timer
        {
            Interval = 1000,
            Enabled = false,
        };
        _refreshTimer.Tick += async (_, _) => await SnapshotCpuAsync();

        _memoryTimer = new System.Windows.Forms.Timer
        {
            Interval = 60_000,
            Enabled = false,
        };
        _memoryTimer.Tick += async (_, _) =>
        {
            await SnapshotMemoryAsync();
            await SnapshotDrivesAsync();
        };

        _networkTimer = new System.Windows.Forms.Timer
        {
            Interval = 1000,
            Enabled = false,
        };
        _networkTimer.Tick += async (_, _) => await SnapshotNetworkAsync();

        _metricTabs = new TabControl
        {
            Dock = DockStyle.Fill,
        };

        var cpuPage = new TabPage("CPU")
        {
            Padding = new Padding(10),
        };

        var cpuHeader = new Label
        {
            AutoSize = true,
            Text = "CPU per-core (C1-C4; Usg=% Tmp=°F; updates every second)",
        };

        var cpuTitle = new Label
        {
            Dock = DockStyle.Top,
            Height = (int)Math.Round(0.30 * DeviceDpi),
            Text = "CPU",
            TextAlign = ContentAlignment.MiddleCenter,
            Font = new Font(Font.FontFamily, Font.SizeInPoints + 4f, FontStyle.Bold),
        };

        _cpuStatusLabel = new Label
        {
            AutoSize = true,
            ForeColor = SystemColors.GrayText,
            Padding = new Padding(10, 4, 10, 0),
            Text = "CPU Fan: n/a",
        };

        _cpuSnapshotButton = new Button
        {
            Text = "Snapshot",
            AutoSize = true,
        };
        _cpuSnapshotButton.Click += async (_, _) => await SnapshotCpuAsync();

        var cpuStatusHeightPx = _cpuStatusLabel.Height;
        _cpuStatusLabel.AutoSize = false;
        _cpuStatusLabel.Height = cpuStatusHeightPx;
        _cpuStatusLabel.TextAlign = ContentAlignment.MiddleCenter;

        cpuHeader.AutoSize = false;
        cpuHeader.Height = cpuStatusHeightPx;
        cpuHeader.Width = 0;

        _cpuCoreBars = new GroupedBarChartControl
        {
            Title = "",
            ShowValueLabels = true,
        };
        _cpuCoreBars.SetSeries(new[]
        {
            new BarSeries(
                Key: "use",
                Minimum: 0,
                Maximum: 100,
                Units: "%",
                ValueFormat: "0.0",
                Ranges: new[]
                {
                    new GaugeRange(0, 60, Color.FromArgb(0x2E, 0xCC, 0x71)),
                    new GaugeRange(60, 75, Color.FromArgb(0xF1, 0xC4, 0x0F)),
                    new GaugeRange(75, 90, Color.FromArgb(0xF3, 0x9C, 0x12)),
                    new GaugeRange(90, 100, Color.FromArgb(0xE7, 0x4C, 0x3C)),
                },
                DisplayLabel: "Usg"),
            new BarSeries(
                Key: "temp",
                Minimum: 20,
                Maximum: 105,
                Units: "\u00B0C",
                ValueFormat: "0.0",
                Ranges: new[]
                {
                    new GaugeRange(20, 70, Color.FromArgb(0x2E, 0xCC, 0x71)),  // green
                    new GaugeRange(70, 80, Color.FromArgb(0xF1, 0xC4, 0x0F)),  // yellow
                    new GaugeRange(80, 90, Color.FromArgb(0xF3, 0x9C, 0x12)),  // orange
                    new GaugeRange(90, 100, Color.FromArgb(0xE7, 0x4C, 0x3C)), // red
                    new GaugeRange(100, 105, Color.FromArgb(0xFF, 0x00, 0x00)), // bright red
                },
                DisplayLabel: "Tmp"),
        });

        _gpuStatusLabel = new Label
        {
            AutoSize = true,
            ForeColor = SystemColors.GrayText,
            Padding = new Padding(10, 0, 10, 0),
            Text = "GPU Fan: n/a",
        };
        _intelGpuNameLabel = new Label
        {
            AutoSize = true,
            ForeColor = SystemColors.GrayText,
            Text = "Intel graphics",
        };
        _nvidiaGpuNameLabel = new Label
        {
            AutoSize = true,
            ForeColor = SystemColors.GrayText,
            Text = "NVIDIA GPU",
        };
        var gpuStatusHeightPx = _gpuStatusLabel.Height;
        _gpuStatusLabel.AutoSize = false;
        _gpuStatusLabel.Height = gpuStatusHeightPx;
        _gpuStatusLabel.TextAlign = ContentAlignment.MiddleCenter;

        _gpuBars = new GroupedBarChartControl
        {
            Title = "",
            ShowValueLabels = true,
        };
        _gpuBars.SetSeries(new[]
        {
            new BarSeries(
                Key: "use",
                Minimum: 0,
                Maximum: 100,
                Units: "%",
                ValueFormat: "0.0",
                Ranges: new[]
                {
                    new GaugeRange(0, 60, Color.FromArgb(0x2E, 0xCC, 0x71)),
                    new GaugeRange(60, 75, Color.FromArgb(0xF1, 0xC4, 0x0F)),
                    new GaugeRange(75, 90, Color.FromArgb(0xF3, 0x9C, 0x12)),
                    new GaugeRange(90, 100, Color.FromArgb(0xE7, 0x4C, 0x3C)),
                },
                DisplayLabel: "Usg"),
            new BarSeries(
                Key: "temp",
                Minimum: 32,
                Maximum: 105,
                Units: "\u00B0C",
                ValueFormat: "0.0",
                Ranges: new[]
                {
                    new GaugeRange(32, 66, Color.FromArgb(0x2E, 0xCC, 0x71)),   // green
                    new GaugeRange(66, 73.5, Color.FromArgb(0xF1, 0xC4, 0x0F)), // yellow
                    new GaugeRange(73.5, 85, Color.FromArgb(0xF3, 0x9C, 0x12)), // orange
                    new GaugeRange(85, 93.5, Color.FromArgb(0xE7, 0x4C, 0x3C)), // red
                    new GaugeRange(93.5, 105, Color.FromArgb(0xFF, 0x00, 0x00)), // bright red
                },
                DisplayLabel: "Tmp"),
            new BarSeries(
                Key: "cpu",
                Minimum: 0,
                Maximum: 100,
                Units: "%",
                ValueFormat: "0.0",
                Ranges: new[]
                {
                    new GaugeRange(0, 60, Color.FromArgb(0x2E, 0xCC, 0x71)),
                    new GaugeRange(60, 75, Color.FromArgb(0xF1, 0xC4, 0x0F)),
                    new GaugeRange(75, 90, Color.FromArgb(0xF3, 0x9C, 0x12)),
                    new GaugeRange(90, 100, Color.FromArgb(0xE7, 0x4C, 0x3C)),
                },
                DisplayLabel: "CPU"),
            new BarSeries(
                Key: "usb",
                Minimum: 0,
                Maximum: 600,
                Units: "MB/s",
                ValueFormat: "0.0",
                Ranges: new[]
                {
                    new GaugeRange(0, 100, Color.FromArgb(0x2E, 0xCC, 0x71)),
                    new GaugeRange(100, 250, Color.FromArgb(0xF1, 0xC4, 0x0F)),
                    new GaugeRange(250, 400, Color.FromArgb(0xF3, 0x9C, 0x12)),
                    new GaugeRange(400, 600, Color.FromArgb(0xE7, 0x4C, 0x3C)),
                },
                DisplayLabel: "USB"),
        });

        _memoryBar = new StackedBarControl
        {
            Dock = DockStyle.Fill,
            TitleLeft = "Memory",
            TitleRight = "",
        };

        _cDriveBar = new StackedBarControl
        {
            Dock = DockStyle.Fill,
            TitleLeft = "C:\\",
            TitleRight = "",
        };

        _dDriveBar = new StackedBarControl
        {
            Dock = DockStyle.Fill,
            TitleLeft = "D:\\",
            TitleRight = "",
        };

        _networkBar = new StackedBarControl
        {
            Dock = DockStyle.Fill,
            TitleLeft = "Network",
            TitleRight = "",
            FillBarBackground = true,
            BarBackgroundColor = Color.FromArgb(0x34, 0x98, 0xDB), // blue total
        };

        var cpuTopRow = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            Padding = new Padding(0, 0, 0, 8),
        };
        cpuTopRow.Layout += (_, _) => CenterCpuInfoLine(cpuTopRow, cpuHeader, _cpuStatusLabel, _cpuSnapshotButton);
        cpuTopRow.Controls.Add(cpuHeader);
        cpuTopRow.Controls.Add(_cpuStatusLabel);
        cpuTopRow.Controls.Add(_cpuSnapshotButton);

        var chartWidthPx = (int)Math.Round(3.0 * DeviceDpi);
        var chartHeightPx = (int)Math.Round(2.0 * DeviceDpi);

        _cpuCoreBars.Dock = DockStyle.Fill;
        _cpuCoreBars.MinimumSize = new Size(chartWidthPx, chartHeightPx);

        var gpuTitle = new Label
        {
            Dock = DockStyle.Top,
            Height = (int)Math.Round(0.26 * DeviceDpi),
            Text = "GPU",
            TextAlign = ContentAlignment.MiddleCenter,
            Font = new Font(Font.FontFamily, Font.SizeInPoints + 3f, FontStyle.Bold),
        };
        _gpuBars.Dock = DockStyle.Fill;
        _gpuBars.MinimumSize = new Size(chartWidthPx, (int)Math.Round(3.0 * DeviceDpi));

        _gpuProcessList = new ListView
        {
            Dock = DockStyle.Fill,
            View = View.Details,
            FullRowSelect = true,
            GridLines = true,
            HideSelection = false,
            MultiSelect = false,
            HeaderStyle = ColumnHeaderStyle.Nonclickable,
        };

        var colProcess = (int)Math.Round(2.05 * DeviceDpi);
        var colPid = (int)Math.Round(0.60 * DeviceDpi);
        var colEngine = (int)Math.Round(0.90 * DeviceDpi);
        var colGpu = (int)Math.Round(0.65 * DeviceDpi);
        var colCpu = (int)Math.Round(0.65 * DeviceDpi);
        _gpuProcessList.Columns.Add("Process", colProcess);
        _gpuProcessList.Columns.Add("PID", colPid);
        _gpuProcessList.Columns.Add("Engine", colEngine);
        _gpuProcessList.Columns.Add("GPU", colGpu);
        _gpuProcessList.Columns.Add("CPU", colCpu);

        var gpuProcLabel = new Label
        {
            Dock = DockStyle.Top,
            Height = (int)Math.Round(0.20 * DeviceDpi),
            Text = "Top processes (by GPU engine activity)",
            TextAlign = ContentAlignment.MiddleLeft,
            ForeColor = SystemColors.GrayText,
            Padding = new Padding(0, 0, 0, 2),
        };

        var gpuProcHeightPx = (int)Math.Round(1.25 * DeviceDpi);
        var gpuProcHost = new Panel
        {
            Height = gpuProcHeightPx,
            Margin = Padding.Empty,
        };
        gpuProcHost.Controls.Add(_gpuProcessList);
        gpuProcHost.Controls.Add(gpuProcLabel);

        var gpuMetricLabelRow = new TableLayoutPanel
        {
            Dock = DockStyle.Bottom,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            ColumnCount = 6,
            RowCount = 1,
            Margin = Padding.Empty,
            Padding = new Padding(10, 0, 10, 0),
        };
        for (var c = 0; c < gpuMetricLabelRow.ColumnCount; c++)
        {
            gpuMetricLabelRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f / gpuMetricLabelRow.ColumnCount));
        }
        gpuMetricLabelRow.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        var legendLabels = new[] { "Usg", "Tmp", "CPU", "Usg", "Tmp", "CPU" };
        for (var i = 0; i < legendLabels.Length; i++)
        {
            var label = new Label
            {
                Dock = DockStyle.Fill,
                Text = legendLabels[i],
                ForeColor = SystemColors.GrayText,
                Font = new Font(Font.FontFamily, Font.SizeInPoints, FontStyle.Regular),
                TextAlign = ContentAlignment.MiddleCenter,
                Margin = new Padding(4, 0, 4, 0),
            };
            gpuMetricLabelRow.Controls.Add(label, i, 0);
        }

        var gpuNameRow = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            Height = (int)Math.Round(0.26 * DeviceDpi),
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            Padding = new Padding(10, 0, 10, 0),
        };
        gpuNameRow.Controls.Add(_intelGpuNameLabel);
        gpuNameRow.Controls.Add(_nvidiaGpuNameLabel);

        var gpuNameArea = new Panel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Padding = new Padding(10, 0, 10, 0),
        };
        gpuNameArea.Controls.Add(gpuNameRow);

        var gpuBarHost = new Panel
        {
            Dock = DockStyle.Fill,
            Margin = Padding.Empty,
            Padding = Padding.Empty,
        };
        gpuBarHost.Controls.Add(gpuMetricLabelRow);
        gpuBarHost.Controls.Add(_gpuBars);

        var memHeightPx = (int)Math.Round(0.65 * DeviceDpi);
        var memHost = new Panel
        {
            Size = new Size(chartWidthPx, memHeightPx),
            MinimumSize = new Size(chartWidthPx, memHeightPx),
            MaximumSize = new Size(chartWidthPx, memHeightPx),
            Margin = new Padding(0, 6, 12, 0),
        };
        memHost.Controls.Add(_memoryBar);

        var cHost = new Panel
        {
            Size = new Size(chartWidthPx, memHeightPx),
            MinimumSize = new Size(chartWidthPx, memHeightPx),
            MaximumSize = new Size(chartWidthPx, memHeightPx),
            Margin = new Padding(0, 6, 12, 0),
        };
        cHost.Controls.Add(_cDriveBar);

        var dHost = new Panel
        {
            Size = new Size(chartWidthPx, memHeightPx),
            MinimumSize = new Size(chartWidthPx, memHeightPx),
            MaximumSize = new Size(chartWidthPx, memHeightPx),
            Margin = new Padding(0, 6, 12, 0),
        };
        dHost.Controls.Add(_dDriveBar);

        var nHost = new Panel
        {
            Size = new Size(chartWidthPx, memHeightPx),
            MinimumSize = new Size(chartWidthPx, memHeightPx),
            MaximumSize = new Size(chartWidthPx, memHeightPx),
            Margin = new Padding(0, 6, 12, 0),
        };
        nHost.Controls.Add(_networkBar);

        var threadRow = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            Margin = Padding.Empty,
            Padding = new Padding(0, 6, 0, 0),
            ColumnCount = 8,
            RowCount = 1,
        };
        for (var c = 0; c < threadRow.ColumnCount; c++)
        {
            threadRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 12.5f));
        }
        threadRow.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));

        var threadUsageRanges = new[]
        {
            new GaugeRange(0, 60, Color.FromArgb(0x2E, 0xCC, 0x71)),
            new GaugeRange(60, 75, Color.FromArgb(0xF1, 0xC4, 0x0F)),
            new GaugeRange(75, 90, Color.FromArgb(0xF3, 0x9C, 0x12)),
            new GaugeRange(90, 100, Color.FromArgb(0xE7, 0x4C, 0x3C)),
        };

        for (var i = 0; i < _threadGauges.Length; i++)
        {
            var gauge = new GaugeControl
            {
                Dock = DockStyle.Fill,
                Minimum = 0,
                Maximum = 100,
                Units = "%",
                ValueFormat = "0.0",
                Title = "T" + (i + 1).ToString(),
                Margin = new Padding(4),
                MinimumSize = new Size((int)Math.Round(0.60 * DeviceDpi), (int)Math.Round(0.60 * DeviceDpi)),
            };
            gauge.SetRanges(threadUsageRanges);
            _threadGauges[i] = gauge;
            threadRow.Controls.Add(gauge, i, 0);
        }

        var cpuPanel = new Panel
        {
            Dock = DockStyle.Fill,
            Margin = Padding.Empty,
            Padding = Padding.Empty,
        };
        cpuTitle.Dock = DockStyle.Top;
        cpuTopRow.Dock = DockStyle.Top;
        cpuTitle.Margin = Padding.Empty;
        cpuTopRow.Margin = Padding.Empty;
        cpuPanel.Controls.Add(_cpuCoreBars);
        cpuPanel.Controls.Add(cpuTopRow);
        cpuPanel.Controls.Add(cpuTitle);

        var gpuPanel = new Panel
        {
            Dock = DockStyle.Fill,
            Margin = Padding.Empty,
            Padding = Padding.Empty,
        };
        gpuTitle.Dock = DockStyle.Top;
        _gpuStatusLabel.Dock = DockStyle.Top;
        gpuTitle.Margin = Padding.Empty;
        _gpuStatusLabel.Margin = Padding.Empty;
        gpuPanel.Controls.Add(gpuBarHost);
        gpuPanel.Controls.Add(gpuNameArea);
        gpuPanel.Controls.Add(_gpuStatusLabel);
        gpuPanel.Controls.Add(gpuTitle);

        var topRowHeightPx = cpuTitle.Height + cpuTopRow.GetPreferredSize(Size.Empty).Height + chartHeightPx + (int)Math.Round(0.20 * DeviceDpi);
        var threadRowHeightPx = (int)Math.Round(1.15 * DeviceDpi);

        var topRow = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            Margin = Padding.Empty,
            Padding = Padding.Empty,
            ColumnCount = 2,
            RowCount = 1,
        };
        topRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50f));
        topRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50f));
        topRow.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
        topRow.Controls.Add(cpuPanel, 0, 0);
        topRow.Controls.Add(gpuPanel, 1, 0);

        gpuProcHost.Dock = DockStyle.None;
        gpuProcHost.Width = (chartWidthPx * 2) + 12;
        gpuProcHost.Margin = new Padding(0, 6, 0, 0);

        var bottomFlow = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Margin = Padding.Empty,
            Padding = Padding.Empty,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = true,
        };
        bottomFlow.Controls.Add(memHost);
        bottomFlow.Controls.Add(cHost);
        bottomFlow.Controls.Add(dHost);
        bottomFlow.Controls.Add(nHost);
        bottomFlow.Controls.Add(gpuProcHost);

        var bottomScrollHost = new Panel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true,
            Margin = Padding.Empty,
            Padding = Padding.Empty,
        };
        bottomScrollHost.Controls.Add(bottomFlow);

        var layoutRoot = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            Margin = Padding.Empty,
            Padding = Padding.Empty,
            ColumnCount = 1,
            RowCount = 3,
        };
        layoutRoot.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
        layoutRoot.RowStyles.Add(new RowStyle(SizeType.Absolute, topRowHeightPx));
        layoutRoot.RowStyles.Add(new RowStyle(SizeType.Absolute, threadRowHeightPx));
        layoutRoot.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
        layoutRoot.Controls.Add(topRow, 0, 0);
        layoutRoot.Controls.Add(threadRow, 0, 1);
        layoutRoot.Controls.Add(bottomScrollHost, 0, 2);

        cpuPage.Controls.Add(layoutRoot);

        bottomScrollHost.MouseEnter += (_, _) =>
        {
            try { bottomScrollHost.Focus(); } catch { }
        };
        EnableMouseWheelScrolling(bottomFlow, bottomScrollHost);

        _metricTabs.TabPages.Add(cpuPage);
        Controls.Add(_metricTabs);

        VisibleChanged += (_, _) => UpdateRefreshTimerState();
        HandleCreated += (_, _) => UpdateRefreshTimerState();
        HandleDestroyed += (_, _) => UpdateRefreshTimerState();

        RestartTelemetryLoop();
    }

    private static void CenterCpuInfoLine(
        FlowLayoutPanel row,
        Control leftSpacer,
        Label infoLabel,
        Control rightControl)
    {
        if (row.ClientSize.Width <= 0)
        {
            return;
        }

        var innerWidth = row.ClientSize.Width - row.Padding.Horizontal;
        if (innerWidth <= 0)
        {
            return;
        }

        var rightTotal = rightControl.Width + rightControl.Margin.Horizontal;
        var leftMargin = leftSpacer.Margin.Horizontal;
        var desiredLeftTotal = rightTotal;
        var leftWidth = Math.Max(0, desiredLeftTotal - leftMargin);

        if (leftSpacer.Width != leftWidth)
        {
            leftSpacer.Width = leftWidth;
        }

        var leftTotal = leftWidth + leftMargin;
        var infoTotal = innerWidth - leftTotal - rightTotal;
        var infoWidth = Math.Max(0, infoTotal - infoLabel.Margin.Horizontal);

        if (infoLabel.Width != infoWidth)
        {
            infoLabel.Width = infoWidth;
        }
    }

    private static void EnableMouseWheelScrolling(Control root, ScrollableControl scrollHost)
    {
        if (root is null || scrollHost is null)
        {
            return;
        }

        root.MouseWheel += (_, e) => ScrollByWheel(scrollHost, e);

        try
        {
            foreach (Control child in root.Controls)
            {
                EnableMouseWheelScrolling(child, scrollHost);
            }
        }
        catch
        {
        }
    }

    private static void ScrollByWheel(ScrollableControl scrollHost, MouseEventArgs e)
    {
        try
        {
            if (!scrollHost.VerticalScroll.Visible)
            {
                return;
            }

            var notches = e.Delta / 120;
            if (notches == 0)
            {
                notches = Math.Sign(e.Delta);
            }

            var lines = SystemInformation.MouseWheelScrollLines;
            if (lines <= 0)
            {
                lines = 3;
            }

            var step = scrollHost.VerticalScroll.SmallChange;
            if (step <= 0)
            {
                step = 30;
            }

            var delta = notches * lines * step;
            var next = scrollHost.VerticalScroll.Value - delta;
            next = Math.Clamp(next, scrollHost.VerticalScroll.Minimum, scrollHost.VerticalScroll.Maximum);
            scrollHost.VerticalScroll.Value = next;
            scrollHost.PerformLayout();
        }
        catch
        {
        }
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            try
            {
                _refreshTimer.Stop();
                _refreshTimer.Dispose();
                _memoryTimer.Stop();
                _memoryTimer.Dispose();
                _networkTimer.Stop();
                _networkTimer.Dispose();
            }
            catch
            {
            }
        }

        base.Dispose(disposing);
    }

    private void UpdateRefreshTimerState()
    {
        if (IsDisposed)
        {
            return;
        }

        var shouldRun = Visible;
        if (shouldRun)
        {
            _refreshTimer.Start();
            _memoryTimer.Start();
            _networkTimer.Start();
        }
        else
        {
            _refreshTimer.Stop();
            _memoryTimer.Stop();
            _networkTimer.Stop();
        }
    }

    private void RestartTelemetryLoop()
    {
        ProcessCpuUsageSampler.Shared.Reset();
        WindowsGpuPerfSession.Shared.Reset();
        LibreHardwareGpuSession.Shared.Reset();
        HwinfoSharedMemorySession.Shared.Reset();

        _snapshotInFlight = false;
        _memoryInFlight = false;
        _drivesInFlight = false;
        _networkInFlight = false;

        Array.Fill(_lastCoreUsage, null);
        Array.Fill(_lastCoreTempC, null);
        Array.Fill(_lastThreadUsage, null);
        _lastIntelGpuUsage = null;
        _lastIntelGpuTempC = null;
        _lastIntelGpuCpu = null;
        _lastNvidiaGpuUsage = null;
        _lastNvidiaGpuTempC = null;
        _lastNvidiaGpuCpu = null;
        _lastUsbProxyUsage = null;
        _lastUsbDriverCpu = null;
        _lastUsbIoMBps = null;

        _cpuStatusLabel.Text = "CPU Fan: n/a";
        _gpuStatusLabel.Text = "GPU Fan: n/a";
        _intelGpuNameLabel.Text = "Intel graphics";
        _nvidiaGpuNameLabel.Text = "NVIDIA GPU";

        UpdateRefreshTimerState();

        _ = SnapshotCpuAsync();
        _ = SnapshotMemoryAsync();
        _ = SnapshotDrivesAsync();
        _ = SnapshotNetworkAsync();

        _cpuStatusLabel.Invalidate();
        _cpuStatusLabel.Refresh();
        _gpuStatusLabel.Invalidate();
        _gpuStatusLabel.Refresh();
    }

    private async Task SnapshotCpuAsync()
    {
        if (_snapshotInFlight)
        {
            return;
        }

        _snapshotInFlight = true;
        try
        {
            var tempTask = Task.Run(_cpuProvider.Snapshot);
            var usageTask = Task.Run(() => _cpuUsageProvider.ReadCoreUsagePercentById(expectedCores: 8));
            var gpuTask = Task.Run(_gpuUsageProvider.Read);
            var fanTask = Task.Run(_fanSpeedProvider.Read);
            await Task.WhenAll(tempTask, usageTask, gpuTask, fanTask);

            var snapshot = tempTask.Result;
            var usageByCore = usageTask.Result;
            var gpu = gpuTask.Result;
            var fan = fanTask.Result;

            if (!IsDisposed)
            {
                var logicalLoads = _logicalCpuProvider.ReadUsagePercentPerLogicalProcessor();

                var coreTempsC = new double?[4];
                foreach (var core in snapshot.Cpu.Cores)
                {
                    if (core.Id < 0 || core.Id >= coreTempsC.Length)
                    {
                        continue;
                    }

                    coreTempsC[core.Id] = Math.Round(core.TempC, 1);
                }

                // Hold last known values if a particular sensor drops out for a tick.
                for (var i = 0; i < 4; i++)
                {
                    if (usageByCore.TryGetValue(i, out var use))
                    {
                        _lastCoreUsage[i] = use;
                    }

                    if (coreTempsC[i] is { } tc)
                    {
                        _lastCoreTempC[i] = tc;
                    }
                }

                for (var i = 0; i < _lastThreadUsage.Length; i++)
                {
                    if (i < logicalLoads.Length && logicalLoads[i] is { } logical)
                    {
                        _lastThreadUsage[i] = logical;
                    }
                    else if (usageByCore.TryGetValue(i, out var use))
                    {
                        _lastThreadUsage[i] = use;
                    }
                }

                var items = new GroupedBarItem[8];
                for (var i = 0; i < 4; i++)
                {
                    var group = "C" + (i + 1).ToString();
                    items[(i * 2) + 0] = new GroupedBarItem(group, "use", _lastCoreUsage[i]);
                    items[(i * 2) + 1] = new GroupedBarItem(group, "temp", _lastCoreTempC[i]);
                }

                _cpuCoreBars.SetItems(items);

                _cpuStatusLabel.Text = fan.CpuFanRpm is null ? "CPU Fan: n/a" : $"CPU Fan: {fan.CpuFanRpm.Value} RPM";
                _gpuStatusLabel.Text = fan.GpuFanRpm is null ? "GPU Fan: n/a" : $"GPU Fan: {fan.GpuFanRpm.Value} RPM";
                var intelName = string.IsNullOrWhiteSpace(gpu.Intel?.Name) ? "Intel graphics" : gpu.Intel!.Name!.Trim();
                var nvidiaName = string.IsNullOrWhiteSpace(gpu.Nvidia?.Name) ? "NVIDIA GPU" : gpu.Nvidia!.Name!.Trim();
                _intelGpuNameLabel.Text = intelName;
                _nvidiaGpuNameLabel.Text = nvidiaName;

                if (gpu.Intel?.CoreLoadPercent is { } igpuUse)
                {
                    _lastIntelGpuUsage = igpuUse;
                }

                if (gpu.Intel?.CoreTempC is { } igpuTempC)
                {
                    _lastIntelGpuTempC = Math.Round(igpuTempC, 1);
                }

                _lastIntelGpuCpu = gpu.Intel?.CpuPercent;

                if (gpu.Nvidia?.CoreLoadPercent is { } dgpuUse)
                {
                    _lastNvidiaGpuUsage = dgpuUse;
                }

                if (gpu.Nvidia?.CoreTempC is { } dgpuTempC)
                {
                    _lastNvidiaGpuTempC = Math.Round(dgpuTempC, 1);
                }

                _lastNvidiaGpuCpu = gpu.Nvidia?.CpuPercent;

                if (gpu.Usb?.CoreLoadPercent is { } usbProxy)
                {
                    _lastUsbProxyUsage = usbProxy;
                }
                else
                {
                    _lastUsbProxyUsage = 0d;
                }

                if (gpu.Usb?.CpuPercent is { } usbCpu)
                {
                    _lastUsbDriverCpu = usbCpu;
                }
                else
                {
                    _lastUsbDriverCpu = 0d;
                }

                _lastUsbIoMBps = Math.Round(Math.Max(0d, gpu.Usb?.IoBytesPerSec ?? 0d) / (1024d * 1024d), 1);

                // Per-group series:
                // - Intel: usage + temp + CPU
                // - NVIDIA: usage + temp + CPU
                // - USB: usage(proxy) + CPU + USB video activity MB/s
                _gpuBars.SetItems(new[]
                {
                    new GroupedBarItem("Intel", "use", _lastIntelGpuUsage),
                    new GroupedBarItem("Intel", "temp", _lastIntelGpuTempC),
                    new GroupedBarItem("Intel", "cpu", _lastIntelGpuCpu),
                    new GroupedBarItem("NVIDIA", "use", _lastNvidiaGpuUsage),
                    new GroupedBarItem("NVIDIA", "temp", _lastNvidiaGpuTempC),
                    new GroupedBarItem("NVIDIA", "cpu", _lastNvidiaGpuCpu),
                    new GroupedBarItem("USB", "use", _lastUsbProxyUsage),
                    new GroupedBarItem("USB", "cpu", _lastUsbDriverCpu),
                    new GroupedBarItem("USB", "usb", _lastUsbIoMBps),
                });

                UpdateGpuProcessList(gpu.Processes);

                for (var i = 0; i < _threadGauges.Length; i++)
                {
                    if (_lastThreadUsage[i] is { } v)
                    {
                        _threadGauges[i].Value = v;
                    }
                }

                // Status strip is reserved for fan RPM only.
            }
        }
        catch (Exception)
        {
            _cpuStatusLabel.Text = "CPU Fan: n/a";
            _gpuStatusLabel.Text = "GPU Fan: n/a";
        }
        finally
        {
            _snapshotInFlight = false;
        }
    }

    private async Task SnapshotMemoryAsync()
    {
        if (_memoryInFlight)
        {
            return;
        }

        _memoryInFlight = true;
        try
        {
            var snapshot = await Task.Run(_memoryProvider.Read);
            if (snapshot.TotalBytes > 0)
            {
                _lastMemory = snapshot;
            }

            if (IsDisposed || _lastMemory is null || _lastMemory.TotalBytes == 0)
            {
                return;
            }

            var total = (double)_lastMemory.TotalBytes;
            var used = (double)_lastMemory.UsedBytes;
            var modified = (double)_lastMemory.ModifiedBytes;
            var free = (double)_lastMemory.FreeBytes;

            // Normalize if anything is slightly off due to measurement differences.
            var sum = used + modified + free;
            if (sum > total && sum > 0)
            {
                var scale = total / sum;
                used *= scale;
                modified *= scale;
                free *= scale;
            }

            var totalGb = total / (1024d * 1024d * 1024d);
            _memoryBar.TitleRight = totalGb.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + " GB";
            _memoryBar.SetSegments(total, new[]
            {
                new StackedSegment("used", used, Color.FromArgb(0x34, 0x98, 0xDB)),     // blue
                new StackedSegment("modified", modified, Color.FromArgb(0x2E, 0xCC, 0x71)), // green
                new StackedSegment("free", free, Color.FromArgb(0x95, 0xA5, 0xA6)),     // gray
            });
        }
        catch
        {
        }
        finally
        {
            _memoryInFlight = false;
        }
    }

    private void UpdateGpuProcessList(System.Collections.Generic.IReadOnlyList<GpuProcessSnapshot>? processes)
    {
        if (IsDisposed)
        {
            return;
        }

        try
        {
            _gpuProcessList.BeginUpdate();
            _gpuProcessList.Items.Clear();
            _gpuProcessList.Groups.Clear();

            if (processes is null || processes.Count == 0)
            {
                return;
            }

            var orderedGroups = new[] { "Intel", "NVIDIA", "USB" };
            foreach (var groupName in orderedGroups)
            {
                var groupItems = processes.Where(p => string.Equals(p.GpuLabel, groupName, StringComparison.OrdinalIgnoreCase)).ToList();
                if (groupItems.Count == 0)
                {
                    continue;
                }

                var group = new ListViewGroup(groupName, HorizontalAlignment.Left);
                _gpuProcessList.Groups.Add(group);

                foreach (var p in groupItems)
                {
                    var procName = string.IsNullOrWhiteSpace(p.ProcessName) ? $"pid {p.ProcessId}" : p.ProcessName!.Trim();
                    var pidText = p.ProcessId <= 0 ? "n/a" : p.ProcessId.ToString(System.Globalization.CultureInfo.InvariantCulture);
                    var engText = string.IsNullOrWhiteSpace(p.EngineType) ? "n/a" : p.EngineType.Trim();
                    var gpuText = p.GpuPercent.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + "%";
                    var cpuText = p.CpuPercent is null ? "n/a" : p.CpuPercent.Value.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + "%";

                    var item = new ListViewItem(procName) { Group = group };
                    item.SubItems.Add(pidText);
                    item.SubItems.Add(engText);
                    item.SubItems.Add(gpuText);
                    item.SubItems.Add(cpuText);
                    _gpuProcessList.Items.Add(item);
                }
            }
        }
        catch
        {
        }
        finally
        {
            try
            {
                _gpuProcessList.EndUpdate();
            }
            catch
            {
            }
        }
    }

    private async Task SnapshotDrivesAsync()
    {
        if (_drivesInFlight)
        {
            return;
        }

        _drivesInFlight = true;
        try
        {
            var cTask = Task.Run(() => _driveProvider.Read("C:\\"));
            var dTask = Task.Run(() => _driveProvider.Read("D:\\"));
            await Task.WhenAll(cTask, dTask);

            if (cTask.Result.TotalBytes > 0)
            {
                _lastCDrive = cTask.Result;
            }

            if (dTask.Result.TotalBytes > 0)
            {
                _lastDDrive = dTask.Result;
            }

            if (IsDisposed)
            {
                return;
            }

            RenderDriveBar(_cDriveBar, _lastCDrive, defaultTitleLeft: "C:\\");
            RenderDriveBar(_dDriveBar, _lastDDrive, defaultTitleLeft: "D:\\");
        }
        catch
        {
        }
        finally
        {
            _drivesInFlight = false;
        }
    }

    private static void RenderDriveBar(StackedBarControl bar, DriveUsageSnapshot? snapshot, string defaultTitleLeft)
    {
        if (bar is null)
        {
            return;
        }

        if (snapshot is null || snapshot.TotalBytes == 0)
        {
            bar.TitleLeft = defaultTitleLeft;
            bar.TitleRight = "n/a";
            bar.SetSegments(1, Array.Empty<StackedSegment>());
            return;
        }

        var total = (double)snapshot.TotalBytes;
        var used = (double)snapshot.UsedBytes;
        var free = (double)snapshot.FreeBytes;

        var totalGb = total / (1024d * 1024d * 1024d);
        var freeGb = free / (1024d * 1024d * 1024d);
        var driveLabel = string.IsNullOrWhiteSpace(snapshot.DriveRoot) ? defaultTitleLeft : snapshot.DriveRoot.Trim();
        bar.TitleLeft = driveLabel + "  " + totalGb.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + " GB";
        bar.TitleRight = freeGb.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + " GB free";

        bar.SetSegments(total, new[]
        {
            new StackedSegment("used", used, Color.FromArgb(0x34, 0x98, 0xDB)), // blue
            new StackedSegment("free", free, Color.FromArgb(0x2E, 0xCC, 0x71)), // green
        });
    }

    private async Task SnapshotNetworkAsync()
    {
        if (_networkInFlight)
        {
            return;
        }

        _networkInFlight = true;
        try
        {
            var snapshot = await Task.Run(_networkProvider.Read);
            if (snapshot.TotalMbps > 0)
            {
                _lastNetwork = snapshot;
            }

            if (IsDisposed || _lastNetwork is null || _lastNetwork.TotalMbps <= 0)
            {
                _networkBar.TitleRight = "n/a";
                _networkBar.SetSegments(1, Array.Empty<StackedSegment>());
                return;
            }

            var used = _lastNetwork.UsedMbpsPerSecond;
            var total = _lastNetwork.TotalMbps;
            var usedClamped = used is null ? (double?)null : Math.Clamp(used.Value, 0d, total);

            _networkBar.TitleRight = (usedClamped is null
                ? total.ToString("0", System.Globalization.CultureInfo.InvariantCulture) + " Mbps"
                : usedClamped.Value.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + " / " + total.ToString("0", System.Globalization.CultureInfo.InvariantCulture) + " Mbps");

            _networkBar.SetSegments(total, usedClamped is null
                ? Array.Empty<StackedSegment>()
                : new[]
                {
                    new StackedSegment("used_s", usedClamped.Value, Color.FromArgb(0x2E, 0xCC, 0x71)), // green used/s
                });
        }
        catch
        {
        }
        finally
        {
            _networkInFlight = false;
        }
    }
}
