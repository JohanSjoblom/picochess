<#
.SYNOPSIS
Installs the Windows PicoChess Python environment and portable data resources.

.DESCRIPTION
The installer can use the checkout containing this script or clone PicoChess
into a user-selected directory. It creates a Python 3.11-3.13 AMD64 virtual environment,
installs requirements.txt, initializes writable runtime files, and optionally
downloads official Stockfish and Lc0 with PicoChess engine metadata, the
shared Lc0 weights, books, opening data, and games database data.

It deliberately does not install Windows services, scheduled tasks, drivers,
firewall rules, or Linux host integrations.

.PARAMETER InstallDir
PicoChess checkout to use or create. When omitted, the checkout containing
this script is used if possible; otherwise %USERPROFILE%\PicoChess is used.

.PARAMETER Resources
Portable resource packs to install. The default is Engines, Lc0, Books,
OpeningData, Games. Lc0 also downloads the shared Lc0 weights (about 620 MB)
when engines\lc0_weights is missing. A failed Lc0 installation is reported as
a warning and leaves Stockfish usable.

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

    [string[]]$Resources = @("Engines", "Lc0", "Books", "OpeningData", "Games"),

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
$repositoryBranch = "master"
$selectedResources = @()
$resourceDefinitions = @{
    # Official Stockfish is downloaded unmodified and keeps its upstream file
    # name. PicoChess supplies only its catalog and level metadata.
    Engines = @{
        ArchiveType = "StarterEngine"
        Destination = "engines\AMD64"
        Marker = "stockfish-windows-x86-64-universal.exe"
        Engine = @{
            Url = "https://github.com/official-stockfish/Stockfish/releases/download/sf_19/stockfish-windows-x86-64-universal.zip"
            Archive = "stockfish-windows-x86-64-universal.zip"
            Sha256 = "3C8BF1F9EA66A09350A40DF4F632288285AC206D99F33AB5842C408FC30B48A7"
            ArchivePath = "stockfish/stockfish-windows-x86-64-universal.exe"
            LicensePath = "stockfish/Copying.txt"
        }
        Metadata = @{
            Url = "https://github.com/JohanSjoblom/picochess/releases/download/v4.4.1/picochess-amd64-engines-metadata-v4.4.1.zip"
            Archive = "picochess-amd64-engines-metadata-v4.4.1.zip"
            Sha256 = "55AF2842A4E19DDC998AF61657AAFD81A3F35EE32893B774A02AFDEA99686A2F"
        }
    }
    # Official Lc0 CPU (OpenBLAS) build. The extra catalog entries are copies of
    # lc0.exe, because Windows symlinks need administrator rights.
    Lc0 = @{
        ArchiveType = "Lc0Engine"
        Destination = "engines\AMD64"
        Marker = "lc0.exe"
        Profiles = @("classic.exe", "elitev2.exe", "maiav0321.exe", "maia3.exe")
        Engine = @{
            Url = "https://github.com/LeelaChessZero/lc0/releases/download/v0.32.1/lc0-v0.32.1-windows-cpu-openblas.zip"
            Archive = "lc0-v0.32.1-windows-cpu-openblas.zip"
            Sha256 = "B2CAA8443F0E0CB15CF76C335C53985F2973CD6438E77D3E2366CD21D2EFFA38"
            Files = @("lc0.exe", "libopenblas.dll", "mimalloc-override.dll", "mimalloc-redirect.dll")
        }
        Metadata = @{
            Url = "https://github.com/JohanSjoblom/picochess/releases/download/v4.4.1/picochess-amd64-lc0-metadata-v4.4.1.zip"
            Archive = "picochess-amd64-lc0-metadata-v4.4.1.zip"
            Sha256 = "D40FC71B549730605B74EA86877AE9B63DE4B7E90C173F13585736B456909459"
        }
        Weights = @{
            Url = "https://github.com/JohanSjoblom/picochess/releases/download/v4.4.1/lc0_weights.tar.gz"
            Archive = "lc0_weights.tar.gz"
            Sha256 = "6B4D6B0C23FDD8F3E955A639B597AAEFA403452B692CE012C03145B35F84E66F"
            Destination = "engines\lc0_weights"
            Marker = "792013-192x15.txt"
        }
    }
    Books = @{
        Url = "https://github.com/JohanSjoblom/picochess/releases/download/v4.2.0/books.tar.gz"
        Archive = "books.tar.gz"
        ArchiveType = "TarGz"
        Destination = "books"
        Marker = "books.ini"
    }
    OpeningData = @{
        Url = "https://github.com/JohanSjoblom/picochess/releases/download/v4.2.0/openingdata.tar.gz"
        Archive = "openingdata.tar.gz"
        ArchiveType = "TarGz"
        Destination = "obooksrv"
        Marker = "opening.data"
    }
    Games = @{
        Url = "https://github.com/JohanSjoblom/picochess/releases/download/v4.2.0/gamesdb.tar.gz"
        Archive = "gamesdb.tar.gz"
        ArchiveType = "TarGz"
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
        $candidates += ,@{ File = $ExistingVenvPython; Prefix = @(); ExistingVenv = $true }
    }
    $launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($version in @("3.13", "3.12", "3.11")) {
            $candidates += ,@{ File = $launcher.Source; Prefix = @("-$version"); ExistingVenv = $false }
        }
    }
    $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if (-not $python) {
        $python = Get-Command "python" -ErrorAction SilentlyContinue
    }
    if ($python) {
        $candidates += ,@{ File = $python.Source; Prefix = @(); ExistingVenv = $false }
    }

    # Use Python single-quoted literals because Windows PowerShell's legacy
    # native argument binder removes embedded double quotes from -c strings.
    $probe = "import platform, struct, sys; print('{}.{}|{}|{}'.format(sys.version_info.major, sys.version_info.minor, struct.calcsize('P') * 8, platform.machine()))"
    $detectedPythons = @()
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
        if ($exitCode -ne 0 -and $candidate.ExistingVenv) {
            Write-Warning "The existing PicoChess virtual environment could not run its Python interpreter."
            throw "Rerun this installer with -RecreateVenv after installing CPython 3.11-3.13 x64 (AMD64)."
        }
        if ($exitCode -eq 0 -and $result.Count -gt 0) {
            $details = [string]$result[-1]
            if ($details -match '^3\.(11|12|13)\|64\|AMD64$') {
                return @{
                    File = [string]$candidate.File
                    Prefix = @($candidate.Prefix)
                    Details = $details
                }
            }
            $detectedPythons += $details
            if ($candidate.ExistingVenv) {
                Write-Warning "The existing PicoChess virtual environment uses unsupported Python '$details'. PicoChess on Windows requires CPython 3.11-3.13 x64 (AMD64), not ARM64 or 32-bit Python."
                throw "Rerun this installer with -RecreateVenv after installing a supported x64 (AMD64) Python."
            }
        }
    }

    $detectedSummary = (($detectedPythons | Select-Object -Unique) -join ", ")
    if ($detectedSummary) {
        Write-Warning "Unsupported Python detected: $detectedSummary. ARM64 and 32-bit Python builds are not supported by the current Windows dependencies."
    }
    throw "CPython 3.11-3.13 x64 (AMD64) was not found. Install the Windows '64-bit' build from python.org (not the 'ARM64' build), enable the Python launcher or PATH option, and rerun this installer."
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
        Invoke-Native -FilePath $GitCommand -ArgumentList @("clone", "--branch", $repositoryBranch, $repositoryUrl, $TargetPath)
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
        Invoke-Native -FilePath $GitCommand -ArgumentList @("clone", "--branch", $repositoryBranch, $repositoryUrl, $TargetPath)
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
        # Older installers cloned with --single-branch, which fetches only the
        # checked-out branch. Fetch all branches so the checkout can later move
        # to another branch; the current branch and its upstream are unchanged.
        $allBranches = "+refs/heads/*:refs/remotes/origin/*"
        $fetchSpecs = @(Invoke-NativeCapture -FilePath $GitCommand -ArgumentList @("-C", $TargetPath, "config", "--get-all", "remote.origin.fetch"))
        if ($fetchSpecs -notcontains $allBranches) {
            Write-Status "Configuring origin to fetch all branches."
            Invoke-Native -FilePath $GitCommand -ArgumentList @("-C", $TargetPath, "config", "--replace-all", "remote.origin.fetch", $allBranches)
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

function Assert-SafeZipArchiveEntries {
    param([string]$ArchivePath)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        if ($archive.Entries.Count -eq 0) {
            throw "Downloaded archive is empty: $ArchivePath"
        }
        foreach ($zipEntry in $archive.Entries) {
            $entry = ([string]$zipEntry.FullName).Replace('\', '/')
            if ($entry -match '^[\/]' -or $entry -match '^[A-Za-z]:' -or $entry -match '(^|/)\.\.(/|$)') {
                throw "Archive contains an unsafe path: $entry"
            }
        }
    } finally {
        $archive.Dispose()
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
    # Nested resources such as engines\AMD64 need their parent folder.
    New-Item -ItemType Directory -Path (Split-Path -Parent $backupPath) -Force | Out-Null
    Move-Item -LiteralPath $ExistingPath -Destination $backupPath
    Write-Status "Existing resource moved to: $backupPath"
}

function Save-VerifiedDownload {
    param(
        [string]$Name,
        [string]$Url,
        [string]$OutFile,
        [string]$Sha256
    )

    Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing
    if ($Sha256) {
        $actualHash = (Get-FileHash -LiteralPath $OutFile -Algorithm SHA256).Hash
        if ($actualHash -ne $Sha256) {
            throw "$Name archive checksum mismatch. Expected $Sha256, received $actualHash."
        }
    }
}

function Install-StarterEngine {
    param(
        [hashtable]$Definition,
        [string]$RepositoryPath,
        [string]$TemporaryRoot,
        [switch]$ReplaceExisting
    )

    $engineName = $Definition.Marker
    $destination = Join-Path $RepositoryPath $Definition.Destination
    if ((Test-Path -LiteralPath (Join-Path $destination $engineName)) -and -not $ReplaceExisting) {
        Write-Status "Stockfish already installed; keeping $destination"
        return
    }
    if ((Test-Path -LiteralPath $destination) -and -not $ReplaceExisting) {
        # Keep user-installed engines. -ForceResources backs them up first.
        Write-Warning "Keeping existing engine directory without $engineName`: $destination"
        Write-Status "Rerun with -ForceResources to back it up and install official Stockfish."
        return
    }

    $resourceRoot = Join-Path $TemporaryRoot "Engines"
    $engineExtract = Join-Path $resourceRoot "engine"
    $metadataExtract = Join-Path $resourceRoot "metadata"
    $stageRoot = Join-Path $resourceRoot "stage"
    New-Item -ItemType Directory -Path $engineExtract, $metadataExtract, $stageRoot -Force | Out-Null

    Write-Step "Downloading official Stockfish for Windows"
    $engineArchive = Join-Path $resourceRoot $Definition.Engine.Archive
    Save-VerifiedDownload -Name "Stockfish" -Url $Definition.Engine.Url -OutFile $engineArchive -Sha256 $Definition.Engine.Sha256
    Assert-SafeZipArchiveEntries -ArchivePath $engineArchive
    Expand-Archive -LiteralPath $engineArchive -DestinationPath $engineExtract

    $engineSource = Join-Path $engineExtract $Definition.Engine.ArchivePath
    if (-not (Test-Path -LiteralPath $engineSource -PathType Leaf)) {
        throw "Stockfish archive did not contain $($Definition.Engine.ArchivePath). Nothing was installed."
    }
    $stagedEngine = Join-Path $stageRoot $engineName
    Copy-Item -LiteralPath $engineSource -Destination $stagedEngine
    $licenseSource = Join-Path $engineExtract $Definition.Engine.LicensePath
    if (Test-Path -LiteralPath $licenseSource -PathType Leaf) {
        Copy-Item -LiteralPath $licenseSource -Destination (Join-Path $stageRoot "Copying.txt")
    }

    # The handshake also proves that this CPU can execute the downloaded binary.
    # The leading empty line absorbs the BOM Windows PowerShell 5.1 writes to stdin.
    $uciOutput = @("", "uci", "isready", "quit") | & $stagedEngine 2>&1 | ForEach-Object { ([string]$_).Trim() }
    if ($LASTEXITCODE -ne 0 -or $uciOutput -notcontains "uciok" -or $uciOutput -notcontains "readyok") {
        throw "Downloaded Stockfish did not complete the UCI handshake. Nothing was installed. Output: $($uciOutput -join ' | ')"
    }
    Write-Status "Stockfish answered uciok and readyok"

    Write-Step "Downloading PicoChess Windows engine metadata"
    $metadataArchive = Join-Path $resourceRoot $Definition.Metadata.Archive
    Save-VerifiedDownload -Name "Engine metadata" -Url $Definition.Metadata.Url -OutFile $metadataArchive -Sha256 $Definition.Metadata.Sha256
    Assert-SafeZipArchiveEntries -ArchivePath $metadataArchive
    Expand-Archive -LiteralPath $metadataArchive -DestinationPath $metadataExtract
    $catalog = Join-Path $metadataExtract "engines.ini"
    $levels = Join-Path $metadataExtract "$engineName.uci"
    if (-not (Test-Path -LiteralPath $catalog -PathType Leaf) -or -not (Test-Path -LiteralPath $levels -PathType Leaf)) {
        throw "Engine metadata archive must contain engines.ini and $engineName.uci. Nothing was installed."
    }
    if (@(Get-ChildItem -LiteralPath $metadataExtract -Recurse -File -Filter "*.exe").Count -gt 0) {
        throw "Engine metadata archive must not contain engine executables. Nothing was installed."
    }
    if (-not (Select-String -LiteralPath $catalog -SimpleMatch "[$engineName]" -Quiet)) {
        throw "Engine catalog is missing [$engineName]. Nothing was installed."
    }
    if (-not (Select-String -LiteralPath $levels -SimpleMatch "[Elo@2200]" -Quiet)) {
        throw "Engine levels are missing Elo@2200. Nothing was installed."
    }
    Copy-Item -Path (Join-Path $metadataExtract "*") -Destination $stageRoot -Recurse

    if (Test-Path -LiteralPath $destination) {
        Move-ResourceToBackup -ExistingPath $destination -ResourceName $Definition.Destination
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Move-Item -LiteralPath $stageRoot -Destination $destination
    Write-Status "Stockfish installed in $destination"
}

function Install-Lc0Weights {
    param(
        [hashtable]$Definition,
        [string]$RepositoryPath,
        [string]$TarCommand,
        [string]$TemporaryRoot
    )

    $destination = Join-Path $RepositoryPath $Definition.Destination
    if (Test-Path -LiteralPath $destination) {
        # Shared with other platforms; refreshing it means moving the whole folder away first.
        Write-Status "Reusing existing Lc0 weights in $destination"
        return
    }
    if (-not $TarCommand) {
        throw "Windows tar.exe is required to extract the Lc0 weights."
    }

    $weightsRoot = Join-Path $TemporaryRoot "Lc0Weights"
    $extractRoot = Join-Path $weightsRoot "extract"
    New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null
    $archivePath = Join-Path $weightsRoot $Definition.Archive

    Write-Step "Downloading Lc0 weights (about 620 MB)"
    Save-VerifiedDownload -Name "Lc0 weights" -Url $Definition.Url -OutFile $archivePath -Sha256 $Definition.Sha256
    Assert-SafeArchiveEntries -TarCommand $TarCommand -ArchivePath $archivePath
    Invoke-Native -FilePath $TarCommand -ArgumentList @("-xzf", $archivePath, "-C", $extractRoot)
    Remove-Item -LiteralPath $archivePath -Force
    if (-not (Test-Path -LiteralPath (Join-Path $extractRoot $Definition.Marker) -PathType Leaf)) {
        throw "Lc0 weights archive did not contain $($Definition.Marker)."
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Move-Item -LiteralPath $extractRoot -Destination $destination
    Write-Status "Lc0 weights installed in $destination"
}

function Install-Lc0 {
    param(
        [hashtable]$Definition,
        [string]$RepositoryPath,
        [string]$TarCommand,
        [string]$TemporaryRoot,
        [string]$VenvPython,
        [switch]$ReplaceExisting
    )

    $destination = Join-Path $RepositoryPath $Definition.Destination
    if ((Test-Path -LiteralPath (Join-Path $destination $Definition.Marker)) -and -not $ReplaceExisting) {
        Write-Status "Lc0 already installed; keeping $destination"
        return
    }

    Install-Lc0Weights -Definition $Definition.Weights -RepositoryPath $RepositoryPath -TarCommand $TarCommand -TemporaryRoot $TemporaryRoot
    $weightsPath = Join-Path $RepositoryPath $Definition.Weights.Destination

    $resourceRoot = Join-Path $TemporaryRoot "Lc0"
    $engineExtract = Join-Path $resourceRoot "engine"
    $metadataExtract = Join-Path $resourceRoot "metadata"
    $stageRoot = Join-Path $resourceRoot "stage"
    New-Item -ItemType Directory -Path $engineExtract, $metadataExtract, $stageRoot -Force | Out-Null

    Write-Step "Downloading official Lc0 for Windows (OpenBLAS)"
    $engineArchive = Join-Path $resourceRoot $Definition.Engine.Archive
    Save-VerifiedDownload -Name "Lc0" -Url $Definition.Engine.Url -OutFile $engineArchive -Sha256 $Definition.Engine.Sha256
    Assert-SafeZipArchiveEntries -ArchivePath $engineArchive
    Expand-Archive -LiteralPath $engineArchive -DestinationPath $engineExtract
    foreach ($fileName in $Definition.Engine.Files) {
        $source = Join-Path $engineExtract $fileName
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Lc0 archive did not contain $fileName."
        }
        Copy-Item -LiteralPath $source -Destination $stageRoot
    }
    $engineLicense = Join-Path $engineExtract "COPYING"
    if (Test-Path -LiteralPath $engineLicense -PathType Leaf) {
        Copy-Item -LiteralPath $engineLicense -Destination (Join-Path $stageRoot "lc0-COPYING.txt")
    }
    foreach ($entryName in $Definition.Profiles) {
        Copy-Item -LiteralPath (Join-Path $stageRoot $Definition.Marker) -Destination (Join-Path $stageRoot $entryName)
    }

    Write-Step "Downloading PicoChess Windows Lc0 metadata"
    $metadataArchive = Join-Path $resourceRoot $Definition.Metadata.Archive
    Save-VerifiedDownload -Name "Lc0 metadata" -Url $Definition.Metadata.Url -OutFile $metadataArchive -Sha256 $Definition.Metadata.Sha256
    Assert-SafeZipArchiveEntries -ArchivePath $metadataArchive
    Expand-Archive -LiteralPath $metadataArchive -DestinationPath $metadataExtract
    if (@(Get-ChildItem -LiteralPath $metadataExtract -Recurse -File -Filter "*.exe").Count -gt 0) {
        throw "Lc0 metadata archive must not contain engine executables."
    }
    $catalog = Join-Path $metadataExtract "engines.ini"
    if (-not (Test-Path -LiteralPath $catalog -PathType Leaf)) {
        throw "Lc0 metadata archive is missing engines.ini."
    }

    # The level files use the Linux weights path; point them at this installation.
    $utf8 = New-Object System.Text.UTF8Encoding $false
    $weightsPrefix = $weightsPath.TrimEnd('\') + '\'
    foreach ($engineName in @($Definition.Marker) + $Definition.Profiles) {
        $levelSource = Join-Path $metadataExtract "$engineName.uci"
        if (-not (Test-Path -LiteralPath $levelSource -PathType Leaf)) {
            throw "Lc0 metadata archive is missing $engineName.uci."
        }
        if (-not (Select-String -LiteralPath $catalog -SimpleMatch "[$engineName]" -Quiet)) {
            throw "Lc0 catalog is missing [$engineName]."
        }
        $levels = [IO.File]::ReadAllText($levelSource).Replace("/opt/picochess/engines/lc0_weights/", $weightsPrefix)
        if ($levels.Contains("/opt/")) {
            throw "$engineName.uci still contains a Linux path after rewriting."
        }
        foreach ($match in [regex]::Matches($levels, '(?m)^\s*WeightsFile\s*=\s*(.+?)\s*$')) {
            if (-not (Test-Path -LiteralPath $match.Groups[1].Value -PathType Leaf)) {
                throw "$engineName.uci needs a network that is missing: $($match.Groups[1].Value)"
            }
        }
        [IO.File]::WriteAllText((Join-Path $stageRoot "$engineName.uci"), $levels, $utf8)
    }

    Write-Step "Checking Lc0 with a short search for each catalog entry"
    $checkScript = Join-Path $RepositoryPath "scripts\check-lc0-engines.py"
    Invoke-Native -FilePath $VenvPython -ArgumentList @("-I", $checkScript, $stageRoot)

    $stagedFiles = @(Get-ChildItem -LiteralPath $stageRoot -File)
    $existing = @($stagedFiles | Where-Object { Test-Path -LiteralPath (Join-Path $destination $_.Name) })
    if ($existing.Count -gt 0) {
        if (-not $ReplaceExisting) {
            throw "Files with Lc0 names already exist in ${destination}: $(($existing | ForEach-Object Name) -join ', '). Rerun with -ForceResources to back them up and replace them."
        }
        if (-not $env:LOCALAPPDATA) {
            throw "LOCALAPPDATA is not available; cannot safely back up existing Lc0 files."
        }
        $backupPath = Join-Path $env:LOCALAPPDATA "PicoChess\backups\$(Get-Date -Format 'yyyyMMdd-HHmmss')\$($Definition.Destination)"
        New-Item -ItemType Directory -Path $backupPath -Force | Out-Null
        foreach ($file in $existing) {
            Move-Item -LiteralPath (Join-Path $destination $file.Name) -Destination $backupPath
        }
        Write-Status "Existing Lc0 files moved to: $backupPath"
    }

    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    $installed = @()
    try {
        foreach ($file in $stagedFiles) {
            $target = Join-Path $destination $file.Name
            Copy-Item -LiteralPath $file.FullName -Destination $target
            $installed += $target
        }

        # Append missing catalog sections after the existing ones, so Stockfish stays first.
        $catalogTarget = Join-Path $destination "engines.ini"
        $existingCatalog = ""
        if (Test-Path -LiteralPath $catalogTarget) {
            $existingCatalog = [IO.File]::ReadAllText($catalogTarget)
        }
        $sections = [regex]::Split([IO.File]::ReadAllText($catalog), '(?m)^(?=\[)') | Where-Object { $_.Trim() }
        $missing = @($sections | Where-Object { -not $existingCatalog.Contains(($_ -split "`r?`n")[0].Trim()) })
        if ($missing.Count -gt 0) {
            $separator = ""
            if ($existingCatalog -and -not $existingCatalog.EndsWith("`n")) {
                $separator = "`n"
            }
            if ($existingCatalog) {
                $separator += "`n"
            }
            [IO.File]::AppendAllText($catalogTarget, $separator + (($missing | ForEach-Object { $_.TrimEnd() }) -join "`n`n") + "`n", $utf8)
        }
    } catch {
        foreach ($target in $installed) {
            Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
        }
        throw
    }
    Write-Status "Lc0 installed in $destination"
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
    Save-VerifiedDownload -Name $Name -Url $Definition.Url -OutFile $archivePath -Sha256 $(if ($Definition.ContainsKey("Sha256")) { $Definition.Sha256 } else { $null })

    switch ($Definition.ArchiveType) {
        "Zip" {
            Assert-SafeZipArchiveEntries -ArchivePath $archivePath
            Expand-Archive -LiteralPath $archivePath -DestinationPath $extractRoot
        }
        "TarGz" {
            if (-not $TarCommand) {
                throw "Windows tar.exe is required to extract the $Name resource pack."
            }
            Assert-SafeArchiveEntries -TarCommand $TarCommand -ArchivePath $archivePath
            Invoke-Native -FilePath $TarCommand -ArgumentList @("-xzf", $archivePath, "-C", $extractRoot)
        }
        default {
            throw "Unsupported archive type '$($Definition.ArchiveType)' for $Name."
        }
    }

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

function Initialize-WindowsConfiguration {
    param([string]$RepositoryPath)

    $configuration = Join-Path $RepositoryPath "picochess.ini"
    if (Test-Path -LiteralPath $configuration) {
        Write-Status "Preserving existing configuration: $configuration"
        return
    }

    $exampleConfiguration = Join-Path $RepositoryPath "picochess.ini.example-web-AMD64"
    if (-not (Test-Path -LiteralPath $exampleConfiguration)) {
        throw "Windows example configuration is missing: $exampleConfiguration"
    }
    Copy-Item -LiteralPath $exampleConfiguration -Destination $configuration
    Write-Status "Created $configuration from the Windows web example"
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
        Write-Warning "Configuration is missing: $configuration"
    }

    if ($selectedResources -contains "Games" -and -not $SkipResources) {
        Write-Status "Games data is installed separately from Scid vs. PC."
        Write-Status "After installing Scid, start with start-picochess-windows.ps1 to enable the Games tab."
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
                throw "Unknown resource '$normalizedResource'. Choose Engines, Lc0, Books, OpeningData, or Games."
            }
            if ($selectedResources -notcontains $normalizedResource) {
                $selectedResources += $normalizedResource
            }
        }
    }
    # Stockfish must be installed before Lc0 joins its engine folder.
    $selectedResources = @(@("Engines", "Lc0", "Books", "OpeningData", "Games") | Where-Object { $selectedResources -contains $_ })

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
        $tarCommand = $null
        if (@($selectedResources | Where-Object { $resourceDefinitions[$_].ArchiveType -in @("TarGz", "Lc0Engine") }).Count -gt 0) {
            # Prefer Windows' bsdtar: a GNU tar earlier on PATH (Git usr\bin) misreads C: paths.
            $tarCommand = Join-Path $env:SystemRoot "System32\tar.exe"
            if (-not (Test-Path -LiteralPath $tarCommand -PathType Leaf)) {
                $tar = Get-Command "tar.exe" -ErrorAction SilentlyContinue
                if (-not $tar) {
                    throw "Windows tar.exe is required to extract the selected tar.gz resource packs."
                }
                $tarCommand = $tar.Source
            }
        }
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        $temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ("picochess-windows-install-" + [Guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
        try {
            foreach ($resourceName in $selectedResources) {
                if ($resourceDefinitions[$resourceName].ArchiveType -eq "StarterEngine") {
                    Install-StarterEngine -Definition $resourceDefinitions[$resourceName] -RepositoryPath $targetPath -TemporaryRoot $temporaryRoot -ReplaceExisting:$ForceResources
                    continue
                }
                if ($resourceDefinitions[$resourceName].ArchiveType -eq "Lc0Engine") {
                    # Lc0 is optional: report a failure, but keep Stockfish and the other resources.
                    try {
                        Install-Lc0 -Definition $resourceDefinitions[$resourceName] -RepositoryPath $targetPath -TarCommand $tarCommand -TemporaryRoot $temporaryRoot -VenvPython $venvPython -ReplaceExisting:$ForceResources
                    } catch {
                        Write-Warning "Lc0 was not installed: $($_.Exception.Message)"
                        Write-Status "Stockfish remains available. Fix the problem and rerun with -Resources Lc0."
                    }
                    continue
                }
                Install-ResourcePack -Name $resourceName -Definition $resourceDefinitions[$resourceName] -RepositoryPath $targetPath -TarCommand $tarCommand -TemporaryRoot $temporaryRoot -ReplaceExisting:$ForceResources
            }
        } finally {
            if ((Test-Path -LiteralPath $temporaryRoot) -and ([IO.Path]::GetFileName($temporaryRoot) -like "picochess-windows-install-*")) {
                Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
            }
        }
    } else {
        Write-Status "Resource downloads skipped."
    }

    Write-Step "Preparing Windows configuration"
    Initialize-WindowsConfiguration -RepositoryPath $targetPath

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
    Write-Host "  & `"$(Join-Path $targetPath 'start-picochess-windows.ps1')`""
} catch {
    Write-Host "`nInstallation failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
