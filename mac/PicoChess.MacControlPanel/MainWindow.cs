using System.Diagnostics;
using System.Net.Sockets;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Platform.Storage;
using Avalonia.Threading;

namespace PicoChess.MacControlPanel;

internal sealed class MainWindow : Window
{
    private const int MaxLogLength = 200_000;
    private readonly Button _start = new() { Content = "Start" };
    private readonly Button _browser = new() { Content = "Open in browser" };
    private readonly Button _stop = new() { Content = "Stop" };
    private readonly Button _upgrade = new() { Content = "Upgrade" };
    private readonly Button _changeFolder = new() { Content = "Change folder..." };
    private readonly TextBlock _repository = new() { Foreground = Brushes.Gray, VerticalAlignment = VerticalAlignment.Center };
    private readonly TextBlock _status = new() { FontSize = 15, FontWeight = FontWeight.SemiBold };
    private readonly StackPanel _controlPanel = new() { Spacing = 12 };
    private readonly StackPanel _installPanel = new() { Spacing = 8 };
    private readonly TextBox _installDirectory = new() { Text = PicoChessLocation.DefaultInstallDirectory };
    private readonly CheckBox _installResources = new()
    {
        Content = "Download the standard books, opening data, and games resources",
        IsChecked = true
    };
    private readonly Button _install = new() { Content = "Install" };
    private readonly TextBox _log = new()
    {
        IsReadOnly = true,
        AcceptsReturn = true,
        TextWrapping = TextWrapping.NoWrap,
        FontFamily = new FontFamily("Menlo, Monaco, Consolas, monospace"),
        FontSize = 12
    };
    private readonly DispatcherTimer _statusTimer = new() { Interval = TimeSpan.FromSeconds(1) };
    private readonly PicoChessProcess _picoChess;
    private string? _repositoryPath;
    private int _webPort = 8080;
    private bool _webServerUp;
    private bool _busy;
    private bool _probing;
    private bool _closeAfterStop;

    public MainWindow(string[] args)
    {
        _picoChess = new PicoChessProcess(AppendLog);
        _picoChess.Exited += (_, _) => Dispatcher.UIThread.Post(OnPicoChessExited);

        Title = "PicoChess";
        Width = 760;
        Height = 560;
        MinWidth = 600;
        MinHeight = 440;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;

        foreach (var button in new[] { _start, _browser, _stop, _upgrade })
        {
            button.MinWidth = 130;
            button.HorizontalContentAlignment = HorizontalAlignment.Center;
        }
        _start.Click += async (_, _) => await StartAsync();
        _browser.Click += (_, _) => OpenBrowser();
        _stop.Click += async (_, _) => await StopAsync();
        _upgrade.Click += async (_, _) => await UpgradeAsync();
        _changeFolder.Click += async (_, _) => await ChangeFolderAsync();
        _install.Click += async (_, _) => await InstallAsync();

        var repositoryRow = new DockPanel { LastChildFill = true };
        DockPanel.SetDock(_changeFolder, Dock.Right);
        repositoryRow.Children.Add(_changeFolder);
        repositoryRow.Children.Add(_repository);

        _controlPanel.Children.Add(_status);
        _controlPanel.Children.Add(new WrapPanel
        {
            ItemSpacing = 8,
            LineSpacing = 8,
            Children = { _start, _browser, _stop, _upgrade }
        });

        _installPanel.Children.Add(new TextBlock
        {
            Text = "PicoChess is not installed yet. Choose a folder and click Install. " +
                   "Git (Xcode Command Line Tools) and CPython 3.11-3.13 are required.",
            TextWrapping = TextWrapping.Wrap
        });
        _installPanel.Children.Add(_installDirectory);
        _installPanel.Children.Add(_installResources);
        _installPanel.Children.Add(_install);

        var header = new StackPanel
        {
            Spacing = 12,
            Margin = new Thickness(0, 0, 0, 12),
            Children =
            {
                new TextBlock { Text = "PicoChess", FontSize = 26, FontWeight = FontWeight.SemiBold },
                repositoryRow,
                _controlPanel,
                _installPanel
            }
        };

        var layout = new DockPanel { Margin = new Thickness(24) };
        DockPanel.SetDock(header, Dock.Top);
        layout.Children.Add(header);
        layout.Children.Add(_log);
        Content = layout;

        SetRepository(PicoChessLocation.Resolve(args));

        _statusTimer.Tick += async (_, _) => await RefreshStatusAsync();
        Opened += async (_, _) =>
        {
            _statusTimer.Start();
            await RefreshStatusAsync();
        };
        Closing += OnClosing;
    }

