#!/bin/sh

SERVICE="picochess-update.service"
TIMESTAMP_FILE="/var/log/picochess-last-update"

# 1. Check if last run failed
if systemctl is-failed --quiet "$SERVICE"; then
    echo "upd: failed"
    exit 0
fi

# 2. If no successful run ever
if [ ! -s "$TIMESTAMP_FILE" ]; then
    echo "upd: never"
    exit 0
fi

# 3. Calculate age in days
NOW=$(date +%s)
LAST_RUN=$(cat "$TIMESTAMP_FILE")
AGE=$(( (NOW - LAST_RUN) / 86400 ))

if [ "$AGE" -gt 999 ]; then
    echo "upd: long ago"
else
    echo "upd: ${AGE}d ago"
fi
exit 0
