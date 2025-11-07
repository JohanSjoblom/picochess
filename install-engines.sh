#!/bin/sh
# install-engines.sh – Download and extract chess engines if missing
# POSIX-compliant
#
# Run this as normal user pi, not as sudo
#

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
    echo "Detected architecture: aarch64"

    if [ ! -d "$ENGINES_DIR/aarch64" ]; then
        echo "No engines found for aarch64. Installing latest lite/DGT engine package..."
        mkdir -p "$ENGINES_DIR/aarch64" || exit 1

        ENGINE_URL="https://github.com/JohanSjoblom/picochess/releases/download/v4.1.6/aarch64_engines_lite.tar.gz"
        TMPFILE="/home/pi/pico_backups/current/tmp/aarch64_engines_lite.tar.gz"

        echo "Downloading aarch64 engines..."
        if command -v curl >/dev/null 2>&1; then
            curl -L -o "$TMPFILE" "$ENGINE_URL" || exit 1
        elif command -v wget >/dev/null 2>&1; then
            wget -O "$TMPFILE" "$ENGINE_URL" || exit 1
        else
            echo "Error: need curl or wget to download" 1>&2
            exit 1
        fi

        echo "Extracting aarch64 engines..."
        tar -xzf "$TMPFILE" -C "$ENGINES_DIR/aarch64" || {
            echo "Extraction failed for aarch64 engines." 1>&2
            sh "$RESTORE_SCRIPT" arch "$ARCH"
            rm -f "$TMPFILE"
            exit 1
        }
        rm -f "$TMPFILE"

        echo "aarch64 engine package installed successfully."
    else
        echo "Engines for aarch64 already present."
    fi

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

# --- pgn_audio files ---------------------------------------------------
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

exit 0
