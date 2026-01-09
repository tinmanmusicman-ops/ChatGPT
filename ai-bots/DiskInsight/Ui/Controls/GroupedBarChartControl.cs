using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Linq;
using System.Windows.Forms;

namespace DiskInsight.Ui.Controls;

public sealed class GroupedBarChartControl : Control
{
    private string _title = "";
    private bool _showValueLabels;
    private bool _enableAnimations = true;
    private int _animationDurationMs = 350;
    private List<BarSeries> _series = new();
    private List<GroupedBarItem> _items = new();
    private List<double?> _displayValues = new();
    private List<double?>? _animFrom;
    private List<double?>? _animTo;
    private long _animStartTicks;
    private readonly System.Windows.Forms.Timer _animTimer;

    private sealed record RenderSlot(string Group, string SeriesKey, double? Value);

    public GroupedBarChartControl()
    {
        SetStyle(
            ControlStyles.UserPaint |
            ControlStyles.AllPaintingInWmPaint |
            ControlStyles.OptimizedDoubleBuffer |
            ControlStyles.ResizeRedraw, true);

        ForeColor = SystemColors.ControlText;
        BackColor = SystemColors.Window;

        _animTimer = new System.Windows.Forms.Timer
        {
            Interval = 16,
            Enabled = false,
        };
        _animTimer.Tick += (_, _) => TickAnimation();
    }

    [Category("Appearance")]
    public string Title
    {
        get => _title;
        set
        {
            _title = value ?? "";
            Invalidate();
        }
    }

    [Category("Appearance")]
    public bool ShowValueLabels
    {
        get => _showValueLabels;
        set
        {
            _showValueLabels = value;
            Invalidate();
        }
    }

    [Category("Behavior")]
    public bool EnableAnimations
    {
        get => _enableAnimations;
        set
        {
            _enableAnimations = value;
            if (!_enableAnimations)
            {
                StopAnimation();
            }
            Invalidate();
        }
    }

    [Category("Behavior")]
    public int AnimationDurationMs
    {
        get => _animationDurationMs;
        set
        {
            _animationDurationMs = Math.Clamp(value, 0, 5_000);
            Invalidate();
        }
    }

    [Browsable(false)]
    public IReadOnlyList<BarSeries> Series => _series;

    [Browsable(false)]
    public IReadOnlyList<GroupedBarItem> Items => _items;

    public void SetSeries(IEnumerable<BarSeries> series)
    {
        _series = (series ?? Enumerable.Empty<BarSeries>())
            .Where(s => !string.IsNullOrWhiteSpace(s.Key))
            .GroupBy(s => s.Key, StringComparer.OrdinalIgnoreCase)
            .Select(g => g.First())
            .ToList();
        Invalidate();
    }

    public void SetItems(IEnumerable<GroupedBarItem> items)
    {
        var nextItems = (items ?? Enumerable.Empty<GroupedBarItem>()).ToList();
        _items = nextItems;

        // Values are animated in the same order they are rendered (group order, then series order).
        var nextValues = BuildRenderSlots(nextItems).Select(s => s.Value).ToList();

        if (!_enableAnimations || _animationDurationMs <= 0 || _displayValues.Count == 0)
        {
            StopAnimation();
            _displayValues = nextValues;
            Invalidate();
            return;
        }

        var from = new List<double?>(capacity: nextValues.Count);
        var to = new List<double?>(capacity: nextValues.Count);
        var willAnimate = false;

        for (var i = 0; i < nextValues.Count; i++)
        {
            var cur = i < _displayValues.Count ? _displayValues[i] : null;
            var nxt = nextValues[i];

            from.Add(cur);
            to.Add(nxt);

            if (cur is not null && nxt is not null && Math.Abs(cur.Value - nxt.Value) > 0.01)
            {
                willAnimate = true;
            }
        }

        if (!willAnimate)
        {
            StopAnimation();
            _displayValues = nextValues;
            Invalidate();
            return;
        }

        _animFrom = from;
        _animTo = to;
        _animStartTicks = Environment.TickCount64;
        _animTimer.Start();
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);

