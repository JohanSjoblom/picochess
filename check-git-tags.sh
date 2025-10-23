#!/bin/sh
#
# list-git-tags.sh
# POSIX shell script to list the latest 6 git tags (tag name + date)
# for PicoChess — only tags starting with "v4"
#

REPO_DIR="/opt/picochess"
cd "$REPO_DIR" || exit 1

# Get the 6 most recent tags starting with "v4"
TAG_LIST=$(git for-each-ref --sort=-creatordate \
    --format='%(refname:short)  %(creatordate:short)' refs/tags 2>/dev/null |
    grep '^v4' | head -n 6)

if [ -z "$TAG_LIST" ]; then
    echo "No v4 tags found"
    exit 0
fi

echo "$TAG_LIST"
