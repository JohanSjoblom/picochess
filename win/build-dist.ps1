<#
.SYNOPSIS
Builds the distributable PicoChess Windows installer, a release zip, and their SHA-256 checksums.

.DESCRIPTION
Publishes PicoChess.WindowsInstaller as a self-contained, single-file win-x64
executable (it also contains the control panel) and writes these files to the
output folder:

  PicoChessInstaller.exe
  PicoChessInstaller.exe.sha256
  PicoChessInstaller.zip          (contains the two files above)
  PicoChessInstaller.zip.sha256

The zip and its checksum are the files to upload to a GitHub release. The
checksum files use the sha256sum format, so they can be verified with
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

function Write-Sha256File {
    param([string]$Path)

    $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    $checksumFile = "$Path.sha256"
    # sha256sum format: "<hash> *<file>" (binary mode), LF line ending, no BOM.
    [IO.File]::WriteAllText($checksumFile, "$hash *$(Split-Path $Path -Leaf)`n", (New-Object Text.UTF8Encoding($false)))

    Write-Host "File:     $Path ($([Math]::Round((Get-Item -LiteralPath $Path).Length / 1MB, 1)) MB)"
    Write-Host "SHA-256:  $hash"
    Write-Host "Checksum: $checksumFile"
    return $checksumFile
}

$project = Join-Path $PSScriptRoot "PicoChess.WindowsInstaller"
$executableName = "PicoChessInstaller.exe"
$zipName = "PicoChessInstaller.zip"
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
    $executableChecksum = Write-Sha256File -Path $executable

    $zip = Join-Path $OutputDirectory $zipName
    if (Test-Path -LiteralPath $zip) {
        Remove-Item -LiteralPath $zip -Force
    }
    Compress-Archive -LiteralPath $executable, $executableChecksum -DestinationPath $zip -CompressionLevel Optimal
    Write-Host ""
    Write-Sha256File -Path $zip | Out-Null
} finally {
    if (Test-Path -LiteralPath $publishDirectory) {
        Remove-Item -LiteralPath $publishDirectory -Recurse -Force
    }
}
