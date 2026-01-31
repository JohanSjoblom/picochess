#!/bin/sh
#
# Install kiosk autostart and enable autologin for PicoChess
# Run this script as root (sudo)
#

set -e

REPO_DIR="/opt/picochess"
INSTALL_USER="${SUDO_USER:-${USER:-}}"
if [ -z "$INSTALL_USER" ] || [ "$INSTALL_USER" = "root" ]; then
    INSTALL_USER=$(logname 2>/dev/null || true)
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
INSTALL_USER_HOME=$(getent passwd "$INSTALL_USER" | cut -d: -f6)
if [ -z "$INSTALL_USER_HOME" ]; then
    echo "Error: could not determine home directory for $INSTALL_USER." >&2
    exit 1
fi

echo "Setting up kiosk autostart for user: $INSTALL_USER"

# Best-effort autologin (Raspberry Pi OS)
if command -v raspi-config >/dev/null 2>&1; then
    echo "Configuring autologin via raspi-config"
    raspi-config nonint do_boot_behaviour B4 || true
fi

# LightDM autologin
if [ -f /etc/lightdm/lightdm.conf ]; then
    echo "Configuring LightDM autologin"
    if ! grep -q "^\[Seat:\*\]" /etc/lightdm/lightdm.conf; then
        printf "\n[Seat:*]\n" >> /etc/lightdm/lightdm.conf
    fi
    if grep -q "^autologin-user=" /etc/lightdm/lightdm.conf; then
        sed -i "s/^autologin-user=.*/autologin-user=$INSTALL_USER/" /etc/lightdm/lightdm.conf
    else
        printf "autologin-user=%s\n" "$INSTALL_USER" >> /etc/lightdm/lightdm.conf
    fi
    if grep -q "^autologin-user-timeout=" /etc/lightdm/lightdm.conf; then
        sed -i "s/^autologin-user-timeout=.*/autologin-user-timeout=0/" /etc/lightdm/lightdm.conf
    else
        printf "autologin-user-timeout=0\n" >> /etc/lightdm/lightdm.conf
    fi
fi

# GDM3 autologin (Ubuntu)
for gdm_conf in /etc/gdm3/custom.conf /etc/gdm3/daemon.conf; do
    if [ -f "$gdm_conf" ]; then
        echo "Configuring GDM3 autologin in $gdm_conf"
        if ! grep -q "^\[daemon\]" "$gdm_conf"; then
            printf "\n[daemon]\n" >> "$gdm_conf"
        fi
        if grep -q "^AutomaticLoginEnable=" "$gdm_conf"; then
            sed -i "s/^AutomaticLoginEnable=.*/AutomaticLoginEnable=True/" "$gdm_conf"
        else
            printf "AutomaticLoginEnable=True\n" >> "$gdm_conf"
        fi
        if grep -q "^AutomaticLogin=" "$gdm_conf"; then
            sed -i "s/^AutomaticLogin=.*/AutomaticLogin=$INSTALL_USER/" "$gdm_conf"
        else
            printf "AutomaticLogin=%s\n" "$INSTALL_USER" >> "$gdm_conf"
        fi
        break
    fi
done

# Console autologin (fallback)
echo "Configuring getty autologin"
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $INSTALL_USER --noclear %I \$TERM
EOF

systemctl daemon-reload

# Kiosk autostart
AUTOSTART_DIR="$INSTALL_USER_HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
if [ -f "$REPO_DIR/etc/pico-kiosk.desktop" ]; then
    cp "$REPO_DIR/etc/pico-kiosk.desktop" "$AUTOSTART_DIR/pico-kiosk.desktop"
    sed -i "s|^Exec=.*|Exec=$INSTALL_USER_HOME/kiosk.sh|" "$AUTOSTART_DIR/pico-kiosk.desktop"
    chown "$INSTALL_USER:$INSTALL_USER" "$AUTOSTART_DIR/pico-kiosk.desktop"
else
    echo "Warning: $REPO_DIR/etc/pico-kiosk.desktop not found" >&2
fi

# Copy kiosk script into user home (allow user overrides)
if [ -f "$REPO_DIR/kiosk.sh" ]; then
    if [ -f "$INSTALL_USER_HOME/kiosk.sh" ]; then
        echo "kiosk.sh already exists in $INSTALL_USER_HOME - leaving it unchanged"
    else
        cp "$REPO_DIR/kiosk.sh" "$INSTALL_USER_HOME/kiosk.sh"
        chown "$INSTALL_USER:$INSTALL_USER" "$INSTALL_USER_HOME/kiosk.sh"
        chmod +x "$INSTALL_USER_HOME/kiosk.sh" 2>/dev/null || true
    fi
else
    echo "Warning: $REPO_DIR/kiosk.sh not found" >&2
fi

echo "Kiosk setup complete. Reboot to use autologin and kiosk autostart."
