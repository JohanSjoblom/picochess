#!/bin/sh
# install-books-games.sh – Download and install opening books and game resources
# POSIX-compliant; intended to run as user pi (no sudo).
# Draft version with placeholder asset URLs for future release v4.1.9.
#

REPO_DIR=${REPO_DIR:-/opt/picochess}
TMP_DIR="${HOME}/pico_backups/current/tmp"

if [ ! -d "$REPO_DIR" ]; then
    echo "Repository directory $REPO_DIR not found. Aborting." >&2
    exit 1
fi

mkdir -p "$TMP_DIR" || exit 1

BOOKS_ARCHIVE="books.tar.gz"
GAMES_ARCHIVE="gamesdb.tar.gz"
BOOKS_URL="https://github.com/JohanSjoblom/picochess/releases/download/v4.1.9/${BOOKS_ARCHIVE}"
GAMES_URL="https://github.com/JohanSjoblom/picochess/releases/download/v4.1.9/${GAMES_ARCHIVE}"
BOOKS_TMP="$TMP_DIR/$BOOKS_ARCHIVE"
GAMES_TMP="$TMP_DIR/$GAMES_ARCHIVE"

download_asset() {
    URL=$1
    DEST=$2
    if command -v curl >/dev/null 2>&1; then
        curl -L -o "$DEST" "$URL" || return 1
    elif command -v wget >/dev/null 2>&1; then
        wget -O "$DEST" "$URL" || return 1
    else
        echo "Error: need curl or wget to download assets." >&2
        return 1
    fi
    return 0
}

extract_asset() {
    TARFILE=$1
    TARGET_DIR=$2
    if ! tar -xzf "$TARFILE" -C "$TARGET_DIR"; then
        echo "Extraction failed for $TARFILE" >&2
        rm -f "$TARFILE"
        return 1
    fi
    rm -f "$TARFILE"
    return 0
}

if [ -d "$REPO_DIR/books" ]; then
    echo "Books directory already exists - skipping download."
else
    echo "Downloading opening books archive..."
    download_asset "$BOOKS_URL" "$BOOKS_TMP" || exit 1
    echo "Extracting opening books into $REPO_DIR/books..."
    mkdir -p "$REPO_DIR/books" || exit 1
    extract_asset "$BOOKS_TMP" "$REPO_DIR/books" || exit 1
fi

if [ -d "$REPO_DIR/gamesdb" ]; then
    echo "Gamesdb directory already exists - skipping download."
else
    echo "Downloading games archive..."
    download_asset "$GAMES_URL" "$GAMES_TMP" || exit 1
    echo "Extracting games into $REPO_DIR/gamesdb..."
    mkdir -p "$REPO_DIR/gamesdb" || exit 1
    extract_asset "$GAMES_TMP" "$REPO_DIR/gamesdb" || exit 1
fi

# Ensure correct tcscid binary is selected for this architecture
if [ -d "$REPO_DIR/gamesdb" ]; then
    ARCH=$(uname -m)
    TCSCID_SRC="$REPO_DIR/gamesdb/$ARCH/tcscid"
    TCSCID_LINK="$REPO_DIR/gamesdb/tcscid"
    if [ -f "$TCSCID_SRC" ]; then
        ln -sf "$TCSCID_SRC" "$TCSCID_LINK"
    else
        echo "Warning: tcscid binary for arch '$ARCH' not found in gamesdb." >&2
    fi
fi

# Ensure resulting directories are owned by pi
chown -R pi:pi "$REPO_DIR/books" 2>/dev/null || true
chown -R pi:pi "$REPO_DIR/gamesdb" 2>/dev/null || true

echo "Book and game resources installed."
exit 0
