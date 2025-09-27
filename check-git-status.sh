#!/bin/sh
cd /opt/picochess || { echo "git:none"; exit 1; }

git fetch --quiet origin

# Case 1: exact tag
if git describe --tags --exact-match >/dev/null 2>&1; then
    TAG=$(git describe --tags --exact-match)
    echo "git:$TAG" | cut -c1-11
    exit 0
fi

# Current branch or HEAD
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "none")

if [ "$BRANCH" = "HEAD" ]; then
    # Detached commit
    COMMIT=$(git rev-parse --short=7 HEAD)
    echo "git:$COMMIT" | cut -c1-11
    exit 0
fi

if [ "$BRANCH" = "master" ] || [ "$BRANCH" = "main" ]; then
    BEHIND=$(git rev-list --count "$BRANCH"..origin/"$BRANCH" 2>/dev/null)

    if [ "$BEHIND" -gt 0 ]; then
        echo "git:$BEHIND new" | cut -c1-11
        exit 0
    else
        echo "git:no new" | cut -c1-11
        exit 0
    fi
fi

# Any other branch: truncate to max 11 chars
echo "git:$BRANCH" | cut -c1-11

exit 0
