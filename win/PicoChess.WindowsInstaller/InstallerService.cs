using System.Diagnostics;
namespace PicoChess.WindowsInstaller;

internal sealed class InstallerService
{
    private const string RepositoryUrl = "https://github.com/JohanSjoblom/picochess.git";
    private readonly Action<string> _log;

    public InstallerService(Action<string> log) => _log = log;

    public async Task InstallAsync(InstallerOptions options, CancellationToken cancellationToken)
    {
        if (!OperatingSystem.IsWindows() || !Environment.Is64BitOperatingSystem)
        {
            throw new InvalidOperationException("PicoChess requires 64-bit Windows.");
        }

        var installDirectory = Path.GetFullPath(
            Environment.ExpandEnvironmentVariables(options.InstallDirectory.Trim()));

        _log("Checking prerequisites...");
        var gitAvailable = await CommandSucceedsAsync("git.exe", ["--version"], cancellationToken);
        var pythonAvailable = await HasSupportedPythonAsync(cancellationToken);

        if (!gitAvailable || !pythonAvailable)
        {
            if (!await CommandSucceedsAsync("winget.exe", ["--version"], cancellationToken))
            {
                throw new InvalidOperationException(
                    "Windows Package Manager (winget) is required to install missing prerequisites. " +
                    "Install or update 'App Installer' from Microsoft Store, then try again.");
            }

            if (!gitAvailable)
            {
                _log("\r\nInstalling Git for Windows...");
                await RunAsync("winget.exe",
                    ["install", "--id", "Git.Git", "-e", "--source", "winget", "--silent",
                     "--accept-package-agreements", "--accept-source-agreements"],
                    cancellationToken);
                RefreshPath();
            }

            if (!pythonAvailable)
            {
                _log("\r\nInstalling CPython 3.13 x64...");
                await RunAsync("winget.exe",
                    ["install", "--id", "Python.Python.3.13", "-e", "--source", "winget", "--silent",
                     "--architecture", "x64", "--accept-package-agreements", "--accept-source-agreements"],
                    cancellationToken);
                RefreshPath();
            }
        }

        if (!await CommandSucceedsAsync("git.exe", ["--version"], cancellationToken))
        {
            throw new InvalidOperationException("Git was installed but cannot yet be found. Sign out of Windows and try again.");
        }

        if (!await HasSupportedPythonAsync(cancellationToken))
        {
            throw new InvalidOperationException(
                "CPython 3.13 x64 was installed but cannot yet be found. Sign out of Windows and try again.");
        }

        _log("\r\nPreparing the PicoChess repository...");
        var existingCheckout = Directory.Exists(Path.Combine(installDirectory, ".git"));
        await PrepareRepositoryAsync(installDirectory, cancellationToken);

        var script = Path.Combine(installDirectory, "install-picochess-windows.ps1");
        if (!File.Exists(script))
        {
            throw new InvalidOperationException($"The repository does not contain {Path.GetFileName(script)}.");
        }

        _log("\r\nRunning the PicoChess Windows setup script...");
        var arguments = new List<string>
        {
            "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", script, "-InstallDir", installDirectory
        };
        if (!options.InstallResources)
        {
            arguments.Add("-SkipResources");
        }
        if (existingCheckout && options.UpdateExistingCheckout)
        {
            // Let the PowerShell installer enforce its clean-branch safety checks.
            arguments.Add("-UpdateRepo");
        }

        await RunAsync("powershell.exe", arguments, cancellationToken, installDirectory);
        _log("\r\nInstallation completed successfully.");
    }

    private async Task PrepareRepositoryAsync(
        string installDirectory,
        CancellationToken cancellationToken)
    {
        var gitDirectory = Path.Combine(installDirectory, ".git");
        if (Directory.Exists(gitDirectory))
        {
            _log($"Using existing checkout: {installDirectory}");
            return;
        }

        if (Directory.Exists(installDirectory) && Directory.EnumerateFileSystemEntries(installDirectory).Any())
        {
            throw new InvalidOperationException(
                "The selected folder is not empty and is not a Git checkout. Choose an empty folder or an existing PicoChess checkout.");
        }

        var parent = Directory.GetParent(installDirectory)?.FullName
            ?? throw new InvalidOperationException("Choose an installation folder with a valid parent directory.");
        Directory.CreateDirectory(parent);
        await RunAsync("git.exe", ["clone", RepositoryUrl, installDirectory], cancellationToken);
    }

