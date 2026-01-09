using System.Windows;

namespace PainRadar;

public partial class OnboardingWindow : Window
{
    public OnboardingWindow()
    {
        InitializeComponent();
    }

    private void GotIt_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = true;
        Close();
    }
}

