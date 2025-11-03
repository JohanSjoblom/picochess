#!/bin/sh
# move-books-games-to-backup.sh – Move book and game resources to backup
# Run as user pi; mirrors move-engines-to-backup.sh but for books/games.
#

REPO_DIR=${REPO_DIR:-/opt/picochess}
BOOKS_DIR="$REPO_DIR/books"
GAMES_DIR="$REPO_DIR/games"

BACKUP_DIR_BASE="/home/pi/pico_backups"
BACKUP_DIR="$BACKUP_DIR_BASE/current"
BACKUP_TARGET="$BACKUP_DIR/books_games_backup"

if [ ! -d "$REPO_DIR" ]; then
    echo "Repository directory $REPO_DIR not found. Aborting." >&2
    exit 1
fi

mkdir -p "$BACKUP_TARGET" || {
    echo "Error: Failed to create backup directory $BACKUP_TARGET" >&2
    exit 1
}

echo "Backing up book resources..."
if [ -d "$BOOKS_DIR" ]; then
    rm -rf "$BACKUP_TARGET/books"
    mv "$BOOKS_DIR" "$BACKUP_TARGET/books" || {
        echo "Error: Failed to move books directory to backup." >&2
        exit 1
    }
else
    echo "No books directory found – skipping."
fi

echo "Backing up game resources..."
if [ -d "$GAMES_DIR" ]; then
    rm -rf "$BACKUP_TARGET/games"
    mv "$GAMES_DIR" "$BACKUP_TARGET/games" || {
        echo "Error: Failed to move games directory to backup." >&2
        exit 1
    }
else
    echo "No games directory found – skipping."
fi

chown -R pi:pi "$BACKUP_TARGET" 2>/dev/null || true

echo "Books and games moved to $BACKUP_TARGET."
exit 0
