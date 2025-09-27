#!/bin/sh
#
# run-picochess-if-flagged.sh
# POSIX shell script to run PicoChess updater if flagged
#

FLAG="/home/pi/run_picochess_update.flag"
SCRIPT="/opt/picochess/install-picochess.sh"
LOGFILE="/var/log/picochess-update.log"
TIMESTAMP_FILE="/var/log/picochess-last-update"
FAIL_FILE="/var/log/picochess-last-update-fail"

# Create log file if it doesn't exist
touch "$LOGFILE"
# Do NOT touch timestamp file here, only update on success

# Check if the flag file exists
if [ -f "$FLAG" ]; then
    NOW=$(date +%s)
    LAST_RUN=$(cat "$TIMESTAMP_FILE" 2>/dev/null || echo 0)
    DIFF=$((NOW - LAST_RUN))

    # Run update if >10 minutes since last successful run,
    # OR first run, OR previous update failed
    if [ "$DIFF" -ge 600 ] || [ "$LAST_RUN" -eq 0 ] || [ -f "$FAIL_FILE" ]; then
        echo "$(date): Running PicoChess update..." | tee -a "$LOGFILE"

        # Clear the flag first to avoid loops
        rm -f "$FLAG"

        # Run the install script
        sh "$SCRIPT" pico >>"$LOGFILE" 2>&1
        STATUS=$?

        if [ "$STATUS" -ne 0 ]; then
            echo "$(date): ERROR: PicoChess update failed (exit code $STATUS)" | tee -a "$LOGFILE"
            # Create fail marker
            touch "$FAIL_FILE"
            exit $STATUS    # Forward exit code to systemd
        else
            echo "$(date): PicoChess update completed successfully." | tee -a "$LOGFILE"
            # Remove fail marker if it exists
            rm -f "$FAIL_FILE"
            # Update timestamp only on success
            echo "$NOW" > "$TIMESTAMP_FILE"
        fi
    else
        echo "$(date): Skipped update (last run <10 minutes ago)" >>"$LOGFILE"
        rm -f "$FLAG"  # Optionally remove flag to prevent retry
    fi
fi

exit 0
