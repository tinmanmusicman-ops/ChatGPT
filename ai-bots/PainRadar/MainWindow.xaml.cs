using System.Windows;

namespace PainRadar;

public partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();
    }

    public void FocusSearch()
    {
        try
        {
            Activate();
            SearchTextBox.Focus();
            SearchTextBox.SelectAll();
        }
        catch
        {
        }
    }
}
