#!/bin/bash
#
# Install the portable PicoChess environment on macOS.
# This script intentionally does not install engines, launch agents, drivers,
# or Linux host integrations.

set -eu

REPOSITORY_URL="https://github.com/JohanSjoblom/picochess.git"
# Temporary during Windows/macOS beta testing. Remove the explicit branch from
# the clone commands before merging this feature branch into the default branch.
REPOSITORY_BRANCH="471-port-to-windows"
INSTALL_DIR=""
RESOURCES="Books,OpeningData,Games"
SKIP_RESOURCES=false
UPDATE_REPO=false
FORCE_RESOURCES=false
RECREATE_VENV=false
SKIP_SMOKE_TESTS=false
VALIDATE_ONLY=false
TEMPORARY_ROOT=""
TEMP_BASE=${TMPDIR:-/tmp}
TEMP_BASE=${TEMP_BASE%/}
[ -n "$TEMP_BASE" ] || TEMP_BASE=/tmp
PYTHON_DETAILS=""

usage() {
    cat <<'EOF'
Usage: install-picochess-mac.sh [options]

Options:
  --install-dir PATH       Use or create this PicoChess checkout.
                           Default: this checkout, or $HOME/PicoChess.
  --resources LIST         Comma-separated resource packs to install.
                           Choices: Books, OpeningData, Games.
  --skip-resources         Do not download resource packs.
  --update-repo            Update a clean checkout with git pull --ff-only.
  --force-resources        Back up and replace existing resource directories.
  --recreate-venv          Back up the existing venv and create a new one.
  --skip-smoke-tests       Skip dependency and import smoke tests.
  --validate-only          Check prerequisites without changing anything.
  -h, --help               Show this help.

The installer supports native CPython 3.11 through 3.13 on Apple-silicon
(`arm64`) and Intel (`x86_64`) Macs. It does not require sudo.
EOF
}

fail() {
    printf '\nInstallation failed: %s\n' "$*" >&2
    exit 1
}

step() {
    printf '\n==> %s\n' "$*"
}

status() {
    printf '    %s\n' "$*"
}

warn() {
    printf 'Warning: %s\n' "$*" >&2
}

cleanup() {
    if [ -n "$TEMPORARY_ROOT" ] && [ -d "$TEMPORARY_ROOT" ]; then
        case "$TEMPORARY_ROOT" in
            "$TEMP_BASE"/picochess-mac-install.*)
                rm -rf -- "$TEMPORARY_ROOT"
                ;;
        esac
    fi
}
trap cleanup EXIT HUP INT TERM

is_checkout() {
    [ -d "$1/.git" ] && [ -f "$1/picochess.py" ] && [ -f "$1/requirements.txt" ]
}

