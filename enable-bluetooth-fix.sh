#!/bin/sh
set -eu

USER_NAME="${SUDO_USER:-$(id -un)}"
SUDOERS_FILE="/etc/sudoers.d/picochess-bluetooth-fix"
SCRIPT_PATH="/opt/picochess/Fix_bluetooth.sh"

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run with sudo: sudo ./enable-bluetooth-fix.sh"
  exit 1
fi

if [ ! -x "${SCRIPT_PATH}" ]; then
  echo "Fix_bluetooth.sh not found or not executable at ${SCRIPT_PATH}"
  exit 1
fi

echo "${USER_NAME} ALL=NOPASSWD: ${SCRIPT_PATH}" > "${SUDOERS_FILE}"
chmod 0440 "${SUDOERS_FILE}"

if visudo -cf "${SUDOERS_FILE}" >/dev/null 2>&1; then
  echo "Bluetooth fix enabled for user ${USER_NAME}"
  exit 0
fi

echo "sudoers validation failed, removing ${SUDOERS_FILE}"
rm -f "${SUDOERS_FILE}"
exit 1