        var g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.Clear(BackColor);

        var rect = ClientRectangle;
        if (rect.Width <= 2 || rect.Height <= 2)
        {
            return;
        }

        using var borderPen = new Pen(Color.FromArgb(50, ForeColor), 1f);
        g.DrawRectangle(borderPen, rect.Left, rect.Top, rect.Width - 1, rect.Height - 1);

        using var titleFont = new Font(Font, FontStyle.Bold);
        using var axisFont = new Font(Font.FontFamily, Math.Max(7f, Font.SizeInPoints - 1f), FontStyle.Regular);
        using var labelBrush = new SolidBrush(Color.FromArgb(170, ForeColor));

        var titleHeight = 0;
        if (!string.IsNullOrWhiteSpace(_title))
        {
            titleHeight = TextRenderer.MeasureText(_title, titleFont).Height;
            TextRenderer.DrawText(g, _title, titleFont, new Point(6, 4), ForeColor);
        }

        var plotTop = 6 + (titleHeight > 0 ? titleHeight + 2 : 0);
        var seriesLabelHeight = axisFont.Height + 2;
        var groupLabelHeight = axisFont.Height + 2;
        var valueLabelHeight = _showValueLabels ? axisFont.Height + 2 : 0;

        var plot = Rectangle.FromLTRB(
            rect.Left + 6,
            plotTop + valueLabelHeight,
            rect.Right - 6,
            rect.Bottom - 6 - seriesLabelHeight - groupLabelHeight);

        if (plot.Width <= 10 || plot.Height <= 10)
        {
            return;
        }

