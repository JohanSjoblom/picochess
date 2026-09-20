<#
.SYNOPSIS
Installs the Windows PicoChess Python environment and portable data resources.

.DESCRIPTION
The installer can use the checkout containing this script or clone PicoChess
into a user-selected directory. It creates a Python 3.13 virtual environment,
installs requirements.txt, initializes writable runtime files, and optionally
downloads books, opening data, and games database data.

It deliberately does not install chess engines, Windows services, scheduled
tasks, drivers, firewall rules, or Linux host integrations.

.PARAMETER InstallDir
PicoChess checkout to use or create. When omitted, the checkout containing
this script is used if possible; otherwise %USERPROFILE%\PicoChess is used.

.PARAMETER Resources
Portable resource packs to install. The default is Books, OpeningData, Games.

.PARAMETER SkipResources
Do not download any resource packs.

.PARAMETER UpdateRepo
Update an existing, clean branch using "git pull --ff-only". Repository
updates are opt-in and local changes are never reset.

.PARAMETER ForceResources
Replace incomplete or existing resource directories. Existing data is moved
to a timestamped backup under %LOCALAPPDATA%\PicoChess\backups first.

.PARAMETER RecreateVenv
Move the existing venv to a timestamped backup and create a new one.

.PARAMETER SkipSmokeTests
Skip import and command-line smoke tests after dependency installation.

.PARAMETER ValidateOnly
Only inspect prerequisites and the selected existing checkout. Make no changes.
#>

[CmdletBinding()]
param(
    [string]$InstallDir,

    [string[]]$Resources = @("Books", "OpeningData", "Games"),

    [switch]$SkipResources,
    [switch]$UpdateRepo,
    [switch]$ForceResources,
    [switch]$RecreateVenv,
    [switch]$SkipSmokeTests,
    [switch]$ValidateOnly
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$repositoryUrl = "https://github.com/JohanSjoblom/picochess.git"
$selectedResources = @()
$resourceDefinitions = @{
    Books = @{
        Url = "https://github.com/JohanSjoblom/picochess/releases/download/v4.2.0/books.tar.gz"
        Archive = "books.tar.gz"
        Destination = "books"
        Marker = "books.ini"
    }
    OpeningData = @{
        Url = "https://github.com/JohanSjoblom/picochess/releases/download/v4.2.0/openingdata.tar.gz"
        Archive = "openingdata.tar.gz"
        Destination = "obooksrv"
        Marker = "opening.data"
    }
    Games = @{
        Url = "https://github.com/JohanSjoblom/picochess/releases/download/v4.2.0/gamesdb.tar.gz"
        Archive = "gamesdb.tar.gz"
        Destination = "gamesdb"
        Marker = "get_games.tcl"
    }
}

function Write-Step {
    param([string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Write-Status {
    param([string]$Message)
    Write-Host "    $Message"
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList
    )

    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @ArgumentList
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorPreference
    }
    if ($exitCode -ne 0) {
        throw "Command failed with exit code ${exitCode}: $FilePath $($ArgumentList -join ' ')"
    }
}

function Invoke-NativeCapture {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList
    )

    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = @(& $FilePath @ArgumentList 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorPreference
    }
    if ($exitCode -ne 0) {
        throw "Command failed with exit code ${exitCode}: $FilePath $($ArgumentList -join ' ')`n$($output -join [Environment]::NewLine)"
    }
    return $output
}

function Test-PicoChessCheckout {
    param([string]$Path)
    return (Test-Path -LiteralPath (Join-Path $Path ".git")) -and
        (Test-Path -LiteralPath (Join-Path $Path "picochess.py")) -and
        (Test-Path -LiteralPath (Join-Path $Path "requirements.txt"))
}

function Get-InstallPath {
    param([string]$RequestedPath)

    if ($RequestedPath) {
        return [IO.Path]::GetFullPath($RequestedPath)
    }

    $scriptRoot = Split-Path -Parent $MyInvocation.ScriptName
    if ($scriptRoot -and (Test-PicoChessCheckout -Path $scriptRoot)) {
        return [IO.Path]::GetFullPath($scriptRoot)
    }

    if (-not $env:USERPROFILE) {
        throw "USERPROFILE is not available. Supply -InstallDir explicitly."
    }
    return [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE "PicoChess"))
}

