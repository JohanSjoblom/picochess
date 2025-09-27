#!/bin/sh
#
# check-update-status.sh
# POSIX shell script to display PicoChess updater status in short form
#

TIMESTAMP_FILE="/var/log/picochess-last-update"
FAIL_FILE="/var/log/picochess-last-update-fail"

# Check for failure first (failure overrides everything)
if [ -f "$FAIL_FILE" ]; then
    echo "upd: failed"
    exit 0
fi

# If no timestamp file exists, assume first run → 0d ago
if [ ! -f "$TIMESTAMP_FILE" ]; then
    echo "upd: 0d ago"
    exit 0
fi

# Compute days since last successful update
LAST_RUN=$(date -r "$TIMESTAMP_FILE" +%s 2>/dev/null || echo 0)
NOW=$(date +%s)
DIFF=$(( (NOW - LAST_RUN) / 86400 ))  # seconds → days

# Cap days at 999 and show 'long' if over
if [ "$DIFF" -gt 999 ]; then
    echo "upd: long ago"
else
    echo "upd: ${DIFF}d ago"
fi
exit 0
