<#
.SYNOPSIS
Prepares the experimental PicoChess MCP server on Windows.

.DESCRIPTION
Creates or reuses mcp\.venv with a 64-bit CPython 3.10 or newer, installs
mcp\requirements.txt into it, and checks that the server's imports work.
PicoChess's own venv and the system Python are not changed.

With -Register it also registers the server with Claude Code as "picochess",
scoped to this PicoChess checkout. An existing registration is left unchanged.

.PARAMETER Register
Register the server with Claude Code after installing. Requires the claude CLI.

.PARAMETER PicoChessUrl
PicoChess web address passed to the server as PICOCHESS_URL when registering.
Defaults to the server's own default, http://localhost:8080.

.PARAMETER RecreateVenv
Delete mcp\.venv and create it again.
#>

[CmdletBinding()]
param(
    [switch]$Register,
    [string]$PicoChessUrl,
    [switch]$RecreateVenv
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$mcpDirectory = $PSScriptRoot
$repositoryPath = Split-Path $mcpDirectory -Parent
$venvPath = Join-Path $mcpDirectory ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$requirements = Join-Path $mcpDirectory "requirements.txt"
$serverScript = Join-Path $mcpDirectory "server.py"

function Write-Step {
    param([string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Test-SupportedPython {
    param([string]$File, [string[]]$Prefix = @())

    $probe = "import struct,sys;raise SystemExit(0 if sys.version_info[:2]>=(3,10) and struct.calcsize('P')==8 else 1)"
    try {
        & $File @Prefix -c $probe 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Get-BasePython {
    # PicoChess runs on 3.13, so prefer it; the MCP SDK needs 3.10 or newer.
    $launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($version in @("3.13", "3.12", "3.11", "3.10")) {
            if (Test-SupportedPython -File $launcher.Source -Prefix @("-$version")) {
                return @{ File = $launcher.Source; Prefix = @("-$version") }
            }
        }
    }
    $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($python -and (Test-SupportedPython -File $python.Source)) {
        return @{ File = $python.Source; Prefix = @() }
    }
    throw "No 64-bit CPython 3.10 or newer was found. Install CPython 3.13 (the version PicoChess uses) and run this script again."
}

try {
    Write-Host "PicoChess MCP setup" -ForegroundColor Green

    if ($RecreateVenv -and (Test-Path -LiteralPath $venvPath)) {
        Write-Step "Removing the existing MCP virtual environment"
        Remove-Item -LiteralPath $venvPath -Recurse -Force
    }

    if ((Test-Path -LiteralPath $venvPython) -and (Test-SupportedPython -File $venvPython)) {
        Write-Step "Reusing $venvPath"
    } else {
        if (Test-Path -LiteralPath $venvPath) {
            throw "$venvPath exists but is incomplete or unsupported. Run again with -RecreateVenv."
        }
        $basePython = Get-BasePython
        Write-Step "Creating $venvPath"
        & $basePython.File @($basePython.Prefix) -m venv $venvPath
        if ($LASTEXITCODE -ne 0) { throw "Creating the virtual environment failed." }
    }

    Write-Step "Installing $requirements"
    & $venvPython -m pip install --disable-pip-version-check --upgrade -r $requirements
    if ($LASTEXITCODE -ne 0) { throw "Installing the MCP requirements failed." }

    Write-Step "Checking the server's imports"
    & $venvPython -c "import chess; from mcp.server.mcpserver import MCPServer; print('    imports OK')"
    if ($LASTEXITCODE -ne 0) { throw "The MCP server's imports failed. Run again with -RecreateVenv." }

    $registerCommand = "claude mcp add picochess -- `"$venvPython`" `"$serverScript`""
    if ($Register) {
        Write-Step "Registering with Claude Code"
        if (-not (Get-Command "claude" -ErrorAction SilentlyContinue)) {
            throw "The claude CLI was not found. Install Claude Code, then run: $registerCommand"
        }
        # Local scope belongs to the folder claude runs in; use this checkout.
        Push-Location $repositoryPath
        try {
            & claude mcp get picochess *> $null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "    'picochess' is already registered; left unchanged."
                Write-Host "    To change it, first run: claude mcp remove picochess -s local"
            } else {
                $arguments = @("mcp", "add", "picochess")
                if ($PicoChessUrl) {
                    $arguments += @("-e", "PICOCHESS_URL=$PicoChessUrl")
                }
                $arguments += @("--", $venvPython, $serverScript)
                & claude @arguments
                if ($LASTEXITCODE -ne 0) { throw "claude mcp add failed." }
            }
        } finally {
            Pop-Location
        }
    }

    Write-Host "`nPicoChess MCP setup completed." -ForegroundColor Green
    if (-not $Register) {
        Write-Host "Register it with Claude Code from $repositoryPath with:"
        Write-Host "  $registerCommand"
    }
    Write-Host "Start PicoChess before using the tools, and start a new Claude Code session after registering."
} catch {
    Write-Host "`nPicoChess MCP setup failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
