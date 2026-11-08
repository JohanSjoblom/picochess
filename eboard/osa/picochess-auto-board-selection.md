# Auto-selecting the connected chess board at boot (picochess)

## Objective

On a Raspberry Pi running picochess v4 with three different electronic boards
(Saitek **OSA**, Novag **Citrine**, **DGT**), make picochess start automatically
with whichever board is actually powered on, without editing `picochess.ini` by
hand before every session. If no board is detected at boot, fall back to a
boardless mode (`noeboard`) instead of failing.

## How it works

Each board is bound to a fixed `/dev/rfcommN` device by its own systemd unit
(`rfcomm_*.service`). A new oneshot unit, `picochess-select-board.service`, runs
**before** `picochess.service`. It detects which board is present, rewrites the
`board-type` and `dgt-port` lines in `picochess.ini` accordingly, and only then
lets picochess start.

Detection uses `l2ping` against each board's Bluetooth MAC. This is deliberate:
`rfcomm bind` only creates the device node; the actual SPP connection is not
established until picochess opens the port. As a result, connection-state checks
(e.g. `bluetoothctl info … | grep "Connected: yes"`) report "no" for every board
at boot. `l2ping` instead tests **presence** (powered on and in range), which is
available before any port is opened.

## Board mapping

The port assignments follow the `rfcomm bind` commands in the existing
`rfcomm_*.service` files (this is the source of truth):

| Board   | Bluetooth MAC       | Device node   | `board-type` |
|---------|---------------------|---------------|--------------|
| OSA     | `XX:XX:XX:XX:XX:XX` | `/dev/rfcomm0` | `osa`        |
| Citrine | `XX:XX:XX:XX:XX:XX` | `/dev/rfcomm1` | `citrine`    |
| DGT     | `XX:XX:XX:XX:XX:XX` | `/dev/rfcomm2` | `dgt`        |
| (none)  | —                   | unchanged      | `noeboard`   |

A single `picochess.ini` key, `dgt-port`, holds the device path for all three
boards; only its value changes per board.

## Components

### 1. `/opt/picochess/select-board.sh`

Detects the present board and updates `picochess.ini`. Run as **root** (so
`l2ping` has the required privileges).

```bash
#!/usr/bin/env bash
set -euo pipefail
INI=/opt/picochess/picochess.ini

declare -A TYPE                      # replace XX:XX… with your real MACs (bluetoothctl devices)
TYPE["XX:XX:XX:XX:XX:XX"]=osa        # rfcomm0
TYPE["XX:XX:XX:XX:XX:XX"]=citrine    # rfcomm1
TYPE["XX:XX:XX:XX:XX:XX"]=dgt        # rfcomm2

declare -A PORT
PORT[osa]=/dev/rfcomm0
PORT[citrine]=/dev/rfcomm1
PORT[dgt]=/dev/rfcomm2

ROUNDS=5         # detection passes (raise if a board powers on late)
PING_TIMEOUT=2   # seconds per l2ping attempt

selected=""
for _ in $(seq 1 "$ROUNDS"); do
  for mac in "${!TYPE[@]}"; do
    if l2ping -c 1 -t "$PING_TIMEOUT" "$mac" &>/dev/null; then
      selected="$mac"; break
    fi
  done
  [ -n "$selected" ] && break
  sleep 1
done

btype="${selected:+${TYPE[$selected]}}"
btype="${btype:-noeboard}"

# Replace only the FIRST matching line in the file (GNU sed 0,/re/ idiom).
sed -i -E "0,/^[#; ]*board-type[[:space:]]*=.*/ s||board-type = ${btype}|" "$INI"
if [ "$btype" != noeboard ]; then
  sed -i -E "0,/^[#; ]*dgt-port[[:space:]]*=.*/ s||dgt-port = ${PORT[$btype]}|" "$INI"
fi

echo "select-board: board-type=${btype} dgt-port=${PORT[$btype]:-none}"
```

Notes on the `sed`:
- The `0,/regex/ s||…|` form restricts the substitution to the first matching
  line in the whole file (avoids touching commented example lines elsewhere).
