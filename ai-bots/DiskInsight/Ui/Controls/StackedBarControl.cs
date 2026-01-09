using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Linq;
using System.Windows.Forms;

namespace DiskInsight.Ui.Controls;

public sealed class StackedBarControl : Control
{
    private string _titleLeft = "";
    private string _titleRight = "";
    private List<StackedSegment> _segments = new();
    private double _total = 1d;
    private bool _fillBarBackground;
    private Color _barBackgroundColor = Color.FromArgb(0x34, 0x98, 0xDB);

    public StackedBarControl()
    {
        SetStyle(
            ControlStyles.UserPaint |
            ControlStyles.AllPaintingInWmPaint |
            ControlStyles.OptimizedDoubleBuffer |
            ControlStyles.ResizeRedraw, true);

        ForeColor = SystemColors.ControlText;
        BackColor = SystemColors.Window;
    }

    [Category("Appearance")]
    public string TitleLeft
    {
        get => _titleLeft;
        set
        {
            _titleLeft = value ?? "";
            Invalidate();
        }
    }

    [Category("Appearance")]
    public string TitleRight
    {
        get => _titleRight;
        set
        {
            _titleRight = value ?? "";
            Invalidate();
        }
    }

    [Browsable(false)]
    public IReadOnlyList<StackedSegment> Segments => _segments;

    [Browsable(false)]
    public double Total => _total;

    [Category("Appearance")]
    public bool FillBarBackground
    {
        get => _fillBarBackground;
        set
        {
            _fillBarBackground = value;
            Invalidate();
        }
    }

    [Category("Appearance")]
    public Color BarBackgroundColor
    {
        get => _barBackgroundColor;
        set
        {
            _barBackgroundColor = value;
            Invalidate();
        }
    }

    public void SetSegments(double total, IEnumerable<StackedSegment> segments)
    {
        _total = Math.Max(1d, total);
        _segments = (segments ?? Enumerable.Empty<StackedSegment>())
            .Where(s => s.Value > 0)
            .ToList();
        Invalidate();
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
        using var textBrush = new SolidBrush(Color.FromArgb(200, ForeColor));

        var titleH = TextRenderer.MeasureText("Ag", titleFont).Height;
        var titleRect = new Rectangle(rect.Left + 6, rect.Top + 3, rect.Width - 12, titleH);

        if (!string.IsNullOrWhiteSpace(_titleLeft))
        {
            TextRenderer.DrawText(g, _titleLeft, titleFont, titleRect, ForeColor,
                TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
        }
        if (!string.IsNullOrWhiteSpace(_titleRight))
        {
            TextRenderer.DrawText(g, _titleRight, titleFont, titleRect, ForeColor,
                TextFormatFlags.Right | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
        }

        var barTop = titleRect.Bottom + 4;
        var bar = Rectangle.FromLTRB(rect.Left + 6, barTop, rect.Right - 6, rect.Bottom - 6);
        if (bar.Width <= 4 || bar.Height <= 4)
        {
            return;
        }

        using var outlinePen = new Pen(Color.FromArgb(70, ForeColor), 1f);
        g.DrawRectangle(outlinePen, bar.Left, bar.Top, bar.Width - 1, bar.Height - 1);

        var usable = new Rectangle(bar.Left + 1, bar.Top + 1, bar.Width - 2, bar.Height - 2);
        if (_fillBarBackground)
        {
            using var bgBrush = new SolidBrush(_barBackgroundColor);
            g.FillRectangle(bgBrush, usable);
        }

        if (_segments.Count == 0)
        {
            if (!_fillBarBackground)
            {
                using var emptyBrush = new SolidBrush(Color.FromArgb(25, ForeColor));
                g.FillRectangle(emptyBrush, usable);
            }
            return;
        }

        var x = usable.Left;
        var remaining = usable.Width;

        using var labelFont = new Font(Font, FontStyle.Bold);
        using var labelBrush = new SolidBrush(Color.Black);
        using var labelSf = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center };

        var total = Math.Max(1d, _total);
        for (var i = 0; i < _segments.Count; i++)
        {
            var seg = _segments[i];
            var w = i == _segments.Count - 1
                ? remaining
                : (int)Math.Round((seg.Value / total) * usable.Width);

            w = Math.Clamp(w, 0, remaining);
            if (w <= 0)
            {
                continue;
            }

            var segRect = new Rectangle(x, usable.Top, w, usable.Height);
            using (var brush = new SolidBrush(seg.Color))
            {
                g.FillRectangle(brush, segRect);
            }

            var label = GetSegmentLabel(seg.Key);
            if (!string.IsNullOrWhiteSpace(label))
            {
                var textSize = TextRenderer.MeasureText(label, labelFont);
                if (segRect.Width >= textSize.Width + 6)
                {
                    g.DrawString(label, labelFont, labelBrush, segRect, labelSf);
                }
            }

            x += w;
            remaining -= w;
            if (remaining <= 0)
            {
                break;
            }
        }
    }

    private static string GetSegmentLabel(string key)
    {
        if (string.IsNullOrWhiteSpace(key))
        {
            return "";
        }

        return key.Trim().ToLowerInvariant() switch
        {
            "used" => "Used",
            "used_s" => "Used/s",
            "modified" => "Modified",
            "free" => "Free",
            _ => key
        };
    }
}

public sealed record StackedSegment(string Key, double Value, Color Color);
