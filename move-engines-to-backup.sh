#!/bin/bash
###############################################################################
# move-engines-to-backup.sh
# --------------------------
# Moves current engine directories (engines/$ARCH and engines/lc0_weights)
# from the Picochess repository to the backup folder.
#
# Used when preparing for a fresh engine installation.
# Compatible with install-picochess.sh backup layout.
###############################################################################
# Run this script as the 'pi' user (not as root).
# Use it to prepare for installing the latest engines:
#
# 1. Move your existing engines to the backup folder:
#      > ./move-engines-to-backup.sh
#
# 2. Then run the main installer to re-install the latest engines:
#      > ./install-picochess.sh
###############################################################################


ARCH=$(uname -m)
REPO_DIR="/opt/picochess"
SRC_DIR="$REPO_DIR/engines"

BACKUP_DIR_BASE="/home/pi/pico_backups"
BACKUP_DIR="$BACKUP_DIR_BASE/current"
ENGINES_BACKUP_DIR="$BACKUP_DIR/engines_backup"

echo "---------------------------------------------"
echo " Moving PicoChess engine files to backup ..."
echo " Architecture: $ARCH"
echo " Source: $SRC_DIR"
echo " Backup: $ENGINES_BACKUP_DIR"
echo "---------------------------------------------"

# Ensure destination exists
mkdir -p "$ENGINES_BACKUP_DIR" || {
    echo "Error: Failed to create backup directory $ENGINES_BACKUP_DIR" >&2
    exit 1
}

# Move architecture-specific engines
if [ -d "$SRC_DIR/$ARCH" ]; then
    echo "Moving $SRC_DIR/$ARCH to $ENGINES_BACKUP_DIR/$ARCH ..."
    rm -rf "$ENGINES_BACKUP_DIR/$ARCH"
    mv "$SRC_DIR/$ARCH" "$ENGINES_BACKUP_DIR/$ARCH" || {
        echo "Error: Failed to move $SRC_DIR/$ARCH" >&2
        exit 1
    }
else
    echo "No $ARCH engine directory found — skipping."
fi

# Move LC0 weights if present
if [ -d "$SRC_DIR/lc0_weights" ]; then
    echo "Moving $SRC_DIR/lc0_weights to $ENGINES_BACKUP_DIR/lc0_weights ..."
    rm -rf "$ENGINES_BACKUP_DIR/lc0_weights"
    mv "$SRC_DIR/lc0_weights" "$ENGINES_BACKUP_DIR/lc0_weights" || {
        echo "Error: Failed to move lc0_weights" >&2
        exit 1
    }
else
    echo "No lc0_weights directory found — skipping."
fi

# Final ownership fix (optional but consistent)
chown -R pi:pi "$ENGINES_BACKUP_DIR"

echo "---------------------------------------------"
echo " Engine directories moved successfully."
echo " They are now stored in: $ENGINES_BACKUP_DIR"
echo "---------------------------------------------"
exit 0