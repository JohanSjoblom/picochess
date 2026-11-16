#!/bin/bash
#
# Install the portable PicoChess environment on macOS.
# This script installs a starter engine when the native engine directory is
# missing. It does not install launch agents, drivers, or Linux host integrations.

set -eu

REPOSITORY_URL="https://github.com/JohanSjoblom/picochess.git"
REPOSITORY_BRANCH="master"
INSTALL_DIR=""
RESOURCES="Engines,Lc0,Books,OpeningData,Games"
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
                           Choices: Engines, Lc0, Books, OpeningData, Games.
                           Lc0 also downloads the shared Lc0 weights (about
                           620 MB) when engines/lc0_weights is missing. A failed
                           Lc0 installation is a warning; Stockfish stays usable.
  --skip-resources         Do not download resource packs.
  --update-repo            Update a clean checkout with git pull --ff-only.
  --force-resources        Back up and replace existing data resource directories.
                           The native engine directory is always preserved.
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
        Engines|Lc0|Books|OpeningData|Games)
            case ",$SELECTED_RESOURCES," in
                *,$resource,*) ;;
                *) SELECTED_RESOURCES="${SELECTED_RESOURCES}${SELECTED_RESOURCES:+,}${resource}" ;;
            esac
            ;;
        "") ;;
        *) fail "Unknown resource '$resource'. Choose Engines, Lc0, Books, OpeningData, or Games." ;;
    esac
    IFS=,
done
IFS=$OLD_IFS

# Stockfish must be installed before Lc0 joins its engine folder.
ORDERED_RESOURCES=""
for resource in Engines Lc0 Books OpeningData Games; do
    case ",$SELECTED_RESOURCES," in
        *,$resource,*) ORDERED_RESOURCES="${ORDERED_RESOURCES}${ORDERED_RESOURCES:+,}${resource}" ;;
    esac
done
SELECTED_RESOURCES=$ORDERED_RESOURCES

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
    config_file="$INSTALL_DIR/picochess.ini"
    if [ ! -e "$config_file" ] && [ ! -L "$config_file" ]; then
        [ -f "$INSTALL_DIR/picochess.ini.example-web-MAC" ] || fail "macOS configuration template is missing."
        cp "$INSTALL_DIR/picochess.ini.example-web-MAC" "$config_file"
        status "Created $config_file from picochess.ini.example-web-MAC"
    fi
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

