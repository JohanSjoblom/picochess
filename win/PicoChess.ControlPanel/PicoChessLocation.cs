using System.Text.RegularExpressions;

namespace PicoChess.ControlPanel;

/// <summary>
/// Finds the PicoChess checkout that the control panel operates on and reads
/// the few settings it needs from it.
/// </summary>
internal static partial class PicoChessLocation
{
    public const string StartScript = "start-picochess-windows.ps1";
    public const string InstallScript = "install-picochess-windows.ps1";
    private const int DefaultWebPort = 8080;

    private static readonly string SettingsFile = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "PicoChess", "controlpanel-repository.txt");

    /// <summary>
    /// Resolution order: <c>--repo &lt;path&gt;</c>, the <c>PICOCHESS_HOME</c>
    /// environment variable, the folder saved from a previous Browse, a checkout
    /// containing this executable, and finally the installer default
    /// <c>%USERPROFILE%\PicoChess</c>.
    /// </summary>
    public static string? Resolve(string[] args)
    {
        var index = Array.FindIndex(args, arg => string.Equals(arg, "--repo", StringComparison.OrdinalIgnoreCase));
        if (index >= 0 && index + 1 < args.Length && IsCheckout(args[index + 1]))
        {
            return Normalize(args[index + 1]);
        }

        var environmentHome = Environment.GetEnvironmentVariable("PICOCHESS_HOME");
        if (!string.IsNullOrWhiteSpace(environmentHome) && IsCheckout(environmentHome))
        {
            return Normalize(environmentHome);
        }

        var saved = ReadSavedRepository();
        if (saved is not null && IsCheckout(saved))
        {
            return Normalize(saved);
        }

        for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
        {
            if (IsCheckout(directory.FullName))
            {
                return directory.FullName;
            }
        }

        var installerDefault = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "PicoChess");
        return IsCheckout(installerDefault) ? installerDefault : null;
    }

    public static bool IsCheckout(string directory)
    {
        try
        {
            return File.Exists(Path.Combine(directory, "picochess.py"))
                && File.Exists(Path.Combine(directory, StartScript));
        }
        catch (Exception exception) when (exception is ArgumentException or IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    public static bool HasVirtualEnvironment(string repository) =>
        File.Exists(Path.Combine(repository, "venv", "Scripts", "python.exe"));

    public static void SaveRepository(string repository)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(SettingsFile)!);
            File.WriteAllText(SettingsFile, repository);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // Remembering the folder is a convenience only.
        }
    }

    /// <summary>
    /// Reads <c>web-server = PORT</c> from picochess.ini. The Windows example
    /// configuration uses 8080, which is also the fallback.
    /// </summary>
    public static int ReadWebPort(string repository)
    {
        try
        {
            var configuration = Path.Combine(repository, "picochess.ini");
            if (!File.Exists(configuration)) return DefaultWebPort;

            foreach (var line in File.ReadLines(configuration))
            {
                var match = WebServerLine().Match(line);
                if (match.Success && int.TryParse(match.Groups[1].Value, out var port) && port is > 0 and < 65536)
                {
                    return port;
                }
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
        }
        return DefaultWebPort;
    }

    private static string? ReadSavedRepository()
    {
        try
        {
            return File.Exists(SettingsFile) ? File.ReadAllText(SettingsFile).Trim() : null;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    private static string Normalize(string directory) =>
        Path.GetFullPath(Environment.ExpandEnvironmentVariables(directory.Trim()));

    [GeneratedRegex(@"^\s*web-server\s*=\s*(\d+)\s*(?:[#;].*)?$", RegexOptions.IgnoreCase)]
    private static partial Regex WebServerLine();
}
