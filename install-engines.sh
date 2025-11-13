#!/bin/sh
# install-engines.sh – Download and extract chess engines if missing
# POSIX-compliant
#
# Run this as normal user pi, not as sudo
#

usage() {
    cat <<EOF
Usage: $0 [small|lite]

Options:
  small   Install the smaller aarch64 engine bundle.
  lite    Install the lite/DGT-focused aarch64 engine bundle.

Notes:
  - Script only installs engines when the target directories are missing.
  - To force a reinstall, first run move-engines-to-backup.sh.
  - You must specify either "small" or "lite".

Example:
  ./install-engines.sh lite
EOF
    exit "${1:-0}"
}

if [ $# -eq 0 ]; then
    usage 1
fi

case "$1" in
    -h|--help|help)
        usage 0
        ;;
esac

ENGINE_VARIANT=$1
ENGINE_VARIANT=$(printf "%s" "$ENGINE_VARIANT" | tr '[:upper:]' '[:lower:]')
if [ "$ENGINE_VARIANT" != "small" ] && [ "$ENGINE_VARIANT" != "lite" ]; then
    usage 1
fi

REPO_DIR=${REPO_DIR:-/opt/picochess}
RESTORE_SCRIPT="$REPO_DIR/restore-engines-from-backup.sh"
ENGINES_DIR="$REPO_DIR/engines"

if [ ! -d "$REPO_DIR" ]; then
    echo "Repository directory $REPO_DIR not found. Aborting." 1>&2
    exit 1
fi

cd "$REPO_DIR" || {
    echo "Failed to enter repository directory $REPO_DIR." 1>&2
    exit 1
}

echo "Checking architecture..."
ARCH=$(uname -m)

# --- Unsupported -------------------------------------------------------------
if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "x86_64" ]; then
    echo "Unsupported architecture: $ARCH"
    exit 2
fi

# Ensure top-level engines folder and tmp folder exist
mkdir -p "$ENGINES_DIR" || exit 1
mkdir -p /home/pi/pico_backups/current/tmp || exit 1

