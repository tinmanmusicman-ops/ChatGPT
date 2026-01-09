using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Linq;
using System.Windows.Forms;

namespace DiskInsight.Ui.Controls;

public sealed class VerticalBarChartControl : Control
{
    private double _minimum = 0;
    private double _maximum = 100;
    private string _title = "";
    private string _units = "";
    private string _valueFormat = "0.0";
    private bool _showValueLabels = true;
    private List<GaugeRange> _ranges = new();
    private List<BarItem> _items = new();
    private List<double?> _displayValues = new();
    private List<double?>? _animFrom;
    private List<double?>? _animTo;
    private long _animStartTicks;
    private readonly System.Windows.Forms.Timer _animTimer;
    private int _animationDurationMs = 350;
    private bool _enableAnimations = true;

    public VerticalBarChartControl()
    {
        SetStyle(
            ControlStyles.UserPaint |
            ControlStyles.AllPaintingInWmPaint |
            ControlStyles.OptimizedDoubleBuffer |
            ControlStyles.ResizeRedraw, true);

        ForeColor = SystemColors.ControlText;
        BackColor = SystemColors.Window;

        _ranges = new List<GaugeRange>
        {
            new(0, 70, Color.FromArgb(0x2E, 0xCC, 0x71)),
            new(70, 85, Color.FromArgb(0xF1, 0xC4, 0x0F)),
            new(85, 100, Color.FromArgb(0xE7, 0x4C, 0x3C)),
        };

        _animTimer = new System.Windows.Forms.Timer
        {
            Interval = 16,
            Enabled = false,
        };
        _animTimer.Tick += (_, _) => TickAnimation();
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

    [Category("Behavior")]
    public double Minimum
    {
        get => _minimum;
        set
        {
            _minimum = value;
            if (_maximum < _minimum)
            {
                _maximum = _minimum;
            }
            Invalidate();
        }
    }

    [Category("Behavior")]
    public double Maximum
    {
        get => _maximum;
        set
        {
            _maximum = value;
            if (_maximum < _minimum)
            {
                _minimum = _maximum;
            }
            Invalidate();
        }
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
    public string Units
    {
        get => _units;
        set
        {
            _units = value ?? "";
            Invalidate();
        }
    }

    [Category("Appearance")]
    public string ValueFormat
    {
        get => _valueFormat;
        set
        {
            _valueFormat = string.IsNullOrWhiteSpace(value) ? "0.0" : value;
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

    [Browsable(false)]
    public IReadOnlyList<GaugeRange> Ranges => _ranges;

    [Browsable(false)]
    public IReadOnlyList<BarItem> Items => _items;

    public void SetRanges(IEnumerable<GaugeRange> ranges)
    {
        _ranges = (ranges ?? Enumerable.Empty<GaugeRange>())
            .Where(r => r.EndValue > r.StartValue)
            .OrderBy(r => r.StartValue)
            .ToList();
        Invalidate();
    }

    public void SetItems(IEnumerable<BarItem> items)
    {
        var nextItems = (items ?? Enumerable.Empty<BarItem>())
            .ToList();
        _items = nextItems;

        var nextValues = nextItems.Select(i => i.Value).ToList();

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
        Invalidate();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            try
            {
                _animTimer.Stop();
                _animTimer.Dispose();
            }
            catch
            {
            }
        }
        base.Dispose(disposing);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);

        var g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.Clear(BackColor);

        if (ClientSize.Width < 120 || ClientSize.Height < 100)
        {
            return;
        }

        using var titleFont = new Font(Font.FontFamily, Math.Max(9f, Font.Size + 1f), FontStyle.Bold);
        using var axisFont = new Font(Font.FontFamily, Math.Max(8f, Font.Size - 1f), FontStyle.Regular);
        using var labelFont = new Font(FontFamily.GenericMonospace, Math.Max(8f, Font.Size - 1f), FontStyle.Regular);

        var topPad = 8;
        var titleHeight = string.IsNullOrWhiteSpace(_title) ? 0 : (int)Math.Ceiling(g.MeasureString(_title, titleFont).Height) + 4;

        var leftPad = 34;
        var rightPad = 10;
        var bottomPad = 22;
        if (_showValueLabels)
        {
            topPad += 14;
        }

        var plot = new Rectangle(
            x: leftPad,
            y: topPad + titleHeight,
            width: Math.Max(1, ClientSize.Width - leftPad - rightPad),
            height: Math.Max(1, ClientSize.Height - (topPad + titleHeight) - bottomPad));

        if (!string.IsNullOrWhiteSpace(_title))
        {
            using var titleBrush = new SolidBrush(ForeColor);
            g.DrawString(_title, titleFont, titleBrush, new RectangleF(0, 4, ClientSize.Width, titleHeight),
                new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Near });
        }

        DrawAxis(g, plot, axisFont);
        DrawBars(g, plot, axisFont, labelFont);
    }

    private void DrawAxis(Graphics g, Rectangle plot, Font axisFont)
    {
        using var axisPen = new Pen(Color.FromArgb(90, ForeColor), 1f);
        g.DrawRectangle(axisPen, plot);

        if (_maximum <= _minimum)
        {
            return;
        }

        var ticks = 4;
        using var tickPen = new Pen(Color.FromArgb(60, ForeColor), 1f);
        using var brush = new SolidBrush(Color.FromArgb(140, ForeColor));
        using var sf = new StringFormat { Alignment = StringAlignment.Far, LineAlignment = StringAlignment.Center };

        for (var i = 0; i <= ticks; i++)
        {
            var t = ticks == 0 ? 0d : i / (double)ticks;
            var y = plot.Top + (int)Math.Round((1d - t) * plot.Height);

            g.DrawLine(tickPen, plot.Left, y, plot.Right, y);

            var v = _minimum + ((_maximum - _minimum) * t);
            var label = v.ToString("0");
            g.DrawString(label, axisFont, brush, new RectangleF(0, y - 10, plot.Left - 4, 20), sf);
        }
    }

    private void DrawBars(Graphics g, Rectangle plot, Font axisFont, Font labelFont)
    {
        if (_items.Count == 0 || _maximum <= _minimum)
        {
            return;
        }

        var barCount = _items.Count;
        var gap = Math.Max(4, plot.Width / (barCount * 10));
        var barWidth = Math.Max(8, (plot.Width - (gap * (barCount + 1))) / barCount);
        if ((barWidth * barCount) + (gap * (barCount + 1)) > plot.Width)
        {
            barWidth = Math.Max(6, barWidth - 1);
        }

        using var labelBrush = new SolidBrush(Color.FromArgb(170, ForeColor));
        using var valueBrush = new SolidBrush(ForeColor);
        using var outlinePen = new Pen(Color.FromArgb(70, ForeColor), 1f);
        using var valueSf = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Far };
        using var labelSf = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Near };