        DrawGroupedBars(g, plot, axisFont, labelBrush);
    }

    private void DrawGroupedBars(Graphics g, Rectangle plot, Font axisFont, Brush labelBrush)
    {
        if (_items.Count == 0 || _series.Count == 0)
        {
            return;
        }

        var seriesByKey = new Dictionary<string, BarSeries>(StringComparer.OrdinalIgnoreCase);
        foreach (var s in _series)
        {
            seriesByKey[s.Key] = s;
        }

        var groupsInOrder = new List<string>(capacity: 8);
        var groupSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var item in _items)
        {
            if (string.IsNullOrWhiteSpace(item.Group))
            {
                continue;
            }

            if (groupSet.Add(item.Group))
            {
                groupsInOrder.Add(item.Group);
            }
        }

        if (groupsInOrder.Count == 0)
        {
            return;
        }

        var seriesInOrder = _series.Select(s => s.Key).ToList();

        var itemsByGroup = _items
            .Where(i => !string.IsNullOrWhiteSpace(i.Group) && !string.IsNullOrWhiteSpace(i.SeriesKey))
            .GroupBy(i => i.Group, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(
                g => g.Key,
                g => g.ToDictionary(i => i.SeriesKey, i => i, StringComparer.OrdinalIgnoreCase),
                StringComparer.OrdinalIgnoreCase);

        var seriesKeysByGroup = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
        var groupsToRender = new List<string>(capacity: groupsInOrder.Count);
        var totalBars = 0;

        for (var i = 0; i < groupsInOrder.Count; i++)
        {
            var group = groupsInOrder[i];
            if (!itemsByGroup.TryGetValue(group, out var groupItems) || groupItems is null)
            {
                continue;
            }

            var keys = seriesInOrder.Where(k => groupItems.ContainsKey(k)).ToList();
            if (keys.Count == 0)
            {
                continue;
            }

            seriesKeysByGroup[group] = keys;
            groupsToRender.Add(group);
            totalBars += keys.Count;
        }

        if (totalBars == 0)
        {
            return;
        }

        var groupCount = groupsToRender.Count;
        var groupGap = Math.Clamp(plot.Width / (groupCount * 6), 4, 18);
        var barGap = Math.Clamp(groupGap / 2, 2, 10);

        var totalGap = (groupGap * (groupCount + 1)) + (barGap * Math.Max(0, totalBars - groupCount));
        var barWidth = Math.Max(4, (plot.Width - totalGap) / Math.Max(1, totalBars));

        var seriesLabelHeight = axisFont.Height + 2;

        // If we can't fit, shrink gaps before shrinking bars too far.
        while (barWidth < 4 && groupGap > 4)
        {
            groupGap--;
            barGap = Math.Max(2, groupGap / 2);
            totalGap = (groupGap * (groupCount + 1)) + (barGap * Math.Max(0, totalBars - groupCount));
            barWidth = Math.Max(4, (plot.Width - totalGap) / Math.Max(1, totalBars));
        }

        using var outlinePen = new Pen(Color.FromArgb(70, ForeColor), 1f);
        using var valueBrush = new SolidBrush(ForeColor);
        using var naBrush = new SolidBrush(Color.FromArgb(150, ForeColor));
        using var valueSf = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Far };
        using var groupSf = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Near };
        using var seriesSf = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Near };

        var x = plot.Left + groupGap;
        var itemIndex = 0;

        for (var groupIdx = 0; groupIdx < groupCount; groupIdx++)
        {
            var group = groupsToRender[groupIdx];
            var groupStartX = x;

            itemsByGroup.TryGetValue(group, out var groupItems);
            seriesKeysByGroup.TryGetValue(group, out var groupSeries);
            groupSeries ??= new List<string>();

            for (var seriesIdx = 0; seriesIdx < groupSeries.Count; seriesIdx++)
            {
                var seriesKey = groupSeries[seriesIdx];
                if (!seriesByKey.TryGetValue(seriesKey, out var series))
                {
                    continue;
                }

                GroupedBarItem? item = null;
                if (groupItems is not null)
                {
                    groupItems.TryGetValue(seriesKey, out item);
                }

                var barRect = new Rectangle(x, plot.Top, barWidth, plot.Height);
                g.DrawRectangle(outlinePen, barRect);

                var displayValue = itemIndex < _displayValues.Count ? _displayValues[itemIndex] : item?.Value;
                itemIndex++;

                if (displayValue is not null && series.Maximum > series.Minimum)
                {
                    var v = Clamp(displayValue.Value, series.Minimum, series.Maximum);
                    var t = (v - series.Minimum) / (series.Maximum - series.Minimum);
                    t = Clamp(t, 0, 1);

                    var fillH = (int)Math.Round(t * plot.Height);
                    var fillRect = new Rectangle(x + 1, plot.Bottom - fillH + 1, barWidth - 1, Math.Max(0, fillH - 1));

                    var color = series.GetRangeColor(v);
                    using (var brush = new SolidBrush(color))
                    {
                        g.FillRectangle(brush, fillRect);
                    }

                    if (_showValueLabels)
                    {
                        var text = v.ToString(series.ValueFormat) + series.Units;
                        g.DrawString(text, axisFont, valueBrush, new RectangleF(x, plot.Top - axisFont.Height - 2, barWidth, axisFont.Height), valueSf);
                    }
                }
                else if (_showValueLabels && displayValue is null)
                {
                    g.DrawString("n/a", axisFont, naBrush, new RectangleF(x, plot.Top - axisFont.Height - 2, barWidth, axisFont.Height), valueSf);
                }

                var seriesLabel = string.IsNullOrWhiteSpace(series.DisplayLabel) ? series.Key : series.DisplayLabel;
                g.DrawString(seriesLabel, axisFont, labelBrush, new RectangleF(x, plot.Bottom + 2, barWidth, axisFont.Height), seriesSf);

                x += barWidth;
                if (seriesIdx < groupSeries.Count - 1)
                {
                    x += barGap;
                }
            }

            var groupEndX = x;
            var groupWidth = Math.Max(1, groupEndX - groupStartX);
            g.DrawString(
                group,
                axisFont,
                labelBrush,
                new RectangleF(groupStartX, plot.Bottom + 2 + seriesLabelHeight, groupWidth, axisFont.Height),
                groupSf);

            x += groupGap;
        }
    }

    private static double Clamp(double v, double min, double max) => v < min ? min : v > max ? max : v;

    private IReadOnlyList<RenderSlot> BuildRenderSlots(IReadOnlyList<GroupedBarItem> items)
    {
        if (items.Count == 0 || _series.Count == 0)
        {
            return Array.Empty<RenderSlot>();
        }

        var seriesInOrder = _series.Select(s => s.Key).ToList();

        var groupsInOrder = new List<string>(capacity: 8);
        var groupSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var item in items)
        {
            if (string.IsNullOrWhiteSpace(item.Group))
            {
                continue;
            }

            if (groupSet.Add(item.Group))
            {
                groupsInOrder.Add(item.Group);
            }
        }

        var itemsByGroup = items
            .Where(i => !string.IsNullOrWhiteSpace(i.Group) && !string.IsNullOrWhiteSpace(i.SeriesKey))
            .GroupBy(i => i.Group, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(
                g => g.Key,
                g => g.ToDictionary(i => i.SeriesKey, i => i, StringComparer.OrdinalIgnoreCase),
                StringComparer.OrdinalIgnoreCase);

        var slots = new List<RenderSlot>(capacity: items.Count);
        for (var gi = 0; gi < groupsInOrder.Count; gi++)
        {
            var group = groupsInOrder[gi];
            if (!itemsByGroup.TryGetValue(group, out var groupItems) || groupItems is null)
            {
                continue;
            }

            for (var si = 0; si < seriesInOrder.Count; si++)
            {
                var seriesKey = seriesInOrder[si];
                if (!groupItems.TryGetValue(seriesKey, out var item))
                {
                    continue;
                }

                slots.Add(new RenderSlot(group, seriesKey, item.Value));
            }
        }

        return slots;
    }

    private void TickAnimation()
    {
        if (_animFrom is null || _animTo is null || _animationDurationMs <= 0)
        {
            StopAnimation();
            return;
        }

        var elapsed = Environment.TickCount64 - _animStartTicks;
        var t = Math.Clamp(elapsed / (double)_animationDurationMs, 0d, 1d);
        t = t * t * (3d - (2d * t));

        var count = _animTo.Count;
        if (_displayValues.Count != count)
        {
            _displayValues = Enumerable.Repeat<double?>(null, count).ToList();
        }

        for (var i = 0; i < count; i++)
        {
            var from = i < _animFrom.Count ? _animFrom[i] : null;
            var to = _animTo[i];

            if (from is null || to is null)
            {
                _displayValues[i] = to;
                continue;
            }

            _displayValues[i] = (from.Value * (1d - t)) + (to.Value * t);
        }

        if (elapsed >= _animationDurationMs)
        {
            _displayValues = _animTo.ToList();
            StopAnimation();
        }

        Invalidate();
    }

    private void StopAnimation()
    {
        try
        {
            _animTimer.Stop();
        }
        catch
        {
        }

        _animFrom = null;
        _animTo = null;
    }
}

public sealed record BarSeries(
    string Key,
    double Minimum,
    double Maximum,
    string Units,
    string ValueFormat,
    IReadOnlyList<GaugeRange> Ranges,
    string DisplayLabel)
{
    public Color GetRangeColor(double value)
    {
        foreach (var range in Ranges)
        {
            if (value >= range.StartValue && value < range.EndValue)
            {
                return range.Color;
            }
        }

        if (Ranges.Count > 0 && value >= Ranges[^1].EndValue)
        {
            return Ranges[^1].Color;
        }

        return Color.FromArgb(0x2E, 0x86, 0xC1);
    }
}

public sealed record GroupedBarItem(string Group, string SeriesKey, double? Value);