# --- aarch64 -----------------------------------------------------------------
if [ "$ARCH" = "aarch64" ]; then
    echo "Detected architecture: aarch64 (variant: $ENGINE_VARIANT)"

    if [ ! -d "$ENGINES_DIR/aarch64" ]; then
        echo "No engines found for aarch64. Installing requested engine package..."
        mkdir -p "$ENGINES_DIR/aarch64" || exit 1

        if [ "$ENGINE_VARIANT" = "lite" ]; then
            ENGINE_URL="https://github.com/JohanSjoblom/picochess/releases/download/v4.1.6/aarch64_engines_lite.tar.gz"
            TMPFILE="/home/pi/pico_backups/current/tmp/aarch64_engines_lite.tar.gz"
            ENGINE_DESC="aarch64 lite engine package"
        else
            ENGINE_URL="https://github.com/JohanSjoblom/picochess/releases/download/v4.1.5/engines-aarch64-small.tar.gz"
            TMPFILE="/home/pi/pico_backups/current/tmp/engines-aarch64-small.tar.gz"
            ENGINE_DESC="aarch64 small engine package"
        fi

        echo "Downloading $ENGINE_DESC..."
        if command -v curl >/dev/null 2>&1; then
            curl -L -o "$TMPFILE" "$ENGINE_URL" || exit 1
        elif command -v wget >/dev/null 2>&1; then
            wget -O "$TMPFILE" "$ENGINE_URL" || exit 1
        else
            echo "Error: need curl or wget to download" 1>&2
            exit 1
        fi

        echo "Extracting $ENGINE_DESC..."
        tar -xzf "$TMPFILE" -C "$ENGINES_DIR/aarch64" || {
            echo "Extraction failed for $ENGINE_DESC." 1>&2
            sh "$RESTORE_SCRIPT" arch "$ARCH"
            rm -f "$TMPFILE"
            exit 1
        }
        rm -f "$TMPFILE"

        echo "$ENGINE_DESC installed successfully."
    else
        echo "Engines for aarch64 already present."
    fi

    if [ "$ENGINE_VARIANT" = "lite" ]; then
        if [ ! -d "$ENGINES_DIR/mame_emulation" ]; then
            echo "No MAME emulation files found. Installing package..."
            mkdir -p "$ENGINES_DIR/mame_emulation" || exit 1

            MAME_URL="https://github.com/JohanSjoblom/picochess/releases/download/v4.1.6/aarch64_mame_lite.tar.gz"
            MAME_TMP="/home/pi/pico_backups/current/tmp/aarch64_mame_lite.tar.gz"

            echo "Downloading MAME emulation package..."
            if command -v curl >/dev/null 2>&1; then
                curl -L -o "$MAME_TMP" "$MAME_URL" || exit 1
            elif command -v wget >/dev/null 2>&1; then
                wget -O "$MAME_TMP" "$MAME_URL" || exit 1
            else
                echo "Error: need curl or wget to download" 1>&2
                exit 1
            fi

            echo "Extracting MAME emulation package..."
            tar -xzf "$MAME_TMP" -C "$ENGINES_DIR/mame_emulation" || {
                echo "Extraction failed for MAME emulation package." 1>&2
                rm -f "$MAME_TMP"
                exit 1
            }
            rm -f "$MAME_TMP"

            echo "MAME emulation package installed successfully."
        else
            echo "MAME emulation files already present."
        fi
    else
        echo "Skipping MAME emulation package for small variant."
    fi

    if [ "$ENGINE_VARIANT" = "lite" ]; then
        if [ ! -d "$ENGINES_DIR/rodent3" ]; then
            echo "No Rodent III files found. Installing package..."
            mkdir -p "$ENGINES_DIR/rodent3" || exit 1

            RODENT3_URL="https://github.com/JohanSjoblom/picochess/releases/download/v4.1.6/aarch64_rodent3_lite.tar.gz"
            RODENT3_TMP="/home/pi/pico_backups/current/tmp/aarch64_rodent3_lite.tar.gz"

            echo "Downloading Rodent III package..."
            if command -v curl >/dev/null 2>&1; then
                curl -L -o "$RODENT3_TMP" "$RODENT3_URL" || exit 1
            elif command -v wget >/dev/null 2>&1; then
                wget -O "$RODENT3_TMP" "$RODENT3_URL" || exit 1
            else
                echo "Error: need curl or wget to download" 1>&2
                exit 1
            fi

            echo "Extracting Rodent III package..."
            tar -xzf "$RODENT3_TMP" -C "$ENGINES_DIR/rodent3" || {
                echo "Extraction failed for Rodent III package." 1>&2
                rm -f "$RODENT3_TMP"
                exit 1
            }
            rm -f "$RODENT3_TMP"

            echo "Rodent III package installed successfully."
        else
            echo "Rodent III files already present."
        fi

        if [ ! -d "$ENGINES_DIR/rodent4" ]; then
            echo "No Rodent IV files found. Installing package..."
            mkdir -p "$ENGINES_DIR/rodent4" || exit 1

            RODENT4_URL="https://github.com/JohanSjoblom/picochess/releases/download/v4.1.6/aarch64_rodent4_lite.tar.gz"
            RODENT4_TMP="/home/pi/pico_backups/current/tmp/aarch64_rodent4_lite.tar.gz"

            echo "Downloading Rodent IV package..."
            if command -v curl >/dev/null 2>&1; then
                curl -L -o "$RODENT4_TMP" "$RODENT4_URL" || exit 1
            elif command -v wget >/dev/null 2>&1; then
                wget -O "$RODENT4_TMP" "$RODENT4_URL" || exit 1
            else
                echo "Error: need curl or wget to download" 1>&2
                exit 1
            fi

            echo "Extracting Rodent IV package..."
            tar -xzf "$RODENT4_TMP" -C "$ENGINES_DIR/rodent4" || {
                echo "Extraction failed for Rodent IV package." 1>&2
                rm -f "$RODENT4_TMP"
                exit 1
            }
            rm -f "$RODENT4_TMP"

            echo "Rodent IV package installed successfully."
        else
            echo "Rodent IV files already present."
        fi
    else
        echo "Skipping Rodent III and IV packages for small variant."
    fi
fi

# --- x86_64 ------------------------------------------------------------------
if [ "$ARCH" = "x86_64" ]; then
    echo "Detected architecture: x86_64"

    if [ ! -d "$ENGINES_DIR/x86_64" ]; then
        echo "No engines found for x86_64. Installing small package..."
        mkdir -p "$ENGINES_DIR/x86_64" || exit 1

        ENGINE_URL="https://github.com/JohanSjoblom/picochess/releases/download/v4.1.5/engines-x86_64-small.tar.gz"
        TMPFILE="/home/pi/pico_backups/current/tmp/engines-x86_64-small.tar.gz"

        echo "Downloading x86_64 engines..."
        if command -v curl >/dev/null 2>&1; then
            curl -L -o "$TMPFILE" "$ENGINE_URL" || exit 1
        elif command -v wget >/dev/null 2>&1; then
            wget -O "$TMPFILE" "$ENGINE_URL" || exit 1
        else
            echo "Error: need curl or wget to download" 1>&2
            exit 1
        fi

        echo "Extracting x86_64 engines..."
        tar -xzf "$TMPFILE" -C "$ENGINES_DIR/x86_64" || {
            echo "Extraction failed for x86_64 engines." 1>&2
            sh "$RESTORE_SCRIPT" arch "$ARCH"
            rm -f "$TMPFILE"
            exit 1
        }
        rm -f "$TMPFILE"

        echo "x86_64 engine package installed successfully."
    else
        echo "Engines for x86_64 already present."
    fi
