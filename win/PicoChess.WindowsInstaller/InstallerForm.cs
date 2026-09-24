using System.Diagnostics;
using System.Drawing;

namespace PicoChess.WindowsInstaller;

internal sealed class InstallerForm : Form
{
    private readonly TextBox _installDirectory = new();
    private readonly CheckBox _resources = new();
    private readonly CheckBox _update = new();
    private readonly CheckBox _desktopShortcut = new();
    private readonly RichTextBox _log = new();
    private readonly Button _install = new();
    private readonly Button _cancel = new();
    private readonly Button _openFolder = new();
    private readonly Button _openControlPanel = new();
    private readonly Button _browse = new();
    private readonly ProgressBar _progress = new();
    private readonly Label _status = new();
    private CancellationTokenSource? _cancellation;
    private string? _controlPanel;
    private string? _installedDirectory;

    public InstallerForm()
    {
        Text = "PicoChess Setup";
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(720, 640);
        Size = new Size(840, 720);
        Font = new Font("Segoe UI", 9F);
        AutoScaleMode = AutoScaleMode.Dpi;

        var title = new Label
        {
            Text = "Install PicoChess for Windows",
            Font = new Font("Segoe UI Semibold", 20F),
            AutoSize = true,
            Margin = new Padding(0, 0, 0, 4)
        };
        var subtitle = new Label
        {
            Text = "This assistant installs Git and Python 3.13 when needed, clones PicoChess, and prepares its Python environment.",
            AutoSize = true,
            ForeColor = Color.DimGray,
            MaximumSize = new Size(760, 0),
            Margin = new Padding(0, 0, 0, 18)
        };

        var directoryLabel = new Label { Text = "Installation folder", AutoSize = true };
        _installDirectory.Text = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "PicoChess");
        _installDirectory.Dock = DockStyle.Fill;

        _browse.Text = "Browse...";
        _browse.AutoSize = true;
        _browse.Click += Browse_Click;

        var directoryRow = new TableLayoutPanel
        {
            AutoSize = true,
            Dock = DockStyle.Top,
            ColumnCount = 2,
            Margin = new Padding(0, 4, 0, 12)
        };
        directoryRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
        directoryRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        directoryRow.Controls.Add(_installDirectory, 0, 0);
        directoryRow.Controls.Add(_browse, 1, 0);

        _resources.Text = "Download the standard books, opening data, and games resources";
        _resources.Checked = true;
        _resources.AutoSize = true;
        _resources.Margin = new Padding(0, 0, 0, 6);

        _update.Text = "Update an existing clean checkout before installing";
        _update.Checked = true;
        _update.AutoSize = true;
        _update.Margin = new Padding(0, 0, 0, 6);

        _desktopShortcut.Text = "Create a desktop shortcut for the PicoChess control panel";
        _desktopShortcut.Checked = true;
        _desktopShortcut.AutoSize = true;
        _desktopShortcut.Margin = new Padding(0, 0, 0, 14);

        _log.Dock = DockStyle.Fill;
        _log.ReadOnly = true;
        _log.BackColor = Color.FromArgb(30, 30, 30);
        _log.ForeColor = Color.Gainsboro;
        _log.Font = new Font("Cascadia Mono", 9F);
        _log.WordWrap = false;
        _log.Text = "Ready. Click Install to begin.\r\n";

        _status.Text = "Ready";
        _status.AutoSize = true;
        _status.Anchor = AnchorStyles.Left;

        _progress.Style = ProgressBarStyle.Marquee;
        _progress.MarqueeAnimationSpeed = 30;
        _progress.Visible = false;
        _progress.Dock = DockStyle.Fill;

        _install.Text = "Install";
        _install.AutoSize = true;
        _install.Padding = new Padding(18, 4, 18, 4);
        _install.Click += Install_Click;
        AcceptButton = _install;

        _cancel.Text = "Cancel";
        _cancel.AutoSize = true;
        _cancel.Padding = new Padding(10, 4, 10, 4);
        _cancel.Enabled = false;
        _cancel.Click += (_, _) => _cancellation?.Cancel();

        _openFolder.Text = "Open folder";
        _openFolder.AutoSize = true;
        _openFolder.Padding = new Padding(10, 4, 10, 4);
        _openFolder.Visible = false;
        _openFolder.Click += OpenFolder_Click;

        _openControlPanel.Text = "Open PicoChess";
        _openControlPanel.AutoSize = true;
        _openControlPanel.Padding = new Padding(18, 4, 18, 4);
        _openControlPanel.Visible = false;
        _openControlPanel.Click += OpenControlPanel_Click;

