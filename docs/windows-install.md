# Installing PicoChess on Windows

The Windows installer prepares PicoChess without installing chess engines,
Windows services, scheduled tasks, drivers, or Linux host integrations. It can
use an existing repository checkout or clone the repository when the selected
installation directory is absent or empty.

The currently validated baseline is 64-bit Windows with 64-bit CPython 3.13.

## Prerequisites

- 64-bit Windows 10 or Windows 11.
- 64-bit CPython 3.13 from <https://www.python.org/downloads/windows/>.
  Enabling the Python launcher (`py.exe`) during installation is recommended.
- Git for Windows when the repository still needs to be cloned, or when using
  the optional repository-update mode.
- Internet access for Python dependencies and selected resource packs.

The installer does not require administrator privileges. Do not install
PicoChess under `Program Files`; a normal user-writable directory is preferred.

## Basic installation

From an existing PicoChess checkout, open PowerShell in the repository root:

```powershell
.\install-picochess-windows.ps1
```

When PowerShell script execution is restricted, enable it only for the current
PowerShell process and then run the installer:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install-picochess-windows.ps1
```

To use the script as a bootstrap installer outside a checkout:

```powershell
.\install-picochess-windows.ps1 -InstallDir "$env:USERPROFILE\PicoChess"
```

The installer creates or reuses `venv`, installs `requirements.txt`, creates
runtime directories and `talker\voices\voices.ini`, installs portable resource
packs, and runs dependency/import smoke tests.

It never resets local Git changes. Repository updating is opt-in and succeeds
only on a clean branch using a fast-forward-only pull:

```powershell
.\install-picochess-windows.ps1 -UpdateRepo
```

## Resource selection

The default resource selection is:

```text
Books, OpeningData, Games
```

Select a subset or skip all resource downloads with:

```powershell
.\install-picochess-windows.ps1 -Resources Books,OpeningData
.\install-picochess-windows.ps1 -SkipResources
```

Existing resources with their expected marker files are preserved. Incomplete
resource directories cause the installer to stop rather than merge unknown
content. `-ForceResources` moves existing data to a timestamped backup under
`%LOCALAPPDATA%\PicoChess\backups` before installing a clean copy.

### Games database limitation

The games resource pack supplies database data, but the web client's Games tab
also needs a `tcscid` HTTP server on port 7778. The existing server launcher and
packaged binaries are Linux-oriented. This first Windows installer deliberately
does not install or start a Windows service, so installing the games pack alone
does not enable the Games tab.

### MAME limitation

The existing MAME resource packs are distributed by the Linux engine installer
and include platform-specific runtime assumptions. They are not installed on
Windows. Windows MAME support needs a native resource pack and runtime validation
before it can safely become an installer option.

## Engines and configuration

No engine is downloaded or installed. Follow [the engine setup guide](../engines/README.md#experimental-windows-amd64-setup)
and place a native Windows UCI engine and its catalog files under:

```text
engines\AMD64\
```

The installer preserves an existing `picochess.ini`. If it is missing, the
installer does not create one because it cannot safely guess the engine path.
A minimal web-only configuration after installing an engine is:

```ini
engine = engines\AMD64\stockfish.exe
engine-level = Elo@2200
tutor-engine = engines\AMD64\stockfish.exe
board-type = noeboard
web-server = 8080
theme = dark
book = books\h-varied.bin
```

Adjust the executable and level names to match the local engine catalog.

## Validation and recovery options

Inspect prerequisites and an existing checkout without changing anything:

```powershell
.\install-picochess-windows.ps1 -ValidateOnly
```

Other recovery and diagnostic switches are:

```powershell
# Move the current venv aside and build a new one.
.\install-picochess-windows.ps1 -RecreateVenv

# Install without running the final imports and --help checks.
.\install-picochess-windows.ps1 -SkipSmokeTests
```

The old environment created by `-RecreateVenv` is retained as
`venv.backup.<timestamp>` until it is removed manually.

## Starting PicoChess

After installing and configuring a Windows engine, run from the repository root:

```powershell
.\venv\Scripts\python.exe .\picochess.py
```

Then open <http://localhost:8080>. See
[Windows port status](windows-port-status.md) for currently validated features
and known Windows limitations.

