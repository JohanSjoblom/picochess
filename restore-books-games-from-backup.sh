#!/bin/sh
# restore-books-games-from-backup.sh – Restore book/game resources from backup
# Run as user pi. Complements move-books-games-to-backup.sh.
#

REPO_DIR=${REPO_DIR:-/opt/picochess}
BOOKS_DIR="$REPO_DIR/books"
GAMES_DIR="$REPO_DIR/gamesdb"

BACKUP_DIR_BASE="/home/pi/pico_backups"
BACKUP_DIR="$BACKUP_DIR_BASE/current/books_games_backup"

if [ ! -d "$REPO_DIR" ]; then
    echo "Repository directory $REPO_DIR not found. Aborting." >&2
    exit 1
fi

if [ ! -d "$BACKUP_DIR" ]; then
    echo "Backup directory $BACKUP_DIR not found. Nothing to restore." >&2
    exit 1
fi

restore_dir() {
    SRC="$1"
    DST="$2"
    NAME="$3"

    if [ -d "$SRC" ]; then
        rm -rf "$DST"
        mv "$SRC" "$DST" || {
            echo "Error: Failed to restore $NAME directory." >&2
            return 1
        }
        chown -R pi:pi "$DST" 2>/dev/null || true
        echo "Restored $NAME directory."
    else
        echo "No $NAME directory in backup – skipping."
    fi
    return 0
}

restore_dir "$BACKUP_DIR/books" "$BOOKS_DIR" "books" || exit 1
restore_dir "$BACKUP_DIR/gamesdb" "$GAMES_DIR" "gamesdb" || exit 1

echo "Books and games restored to $REPO_DIR."
exit 0
