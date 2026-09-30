using System.Diagnostics;

namespace PicoChess.ControlPanel;

/// <summary>
/// Owns the PicoChess process tree started by the control panel:
/// powershell.exe running start-picochess-windows.ps1, which starts
/// venv\Scripts\python.exe picochess.py and optionally the Scid games helper.
/// </summary>
internal sealed class PicoChessProcess : IDisposable
{
    private static readonly TimeSpan GracefulStopTimeout = TimeSpan.FromSeconds(20);
    private static readonly SemaphoreSlim ConsoleLock = new(1, 1);
    private readonly Action<string> _log;
    private Process? _process;

    public PicoChessProcess(Action<string> log) => _log = log;

    /// <summary>Raised on a thread-pool thread when the launcher process exits.</summary>
    public event EventHandler? Exited;

    public bool IsRunning => _process is { HasExited: false };

    public void Start(string repository)
    {
        if (IsRunning) throw new InvalidOperationException("PicoChess is already running.");

        var process = CreatePowerShellProcess(repository, PicoChessLocation.StartScript, []);
        // Keep Python output visible in the log while it is running.
        process.StartInfo.Environment["PYTHONUNBUFFERED"] = "1";
        process.StartInfo.Environment["PYTHONIOENCODING"] = "utf-8";
        process.Exited += (_, _) => Exited?.Invoke(this, EventArgs.Empty);

        _log($"> powershell.exe -File {PicoChessLocation.StartScript}");
        StartWithOutput(process, _log);
        _process?.Dispose();
        _process = process;
    }

    /// <summary>
    /// Sends Ctrl+C so picochess.py can run its normal SIGINT shutdown and the
    /// launcher can stop the games helper; forcibly ends whatever remains after
    /// the timeout.
    /// </summary>
    public async Task StopAsync()
    {
        var process = _process;
        if (process is null || process.HasExited) return;

        // Capture the tree first: PowerShell may exit before python.exe does.
        var tree = new List<Process> { process };
        foreach (var id in NativeMethods.GetDescendantProcessIds(process.Id))
        {
            try { tree.Add(Process.GetProcessById(id)); }
            catch (ArgumentException) { /* already exited */ }
        }

        await ConsoleLock.WaitAsync();
        try
        {
            _log("Asking PicoChess to shut down...");
            var signalled = SendCtrlC(process.Id);
            if (signalled)
            {
                using var timeout = new CancellationTokenSource(GracefulStopTimeout);
                try
                {
                    await Task.WhenAll(tree.Select(p => p.WaitForExitAsync(timeout.Token)));
                }
                catch (OperationCanceledException)
                {
                    _log("PicoChess did not shut down in time.");
                }
            }
        }
        finally
        {
            // The ignore flag is inherited by new children, so always restore it
            // before anything else can be started.
            NativeMethods.SetConsoleCtrlHandler(IntPtr.Zero, false);
            ConsoleLock.Release();
        }

        var remaining = tree.Where(p => !HasExited(p)).ToList();
        if (remaining.Count > 0)
        {
            _log("Forcing the remaining PicoChess processes to stop.");
            foreach (var p in remaining)
            {
                try { p.Kill(entireProcessTree: true); }
                catch (Exception exception) when (exception is InvalidOperationException or System.ComponentModel.Win32Exception) { }
            }
            await Task.WhenAll(remaining.Select(p => p.WaitForExitAsync()));
        }

        foreach (var p in tree.Where(p => p != process)) p.Dispose();
    }

    /// <summary>Runs install-picochess-windows.ps1 in update mode and streams its output.</summary>
    public static async Task<int> RunUpgradeAsync(string repository, Action<string> log, CancellationToken cancellationToken)
    {
        using var process = CreatePowerShellProcess(repository, PicoChessLocation.InstallScript,
            ["-InstallDir", repository, "-UpdateRepo"]);
        log($"> powershell.exe -File {PicoChessLocation.InstallScript} -InstallDir \"{repository}\" -UpdateRepo");
        StartWithOutput(process, log);
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
        return process.ExitCode;
    }

    public void Dispose() => _process?.Dispose();

    private static Process CreatePowerShellProcess(string repository, string script, IEnumerable<string> scriptArguments)
    {
        var process = new Process
        {
            StartInfo = new ProcessStartInfo
            {
                FileName = "powershell.exe",
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                // A hidden console is still created, which is what lets Stop send Ctrl+C.
                CreateNoWindow = true,
                WorkingDirectory = repository
            },
            EnableRaisingEvents = true
        };
        foreach (var argument in new[]
                 {
                     "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                     "-File", Path.Combine(repository, script)
                 }.Concat(scriptArguments))
        {
            process.StartInfo.ArgumentList.Add(argument);
        }
        return process;
    }

    private static void StartWithOutput(Process process, Action<string> log)
    {
        process.OutputDataReceived += (_, e) => { if (e.Data is not null) log(e.Data); };
        process.ErrorDataReceived += (_, e) => { if (e.Data is not null) log(e.Data); };
        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
    }

    private static bool SendCtrlC(int processId)
    {
        // A WinForms process has no console of its own; borrow the child's hidden
        // console, ignore the event ourselves, and broadcast Ctrl+C to it.
        NativeMethods.FreeConsole();
        if (!NativeMethods.AttachConsole((uint)processId)) return false;
        try
        {
            NativeMethods.SetConsoleCtrlHandler(IntPtr.Zero, true);
            return NativeMethods.GenerateConsoleCtrlEvent(NativeMethods.CtrlCEvent, 0);
        }
        finally
        {
            NativeMethods.FreeConsole();
        }
    }

    private static bool HasExited(Process process)
    {
        try { return process.HasExited; }
        catch (InvalidOperationException) { return true; }
    }
}
