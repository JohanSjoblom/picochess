#!/bin/sh
#
# check-git-status.sh
# Show concise Git status for PicoChess
#

REPO_DIR="/opt/picochess"
BRANCH="master"
REMOTE="origin"

cd "$REPO_DIR" || exit 1

# Ensure we have git info
if [ ! -d ".git" ]; then
    echo "git: unknown"
    exit 1
fi

# Get current branch or detached head
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

if [ "$CURRENT_BRANCH" = "HEAD" ]; then
    # Detached head, could be tag or commit
    HEAD_TYPE=$(git describe --tags --exact-match 2>/dev/null)
    if [ $? -eq 0 ]; then
        # It is a tag
        echo "t:$(git describe --tags --abbrev=0)"
    else
        # Just a commit
        SHORT_COMMIT=$(git rev-parse --short HEAD)
        echo "c:$SHORT_COMMIT"
    fi
    exit 0
fi

# Fetch remote info to check behind status
git fetch "$REMOTE" > /dev/null 2>&1

# Count commits behind remote
BEHIND=$(git rev-list --count "$CURRENT_BRANCH..$REMOTE/$CURRENT_BRANCH" 2>/dev/null || echo 0)

if [ "$CURRENT_BRANCH" = "$BRANCH" ]; then
    # Master branch
    if [ "$BEHIND" -eq 0 ]; then
        echo "git:no new"
    else
        echo "git:$BEHIND new"
    fi
else
    # Development/test branch
    if [ "$BEHIND" -eq 0 ]; then
        echo "b: no new"
    else
        echo "b:$BEHIND new"
    fi
fi
