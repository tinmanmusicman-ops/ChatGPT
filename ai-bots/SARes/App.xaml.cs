using System.Threading.Tasks;
using System.Windows;
using SARes.ui;

namespace SARes;

public partial class App : System.Windows.Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        var splash = new SplashWindow();
        splash.Show();
        _ = ShowMainWindowAsync(splash);
    }

    private static async Task ShowMainWindowAsync(SplashWindow splash)
    {
        await Task.Delay(5000);
        var main = new MainWindow();
        Current.MainWindow = main;
        main.Show();
        splash.Close();
    }
}
