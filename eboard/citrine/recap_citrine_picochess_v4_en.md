# Project Summary — Novag Citrine Integration into picochess v4

*Date: November 7, 2026*

## Goal
Connect the Novag Citrine over Bluetooth (`/dev/rfcomm1`) or over a USB cable (`/dev/ttyUSB0`)
as an e-chess board in picochess v4, replacing or complementing the DGT board.

---

## Setup checklist

1. Create the driver (`eboard/citrine/`)
2. Register the board (`dgt/util.py`, `dgt/translate.py`)
3. Wire it into `picochess.py`
4. Update `server.py` (web label + selector whitelist)
5. Configure `picochess.ini`
6. Connect the board (USB **or** Bluetooth)
7. Test

> **Naming rule:** `EBoard.CITRINE` (member name in `util.py`), `board-type = citrine` (in the
> `.ini`) and the references in `picochess.py` must all say "citrine". The lookup is
> `EBoard[args.board_type.upper()]`, i.e. by **name**. If the `.ini` token does not resolve,
> picochess **silently falls back to DGT**.

---

## 1. New files

### `/opt/picochess/eboard/citrine/__init__.py`
Empty file (Python package marker).

### `/opt/picochess/eboard/citrine/board.py`
Citrine driver. Class names stay `NovagBoard` and `NovagDisplay` (imported by `picochess.py`).
- `NovagBoard`: async serial connection, reads moves, sends engine moves
- `NovagDisplay`: intercepts `COMPUTER_MOVE` and forwards it to the Citrine
- Connection sequence, in this order: `Xon` ×2 → `I` → `N` → `Uon` ×2
  (`N` resets Referee mode, so `Uon` must come after it)
- Re-send `Uon` after every `New Game` received
- Send the engine move twice (e.g. `mb8c6` ×2) to activate the LEDs
- `pos960=518` to start in standard chess
- Take-back: `TAKE_BACK(take_back="TAKEBACK")`
- No-op stubs for the other methods of the `EBoard` protocol
- Board flip with `F` (toggle) when the user plays Black:
  - `set_computer_color(computer_white)` sends `F` only if the orientation changes
  - `computer_white = (mode == PlayMode.USER_BLACK)` on `PLAY_MODE`
  - lock the orientation (`_orientation_locked = True`) at the first human move, otherwise each
    take-back re-emits `PLAY_MODE` and flips the board; reset the lock on new game / New Game button
  - if the board is physically flipped when playing White, use `mode == PlayMode.USER_WHITE`

---

## 2. Register the board

### `/opt/picochess/dgt/util.py`
Add the member to `EBoard` and to `items()`:
```python
class EBoard(MyEnum):
    ...
    CITRINE   = "B00_eboard_citrine_menu"
    NOEBOARD  = "B00_eboard_noeboard_menu"

    @classmethod
    def items(cls):
        return [EBoard.CERTABO, EBoard.CHESSLINK, EBoard.CHESSNUT,
                EBoard.DGT, EBoard.ICHESSONE, EBoard.CITRINE, EBoard.NOEBOARD]
```

### `/opt/picochess/dgt/translate.py`
Add before the `eboard_noeboard_menu` block (the text_id must be `eboard_citrine_menu`):
```python
if text_id == "eboard_citrine_menu":
    entxt = Dgt.DISPLAY_TEXT(
        web_text="Novag Citrine",
        large_text="Nov Citrin",
        medium_text="citrin  ",
        small_text="citri",
    )
    detxt = entxt
    nltxt = entxt
    frtxt = entxt
    estxt = entxt
    ittxt = entxt
```

---

## 3. `/opt/picochess/picochess.py`

**Imports:**
```python
from eboard.citrine.board import NovagBoard
from eboard.citrine.board import NovagDisplay
```

**Board creation** in `async def main()`:
```python
elif board_type == dgt.util.EBoard.CITRINE:
    dgtboard = NovagBoard(main_loop)
    if args.dgt_port:
        connected = await dgtboard.connect(args.dgt_port)
        if not connected:
            logger.error("NovagBoard: cannot connect on %s", args.dgt_port)
    else:
        logger.error("NovagBoard: no port defined (dgt-port missing)")
```

