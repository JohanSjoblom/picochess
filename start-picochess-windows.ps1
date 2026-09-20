<#
.SYNOPSIS
Starts PicoChess on Windows and optionally starts its Scid games helper.

.DESCRIPTION
PicoChess itself is always started from the repository virtual environment.
When gamesdb data and a user-installed Scid vs. PC tcscid.exe are available,
this launcher starts get_games.tcl on port 7778 before starting PicoChess. The
helper process is stopped when PicoChess exits.

Failure to find or start tcscid.exe is non-fatal. Normal PicoChess play and the
other web tabs remain available; only the Games tab lacks its database results.

.PARAMETER TcscidPath
Explicit path to a user-installed tcscid.exe. When omitted, the launcher checks
PICOCHESS_TCSCID, PATH, and common Scid vs. PC installation directories.

.PARAMETER GamesPort
TCP port used by get_games.tcl. The PicoChess web client currently expects 7778.

.PARAMETER SkipGamesServer
Start PicoChess without looking for or launching tcscid.exe.

.PARAMETER PicoChessArguments
Optional arguments passed to picochess.py. For example:
-PicoChessArguments @("--board-type", "noeboard", "--web-server", "8080")
#>

[CmdletBinding()]
param(
    [string]$TcscidPath,

    [ValidateRange(1, 65535)]
    [int]$GamesPort = 7778,

    [switch]$SkipGamesServer,

    [string[]]$PicoChessArguments = @()
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

function Write-Status {
    param([string]$Message)
    Write-Host "    $Message"
}

function Test-TcpPort {
    param(
        [string]$HostName,
        [int]$Port,
        [int]$TimeoutMilliseconds = 250
    )

    $client = New-Object System.Net.Sockets.TcpClient
    $connectResult = $null
    try {
        $connectResult = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $connectResult.AsyncWaitHandle.WaitOne($TimeoutMilliseconds)) {
            return $false
        }
        $client.EndConnect($connectResult)
        return $true
    } catch {
        return $false
    } finally {
        if ($connectResult) {
            $connectResult.AsyncWaitHandle.Close()
        }
        $client.Close()
    }
}

function Get-TcscidExecutable {
    param([string]$RequestedPath)

    if ($RequestedPath) {
        if (Test-Path -LiteralPath $RequestedPath -PathType Leaf) {
            return (Resolve-Path -LiteralPath $RequestedPath).Path
        }
        Write-Warning "The supplied tcscid path does not exist: $RequestedPath"
    }

    if ($env:PICOCHESS_TCSCID) {
        if (Test-Path -LiteralPath $env:PICOCHESS_TCSCID -PathType Leaf) {
            return (Resolve-Path -LiteralPath $env:PICOCHESS_TCSCID).Path
        }
        Write-Warning "PICOCHESS_TCSCID points to a missing file: $env:PICOCHESS_TCSCID"
    }

    $pathCommand = Get-Command "tcscid.exe" -ErrorAction SilentlyContinue
    if ($pathCommand) {
        return $pathCommand.Source
    }

    $searchRoots = @()
    if ($env:ProgramFiles) {
        $searchRoots += $env:ProgramFiles
    }
    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    if ($programFilesX86) {
        $searchRoots += $programFilesX86
    }
    if ($env:LOCALAPPDATA) {
        $searchRoots += (Join-Path $env:LOCALAPPDATA "Programs")
    }
    if ($env:SystemDrive) {
        $searchRoots += "$($env:SystemDrive)\"
    }

    foreach ($root in $searchRoots | Select-Object -Unique) {
        if (-not (Test-Path -LiteralPath $root -PathType Container)) {
            continue
        }
        $installDirectories = @(Get-ChildItem -Path (Join-Path $root "Scid vs PC*") -Directory -ErrorAction SilentlyContinue)
        foreach ($installDirectory in $installDirectories) {
            foreach ($relativePath in @("bin\tcscid.exe", "tcscid.exe")) {
                $candidate = Join-Path $installDirectory.FullName $relativePath
                if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                    return (Resolve-Path -LiteralPath $candidate).Path
                }
            }
        }
    }

    return $null
}

