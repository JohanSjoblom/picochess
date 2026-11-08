#!/bin/sh
# Install repository-managed catalog metadata without replacing user files.
set -eu

ARCH=${1:-}
case "$ARCH" in
    aarch64|x86_64|AMD64|arm64|mac_x86_64) ;;
    *)
        echo "Unsupported engine metadata architecture: $ARCH" >&2
        exit 2
        ;;
esac

REPO_DIR=${REPO_DIR:-/opt/picochess}
ENGINES_DIR=${ENGINES_DIR:-$REPO_DIR/engines}
PROFILE_SOURCE=${PROFILE_SOURCE:-$REPO_DIR/engine-packages/fairy14}
NNUE_NAMES_SOURCE=${NNUE_NAMES_SOURCE:-$REPO_DIR/engine-packages/nnue/engine-names.txt}
NNUE_BUILDER=${NNUE_BUILDER:-$REPO_DIR/build-nnue-catalog.py}
TARGET_DIR="$ENGINES_DIR/$ARCH"

if [ ! -d "$TARGET_DIR" ]; then
    echo "Engine directory $TARGET_DIR is absent; skipping catalog metadata."
    exit 0
fi

# favorites.ini was historically the static Special catalog.  Preserve it and
# create the unambiguous new name only when the package has not supplied one.
if [ -f "$TARGET_DIR/favorites.ini" ] && [ ! -f "$TARGET_DIR/special.ini" ]; then
    cp "$TARGET_DIR/favorites.ini" "$TARGET_DIR/special.ini"
    echo "Installed special.ini from the legacy Special catalog."
fi

# NNUE is a catalog classification of binaries already supplied by the chosen
# small/lite package.  Generate it only at install time and never replace a
# catalog maintained by the user or a future engine package.
if [ -f "$TARGET_DIR/engines.ini" ] && [ ! -f "$TARGET_DIR/nnue.ini" ]; then
    python3 "$NNUE_BUILDER" "$TARGET_DIR/engines.ini" "$NNUE_NAMES_SOURCE" "$TARGET_DIR/nnue.ini"
fi

# These files are useful only with the shared Fairy-Stockfish executable.  Do
# not expose unavailable variant entries on systems that do not carry it.
if [ ! -f "$TARGET_DIR/fairy" ]; then
    echo "Fairy-Stockfish is absent; skipping managed variant profiles."
    exit 0
fi

for profile_file in \
    variants.ini \
    fairy-3check.uci \
    fairy-koth.uci \
    fairy-atomic.uci \
    fairy-racingkings.uci \
    fairy-antichess.uci
do
    if [ ! -f "$TARGET_DIR/$profile_file" ]; then
        cp "$PROFILE_SOURCE/$profile_file" "$TARGET_DIR/$profile_file"
        echo "Installed $profile_file."
    fi
done
