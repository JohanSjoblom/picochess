#!/bin/sh
# Simple pylint consistency check script
# Compares current pylint E/W errors with previous baseline
#
# run as normal pi user, not sudo - Note: it does run for quite some minutes
#
# it creates
# pylint_errors.txt  <--- in gitignore - this script creates this file with latest pylint E/W
# BASELINE file      <--- baseline to compare against, master branch copy of pylint_errors.txt
# pylint_diff        <--- in gitignore - compares latest vs baseline
#
# The idea is to always have a BASELINE pylint_file in master branch.
# When you create a new feature branch from master it will get the latest baseline.
#
# When working on that feature branch, run this script to see if new pylint errors/warnings
# have been introduced compared to the inherited master baseline.
# --> If so, fix them before merging to master.
# The baseline is never updated in feature branches to avoid merge conflict
#
# The latest pylint_errors.txt and diff are ignored in gitignore in both master and branches
# to avoid merge conflicts.
#
set -e

BASELINE="pylint_errors_master_baseline.txt"
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
RAW_OUTPUT="pylint_raw_output.txt"
CURRENT="pylint_errors.txt"

echo "---- Running pylint check on branch: $BRANCH ----"

# Optional update
if [ "$1" = "--update" ]; then
    echo "Updating pip dependencies..."
    pip install --upgrade -r requirements.txt || exit 1
fi

echo "Running pylint (E + W only) and capturing output..."
# Run pylint via python module (robust across envs), capture stdout+stderr,
# and remove ANSI color codes (if any) before further processing.
python -m pylint --output-format=text $(git ls-files '*.py') 2>&1 \
    | sed -E 's/\x1b\[[0-9;]*[mK]//g' > "$RAW_OUTPUT" || true

# Debug helper: if RAW_OUTPUT is empty, print a hint and show first lines
if [ ! -s "$RAW_OUTPUT" ]; then
    echo "⚠️  pylint produced no output. Check that pylint is installed and works:"
    echo "Try: python -m pylint --version"
    echo "Raw output file is empty: $RAW_OUTPUT"
    exit 1
fi

# Extract only lines that contain E/W message codes in typical pylint format:
# e.g. path/to/file.py:12:4: E1120: message...
grep -E ': [EW][0-9]+' "$RAW_OUTPUT" \
    | grep -v '^tests/' \
    > "$CURRENT" || true

# Sort for stable diff
sort "$CURRENT" -o "$CURRENT"
[ -f "$BASELINE" ] && sort "$BASELINE" -o "$BASELINE"

# If baseline missing, create only on master/main
if [ ! -f "$BASELINE" ]; then
    if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
        echo "No baseline found — creating $BASELINE ..."
        cp "$CURRENT" "$BASELINE"
    else
        echo "⚠️  No baseline found. Please run this script once on main/master first."
        exit 1
    fi
fi

# Summary counts
NEW_COUNT=$(wc -l < "$CURRENT")
OLD_COUNT=$(wc -l < "$BASELINE")
echo
echo "---- Summary ----"
echo "New pylint_errors.txt line count: $NEW_COUNT"
echo "Master baseline line count:       $OLD_COUNT"
echo

# Diff
if diff -u "$BASELINE" "$CURRENT" > pylint_diff.txt; then
    echo "✅ No new errors or warnings."
else
    ADDED=$(grep -c '^+' pylint_diff.txt || true)
    REMOVED=$(grep -c '^-' pylint_diff.txt || true)
    ADDED=$((ADDED - 2)); [ "$ADDED" -lt 0 ] && ADDED=0
    REMOVED=$((REMOVED - 2)); [ "$REMOVED" -lt 0 ] && REMOVED=0
    echo "⚠️  Differences found:"
    echo "   +$ADDED new issues"
    echo "   -$REMOVED fixed issues"
    echo
    if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
        echo "✅ On $BRANCH — updating baseline ($BASELINE)..."
        cp "$CURRENT" "$BASELINE"
    else
        echo "🛑 On branch '$BRANCH' — baseline not updated."
        echo "    To update baseline, switch to main/master and run:"
        echo "    cp $CURRENT $BASELINE"
    fi
fi

# Extra: count E and W and list E if <10
ECOUNT=$(grep -c ': E[0-9]' "$CURRENT" || true)
WCOUNT=$(grep -c ': W[0-9]' "$CURRENT" || true)

echo
echo "---- Error overview ----"
echo "Errors (E): $ECOUNT"
echo "Warnings (W): $WCOUNT"

if [ "$ECOUNT" -gt 0 ]; then
    if [ "$ECOUNT" -lt 10 ]; then
        echo
        echo "❌ Listing all $ECOUNT E-errors:"
        grep ': E[0-9]' "$CURRENT" || true
    else
        echo
        echo "❌ Too many E-errors ($ECOUNT) — not listing individually."
        echo "   Check $CURRENT for details."
    fi
fi

exit 0