        for (var i = 0; i < barCount; i++)
        {
            var item = _items[i];
            var x = plot.Left + gap + (i * (barWidth + gap));
            var barRect = new Rectangle(x, plot.Top, barWidth, plot.Height);

            g.DrawRectangle(outlinePen, barRect);

            var displayValue = i < _displayValues.Count ? _displayValues[i] : item.Value;
            if (displayValue is null)
            {
                g.DrawString(item.Label, axisFont, labelBrush, new RectangleF(x, plot.Bottom + 2, barWidth, 18), labelSf);
                continue;
            }

            var v = Clamp(displayValue.Value, _minimum, _maximum);
            var t = (v - _minimum) / (_maximum - _minimum);
            t = Clamp(t, 0, 1);

            var fillH = (int)Math.Round(t * plot.Height);
            var fillRect = new Rectangle(x + 1, plot.Bottom - fillH + 1, barWidth - 1, Math.Max(0, fillH - 1));

            var color = GetRangeColor(v);
            using (var brush = new SolidBrush(color))
            {
                g.FillRectangle(brush, fillRect);
            }

            if (_showValueLabels)
            {
                var text = v.ToString(_valueFormat) + _units;
                g.DrawString(text, axisFont, valueBrush, new RectangleF(x, plot.Top - 16, barWidth, 14), valueSf);
            }

            g.DrawString(item.Label, axisFont, labelBrush, new RectangleF(x, plot.Bottom + 2, barWidth, 18), labelSf);
        }
    }

    private Color GetRangeColor(double value)
    {
        foreach (var range in _ranges)
        {
            if (value >= range.StartValue && value < range.EndValue)
            {
                return range.Color;
            }
        }

        if (_ranges.Count > 0 && value >= _ranges[^1].EndValue)
        {
            return _ranges[^1].Color;
        }

        return Color.FromArgb(0x2E, 0x86, 0xC1);
    }

    private static double Clamp(double v, double min, double max) => v < min ? min : v > max ? max : v;

    private void TickAnimation()
    {
        if (_animFrom is null || _animTo is null || _animationDurationMs <= 0)
        {
            StopAnimation();
            return;
        }

        var elapsed = Environment.TickCount64 - _animStartTicks;
        var t = Math.Clamp(elapsed / (double)_animationDurationMs, 0d, 1d);
        // Smoothstep easing.
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

public sealed record BarItem(string Label, double? Value);