    private async Task<bool> HasSupportedPythonAsync(CancellationToken cancellationToken)
    {
        const string probe = "import platform,struct,sys;raise SystemExit(0 if sys.version_info[:2]==(3,13) and struct.calcsize('P')==8 and platform.machine()=='AMD64' else 1)";
        if (await CommandSucceedsAsync("py.exe", ["-3.13", "-c", probe], cancellationToken))
        {
            return true;
        }

        return await CommandSucceedsAsync("python.exe", ["-c", probe], cancellationToken);
    }

    private async Task<bool> CommandSucceedsAsync(
        string fileName,
        IReadOnlyCollection<string> arguments,
        CancellationToken cancellationToken)
    {
        try
        {
            return await RunAsync(fileName, arguments, cancellationToken, logOutput: false) == 0;
        }
        catch (Exception exception) when (exception is System.ComponentModel.Win32Exception or FileNotFoundException)
        {
            return false;
        }
    }

    private async Task<int> RunAsync(
        string fileName,
        IReadOnlyCollection<string> arguments,
        CancellationToken cancellationToken,
        string? workingDirectory = null,
        bool logOutput = true)
    {
        using var process = new Process
        {
            StartInfo = new ProcessStartInfo
            {
                FileName = fileName,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
                WorkingDirectory = workingDirectory ?? Environment.CurrentDirectory
            },
            EnableRaisingEvents = true
        };

        foreach (var argument in arguments)
        {
            process.StartInfo.ArgumentList.Add(argument);
        }

        if (logOutput)
        {
            _log($"> {Path.GetFileName(fileName)} {string.Join(' ', arguments.Select(FormatArgument))}");
        }

        process.OutputDataReceived += (_, eventArgs) =>
        {
            if (logOutput && eventArgs.Data is not null) _log(eventArgs.Data);
        };
        process.ErrorDataReceived += (_, eventArgs) =>
        {
            if (logOutput && eventArgs.Data is not null) _log(eventArgs.Data);
        };

        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();

        try
        {
            await process.WaitForExitAsync(cancellationToken);
        }
        catch (OperationCanceledException)
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
                await process.WaitForExitAsync(CancellationToken.None);
            }
            throw;
        }

        if (process.ExitCode != 0 && logOutput)
        {
            throw new InvalidOperationException($"{Path.GetFileName(fileName)} exited with code {process.ExitCode}.");
        }
        return process.ExitCode;
    }

    private static string FormatArgument(string argument) =>
        argument.Any(char.IsWhiteSpace) ? $"\"{argument}\"" : argument;

    private static void RefreshPath()
    {
        var machinePath = Environment.GetEnvironmentVariable("Path", EnvironmentVariableTarget.Machine);
        var userPath = Environment.GetEnvironmentVariable("Path", EnvironmentVariableTarget.User);
        Environment.SetEnvironmentVariable("Path", string.Join(';', new[] { machinePath, userPath }
            .Where(value => !string.IsNullOrWhiteSpace(value))));

        // The Python launcher may be registered without immediately updating this process' PATH.
        var windowsDirectory = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
        AddPathIfPresent(Path.Combine(windowsDirectory, "py.exe"));
        AddDirectoryIfPresent(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Programs", "Python", "Launcher"));
        AddDirectoryIfPresent(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Git", "cmd"));
    }

    private static void AddPathIfPresent(string file) => AddDirectoryIfPresent(Path.GetDirectoryName(file)!);

    private static void AddDirectoryIfPresent(string directory)
    {
        if (!Directory.Exists(directory)) return;
        var path = Environment.GetEnvironmentVariable("Path") ?? string.Empty;
        if (!path.Split(';').Contains(directory, StringComparer.OrdinalIgnoreCase))
        {
            Environment.SetEnvironmentVariable("Path", directory + ";" + path);
        }
    }
}
