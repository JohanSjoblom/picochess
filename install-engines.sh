#!/bin/sh
# install-engines.sh – Download and extract chess engines if missing
# POSIX-compliant
#
# Run this as normal user pi, not as sudo
#

echo "Checking architecture..."
ARCH=$(uname -m)

# --- Unsupported -------------------------------------------------------------
if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "x86_64" ]; then
    echo "Unsupported architecture: $ARCH"
    exit 2
fi

# Ensure top-level engines folder and tmp folder exist
mkdir -p engines || exit 1
mkdir -p /home/pi/pico_backups/current/tmp || exit 1

# --- aarch64 -----------------------------------------------------------------
if [ "$ARCH" = "aarch64" ]; then
    echo "Detected architecture: aarch64"

    if [ ! -d "engines/aarch64" ]; then
        echo "No engines found for aarch64. Installing small package..."
        mkdir -p engines/aarch64 || exit 1

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
        tar -xzf "$TMPFILE" -C engines/aarch64 || { rm -f "$TMPFILE"; exit 1; }
        rm -f "$TMPFILE"

        echo "aarch64 engine package installed successfully."
    else
        echo "Engines for aarch64 already present."
    fi
fi

# --- x86_64 ------------------------------------------------------------------
if [ "$ARCH" = "x86_64" ]; then
    echo "Detected architecture: x86_64"

    if [ ! -d "engines/x86_64" ]; then
        echo "No engines found for x86_64. Installing small package..."
        mkdir -p engines/x86_64 || exit 1

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
        tar -xzf "$TMPFILE" -C engines/x86_64 || { rm -f "$TMPFILE"; exit 1; }
        rm -f "$TMPFILE"

        echo "x86_64 engine package installed successfully."
    else
        echo "Engines for x86_64 already present."
    fi
fi

# --- Common LC0 weights ------------------------------------------------------
if [ ! -d "engines/$ARCH/lc0_weights" ]; then
    if [ ! -d "engines/lc0_weights" ]; then
        echo "Installing LC0 weights..."
        mkdir -p engines/lc0_weights || exit 1

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
        tar -xzf "$TMPFILE" -C engines/lc0_weights || { rm -f "$TMPFILE"; exit 1; }
        rm -f "$TMPFILE"

        echo "LC0 weights installed successfully."
    else
        echo "LC0 weights already present in engines folder."
    fi
else
    echo "LC0 weights already present in engines/$ARCH."
fi

# --- pgn_audio files ---------------------------------------------------
if [ ! -d "engines/pgn_engine/pgn_audio" ]; then
    echo "Installing pgn_audio files..."
    mkdir -p engines/pgn_engine/pgn_audio || exit 1

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
    tar -xzf "$TMPFILE" -C engines/pgn_engine/pgn_audio || { rm -f "$TMPFILE"; exit 1; }
    rm -f "$TMPFILE"

    echo "pgn_audio files installed successfully."
else
    echo "pgn_audio files already present in engines folder."
fi

exit 0
