using System.Diagnostics;
using System.Drawing;
using System.Net.Sockets;

namespace PicoChess.ControlPanel;

internal sealed class ControlPanelForm : Form
{
    private readonly Button _start = new();
    private readonly Button _browser = new();
    private readonly Button _stop = new();
    private readonly Button _upgrade = new();
    private readonly Button _browse = new();
    private readonly Label _repository = new();
    private readonly Label _status = new();
    private readonly RichTextBox _log = new();
    private readonly System.Windows.Forms.Timer _statusTimer = new() { Interval = 1000 };
    private readonly PicoChessProcess _picoChess;
    private string? _repositoryPath;
    private int _webPort;
    private bool _webServerUp;
    private bool _busy;
    private bool _probing;
    private bool _closeAfterStop;

    public ControlPanelForm(string[] args)
    {
        _picoChess = new PicoChessProcess(AppendLog);
        _picoChess.Exited += (_, _) => RunOnUiThread(OnPicoChessExited);

        Text = "PicoChess Control Panel";
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(620, 460);
        Size = new Size(760, 560);
        Font = new Font("Segoe UI", 9F);
        AutoScaleMode = AutoScaleMode.Dpi;

        var title = new Label
        {
            Text = "PicoChess",
            Font = new Font("Segoe UI Semibold", 20F),
            AutoSize = true,
            Margin = new Padding(0, 0, 0, 4)
        };

        _repository.AutoSize = true;
        _repository.ForeColor = Color.DimGray;
        _repository.Anchor = AnchorStyles.Left;

        _browse.Text = "Change folder...";
        _browse.AutoSize = true;
        _browse.Click += Browse_Click;

        var repositoryRow = new TableLayoutPanel
        {
            AutoSize = true,
            Dock = DockStyle.Top,
            ColumnCount = 2,
            Margin = new Padding(0, 0, 0, 12)
        };
        repositoryRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
        repositoryRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        repositoryRow.Controls.Add(_repository, 0, 0);
        repositoryRow.Controls.Add(_browse, 1, 0);

        _status.AutoSize = true;
        _status.Font = new Font("Segoe UI Semibold", 11F);
        _status.Margin = new Padding(0, 0, 0, 12);

        ConfigureButton(_start, "Start", Start_Click);
        ConfigureButton(_browser, "Open in browser", Browser_Click);
        ConfigureButton(_stop, "Stop", Stop_Click);
        ConfigureButton(_upgrade, "Upgrade", Upgrade_Click);

        var buttonRow = new FlowLayoutPanel
        {
            AutoSize = true,
            Dock = DockStyle.Top,
            WrapContents = true,
            Margin = new Padding(0, 0, 0, 12)
        };
        buttonRow.Controls.AddRange([_start, _browser, _stop, _upgrade]);

        _log.Dock = DockStyle.Fill;
        _log.ReadOnly = true;
        _log.BackColor = Color.FromArgb(30, 30, 30);
        _log.ForeColor = Color.Gainsboro;
        _log.Font = new Font("Cascadia Mono", 9F);
        _log.WordWrap = false;

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(24),
            RowCount = 5,
            ColumnCount = 1
        };
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));
        layout.Controls.Add(title, 0, 0);
        layout.Controls.Add(repositoryRow, 0, 1);
        layout.Controls.Add(_status, 0, 2);
        layout.Controls.Add(buttonRow, 0, 3);
        layout.Controls.Add(_log, 0, 4);
        Controls.Add(layout);

        SetRepository(PicoChessLocation.Resolve(args));
        if (_repositoryPath is null)
        {
            AppendLog("No PicoChess installation was found. Use \"Change folder...\" to select it.");
        }

        _statusTimer.Tick += async (_, _) => await RefreshStatusAsync();
        Shown += async (_, _) =>
        {
            _statusTimer.Start();
            await RefreshStatusAsync();
        };
    }

    private string Url => $"http://localhost:{_webPort}/";

    private static void ConfigureButton(Button button, string text, EventHandler onClick)
    {
        button.Text = text;
        button.AutoSize = true;
        button.MinimumSize = new Size(130, 0);
        button.Padding = new Padding(12, 6, 12, 6);
        button.Margin = new Padding(0, 0, 8, 0);
        button.Click += onClick;
    }

    private void SetRepository(string? repository)
    {
        _repositoryPath = repository;
        _webPort = repository is null ? 8080 : PicoChessLocation.ReadWebPort(repository);
        _repository.Text = repository is null
            ? "PicoChess folder: not found"
            : $"PicoChess folder: {repository}    Web port: {_webPort}";
        UpdateControls();
    }

    private void Browse_Click(object? sender, EventArgs e)
    {
        using var dialog = new FolderBrowserDialog
        {
            Description = "Select the PicoChess folder (it contains picochess.py)",
            UseDescriptionForTitle = true,
            SelectedPath = _repositoryPath ?? Environment.GetFolderPath(Environment.SpecialFolder.UserProfile)
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;

        if (!PicoChessLocation.IsCheckout(dialog.SelectedPath))
        {
            MessageBox.Show(this,
                $"This folder does not contain picochess.py and {PicoChessLocation.StartScript}.",
                Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        PicoChessLocation.SaveRepository(dialog.SelectedPath);
        SetRepository(dialog.SelectedPath);
    }

    private async void Start_Click(object? sender, EventArgs e)
    {
        if (_repositoryPath is null) return;
        if (!PicoChessLocation.HasVirtualEnvironment(_repositoryPath))
        {
            MessageBox.Show(this,
                "The PicoChess Python environment (venv) is missing. Run the PicoChess installer or Upgrade first.",
                Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        // Re-read the port in case picochess.ini was edited since the panel opened.
        SetRepository(_repositoryPath);
        try
        {
            _log.Clear();
            _picoChess.Start(_repositoryPath);
        }
        catch (Exception exception)
        {
            AppendLog($"ERROR: {exception.Message}");
            MessageBox.Show(this, exception.Message, "PicoChess could not be started",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        await RefreshStatusAsync();
    }

    private void Browser_Click(object? sender, EventArgs e)
    {
        try
        {
            Process.Start(new ProcessStartInfo(Url) { UseShellExecute = true });
        }
        catch (Exception exception) when (exception is System.ComponentModel.Win32Exception or InvalidOperationException)
        {
            MessageBox.Show(this, $"Could not open {Url}: {exception.Message}", Text,
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private async void Stop_Click(object? sender, EventArgs e) => await StopAsync();

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

    private async void Upgrade_Click(object? sender, EventArgs e)
    {
        if (_repositoryPath is null) return;
        var answer = MessageBox.Show(this,
            "Upgrade updates PicoChess from GitHub and re-runs the Windows install script. " +
            "Local changes in the PicoChess folder will stop the update.\r\n\r\nContinue?",
            Text, MessageBoxButtons.OKCancel, MessageBoxIcon.Question);
        if (answer != DialogResult.OK) return;

        _busy = true;
        _status.Text = "Upgrading...";
        UpdateControls();
        _log.Clear();
        try
        {
            var exitCode = await PicoChessProcess.RunUpgradeAsync(_repositoryPath, AppendLog, CancellationToken.None);
            AppendLog(exitCode == 0 ? "Upgrade completed." : $"Upgrade failed with exit code {exitCode}.");
            if (exitCode != 0)
            {
                MessageBox.Show(this, "The upgrade failed. See the log for details.", Text,
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
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
        if (_probing || IsDisposed) return;
        _probing = true;
        try
        {
            _webServerUp = await IsPortOpenAsync(_webPort);
        }
        finally
        {
            _probing = false;
        }
        if (IsDisposed) return;

        if (!_busy)
        {
            _status.Text = (_picoChess.IsRunning, _webServerUp) switch
            {
                (true, true) => $"Running - {Url}",
                (true, false) => "Starting...",
                (false, true) => $"Running outside this control panel - {Url}",
                _ => "Stopped"
            };
            _status.ForeColor = _webServerUp ? Color.ForestGreen : (_picoChess.IsRunning ? Color.DarkOrange : Color.DimGray);
        }
        UpdateControls();
    }

    private void UpdateControls()
    {
        var owned = _picoChess.IsRunning;
        var idle = !_busy && _repositoryPath is not null;
        _start.Enabled = idle && !owned && !_webServerUp;
        _browser.Enabled = _webServerUp;
        _stop.Enabled = !_busy && owned;
        _upgrade.Enabled = idle && !owned && !_webServerUp;
        _browse.Enabled = !_busy && !owned;
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
        if (IsDisposed) return;
        if (InvokeRequired)
        {
            RunOnUiThread(() => AppendLog(message));
            return;
        }
        _log.AppendText(message + Environment.NewLine);
        _log.SelectionStart = _log.TextLength;
        _log.ScrollToCaret();
    }

    private void RunOnUiThread(Action action)
    {
        try
        {
            if (!IsDisposed) BeginInvoke(action);
        }
        catch (InvalidOperationException)
        {
            // The window is closing; there is nothing left to update.
        }
    }

    protected override async void OnFormClosing(FormClosingEventArgs e)
    {
        base.OnFormClosing(e);
        if (_closeAfterStop) return;

        if (_busy)
        {
            e.Cancel = true;
            return;
        }
        if (!_picoChess.IsRunning) return;

        // PicoChess writes to pipes owned by this window, so it is stopped with it.
        var answer = MessageBox.Show(this, "PicoChess is running. Stop PicoChess and close the control panel?",
            Text, MessageBoxButtons.OKCancel, MessageBoxIcon.Question);
        e.Cancel = true;
        if (answer != DialogResult.OK) return;

        await StopAsync();
        _closeAfterStop = true;
        Close();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _statusTimer.Dispose();
            _picoChess.Dispose();
        }
        base.Dispose(disposing);
    }
}
