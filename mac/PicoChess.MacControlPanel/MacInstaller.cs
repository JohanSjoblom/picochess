namespace PicoChess.MacControlPanel;

/// <summary>
/// Clones PicoChess when needed and runs install-picochess-mac.sh. Git and
/// Python are not installed silently on macOS; the user is told what to install.
/// </summary>
internal static class MacInstaller
{
    private const string RepositoryUrl = "https://github.com/JohanSjoblom/picochess.git";
    // Temporary during Windows/macOS beta testing. Remove this explicit branch
    // selection before merging the port into the default branch.
    private const string RepositoryBranch = "471-port-to-windows";

    public static async Task InstallAsync(
        string installDirectory,
        bool installResources,
        Action<string> log,
        CancellationToken cancellationToken)
    {
        installDirectory = PicoChessLocation.Normalize(installDirectory);

        if (!PicoChessLocation.IsCheckout(installDirectory))
        {
            if (Directory.Exists(installDirectory) && Directory.EnumerateFileSystemEntries(installDirectory).Any())
            {
                throw new InvalidOperationException(
                    "The selected folder is not empty and is not a PicoChess checkout. Choose an empty folder or an existing PicoChess checkout.");
            }

            log("Checking for Git...");
            if (!await ScriptRunner.SucceedsAsync("/usr/bin/env", ["git", "--version"], cancellationToken))
            {
                throw new InvalidOperationException(
                    "Git is required. If macOS offers to install the Command Line Tools, accept and wait for it to finish, " +
                    "then click Install again. Otherwise install them in Terminal with: xcode-select --install");
            }

            var parent = Directory.GetParent(installDirectory)?.FullName
                ?? throw new InvalidOperationException("Choose an installation folder with a valid parent directory.");
            Directory.CreateDirectory(parent);

            log("\nCloning PicoChess...");
            var cloneExit = await ScriptRunner.RunAsync("/usr/bin/env",
                ["git", "clone", "--branch", RepositoryBranch, RepositoryUrl, installDirectory],
                parent, log, cancellationToken);
            if (cloneExit != 0)
            {
                throw new InvalidOperationException($"git clone failed with exit code {cloneExit}.");
            }
        }
        else
        {
            log($"Using existing checkout: {installDirectory}");
        }

        log("\nRunning the PicoChess macOS setup script...");
        var arguments = new List<string> { "--install-dir", installDirectory };
        if (!installResources) arguments.Add("--skip-resources");
        var exitCode = await RunScriptAsync(installDirectory, arguments, log, cancellationToken);
        if (exitCode != 0)
        {
            throw new InvalidOperationException(
                "The setup script failed. If it reports that Python was not found, install CPython 3.13 from " +
                "https://www.python.org/downloads/macos/ and click Install again.");
        }
        log("\nInstallation completed.");
    }

    /// <summary>Runs install-picochess-mac.sh in update mode (git pull --ff-only on a clean checkout).</summary>
    public static Task<int> UpgradeAsync(string repository, Action<string> log, CancellationToken cancellationToken) =>
        RunScriptAsync(repository, ["--install-dir", repository, "--update-repo"], log, cancellationToken);

    private static async Task<int> RunScriptAsync(
        string repository,
        IEnumerable<string> arguments,
        Action<string> log,
        CancellationToken cancellationToken) =>
        await ScriptRunner.RunAsync("/bin/bash",
            new[] { Path.Combine(repository, PicoChessLocation.InstallScript) }.Concat(arguments),
            repository, log, cancellationToken);
}
