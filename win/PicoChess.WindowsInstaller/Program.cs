using PicoChess.ControlPanel;

namespace PicoChess.WindowsInstaller;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        if (args.Contains(ControlPanelInstaller.ControlPanelArgument, StringComparer.OrdinalIgnoreCase))
        {
            Application.Run(new ControlPanelForm(args));
            return;
        }
        Application.Run(new InstallerForm());
    }
}