        var buttonRow = new FlowLayoutPanel
        {
            FlowDirection = FlowDirection.RightToLeft,
            Dock = DockStyle.Fill,
            AutoSize = true,
            WrapContents = false
        };
        buttonRow.Controls.Add(_openControlPanel);
        buttonRow.Controls.Add(_install);
        buttonRow.Controls.Add(_cancel);
        buttonRow.Controls.Add(_openFolder);

        var footer = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, AutoSize = true };
        footer.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
        footer.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        footer.Controls.Add(_status, 0, 0);
        footer.Controls.Add(_progress, 1, 0);
        footer.Controls.Add(buttonRow, 2, 0);

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(28),
            RowCount = 9,
            ColumnCount = 1
        };
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.Controls.Add(title, 0, 0);
        layout.Controls.Add(subtitle, 0, 1);
        layout.Controls.Add(directoryLabel, 0, 2);
        layout.Controls.Add(directoryRow, 0, 3);
        layout.Controls.Add(_resources, 0, 4);
        layout.Controls.Add(_update, 0, 5);
        layout.Controls.Add(_desktopShortcut, 0, 6);
        layout.Controls.Add(_log, 0, 7);
        layout.Controls.Add(footer, 0, 8);
        Controls.Add(layout);
    }

    private void Browse_Click(object? sender, EventArgs e)
    {
        using var dialog = new FolderBrowserDialog
        {
            Description = "Choose where PicoChess will be installed",
            SelectedPath = _installDirectory.Text,
            UseDescriptionForTitle = true,
            ShowNewFolderButton = true
        };
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            _installDirectory.Text = dialog.SelectedPath;
        }
    }

    private async void Install_Click(object? sender, EventArgs e)
    {
        if (string.IsNullOrWhiteSpace(_installDirectory.Text))
        {
            MessageBox.Show(this, "Choose an installation folder.", Text,
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        SetBusy(true);
        _log.Clear();
        _cancellation = new CancellationTokenSource();
        var service = new InstallerService(AppendLog);
        var options = new InstallerOptions(
            _installDirectory.Text, _resources.Checked, _update.Checked, _desktopShortcut.Checked);

        try
        {
            _controlPanel = await service.InstallAsync(options, _cancellation.Token);
            _installedDirectory = Path.GetFullPath(Environment.ExpandEnvironmentVariables(_installDirectory.Text.Trim()));
            _status.Text = "Installation complete";
            _openFolder.Visible = true;
            _openControlPanel.Visible = true;
            AcceptButton = _openControlPanel;
            MessageBox.Show(this,
                "PicoChess was installed successfully.\r\n\r\n" +
                "Start it with the PicoChess shortcut in the Start menu" +
                (options.CreateDesktopShortcut ? " or on the desktop" : "") +
                ", or click Open PicoChess.",
                Text, MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (OperationCanceledException)
        {
            AppendLog("\r\nInstallation cancelled.");
            _status.Text = "Cancelled";
        }
        catch (Exception exception)
        {
            AppendLog($"\r\nERROR: {exception.Message}");
            _status.Text = "Installation failed";
            MessageBox.Show(this, exception.Message, "PicoChess installation failed",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally
        {
            _cancellation.Dispose();
            _cancellation = null;
            SetBusy(false);
        }
    }

    private void SetBusy(bool busy)
    {
        _install.Enabled = !busy;
        _installDirectory.Enabled = !busy;
        _browse.Enabled = !busy;
        _resources.Enabled = !busy;
        _update.Enabled = !busy;
        _desktopShortcut.Enabled = !busy;
        _openControlPanel.Enabled = !busy;
        _cancel.Enabled = busy;
        _progress.Visible = busy;
        if (busy) _status.Text = "Installing...";
    }

    private void AppendLog(string message)
    {
        if (InvokeRequired)
        {
            BeginInvoke(() => AppendLog(message));
            return;
        }
        _log.AppendText(message + Environment.NewLine);
        _log.SelectionStart = _log.TextLength;
        _log.ScrollToCaret();
    }

    private void OpenControlPanel_Click(object? sender, EventArgs e)
    {
        if (_controlPanel is null || _installedDirectory is null) return;
        try
        {
            ControlPanelInstaller.Launch(_controlPanel, _installedDirectory);
            Close();
        }
        catch (Exception exception) when (exception is System.ComponentModel.Win32Exception or InvalidOperationException)
        {
            MessageBox.Show(this, exception.Message, "PicoChess control panel could not be started",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private void OpenFolder_Click(object? sender, EventArgs e)
    {
        var directory = Path.GetFullPath(Environment.ExpandEnvironmentVariables(_installDirectory.Text.Trim()));
        if (Directory.Exists(directory))
        {
            Process.Start(new ProcessStartInfo("explorer.exe", directory) { UseShellExecute = true });
        }
    }
}