    public bool IsPicoChessRunning => _picoChess.IsRunning;

    private string Url => $"http://localhost:{_webPort}/";

    private void SetRepository(string? repository)
    {
        _repositoryPath = repository;
        _webPort = repository is null ? 8080 : PicoChessLocation.ReadWebPort(repository);
        _repository.Text = repository is null
            ? "PicoChess folder: not found"
            : $"PicoChess folder: {repository}    Web port: {_webPort}";
        _controlPanel.IsVisible = repository is not null;
        _installPanel.IsVisible = repository is null;
        UpdateControls();
    }

    private async Task ChangeFolderAsync()
    {
        var folders = await StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions
        {
            Title = "Select the PicoChess folder (it contains picochess.py)",
            AllowMultiple = false
        });
        var path = folders.Count > 0 ? folders[0].TryGetLocalPath() : null;
        if (path is null) return;

        if (!PicoChessLocation.IsCheckout(path))
        {
            await MessageDialog.ShowAsync(this, Title!,
                $"This folder does not contain picochess.py and {PicoChessLocation.InstallScript}.");
            return;
        }
        PicoChessLocation.SaveRepository(path);
        SetRepository(PicoChessLocation.Normalize(path));
        await RefreshStatusAsync();
    }

    private async Task InstallAsync()
    {
        var directory = _installDirectory.Text?.Trim();
        if (string.IsNullOrEmpty(directory))
        {
            await MessageDialog.ShowAsync(this, Title!, "Choose an installation folder.");
            return;
        }

        _busy = true;
        _status.Text = "Installing...";
        UpdateControls();
        _log.Text = string.Empty;
        try
        {
            await MacInstaller.InstallAsync(directory, _installResources.IsChecked == true, AppendLog, CancellationToken.None);
            var installed = PicoChessLocation.Normalize(directory);
            PicoChessLocation.SaveRepository(installed);
            _busy = false;
            SetRepository(installed);
            await MessageDialog.ShowAsync(this, Title!,
                "PicoChess was installed. Add a native macOS engine and picochess.ini before starting it; " +
                "see docs/mac-install.md in the PicoChess folder.");
        }
        catch (Exception exception)
        {
            AppendLog($"\nERROR: {exception.Message}");
            await MessageDialog.ShowAsync(this, "PicoChess installation failed", exception.Message);
        }
        finally
        {
            _busy = false;
        }
        await RefreshStatusAsync();
    }

    private async Task StartAsync()
    {
        if (_repositoryPath is null) return;
        if (!PicoChessLocation.HasStartScript(_repositoryPath))
        {
            await MessageDialog.ShowAsync(this, Title!,
                $"{PicoChessLocation.StartScript} is missing from this PicoChess folder. Click Upgrade to update it.");
            return;
        }
        if (!PicoChessLocation.HasVirtualEnvironment(_repositoryPath))
        {
            await MessageDialog.ShowAsync(this, Title!,
                "The PicoChess Python environment (venv) is missing. Click Upgrade to run the setup script.");
            return;
        }

        // Re-read the port in case picochess.ini was edited since the panel opened.
        SetRepository(_repositoryPath);
        try
        {
            _log.Text = string.Empty;
            _picoChess.Start(_repositoryPath);
        }
        catch (Exception exception)
        {
            AppendLog($"ERROR: {exception.Message}");
            await MessageDialog.ShowAsync(this, "PicoChess could not be started", exception.Message);
        }
        await RefreshStatusAsync();
    }

    private void OpenBrowser()
    {
        try
        {
            Process.Start(new ProcessStartInfo("/usr/bin/open") { ArgumentList = { Url }, UseShellExecute = false });
        }
        catch (Exception exception) when (exception is System.ComponentModel.Win32Exception or InvalidOperationException)
        {
            AppendLog($"Could not open {Url}: {exception.Message}");
        }
    }

    private async Task StopAsync()
    {
        _busy = true;
        _status.Text = "Stopping...";
        UpdateControls();
        try
        {
            await _picoChess.StopAsync();
            AppendLog("PicoChess stopped.");
        }
        catch (Exception exception)
        {
            AppendLog($"ERROR while stopping: {exception.Message}");
        }
        finally
        {
            _busy = false;
        }
        await RefreshStatusAsync();
    }

    private async Task UpgradeAsync()
    {
        if (_repositoryPath is null) return;
        var confirmed = await MessageDialog.ConfirmAsync(this, Title!,
            "Upgrade updates PicoChess from GitHub and re-runs the macOS install script. " +
            "Local changes in the PicoChess folder will stop the update.\n\nContinue?");
        if (!confirmed) return;

        _busy = true;
        _status.Text = "Upgrading...";
        UpdateControls();
        _log.Text = string.Empty;
        try
        {
            var exitCode = await MacInstaller.UpgradeAsync(_repositoryPath, AppendLog, CancellationToken.None);
            AppendLog(exitCode == 0 ? "Upgrade completed." : $"Upgrade failed with exit code {exitCode}.");
            if (exitCode != 0)
            {
                await MessageDialog.ShowAsync(this, Title!, "The upgrade failed. See the log for details.");
            }
        }
        catch (Exception exception)
        {
            AppendLog($"ERROR: {exception.Message}");
        }
        finally
        {
            _busy = false;
            SetRepository(_repositoryPath);
        }
        await RefreshStatusAsync();
    }

    private async void OnPicoChessExited()
    {
        if (!_busy) AppendLog("PicoChess has exited.");
        await RefreshStatusAsync();
    }

    private async Task RefreshStatusAsync()
    {
        if (_probing) return;
        _probing = true;
        try
        {
            _webServerUp = _repositoryPath is not null && await IsPortOpenAsync(_webPort);
        }
        finally
        {
            _probing = false;
        }

        if (!_busy)
        {
            var running = _picoChess.IsRunning;
            _status.Text = (running, _webServerUp) switch
            {
                (true, true) => $"Running - {Url}",
                (true, false) => "Starting...",
                (false, true) => $"Running outside this control panel - {Url}",
                _ => "Stopped"
            };
            _status.Foreground = _webServerUp ? Brushes.ForestGreen : running ? Brushes.DarkOrange : Brushes.Gray;
        }
        UpdateControls();
    }

    private void UpdateControls()
    {
        var owned = _picoChess.IsRunning;
        var idle = !_busy && _repositoryPath is not null;
        _start.IsEnabled = idle && !owned && !_webServerUp;
        _browser.IsEnabled = _webServerUp;
        _stop.IsEnabled = !_busy && owned;
        _upgrade.IsEnabled = idle && !owned && !_webServerUp;
        _changeFolder.IsEnabled = !_busy && !owned;
        _install.IsEnabled = !_busy;
        _installDirectory.IsEnabled = !_busy;
        _installResources.IsEnabled = !_busy;
    }

    private static async Task<bool> IsPortOpenAsync(int port)
    {
        using var client = new TcpClient();
        using var timeout = new CancellationTokenSource(TimeSpan.FromMilliseconds(400));
        try
        {
            await client.ConnectAsync("127.0.0.1", port, timeout.Token);
            return true;
        }
        catch (Exception exception) when (exception is SocketException or OperationCanceledException)
        {
            return false;
        }
    }

    private void AppendLog(string message)
    {
        if (!Dispatcher.UIThread.CheckAccess())
        {
            Dispatcher.UIThread.Post(() => AppendLog(message));
            return;
        }
        var text = (_log.Text ?? string.Empty) + message + Environment.NewLine;
        if (text.Length > MaxLogLength)
        {
            text = text[^MaxLogLength..];
        }
        _log.Text = text;
        _log.CaretIndex = text.Length;
    }

    private async void OnClosing(object? sender, WindowClosingEventArgs e)
    {
        if (_closeAfterStop) return;
        if (_busy)
        {
            e.Cancel = true;
            return;
        }
        if (!_picoChess.IsRunning) return;

        // PicoChess writes to pipes owned by this app, so it is stopped with it.
        e.Cancel = true;
        var confirmed = await MessageDialog.ConfirmAsync(this, Title!,
            "PicoChess is running. Stop PicoChess and close the control panel?", "Stop and close");
        if (!confirmed) return;

        await StopAsync();
        _closeAfterStop = true;
        Close();
    }

    protected override void OnClosed(EventArgs e)
    {
        _statusTimer.Stop();
        _picoChess.Dispose();
        base.OnClosed(e);
    }
}
