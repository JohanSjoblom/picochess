# PicoChess Windows installer

This folder contains an MVP graphical installer built with C# and Windows Forms on .NET 10.
It performs the following steps:

1. Checks for Git and 64-bit CPython 3.13.
2. Installs missing prerequisites with Windows Package Manager (`winget`).
3. Clones `https://github.com/JohanSjoblom/picochess.git`, or reuses an existing checkout.
4. Runs `install-picochess-windows.ps1` and displays its live output.

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

Create a self-contained single-file executable for 64-bit Windows:

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

- `winget` (App Installer) must already be available on the PC.
- The repository URL is currently fixed to the official PicoChess repository.
- The installer targets x64 Windows and CPython 3.13, matching the supported versions in the
  PowerShell installer.
- Code signing and an MSI/MSIX packaging layer are not included yet.
