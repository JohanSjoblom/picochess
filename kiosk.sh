#!/bin/bash

PICOCHESS_SERVICE="${PICOCHESS_KIOSK_SERVICE:-picochess}"
CHROMIUM_BIN="${PICOCHESS_KIOSK_CHROMIUM:-/usr/bin/chromium}"
KIOSK_PROFILE_DIR="${PICOCHESS_KIOSK_PROFILE:-${HOME}/.config/picochess-kiosk-chromium}"
SERVICE_POLL_INTERVAL="${PICOCHESS_KIOSK_POLL_INTERVAL:-1}"
STARTUP_POLL_INTERVAL="${PICOCHESS_KIOSK_STARTUP_POLL_INTERVAL:-5}"
CHROMIUM_PID=""

is_wayland() {
  [ "${XDG_SESSION_TYPE:-}" = "wayland" ] || [ -n "${WAYLAND_DISPLAY:-}" ]
}

if is_wayland; then
  echo "kiosk.sh: Wayland session detected"
else
  echo "kiosk.sh: X11 session detected"
  xset s noblank
  xset s off
  xset -dpms

  # Uncomment this to rotate the DSI display to portrait
  # xrandr --output DSI-1 --rotate right

  unclutter -idle 0.5 -root &
fi

display_ready() {
  if [ -n "${WAYLAND_DISPLAY:-}" ]; then
    return 0
  fi
  if [ -z "${DISPLAY:-}" ]; then
    return 1
  fi
  if [ -n "${XDG_SESSION_TYPE:-}" ]; then
    return 0
  fi
  ls /tmp/.X11-unix/X* >/dev/null 2>&1
}

terminal_cmd() {
  if command -v lxterminal >/dev/null 2>&1; then
    echo "lxterminal --title=Updating... -e sh -c 'tail -F /var/log/picochess-update.log'"
  elif command -v xfce4-terminal >/dev/null 2>&1; then
    echo "xfce4-terminal --disable-server --title=Updating... -e 'sh -c \"tail -F /var/log/picochess-update.log\"'"
  elif command -v xterm >/dev/null 2>&1; then
    echo "xterm -fullscreen -bg black -fg white -title Updating... -e sh -c 'tail -F /var/log/picochess-update.log'"
  else
    echo ""
  fi
}

notify_no_terminal() {
  local msg="Updating PicoChess... please wait (this can take 10-15 minutes)."
  if [ -w /dev/console ]; then
    printf '%s\n' "$msg" >/dev/console 2>/dev/null
  fi
  if command -v logger >/dev/null 2>&1; then
    logger -t picochess-kiosk "$msg"
  fi
}

update_pending() {
  [ -f "${HOME}/run_picochess_update.flag" ]
}

close_update_terminal() {
  if [ -n "${UPDATE_TERM_PID:-}" ] && kill -0 "$UPDATE_TERM_PID" 2>/dev/null; then
    kill "$UPDATE_TERM_PID" 2>/dev/null
  fi
  if command -v pkill >/dev/null 2>&1; then
    pkill -u "$USER" -f "lxterminal --title=Updating..." 2>/dev/null
    pkill -u "$USER" -f "xfce4-terminal .*--title=Updating..." 2>/dev/null
    pkill -u "$USER" -f "xterm -fullscreen.*-title Updating..." 2>/dev/null
    pkill -u "$USER" -f "tail -F /var/log/picochess-update.log" 2>/dev/null
  fi
  UPDATE_TERM_PID=""
}

configured_web_port() {
  awk -F= '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*web-server[[:space:]]*=/ {
      value = $2
      sub(/#.*/, "", value)
      gsub(/[[:space:]]/, "", value)
      print value
    }
  ' /opt/picochess/picochess.ini 2>/dev/null | tail -n 1
}

port_open() {
  local port="$1"
  [ -n "$port" ] || return 1
  (: >/dev/tcp/127.0.0.1/"$port") >/dev/null 2>&1
}

picochess_url() {
  local port

  if [ -n "${PICOCHESS_KIOSK_URL:-}" ]; then
    printf '%s\n' "$PICOCHESS_KIOSK_URL"
    return
  fi

  port="$(configured_web_port)"
  [ -n "$port" ] || port=80
  case "$port" in
    *[!0-9]*)
      port=80
      ;;
  esac

  for _ in 1 2 3 4 5; do
    if port_open "$port"; then
      break
    fi
    if [ "$port" = "80" ] && port_open 8080; then
      port=8080
      break
    fi
    sleep 1
  done

  if [ "$port" = "80" ]; then
    printf '%s\n' "http://127.0.0.1"
  else
    printf '%s\n' "http://127.0.0.1:$port"
  fi
}

