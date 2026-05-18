#!/bin/sh
#
# run-picochess-if-flagged.sh
# POSIX shell script to run PicoChess updater if flagged
#

REPO_DIR="/opt/picochess"
INSTALL_USER=$(stat -c %U "$REPO_DIR" 2>/dev/null || true)
if [ -z "$INSTALL_USER" ] || [ "$INSTALL_USER" = "root" ]; then
    if getent passwd pi >/dev/null 2>&1; then
        INSTALL_USER="pi"
        echo "Warning: using fallback install user 'pi'." >&2
    else
        echo "Error: could not determine non-root install user from $REPO_DIR owner." >&2
        exit 1
    fi
fi
INSTALL_USER_HOME=$(getent passwd "$INSTALL_USER" | cut -d: -f6)
if [ -z "$INSTALL_USER_HOME" ]; then
    echo "Error: could not determine home directory for $INSTALL_USER." >&2
    exit 1
fi

FLAG="$INSTALL_USER_HOME/run_picochess_update.flag"
PICO_SCRIPT="$REPO_DIR/install-picochess.sh"
ENGINE_SCRIPT="$REPO_DIR/install-engines.sh"
BOOKS_SCRIPT="$REPO_DIR/install-books-games.sh"
ENGINE_RESTORE_SCRIPT="$REPO_DIR/restore-engines-from-backup.sh"
BOOKS_RESTORE_SCRIPT="$REPO_DIR/restore-books-games-from-backup.sh"

LOGFILE="/var/log/picochess-update.log"
TIMESTAMP_FILE="/var/log/picochess-last-update"
FAIL_FILE="/var/log/picochess-last-update-fail"

# Create log file if it doesn't exist
touch "$LOGFILE"
# Do NOT touch timestamp file here, only update on success

find_cap_tool() {
    tool_name="$1"
    tool_path=$(command -v "$tool_name" 2>/dev/null || true)
    if [ -n "$tool_path" ]; then
        echo "$tool_path"
        return 0
    fi
    for tool_dir in /usr/sbin /sbin /usr/bin /bin; do
        if [ -x "$tool_dir/$tool_name" ]; then
            echo "$tool_dir/$tool_name"
            return 0
        fi
    done
    return 1
}

repair_python_bind_capability() {
    if [ "$(id -u)" -ne 0 ]; then
        echo "$(date): WARNING: cannot repair Python port-80 capability without root." >>"$LOGFILE"
        return 0
    fi
    SETCAP=$(find_cap_tool setcap || true)
    if [ -z "$SETCAP" ]; then
        echo "$(date): WARNING: setcap not found; cannot repair Python port-80 capability." >>"$LOGFILE"
        return 0
    fi
    GETCAP=$(find_cap_tool getcap || true)
    if [ -z "$GETCAP" ]; then
        echo "$(date): WARNING: getcap not found; cannot check Python port-80 capability." >>"$LOGFILE"
        return 0
    fi

    PYTHON_LINK=""
    for candidate in "$REPO_DIR/venv/bin/python3" "$REPO_DIR/venv/bin/python"; do
        if [ -x "$candidate" ]; then
            PYTHON_LINK="$candidate"
            break
        fi
    done
    if [ -z "$PYTHON_LINK" ]; then
        echo "$(date): WARNING: PicoChess venv Python not found; skipping port-80 capability repair." >>"$LOGFILE"
        return 0
    fi

    PYTHON_TARGET=$("$PYTHON_LINK" -c 'import os, sys; print(os.path.realpath(sys.executable))' 2>/dev/null || true)
    if [ -z "$PYTHON_TARGET" ] || [ ! -x "$PYTHON_TARGET" ]; then
        echo "$(date): WARNING: could not resolve executable Python from $PYTHON_LINK." >>"$LOGFILE"
        return 0
    fi

    PYTHON_CAPS=$("$GETCAP" "$PYTHON_TARGET" 2>/dev/null || true)
    case "$PYTHON_CAPS" in
        *cap_net_bind_service*)
            return 0
            ;;
    esac

    if [ -n "$PYTHON_CAPS" ]; then
        echo "$(date): WARNING: $PYTHON_TARGET has capabilities but not cap_net_bind_service; leaving unchanged: $PYTHON_CAPS" >>"$LOGFILE"
        return 0
    fi

    if "$SETCAP" 'cap_net_bind_service=+ep' "$PYTHON_TARGET" 2>>"$LOGFILE"; then
        echo "$(date): Repaired Python port-80 capability on $PYTHON_TARGET." >>"$LOGFILE"
    else
        echo "$(date): WARNING: failed to repair Python port-80 capability on $PYTHON_TARGET." >>"$LOGFILE"
    fi
    return 0
}

# This service runs as root before picochess.service. Repair this even when no
# update flag exists, because an OS Python upgrade replaces the executable and
# drops file capabilities.
repair_python_bind_capability

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
                # Run twice: the first pass may update the install script itself;
                # the second pass uses the updated script to update the application.
                echo "$(date): Running install-picochess.sh (pass 1/2)..." | tee -a "$LOGFILE"
                sh "$PICO_SCRIPT" pico noengines >>"$LOGFILE" 2>&1
                STATUS=$?
                if [ "$STATUS" -eq 0 ]; then
                    echo "$(date): Running install-picochess.sh (pass 2/2)..." | tee -a "$LOGFILE"
                    sh "$PICO_SCRIPT" pico noengines >>"$LOGFILE" 2>&1
                    STATUS=$?
                fi
                ;;
            engines)
                if [ ! -x "$ENGINE_SCRIPT" ]; then
                    echo "$(date): ERROR: Script $ENGINE_SCRIPT not found or not executable." | tee -a "$LOGFILE"
                    touch "$FAIL_FILE"
                    exit 1
                fi
                sudo -u "$INSTALL_USER" sh "$ENGINE_SCRIPT" lite >>"$LOGFILE" 2>&1
                STATUS=$?
                ;;
            books-games)
                if [ ! -x "$BOOKS_SCRIPT" ]; then
                    echo "$(date): ERROR: Script $BOOKS_SCRIPT not found or not executable." | tee -a "$LOGFILE"
                    touch "$FAIL_FILE"
                    exit 1
                fi
                sudo -u "$INSTALL_USER" sh "$BOOKS_SCRIPT" >>"$LOGFILE" 2>&1
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
                        sudo -u "$INSTALL_USER" sh "$ENGINE_RESTORE_SCRIPT" >>"$LOGFILE" 2>&1 || \
                            echo "$(date): WARNING: Failed to restore engines from backup." | tee -a "$LOGFILE"
                    fi
                    ;;
                books-games)
                    if [ -x "$BOOKS_RESTORE_SCRIPT" ]; then
                        echo "$(date): Restoring book/game resources from backup due to failure." | tee -a "$LOGFILE"
                        sudo -u "$INSTALL_USER" sh "$BOOKS_RESTORE_SCRIPT" >>"$LOGFILE" 2>&1 || \
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
