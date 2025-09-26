#!/bin/sh
# Compact git status for /opt/picochess (max 11 chars)

REPO_DIR="/opt/picochess"

if [ ! -d "$REPO_DIR/.git" ]; then
    echo "git:none"
    exit 0
fi

cd "$REPO_DIR" || exit 1

# Tag?
TAG=$(git describe --tags --exact-match 2>/dev/null)
if [ -n "$TAG" ]; then
    echo "git:$TAG" | cut -c1-11
    exit 0
fi

# Branch or commit
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
if [ "$BRANCH" = "HEAD" ]; then
    COMMIT=$(git rev-parse --short HEAD 2>/dev/null)
    echo "git:$COMMIT" | cut -c1-11
else
    echo "git:$BRANCH" | cut -c1-11
fi
exit 0
