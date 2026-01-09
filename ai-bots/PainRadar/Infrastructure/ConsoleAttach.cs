using System.Diagnostics;
using System.Runtime.InteropServices;

namespace PainRadar.Infrastructure;

public static class ConsoleAttach
{
    public static void TryAttachToParent()
    {
        try
        {
            var force = string.Equals(Environment.GetEnvironmentVariable("PAINRADAR_ATTACH_CONSOLE"), "1", StringComparison.OrdinalIgnoreCase);
            if (!force && !Debugger.IsAttached)
                return;

            AttachConsole(ATTACH_PARENT_PROCESS);
        }
        catch
        {
        }
    }

    private const int ATTACH_PARENT_PROCESS = -1;

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AttachConsole(int dwProcessId);
}

