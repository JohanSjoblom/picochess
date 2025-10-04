#!/bin/sh
# install-engines.sh – Download and extract chess engines if missing
# POSIX-compliant

echo "Checking architecture..."
ARCH=$(uname -m)

# --- Unsupported -------------------------------------------------------------
if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "x86_64" ]; then
    echo "Unsupported architecture: $ARCH"
    exit 2
fi

# --- aarch64 -----------------------------------------------------------------
if [ "$ARCH" = "aarch64" ]; then
    echo "Detected architecture: aarch64"

    if [ ! -d "engines/aarch64" ]; then
        echo "No engines found for aarch64. Installing small package..."
        mkdir -p engines || exit 1
        cd engines || exit 1
        mkdir -p aarch64 || exit 1
        cd aarch64 || exit 1

        ENGINE_URL="https://github.com/JohanSjoblom/picochess/releases/download/v4.1.5/engines-aarch64-small.tar.gz"
        TMPFILE="/tmp/engines-aarch64-small.tar.gz"

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
        tar -xzf "$TMPFILE" -C engines || exit 1
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
        mkdir -p engines || exit 1
        cd engines || exit 1
        mkdir -p x86_64 || exit 1
        cd x86_64 || exit 1

        ENGINE_URL="https://github.com/JohanSjoblom/picochess/releases/download/v4.1.5/engines-x86_64-small.tar.gz"
        TMPFILE="/tmp/engines-x86_64-small.tar.gz"

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
        tar -xzf "$TMPFILE" -C engines || exit 1
        rm -f "$TMPFILE"

        echo "x86_64 engine package installed successfully."
    else
        echo "Engines for x86_64 already present."
    fi
fi

# --- Common LC0 weights ------------------------------------------------------
if [ ! -d "engines/lc0_weights" ]; then
    echo "Installing LC0 weights..."
    cd /opt/picochess/engines || exit 1
    mkdir -p lc0_weights || exit 1
    cd lc0_weights || exit 1

    WEIGHTS_URL="https://github.com/JohanSjoblom/picochess/releases/download/v4.1.5/lc0-weights-small.tar.gz"
    TMPFILE="/tmp/lc0-weights-small.tar.gz"

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
    tar -xzf "$TMPFILE" -C engines || exit 1
    rm -f "$TMPFILE"

    echo "LC0 weights installed successfully."
else
    echo "LC0 weights already present."
fi

exit 0