function Start-GamesHelper {
    param(
        [string]$RepositoryPath,
        [string]$Executable,
        [int]$Port
    )

    $gamesDirectory = Join-Path $RepositoryPath "gamesdb"
    $serverScript = Join-Path $gamesDirectory "get_games.tcl"
    $databaseIndex = Join-Path $gamesDirectory "games.si4"
    if (-not (Test-Path -LiteralPath $serverScript -PathType Leaf)) {
        Write-Warning "Games data is missing get_games.tcl. Run install-picochess-windows.ps1 to install the Games resource."
        return $null
    }
    if (-not (Test-Path -LiteralPath $databaseIndex -PathType Leaf)) {
        Write-Warning "Games data is missing games.si4. The Games resource may be incomplete."
        return $null
    }

    $logsDirectory = Join-Path $RepositoryPath "logs"
    if (-not (Test-Path -LiteralPath $logsDirectory)) {
        New-Item -ItemType Directory -Path $logsDirectory -Force | Out-Null
    }
    $stdoutLog = Join-Path $logsDirectory "gamesdb-windows.log"
    $stderrLog = Join-Path $logsDirectory "gamesdb-windows-error.log"

    Write-Host "Starting the optional Scid games helper..." -ForegroundColor Cyan
    try {
        $process = Start-Process `
            -FilePath $Executable `
            -ArgumentList @("get_games.tcl", "--server", [string]$Port) `
            -WorkingDirectory $gamesDirectory `
            -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutLog `
            -RedirectStandardError $stderrLog `
            -PassThru
    } catch {
        Write-Warning "Could not start tcscid.exe: $($_.Exception.Message)"
        Write-Status "PicoChess will continue without Games-tab database results."
        return $null
    }

    $deadline = [DateTime]::UtcNow.AddSeconds(8)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($process.HasExited) {
            Write-Warning "tcscid.exe exited during startup with code $($process.ExitCode)."
            Write-Status "See $stderrLog"
            return $null
        }
        if (Test-TcpPort -HostName "127.0.0.1" -Port $Port) {
            Write-Status "Games helper is listening on port $Port."
            return $process
        }
        Start-Sleep -Milliseconds 200
    }

    Write-Warning "tcscid.exe did not open port $Port within 8 seconds."
    Write-Status "See $stdoutLog and $stderrLog"
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        $process.WaitForExit(3000) | Out-Null
    }
    return $null
}

$repositoryPath = $PSScriptRoot
$venvPython = Join-Path $repositoryPath "venv\Scripts\python.exe"
$picoChessScript = Join-Path $repositoryPath "picochess.py"
$gamesProcess = $null
$picoChessExitCode = 1

try {
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw "PicoChess virtual environment not found. Run install-picochess-windows.ps1 first."
    }
    if (-not (Test-Path -LiteralPath $picoChessScript -PathType Leaf)) {
        throw "picochess.py was not found beside this launcher."
    }

    if (-not $SkipGamesServer) {
        if (Test-TcpPort -HostName "127.0.0.1" -Port $GamesPort) {
            Write-Status "Port $GamesPort is already accepting connections; assuming a games helper is running."
        } else {
            $tcscidExecutable = Get-TcscidExecutable -RequestedPath $TcscidPath
            if ($tcscidExecutable) {
                Write-Status "Using tcscid: $tcscidExecutable"
                $gamesProcess = Start-GamesHelper -RepositoryPath $repositoryPath -Executable $tcscidExecutable -Port $GamesPort
            } else {
                Write-Warning "tcscid.exe was not found. Install Scid vs. PC or supply -TcscidPath."
                Write-Status "PicoChess will continue normally; only Games-tab database results are unavailable."
            }
        }
    } else {
        Write-Status "Games helper skipped by request."
    }

    Write-Host "Starting PicoChess..." -ForegroundColor Green
    & $venvPython $picoChessScript @PicoChessArguments
    $picoChessExitCode = $LASTEXITCODE
} catch {
    Write-Host "PicoChess startup failed: $($_.Exception.Message)" -ForegroundColor Red
    $picoChessExitCode = 1
} finally {
    if ($gamesProcess -and -not $gamesProcess.HasExited) {
        Write-Status "Stopping the Scid games helper started by this launcher."
        Stop-Process -Id $gamesProcess.Id -Force -ErrorAction SilentlyContinue
        $gamesProcess.WaitForExit(3000) | Out-Null
    }
}

exit $picoChessExitCode

