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

echo "---- Running pylint check on branch: $BRANCH ----"

# Optional: update dependencies
if [ "$1" = "--update" ]; then
    echo "Updating pip dependencies..."
    pip install --upgrade -r requirements.txt || exit 1
fi

# Run pylint on all tracked Python files
echo "Running pylint (E + W only)..."
pylint $(git ls-files '*.py') 2>/dev/null \
  | grep -E ': [EW][0-9]' \
  | grep -v '^tests/' > pylint_errors.txt || true

# If baseline missing, create it only if on main/master
if [ ! -f "$BASELINE" ]; then
    if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
        echo "No baseline found — creating $BASELINE ..."
        cp pylint_errors.txt "$BASELINE"
    else
        echo "⚠️  No baseline found. Please run this script once on main/master first."
        exit 1
    fi
fi

# Compare results
NEW_COUNT=$(wc -l < pylint_errors.txt)
OLD_COUNT=$(wc -l < "$BASELINE")
echo
echo "---- Summary ----"
echo "New pylint_errors.txt line count: $NEW_COUNT"
echo "Master baseline line count:       $OLD_COUNT"

echo
echo "---- Diff vs master baseline ----"
if diff -u "$BASELINE" pylint_errors.txt > pylint_diff.txt; then
    echo "✅ No new errors or warnings."
    exit 0
else
    ADDED=$(grep -c '^+' pylint_diff.txt || true)
    REMOVED=$(grep -c '^-' pylint_diff.txt || true)
    ADDED=$((ADDED - 2)); [ "$ADDED" -lt 0 ] && ADDED=0
    REMOVED=$((REMOVED - 2)); [ "$REMOVED" -lt 0 ] && REMOVED=0
    echo "⚠️  Differences found:"
    echo "   +$ADDED new issues"
    echo "   -$REMOVED fixed issues"
    echo

    # Only update baseline automatically if on main/master
    if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
        echo "✅ On $BRANCH — updating baseline ($BASELINE)..."
        cp pylint_errors.txt "$BASELINE"
    else
        echo "🛑 On branch '$BRANCH' — baseline not updated."
        echo "    To update baseline, switch to main/master and run:"
        echo "    cp pylint_errors.txt $BASELINE"
    fi
    exit 1
fi
exit 0