function Get-GitCommand {
    $command = Get-Command "git.exe" -ErrorAction SilentlyContinue
    if (-not $command) {
        $command = Get-Command "git" -ErrorAction SilentlyContinue
    }
    if ($command) {
        return $command.Source
    }
    return $null
}

function Get-SupportedPython {
    param([string]$ExistingVenvPython)

    $candidates = @()
    if ($ExistingVenvPython -and (Test-Path -LiteralPath $ExistingVenvPython)) {
        $candidates += ,@{ File = $ExistingVenvPython; Prefix = @() }
    }
    $launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($launcher) {
        $candidates += ,@{ File = $launcher.Source; Prefix = @("-3.13") }
    }
    $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if (-not $python) {
        $python = Get-Command "python" -ErrorAction SilentlyContinue
    }
    if ($python) {
        $candidates += ,@{ File = $python.Source; Prefix = @() }
    }

    # Use Python single-quoted literals because Windows PowerShell's legacy
    # native argument binder removes embedded double quotes from -c strings.
    $probe = "import platform, struct, sys; print('{}.{}|{}|{}'.format(sys.version_info.major, sys.version_info.minor, struct.calcsize('P') * 8, platform.machine()))"
    foreach ($candidate in $candidates) {
        $arguments = @($candidate.Prefix) + @("-c", $probe)
        $previousErrorPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $result = @(& $candidate.File @arguments 2>$null)
            $exitCode = $LASTEXITCODE
        } catch {
            $result = @()
            $exitCode = 1
        } finally {
            $ErrorActionPreference = $previousErrorPreference
        }
        if ($exitCode -eq 0 -and $result.Count -gt 0) {
            $details = [string]$result[-1]
            if ($details -match '^3\.13\|64\|') {
                return @{
                    File = [string]$candidate.File
                    Prefix = @($candidate.Prefix)
                    Details = $details
                }
            }
        }
    }

    throw "64-bit CPython 3.13 was not found. Install it from python.org, enable the Python launcher or PATH option, and rerun this installer."
}

