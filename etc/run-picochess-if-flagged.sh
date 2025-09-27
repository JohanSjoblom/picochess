#!/bin/sh

FLAG="/home/pi/run_picochess_update.flag"
SCRIPT="/opt/picochess/install-picochess.sh"
LOGFILE="/var/log/picochess-update.log"
TIMESTAMP_FILE="/var/log/picochess-last-update"

# Create log file if it doesn't exist
touch "$LOGFILE"

# Check if the flag file exists
if [ -f "$FLAG" ]; then
    # Get current and last run time
    NOW=$(date +%s)
    LAST_RUN=$(cat "$TIMESTAMP_FILE" 2>/dev/null || echo 0)
    DIFF=$((NOW - LAST_RUN))

    # 10 min = 600 seconds, or if never run before (LAST_RUN=0)
    if [ "$DIFF" -ge 600 ] || [ "$LAST_RUN" -eq 0 ]; then
        echo "$(date): Running PicoChess update..." | tee -a "$LOGFILE"

        # Clear the flag first to avoid loops
        rm -f "$FLAG"

        # Run the update script and capture its exit code
        # system upgrade takes a long time to do
        # use pico param to skip system upgrade (pico update only)
        sh "$SCRIPT" pico >>"$LOGFILE" 2>&1
        STATUS=$?

        if [ $STATUS -ne 0 ]; then
            echo "$(date): ERROR: PicoChess update failed (exit code $STATUS)" | tee -a "$LOGFILE"
            exit $STATUS    # <-- forward the same exit code to systemd
        fi

        # Update timestamp only on success
        echo "$NOW" > "$TIMESTAMP_FILE"
        echo "$(date): PicoChess update completed successfully." | tee -a "$LOGFILE"
    else
        echo "$(date): Skipped update (last run was less than 10 minutes ago)" >>"$LOGFILE"
        rm -f "$FLAG"  # Optionally remove flag to prevent retry
    fi
fi

exit 0
