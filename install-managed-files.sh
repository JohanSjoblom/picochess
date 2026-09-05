#!/bin/sh

# Shared helpers for installer-managed files outside the tracked repository.
# This file is sourced by install-picochess.sh and install-kiosk.sh.

has_no_update_marker() {
    marker_file=$1
    [ -f "$marker_file" ] || return 1
    grep -Eq '^[[:space:]]*#[[:space:]]*no[[:space:]]+update[[:space:]]*$' "$marker_file"
}

# Return success when the last active occurrence of an INI key is true.
ini_setting_is_true() {
    setting_file=$1
    setting_key=$2
    [ -f "$setting_file" ] || return 1
    awk -F '=' -v key="$setting_key" '
        /^[[:space:]]*#/ {next}
        {
            name=$1
            gsub(/[[:space:]]/, "", name)
            if (tolower(name) == tolower(key)) {
                value=$2
                sub(/#.*/, "", value)
                gsub(/[[:space:]]/, "", value)
                found = (tolower(value) == "true")
                seen = 1
            }
        }
        END {exit(seen && found ? 0 : 1)}
    ' "$setting_file"
}

# Replace a managed file only when its contents changed. Keeping this operation
# idempotent is important because PicoChess code updates run the installer twice.
#
# Arguments: source target backup respect_no_update executable owner
replace_managed_file() {
    managed_source=$1
    managed_target=$2
    managed_backup=$3
    managed_respect_marker=$4
    managed_executable=$5
    managed_owner=$6

    if [ ! -f "$managed_source" ]; then
        echo "Error: managed file source not found: $managed_source" >&2
        return 1
    fi

    if [ "$managed_respect_marker" = true ] && has_no_update_marker "$managed_target"; then
        echo "Keeping $managed_target because it contains the '# no update' marker."
        return 0
    fi

    if [ -f "$managed_target" ] && cmp -s "$managed_source" "$managed_target"; then
        echo "$managed_target is already current."
        return 0
    fi

    if [ -f "$managed_target" ]; then
        if ! cp -p "$managed_target" "$managed_backup"; then
            echo "Error: could not back up $managed_target to $managed_backup" >&2
            return 1
        fi
        echo "Backed up $managed_target to $managed_backup."
    fi

    managed_tmp="${managed_target}.tmp.$$"
    if ! cp "$managed_source" "$managed_tmp"; then
        echo "Error: could not prepare replacement for $managed_target" >&2
        rm -f "$managed_tmp"
        return 1
    fi

    if [ "$managed_executable" = true ]; then
        chmod +x "$managed_tmp" || {
            rm -f "$managed_tmp"
            return 1
        }
    fi

    if [ -n "$managed_owner" ]; then
        chown "$managed_owner:$managed_owner" "$managed_tmp" || {
            rm -f "$managed_tmp"
            return 1
        }
    fi

    if ! mv "$managed_tmp" "$managed_target"; then
        echo "Error: could not replace $managed_target" >&2
        rm -f "$managed_tmp"
        return 1
    fi

    echo "Installed current $managed_target."
}