**Consumer**, after `my_pgn_display`:
```python
if board_type == dgt.util.EBoard.CITRINE:
    my_novag_display = NovagDisplay(dgtboard, main_loop)
    non_main_tasks.add(asyncio.create_task(my_novag_display.message_consumer()))
```

**`Event.SWITCH_SIDES` handler** (`NORMAL`/`BRAIN`/`TRAINING` branch). Without it, the engine's
first move is discarded as "stale" when the user switches to Black before playing:
```python
if cond1 or cond2:
    if self.board_type == dgt.util.EBoard.CITRINE:
        self.state.newgame_happened = False
    self.state.time_control.reset_start_time()
    await self.think(msg)  # PLAY_MODE
```

---

## 4. `/opt/picochess/server.py`

**Web label:** add the Citrine to `_eboard_labels`:
```python
_dgt_util.EBoard.CITRINE:   "Novag Citrine",
```

**Web selector whitelist** (`action == "eboard"`): add `citrine`, otherwise selecting it in the
web Settings page is silently ignored:
```python
_valid_eboards = {"dgt", "certabo", "chesslink", "chessnut", "ichessone", "citrine", "none"}
```
Also check that the `<select>` in the template offers the `citrine` option.

---

## 5. `/opt/picochess/picochess.ini`
The `board-type` line must be uncommented and in the right section.

**USB cable (Prolific):**
```ini
board-type = citrine
dgt-port   = /dev/ttyUSB0
```
**Bluetooth:**
```ini
board-type = citrine
dgt-port   = /dev/rfcomm1
```

---

## 6. Connect the board

### Option A: USB cable
Plug in the Prolific cable and set `dgt-port = /dev/ttyUSB0`. Nothing else is needed.

### Option B: Bluetooth

**Pair once:**
```bash
sudo bluetoothctl
  agent on
  scan on
  pair XX:XX:XX:XX:XX:XX    # PIN : XXXX
  trust XX:XX:XX:XX:XX:XX
  quit
```

**`/etc/systemd/system/rfcomm_citrine.service`** (binds the Citrine to `/dev/rfcomm1` at boot):
```ini
[Unit]
Description=Bind Novag Citrine (XX:XX:XX:XX:XX:XX) to /dev/rfcomm1
After=bluetooth.target bluetooth-mesh.target
Requires=bluetooth.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/bin/sleep 5
ExecStart=/usr/bin/rfcomm bind 1 XX:XX:XX:XX:XX:XX
ExecStop=/usr/bin/rfcomm release 1
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/picochess.service`**, in `[Unit]`:
```ini
After=multi-user.target rfcomm_citrine.service
Wants=rfcomm_citrine.service
```

---

## 7. Test

**Manual start (debug):**
```bash
sudo systemctl stop picochess.service
# Bluetooth only: sudo rfcomm bind 1 XX:XX:XX:XX:XX:XX
cd /opt/picochess && sudo /opt/picochess/venv/bin/python3 picochess.py \
    --board-type citrine --dgt-port /dev/ttyUSB0 --log-level debug --log-file pico.log
```
(use `/dev/rfcomm1` for Bluetooth). If it works with `--board-type citrine` on the command
line but not via the `.ini`, the problem is in `picochess.ini`.

**Check naming consistency:**
```bash
grep -nE "NOVAG|CITRINE" /opt/picochess/dgt/util.py      # member name = CITRINE
grep -i  "board-type"     /opt/picochess/picochess.ini    # = citrine, not commented
grep -nE "CITRINE"        /opt/picochess/picochess.py     # EBoard.CITRINE
```

**Follow the logs** (engine's first move and flip):
```bash
tail -f /opt/picochess/logs/pico.log | grep -i \
    "discarding stale engine move\|SWITCH_SIDES\|COMPUTER_MOVE\|'F' sent\|PLAY_MODE"
```
- `'F' sent — computer_is_white=True` should appear when switching to Black
- `discarding stale engine move` at the switch means the `SWITCH_SIDES` block is missing or wrong

---

## Switching back to the DGT board
In `/opt/picochess/picochess.ini`:
```ini
board-type = dgt
dgt-port   = /dev/ttyACM0
```