absolute_path() {
    case "$1" in
        /*) printf '%s\n' "$1" ;;
        *) printf '%s/%s\n' "$(pwd -P)" "$1" ;;
    esac
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --install-dir)
            [ "$#" -ge 2 ] || fail "--install-dir requires a path."
            INSTALL_DIR=$2
            shift 2
            ;;
        --resources)
            [ "$#" -ge 2 ] || fail "--resources requires a comma-separated list."
            RESOURCES=$2
            shift 2
            ;;
        --skip-resources) SKIP_RESOURCES=true; shift ;;
        --update-repo) UPDATE_REPO=true; shift ;;
        --force-resources) FORCE_RESOURCES=true; shift ;;
        --recreate-venv) RECREATE_VENV=true; shift ;;
        --skip-smoke-tests) SKIP_SMOKE_TESTS=true; shift ;;
        --validate-only) VALIDATE_ONLY=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) fail "Unknown option: $1 (use --help for usage)." ;;
    esac
done

[ "$(uname -s)" = "Darwin" ] || fail "This installer supports macOS only."

SYSTEM_ARCH=$(uname -m)
case "$SYSTEM_ARCH" in
    arm64)
        ENGINE_PLATFORM=arm64
        ;;
    x86_64)
        ENGINE_PLATFORM=mac_x86_64
        ;;
    *)
        fail "Unsupported Mac architecture '$SYSTEM_ARCH'; expected arm64 or x86_64."
        ;;
esac

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
if [ -z "$INSTALL_DIR" ]; then
    if is_checkout "$SCRIPT_DIR"; then
        INSTALL_DIR=$SCRIPT_DIR
    else
        [ -n "${HOME:-}" ] || fail "HOME is unavailable; supply --install-dir explicitly."
        INSTALL_DIR="$HOME/PicoChess"
    fi
else
    INSTALL_DIR=$(absolute_path "$INSTALL_DIR")
fi

SELECTED_RESOURCES=""
OLD_IFS=$IFS
IFS=,
for resource in $RESOURCES; do
    IFS=$OLD_IFS
    resource=$(printf '%s' "$resource" | tr -d '[:space:]')
    case "$resource" in
        Books|OpeningData|Games)
            case ",$SELECTED_RESOURCES," in
                *,$resource,*) ;;
                *) SELECTED_RESOURCES="${SELECTED_RESOURCES}${SELECTED_RESOURCES:+,}${resource}" ;;
            esac
            ;;
        "") ;;
        *) fail "Unknown resource '$resource'. Choose Books, OpeningData, or Games." ;;
    esac
    IFS=,
done
IFS=$OLD_IFS

ensure_repository() {
    step "Checking repository"
    status "Install directory: $INSTALL_DIR"
    if command -v git >/dev/null 2>&1; then
        status "Git: $(command -v git)"
    else
        warn "Git was not found. It is required only when cloning or using --update-repo."
    fi

    if is_checkout "$INSTALL_DIR"; then
        status "Using existing checkout: $INSTALL_DIR"
    elif [ -e "$INSTALL_DIR" ]; then
        [ "$VALIDATE_ONLY" = false ] || fail "--validate-only requires an existing PicoChess checkout: $INSTALL_DIR"
        [ -d "$INSTALL_DIR" ] || fail "Install path exists and is not a directory: $INSTALL_DIR"
        [ -z "$(ls -A "$INSTALL_DIR")" ] || fail "Install directory is neither empty nor a PicoChess checkout: $INSTALL_DIR"
        command -v git >/dev/null 2>&1 || fail "Git is required to clone PicoChess. Install the Xcode Command Line Tools or Homebrew Git."
        step "Cloning PicoChess"
        git clone --branch "$REPOSITORY_BRANCH" "$REPOSITORY_URL" "$INSTALL_DIR"
    else
        [ "$VALIDATE_ONLY" = false ] || fail "--validate-only requires an existing PicoChess checkout: $INSTALL_DIR"
        command -v git >/dev/null 2>&1 || fail "Git is required to clone PicoChess. Install the Xcode Command Line Tools or Homebrew Git."
        mkdir -p "$(dirname -- "$INSTALL_DIR")"
        step "Cloning PicoChess"
        git clone --branch "$REPOSITORY_BRANCH" "$REPOSITORY_URL" "$INSTALL_DIR"
    fi

    is_checkout "$INSTALL_DIR" || fail "The selected directory is not a complete PicoChess Git checkout: $INSTALL_DIR"

    if command -v git >/dev/null 2>&1; then
        origin=$(git -C "$INSTALL_DIR" remote get-url origin 2>/dev/null || true)
        if [ -n "$origin" ]; then
            status "Git origin: $origin"
            case "$origin" in
                *JohanSjoblom/picochess|*JohanSjoblom/picochess.git) ;;
                *) warn "This checkout uses a non-standard origin. It will be preserved: $origin" ;;
            esac
        fi
    fi

    if [ "$UPDATE_REPO" = true ]; then
        [ "$VALIDATE_ONLY" = false ] || fail "--update-repo cannot be combined with --validate-only."
        command -v git >/dev/null 2>&1 || fail "Git is required for --update-repo."
        [ -z "$(git -C "$INSTALL_DIR" status --porcelain)" ] || fail "The checkout has local changes. Commit or stash them before using --update-repo. No files were changed."
        branch=$(git -C "$INSTALL_DIR" symbolic-ref --quiet --short HEAD 2>/dev/null || true)
        [ -n "$branch" ] || fail "The checkout is detached. Select a branch before using --update-repo."
        # A --single-branch clone fetches only the checked-out branch. Fetch all
        # branches so the checkout can later move to another branch; the current
        # branch and its upstream are unchanged.
        all_branches="+refs/heads/*:refs/remotes/origin/*"
        if ! git -C "$INSTALL_DIR" config --get-all remote.origin.fetch | grep -qxF "$all_branches"; then
            status "Configuring origin to fetch all branches."
            git -C "$INSTALL_DIR" config --replace-all remote.origin.fetch "$all_branches"
        fi
        step "Updating branch $branch with a fast-forward-only pull"
        git -C "$INSTALL_DIR" pull --ff-only
    fi
}

probe_python() {
    candidate=$1
    "$candidate" -c "import platform, struct, sys; print('{}.{}|{}|{}'.format(sys.version_info.major, sys.version_info.minor, struct.calcsize('P') * 8, platform.machine()))" 2>/dev/null
}

is_supported_python() {
    case "$SYSTEM_ARCH:$1" in
        arm64:3.11\|64\|arm64|arm64:3.12\|64\|arm64|arm64:3.13\|64\|arm64|x86_64:3.11\|64\|x86_64|x86_64:3.12\|64\|x86_64|x86_64:3.13\|64\|x86_64)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

select_python() {
    existing_python=$1
    if [ -n "$existing_python" ] && [ -x "$existing_python" ]; then
        details=$(probe_python "$existing_python" || true)
        if is_supported_python "$details"; then
            PYTHON_COMMAND=$existing_python
            PYTHON_DETAILS=$details
            return
        fi
        warn "The existing PicoChess virtual environment uses unsupported Python '$details'."
        fail "Rerun with --recreate-venv after installing native $SYSTEM_ARCH CPython 3.11 through 3.13."
    fi

    detected=""
    for candidate in python3.13 python3.12 python3.11 python3; do
        command -v "$candidate" >/dev/null 2>&1 || continue
        command_path=$(command -v "$candidate")
        details=$(probe_python "$command_path" || true)
        if is_supported_python "$details"; then
            PYTHON_COMMAND=$command_path
            PYTHON_DETAILS=$details
            return
        fi
        [ -z "$details" ] || detected="${detected}${detected:+, }$details"
    done
    [ -z "$detected" ] || warn "Unsupported Python detected: $detected"
    fail "Native $SYSTEM_ARCH CPython 3.11 through 3.13 was not found. Install it from python.org or with Homebrew and rerun this installer."
}

initialize_runtime_files() {
    for path in "$INSTALL_DIR/logs" "$INSTALL_DIR/games/uploads"; do
        if [ ! -d "$path" ]; then
            mkdir -p "$path"
            status "Created $path"
        fi
    done
    voices_file="$INSTALL_DIR/talker/voices/voices.ini"
    if [ ! -f "$voices_file" ]; then
        [ -f "$INSTALL_DIR/voices-example.ini" ] || fail "Voice configuration template is missing."
        cp "$INSTALL_DIR/voices-example.ini" "$voices_file"
        status "Created $voices_file"
    fi
}

resource_value() {
    case "$1:$2" in
        Books:url) printf '%s\n' "https://github.com/JohanSjoblom/picochess/releases/download/v4.2.0/books.tar.gz" ;;
        Books:archive) printf '%s\n' "books.tar.gz" ;;
        Books:destination) printf '%s\n' "books" ;;
        Books:marker) printf '%s\n' "books.ini" ;;
        OpeningData:url) printf '%s\n' "https://github.com/JohanSjoblom/picochess/releases/download/v4.2.0/openingdata.tar.gz" ;;
        OpeningData:archive) printf '%s\n' "openingdata.tar.gz" ;;
        OpeningData:destination) printf '%s\n' "obooksrv" ;;
        OpeningData:marker) printf '%s\n' "opening.data" ;;
        Games:url) printf '%s\n' "https://github.com/JohanSjoblom/picochess/releases/download/v4.2.0/gamesdb.tar.gz" ;;
        Games:archive) printf '%s\n' "gamesdb.tar.gz" ;;
        Games:destination) printf '%s\n' "gamesdb" ;;
        Games:marker) printf '%s\n' "get_games.tcl" ;;
    esac
}

assert_safe_archive() {
    archive=$1
    entries=$(tar -tzf "$archive") || fail "Could not inspect downloaded archive: $archive"
    [ -n "$entries" ] || fail "Downloaded archive is empty: $archive"
    while IFS= read -r entry; do
        case "$entry" in
            /*|..|../*|*/../*|*/..) fail "Archive contains an unsafe path: $entry" ;;
        esac
    done <<EOF
