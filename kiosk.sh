#!/bin/bash

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

if [ -d "/home/$USER/.config/chromium/Default" ]; then
  sed -i 's/"exited_cleanly":false/"exited_cleanly":true/' /home/$USER/.config/chromium/'Local State'
  sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/' /home/$USER/.config/chromium/Default/Preferences
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
    pkill -u "$USER" -f "xterm -fullscreen.*-title Updating..." 2>/dev/null
    pkill -u "$USER" -f "tail -F /var/log/picochess-update.log" 2>/dev/null
  fi
  UPDATE_TERM_PID=""
}

# This will wait for PicoChess to start before launching the browser
while true; do
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

  systemctl is-active --quiet picochess
  if [ $? -eq 0 ]; then
    close_update_terminal
    if is_wayland; then
      /usr/bin/chromium --touch-events=enabled --enable-features=TouchpadOverscrollHistoryNavigation --password-store=basic --kiosk http://127.0.0.1 &
    else
      /usr/bin/chromium --enable-features=OverlayScrollbar --password-store=basic --display=:0 --noerrdialogs --disable-infobars --kiosk http://127.0.0.1 &
    fi
    exit 0
  else
    /bin/sleep 5
  fi
done

# This section will enable a refresh by chromium every 'sleep xx' seconds.
#
#while true; do
#  xdotool keydown ctrl+r; xdotool keyup ctrl+r;
#  sleep 20
#done
