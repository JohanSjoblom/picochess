#!/bin/sh
#
# Installation script for DGTPi clock and DGT3000 mod
# Run install-picochess first to install base picochess
#
# you also need to set dgtpi = True in ini file - use with care, know what you are doing
# you can use the example ini file picochess.ini.example-dgtpi3-clock
REPO_DIR="/opt/picochess"

if [ ! -d "$REPO_DIR" ]; then
    echo "Error: $REPO_DIR not found. Run install-picochess.sh first." >&2
    exit 1
fi

echo "setting up dgtpi service for hardwired clock like DGTPi"
cd "$REPO_DIR" || exit 1
if [ ! -f "$REPO_DIR/picochess.ini" ]; then
    if [ -f "$REPO_DIR/picochess.ini.example-dgtpi-clock" ]; then
        cp "$REPO_DIR/picochess.ini.example-dgtpi-clock" "$REPO_DIR/picochess.ini"
        if [ -n "$SUDO_USER" ]; then
            chown "$SUDO_USER:$SUDO_USER" "$REPO_DIR/picochess.ini"
        fi
        echo "Created picochess.ini from picochess.ini.example-dgtpi-clock"
    else
        echo "Warning: picochess.ini.example-dgtpi-clock not found; picochess.ini not created" >&2
    fi
fi
ln -sf "$REPO_DIR/etc/$(uname -m)/dgtpicom" "$REPO_DIR/etc/dgtpicom"
ln -sf "$REPO_DIR/etc/$(uname -m)/dgtpicom.so" "$REPO_DIR/etc/dgtpicom.so"
cp etc/dgtpi.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable dgtpi.service

echo "no setcap rights used in this script, they are all in install-picochess.sh"
echo "setcap not needed as no system update done here"

echo " ------- "
echo "DGTPi clock installation complete. Please reboot"
echo "If picochess.ini was missing, it was created from picochess.ini.example-dgtpi-clock"
echo "Otherwise, update picochess.ini with dgt clock setting dgtpi = True"
echo "NOTE: dgtpi = True setting should be used with care, only for DGTPi clocks"
echo "In case of problems have a look in the log $REPO_DIR/logs/picochess.log"
