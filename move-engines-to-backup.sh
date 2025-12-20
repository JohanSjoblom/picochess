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
# Run this script as a normal user (not as root).
# Use it to prepare for installing the latest engines:
#
# 1. Move your existing engines to the backup folder:
#      > ./move-engines-to-backup.sh
#
# 2. Then run the main installer to re-install the latest engines:
#      > ./install-picochess.sh
###############################################################################


ARCH=$(uname -m)
REPO_DIR=${REPO_DIR:-/opt/picochess}
SRC_DIR="$REPO_DIR/engines"

if [ ! -d "$REPO_DIR" ]; then
    echo "Repository directory $REPO_DIR not found. Aborting." >&2
    exit 1
fi

INSTALL_USER="${SUDO_USER:-${USER:-}}"
if [ -z "$INSTALL_USER" ] || [ "$INSTALL_USER" = "root" ]; then
    INSTALL_USER=$(logname 2>/dev/null || true)
fi
if [ -z "$INSTALL_USER" ] || [ "$INSTALL_USER" = "root" ]; then
    INSTALL_USER=$(id -un 2>/dev/null || true)
fi
if [ -z "$INSTALL_USER" ] || [ "$INSTALL_USER" = "root" ]; then
    if getent passwd pi >/dev/null 2>&1; then
        INSTALL_USER="pi"
        echo "Warning: using fallback install user 'pi'." >&2
    else
        echo "Error: could not determine non-root install user. Set INSTALL_USER and retry." >&2
        exit 1
    fi
fi
INSTALL_USER_HOME=${HOME:-$(getent passwd "$INSTALL_USER" | cut -d: -f6)}
if [ -z "$INSTALL_USER_HOME" ]; then
    echo "Error: could not determine home directory for $INSTALL_USER." >&2
    exit 1
fi
BACKUP_DIR_BASE="$INSTALL_USER_HOME/pico_backups"
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

# Move mame_emulation
for extra_dir in mame_emulation rodent3 rodent4; do
    if [ -d "$SRC_DIR/$extra_dir" ]; then
        echo "Moving $SRC_DIR/$extra_dir to $ENGINES_BACKUP_DIR/$extra_dir ..."
        rm -rf "$ENGINES_BACKUP_DIR/$extra_dir"
        mv "$SRC_DIR/$extra_dir" "$ENGINES_BACKUP_DIR/$extra_dir" || {
            echo "Error: Failed to move $SRC_DIR/$extra_dir" >&2
            exit 1
        }
    else
        echo "No $extra_dir directory found — skipping."
    fi
done

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

# Move script engines bundle if present
if [ -d "$SRC_DIR/script_engines" ]; then
    echo "Moving $SRC_DIR/script_engines to $ENGINES_BACKUP_DIR/script_engines ..."
    rm -rf "$ENGINES_BACKUP_DIR/script_engines"
    mv "$SRC_DIR/script_engines" "$ENGINES_BACKUP_DIR/script_engines" || {
        echo "Error: Failed to move script_engines" >&2
        exit 1
    }
else
    echo "No script_engines directory found — skipping."
fi

# Move pgn_audio files (downloaded under pgn_engine) if present
if [ -d "$SRC_DIR/pgn_engine/pgn_audio" ]; then
    echo "Moving $SRC_DIR/pgn_engine/pgn_audio to $ENGINES_BACKUP_DIR/pgn_engine/pgn_audio ..."
    rm -rf "$ENGINES_BACKUP_DIR/pgn_engine/pgn_audio"
    mkdir -p "$ENGINES_BACKUP_DIR/pgn_engine" || {
        echo "Error: Failed to create backup directory for pgn_engine" >&2
        exit 1
    }
    mv "$SRC_DIR/pgn_engine/pgn_audio" "$ENGINES_BACKUP_DIR/pgn_engine/pgn_audio" || {
        echo "Error: Failed to move pgn_engine/pgn_audio" >&2
        exit 1
    }
else
    echo "No pgn_engine/pgn_audio directory found — skipping."
fi

# Final ownership fix (optional but consistent)
chown -R "$INSTALL_USER:$INSTALL_USER" "$ENGINES_BACKUP_DIR"

echo "---------------------------------------------"
echo " Engine directories moved successfully."
echo " They are now stored in: $ENGINES_BACKUP_DIR"
echo "---------------------------------------------"
exit 0
