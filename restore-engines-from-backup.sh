#!/bin/sh
# restore-engines-from-backup.sh - Restore engine directories from backup
# POSIX-compliant companion to move-engines-to-backup.sh
#
# Run this as pi user - not root
#

BACKUP_ROOT="/home/pi/pico_backups/current/engines_backup"
DEFAULT_ARCH=$(uname -m)
REPO_DIR=${REPO_DIR:-/opt/picochess}

if [ ! -d "$REPO_DIR" ]; then
    echo "Repository directory $REPO_DIR does not exist." 1>&2
    exit 1
fi

usage() {
    echo "Usage: $0 {arch [ARCH]|lc0|mame|rodent3|rodent4|all [ARCH]}" 1>&2
    exit 1
}

restore_arch() {
    ARCH_NAME=$1
    if [ -z "$ARCH_NAME" ]; then
        ARCH_NAME=$DEFAULT_ARCH
    fi

    if [ -d "$BACKUP_ROOT/$ARCH_NAME" ]; then
        echo "Restoring engines/$ARCH_NAME from backup..."
        rm -rf "$REPO_DIR/engines/$ARCH_NAME"
        mkdir -p "$REPO_DIR/engines" || exit 1
        cp -R "$BACKUP_ROOT/$ARCH_NAME" "$REPO_DIR/engines/" || exit 1
    else
        echo "No backup available for engines/$ARCH_NAME" 1>&2
        return 1
    fi
}

restore_lc0() {
    if [ -d "$BACKUP_ROOT/lc0_weights" ]; then
        echo "Restoring engines/lc0_weights from backup..."
        rm -rf "$REPO_DIR/engines/lc0_weights"
        mkdir -p "$REPO_DIR/engines" || exit 1
        cp -R "$BACKUP_ROOT/lc0_weights" "$REPO_DIR/engines/" || exit 1
    else
        echo "No backup available for engines/lc0_weights" 1>&2
        return 1
    fi
}

restore_mame() {
    if [ -d "$BACKUP_ROOT/mame_emulation" ]; then
        echo "Restoring engines/mame_emulation from backup..."
        rm -rf "$REPO_DIR/engines/mame_emulation"
        mkdir -p "$REPO_DIR/engines" || exit 1
        cp -R "$BACKUP_ROOT/mame_emulation" "$REPO_DIR/engines/" || exit 1
    else
        echo "No backup available for engines/mame_emulation" 1>&2
        return 1
    fi
}

restore_rodent3() {
    if [ -d "$BACKUP_ROOT/rodent3" ]; then
        echo "Restoring engines/rodent3 from backup..."
        rm -rf "$REPO_DIR/engines/rodent3"
        mkdir -p "$REPO_DIR/engines" || exit 1
        cp -R "$BACKUP_ROOT/rodent3" "$REPO_DIR/engines/" || exit 1
    else
        echo "No backup available for engines/rodent3" 1>&2
        return 1
    fi
}

restore_rodent4() {
    if [ -d "$BACKUP_ROOT/rodent4" ]; then
        echo "Restoring engines/rodent4 from backup..."
        rm -rf "$REPO_DIR/engines/rodent4"
        mkdir -p "$REPO_DIR/engines" || exit 1
        cp -R "$BACKUP_ROOT/rodent4" "$REPO_DIR/engines/" || exit 1
    else
        echo "No backup available for engines/rodent4" 1>&2
        return 1
    fi
}

if [ $# -eq 0 ]; then
    ACTION="all"
else
    ACTION=$1
    shift
fi

case $ACTION in
    arch)
        ARCH_VALUE=$1
        restore_arch "$ARCH_VALUE" || exit 1
        ;;
    lc0)
        restore_lc0 || exit 1
        ;;
    mame)
        restore_mame || exit 1
        ;;
    rodent3)
        restore_rodent3 || exit 1
        ;;
    rodent4)
        restore_rodent4 || exit 1
        ;;
    all)
        ARCH_VALUE=$1
        STATUS=0
        restore_arch "$ARCH_VALUE" || STATUS=1
        restore_lc0 || STATUS=1
        restore_mame || STATUS=1
        restore_rodent3 || STATUS=1
        restore_rodent4 || STATUS=1
        exit $STATUS
        ;;
    *)
        usage
        ;;
esac

exit 0
