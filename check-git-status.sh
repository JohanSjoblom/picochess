#!/bin/sh
#
# check-git-status.sh
# POSIX shell script to show git repo status for PicoChess
#

REPO_DIR="/opt/picochess"
cd "$REPO_DIR" || exit 1

# Detect current branch or tag/commit
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
CURRENT_TAG=$(git describe --tags --exact-match 2>/dev/null || echo "")

OUTPUT=""

if [ -n "$CURRENT_TAG" ]; then
    # On a tag → prefix 't:'
    OUTPUT="t:$CURRENT_TAG"
elif [ "$CURRENT_BRANCH" = "HEAD" ]; then
    # Detached HEAD → prefix 'c:' + short commit hash
    COMMIT_HASH=$(git rev-parse --short HEAD 2>/dev/null)
    OUTPUT="c:$COMMIT_HASH"
elif [ "$CURRENT_BRANCH" = "master" ]; then
    # On master → check if fully updated
    BEHIND=$(git rev-list --count HEAD..origin/master 2>/dev/null || echo 0)
    if [ "$BEHIND" -eq 0 ]; then
        OUTPUT="git:no new"
    else
        OUTPUT="git:$BEHIND new"
    fi
else
    # On some other branch → prefix 'b:' + branch name truncated to 11 chars
    BRANCH_SHORT=$(printf "%s" "$CURRENT_BRANCH" | cut -c1-11)
    OUTPUT="b:$BRANCH_SHORT"
fi

echo "$OUTPUT"
