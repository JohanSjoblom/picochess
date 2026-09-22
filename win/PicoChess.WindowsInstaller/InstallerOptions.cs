namespace PicoChess.WindowsInstaller;

internal sealed record InstallerOptions(
    string InstallDirectory,
    bool InstallResources,
    bool UpdateExistingCheckout);