fi

# --- Common LC0 weights ------------------------------------------------------
if [ ! -d "$ENGINES_DIR/lc0_weights" ]; then
    echo "Installing LC0 weights..."
    mkdir -p "$ENGINES_DIR/lc0_weights" || exit 1

    WEIGHTS_URL="https://github.com/JohanSjoblom/picochess/releases/download/v4.1.6/lc0_weights.tar.gz"
    TMPFILE="/home/pi/pico_backups/current/tmp/lc0_weights.tar.gz"

    echo "Downloading LC0 weights..."
    if command -v curl >/dev/null 2>&1; then
        curl -L -o "$TMPFILE" "$WEIGHTS_URL" || exit 1
    elif command -v wget >/dev/null 2>&1; then
        wget -O "$TMPFILE" "$WEIGHTS_URL" || exit 1
    else
        echo "Error: need curl or wget to download" 1>&2
        exit 1
    fi

    echo "Extracting LC0 weights..."
    tar -xzf "$TMPFILE" -C "$ENGINES_DIR/lc0_weights" || {
        echo "Extraction failed for LC0 weights." 1>&2
        sh "$RESTORE_SCRIPT" lc0
        rm -f "$TMPFILE"
        exit 1
    }
    rm -f "$TMPFILE"

    echo "LC0 weights installed successfully."
else
    echo "LC0 weights already present in engines folder."
fi

# --- Script engines ----------------------------------------------------------
if [ ! -d "$ENGINES_DIR/script_engines" ]; then
    echo "Installing script engines..."
    mkdir -p "$ENGINES_DIR/script_engines" || exit 1

    SCRIPTS_URL="https://github.com/JohanSjoblom/picochess/releases/download/v4.1.6/script_engines.tar.gz"
    TMPFILE="/home/pi/pico_backups/current/tmp/script_engines.tar.gz"

    echo "Downloading script engines..."
    if command -v curl >/dev/null 2>&1; then
        curl -L -o "$TMPFILE" "$SCRIPTS_URL" || exit 1
    elif command -v wget >/dev/null 2>&1; then
        wget -O "$TMPFILE" "$SCRIPTS_URL" || exit 1
    else
        echo "Error: need curl or wget to download" 1>&2
        exit 1
    fi

    echo "Extracting script engines..."
    tar -xzf "$TMPFILE" -C "$ENGINES_DIR/script_engines" || {
        echo "Extraction failed for script engines." 1>&2
        rm -f "$TMPFILE"
        exit 1
    }
    rm -f "$TMPFILE"

    echo "Script engines installed successfully."
else
    echo "Script engines already present in engines folder."
fi

# --- pgn_audio files ---------------------------------------------------
if [ "$ENGINE_VARIANT" = "lite" ]; then
    if [ ! -d "$ENGINES_DIR/pgn_engine/pgn_audio" ]; then
        echo "Installing pgn_audio files..."
        mkdir -p "$ENGINES_DIR/pgn_engine/pgn_audio" || exit 1

        AUDIO_URL="https://github.com/JohanSjoblom/picochess/releases/download/v4.1.5/pgn_audio.tar.gz"
        TMPFILE="/home/pi/pico_backups/current/tmp/pgn_audio.tar.gz"

        echo "Downloading pgn_audio files..."
        if command -v curl >/dev/null 2>&1; then
            curl -L -o "$TMPFILE" "$AUDIO_URL" || exit 1
        elif command -v wget >/dev/null 2>&1; then
            wget -O "$TMPFILE" "$AUDIO_URL" || exit 1
        else
            echo "Error: need curl or wget to download" 1>&2
            exit 1
        fi

        echo "Extracting pgn_audio files..."
        tar -xzf "$TMPFILE" -C "$ENGINES_DIR/pgn_engine/pgn_audio" || { rm -f "$TMPFILE"; exit 1; }
        rm -f "$TMPFILE"

        echo "pgn_audio files installed successfully."
    else
        echo "pgn_audio files already present in engines folder."
    fi
else
    echo "Skipping pgn_audio files for small variant."
fi

exit 0
