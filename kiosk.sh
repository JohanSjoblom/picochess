#!/bin/bash

xset s noblank
xset s off
xset -dpms

unclutter -idle 0.5 -root &

if [ -d "/home/$USER/.config/chromium/Default" ] 
then
    sed -i 's/"exited_cleanly":false/"exited_cleanly":true/' /home/$USER/.config/chromium/'Local State'
    sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/' /home/$USER/.config/chromium/Default/Preferences
fi

#  This will wait for PicoChess to start before launching the browser

while true; do
  systemctl is-active --quiet picochess
  if [ $? -eq 0 ]; then
    /usr/bin/chromium --enable-features=OverlayScrollbar --password-store=basic --display=:0 --noerrdialogs --disable-infobars --kiosk http://127.0.0.1 &
    exit 0
  else
    /bin/sleep 5
  fi
done

#  This setion will enable a refresh by chromium every 'sleep xx' seconds.
#
#while true; do
#   xdotool keydown ctrl+r; xdotool keyup ctrl+r;
#   sleep 20
#done

