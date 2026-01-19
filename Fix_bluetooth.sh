#!/bin/bash
set -e

echo "ES: Arreglo BLE para picochess (Raspberry Pi OS Trixie)"
echo "EN: Fix BLE for picochess (Raspberry Pi OS Trixie)"
echo "-------------------------------------------------"

step() {
  echo ""
  echo "ES: $1"
  echo "EN: $2"
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo ""
    echo "ES: Falta el comando requerido: $cmd"
    echo "EN: Missing required command: $cmd"
    exit 1
  fi
}

# Comprobar root / Check root
if [[ $EUID -ne 0 ]]; then
  echo ""
  echo "ES: Ejecuta este script con sudo"
  echo "EN: Run this script with sudo"
  exit 1
fi

require_cmd rfkill
require_cmd hciconfig
require_cmd setcap
require_cmd getcap
require_cmd systemctl
require_cmd usermod

PICOCHESS_VENV="/opt/picochess/venv"
BLUEPY_HELPER="$PICOCHESS_VENV/lib/python3.13/site-packages/bluepy/bluepy-helper"

step "Desbloqueando Bluetooth (rfkill)..." "Unblocking Bluetooth (rfkill)..."
rfkill unblock bluetooth || true

step "Subiendo interfaz Bluetooth hci0..." "Bringing up Bluetooth interface hci0..."
hciconfig hci0 up || true

step "Aplicando capacidades a bluepy-helper..." "Applying capabilities to bluepy-helper..."
if [[ -f "$BLUEPY_HELPER" ]]; then
  setcap 'cap_net_raw,cap_net_admin+eip' "$BLUEPY_HELPER"
else
  echo ""
  echo "ES: No se encuentra bluepy-helper en:"
  echo "EN: bluepy-helper not found at:"
  echo "   $BLUEPY_HELPER"
  exit 1
fi

step "Verificando capacidades..." "Verifying capabilities..."
getcap "$BLUEPY_HELPER"

step "Configurando bluetoothd en modo compatibilidad..." "Configuring bluetoothd in compatibility mode..."
BLUETOOTHD_PATH=""
for candidate in /usr/libexec/bluetooth/bluetoothd /usr/sbin/bluetoothd /usr/lib/bluetooth/bluetoothd; do
  if [[ -x "$candidate" ]]; then
    BLUETOOTHD_PATH="$candidate"
    break
  fi
done
if [[ -z "$BLUETOOTHD_PATH" ]]; then
  echo ""
  echo "ES: No se encontro bluetoothd en rutas conocidas."
  echo "EN: bluetoothd not found in known paths."
  exit 1
fi

mkdir -p /etc/systemd/system/bluetooth.service.d

cat > /etc/systemd/system/bluetooth.service.d/override.conf << EOF
[Service]
ExecStart=
ExecStart=${BLUETOOTHD_PATH} --compat
EOF

step "Borrando chessnut_config.json si existe..." "Deleting chessnut_config.json if it exists..."
if [[ -f /opt/picochess/chessnut_config.json ]]; then
  rm -f /opt/picochess/chessnut_config.json
fi

step "Borrando /var/lib/bluetooth si existe..." "Deleting /var/lib/bluetooth if it exists..."
if [[ -d /var/lib/bluetooth ]]; then
  rm -rf /var/lib/bluetooth
fi

step "Reiniciando servicios Bluetooth..." "Restarting Bluetooth services..."
systemctl daemon-reexec
systemctl restart bluetooth

step "Anadiendo usuario actual a grupos bluetooth y netdev..." "Adding current user to bluetooth and netdev groups..."
usermod -aG bluetooth,netdev "${SUDO_USER:-$USER}"

echo ""
echo "ES: Configuracion completada."
echo "EN: Configuration completed."
echo "ES: Es RECOMENDABLE reiniciar:"
echo "EN: It is RECOMMENDED to reboot:"
echo "    sudo reboot"
