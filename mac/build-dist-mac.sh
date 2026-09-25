#!/bin/bash
#
# Build the distributable PicoChess.app for Apple-silicon and Intel Macs.
#
# Run on macOS with the .NET 10 SDK installed. For each architecture this
# publishes a self-contained PicoChess.MacControlPanel, wraps it in an app
# bundle, signs it ad hoc, and writes to the output folder:
#
#   PicoChess-mac-arm64.zip  PicoChess-mac-arm64.zip.sha256
#   PicoChess-mac-x64.zip    PicoChess-mac-x64.zip.sha256
#
# The zips and their checksums are the files to upload to a GitHub release.
# The app is not notarized, so Gatekeeper asks users to allow it once.
#
# Usage: bash mac/build-dist-mac.sh [--output-dir DIR]
# Default output: sdist in the repository root (ignored by Git).

set -eu

fail() {
    printf 'Build failed: %s\n' "$*" >&2
    exit 1
}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
OUTPUT_DIR="$(dirname -- "$SCRIPT_DIR")/sdist"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --output-dir)
            [ "$#" -ge 2 ] || fail "--output-dir requires a path."
            OUTPUT_DIR=$2
            shift 2
            ;;
        -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) fail "Unknown option: $1" ;;
    esac
done

[ "$(uname -s)" = "Darwin" ] || fail "The app bundle must be built and signed on macOS."
command -v dotnet >/dev/null 2>&1 || fail "The .NET 10 SDK is required: https://dotnet.microsoft.com/download/dotnet/10.0"

PROJECT="$SCRIPT_DIR/PicoChess.MacControlPanel"
VERSION=$(sed -n 's:.*<Version>\(.*\)</Version>.*:\1:p' "$PROJECT/PicoChess.MacControlPanel.csproj")
[ -n "$VERSION" ] || fail "Could not read <Version> from the project file."

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR=$(CDPATH= cd -- "$OUTPUT_DIR" && pwd -P)
WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/picochess-mac-build.XXXXXX")
trap 'rm -rf -- "$WORK_DIR"' EXIT

for target in osx-arm64:arm64 osx-x64:x64; do
    rid=${target%%:*}
    label=${target##*:}
    printf '\n==> Building PicoChess.app %s for %s\n' "$VERSION" "$label"

    publish_dir="$WORK_DIR/publish-$label"
    dotnet publish "$PROJECT" -c Release -r "$rid" --self-contained true -o "$publish_dir"

    bundle_root="$WORK_DIR/bundle-$label"
    app="$bundle_root/PicoChess.app"
    mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
    cp -R "$publish_dir/." "$app/Contents/MacOS/"
    rm -f "$app/Contents/MacOS/Info.plist"
    sed "s/__VERSION__/$VERSION/g" "$PROJECT/Info.plist" > "$app/Contents/Info.plist"
    chmod +x "$app/Contents/MacOS/PicoChess"

    # Apple silicon refuses unsigned native code; an ad hoc signature is enough
    # to run once the user allows the app in Gatekeeper.
    codesign --force --deep --sign - "$app"
    codesign --verify --deep --strict "$app"

    zip_name="PicoChess-mac-$label.zip"
    rm -f "$OUTPUT_DIR/$zip_name" "$OUTPUT_DIR/$zip_name.sha256"
    # ditto keeps the bundle structure, permissions, and signature intact.
    ditto -c -k --keepParent "$app" "$OUTPUT_DIR/$zip_name"
    (cd "$OUTPUT_DIR" && shasum -a 256 -b "$zip_name" > "$zip_name.sha256")

    printf 'File:     %s\n' "$OUTPUT_DIR/$zip_name"
    printf 'SHA-256:  %s\n' "$(cut -d ' ' -f 1 "$OUTPUT_DIR/$zip_name.sha256")"
done