function Ensure-Repository {
    param(
        [string]$TargetPath,
        [string]$GitCommand,
        [switch]$AllowUpdate,
        [switch]$ReadOnly
    )

    if (Test-PicoChessCheckout -Path $TargetPath) {
        Write-Status "Using existing checkout: $TargetPath"
    } elseif (Test-Path -LiteralPath $TargetPath) {
        $entries = @(Get-ChildItem -Force -LiteralPath $TargetPath)
        if ($ReadOnly) {
            throw "ValidateOnly requires an existing PicoChess checkout: $TargetPath"
        }
        if ($entries.Count -ne 0) {
            throw "Install directory exists but is not an empty directory or PicoChess checkout: $TargetPath"
        }
        if (-not $GitCommand) {
            throw "Git is required to clone PicoChess. Install Git for Windows and rerun the installer."
        }
        Write-Step "Cloning PicoChess"
        Invoke-Native -FilePath $GitCommand -ArgumentList @("clone", $repositoryUrl, $TargetPath)
    } else {
        if ($ReadOnly) {
            throw "ValidateOnly requires an existing PicoChess checkout: $TargetPath"
        }
        if (-not $GitCommand) {
            throw "Git is required to clone PicoChess. Install Git for Windows and rerun the installer."
        }
        $parent = Split-Path -Parent $TargetPath
        if (-not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        Write-Step "Cloning PicoChess"
        Invoke-Native -FilePath $GitCommand -ArgumentList @("clone", $repositoryUrl, $TargetPath)
    }

    if (-not (Test-PicoChessCheckout -Path $TargetPath)) {
        throw "The selected directory is not a complete PicoChess Git checkout: $TargetPath"
    }

    if ($GitCommand) {
        $origin = @(Invoke-NativeCapture -FilePath $GitCommand -ArgumentList @("-C", $TargetPath, "remote", "get-url", "origin")) -join ""
        Write-Status "Git origin: $origin"
        if ($origin -notmatch '(?i)(^|[/:])JohanSjoblom/picochess(?:\.git)?$') {
            Write-Warning "This checkout uses a non-standard origin. It will be preserved: $origin"
        }
    }

    if ($AllowUpdate) {
        if ($ReadOnly) {
            throw "-UpdateRepo cannot be combined with -ValidateOnly."
        }
        if (-not $GitCommand) {
            throw "Git is required for -UpdateRepo."
        }
        $changes = @(Invoke-NativeCapture -FilePath $GitCommand -ArgumentList @("-C", $TargetPath, "status", "--porcelain"))
        if ($changes.Count -ne 0) {
            throw "The checkout has local changes. Commit or stash them before using -UpdateRepo. No files were changed."
        }
        $branch = @(Invoke-NativeCapture -FilePath $GitCommand -ArgumentList @("-C", $TargetPath, "symbolic-ref", "--quiet", "--short", "HEAD")) -join ""
        if (-not $branch) {
            throw "The checkout is detached. Select a branch before using -UpdateRepo."
        }
        Write-Step "Updating branch $branch with a fast-forward-only pull"
        Invoke-Native -FilePath $GitCommand -ArgumentList @("-C", $TargetPath, "pull", "--ff-only")
    }
}

function Assert-SafeArchiveEntries {
    param(
        [string]$TarCommand,
        [string]$ArchivePath
    )

    $entries = @(Invoke-NativeCapture -FilePath $TarCommand -ArgumentList @("-tzf", $ArchivePath))
    if ($entries.Count -eq 0) {
        throw "Downloaded archive is empty: $ArchivePath"
    }
    foreach ($entryValue in $entries) {
        $entry = ([string]$entryValue).Replace('\', '/')
        if ($entry -match '^[\/]' -or $entry -match '^[A-Za-z]:' -or $entry -match '(^|/)\.\.(/|$)') {
            throw "Archive contains an unsafe path: $entry"
        }
    }
}

function Move-ResourceToBackup {
    param(
        [string]$ExistingPath,
        [string]$ResourceName
    )

    if (-not $env:LOCALAPPDATA) {
        throw "LOCALAPPDATA is not available; cannot safely back up existing resource data."
    }
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupRoot = Join-Path $env:LOCALAPPDATA "PicoChess\backups\$timestamp"
    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    $backupPath = Join-Path $backupRoot $ResourceName
    Move-Item -LiteralPath $ExistingPath -Destination $backupPath
    Write-Status "Existing resource moved to: $backupPath"
}

function Install-ResourcePack {
    param(
        [string]$Name,
        [hashtable]$Definition,
        [string]$RepositoryPath,
        [string]$TarCommand,
        [string]$TemporaryRoot,
        [switch]$ReplaceExisting
    )

    $destination = Join-Path $RepositoryPath $Definition.Destination
    $marker = Join-Path $destination $Definition.Marker
    if ((Test-Path -LiteralPath $marker) -and -not $ReplaceExisting) {
        Write-Status "$Name already installed; keeping $destination"
        return
    }
    if ((Test-Path -LiteralPath $destination) -and -not $ReplaceExisting) {
        throw "$Name destination exists but its expected marker '$($Definition.Marker)' is missing. Inspect it or rerun with -ForceResources."
    }

    $resourceRoot = Join-Path $TemporaryRoot $Name
    $extractRoot = Join-Path $resourceRoot "extract"
    $archivePath = Join-Path $resourceRoot $Definition.Archive
    New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null

    Write-Step "Downloading $Name"
    Invoke-WebRequest -Uri $Definition.Url -OutFile $archivePath -UseBasicParsing
    Assert-SafeArchiveEntries -TarCommand $TarCommand -ArchivePath $archivePath
    Invoke-Native -FilePath $TarCommand -ArgumentList @("-xzf", $archivePath, "-C", $extractRoot)

    $stagedMarker = Join-Path $extractRoot $Definition.Marker
    if (-not (Test-Path -LiteralPath $stagedMarker)) {
        throw "$Name archive did not contain the expected '$($Definition.Marker)' file. Nothing was installed."
    }

    if (Test-Path -LiteralPath $destination) {
        Move-ResourceToBackup -ExistingPath $destination -ResourceName $Definition.Destination
    }
    Move-Item -LiteralPath $extractRoot -Destination $destination
    Write-Status "$Name installed in $destination"
}

function Initialize-RuntimeFiles {
    param([string]$RepositoryPath)

    foreach ($relativePath in @("logs", "games\uploads")) {
        $path = Join-Path $RepositoryPath $relativePath
        if (-not (Test-Path -LiteralPath $path)) {
            New-Item -ItemType Directory -Path $path -Force | Out-Null
            Write-Status "Created $path"
        }
    }

    $voicesFile = Join-Path $RepositoryPath "talker\voices\voices.ini"
    $voicesExample = Join-Path $RepositoryPath "voices-example.ini"
    if (-not (Test-Path -LiteralPath $voicesFile)) {
        if (-not (Test-Path -LiteralPath $voicesExample)) {
            throw "Voice configuration template is missing: $voicesExample"
        }
        Copy-Item -LiteralPath $voicesExample -Destination $voicesFile
        Write-Status "Created $voicesFile"
    }
}

function Show-Readiness {
    param(
        [string]$RepositoryPath,
        [string]$VenvPython
    )

    Write-Step "Windows readiness summary"
    Write-Status "Repository: $RepositoryPath"
    if (Test-Path -LiteralPath $VenvPython) {
        Write-Status "Virtual environment: $VenvPython"
    } else {
        Write-Status "Virtual environment: not created"
    }

    $catalog = Join-Path $RepositoryPath "engines\AMD64\engines.ini"
    $engineDirectory = Join-Path $RepositoryPath "engines\AMD64"
    $executables = @()
    if (Test-Path -LiteralPath $engineDirectory) {
        $executables = @(Get-ChildItem -File -LiteralPath $engineDirectory -Filter "*.exe" -ErrorAction SilentlyContinue)
    }
    if ((Test-Path -LiteralPath $catalog) -and $executables.Count -gt 0) {
        Write-Status "Engine catalog: found ($($executables.Count) Windows executable(s))"
    } else {
        Write-Warning "No complete Windows engine catalog was found. This is expected when installing before adding an engine."
        Write-Status "Follow engines\README.md and place native engines under engines\AMD64."
    }

    $configuration = Join-Path $RepositoryPath "picochess.ini"
    if (Test-Path -LiteralPath $configuration) {
        Write-Status "Configuration: preserving existing picochess.ini"
    } else {
        Write-Warning "picochess.ini was not created because no engine path should be guessed. Configure it after adding a Windows engine."
    }

    if ($selectedResources -contains "Games" -and -not $SkipResources) {
        Write-Warning "Games database data may be installed, but the Windows tcscid server on port 7778 is not installed or started by this MVP."
    }
}

try {
    Write-Host "PicoChess Windows installer" -ForegroundColor Green
    if ($env:OS -ne "Windows_NT") {
        throw "This installer supports Windows only."
    }
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw "The Windows port requires a 64-bit operating system."
    }

    foreach ($resourceArgument in $Resources) {
        foreach ($resourceName in $resourceArgument.Split(',')) {
            $normalizedResource = $resourceName.Trim()
            if (-not $normalizedResource) {
                continue
            }
            if (-not $resourceDefinitions.ContainsKey($normalizedResource)) {
                throw "Unknown resource '$normalizedResource'. Choose Books, OpeningData, or Games."
            }
            if ($selectedResources -notcontains $normalizedResource) {
                $selectedResources += $normalizedResource
            }
        }
    }

    $targetPath = Get-InstallPath -RequestedPath $InstallDir
    $gitCommand = Get-GitCommand

    Write-Step "Checking repository"
    Write-Status "Install directory: $targetPath"
    if ($gitCommand) {
        Write-Status "Git: $gitCommand"
    } else {
        Write-Warning "Git was not found. It is only mandatory when cloning or using -UpdateRepo."
    }

    Ensure-Repository -TargetPath $targetPath -GitCommand $gitCommand -AllowUpdate:$UpdateRepo -ReadOnly:$ValidateOnly

    $venvPath = Join-Path $targetPath "venv"
    $venvPython = Join-Path $venvPath "Scripts\python.exe"
    $pythonCandidate = $null
    if (-not $RecreateVenv) {
        $pythonCandidate = $venvPython
    }
    $systemPython = Get-SupportedPython -ExistingVenvPython $pythonCandidate
    Write-Step "Checking Python"
    Write-Status "Python: $($systemPython.File) ($($systemPython.Details))"

    if ($ValidateOnly) {
        Show-Readiness -RepositoryPath $targetPath -VenvPython $venvPython
        Write-Host "`nValidation completed; no changes were made." -ForegroundColor Green
        exit 0
    }

    Write-Step "Preparing runtime directories"
    Initialize-RuntimeFiles -RepositoryPath $targetPath

    if ($RecreateVenv -and (Test-Path -LiteralPath $venvPath)) {
        $venvBackup = "$venvPath.backup.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Move-Item -LiteralPath $venvPath -Destination $venvBackup
        Write-Status "Existing venv moved to: $venvBackup"
    }
    if ((Test-Path -LiteralPath $venvPath) -and -not (Test-Path -LiteralPath $venvPython)) {
        throw "The existing venv is incomplete. Inspect it or rerun with -RecreateVenv."
    }
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Step "Creating Python virtual environment"
        $venvArguments = @($systemPython.Prefix) + @("-m", "venv", $venvPath)
        Invoke-Native -FilePath $systemPython.File -ArgumentList $venvArguments
    } else {
        Write-Status "Reusing virtual environment: $venvPath"
    }

    Write-Step "Installing Python dependencies"
    Invoke-Native -FilePath $venvPython -ArgumentList @("-m", "ensurepip", "--upgrade")
    Invoke-Native -FilePath $venvPython -ArgumentList @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Native -FilePath $venvPython -ArgumentList @("-m", "pip", "install", "--upgrade", "-r", (Join-Path $targetPath "requirements.txt"))

    if (-not $SkipResources) {
        $tar = Get-Command "tar.exe" -ErrorAction SilentlyContinue
        if (-not $tar) {
            throw "Windows tar.exe is required to extract resource packs."
        }
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        $temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ("picochess-windows-install-" + [Guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
        try {
            foreach ($resourceName in $selectedResources) {
                Install-ResourcePack -Name $resourceName -Definition $resourceDefinitions[$resourceName] -RepositoryPath $targetPath -TarCommand $tar.Source -TemporaryRoot $temporaryRoot -ReplaceExisting:$ForceResources
            }
        } finally {
            if ((Test-Path -LiteralPath $temporaryRoot) -and ([IO.Path]::GetFileName($temporaryRoot) -like "picochess-windows-install-*")) {
                Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
            }
        }
    } else {
        Write-Status "Resource downloads skipped."
    }

    if (-not $SkipSmokeTests) {
        Write-Step "Running Windows smoke tests"
        Push-Location $targetPath
        try {
            Invoke-Native -FilePath $venvPython -ArgumentList @("-m", "pip", "check")
            Invoke-Native -FilePath $venvPython -ArgumentList @("-c", "from dgt.board import DgtBoard; print('dgt.board import OK')")
            Invoke-Native -FilePath $venvPython -ArgumentList @("-c", "import server; print('server import OK')")
            Invoke-Native -FilePath $venvPython -ArgumentList @("picochess.py", "--help")
        } finally {
            Pop-Location
        }
    }

    Show-Readiness -RepositoryPath $targetPath -VenvPython $venvPython
    Write-Host "`nPicoChess Windows environment installation completed." -ForegroundColor Green
    Write-Host "After adding and configuring a native Windows UCI engine, start with:"
    Write-Host "  & `"$venvPython`" `"$(Join-Path $targetPath 'picochess.py')`""
} catch {
    Write-Host "`nInstallation failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
