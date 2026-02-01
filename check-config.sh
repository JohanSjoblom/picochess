#!/bin/sh
set -eu

SCRIPT="/opt/picochess/check-config.py"
if [ ! -f "$SCRIPT" ]; then
    echo "ERROR: $SCRIPT not found"
    exit 2
fi

exec python3 "$SCRIPT" "$@"