$entries
EOF
}

backup_resource() {
    existing=$1
    resource_name=$2
    [ -n "${HOME:-}" ] || fail "HOME is unavailable; cannot safely back up resource data."
    backup_root="$HOME/Library/Application Support/PicoChess/backups/$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$backup_root"
    backup_path="$backup_root/$resource_name"
    suffix=1
    while [ -e "$backup_path" ]; do
        backup_path="$backup_root/${resource_name}.$suffix"
        suffix=$((suffix + 1))
    done
    mv "$existing" "$backup_path"
    status "Existing resource moved to: $backup_path"
}

install_resource() {
    name=$1
    url=$(resource_value "$name" url)
    archive_name=$(resource_value "$name" archive)
    destination_name=$(resource_value "$name" destination)
    marker_name=$(resource_value "$name" marker)
    destination="$INSTALL_DIR/$destination_name"

    if [ -f "$destination/$marker_name" ] && [ "$FORCE_RESOURCES" = false ]; then
        status "$name already installed; keeping $destination"
        return
    fi
    if [ -e "$destination" ] && [ "$FORCE_RESOURCES" = false ]; then
        fail "$name destination exists but '$marker_name' is missing. Inspect it or rerun with --force-resources."
    fi

    resource_root="$TEMPORARY_ROOT/$name"
    extract_root="$resource_root/extract"
    archive_path="$resource_root/$archive_name"
    mkdir -p "$extract_root"
    step "Downloading $name"
    curl --fail --location --retry 2 --output "$archive_path" "$url"
    assert_safe_archive "$archive_path"
    tar -xzf "$archive_path" -C "$extract_root"
    [ -f "$extract_root/$marker_name" ] || fail "$name archive did not contain the expected '$marker_name' file. Nothing was installed."

    if [ -e "$destination" ]; then
        backup_resource "$destination" "$destination_name"
    fi
    mv "$extract_root" "$destination"
    status "$name installed in $destination"
}

