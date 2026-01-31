using System.Windows;
using System.Windows.Media;

namespace SARes.ui;

public static class PromptDialogs
{
    public static string? PromptForText(Window? owner, string title, string label, string initial)
    {
        var bg = (SolidColorBrush)new BrushConverter().ConvertFromString("#0B1220")!;
        var panel = (SolidColorBrush)new BrushConverter().ConvertFromString("#0F172A")!;
        var border = (SolidColorBrush)new BrushConverter().ConvertFromString("#334155")!;
        var fg = (SolidColorBrush)new BrushConverter().ConvertFromString("#E5E7EB")!;
        var muted = (SolidColorBrush)new BrushConverter().ConvertFromString("#94A3B8")!;

        var win = new Window
        {
            Title = title,
            Width = 460,
            Height = 190,
            WindowStartupLocation = owner is null ? WindowStartupLocation.CenterScreen : WindowStartupLocation.CenterOwner,
            ResizeMode = ResizeMode.NoResize,
            Background = bg,
            Foreground = fg,
            Owner = owner
        };

        var grid = new System.Windows.Controls.Grid { Margin = new Thickness(12) };
        grid.RowDefinitions.Add(new System.Windows.Controls.RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new System.Windows.Controls.RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new System.Windows.Controls.RowDefinition { Height = GridLength.Auto });

        var labelBlock = new System.Windows.Controls.TextBlock { Text = label, Margin = new Thickness(0, 0, 0, 6), Foreground = muted };
        System.Windows.Controls.Grid.SetRow(labelBlock, 0);
        grid.Children.Add(labelBlock);

        var textBox = new System.Windows.Controls.TextBox
        {
            Text = initial ?? "",
            Margin = new Thickness(0, 0, 0, 10),
            Background = panel,
            Foreground = fg,
            BorderBrush = border,
            BorderThickness = new Thickness(1),
            Padding = new Thickness(10, 8, 10, 8)
        };
        System.Windows.Controls.Grid.SetRow(textBox, 1);
        grid.Children.Add(textBox);

        var buttons = new System.Windows.Controls.StackPanel
        {
            Orientation = System.Windows.Controls.Orientation.Horizontal,
            HorizontalAlignment = System.Windows.HorizontalAlignment.Right
        };
        var ok = new System.Windows.Controls.Button
        {
            Content = "OK",
            Width = 90,
            Margin = new Thickness(0, 0, 8, 0),
            Background = (SolidColorBrush)new BrushConverter().ConvertFromString("#2563EB")!,
            BorderBrush = (SolidColorBrush)new BrushConverter().ConvertFromString("#1D4ED8")!,
            Foreground = System.Windows.Media.Brushes.White
        };
        var cancel = new System.Windows.Controls.Button
        {
            Content = "Cancel",
            Width = 90,
            Background = (SolidColorBrush)new BrushConverter().ConvertFromString("#111827")!,
            BorderBrush = border,
            Foreground = fg
        };
        buttons.Children.Add(ok);
        buttons.Children.Add(cancel);
        System.Windows.Controls.Grid.SetRow(buttons, 2);
        grid.Children.Add(buttons);

        win.Content = new System.Windows.Controls.Border
        {
            Background = bg,
            BorderBrush = border,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(10),
            Padding = new Thickness(8),
            Child = grid
        };

        string? result = null;
        ok.Click += (_, _) => { result = textBox.Text; win.DialogResult = true; win.Close(); };
        cancel.Click += (_, _) => { win.DialogResult = false; win.Close(); };
        textBox.KeyDown += (_, e) =>
        {
            if (e.Key == System.Windows.Input.Key.Enter)
            {
                result = textBox.Text;
                win.DialogResult = true;
                win.Close();
            }
        };

        win.Loaded += (_, _) => { textBox.Focus(); textBox.SelectAll(); };
        _ = win.ShowDialog();
        return result;
    }
}
