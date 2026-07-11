# Project Recap - Integrating the Saitek/Mephisto OSA board into picochess v4

## Goal

Connect a **Saitek / Mephisto OSA** board over **Bluetooth** (bound to
`/dev/rfcomm0`) as an e-chess board in picochess v4, the same way the Novag
Citrine was integrated — same two driver objects, same hook points in
picochess — but speaking the **OSA serial protocol** instead of the Novag one.

> The Citrine lives on `/dev/rfcomm1`; the OSA board takes `/dev/rfcomm0`, so
> both can coexist.

This project is the OSA twin of the Citrine project. Everything that was
`CITRINE`/`Novag*`/`/dev/rfcomm1` there becomes `OSA`/`Osa*`/`/dev/rfcomm0`
here. The single real difference is the wire protocol, captured in `LOG OSA.txt`
and implemented in `board.py`.

---

## The "OSA" naming convention

| Element | Value | Freely renamable? |
|---|---|---|
| Driver classes | `OsaBoard`, `OsaDisplay` | No (referenced by the imports in `picochess.py`) |
| Helper functions | `_uci_to_osa`, `_osa_to_move` | No, unless renamed on both sides |
| Internal attribute/parameter | `osa_board` / `self._osa_board` | Yes (internal to `board.py`) |
| **Enum member name** | `EBoard.OSA` | Must match the `.ini` |
| Enum member value | `"B00_eboard_osa_menu"` | Used for menu/translation |
| **`.ini` token** | `board-type = osa` | Must match the member name |
| Web label | `"Saitek OSA"` | Cosmetic |

### Critical point (same trap as Citrine): `EBoard[...]` is a lookup **BY NAME**

In `picochess.py` (`async def main()`):

```python
board_type = dgt.util.EBoard[args.board_type.upper()]   # lookup by member NAME
```

For the OSA board to connect, **three elements must all say "osa"**:

1. `dgt/util.py` -> the **member name** is `OSA`
2. `picochess.ini` -> `board-type = osa`
3. `picochess.py` -> references `EBoard.OSA`

If any diverges: a missing member name raises `AttributeError` (crash at
startup); an unresolved `.ini` token raises `KeyError` and **silently falls
back to DGT** (the OSA board is never loaded, with no error message).

---

## The OSA protocol (from `LOG OSA.txt`)

**Serial**: `9600 baud · 8 data bits · 1 stop bit · no parity · no flow control`.
The link is **Bluetooth SPP**, bound to `/dev/rfcomm0` (the Citrine uses
`/dev/rfcomm1`). Over rfcomm the baud rate is handled by the Bluetooth stack;
9600 is kept only to match the board's announced setting.

**Handshake**: `OPEN` (board replies `- Saitek OSA (9600 baud), Version 1.4 -`)
-> `NEW` (board replies `New Game`) -> `ANALYSIS`. `ANALYSIS` is OSA's
"external engine / referee" mode: the board's own engine stays silent and the
board only reports the human's moves. It is the equivalent of the Citrine's
`Uon`.

**One full ply** (engine answering a human move), exactly as logged:

```
(human plays)                 board -> "  2. e4-e5   00:31"
BOARD OFF                     PC    ->  disarm the board
MOVE D7-D5                    PC    ->  inject the engine's reply
BOARD ON                      PC    ->  light up the move
NORMAL                        PC    ->
ANALYSIS                      PC    ->  re-arm for the next human move
```

**Move notation, board -> PC**
- pawn `e2-e4`, piece `Bf1-b5` / `Qd8xd6` / `Ng1-e2`
- capture `x`, en passant `ep` (`e5xd6ep`), castling `O-O` / `O-O-O`
- check `+`, checkmate `++`, result line `1-0` / `0-1` / `1/2-1/2`
- White moves carry a leading `N.` number and Black moves do not — this is
  only a display column, **never** a human-vs-engine indicator.

**Move command, PC -> board**: `MOVE <FROM>-<TO>` in UPPERCASE
(`MOVE E7-E6`, `MOVE O-O`, `MOVE E7-E8/Q`). The board **echoes** the injected
move back as a normal move line; the driver discards that echo via a
turn-independent move *signature*.

