#!/bin/sh
#
# Installation script for picochess
# Run this script as root (sudo)
#

# REPO_DIR must be set early and remember that the Python code has hardcoded /opt/picochess paths
# See install-picochess.md documentation for more info
REPO_DIR="/opt/picochess"
BRANCH="master"
BACKUP_DIR_BASE="/home/pi/pico_backups"
BACKUP_DIR="$BACKUP_DIR_BASE/current"
WORKING_COPY_DIR="$BACKUP_DIR/working_copy"
UNTRACKED_DIR="$BACKUP_DIR/untracked_files"

# Check for the "pico" parameter, if present skip system upgrade
SKIP_UPDATE=false
if [ "$1" = "pico" ]; then
    SKIP_UPDATE=true
fi

if [ "$SKIP_UPDATE" = false ]; then
    echo "starting by upgrading system before installing picochess"
    apt update && apt upgrade -y
else
    echo "Skipping system update because 'pico' parameter was given."
    echo "Updating Picochess but not system"
fi

#
# INSTALLING NEEDED SYSTEM LIBRARIES BEFORE BACKUP SECTION
#
echo " ------------------------- "
echo "installing needed libraries"
apt -y install git sox unzip wget libtcl8.6 telnet libglib2.0-dev
apt -y install avahi-daemon avahi-discover libnss-mdns
apt -y install vorbis-tools
apt -y install python3 python3-pip
apt -y install python3-dev
apt -y install python3-pyaudio portaudio19-dev
apt -y install python3-venv
apt -y install libffi-dev libssl-dev
apt -y install tk tcl libtcl8.6
# for mame_emulation we need
apt -y install xdotool
# following lines are for (building) and running leela-chess-zero
# apt -y install libopenblas-dev ninja-build meson
# added more tools for building lc0 0.32
# apt -y install build-essential cmake protobuf-compiler
# following line are to run mame (missing on lite images)
apt -y install libsdl2-2.0-0 libsdl2-ttf-2.0-0 qt5ct
# following needed for backup to work
apt -y install rsync
# following needed for pydub AudioSegment to work in PicoTalker
# apt -y install ffmpeg

# for backward compatibility with old installations where git was uses as root
# this is temporary and should be removed when testers have updated at least once
echo " --------------------------------------------------- "
echo "System updates done - Starting Picochess installation"
echo " --------------------------------------------------- "
if [ -d "$REPO_DIR" ]; then
    chown -R pi:pi "$REPO_DIR"
    sudo -u pi git config --global --add safe.directory "$REPO_DIR"
fi

# BACKUP section starts
###############################################################################
# Fast Incremental Backup & Git Reset Script for $REPO_DIR
# - Maintains a single backup in /home/pi/pico_backups/current
# - Uses rsync to copy only changed files
# - Excludes 'engines/' and 'mame/' from backup
# - Preserves untracked files outside excluded folders
###############################################################################

