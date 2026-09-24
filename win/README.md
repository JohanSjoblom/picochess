# PicoChess Windows installer

This folder contains an MVP graphical installer built with C# and Windows Forms on .NET 10.
It performs the following steps:

1. Checks for Git and 64-bit (x64) CPython 3.11-3.13. An existing supported installation is
   reused; CPython 3.13 is installed only when none is found.
2. Installs missing prerequisites with Windows Package Manager (`winget`).
3. Clones `https://github.com/JohanSjoblom/picochess.git`, or reuses an existing checkout.
4. Runs `install-picochess-windows.ps1` and displays its live output.
5. Installs the PicoChess control panel (see below) and creates a **PicoChess** shortcut in the
   Start menu and, optionally, on the desktop.

The installer executable also contains the control panel, so end users download a single file.
After a successful installation it copies itself to `%LOCALAPPDATA%\Programs\PicoChess\PicoChess.exe`
(outside the Git checkout, so the install script's clean-checkout check is unaffected). The shortcuts
start that copy with `--control-panel --repo "<install folder>"`. Running the installer again
refreshes the copy and the shortcuts; close the control panel first.

The app runs as the current user. `winget` may show a Windows elevation prompt if a prerequisite
installer requires one.

> **Beta note:** Fresh installations currently clone the `471-port-to-windows` branch explicitly.
> This temporary branch pin must be removed before the Windows port is merged into the default
> branch.

## Download

The self-contained `PicoChessInstaller.exe` will be available as a downloadable asset on the
project's GitHub Releases page. It includes the required .NET runtime, so end users do not need to
install .NET before running it. Generated executables remain excluded from the Git repository.

## Build and run

Install the [.NET 10 SDK](https://dotnet.microsoft.com/download/dotnet/10.0), then run:

```powershell
dotnet run --project .\win\PicoChess.WindowsInstaller
```

Build the distributable installer and its checksum into `sdist` at the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\win\build-dist.ps1
```

This writes `sdist\PicoChessInstaller.exe` and `sdist\PicoChessInstaller.exe.sha256` (sha256sum
format, verify with `sha256sum -c PicoChessInstaller.exe.sha256` or `Get-FileHash`). `sdist` is
ignored by Git; it only collects files to upload to a GitHub release. Pass `-OutputDirectory` to
build somewhere else.

To publish manually instead, create a self-contained single-file executable for 64-bit Windows:

```powershell
dotnet publish .\win\PicoChess.WindowsInstaller -c Release -r win-x64 `
  --self-contained true -p:PublishSingleFile=true `
  -p:EnableCompressionInSingleFile=true -o .\win\artifacts\self-contained
```

The executable is written to `win\artifacts\self-contained`. Build outputs under
`win\artifacts`, `bin`, and `obj` are deliberately ignored by Git.

The self-contained build is the useful end-user package because it does not require .NET to be
installed first. A framework-dependent publish is much smaller, but requires the matching .NET 10
Desktop Runtime on the destination PC.

## MVP limitations

- `winget` (App Installer) must already be available on the PC to install missing prerequisites.
- The repository URL is currently fixed to the official PicoChess repository.
- The installer targets x64 Windows and accepts CPython 3.11-3.13, matching the supported
  versions in the PowerShell installer. New Python installations use 3.13.
- Code signing and an MSI/MSIX packaging layer are not included yet.
- There is no uninstaller. Remove `%LOCALAPPDATA%\Programs\PicoChess`, the `PicoChess` shortcuts in
  the Start menu and on the desktop, and the PicoChess folder manually.

# PicoChess control panel

`PicoChess.ControlPanel` is a small Windows Forms app (.NET 10) for running an installed PicoChess
without a terminal. It has four buttons:

- **Start** runs `start-picochess-windows.ps1` from the PicoChess folder in a hidden console. That
  launcher starts `venv\Scripts\python.exe picochess.py` and the optional Scid games helper.
- **Open in browser** opens `http://localhost:<port>/`. The port is read from `web-server` in
  `picochess.ini` (default 8080). It is enabled once the web server accepts connections.
- **Stop** sends Ctrl+C to the hidden console, so PicoChess runs its normal SIGINT shutdown and the
  launcher stops the games helper. Anything still running after 20 seconds is terminated.
- **Upgrade** re-runs `install-picochess-windows.ps1 -InstallDir <folder> -UpdateRepo`. It is only
  enabled while PicoChess is stopped. The install script refuses to update a checkout with local
  changes.

The status line shows Stopped, Starting, Running, or "Running outside this control panel" when
something else already listens on the web port. Output from PicoChess and the scripts is shown in
the log pane. Closing the window while PicoChess is running offers to stop it first, because the
PicoChess process writes its output to the control panel.

The PicoChess folder is found in this order: `--repo <folder>` on the command line, the
`PICOCHESS_HOME` environment variable, the folder last chosen with **Change folder...** (saved in
`%LOCALAPPDATA%\PicoChess\controlpanel-repository.txt`), a checkout containing the executable, and
the installer default `%USERPROFILE%\PicoChess`.

End users get the control panel from the installer. The installer project compiles in the
control panel sources (everything except its `Program.cs`) and opens the control panel when
started with `--control-panel`. The standalone project is kept for development:

```powershell
dotnet run --project .\win\PicoChess.ControlPanel
dotnet run --project .\win\PicoChess.WindowsInstaller -- --control-panel
```

Not included yet: a tray icon and starting PicoChess automatically at sign-in.
