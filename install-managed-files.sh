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

# Select the configuration profile for a settings reset. Explicit hardware
# flags take precedence over the existing file: a standalone DGT3000 is
# connected through the eboard and must not enable the DGTPi GPIO driver.
# Arguments: install_dgtpi install_dgt3000 reset_settings existing_ini
select_ini_profile() {
    profile_dgtpi=$1
    profile_dgt3000=$2
    profile_reset=$3
    profile_existing_ini=$4

    if [ "$profile_dgtpi" = true ]; then
        printf '%s\n' dgtpi
    elif [ "$profile_dgt3000" = true ]; then
        printf '%s\n' web
    elif [ "$profile_reset" = true ] && ini_setting_is_true "$profile_existing_ini" dgtpi; then
        printf '%s\n' dgtpi
    else
        printf '%s\n' web
    fi
}

# Remove a complete installer-managed block from a file, retaining the
# pre-change file as the supplied backup. Missing blocks are already clean;
# incomplete blocks are left untouched for manual inspection.
# Arguments: file begin_marker end_marker backup
remove_managed_block() {
    block_file=$1
    block_begin=$2
    block_end=$3
    block_backup=$4

    [ -f "$block_file" ] || return 0

    block_tmp="${block_file}.tmp.$$"
    if ! cp -p "$block_file" "$block_tmp"; then
        echo "Error: could not prepare managed-block update for $block_file" >&2
        return 1
    fi
    awk -v begin="$block_begin" -v end="$block_end" '
        $0 == begin {
            if (skip) {
                invalid = 1
                next
            }
            skip = 1
            found = 1
            next
        }
        $0 == end && skip {
            skip = 0
            complete = 1
            next
        }
        !skip {print}
        END {
            if (invalid || skip || (found && !complete)) exit 2
            if (!found) exit 3
        }
    ' "$block_file" > "$block_tmp"
    block_status=$?

    case "$block_status" in
        0)
            ;;
        3)
            rm -f "$block_tmp"
            echo "No managed block found in $block_file."
            return 0
            ;;
        *)
            rm -f "$block_tmp"
            echo "Error: incomplete managed block in $block_file; leaving it unchanged." >&2
            return 1
            ;;
    esac

    if ! cp -p "$block_file" "$block_backup"; then
        rm -f "$block_tmp"
        echo "Error: could not back up $block_file to $block_backup" >&2
        return 1
    fi
    if ! mv "$block_tmp" "$block_file"; then
        rm -f "$block_tmp"
        echo "Error: could not remove managed block from $block_file" >&2
        return 1
    fi

    echo "Removed managed block from $block_file."
    echo "Backup saved as $block_backup."
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
        if [ "$managed_executable" = true ]; then
            chmod +x "$managed_target" || return 1
        fi
        if [ -n "$managed_owner" ]; then
            chown "$managed_owner:$managed_owner" "$managed_target" || return 1
        fi
        echo "$managed_target is already current; ownership and permissions were verified."
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