# Only attempt backup if $REPO_DIR exists
if [ -d "$REPO_DIR" ]; then
    cd "$REPO_DIR" || exit 1

    # Determine Git state
    CURRENT_BRANCH=$(sudo -u pi git rev-parse --abbrev-ref HEAD)
    DETACHED_TAG=$(sudo -u pi git describe --tags --exact-match 2>/dev/null)

    # Only do backup for master branch or detached tag
    if [ "$CURRENT_BRANCH" = "$BRANCH" ] || [ "$CURRENT_BRANCH" = "HEAD" ]; then
        echo "Starting backup (runs only for master branch or detached tag)..."

        # Create required directories
        mkdir -p "$WORKING_COPY_DIR" "$UNTRACKED_DIR"
        # Ensure backup directory is writable by pi
        chown pi:pi "$BACKUP_DIR_BASE"
        chown pi:pi "$BACKUP_DIR"
        echo "Creating backup in: $BACKUP_DIR"

        # === Save Git diff of local changes ===
        if [ -d "$REPO_DIR/.git" ]; then
            echo "Saving git diff..."
            sudo -u pi git diff > "$BACKUP_DIR/local_changes.diff"
            chown pi:pi "$BACKUP_DIR/local_changes.diff"

            # Save untracked files (excluding engines/)
            echo "Backing up untracked files..."
            rm -rf "$UNTRACKED_DIR"/*
            sudo -u pi git ls-files --others --exclude-standard | while read -r file; do
                case "$file" in
                    engines/aarch64/*|engines/x86_64/*|engines/lc0_weights/*|engines/mame_emulation/*) continue ;;
                esac
                mkdir -p "$UNTRACKED_DIR/$(dirname "$file")"
                cp -p "$file" "$UNTRACKED_DIR/$file"
            done
            chown pi:pi "$UNTRACKED_DIR"
        else
            echo "No Git repository found to backup. Doing only rsync of working directory."
        fi

        # Sync working copy excluding .git, engines/, and mame_emulation/
        cd "$REPO_DIR" || exit 1
        echo "Syncing working directory..."
        sudo -u pi rsync -a --delete --info=progress2 \
            --exclude='.git/' \
            --exclude='engines/aarch64/' \
            --exclude='engines/x86_64/' \
            --exclude='engines/lc0_weights/' \
            --exclude='engines/mame_emulation/' \
            ./ "$WORKING_COPY_DIR/"

        echo "Backup safely stored at: $BACKUP_DIR"

    else
        echo "Branch tester detected ('$CURRENT_BRANCH') — skipping backup to speed up update."
    fi
else
    echo "No $REPO_DIR directory found — skipping backup."
fi

# BACKUP section ends

# GIT UPDATE section starts
###############################################################################
echo " ------- "
if [ -d "$REPO_DIR/.git" ]; then
    cd "$REPO_DIR" || exit 1
    CURRENT_BRANCH=$(sudo -u pi git rev-parse --abbrev-ref HEAD)
    DETACHED_TAG=$(sudo -u pi git describe --tags --exact-match 2>/dev/null)

    if [ "$CURRENT_BRANCH" = "HEAD" ]; then
        if [ -n "$DETACHED_TAG" ]; then
            echo "Detached tag '$DETACHED_TAG' detected — forcing reset..."
            sudo -u pi git fetch --tags origin
            sudo -u pi git checkout "$DETACHED_TAG"
            sudo -u pi git reset --hard "$DETACHED_TAG"
        else
            echo "Detached HEAD without tag — no forced update."
        fi

    elif [ "$CURRENT_BRANCH" = "$BRANCH" ]; then
        echo "On master branch — forcing update to latest official version..."
        sudo -u pi git fetch origin
        sudo -u pi git reset --hard "origin/$BRANCH"

    else
        echo "On development branch '$CURRENT_BRANCH' — doing a safe pull..."
        sudo -u pi git fetch origin
        sudo -u pi git pull --no-rebase origin "$CURRENT_BRANCH" || {
            echo "WARNING: Git pull failed on branch '$CURRENT_BRANCH'. Check your local changes."
        }
    fi

else
    echo "No git repo found — fetching picochess... cloning using pi user"
    mkdir -p "$(dirname "$REPO_DIR")"
    chown pi:pi "$(dirname "$REPO_DIR")"
    sudo -u pi git clone https://github.com/JohanSjoblom/picochess "$REPO_DIR"
    cd "$REPO_DIR" || exit 1
fi
echo " ------- "
# GIT UPDATE section ends

# Upload directory
if [ -d "$REPO_DIR/games/uploads" ]; then
    echo "upload dir already exists - making sure pi is owner"
    chown -R pi:pi "$REPO_DIR/games/uploads"
else
    echo "creating uploads dir for pi user"
    sudo -u pi mkdir "$REPO_DIR/games/uploads"
fi

# install engines as user pi if there is no engines architecture folder
if [ -f install-engines.sh ]; then
    cd "$REPO_DIR" || exit 1
    chmod +x install-engines.sh 2>/dev/null
    sudo -u pi ./install-engines.sh small
else
    echo "install-engines.sh missing — cannot install engines."
fi

# Ensure engines folder belongs to pi (in case user ran install-engines with sudo)
if [ -d "$REPO_DIR/engines" ]; then
    echo "Fixing ownership for engines folder..."
    chown -R pi:pi "$REPO_DIR/engines" 2>/dev/null || true
fi

if [ -d "$REPO_DIR/logs" ]; then
    echo "logs dir already exists - making sure pi is owner"
    chown -R pi:pi "$REPO_DIR/logs"
else
    echo "creating logs dir for pi user"
    sudo -u pi mkdir "$REPO_DIR/logs"
fi

echo " ------- "
if [ -d "$REPO_DIR/venv" ]; then
    echo "venv already exists - making sure pi is owner and group"
    chown -R pi "$REPO_DIR/venv"
    chgrp -R pi "$REPO_DIR/venv"
else
    echo "creating virtual Python env named venv"
    sudo -u pi python3 -m venv "$REPO_DIR/venv"
fi

# picochess.ini
if [ -f "$REPO_DIR/picochess.ini" ]; then
    echo "picochess.ini already existed - no changes done"
else
    cd "$REPO_DIR"
    cp picochess.ini.example-web-$(uname -m) picochess.ini
    chown pi picochess.ini
fi

# no copying of example engines.ini - they are in resource files

# initialize other ini files like voices.ini... etc
# copy in the default files - ini files should not be in repository
if [ -f "$REPO_DIR/talker/voices/voices.ini" ]; then
    echo "voices.ini already existed - no changes done"
else
    cd "$REPO_DIR"
    cp voices-example.ini "$REPO_DIR/talker/voices/voices.ini"
    chown pi "$REPO_DIR/talker/voices/voices.ini"
fi

# Python module check
echo " ------- "
echo "checking required python modules..."
cd "$REPO_DIR"
sudo -u pi "$REPO_DIR/venv/bin/pip3" install --upgrade pip
sudo -u pi "$REPO_DIR/venv/bin/pip3" install --upgrade -r requirements.txt

echo " ------- "
echo "setting up picochess, obooksrv, gamesdb, and update services"
cp etc/picochess.service /etc/systemd/system/
ln -sf "$REPO_DIR/obooksrv/$(uname -m)/obooksrv" "$REPO_DIR/obooksrv/obooksrv"
cp etc/obooksrv.service /etc/systemd/system/
ln -sf "$REPO_DIR/gamesdb/$(uname -m)/tcscid" "$REPO_DIR/gamesdb/tcscid"
cp etc/gamesdb.service /etc/systemd/system/
cp etc/picochess-update.service /etc/systemd/system/
cp etc/run-picochess-if-flagged.sh /usr/local/bin/
chmod +x /usr/local/bin/run-picochess-if-flagged.sh
# output of these util scripts are used directly in the update python code
# but developers can also use them as utilities from command line
chmod +x "$REPO_DIR/check-update-status.sh"
chmod +x "$REPO_DIR/check-git-status.sh"
chmod +x "$REPO_DIR/check-git-tags.sh"
chmod +x "$REPO_DIR/move-engines-to-backup.sh"
chmod +x "$REPO_DIR/restore-engines-from-backup.sh"
# script to help check if feature branches have added or reduced pylint errors/warnings
# see pylint-check.sh for more info
chmod +x "$REPO_DIR/pylint-check.sh"
touch /var/log/picochess-update.log /var/log/picochess-last-update
chown root:root /var/log/picochess-*
systemctl daemon-reload
systemctl enable picochess.service
systemctl enable obooksrv.service
systemctl enable gamesdb.service
systemctl enable picochess-update.service

# setcap for DGT board, bluetooth etc
echo " ------- setcap start ------- "
echo "after each system update we need to rerun the cap_net rights"
echo "giving bluetooth rights so that communication works to DGT board etc"
# dynamically detect the Python binary in the venv
VENV_PYTHON=$(readlink -f "$REPO_DIR/venv/bin/python")
echo "Debug: Using venv python at $VENV_PYTHON"
# get python version string like python3.13
PYVER=$($VENV_PYTHON -c 'import sys; print("python%d.%d" % sys.version_info[:2])')
echo "Debug: Detected python version: $PYVER"
# construct the path to bluepy-helper dynamically
BLUEPY_HELPER="$REPO_DIR/venv/lib/$PYVER/site-packages/bluepy/bluepy-helper"
echo "Debug: Bluepy helper path: $BLUEPY_HELPER"
# apply capabilities if the helper exists
if [ -f "$BLUEPY_HELPER" ]; then
    setcap 'cap_net_raw,cap_net_admin+eip' "$BLUEPY_HELPER" || \
        echo "Warning: setcap failed for $BLUEPY_HELPER" >&2
else
    echo "Warning: $BLUEPY_HELPER not found, skipping setcap" >&2
fi
# apply capabilities to venv python, continue even if it fails
if [ -x "$VENV_PYTHON" ]; then
    setcap 'cap_sys_boot,cap_net_bind_service,cap_sys_rawio,cap_dac_override+eip' "$VENV_PYTHON" || \
        echo "Warning: setcap failed for $VENV_PYTHON" >&2
else
    echo "Warning: venv python $VENV_PYTHON not found or not executable" >&2
fi
echo " ------- setcap end ------- "

# backup folder ownership fix
echo "Fixing ownership for backup folders - in case user has run install-engines as sudo"
chown -R pi:pi "$BACKUP_DIR_BASE" 2>/dev/null || true

echo "Picochess installation complete. Please reboot"
echo "NOTE: If you are on DGTPi clock hardware you need to run install-dgtpi-clock.sh"
echo "After reboot open a browser to localhost"
echo "If you have a DGT board you need to change the board type"
echo "in the picochess.ini like this: board-type = dgt"
echo "Other board types are also supported - see the picochess.ini file"
echo " ------- "
echo "In case of problems have a look in the log $REPO_DIR/logs/picochess.log"
echo "You can rerun this installation whenever you want to update your system"
echo "Use the parameter pico if you want to skip system update"

exit 0
