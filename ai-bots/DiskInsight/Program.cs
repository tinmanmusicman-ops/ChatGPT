using System;
using System.Windows.Forms;

namespace DiskInsight;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        Application.SetHighDpiMode(HighDpiMode.SystemAware);
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);

        using var eiService = new EiCommentaryService();
        Application.Run(new MainForm(eiService));
    }
}
