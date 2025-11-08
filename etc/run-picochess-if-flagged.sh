#!/bin/sh
#
# run-picochess-if-flagged.sh
# POSIX shell script to run PicoChess updater if flagged
#

FLAG="/home/pi/run_picochess_update.flag"
PICO_SCRIPT="/opt/picochess/install-picochess.sh"
ENGINE_SCRIPT="/opt/picochess/install-engines.sh"
BOOKS_SCRIPT="/opt/picochess/install-books-games.sh"
ENGINE_RESTORE_SCRIPT="/opt/picochess/restore-engines-from-backup.sh"
BOOKS_RESTORE_SCRIPT="/opt/picochess/restore-books-games-from-backup.sh"

LOGFILE="/var/log/picochess-update.log"
TIMESTAMP_FILE="/var/log/picochess-last-update"
FAIL_FILE="/var/log/picochess-last-update-fail"

# Create log file if it doesn't exist
touch "$LOGFILE"
# Do NOT touch timestamp file here, only update on success

# Check if the flag file exists
if [ -f "$FLAG" ]; then
    REASON=$(head -n 1 "$FLAG" 2>/dev/null | tr -d '\r')
    if [ -z "$REASON" ]; then
        REASON="pico"
    fi

    NOW=$(date +%s)
    LAST_RUN=$(cat "$TIMESTAMP_FILE" 2>/dev/null || echo 0)
    DIFF=$((NOW - LAST_RUN))
    FORCE_RUN=false
    UPDATE_MODE="pico"

    if [ "$REASON" = "engines" ]; then
        FORCE_RUN=true
        UPDATE_MODE="engines"
    elif [ "$REASON" = "books-games" ]; then
        FORCE_RUN=true
        UPDATE_MODE="books-games"
    fi

    # Run update if >3 minutes since last successful run,
    # OR first run, OR previous update failed
    if [ "$DIFF" -ge 180 ] || [ "$LAST_RUN" -eq 0 ] || [ -f "$FAIL_FILE" ] || [ "$FORCE_RUN" = true ]; then
        echo "$(date): Running PicoChess update (reason: $REASON)..." | tee -a "$LOGFILE"

        # Run the appropriate script based on the update mode
        case "$UPDATE_MODE" in
            pico)
                if [ ! -x "$PICO_SCRIPT" ]; then
                    echo "$(date): ERROR: Script $PICO_SCRIPT not found or not executable." | tee -a "$LOGFILE"
                    touch "$FAIL_FILE"
                    exit 1
                fi
                sh "$PICO_SCRIPT" pico >>"$LOGFILE" 2>&1
                STATUS=$?
                ;;
            engines)
                if [ ! -x "$ENGINE_SCRIPT" ]; then
                    echo "$(date): ERROR: Script $ENGINE_SCRIPT not found or not executable." | tee -a "$LOGFILE"
                    touch "$FAIL_FILE"
                    exit 1
                fi
                sudo -u pi sh "$ENGINE_SCRIPT" lite >>"$LOGFILE" 2>&1
                STATUS=$?
                ;;
            books-games)
                if [ ! -x "$BOOKS_SCRIPT" ]; then
                    echo "$(date): ERROR: Script $BOOKS_SCRIPT not found or not executable." | tee -a "$LOGFILE"
                    touch "$FAIL_FILE"
                    exit 1
                fi
                sudo -u pi sh "$BOOKS_SCRIPT" >>"$LOGFILE" 2>&1
                STATUS=$?
                ;;
            *)
                echo "$(date): ERROR: Unknown update mode '$UPDATE_MODE'." | tee -a "$LOGFILE"
                touch "$FAIL_FILE"
                exit 1
                ;;
        esac

        if [ "$STATUS" -ne 0 ]; then
            echo "$(date): ERROR: PicoChess update failed (exit code $STATUS)" | tee -a "$LOGFILE"
            case "$UPDATE_MODE" in
                engines)
                    if [ -x "$ENGINE_RESTORE_SCRIPT" ]; then
                        echo "$(date): Restoring engines from backup due to failure." | tee -a "$LOGFILE"
                        sudo -u pi sh "$ENGINE_RESTORE_SCRIPT" >>"$LOGFILE" 2>&1 || \
                            echo "$(date): WARNING: Failed to restore engines from backup." | tee -a "$LOGFILE"
                    fi
                    ;;
                books-games)
                    if [ -x "$BOOKS_RESTORE_SCRIPT" ]; then
                        echo "$(date): Restoring book/game resources from backup due to failure." | tee -a "$LOGFILE"
                        sudo -u pi sh "$BOOKS_RESTORE_SCRIPT" >>"$LOGFILE" 2>&1 || \
                            echo "$(date): WARNING: Failed to restore book/game resources from backup." | tee -a "$LOGFILE"
                    fi
                    ;;
            esac
            # Create fail marker
            touch "$FAIL_FILE"
            exit $STATUS    # Forward exit code to systemd
        else
            echo "$(date): PicoChess update completed successfully." | tee -a "$LOGFILE"
            # Remove fail marker if it exists
            rm -f "$FAIL_FILE"
            # Update timestamp only on success
            echo "$NOW" > "$TIMESTAMP_FILE"
            # Clear the flag now that update succeeded
            rm -f "$FLAG"
        fi
    else
        echo "$(date): Skipped update (last run <3 minutes ago)" >>"$LOGFILE"
        rm -f "$FLAG"  # Optionally remove flag to prevent retry
    fi
fi

exit 0