assert_sha256() {
    file=$1
    expected=$2
    actual=$(shasum -a 256 "$file" | awk '{print $1}') || fail "Could not compute the checksum of $file"
    [ "$actual" = "$expected" ] || fail "Checksum mismatch for $(basename "$file"). Expected $expected, received $actual. Nothing was installed."
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

install_starter_engine() {
    destination="$INSTALL_DIR/engines/$ENGINE_PLATFORM"
    if [ -d "$destination" ]; then
        status "Native engine directory already exists; keeping $destination"
        return
    fi
    [ ! -e "$destination" ] && [ ! -L "$destination" ] || fail "Engine destination exists and is not a directory: $destination"

    resource_root="$TEMPORARY_ROOT/Engines"
    extract_root="$resource_root/extract"
    metadata_root="$resource_root/metadata"
    stage_root="$resource_root/stage"
    archive_path="$resource_root/stockfish-macos-universal.tar.gz"
    metadata_archive="$resource_root/picochess-mac-engines-small-v4.3.5.tar.gz"
    mkdir -p "$extract_root" "$metadata_root" "$stage_root"

    step "Downloading Stockfish 19 for macOS"
    curl --fail --location --retry 2 --output "$archive_path" \
        "https://github.com/official-stockfish/Stockfish/releases/download/sf_19/stockfish-macos-universal.tar.gz"
    assert_sha256 "$archive_path" a1f0e3bcc5a6927a11fe6fc8e54a779754645f3c2bae2cf13420fd1957adaa77
    assert_safe_archive "$archive_path"
    tar -xzf "$archive_path" -C "$extract_root"

    matches=$(find "$extract_root" -type f -name stockfish-macos-universal -print)
    [ -n "$matches" ] || fail "Stockfish archive did not contain stockfish-macos-universal. Nothing was installed."
    case "$matches" in
        *'
'*) fail "Stockfish archive contained multiple engine binaries. Nothing was installed." ;;
    esac
    cp "$matches" "$stage_root/a-stockf"
    chmod 755 "$stage_root/a-stockf"

    # Running the UCI handshake also checks that this Mac can execute the binary.
    if ! uci_output=$(printf 'uci\nisready\nquit\n' | "$stage_root/a-stockf" 2>&1); then
        fail "Downloaded Stockfish cannot run on this Mac: $uci_output"
    fi
    printf '%s\n' "$uci_output" | grep -qx 'uciok' || fail "Downloaded Stockfish did not answer uci. Nothing was installed."
    printf '%s\n' "$uci_output" | grep -qx 'readyok' || fail "Downloaded Stockfish did not answer isready. Nothing was installed."

    step "Downloading PicoChess macOS engine metadata"
    curl --fail --location --retry 2 --output "$metadata_archive" \
        "https://github.com/JohanSjoblom/picochess/releases/download/v4.3.5/picochess-mac-engines-small-v4.3.5.tar.gz"
    assert_sha256 "$metadata_archive" 4ccab03b14f86983915933724aca206843c38c210e9d48747ef8365ccdd6f5fc
    assert_safe_archive "$metadata_archive"
    tar -xzf "$metadata_archive" -C "$metadata_root"
    [ -f "$metadata_root/engines.ini" ] || fail "Mac engine metadata archive is missing engines.ini. Nothing was installed."
    [ -f "$metadata_root/a-stockf.uci" ] || fail "Mac engine metadata archive is missing a-stockf.uci. Nothing was installed."
    [ ! -e "$metadata_root/a-stockf" ] && [ ! -L "$metadata_root/a-stockf" ] || fail "Mac engine metadata archive must not replace the official Stockfish binary."
    grep -q '^\[a-stockf\]$' "$metadata_root/engines.ini" || fail "Mac engine catalog is missing [a-stockf]. Nothing was installed."
    grep -q '^\[Elo@2200\]$' "$metadata_root/a-stockf.uci" || fail "Mac engine levels are missing Elo@2200. Nothing was installed."
    cp -R "$metadata_root"/. "$stage_root"/

    cp "$INSTALL_DIR/LICENSE" "$stage_root/COPYING.txt"
    cat > "$stage_root/STOCKFISH-SOURCE.txt" <<'EOF'
Stockfish 19, unmodified official macOS universal binary.
Binary: https://github.com/official-stockfish/Stockfish/releases/tag/sf_19
Source: https://github.com/official-stockfish/Stockfish/tree/sf_19
License: GPL-3.0-or-later (COPYING.txt)
EOF

    mkdir -p "$INSTALL_DIR/engines"
    mv "$stage_root" "$destination"
    status "Stockfish installed in $destination"
}

LC0_ENTRIES="lc0 classic elitev2 maiav0321 maia3"

install_lc0_weights() {
    weights_dir="$INSTALL_DIR/engines/lc0_weights"
    if [ -e "$weights_dir" ]; then
        # Shared with other platforms; refreshing it means moving the whole folder away first.
        status "Reusing existing Lc0 weights in $weights_dir"
        return
    fi
    weights_root="$TEMPORARY_ROOT/Lc0Weights"
    mkdir -p "$weights_root/extract"
    step "Downloading Lc0 weights (about 620 MB)"
    curl --fail --location --retry 2 --output "$weights_root/lc0_weights.tar.gz" \
        "https://github.com/JohanSjoblom/picochess/releases/download/v4.4.1/lc0_weights.tar.gz"
    assert_sha256 "$weights_root/lc0_weights.tar.gz" 6b4d6b0c23fdd8f3e955a639b597aaefa403452b692ce012c03145b35f84e66f
    assert_safe_archive "$weights_root/lc0_weights.tar.gz"
    tar -xzf "$weights_root/lc0_weights.tar.gz" -C "$weights_root/extract"
    rm -f "$weights_root/lc0_weights.tar.gz"
    [ -f "$weights_root/extract/792013-192x15.txt" ] || fail "Lc0 weights archive did not contain 792013-192x15.txt."
    mkdir -p "$INSTALL_DIR/engines"
    mv "$weights_root/extract" "$weights_dir"
    status "Lc0 weights installed in $weights_dir"
}

install_lc0() {
    destination="$INSTALL_DIR/engines/$ENGINE_PLATFORM"
    if [ -e "$destination/lc0" ] || [ -L "$destination/lc0" ]; then
        status "Lc0 already installed; keeping $destination"
        return
    fi

    install_lc0_weights
    weights_dir="$INSTALL_DIR/engines/lc0_weights"

    resource_root="$TEMPORARY_ROOT/Lc0"
    metadata_root="$resource_root/metadata"
    stage_root="$resource_root/stage"
    mkdir -p "$metadata_root" "$stage_root"

    # Only a pre-release currently ships a macOS binary. It is universal
    # (arm64 and x86_64) and uses Apple's Accelerate for Backend = blas.
    step "Downloading official Lc0 for macOS (v0.33.0-rc0)"
    curl --fail --location --retry 2 --output "$stage_root/lc0" \
        "https://github.com/LeelaChessZero/lc0/releases/download/v0.33.0-rc0/lc0-v0.33.0-rc0-macos_13.2.1"
    assert_sha256 "$stage_root/lc0" 7414c000e45c7814f5d329ed6051f5d1fc6c2f514dded1147628ee7b473c9dc3
    chmod 755 "$stage_root/lc0"
    for entry in $LC0_ENTRIES; do
        [ "$entry" = lc0 ] || ln -s lc0 "$stage_root/$entry"
    done

    step "Downloading PicoChess macOS Lc0 metadata"
    metadata_archive="$resource_root/picochess-mac-lc0-metadata-v4.4.1.tar.gz"
    curl --fail --location --retry 2 --output "$metadata_archive" \
        "https://github.com/JohanSjoblom/picochess/releases/download/v4.4.1/picochess-mac-lc0-metadata-v4.4.1.tar.gz"
    assert_sha256 "$metadata_archive" 151ddc724c8e46185ac9fbddc930d2dff0c98a0394369b704d79459c32121d90
    assert_safe_archive "$metadata_archive"
    tar -xzf "$metadata_archive" -C "$metadata_root"
    [ -f "$metadata_root/engines.ini" ] || fail "Lc0 metadata archive is missing engines.ini."

    # The level files use the Linux weights path; point them at this installation.
    weights_replacement=$(printf '%s/' "$weights_dir" | sed 's/[&|\\]/\\&/g')
    for entry in $LC0_ENTRIES; do
        [ ! -e "$metadata_root/$entry" ] && [ ! -L "$metadata_root/$entry" ] || fail "Lc0 metadata archive must not contain engine executables."
        [ -f "$metadata_root/$entry.uci" ] || fail "Lc0 metadata archive is missing $entry.uci."
        grep -q "^\[$entry\]\$" "$metadata_root/engines.ini" || fail "Lc0 catalog is missing [$entry]."
        sed "s|/opt/picochess/engines/lc0_weights/|$weights_replacement|g" "$metadata_root/$entry.uci" > "$stage_root/$entry.uci"
        ! grep -q '/opt/' "$stage_root/$entry.uci" || fail "$entry.uci still contains a Linux path after rewriting."
        grep -E '^[[:space:]]*WeightsFile[[:space:]]*=' "$stage_root/$entry.uci" | sed 's/^[^=]*=[[:space:]]*//; s/[[:space:]]*$//' |
            while IFS= read -r network; do
                [ -f "$network" ] || fail "$entry.uci needs a network that is missing: $network"
            done
    done

    step "Checking Lc0 with a short search for each catalog entry"
    "$VENV_PYTHON" -I "$INSTALL_DIR/scripts/check-lc0-engines.py" "$stage_root"

    for staged in "$stage_root"/*; do
        name=$(basename "$staged")
        [ ! -e "$destination/$name" ] && [ ! -L "$destination/$name" ] ||
            fail "A file named $name already exists in $destination. Move it away and rerun with --resources Lc0."
    done
    mkdir -p "$destination"
    for staged in "$stage_root"/*; do
        cp -P "$staged" "$destination/"
    done

    # Append missing catalog sections after the existing ones, so Stockfish stays first.
    catalog="$destination/engines.ini"
    for entry in $LC0_ENTRIES; do
        if [ -f "$catalog" ] && grep -q "^\[$entry\]\$" "$catalog"; then
            continue
        fi
        if [ -s "$catalog" ]; then
            [ -z "$(tail -c 1 "$catalog")" ] || printf '\n' >> "$catalog"
            printf '\n' >> "$catalog"
        fi
        awk -v header="[$entry]" '
            $0 == header { copying = 1; print; next }
            /^\[/ { copying = 0 }
            copying && NF { print }
        ' "$metadata_root/engines.ini" >> "$catalog"
    done
    status "Lc0 installed in $destination"
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
        warn "No complete native macOS engine catalog was found."
        status "Follow engines/README.md and place native macOS engines under engines/$ENGINE_PLATFORM."
    fi

    if [ -f "$INSTALL_DIR/picochess.ini" ]; then
        status "Configuration: picochess.ini is available"
    else
        warn "picochess.ini is missing; installation creates it from picochess.ini.example-web-MAC."
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
        if [ "$resource" = Engines ]; then
            install_starter_engine
        elif [ "$resource" = Lc0 ]; then
            # Lc0 is optional. A subshell keeps fail() from ending the whole
            # installation while set -e still stops at the first Lc0 error.
            set +e
            (
                set -e
                fail() {
                    printf '\nLc0 step failed: %s\n' "$*" >&2
                    exit 1
                }
                install_lc0
            )
            lc0_status=$?
            set -e
            if [ "$lc0_status" -ne 0 ]; then
                warn "Lc0 was not installed. Stockfish remains available; fix the problem and rerun with --resources Lc0."
            fi
        else
            install_resource "$resource"
        fi
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
printf 'Start with:\n'
printf '  bash "%s/start-picochess-mac.sh"\n' "$INSTALL_DIR"