service_active() {
  systemctl is-active --quiet "$PICOCHESS_SERVICE"
}

show_update_status() {
  if display_ready; then
    if update_pending || systemctl is-active --quiet picochess-update.service; then
      if [ -z "${UPDATE_TERM_PID:-}" ] || ! kill -0 "$UPDATE_TERM_PID" 2>/dev/null; then
        TERM_CMD="$(terminal_cmd)"
        if [ -n "$TERM_CMD" ]; then
          eval "$TERM_CMD" &
          UPDATE_TERM_PID=$!
          NO_TERM_NOTICE_SENT=""
        else
          if [ -z "${NO_TERM_NOTICE_SENT:-}" ]; then
            notify_no_terminal
            NO_TERM_NOTICE_SENT="1"
          fi
        fi
      fi
    else
      close_update_terminal
      NO_TERM_NOTICE_SENT=""
    fi
  fi
}

wait_for_picochess() {
  while ! service_active; do
    show_update_status
    /bin/sleep "$STARTUP_POLL_INTERVAL"
  done
  close_update_terminal
}

prepare_kiosk_profile() {
  mkdir -p "$KIOSK_PROFILE_DIR/Default"
  if [ -f "$KIOSK_PROFILE_DIR/Local State" ]; then
    sed -i 's/"exited_cleanly":false/"exited_cleanly":true/' "$KIOSK_PROFILE_DIR/Local State"
  fi
  if [ -f "$KIOSK_PROFILE_DIR/Default/Preferences" ]; then
    sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/' "$KIOSK_PROFILE_DIR/Default/Preferences"
  fi
}

launch_kiosk_browser() {
  local picochess_url
  picochess_url="$(picochess_url)"
  prepare_kiosk_profile

  if is_wayland; then
    "$CHROMIUM_BIN" --user-data-dir="$KIOSK_PROFILE_DIR" --no-first-run --password-store=basic --kiosk "$picochess_url" &
  else
    "$CHROMIUM_BIN" --user-data-dir="$KIOSK_PROFILE_DIR" --no-first-run --enable-features=OverlayScrollbar --password-store=basic --display=:0 --noerrdialogs --disable-infobars --kiosk "$picochess_url" &
  fi
  CHROMIUM_PID=$!
  echo "kiosk.sh: Chromium started with pid $CHROMIUM_PID"
}

close_kiosk_browser() {
  local attempt

  if [ -z "$CHROMIUM_PID" ]; then
    return
  fi

  if kill -0 "$CHROMIUM_PID" 2>/dev/null; then
    echo "kiosk.sh: stopping Chromium pid $CHROMIUM_PID"
    kill "$CHROMIUM_PID" 2>/dev/null
    for attempt in 1 2 3 4 5 6 7 8 9 10; do
      if ! kill -0 "$CHROMIUM_PID" 2>/dev/null; then
        break
      fi
      /bin/sleep 0.2
    done
    if kill -0 "$CHROMIUM_PID" 2>/dev/null; then
      kill -KILL "$CHROMIUM_PID" 2>/dev/null
    fi
  fi
  wait "$CHROMIUM_PID" 2>/dev/null
  CHROMIUM_PID=""
}

monitor_kiosk_browser() {
  while service_active; do
    if ! kill -0 "$CHROMIUM_PID" 2>/dev/null; then
      wait "$CHROMIUM_PID" 2>/dev/null
      CHROMIUM_PID=""
      return 1
    fi
    /bin/sleep "$SERVICE_POLL_INTERVAL"
  done
  return 0
}

cleanup() {
  close_kiosk_browser
  close_update_terminal
}

trap cleanup EXIT
trap 'exit 0' HUP INT TERM

# Keep ownership of the kiosk browser for the desktop session. When PicoChess
# stops, close only this Chromium process. If the service is started again,
# launch a fresh kiosk without touching any normal Chromium session.
while true; do
  wait_for_picochess
  launch_kiosk_browser
  if monitor_kiosk_browser; then
    echo "kiosk.sh: PicoChess stopped; closing Chromium"
    close_kiosk_browser
  else
    echo "kiosk.sh: Chromium exited while PicoChess was running"
    exit 0
  fi
done
