using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Linq;
using System.Windows.Forms;

namespace DiskInsight.Ui.Controls;

public sealed class GaugeControl : Control
{
    private double _minimum = 0;
    private double _maximum = 100;
    private double _value;
    private string _title = "";
    private string _units = "";
    private string _valueFormat = "0.0";
    private List<GaugeRange> _ranges = new();

    public GaugeControl()
    {
        SetStyle(
            ControlStyles.UserPaint |
            ControlStyles.AllPaintingInWmPaint |
            ControlStyles.OptimizedDoubleBuffer |
            ControlStyles.ResizeRedraw, true);

        Size = new Size(220, 220);
        ForeColor = SystemColors.ControlText;
        BackColor = SystemColors.Window;

        _ranges = new List<GaugeRange>
        {
            new(0, 70, Color.FromArgb(0x2E, 0xCC, 0x71)),
            new(70, 85, Color.FromArgb(0xF1, 0xC4, 0x0F)),
            new(85, 100, Color.FromArgb(0xE7, 0x4C, 0x3C)),
        };
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
            _value = Clamp(_value, _minimum, _maximum);
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
            _value = Clamp(_value, _minimum, _maximum);
            Invalidate();
        }
    }

    [Category("Behavior")]
    public double Value
    {
        get => _value;
        set
        {
            var next = Clamp(value, _minimum, _maximum);
            if (Math.Abs(next - _value) < 1e-9)
            {
                return;
            }
            _value = next;
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

    [Browsable(false)]
    public IReadOnlyList<GaugeRange> Ranges => _ranges;

    public void SetRanges(IEnumerable<GaugeRange> ranges)
    {
        _ranges = (ranges ?? Enumerable.Empty<GaugeRange>())
            .Where(r => r.EndValue > r.StartValue)
            .OrderBy(r => r.StartValue)
            .ToList();
        Invalidate();
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);

        var g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.Clear(BackColor);

        var size = Math.Min(ClientSize.Width, ClientSize.Height);
        if (size < 80)
        {
            return;
        }

        var padding = 10;
        var diameter = size - (padding * 2);
        var cx = ClientRectangle.Left + (ClientSize.Width / 2f);
        var cy = ClientRectangle.Top + (ClientSize.Height / 2f);

        var rect = new RectangleF(
            x: cx - (diameter / 2f),
            y: cy - (diameter / 2f),
            width: diameter,
            height: diameter);

        const float startAngle = 150f;
        const float sweepAngle = 240f;

        using (var outlinePen = new Pen(Color.FromArgb(40, ForeColor), 1f))
        {
            g.DrawEllipse(outlinePen, rect);
        }

        var ringThickness = Math.Max(8f, diameter * 0.08f);
        DrawRanges(g, rect, startAngle, sweepAngle, ringThickness);
        DrawTicks(g, rect, startAngle, sweepAngle);
        DrawNeedle(g, rect, startAngle, sweepAngle);
        DrawText(g, rect);
    }

    private void DrawRanges(Graphics g, RectangleF rect, float startAngle, float sweepAngle, float thickness)
    {
        if (_ranges.Count == 0 || _maximum <= _minimum)
        {
            return;
        }

        foreach (var range in _ranges)
        {
            var start = Clamp(range.StartValue, _minimum, _maximum);
            var end = Clamp(range.EndValue, _minimum, _maximum);
            if (end <= start)
            {
                continue;
            }

            var a0 = MapToAngle(start, startAngle, sweepAngle);
            var a1 = MapToAngle(end, startAngle, sweepAngle);
            var sweep = a1 - a0;
            if (sweep <= 0)
            {
                continue;
            }

            using var pen = new Pen(range.Color, thickness)
            {
                StartCap = LineCap.Round,
                EndCap = LineCap.Round,
            };
            g.DrawArc(pen, rect, a0, sweep);
        }
    }

    private void DrawTicks(Graphics g, RectangleF rect, float startAngle, float sweepAngle)
    {
        if (_maximum <= _minimum)
        {
            return;
        }

        var center = new PointF(rect.Left + rect.Width / 2f, rect.Top + rect.Height / 2f);
        var radius = rect.Width / 2f;

        var majorTicks = 10;
        var minorPerMajor = 4;

        using var majorPen = new Pen(Color.FromArgb(120, ForeColor), 2f);
        using var minorPen = new Pen(Color.FromArgb(90, ForeColor), 1f);

        for (var major = 0; major <= majorTicks; major++)
        {
            var t = majorTicks == 0 ? 0f : (float)major / majorTicks;
            var angle = DegreesToRadians(startAngle + (sweepAngle * t));
            DrawTick(g, center, radius, angle, inner: 0.82f, outer: 0.92f, majorPen);

            if (major == majorTicks)
            {
                continue;
            }

            for (var minor = 1; minor <= minorPerMajor; minor++)
            {
                var tt = (float)(major + (minor / (double)(minorPerMajor + 1))) / majorTicks;
                var a = DegreesToRadians(startAngle + (sweepAngle * tt));
                DrawTick(g, center, radius, a, inner: 0.86f, outer: 0.92f, minorPen);
            }
        }
    }

    private static void DrawTick(Graphics g, PointF center, float radius, float angleRad, float inner, float outer, Pen pen)
    {
        var sin = (float)Math.Sin(angleRad);
        var cos = (float)Math.Cos(angleRad);

        var p0 = new PointF(center.X + (radius * inner * cos), center.Y + (radius * inner * sin));
        var p1 = new PointF(center.X + (radius * outer * cos), center.Y + (radius * outer * sin));
        g.DrawLine(pen, p0, p1);
    }

    private void DrawNeedle(Graphics g, RectangleF rect, float startAngle, float sweepAngle)
    {
        if (_maximum <= _minimum)
        {
            return;
        }

        var center = new PointF(rect.Left + rect.Width / 2f, rect.Top + rect.Height / 2f);
        var radius = rect.Width / 2f;

        var angleDeg = MapToAngle(_value, startAngle, sweepAngle);
        var angleRad = DegreesToRadians(angleDeg);
        var sin = (float)Math.Sin(angleRad);
        var cos = (float)Math.Cos(angleRad);

        var needleLen = radius * 0.78f;
        var end = new PointF(center.X + (needleLen * cos), center.Y + (needleLen * sin));

        using var needlePen = new Pen(Color.FromArgb(220, ForeColor), 3f)
        {
            StartCap = LineCap.Round,
            EndCap = LineCap.Round,
        };
        g.DrawLine(needlePen, center, end);

        using var hubBrush = new SolidBrush(Color.FromArgb(230, ForeColor));
        var hubR = Math.Max(5f, radius * 0.06f);
        g.FillEllipse(hubBrush, center.X - hubR, center.Y - hubR, hubR * 2, hubR * 2);
    }

    private void DrawText(Graphics g, RectangleF rect)
    {
        var center = new PointF(rect.Left + rect.Width / 2f, rect.Top + rect.Height / 2f);
        var radius = rect.Width / 2f;

        var valueText = _value.ToString(_valueFormat) + (string.IsNullOrWhiteSpace(_units) ? "" : $" {_units}");

        using var sf = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center };

        using var valueFont = new Font(Font.FontFamily, Math.Max(9f, Font.Size + 2f), FontStyle.Bold);
        using var labelFont = new Font(Font.FontFamily, Math.Max(8f, Font.Size - 1f), FontStyle.Regular);

        g.DrawString(valueText, valueFont, new SolidBrush(ForeColor), new PointF(center.X, center.Y + radius * 0.20f), sf);

        if (!string.IsNullOrWhiteSpace(_title))
        {
            g.DrawString(_title, labelFont, new SolidBrush(Color.FromArgb(170, ForeColor)),
                new PointF(center.X, center.Y + radius * 0.42f), sf);
        }

        var minText = _minimum.ToString("0");
        var maxText = _maximum.ToString("0");

        var minPt = PointOnCircle(center, radius * 0.95f, DegreesToRadians(150f));
        var maxPt = PointOnCircle(center, radius * 0.95f, DegreesToRadians(30f));

        using var minMaxBrush = new SolidBrush(Color.FromArgb(140, ForeColor));
        g.DrawString(minText, labelFont, minMaxBrush, minPt, sf);
        g.DrawString(maxText, labelFont, minMaxBrush, maxPt, sf);
    }

    private float MapToAngle(double value, float startAngle, float sweepAngle)
    {
        if (_maximum <= _minimum)
        {
            return startAngle;
        }
        var t = (value - _minimum) / (_maximum - _minimum);
        t = Clamp(t, 0, 1);
        return startAngle + (float)(sweepAngle * t);
    }

    private static double Clamp(double v, double min, double max) => v < min ? min : v > max ? max : v;

    private static float DegreesToRadians(float degrees) => degrees * (float)(Math.PI / 180d);

    private static PointF PointOnCircle(PointF center, float radius, float angleRad)
    {
        var sin = (float)Math.Sin(angleRad);
        var cos = (float)Math.Cos(angleRad);
        return new PointF(center.X + (radius * cos), center.Y + (radius * sin));
    }
}

public sealed record GaugeRange(double StartValue, double EndValue, Color Color);

