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

# This will wait for PicoChess to start before launching the browser
while true; do
  systemctl is-active --quiet picochess
  if [ $? -eq 0 ]; then
    if is_wayland; then
      /usr/bin/chromium --password-store=basic --kiosk http://127.0.0.1 &
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