show_readiness() {
    step "macOS readiness summary"
    status "Repository: $INSTALL_DIR"
    if [ -x "$INSTALL_DIR/venv/bin/python" ]; then
        status "Virtual environment: $INSTALL_DIR/venv/bin/python"
    else
        status "Virtual environment: not created"
    fi

    engine_dir="$INSTALL_DIR/engines/$ENGINE_PLATFORM"
    if [ -f "$engine_dir/engines.ini" ] && find "$engine_dir" -type f -perm -111 -print -quit 2>/dev/null | grep -q .; then
        status "Engine catalog: found in $engine_dir"
    else
        warn "No complete native macOS engine catalog was found. This is expected before adding an engine."
        status "Follow engines/README.md and place native macOS engines under engines/$ENGINE_PLATFORM."
    fi

    if [ -f "$INSTALL_DIR/picochess.ini" ]; then
        status "Configuration: preserving existing picochess.ini"
    else
        warn "picochess.ini was not created because no engine path should be guessed. Configure it after adding a macOS engine."
    fi

    case ",$SELECTED_RESOURCES," in
        *,Games,*)
            if [ "$SKIP_RESOURCES" = false ]; then
                status "Games database data is portable, but its bundled Linux tcscid binaries are not used on macOS."
                status "With a native macOS tcscid, start-picochess-mac.sh --tcscid PATH enables the Games tab."
            fi
            ;;
    esac
}

printf 'PicoChess macOS installer\n'
ensure_repository

VENV_PATH="$INSTALL_DIR/venv"
VENV_PYTHON="$VENV_PATH/bin/python"
existing_python=""
if [ "$RECREATE_VENV" = false ]; then
    existing_python=$VENV_PYTHON
fi
select_python "$existing_python"
step "Checking Python"
status "Python: $PYTHON_COMMAND ($PYTHON_DETAILS)"

if [ "$VALIDATE_ONLY" = true ]; then
    show_readiness
    printf '\nValidation completed; no changes were made.\n'
    exit 0
fi

step "Preparing runtime directories"
initialize_runtime_files

if [ "$RECREATE_VENV" = true ] && [ -e "$VENV_PATH" ]; then
    venv_backup="$VENV_PATH.backup.$(date +%Y%m%d-%H%M%S)"
    mv "$VENV_PATH" "$venv_backup"
    status "Existing venv moved to: $venv_backup"
fi
if [ -e "$VENV_PATH" ] && [ ! -x "$VENV_PYTHON" ]; then
    fail "The existing venv is incomplete. Inspect it or rerun with --recreate-venv."
fi
if [ ! -x "$VENV_PYTHON" ]; then
    step "Creating Python virtual environment"
    "$PYTHON_COMMAND" -m venv "$VENV_PATH"
else
    status "Reusing virtual environment: $VENV_PATH"
fi

step "Installing Python dependencies"
"$VENV_PYTHON" -m ensurepip --upgrade
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install --upgrade -r "$INSTALL_DIR/requirements.txt"

if [ "$SKIP_RESOURCES" = false ]; then
    command -v curl >/dev/null 2>&1 || fail "curl is required to download resource packs."
    command -v tar >/dev/null 2>&1 || fail "tar is required to extract resource packs."
    TEMPORARY_ROOT=$(mktemp -d "$TEMP_BASE/picochess-mac-install.XXXXXX")
    OLD_IFS=$IFS
    IFS=,
    for resource in $SELECTED_RESOURCES; do
        IFS=$OLD_IFS
        install_resource "$resource"
        IFS=,
    done
    IFS=$OLD_IFS
else
    status "Resource downloads skipped."
fi

if [ "$SKIP_SMOKE_TESTS" = false ]; then
    step "Running macOS smoke tests"
    (
        cd "$INSTALL_DIR"
        "$VENV_PYTHON" -m pip check
        "$VENV_PYTHON" -c "from dgt.board import DgtBoard; print('dgt.board import OK')"
        "$VENV_PYTHON" -c "import server; print('server import OK')"
        "$VENV_PYTHON" picochess.py --help
    )
fi

show_readiness
printf '\nPicoChess macOS environment installation completed.\n'
printf 'After adding and configuring a native macOS UCI engine, start with:\n'
printf '  bash "%s/start-picochess-mac.sh"\n' "$INSTALL_DIR"
