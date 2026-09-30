using System.Text.RegularExpressions;

namespace PicoChess.MacControlPanel;

/// <summary>
/// Finds the PicoChess checkout that the control panel operates on and reads
/// the few settings it needs from it.
/// </summary>
internal static partial class PicoChessLocation
{
    public const string StartScript = "start-picochess-mac.sh";
    public const string InstallScript = "install-picochess-mac.sh";
    private const int DefaultWebPort = 8080;

    private static readonly string Home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);

    public static readonly string DefaultInstallDirectory = Path.Combine(Home, "PicoChess");

    private static readonly string SettingsFile = Path.Combine(
        Home, "Library", "Application Support", "PicoChess", "controlpanel-repository.txt");

    /// <summary>
    /// Resolution order: <c>--repo &lt;path&gt;</c>, the <c>PICOCHESS_HOME</c>
    /// environment variable, the folder saved from a previous choice, a checkout
    /// containing this app, and finally <c>~/PicoChess</c>.
    /// </summary>
    public static string? Resolve(string[] args)
    {
        var index = Array.FindIndex(args, arg => arg == "--repo");
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

        return IsCheckout(DefaultInstallDirectory) ? DefaultInstallDirectory : null;
    }

    /// <summary>
    /// A PicoChess checkout with the macOS installer. Older checkouts may lack the
    /// start script; Start reports that and Upgrade brings it in.
    /// </summary>
    public static bool IsCheckout(string directory)
    {
        try
        {
            return File.Exists(Path.Combine(directory, "picochess.py"))
                && File.Exists(Path.Combine(directory, InstallScript));
        }
        catch (Exception exception) when (exception is ArgumentException or IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    public static bool HasStartScript(string repository) =>
        File.Exists(Path.Combine(repository, StartScript));

    public static bool HasVirtualEnvironment(string repository) =>
        File.Exists(Path.Combine(repository, "venv", "bin", "python"));

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
    /// Reads <c>web-server = PORT</c> from picochess.ini, falling back to 8080.
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

    public static string Normalize(string directory)
    {
        var trimmed = directory.Trim();
        if (trimmed == "~" || trimmed.StartsWith("~/", StringComparison.Ordinal))
        {
            trimmed = Home + trimmed[1..];
        }
        return Path.GetFullPath(trimmed);
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

    [GeneratedRegex(@"^\s*web-server\s*=\s*(\d+)\s*(?:[#;].*)?$", RegexOptions.IgnoreCase)]
    private static partial Regex WebServerLine();
}
