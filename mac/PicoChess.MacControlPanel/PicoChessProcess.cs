using System.Diagnostics;
using System.Globalization;
using System.Runtime.InteropServices;

namespace PicoChess.MacControlPanel;

/// <summary>
/// Owns the PicoChess process tree started by the control panel: bash running
/// start-picochess-mac.sh, which execs venv/bin/python picochess.py, or keeps
/// running beside it to supervise the optional Scid games helper.
/// </summary>
internal sealed partial class PicoChessProcess : IDisposable
{
    private const int SigInt = 2;
    private const int SigKill = 9;
    private static readonly TimeSpan GracefulStopTimeout = TimeSpan.FromSeconds(20);
    private readonly Action<string> _log;
    private Process? _process;

    public PicoChessProcess(Action<string> log) => _log = log;

    /// <summary>Raised on a thread-pool thread when the launcher process exits.</summary>
    public event EventHandler? Exited;

    public bool IsRunning => _process is { HasExited: false };

    public void Start(string repository)
    {
        if (IsRunning) throw new InvalidOperationException("PicoChess is already running.");

        var process = ScriptRunner.CreateBashScript(repository, PicoChessLocation.StartScript, []);
        // Keep Python output visible in the log while it is running.
        process.StartInfo.Environment["PYTHONUNBUFFERED"] = "1";
        process.StartInfo.Environment["PYTHONIOENCODING"] = "utf-8";
        process.Exited += (_, _) => Exited?.Invoke(this, EventArgs.Empty);

        _log($"> bash {PicoChessLocation.StartScript}");
        ScriptRunner.StartWithOutput(process, _log);
        _process?.Dispose();
        _process = process;
    }

    /// <summary>
    /// Sends SIGINT to every process in the tree, like Ctrl+C in Terminal, so
    /// picochess.py runs its normal shutdown and the launcher stops the games
    /// helper; forcibly ends whatever remains after the timeout.
    /// </summary>
    public async Task StopAsync()
    {
        var process = _process;
        if (process is null || process.HasExited) return;

        // Capture the tree first: the launcher may exit before python does.
        var tree = new List<Process> { process };
        foreach (var id in await GetDescendantProcessIdsAsync(process.Id))
        {
            try { tree.Add(Process.GetProcessById(id)); }
            catch (ArgumentException) { /* already exited */ }
        }

        _log("Asking PicoChess to shut down...");
        foreach (var p in tree) Signal(p, SigInt);

        using (var timeout = new CancellationTokenSource(GracefulStopTimeout))
        {
            try
            {
                await Task.WhenAll(tree.Select(p => p.WaitForExitAsync(timeout.Token)));
            }
            catch (OperationCanceledException)
            {
                _log("PicoChess did not shut down in time.");
            }
        }

        var remaining = tree.Where(p => !HasExited(p)).ToList();
        if (remaining.Count > 0)
        {
            _log("Forcing the remaining PicoChess processes to stop.");
            foreach (var p in remaining) Signal(p, SigKill);
            await Task.WhenAll(remaining.Select(p => p.WaitForExitAsync()));
        }

        foreach (var p in tree.Where(p => p != process)) p.Dispose();
    }

    public void Dispose() => _process?.Dispose();

    private static void Signal(Process process, int signal)
    {
        if (!HasExited(process)) Kill(process.Id, signal);
    }

    private static bool HasExited(Process process)
    {
        try { return process.HasExited; }
        catch (InvalidOperationException) { return true; }
    }

    /// <summary>Returns all descendants of <paramref name="rootProcessId"/>, using ps (macOS has no /proc).</summary>
    private static async Task<IReadOnlyList<int>> GetDescendantProcessIdsAsync(int rootProcessId)
    {
        var lines = new List<string>();
        using var ps = ScriptRunner.Create("/bin/ps", ["-A", "-o", "pid=", "-o", "ppid="], "/");
        ps.OutputDataReceived += (_, e) => { if (e.Data is not null) lock (lines) lines.Add(e.Data); };
        ps.Start();
        ps.BeginOutputReadLine();
        ps.BeginErrorReadLine();
        await ps.WaitForExitAsync();

        var children = new Dictionary<int, List<int>>();
        foreach (var line in lines)
        {
            var parts = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length != 2
                || !int.TryParse(parts[0], NumberStyles.Integer, CultureInfo.InvariantCulture, out var pid)
                || !int.TryParse(parts[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out var ppid))
            {
                continue;
            }
            if (!children.TryGetValue(ppid, out var list)) children[ppid] = list = [];
            list.Add(pid);
        }

        var result = new List<int>();
        var pending = new Queue<int>([rootProcessId]);
        while (pending.Count > 0)
        {
            if (!children.TryGetValue(pending.Dequeue(), out var list)) continue;
            foreach (var child in list.Where(child => child != rootProcessId && !result.Contains(child)))
            {
                result.Add(child);
                pending.Enqueue(child);
            }
        }
        return result;
    }

    [LibraryImport("libc", EntryPoint = "kill", SetLastError = true)]
    private static partial int Kill(int pid, int signal);
}
