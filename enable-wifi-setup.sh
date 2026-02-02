#!/bin/sh
set -eu

USER_NAME="${SUDO_USER:-$(id -un)}"
SUDOERS_FILE="/etc/sudoers.d/picochess-nmcli"

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run with sudo: sudo ./enable-wifi-setup.sh"
  exit 1
fi

if [ ! -x /usr/bin/nmcli ]; then
  echo "nmcli not found at /usr/bin/nmcli"
  exit 1
fi

echo "${USER_NAME} ALL=NOPASSWD: /usr/bin/nmcli" > "${SUDOERS_FILE}"
chmod 0440 "${SUDOERS_FILE}"

if visudo -cf "${SUDOERS_FILE}" >/dev/null 2>&1; then
  echo "Wi-Fi setup enabled for user ${USER_NAME}"
  exit 0
fi

echo "sudoers validation failed, removing ${SUDOERS_FILE}"
rm -f "${SUDOERS_FILE}"
exit 1
