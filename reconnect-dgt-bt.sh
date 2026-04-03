#!/bin/bash
# reconnect-dgt-bt.sh — Restore Bluetooth SPP connection to DGT board.
#
# Must run as root (via sudo -n).  Designed to be called from the
# picochess "Reconnect DGT" menu item after a reboot leaves the board
# blinking (no connection).
#
# Strategy:
#   1. Unblock BT hardware and bring up hci0.
#   2. Ensure bluetoothd runs with --compat (enables Serial Port Profile).
#   3. Restart the Bluetooth service so the flag takes effect.
#   4. Look up the already-paired DGT board MAC address.
#   5. Release any stale rfcomm123 device.
#   6. Re-establish rfcomm123 in the background; picochess will detect it.

set -e

if [[ $EUID -ne 0 ]]; then
    echo "EN: Run with sudo"
    exit 1
fi

echo "EN: Reconnecting DGT board via Bluetooth..."

# 1. Hardware
rfkill unblock bluetooth
hciconfig hci0 up 2>/dev/null || true

# 2. Ensure --compat override is present (enables SPP / br-connection profile)
OVERRIDE_DIR="/etc/systemd/system/bluetooth.service.d"
OVERRIDE_FILE="${OVERRIDE_DIR}/override.conf"
mkdir -p "${OVERRIDE_DIR}"

BLUETOOTHD_PATH=""
for candidate in /usr/libexec/bluetooth/bluetoothd /usr/sbin/bluetoothd /usr/lib/bluetooth/bluetoothd; do
    if [[ -x "$candidate" ]]; then
        BLUETOOTHD_PATH="$candidate"
        break
    fi
done

if [[ -z "$BLUETOOTHD_PATH" ]]; then
    echo "EN: bluetoothd not found — cannot enable --compat"
    exit 1
fi

if ! grep -q "\-\-compat" "${OVERRIDE_FILE}" 2>/dev/null; then
    cat > "${OVERRIDE_FILE}" << EOF
[Service]
ExecStart=
ExecStart=${BLUETOOTHD_PATH} --compat
EOF
    echo "EN: --compat override written"
fi

# 3. Restart Bluetooth service (clears any stuck bluetoothctl subprocesses)
systemctl daemon-reload
systemctl restart bluetooth
sleep 3

# 4. Find paired DGT board
MAC=$(bluetoothctl paired-devices 2>/dev/null \
      | grep -E "DGT_BT|PCS-REVII" \
      | awk '{print $2}' \
      | head -1)

if [[ -z "$MAC" ]]; then
    echo "EN: No prior DGT pairing found — picochess will scan and pair automatically."
else
    echo "EN: Found paired DGT board: ${MAC}"

    # 5. Release stale rfcomm device
    rfcomm release 123 2>/dev/null || true
    sleep 1

    # 6. Connect in background (rfcomm connect blocks until disconnected)
    nohup rfcomm connect 123 "${MAC}" 1 </dev/null >>/var/log/picochess-rfcomm.log 2>&1 &

    echo "EN: rfcomm connect started for ${MAC} — picochess will detect /dev/rfcomm123"
fi

echo "EN: Bluetooth service restarted with SPP support. Connection should be restored."
