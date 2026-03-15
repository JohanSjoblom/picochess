#!/bin/sh
#
# Install ydotool and configure user access
# Run this script as root (sudo)
#

set -e

BACKPORTS_LIST="/etc/apt/sources.list.d/trixie-backports.list"
INSTALL_USER="${SUDO_USER:-${USER:-}}"
YDOTOOL_INSTALLED=false
YDOTOOL_RELOGIN_REQUIRED=false

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: run this script as root (sudo)." >&2
    exit 1
fi

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

get_codename() {
    if [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        if [ -n "${VERSION_CODENAME:-}" ]; then
            printf '%s\n' "$VERSION_CODENAME"
            return 0
        fi
    fi

    if command -v lsb_release >/dev/null 2>&1; then
        lsb_release -sc
        return 0
    fi

    return 1
}

has_trixie_backports_source() {
    grep -Rqs '^[[:space:]]*deb[[:space:]].*trixie-backports' \
        /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null || \
    grep -Rqs '^[[:space:]]*Suites:[[:space:]].*trixie-backports' \
        /etc/apt/sources.list.d 2>/dev/null
}

ensure_trixie_backports() {
    codename=$(get_codename || true)

    if [ "$codename" != "trixie" ]; then
        echo "Not running Trixie, skipping trixie-backports setup."
        return 0
    fi

    if has_trixie_backports_source; then
        echo "trixie-backports is already configured."
        return 0
    fi

    echo "Adding trixie-backports apt source..."
    printf '%s\n' "deb http://deb.debian.org/debian trixie-backports main" > "$BACKPORTS_LIST"

    echo "Updating apt package lists..."
    apt-get update
}

install_ydotool() {
    codename=$(get_codename || true)

    if command -v ydotool >/dev/null 2>&1 && command -v ydotoold >/dev/null 2>&1; then
        YDOTOOL_INSTALLED=true
        echo "ydotool and ydotoold already available on PATH."
        return 0
    fi

    if [ "$codename" = "trixie" ]; then
        ensure_trixie_backports
        echo "Installing ydotool from trixie-backports..."
        apt-get install -y -t trixie-backports ydotool
    else
        echo "Installing ydotool from default repositories..."
        apt-get install -y ydotool
    fi

    YDOTOOL_INSTALLED=true
}

configure_ydotool() {
    if [ "$YDOTOOL_INSTALLED" != true ]; then
        return 0
    fi

    echo "Configuring ydotool for install user '$INSTALL_USER'..."

    if getent group input >/dev/null 2>&1; then
        case " $(id -nG "$INSTALL_USER" 2>/dev/null) " in
            *" input "*) ;;
            *)
                usermod -aG input "$INSTALL_USER"
                YDOTOOL_RELOGIN_REQUIRED=true
                ;;
        esac
    else
        echo "Warning: group 'input' not found; ydotool may not be able to access /dev/uinput." >&2
    fi

    YDOTOOL_SERVICE_FILE=""
    if [ -f /usr/lib/systemd/user/ydotool.service ]; then
        YDOTOOL_SERVICE_FILE=/usr/lib/systemd/user/ydotool.service
    elif [ -f /lib/systemd/user/ydotool.service ]; then
        YDOTOOL_SERVICE_FILE=/lib/systemd/user/ydotool.service
    fi

    if [ -n "$YDOTOOL_SERVICE_FILE" ]; then
        sudo -u "$INSTALL_USER" mkdir -p "$INSTALL_USER_HOME/.config/systemd/user/default.target.wants"
        sudo -u "$INSTALL_USER" ln -sf \
            "$YDOTOOL_SERVICE_FILE" \
            "$INSTALL_USER_HOME/.config/systemd/user/default.target.wants/ydotool.service"
    else
        echo "Warning: ydotool.service not found; installed ydotool without enabling its user service." >&2
    fi
}

install_ydotool
configure_ydotool

echo "ydotool installation complete."
if [ "$YDOTOOL_RELOGIN_REQUIRED" = true ]; then
    echo "Please reboot or log out/in so user '$INSTALL_USER' picks up the new input-group membership."
fi
