#!/bin/bash
#
# Start PicoChess on macOS and optionally its Scid games helper.
#
# PicoChess itself is always started from the repository virtual environment.
# When gamesdb data and a native macOS tcscid are available, get_games.tcl is
# started on port 7778 first and stopped again when PicoChess exits. Failure to
# find or start tcscid is non-fatal; only the Games tab lacks database results.
#
# To stop PicoChess, send SIGINT (Ctrl+C) to the process group so picochess.py
# runs its normal shutdown. Without a games helper the script execs Python, so
# signalling this process directly also works.
#
# Written for the bash 3.2 that ships with macOS.

set -eu

TCSCID_PATH=""
GAMES_PORT=7778
SKIP_GAMES_SERVER=false
GAMES_PID=""

usage() {
    cat <<'EOF'
Usage: start-picochess-mac.sh [options] [-- picochess.py arguments]

Options:
  --tcscid PATH            Native macOS tcscid executable for the Games tab.
                           Default: $PICOCHESS_TCSCID, then tcscid on PATH.
  --games-port PORT        Port for get_games.tcl. The web client expects 7778.
  --skip-games-server      Start PicoChess without looking for tcscid.
  -h, --help               Show this help.

Arguments after -- are passed to picochess.py, for example:
  bash ./start-picochess-mac.sh -- --board-type noeboard --web-server 8080
EOF
}

fail() {
    printf 'PicoChess startup failed: %s\n' "$*" >&2
    exit 1
}

status() {
    printf '    %s\n' "$*"
}

warn() {
    printf 'Warning: %s\n' "$*" >&2
}

port_open() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

cleanup() {
    if [ -n "$GAMES_PID" ] && kill -0 "$GAMES_PID" 2>/dev/null; then
        status "Stopping the Scid games helper started by this launcher."
        kill "$GAMES_PID" 2>/dev/null || true
        wait "$GAMES_PID" 2>/dev/null || true
    fi
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --tcscid)
            [ "$#" -ge 2 ] || fail "--tcscid requires a path."
            TCSCID_PATH=$2
            shift 2
            ;;
        --games-port)
            [ "$#" -ge 2 ] || fail "--games-port requires a port number."
            case "$2" in
                ''|*[!0-9]*) fail "--games-port must be a number." ;;
            esac
            [ "$2" -ge 1 ] && [ "$2" -le 65535 ] || fail "--games-port must be between 1 and 65535."
            GAMES_PORT=$2
            shift 2
            ;;
        --skip-games-server) SKIP_GAMES_SERVER=true; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; break ;;
        *) fail "Unknown option: $1 (use --help for usage; pass picochess.py arguments after --)." ;;
    esac
done

[ "$(uname -s)" = "Darwin" ] || fail "This launcher supports macOS only."

REPOSITORY_PATH=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
VENV_PYTHON="$REPOSITORY_PATH/venv/bin/python"
[ -f "$REPOSITORY_PATH/picochess.py" ] || fail "picochess.py was not found beside this launcher."
[ -x "$VENV_PYTHON" ] || fail "PicoChess virtual environment not found. Run install-picochess-mac.sh first."
[ -f "$REPOSITORY_PATH/picochess.ini" ] || warn "picochess.ini was not found. Configure it after adding a native macOS engine."

find_tcscid() {
    if [ -n "$TCSCID_PATH" ]; then
        if [ -x "$TCSCID_PATH" ]; then
            printf '%s\n' "$TCSCID_PATH"
            return
        fi
        warn "The supplied tcscid path is not an executable file: $TCSCID_PATH"
    fi
    if [ -n "${PICOCHESS_TCSCID:-}" ]; then
        if [ -x "$PICOCHESS_TCSCID" ]; then
            printf '%s\n' "$PICOCHESS_TCSCID"
            return
        fi
        warn "PICOCHESS_TCSCID is not an executable file: $PICOCHESS_TCSCID"
    fi
    command -v tcscid 2>/dev/null || true
}

start_games_helper() {
    executable=$1
    games_directory="$REPOSITORY_PATH/gamesdb"
    if [ ! -f "$games_directory/get_games.tcl" ]; then
        warn "Games data is missing get_games.tcl. Run install-picochess-mac.sh to install the Games resource."
        return
    fi
    if [ ! -f "$games_directory/games.si4" ]; then
        warn "Games data is missing games.si4. The Games resource may be incomplete."
        return
    fi

    logs_directory="$REPOSITORY_PATH/logs"
    mkdir -p "$logs_directory"
    stdout_log="$logs_directory/gamesdb-mac.log"
    stderr_log="$logs_directory/gamesdb-mac-error.log"

    printf 'Starting the optional Scid games helper...\n'
    (cd "$games_directory" && exec "$executable" get_games.tcl --server "$GAMES_PORT") \
        >"$stdout_log" 2>"$stderr_log" &
    GAMES_PID=$!

    attempts=0
    while [ "$attempts" -lt 40 ]; do
        if ! kill -0 "$GAMES_PID" 2>/dev/null; then
            code=0
            wait "$GAMES_PID" 2>/dev/null || code=$?
            warn "tcscid exited during startup with code $code. See $stderr_log"
            GAMES_PID=""
            return
        fi
        if port_open "$GAMES_PORT"; then
            status "Games helper is listening on port $GAMES_PORT."
            return
        fi
        sleep 0.2
        attempts=$((attempts + 1))
    done

    warn "tcscid did not open port $GAMES_PORT within 8 seconds. See $stdout_log and $stderr_log"
    cleanup
    GAMES_PID=""
}

if [ "$SKIP_GAMES_SERVER" = true ]; then
    status "Games helper skipped by request."
elif port_open "$GAMES_PORT"; then
    status "Port $GAMES_PORT is already accepting connections; assuming a games helper is running."
else
    tcscid=$(find_tcscid)
    if [ -n "$tcscid" ]; then
        status "Using tcscid: $tcscid"
        trap cleanup EXIT
        trap 'exit 130' INT
        trap 'exit 143' TERM
        start_games_helper "$tcscid"
    else
        warn "No native macOS tcscid was found. Supply --tcscid or set PICOCHESS_TCSCID to enable the Games tab."
        status "PicoChess will continue normally; only Games-tab database results are unavailable."
    fi
fi

cd "$REPOSITORY_PATH"
printf 'Starting PicoChess...\n'
if [ -z "$GAMES_PID" ]; then
    trap - EXIT INT TERM
    exec "$VENV_PYTHON" picochess.py ${1+"$@"}
fi

# Keep this shell alive so the EXIT trap can stop the games helper. A SIGINT
# sent to the process group also reaches picochess.py, which shuts down first.
code=0
"$VENV_PYTHON" picochess.py ${1+"$@"} || code=$?
exit "$code"
