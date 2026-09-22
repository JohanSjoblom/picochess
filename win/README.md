# PicoChess Windows installer

This folder contains an MVP graphical installer built with C# and Windows Forms on .NET 10.
It performs the following steps:

1. Checks for Git and 64-bit CPython 3.13.
2. Installs missing prerequisites with Windows Package Manager (`winget`).
3. Clones `https://github.com/JohanSjoblom/picochess.git`, or reuses an existing checkout.
4. Runs `install-picochess-windows.ps1` and displays its live output.

The app runs as the current user. `winget` may show a Windows elevation prompt if a prerequisite
installer requires one.

## Build and run

Install the [.NET 10 SDK](https://dotnet.microsoft.com/download/dotnet/10.0), then run:

```powershell
dotnet run --project .\win\PicoChess.WindowsInstaller
```

Create a self-contained single-file executable for 64-bit Windows:

```powershell
dotnet publish .\win\PicoChess.WindowsInstaller -c Release -r win-x64 `
  --self-contained true -p:PublishSingleFile=true
```

The executable is written below
`win\PicoChess.WindowsInstaller\bin\Release\net10.0-windows\win-x64\publish`.

## MVP limitations

- `winget` (App Installer) must already be available on the PC.
- The repository URL is currently fixed to the official PicoChess repository.
- The installer targets x64 Windows and CPython 3.13, matching the supported versions in the
  PowerShell installer.
- Code signing and an MSI/MSIX packaging layer are not included yet.
