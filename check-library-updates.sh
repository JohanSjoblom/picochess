#!/bin/sh
# check-library-updates
#
# Check updates via pip-review ONLY for libraries pinned with "==" in
# requirements.txt. Runs one library at a time, filters dependency noise,
# normalizes '_' vs '-', and always stops on Ctrl-C.
#
# Usage:
#   ./check-library-updates [requirements.txt]
#
# Optional:
#   TIMEOUT_SECS=20 ./check-library-updates

# NOTE:
# pip-review outputs may differ:
#   - "pkg old -> new"
#   - "pkg==new is available (you have old)"
# This script intentionally supports both.

REQ_FILE=${1:-requirements.txt}
TIMEOUT_SECS=${TIMEOUT_SECS:-10}

if [ ! -f "$REQ_FILE" ]; then
  echo "Error: requirements file not found: $REQ_FILE" >&2
  exit 2
fi

if ! command -v pip-review >/dev/null 2>&1; then
  echo "Error: pip-review not found. Install with: pip install pip-review" >&2
  exit 2
fi

if ! command -v timeout >/dev/null 2>&1; then
  echo "Error: 'timeout' not found (coreutils required)." >&2
  exit 2
fi

tmp_pkgs=$(mktemp "${TMPDIR:-/tmp}/check-libs.XXXXXX") || exit 2
tmp_out=$(mktemp  "${TMPDIR:-/tmp}/check-libs-out.XXXXXX") || exit 2

cleanup() {
  echo "" >&2
  echo "Interrupted. Stopping." >&2
  rm -f "$tmp_pkgs" "$tmp_out"
  exit 130
}
trap cleanup INT TERM HUP

# Extract pinned package names (left side of '==')
sed -n '
  s/\r$//
  s/#.*$//
  s/^[[:space:]]*//
  s/[[:space:]]*$//
  /^[[:space:]]*$/d
  s/^\([^=[:space:]]*\)==.*/\1/p
' "$REQ_FILE" > "$tmp_pkgs"

export PIP_NO_INPUT=1
export PIP_DISABLE_PIP_VERSION_CHECK=1

while IFS= read -r pkg; do
  [ -n "$pkg" ] || continue

  echo "Checking $pkg..." >&2
  : > "$tmp_out"

  timeout --foreground -k 2s "${TIMEOUT_SECS}s" \
    pip-review "$pkg" </dev/null >"$tmp_out" 2>/dev/null || true

  # Print only lines for THIS package, supporting both pip-review output formats:
  #   1) "pkg 1.0 -> 1.1"
  #   2) "pkg==1.1 is available (you have 1.0)"
  awk -v p="$pkg" '
    function norm(s) { s=tolower(s); gsub(/_/, "-", s); return s }
    BEGIN { pl = norm(p) }
    {
      line = $0
      low  = norm($0)

      # allow "pkg " OR "pkg==" at start
      if (index(low, pl " ") == 1 || index(low, pl "==") == 1) {
        # keep only lines that look like an update
        if (index(low, "->") > 0 || index(low, " is available") > 0) {
          print line
        }
      }
    }
  ' "$tmp_out"

done < "$tmp_pkgs"

rm -f "$tmp_pkgs" "$tmp_out"
exit 0
