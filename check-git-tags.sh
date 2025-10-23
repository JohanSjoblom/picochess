#!/bin/sh
#
# list-git-tags.sh
# POSIX shell script to list the latest git tags (tag name + date)
# for PicoChess — only tags starting with "v4"
#

REPO_DIR="/opt/picochess"
cd "$REPO_DIR" || exit 1

# Default number of tags to show
NUM_TAGS=3

# Allow override via command-line argument (must be a number)
case "$1" in
    '' ) ;;
    *[!0-9]* ) echo "Usage: $0 [number_of_tags]"; exit 1 ;;
    * ) NUM_TAGS=$1 ;;
esac

# Get the most recent tags starting with "v4"
TAG_LIST=$(git for-each-ref --sort=-creatordate \
    --format='%(refname:short)  %(creatordate:short)' refs/tags 2>/dev/null |
    grep '^v4' | head -n "$NUM_TAGS")

if [ -z "$TAG_LIST" ]; then
    echo "No v4 tags found"
    exit 2
fi

echo "$TAG_LIST"
exit 0