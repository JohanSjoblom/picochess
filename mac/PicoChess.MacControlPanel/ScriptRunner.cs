using System.Diagnostics;

namespace PicoChess.MacControlPanel;

/// <summary>Starts child processes with output streamed to the log.</summary>
internal static class ScriptRunner
{
    // An app started from Finder gets only /usr/bin:/bin:/usr/sbin:/sbin, where
    // python3 is the unsupported Xcode 3.9. Add the usual Homebrew and python.org
    // locations so the install script finds the same Python as a Terminal does.
    private static readonly string[] ExtraPathDirectories =
    [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/Library/Frameworks/Python.framework/Versions/3.13/bin",
        "/Library/Frameworks/Python.framework/Versions/3.12/bin",
        "/Library/Frameworks/Python.framework/Versions/3.11/bin"
    ];

    public static Process Create(string fileName, IEnumerable<string> arguments, string workingDirectory)
    {
        var process = new Process
        {
            StartInfo = new ProcessStartInfo
            {
                FileName = fileName,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                WorkingDirectory = workingDirectory
            },
            EnableRaisingEvents = true
        };
        foreach (var argument in arguments) process.StartInfo.ArgumentList.Add(argument);
        process.StartInfo.Environment["PATH"] = BuildPath(process.StartInfo.Environment["PATH"]);
        return process;
    }

    public static Process CreateBashScript(string repository, string script, IEnumerable<string> arguments) =>
        Create("/bin/bash", new[] { Path.Combine(repository, script) }.Concat(arguments), repository);

    public static void StartWithOutput(Process process, Action<string> log)
    {
        process.OutputDataReceived += (_, e) => { if (e.Data is not null) log(e.Data); };
        process.ErrorDataReceived += (_, e) => { if (e.Data is not null) log(e.Data); };
        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
    }

    /// <summary>Runs a process to completion, streaming its output, and returns the exit code.</summary>
    public static async Task<int> RunAsync(
        string fileName,
        IEnumerable<string> arguments,
        string workingDirectory,
        Action<string> log,
        CancellationToken cancellationToken,
        bool logOutput = true)
    {
        var argumentList = arguments.ToList();
        using var process = Create(fileName, argumentList, workingDirectory);
        if (logOutput)
        {
            log($"> {Path.GetFileName(fileName)} {string.Join(' ', argumentList.Select(Quote))}");
            StartWithOutput(process, log);
        }
        else
        {
            StartWithOutput(process, _ => { });
        }

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

    public static async Task<bool> SucceedsAsync(string fileName, IEnumerable<string> arguments, CancellationToken cancellationToken)
    {
        try
        {
            return await RunAsync(fileName, arguments, Environment.CurrentDirectory, _ => { }, cancellationToken, logOutput: false) == 0;
        }
        catch (System.ComponentModel.Win32Exception)
        {
            return false;
        }
    }

    private static string BuildPath(string? current)
    {
        var entries = (current ?? "/usr/bin:/bin:/usr/sbin:/sbin").Split(':', StringSplitOptions.RemoveEmptyEntries).ToList();
        foreach (var directory in ExtraPathDirectories.Reverse())
        {
            if (Directory.Exists(directory) && !entries.Contains(directory))
            {
                entries.Insert(0, directory);
            }
        }
        return string.Join(':', entries);
    }

    private static string Quote(string argument) =>
        argument.Any(char.IsWhiteSpace) ? $"\"{argument}\"" : argument;
}