**Buttons**: `New Game` (board's NEW GAME key) and `Takeback` (one line per
ply taken back, occasionally garbled e.g. `TTTTTakeback`).

---

## NEW files

### `/opt/picochess/eboard/osa/__init__.py`
Empty — Python package marker.

### `/opt/picochess/eboard/osa/board.py`
Full driver. Contains:

- `OsaBoard` — async serial connection (`OPEN`/`NEW`/`ANALYSIS`), reading human
  moves, injecting engine moves with the `BOARD OFF · MOVE · BOARD ON · NORMAL ·
  ANALYSIS` choreography.
- `OsaDisplay` — intercepts `COMPUTER_MOVE` and forwards it to the board
  (attribute renamed to `osa_board` / `self._osa_board`); on `PLAY_MODE` it
  records the user's colour.
- Echo suppression via `_move_signature` (compares `E7E6`/`OO`/`E7E8Q`
  signatures, so the engine's echoed move is never mistaken for a human move).
- `Event.NEW_GAME(pos960=518)` when the board reports `New Game` — the user
  reset the pieces to the starting position (or pressed NEW GAME); re-arms
  `ANALYSIS`.
- `Event.TAKE_BACK(take_back="TAKEBACK")` when the board reports `Takeback` —
  the user physically played a move backwards on the board. Compatible with the
  picochess take-back path validated for the Citrine.
- No-op stubs for every method of the `EBoard` protocol.
- A 2-second grace window after connect so the `New Game` the board echoes in
  reply to our own `NEW` is **not** re-fired as a button event.

> All parser/encoder/echo cases were unit-tested against the exact lines in
> `LOG OSA.txt` (e2-e4, e5xd6ep, Qd8xd6, Bf1-b5+, Ke7-f6, O-O, Qh5-g5++, …) and
> pass.

### `/etc/systemd/system/rfcomm_osa.service`

Binds the OSA board to `/dev/rfcomm0` at startup (analogous to the Citrine's
`rfcomm_citrine.service` on `/dev/rfcomm1`). **Replace the MAC address** with
your OSA board's address:

```ini
[Unit]
Description=Bind Saitek OSA (XX:XX:XX:XX:XX:XX) to /dev/rfcomm0
After=bluetooth.target bluetooth-mesh.target
Requires=bluetooth.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/bin/sleep 5
ExecStart=/usr/bin/rfcomm bind 0 XX:XX:XX:XX:XX:XX
ExecStop=/usr/bin/rfcomm release 0
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

> Note the channel/device number is **0** (`rfcomm bind 0 …` -> `/dev/rfcomm0`),
> versus **1** for the Citrine. If both boards are used, keep both services.

---

## MODIFIED files (identical pattern to the Citrine, with `OSA`)

### `/opt/picochess/dgt/util.py`
Add the `OSA` member to `EBoard` (the **member name** is what must match
`board-type = osa`):

```python
class EBoard(MyEnum):
    CERTABO   = "B00_eboard_certabo_menu"
    CHESSLINK = "B00_eboard_chesslink_menu"
    CHESSNUT  = "B00_eboard_chessnut_menu"
    DGT       = "B00_eboard_dgt_menu"
    ICHESSONE = "B00_eboard_ichessone_menu"
    CITRINE   = "B00_eboard_citrine_menu"
    OSA       = "B00_eboard_osa_menu"          # <- ADDED (name = OSA)
    NOEBOARD  = "B00_eboard_noeboard_menu"

    @classmethod
    def items(cls):
        return [EBoard.CERTABO, EBoard.CHESSLINK, EBoard.CHESSNUT,
                EBoard.DGT, EBoard.ICHESSONE, EBoard.CITRINE,
                EBoard.OSA, EBoard.NOEBOARD]    # <- OSA added
```

### `/opt/picochess/dgt/translate.py`
Add the `eboard_osa_menu` block (text_id derives from the enum value with the
`B00_` prefix stripped), before `eboard_noeboard_menu`:

```python
if text_id == "eboard_osa_menu":
    entxt = Dgt.DISPLAY_TEXT(
        web_text="Saitek OSA",
        large_text="Saitek OSA",
        medium_text="osa     ",
        small_text="osa  ",
    )
    detxt = entxt
    nltxt = entxt
    frtxt = entxt
    estxt = entxt
    ittxt = entxt
```

### `/opt/picochess/configuration.py`
Add `"osa"` to the `--board-type` help text (cosmetic):

```
'Type of e-board: "dgt", "certabo", "chesslink", "chessnut", "ichessone",
 "citrine", "osa" or "noeboard" ...'
```

### `/opt/picochess/picochess.py`

1. Imports:

```python
from eboard.osa.board import OsaBoard
from eboard.osa.board import OsaDisplay
```

2. `elif` block in `async def main()`:

```python
elif board_type == dgt.util.EBoard.OSA:
    dgtboard = OsaBoard(main_loop)
    if args.dgt_port:
        connected = await dgtboard.connect(args.dgt_port)
        if not connected:
            logger.error("OsaBoard: cannot connect on %s", args.dgt_port)
    else:
        logger.error("OsaBoard: no port defined (dgt-port missing)")
```

3. Instantiate the consumer after `my_pgn_display` (positional call):

```python
if board_type == dgt.util.EBoard.OSA:
    my_osa_display = OsaDisplay(dgtboard, main_loop)
    non_main_tasks.add(asyncio.create_task(my_osa_display.message_consumer()))
```

4. **Add `OSA` to the existing CITRINE block in the `Event.SWITCH_SIDES`
   handler** so the engine plays the first move when the user switches to
   Black. The OSA board, like the Citrine, is driven by `KEYBOARD_MOVE`
   events (not a continuous FEN stream), so the `newgame_happened` flag never
   gets cleared by `process_fen` and the engine's first move would be discarded
   as "stale":

```python
                    if cond1 or cond2:
                        # Citrine + OSA are move-event driven (no FEN stream),
                        # so clear the new-game flag here or EVT_BEST_MOVE
                        # discards the engine's first move as "stale".
                        if self.board_type in (dgt.util.EBoard.CITRINE,
                                                dgt.util.EBoard.OSA):
                            self.state.newgame_happened = False
                        self.state.time_control.reset_start_time()
                        await self.think(msg)  # PLAY_MODE
```

### `/opt/picochess/server.py`

1. Web footer label — add the `OSA` entry to `_eboard_labels`:

```python
_eboard_labels = {
    _dgt_util.EBoard.DGT:       "DGT",
    _dgt_util.EBoard.CERTABO:   "Certabo",
    _dgt_util.EBoard.CHESSLINK: "ChessLink",
    _dgt_util.EBoard.CHESSNUT:  "Chessnut",
    _dgt_util.EBoard.ICHESSONE: "iChessOne",
    _dgt_util.EBoard.CITRINE:   "Novag Citrine",
    _dgt_util.EBoard.OSA:       "Saitek OSA",      # <- ADDED
    _dgt_util.EBoard.NOEBOARD:  "No e-board",
}
```

2. Web board selector whitelist — add `"osa"` (otherwise selecting it in the
   web *Settings* page is silently ignored):

```python
_valid_eboards = {"dgt", "certabo", "chesslink", "chessnut",
                  "ichessone", "citrine", "osa", "none"}
```

> Also check the matching `<select>` in the template offers the `osa` option.

### `/opt/picochess/picochess.ini`

```ini
board-type = osa
dgt-port   = /dev/rfcomm0
```

> The `board-type` line must be **uncommented** and in the correct section, or
> picochess silently falls back to DGT.

### `/etc/systemd/system/picochess.service`

Add the dependency on the OSA rfcomm service in `[Unit]` (same idea as the
Citrine; if you use both boards, list both services):

```ini
After=multi-user.target rfcomm_osa.service
Wants=rfcomm_osa.service
```

> The serial device only exists once the board is bound, so make sure the
> rfcomm service runs first. Run picochess as a user in the `dialout` group or
> as root so it can open `/dev/rfcomm0`.

---

## Differences from the Citrine driver (at a glance)

| | Citrine | OSA |
|---|---|---|
| Baud | 57 600 | **9 600** |
| Link | Bluetooth (`/dev/rfcomm1`) | **Bluetooth** (`/dev/rfcomm0`) |
| Handshake | `Xon` · `N` · `Uon`×2 | **`OPEN` · `NEW` · `ANALYSIS`** |
| Referee mode | `Uon` | **`ANALYSIS`** |
| Inject move | `m<move>` (sent twice) | **`MOVE <FROM>-<TO>` + `BOARD ON`/`NORMAL`** |
| Move in | `M e2-e4` | **`  N. e2-e4   00:00`** (number/time stripped) |
| Take-back | `T x x` | **`Takeback`** |
| Board flip | `F` command | **none** (read board from the other side) |
| Startup service | `rfcomm_citrine.service` (rfcomm 1) | **`rfcomm_osa.service` (rfcomm 0)** |

---

## Validated (logic / unit tests)

- [OK] Move parsing for every line type in `LOG OSA.txt`
  (pawn, piece, capture, en passant, check, mate, O-O, O-O-O)
- [OK] Engine-move encoding (`E2-E4`, `G1-F3`, `O-O`, `O-O-O`, `G7-G8/Q`)
- [OK] Echo suppression (injected move vs the board's echoed display line)

## To validate on hardware

- [FIX] **Line terminator** — the driver sends CRLF (`_EOL = "\r\n"`). If the
  board does not respond, try bare CR (`_EOL = "\r"`).
- [FIX] **`PLAY` at game start when the user is Black** — the log shows an extra
  `PLAY` (and `BOARD OFF`) before the engine's very first White move. The driver
  relies on the normal `send_move` choreography (`BOARD OFF` is sent there); if
  the engine's first move is not accepted when the user plays Black, send `PLAY`
  once before that first `MOVE` (in `set_computer_color`).
- [FIX] **Engine castling / promotion command syntax** — the log never shows the
  *engine* castling or promoting. The driver sends `MOVE O-O` / `MOVE O-O-O` /
  `MOVE E7-E8/Q`. Confirm the board accepts these (watch for a `???` reply).
- [FIX] **Rejected-move `???`** — currently only logged. In the log a `???`
  cleared up after a `POSITION` re-sync; if you see repeated `???`, add a
  `POSITION` query + retry in `send_move`.

---

## Useful commands

### Manual startup (debug)

```bash
sudo systemctl stop picochess.service
sudo rfcomm bind 0 XX:XX:XX:XX:XX:XX        # your OSA board's MAC
cd /opt/picochess && sudo /opt/picochess/venv/bin/python3 picochess.py \
    --board-type osa --dgt-port /dev/rfcomm0 --log-level debug --log-file pico.log
```

> If the board connects with `--board-type osa` on the CLI but not via the
> `.ini`, the problem is in `picochess.ini` (commented line, missing line, or
> wrong section).

### Bind / check the Bluetooth serial port

```bash
sudo rfcomm bind 0 XX:XX:XX:XX:XX:XX    # create /dev/rfcomm0
rfcomm                                  # list current bindings
ls -l /dev/rfcomm0                      # device present?
```

### Pairing the OSA board (one time only)

```bash
sudo bluetoothctl
  agent on
  scan on
  pair XX:XX:XX:XX:XX:XX     # your OSA board's MAC; enter its PIN if asked
  trust XX:XX:XX:XX:XX:XX
  quit
```

> Find the MAC with `scan on` in `bluetoothctl` (the board must be powered and
> discoverable). Many Saitek/Mephisto boards use a simple PIN such as `0000` or
> `1234` — check your board.

### Check naming consistency

```bash
grep -nE "OSA"        /opt/picochess/dgt/util.py       # member name = OSA
grep -i  "board-type" /opt/picochess/picochess.ini      # = osa, uncommented
grep -nE "OSA"        /opt/picochess/picochess.py       # EBoard.OSA
```

### Watch the logs

```bash
tail -f /opt/picochess/logs/pico.log | grep -i "osaboard\|human\|forward\|move\|???"
```

---

## Reverting to a DGT board

```ini
board-type = dgt
dgt-port   = /dev/ttyACM0
```