- The `|` delimiter on `s` avoids escaping the `/` in `/dev/rfcommN`.
- The `^[#; ]*` prefix also un-comments the line if it was commented out.

### 2. `/etc/systemd/system/picochess-select-board.service`

Oneshot unit, runs as root, ordered before picochess.

```ini
[Unit]
Description=Select chess board and update picochess.ini
After=bluetooth.service rfcomm_osa.service rfcomm_citrine.service rfcomm_dgt.service
Wants=rfcomm_osa.service rfcomm_citrine.service rfcomm_dgt.service
Before=picochess.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/opt/picochess/select-board.sh

[Install]
WantedBy=multi-user.target
```

`Active: inactive (dead)` between boots is normal for a oneshot — it only runs at
boot (just before picochess) or when started manually.

### 3. `/etc/systemd/system/picochess.service` (changes)

The `[Unit]` section was cleaned (duplicate lines removed) and given a dependency
on the new unit. The three `rfcomm_*` services are kept as `Wants=`/`After=`:
they create the `/dev/rfcommN` nodes that picochess opens, which is a separate
job from detection. `Wants=` (not `Requires=`) is intentional so a powered-off
board cannot block boot.

```ini
[Unit]
Description=PicoChess Chess Program
After=multi-user.target
After=picochess-update.service
After=rfcomm_osa.service rfcomm_citrine.service rfcomm_dgt.service
After=picochess-select-board.service
Wants=picochess-update.service
Wants=gamesdb.service
Wants=rfcomm_osa.service rfcomm_citrine.service rfcomm_dgt.service
Wants=picochess-select-board.service

[Service]
TimeoutStopSec=15s
Environment="DISPLAY=:0"
Environment="XAUTHORITY=/home/pi/.Xauthority"
Environment="XDG_RUNTIME_DIR=/run/user/1000"
User=pi
Group=pi
Type=simple
ExecStart=/opt/picochess/venv/bin/python3 /opt/picochess/picochess.py
ExecStop=/usr/bin/pkill -f picochess.py
ExecStop=/usr/bin/pkill -9 -f mess
WorkingDirectory=/opt/picochess/

[Install]
WantedBy=multi-user.target
```

## Deployment

```bash
# 1. Script
sudo cp select-board.sh /opt/picochess/select-board.sh
sudo chown root:root /opt/picochess/select-board.sh
sudo chmod 755 /opt/picochess/select-board.sh

# 2. New unit
sudo cp picochess-select-board.service /etc/systemd/system/
sudo chown root:root /etc/systemd/system/picochess-select-board.service
sudo chmod 644 /etc/systemd/system/picochess-select-board.service

# 3. Updated picochess.service (overwrite cleanly to avoid duplicate stanzas)
sudo cp picochess.service /etc/systemd/system/picochess.service

# 4. Register and enable
sudo systemctl daemon-reload
sudo systemctl enable picochess-select-board.service
sudo systemctl enable picochess.service

# Dependency required by detection:
which l2ping || sudo apt install -y bluez
```

When pasting unit/script content into a root-owned directory, a `sudo tee … << 'EOF'`
heredoc works where a plain copy-paste is denied:

```bash
sudo tee /etc/systemd/system/picochess.service > /dev/null << 'EOF'
... file content ...
EOF
```

## Verification

```bash
# Manual dry run with a board powered on — should print osa/citrine/dgt, not noeboard
sudo /opt/picochess/select-board.sh

# Both units enabled
systemctl is-enabled picochess.service               # -> enabled
systemctl list-unit-files | grep -i picochess

# After a reboot, confirm detection wrote the right values
grep -E "^board-type|^dgt-port" /opt/picochess/picochess.ini
journalctl -u picochess-select-board.service -b --no-pager
journalctl -u picochess.service -b --no-pager
```

A correct boot log looks like:

```
select-board.sh[…]: select-board: board-type=dgt dgt-port=/dev/rfcomm2
Finished picochess-select-board.service ...
```
