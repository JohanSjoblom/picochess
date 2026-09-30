using System.Diagnostics;
using System.Runtime.InteropServices;

namespace PicoChess.WindowsInstaller;

/// <summary>
/// Installs this executable as the PicoChess control panel and creates its shortcuts.
/// </summary>
internal static class ControlPanelInstaller
{
    public const string ControlPanelArgument = "--control-panel";
    private const string ShortcutName = "PicoChess.lnk";
    private const string SingleFileName = "PicoChess.exe";

    /// <summary>Per-user application folder, kept outside the Git checkout so updates see a clean tree.</summary>
    private static readonly string ApplicationDirectory = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "PicoChess");

    public static string Install(string repository, bool createDesktopShortcut, Action<string> log)
    {
        var executable = CopyApplication();
        log($"Control panel installed: {executable}");

        var startMenu = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), ShortcutName);
        CreateShortcut(startMenu, executable, repository);
        log($"Start menu shortcut: {startMenu}");

        var desktop = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), ShortcutName);
        if (createDesktopShortcut)
        {
            CreateShortcut(desktop, executable, repository);
            log($"Desktop shortcut: {desktop}");
        }
        return executable;
    }

    public static void Launch(string executable, string repository)
    {
        var startInfo = new ProcessStartInfo(executable) { UseShellExecute = true, WorkingDirectory = repository };
        foreach (var argument in Arguments(repository)) startInfo.ArgumentList.Add(argument);
        Process.Start(startInfo);
    }

    private static string[] Arguments(string repository) => [ControlPanelArgument, "--repo", repository];

    private static string CopyApplication()
    {
        var source = Environment.ProcessPath
            ?? throw new InvalidOperationException("Cannot determine the installer executable path.");
        var sourceDirectory = Path.GetDirectoryName(source)!;
        Directory.CreateDirectory(ApplicationDirectory);

        // A framework-dependent or development build needs its companion files (the
        // apphost loads PicoChessInstaller.dll), so copy the whole folder unchanged.
        var companionAssembly = Path.Combine(sourceDirectory, Path.GetFileNameWithoutExtension(source) + ".dll");
        var singleFile = !File.Exists(companionAssembly);
        var target = singleFile
            ? Path.Combine(ApplicationDirectory, SingleFileName)
            : Path.Combine(ApplicationDirectory, Path.GetFileName(source));

        if (string.Equals(Path.GetFullPath(source), Path.GetFullPath(target), StringComparison.OrdinalIgnoreCase))
        {
            return target;
        }

        try
        {
            if (singleFile)
            {
                File.Copy(source, target, overwrite: true);
            }
            else
            {
                foreach (var file in Directory.EnumerateFiles(sourceDirectory, "*", SearchOption.AllDirectories))
                {
                    var destination = Path.Combine(ApplicationDirectory, Path.GetRelativePath(sourceDirectory, file));
                    Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
                    File.Copy(file, destination, overwrite: true);
                }
            }
        }
        catch (IOException exception)
        {
            throw new InvalidOperationException(
                $"Could not update the PicoChess control panel in {ApplicationDirectory}. " +
                "Close the PicoChess control panel if it is open, then run the installer again.", exception);
        }
        return target;
    }

    private static void CreateShortcut(string path, string executable, string repository)
    {
        var shellType = Type.GetTypeFromProgID("WScript.Shell")
            ?? throw new InvalidOperationException("Windows Script Host is not available to create shortcuts.");
        object? shell = null;
        object? shortcut = null;
        try
        {
            shell = Activator.CreateInstance(shellType)!;
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            shortcut = ((dynamic)shell).CreateShortcut(path);
            dynamic link = shortcut!;
            link.TargetPath = executable;
            link.Arguments = string.Join(' ', Arguments(repository).Select(Quote));
            link.WorkingDirectory = repository;
            link.Description = "Start and stop PicoChess";
            link.IconLocation = executable + ",0";
            link.Save();
        }
        finally
        {
            if (shortcut is not null) Marshal.FinalReleaseComObject(shortcut);
            if (shell is not null) Marshal.FinalReleaseComObject(shell);
        }
    }

    private static string Quote(string argument) =>
        argument.Any(char.IsWhiteSpace) || argument.Length == 0 ? $"\"{argument.TrimEnd('\\')}\"" : argument;
}
