#!/bin/sh
# install-books-games.sh – Download and install opening books and game resources
# POSIX-compliant; intended to be run as user pi (no sudo)
#
# This draft mirrors install-engines.sh and assumes future release assets named:
#   v4.1.7/books-and-games-aarch64.tar.gz
#   v4.1.7/books-and-games-x86_64.tar.gz
#

REPO_DIR=${REPO_DIR:-/opt/picochess}
TMP_DIR="/home/pi/pico_backups/current/tmp"

if [ ! -d "$REPO_DIR" ]; then
    echo "Repository directory $REPO_DIR not found. Aborting." >&2
    exit 1
fi

mkdir -p "$TMP_DIR" || exit 1

ARCH=$(uname -m)
ARCHIVE_NAME=""

case "$ARCH" in
    aarch64)
        ARCHIVE_NAME="books-and-games-aarch64.tar.gz"
        ;;
    x86_64)
        ARCHIVE_NAME="books-and-games-x86_64.tar.gz"
        ;;
    *)
        echo "Unsupported architecture: $ARCH" >&2
        exit 2
        ;;
esac

ASSET_URL="https://github.com/JohanSjoblom/picochess/releases/download/v4.1.7/${ARCHIVE_NAME}"
TMPFILE="$TMP_DIR/$ARCHIVE_NAME"

echo "Downloading book and game resources from $ASSET_URL"
if command -v curl >/dev/null 2>&1; then
    curl -L -o "$TMPFILE" "$ASSET_URL" || exit 1
elif command -v wget >/dev/null 2>&1; then
    wget -O "$TMPFILE" "$ASSET_URL" || exit 1
else
    echo "Error: need curl or wget to download assets." >&2
    exit 1
fi

echo "Extracting resources into $REPO_DIR"
if ! tar -xzf "$TMPFILE" -C "$REPO_DIR"; then
    echo "Extraction failed." >&2
    rm -f "$TMPFILE"
    exit 1
fi

rm -f "$TMPFILE"

# Ensure resulting directories are owned by pi
chown -R pi:pi "$REPO_DIR/books" 2>/dev/null || true
chown -R pi:pi "$REPO_DIR/games" 2>/dev/null || true

echo "Book and game resources installed."
exit 0
