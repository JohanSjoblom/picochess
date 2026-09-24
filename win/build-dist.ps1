<#
.SYNOPSIS
Builds the distributable PicoChess Windows installer and its SHA-256 checksum.

.DESCRIPTION
Publishes PicoChess.WindowsInstaller as a self-contained, single-file win-x64
executable (it also contains the control panel) and writes
PicoChessInstaller.exe plus PicoChessInstaller.exe.sha256 to the output folder.
The checksum file uses the sha256sum format, so it can be verified with
"sha256sum -c" or compared with Get-FileHash.

.PARAMETER OutputDirectory
Destination folder. Defaults to sdist in the repository root (ignored by Git).
#>

[CmdletBinding()]
param(
    [string]$OutputDirectory
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

# Windows PowerShell 5.1 does not populate $PSScriptRoot in parameter defaults.
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path (Split-Path $PSScriptRoot -Parent) "sdist"
}

$project = Join-Path $PSScriptRoot "PicoChess.WindowsInstaller"
$executableName = "PicoChessInstaller.exe"
$publishDirectory = Join-Path ([IO.Path]::GetTempPath()) ("picochess-publish-" + [Guid]::NewGuid().ToString("N"))

try {
    & dotnet publish $project -c Release -r win-x64 --self-contained true `
        -p:PublishSingleFile=true -p:EnableCompressionInSingleFile=true -o $publishDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "dotnet publish failed with exit code $LASTEXITCODE."
    }

    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    $executable = Join-Path $OutputDirectory $executableName
    Copy-Item -LiteralPath (Join-Path $publishDirectory $executableName) -Destination $executable -Force

    $hash = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
    $checksumFile = "$executable.sha256"
    # sha256sum format: "<hash> *<file>" (binary mode), LF line ending, no BOM.
    [IO.File]::WriteAllText($checksumFile, "$hash *$executableName`n", (New-Object Text.UTF8Encoding($false)))

    Write-Host "Executable: $executable ($([Math]::Round((Get-Item $executable).Length / 1MB, 1)) MB)"
    Write-Host "SHA-256:    $hash"
    Write-Host "Checksum:   $checksumFile"
} finally {
    if (Test-Path -LiteralPath $publishDirectory) {
        Remove-Item -LiteralPath $publishDirectory -Recurse -Force
    }
}
