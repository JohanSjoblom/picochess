#!/bin/sh
set -eu

OUT_FILE="bluetooth.txt"
FULL=0
NO_MASK=0

if [ "${1:-}" = "--full" ]; then
    FULL=1
elif [ "${1:-}" = "--no-mask" ]; then
    NO_MASK=1
fi

mask_macs() {
    if [ "$NO_MASK" -eq 1 ]; then
        cat
        return
    fi
    sed -E 's/([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}/XX:XX:XX:XX:XX:XX/g'
}

echo "Writing Bluetooth diagnostics to $OUT_FILE"

{
    echo "=== Picochess Bluetooth diagnostics ==="
    echo "Note: MAC addresses are masked. Use --no-mask to disable masking."
    echo "Note: Use --full to include bluetooth journal logs."
    echo "Timestamp: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo ""

    echo "-- OS release --"
    if [ -f /etc/os-release ]; then
        cat /etc/os-release
    else
        echo "Missing /etc/os-release"
    fi
    echo ""

    echo "-- Kernel --"
    uname -a || true
    echo ""

    echo "-- Architecture --"
    uname -m || true
    echo ""

    echo "-- Bluetoothctl version --"
    if command -v bluetoothctl >/dev/null 2>&1; then
        bluetoothctl --version || true
    else
        echo "bluetoothctl not found"
    fi
    echo ""

    echo "-- Bluetooth service status --"
    if command -v systemctl >/dev/null 2>&1; then
        systemctl status bluetooth --no-pager || true
    else
        echo "systemctl not found"
    fi
    echo ""

    if [ "$FULL" -eq 1 ]; then
        echo "-- Bluetooth service logs (tail) --"
        if command -v journalctl >/dev/null 2>&1; then
            journalctl -u bluetooth -b --no-pager | tail -n 200 | mask_macs || true
        else
            echo "journalctl not found"
        fi
        echo ""
    fi

    echo "-- rfkill --"
    if command -v rfkill >/dev/null 2>&1; then
        rfkill list || true
    else
        echo "rfkill not found"
    fi
    echo ""

    echo "-- hciconfig --"
    if command -v hciconfig >/dev/null 2>&1; then
        hciconfig -a | mask_macs || true
    else
        echo "hciconfig not found"
    fi
    echo ""

    echo "-- btmgmt info --"
    if command -v btmgmt >/dev/null 2>&1; then
        btmgmt info | mask_macs || true
    else
        echo "btmgmt not found"
    fi
    echo ""

    echo "-- boot config (UART/Bluetooth) --"
    if [ -f /boot/firmware/config.txt ]; then
        echo "File: /boot/firmware/config.txt"
        grep -n "uart\|serial\|bluetooth\|pi3" /boot/firmware/config.txt || true
    elif [ -f /boot/config.txt ]; then
        echo "File: /boot/config.txt"
        grep -n "uart\|serial\|bluetooth\|pi3" /boot/config.txt || true
    else
        echo "No /boot/firmware/config.txt or /boot/config.txt found"
    fi
    echo ""

    echo "-- bluepy helper capabilities --"
    if command -v getcap >/dev/null 2>&1; then
        for helper in /opt/picochess/venv/lib/python*/site-packages/bluepy/bluepy-helper; do
            if [ -f "$helper" ]; then
                echo "Path: $helper"
                getcap "$helper" || true
            fi
        done
    else
        echo "getcap not found"
    fi
    echo ""

    echo "-- venv python capabilities --"
    if command -v getcap >/dev/null 2>&1; then
        if [ -x /opt/picochess/venv/bin/python ]; then
            getcap /opt/picochess/venv/bin/python || true
        else
            echo "/opt/picochess/venv/bin/python not found"
        fi
    else
        echo "getcap not found"
    fi
    echo ""

    echo "-- Picochess ini board type --"
    if [ -f /opt/picochess/picochess.ini ]; then
        grep -n "^board-type" /opt/picochess/picochess.ini || true
    else
        echo "/opt/picochess/picochess.ini not found"
    fi
    echo ""
} > "$OUT_FILE"

echo "Done."
