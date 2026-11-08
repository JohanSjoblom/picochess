# Project Recap — Saitek / Mephisto OSA board in picochess v4

*Date: November 7, 2026*

## Goal

Connect a **Saitek / Mephisto OSA** board over Bluetooth SPP (bound to `/dev/rfcomm0`) as an
e-board in picochess v4 — the OSA twin of the Novag Citrine integration: same two driver
objects, same picochess hook points, but speaking the **OSA serial protocol**.

The OSA interface is the one exposed by the modular Saitek "Kasparov" boards that accept a
plug-in module and expose the serial/OSA port: **Leonardo**, **Galileo** and **Renaissance**.
The board announces itself as `- Saitek OSA (9600 baud), Version 1.4 -`.

The Citrine lives on `/dev/rfcomm1`; the OSA board takes `/dev/rfcomm0`, so both can coexist.

The only real difference vs the Citrine is the wire protocol (in `board.py`). Everything else —
the naming convention and the picochess edits — follows the Citrine pattern with
`OSA` / `Osa*` / `/dev/rfcomm0`.

> **Wired instead of Bluetooth?** This guide assumes Bluetooth SPP (`/dev/rfcomm0`). If you wire
> the board's serial port to the Pi through a USB-to-TTL adapter instead, the transport changes
> but the driver code does not. See **Appendix — USB serial connection** at the end.

> **Two drivers.** There are two driver files: `board.py` (firmware-LED version) and
> `board-new.py` (driver-LED version). See "Why there are two drivers" below. Whichever you
> pick, it is deployed as `/opt/picochess/eboard/osa/board.py`.

---

## Naming convention

| Element | Value | Renamable? |
|---|---|---|
| Driver classes | `OsaBoard`, `OsaDisplay` | No (imported by `picochess.py`) |
| Helper functions | `_uci_to_osa`, `_osa_to_move` | No (unless renamed both sides) |
| Internal attribute | `self._osa_board` | Yes (internal to `board.py`) |
| **Enum member name** | `EBoard.OSA` | Must match the `.ini` |
| Enum member value | `"B00_eboard_osa_menu"` | Menu/translation id |
| **`.ini` token** | `board-type = osa` | Must match the member name |
| Web label | `"Saitek OSA"` | Cosmetic |

### The `EBoard[...]` trap (lookup BY NAME)

In `picochess.py` (`async def main()`):

```python
board_type = dgt.util.EBoard[args.board_type.upper()]   # lookup by member NAME
```

Three places must all say "osa":

1. `dgt/util.py` → member name `OSA`
2. `picochess.ini` → `board-type = osa`
3. `picochess.py` → `EBoard.OSA`

A missing member name raises `AttributeError` (crash at startup). An unresolved `.ini` token
raises `KeyError` and **silently falls back to DGT** (the OSA board is never loaded, with no
error). This is the single most common failure mode.

---

## The OSA protocol (as implemented and validated on hardware)

**Serial:** `9600 baud, 8 data bits, 1 stop bit, no parity, no flow control`, over Bluetooth SPP
on `/dev/rfcomm0`. (Over rfcomm the baud is handled by the Bluetooth stack; 9600 only matches the
board's announced setting.)

### The `0x17` ready rule (critical — this is what makes the board behave)

Every command the PC sends is acknowledged by the board with a single byte `0x17`. The driver
sends one command, **waits for the board's ready signal, then sends the next** (serialized;
~300 ms per round-trip in practice).

The ready signal is the **bare prompt `>` + `0x17`** (no text before it). A `0x17` that
*terminates a content line* — specifically the **echo of an injected move**,
`  1. e2-e4   00:00  \x17` — is the move-report terminator, **not** a ready signal: the board
then emits its real `>` + `0x17` prompt a moment later (hence the *double* `[17]` seen after a
`MOVE`). The driver must release the per-command ack **only on the bare prompt**.

> Releasing on the echo's `0x17` fires the next command (`BOARD ON`) ~300 ms before the board is
> ready: the move is registered but **never lit on the LEDs**. This was the root cause of "the
> move does not show". In the read loop: `if sep_was_ack and not line: self._ack_event.set()`.

### Handshake (one `NEW` only)

```
OPEN  ->  board replies "- Saitek OSA (9600 baud), Version 1.4 -"
NEW   ->  board resets, replies "New Game"
```

**Stop there.** Do **NOT** arm `ANALYSIS` / `BOARD ON` in the handshake. The board is left in the
clean **post-`NEW`** state, which is the only state `PLAY` flips from (see below). The board is
armed **per colour** on the first `PLAY_MODE`.

### Per-colour arming (in `set_computer_color`, on the first `PLAY_MODE`)

- **User White / computer Black (`USER_WHITE`):** `ANALYSIS` + `BOARD ON`. `ANALYSIS` is OSA's
  "external engine / referee" mode (the board's own engine stays silent and it only reports the
  human's moves — the equivalent of the Citrine's `Uon`). No `PLAY` → the board keeps its default
  orientation (White in front). The human plays White first.
- **User Black / computer White (`USER_BLACK`):** `BOARD OFF` + `PLAY`. **`PLAY` physically flips
  the board** (the user plays Black from the far side) and starts engine-plays-White. `PLAY` only
  flips from the clean post-`NEW` state, so there must be **no `ANALYSIS` and no `NORMAL` before
  it** — the sequence is exactly the Termite reference `NEW` → `BOARD OFF` → `PLAY`.

`_computer_is_white` starts at `None` (not `False`) so the very first `PLAY_MODE` is never
swallowed by the "no change" guard.

Side choice takes effect **at the start of a game**. `PLAY` flips one way only; only a `NEW`
restores the normal orientation. To switch sides cleanly, start a new game.

> **Genuine vs spurious mid-game `PLAY_MODE`.** picochess re-emits `PLAY_MODE` on every change of
> side-to-move (it re-derives `play_mode` from `game.turn`), including a spurious re-emission
> right after a take-back. A real toggle-switch side change must re-orient the board; the
> spurious post-take-back one must be ignored. They are told apart by timing relative to the last
> take-back (`_SIDE_SWITCH_GUARD = 3.0 s`): within the guard = spurious (ignored), later = a
> genuine side switch that falls through to the per-colour setup. A pending board-`New Game`
> re-arm task (`_newgame_arm_task`) is also cancelled when the colour is set explicitly, so a
> late re-arm cannot push `ANALYSIS` / `BOARD ON` onto an already-flipped board (which previously
> caused intermittent "board not inverted" on restart).

### One full ply (engine answering a human move)

```
(human plays)            board -> "  2. e4-e5   00:31"
BOARD OFF                PC    -> disarm the board
MOVE D7-D5               PC    -> inject the engine's reply
BOARD ON                 PC    -> light up the move
NORMAL                   PC    -> normal display
ANALYSIS                 PC    -> re-arm for the next human move
```

No trailing `BOARD ON` after `ANALYSIS` (an earlier version sent one; the hardware does not need
it and it re-touches the board right after re-arming).

### Single `NEW` per game

There is exactly **one** `NEW` per game (handshake, or `new_game()`). Because arming is per
colour, there is **no re-`NEW`**, so the board displays "New Game" only once. The board's
`New Game` echo to our own `NEW` is swallowed by a suppression counter (`_pending_new_acks` + a
time window) so it is not re-fired to picochess as a physical reset.

### Move notation

- **Board → PC:** pawn `e2-e4`, piece `Bf1-b5` / `Qd8xd6` / `Ng1-e2`, capture `x`, en passant
  `e5xd6ep`, castling `O-O` / `O-O-O`, check `+`, mate `++`, result `1-0` / `0-1` / `1/2-1/2`.
  White moves carry a leading `N.` number, Black moves do not — a **display column only**, never
  a human-vs-engine flag.
- **PC → board:** `MOVE <FROM>-<TO>` in UPPERCASE (`MOVE E7-E6`, `MOVE O-O`, `MOVE E7-E8/Q`). The
  board **echoes** the injected move as a normal move line; the driver discards that echo via a
  turn-independent move *signature*.

### Buttons

- **New Game** (the board's NEW GAME key) → `Event.NEW_GAME(pos960=518)`.
- **Takeback** (one line per ply, sometimes garbled, e.g. `TTTTTakeback`) → `Event.TAKE_BACK`. A
  debounce collapses a garbled burst into one event. The driver sends no *protocol command* to
  the board on a take-back (the OSA chains take-backs natively; any command would interrupt its
  LED sequence). In `board-new.py` the only thing done on a take-back is cancelling the in-flight
  LED-guidance task — **never** a DSA clear, which would blank the firmware's own take-back
  display.

---

## Why there are two drivers (`board.py` vs `board-new.py`)

Both files are identical on the protocol/handshake side. They differ only in **who lights the
move-guidance LEDs**.

### `board.py` — firmware-LED (the original)

The OSA firmware does its own move guidance when the engine plays: it blinks the **FROM** square,
waits for the user to lift the piece, then blinks the **TO** square. The driver injects the move
and lets the firmware light it.

**The flaw:** the firmware's LED matrix can only address one square at a time, and its guidance
logic skips the destination on a **capture** — when the **TO** square is already occupied by the
captured piece, the firmware never blinks it. So on every capture the user gets a FROM hint but
**no LED on the square to play to**, for the most error-prone moves.

### `board-new.py` — driver-LED (suitable for Leonardo and Galileo only)

`board-new.py` stops relying on the firmware for the destination LED and drives the squares
itself, so **both the FROM and the TO square are always lit, including on captures**.

> **Renaissance:** no way has been found to drive the LEDs on the Renaissance. If that board is
> recognized, the driver **reverts to the firmware LED guidance** (the `board.py` behaviour).

It uses **MOSAL message 27 (DSA — Display Status Area)** sent over BOSAL as a `$`-prefixed
MOSAL-A frame. A DSA write overwrites the firmware's own blink and holds it (verified on the
bench: writing the destination square killed the firmware's source-square blink and stayed lit).

**The from→to sequence (one move = one finite burst, then silence):**

1. Light the **FROM** square (flashing).
2. Wait `_GUIDE_FROM_DURATION = 1.5 s` — the deliberate pause so the user sees the source first.
3. Light the **TO** square (flashing), **even on a capture**.
4. **Stop.** No more writes; the board's hardware sustains the flash on its own (message 27 flash
   bytes `d18`/`d19`).

The TO square keeps flashing until the user completes the move; the move's completion echo then
triggers `_stop_move_guide`, which clears the board LEDs with a DSA "all off" frame (offset 12,
`d12..d19 = 0`).

**Why a finite burst and not a continuous refresh:** an earlier version rewrote the squares every
second. That continuous DSA traffic **jammed the board's move reporting** — the board returned
only DSA acks and never reported the played move, stalling the game (proven by log). A short
two-write burst leaves the serial link free afterwards.

**Orientation (transposition).** The DSA LED matrix is **always addressed in NORMAL orientation**;
it does *not* follow the board's physical flip. When the engine plays White (board flipped via
`PLAY`, `_computer_is_white = True`), the guidance squares are transposed 180° (`a1 ↔ h8`,
`M(sq) = 63 - sq`) to land on the physically correct squares. A DSA write does **not** un-flip
the board; injection and detection keep working in the flipped orientation.

**Colour convention (confirmed on the bench)** on the bicolor coordinate LEDs:

| | red | green | orange (red+green) |
|---|---|---|---|
| row bits | `0x80` (bit7) | `0x40` (bit6) | `0xC0` |
| column bits | `0x40` (bit6) | `0x20` (bit5) | `0x60` |

**Tunable constants (top of `board-new.py`):**

| Constant | Default | Meaning |
|---|---|---|
| `_GUIDE_MOVES` | `True` | Master switch. `False` → firmware-only (= `board.py` behaviour). |
| `_GUIDE_CAPTURES_ONLY` | `False` | `True` → drive LEDs only on captures, leave normal moves to the firmware. |
| `_GUIDE_LED_COLOR` | `"orange"` | `"red"` \| `"green"` \| `"orange"`. |
| `_GUIDE_FROM_DURATION` | `1.5` | Seconds the FROM square is shown before the TO square is lit. |

**Which to deploy.** Use `board-new.py` on a Leonardo or Galileo for destination guidance on
captures, or `board.py` for firmware-only LEDs (and on a Renaissance, where `board-new.py` falls
back to the firmware anyway). Either way, copy the chosen file to
`/opt/picochess/eboard/osa/board.py` and clear `__pycache__`.

---

## NEW files

### `/opt/picochess/eboard/osa/__init__.py`
Empty — Python package marker.

### `/opt/picochess/eboard/osa/board.py`
The full driver:

- **`OsaBoard`** — async serial link. Handshake (`OPEN` → `NEW`), reads human moves, injects
  engine moves with the `BOARD OFF . MOVE . BOARD ON . NORMAL . ANALYSIS` choreography. The read
  loop releases each command's `0x17` ack **only on the bare prompt**. `set_computer_color` arms
  the board per colour (Black → `ANALYSIS` + `BOARD ON`; White → `BOARD OFF` + `PLAY`/flip) on the
  first `PLAY_MODE`, and tells a spurious post-take-back `PLAY_MODE` from a genuine side switch
  (`_SIDE_SWITCH_GUARD`). In `board-new.py` it also drives the from→to LED guidance via DSA.
- **`OsaDisplay`** — intercepts `COMPUTER_MOVE` and forwards it to the board (`self._osa_board`);
  on `PLAY_MODE` it calls `set_computer_color`.
- Echo suppression via `_move_signature` (`E7E6` / `OO` / `E7E8Q`), so the board's echoed display
  line is never read back as a human move.
- `New Game` suppression so the board's reply to our own `NEW` is not re-fired as a reset.
- No-op stubs for the rest of the `EBoard` protocol.

### `/etc/systemd/system/rfcomm_osa.service`
Binds the OSA board to `/dev/rfcomm0` at startup. **Replace the MAC.**

```ini
[Unit]
Description=Bind Saitek OSA (XX:XX:XX:XX:XX:XX) to /dev/rfcomm0
After=bluetooth.target
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

> Device number **0** (`rfcomm bind 0` → `/dev/rfcomm0`), vs **1** for the Citrine. Keep both
> services if you use both boards.

---

## MODIFIED files (Citrine pattern, with `OSA`)

### `/opt/picochess/dgt/util.py`
Add the `OSA` member to `EBoard` (the member **name** must match `board-type = osa`):

```python
class EBoard(MyEnum):
    CERTABO   = "B00_eboard_certabo_menu"
    CHESSLINK = "B00_eboard_chesslink_menu"
    CHESSNUT  = "B00_eboard_chessnut_menu"
    DGT       = "B00_eboard_dgt_menu"
    ICHESSONE = "B00_eboard_ichessone_menu"
    CITRINE   = "B00_eboard_citrine_menu"
    OSA       = "B00_eboard_osa_menu"          # <- ADDED
    NOEBOARD  = "B00_eboard_noeboard_menu"

    @classmethod
    def items(cls):
        return [EBoard.CERTABO, EBoard.CHESSLINK, EBoard.CHESSNUT,
                EBoard.DGT, EBoard.ICHESSONE, EBoard.CITRINE,
                EBoard.OSA, EBoard.NOEBOARD]    # <- OSA added
```

### `/opt/picochess/dgt/translate.py`
Add the `eboard_osa_menu` block before `eboard_noeboard_menu` (keep the trailing spaces: the
medium text is padded to 8 characters and the small text to 5, as for the Citrine):

```python
if text_id == "eboard_osa_menu":
    entxt = Dgt.DISPLAY_TEXT(
        web_text="Saitek OSA",
        large_text="Saitek OSA",
        medium_text="osa     ",
        small_text="osa  ",
    )
    detxt = entxt; nltxt = entxt; frtxt = entxt; estxt = entxt; ittxt = entxt
```

### `/opt/picochess/configuration.py`
Add `"osa"` to the `--board-type` help text (cosmetic).

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

3. Instantiate the consumer after `my_pgn_display`:

```python
if board_type == dgt.util.EBoard.OSA:
    my_osa_display = OsaDisplay(dgtboard, main_loop)
    non_main_tasks.add(asyncio.create_task(my_osa_display.message_consumer()))
```

4. Add `OSA` to the `CITRINE` block in the `Event.SWITCH_SIDES` handler. The OSA board, like the
   Citrine, is driven by `KEYBOARD_MOVE` events (no continuous FEN stream), so `newgame_happened`
   is never cleared by `process_fen` and the engine's first move after a side switch would be
   discarded as "stale":

```python
                    if cond1 or cond2:
                        if self.board_type in (dgt.util.EBoard.CITRINE,
                                                dgt.util.EBoard.OSA):
                            self.state.newgame_happened = False
                        self.state.time_control.reset_start_time()
                        await self.think(msg)  # PLAY_MODE
```

### `/opt/picochess/server.py`

1. Web footer label — add `OSA` to `_eboard_labels`:

```python
    _dgt_util.EBoard.OSA: "Saitek OSA",      # <- ADDED
```

2. Web board-selector whitelist — add `"osa"` (else the Settings page silently ignores it):

```python
_valid_eboards = {"dgt", "certabo", "chesslink", "chessnut",
                  "ichessone", "citrine", "osa", "none"}
```

> Also check that the matching `<select>` in the template offers the `osa` option.

### `/opt/picochess/picochess.ini`
Must be **uncommented** and in the right section, or picochess silently falls back to DGT:

```ini
board-type = osa
dgt-port   = /dev/rfcomm0
```

### `/etc/systemd/system/picochess.service`

```ini
After=multi-user.target rfcomm_osa.service
Wants=rfcomm_osa.service
```

> The serial device only exists once the board is bound, so rfcomm must run first. Run picochess
> in the `dialout` group (or as root) to open `/dev/rfcomm0`.

---

## Differences from the Citrine driver

| | Citrine | OSA |
|---|---|---|
| Baud | 57 600 | **9 600** |
| Link | Bluetooth (`/dev/rfcomm1`) | **Bluetooth** (`/dev/rfcomm0`) |
| Handshake | `Xon . N . Uon` x2 | **`OPEN . NEW`** (one `NEW`; arm per colour) |
| Referee mode | `Uon` | **`ANALYSIS`** |
| Ready/ack | — | **bare prompt `>` + `0x17`** (not the move echo's `0x17`) |
| Inject move | `m<move>` (twice) | **`MOVE <FROM>-<TO>` + `BOARD ON` / `NORMAL` / `ANALYSIS`** |
| Move in | `M e2-e4` | **`  N. e2-e4   00:00`** (number/time stripped) |
| Take-back | `T x x` | **`Takeback`** (debounced) |
| Board flip | `F` command | **`PLAY`** (flips from the post-`NEW` state; `NEW` restores) |
| Move-guidance LEDs | board's own | firmware (`board.py`) **or** driver via DSA msg 27 (`board-new.py`) |
| Startup service | `rfcomm_citrine.service` (rfcomm 1) | **`rfcomm_osa.service` (rfcomm 0)** |

---

## Status

**Working on hardware**
- Human move parsing for every line type (pawn, piece, capture, en passant, check, mate, O-O,
  O-O-O).
- Engine-move injection and **LED display** (fixed by the bare-prompt ack rule).
- Echo suppression (injected move vs the board's echoed display line).
- `USER_BLACK` board **flip** via `PLAY` from the post-`NEW` state.
- Single `NEW` per game (no duplicate "New Game").
- CRLF line terminator (`_EOL = "\r\n"`) confirmed.
- **From→to LED guidance (`board-new.py`):** FROM lit, 1.5 s wait, TO lit — works on captures
  too; the finite burst leaves move reporting free; 180° transposition when the engine plays
  White; take-back leaves the firmware's LEDs untouched.
- Genuine vs spurious mid-game `PLAY_MODE` distinguished by `_SIDE_SWITCH_GUARD`.

**Still to confirm on hardware**
- Engine castling / promotion command syntax (`MOVE O-O` / `O-O-O` / `MOVE E7-E8/Q`): the log
  never shows the *engine* castling/promoting — watch for a `???` reply.
- Repeated rejected-move `???`: currently only logged; if it recurs, add a `POSITION` query +
  retry in `send_move`.

> Web diagram orientation (chessground in `app.js`) is a separate frontend concern, intentionally
> out of scope here.

---

## Useful commands

### Manual startup (debug)

```bash
sudo systemctl stop picochess.service
sudo rfcomm bind 0 XX:XX:XX:XX:XX:XX        # your OSA board's MAC
cd /opt/picochess && sudo /opt/picochess/venv/bin/python3 picochess.py \
    --board-type osa --dgt-port /dev/rfcomm0 --log-level debug --log-file pico.log
```

> Connects with `--board-type osa` on the CLI but not via the `.ini`? → the problem is in
> `picochess.ini` (commented/missing line, or wrong section).

### Bluetooth serial port

```bash
sudo rfcomm bind 0 XX:XX:XX:XX:XX:XX    # create /dev/rfcomm0
rfcomm                                  # list bindings
ls -l /dev/rfcomm0                      # device present?
```

### Pairing (one time)

```bash
sudo bluetoothctl
  agent on
  scan on
  pair XX:XX:XX:XX:XX:XX     # enter PIN if asked (often 0000 / 1234)
  trust XX:XX:XX:XX:XX:XX
  quit
```

### Naming consistency

```bash
grep -nE "OSA"        /opt/picochess/dgt/util.py     # member name = OSA
grep -i  "board-type" /opt/picochess/picochess.ini    # = osa, uncommented
grep -nE "OSA"        /opt/picochess/picochess.py     # EBoard.OSA
```

### Watch the serial dialogue (debug log)

```bash
grep -aE "OsaDisplay|OsaBoard" /opt/picochess/logs/picochess.log | tail -80
```

At the start of a `USER_BLACK` game, look for, in order: `raw b'NEW'` (once) → `BOARD OFF` →
`PLAY` → `MOVE ...` → echo → `>\x17` → `BOARD ON`. A `no 0x17 ack for '...'` line means a command
stalled (1.2 s). With `board-new.py`, also expect `$ ...` DSA frames around each engine move
(FROM, then TO 1.5 s later, then a clear on completion).

### Reverting to a DGT board

```ini
board-type = dgt
dgt-port   = /dev/ttyACM0
```

---

## Appendix — USB serial connection (instead of Bluetooth)

Everything above assumes Bluetooth SPP on `/dev/rfcomm0`. The OSA boards (Leonardo, Galileo,
Renaissance) expose a **TTL-level serial port**, not USB, so a "USB connection" means wiring that
port to the Pi through a **USB-to-TTL serial adapter** (FTDI, CP210x, CH340 or PL2303). This is a
pure transport change.

**The driver code does not change.** `connect()` already opens the port with the exact serial
settings the board needs — `9600 baud, 8 data bits, no parity, 1 stop bit, no flow control`
(`_BAUD` / `_BYTESIZE` / `_PARITY` / `_STOPBITS` / `_XONXOFF` / `_RTSCTS`). Over Bluetooth those
settings were cosmetic; over a real UART they are enforced, and already correct. Only the **port
string** changes (`/dev/rfcomm0` → a `/dev/ttyUSB*` node). The OSA protocol, the `0x17` ready
rule, the per-colour arming, the LED guidance and every picochess edit are identical.

### What to change

**1. Wiring (the one place to be careful).** Connect adapter `RX` ↔ board `TX`, adapter `TX` ↔
board `RX`, and `GND` ↔ `GND` (TX/RX cross over). These 1980s Saitek boards are **5 V logic**, so
use a 5 V-capable / 5 V-tolerant adapter (or a level shifter). Do **not** wire a 3.3 V-only adapter
straight to the board, and do **not** connect the adapter's `VCC` — power the board from its own
supply and share only ground.

**2. Find the device node.** A USB-serial adapter appears as `/dev/ttyUSB0`
(FTDI / CP210x / CH340 / PL2303) or `/dev/ttyACM0` (CDC-ACM adapters):

```bash
dmesg | tail -20          # shows e.g. "ch341-uart ... now attached to ttyUSB0"
ls -l /dev/ttyUSB* /dev/ttyACM*
```

**3. `picochess.ini` — point `dgt-port` at the USB node** (keep `board-type = osa`):

```ini
board-type = osa
dgt-port   = /dev/ttyUSB0        ; or /dev/ttyACM0, or the stable symlink below
```

**4. Drop the rfcomm machinery — none of it applies over USB:**

- No Bluetooth pairing / `trust` / `rfcomm bind` and no board MAC.
- **Disable** the bind service: `sudo systemctl disable --now rfcomm_osa.service` (you can delete
  `/etc/systemd/system/rfcomm_osa.service` if it is OSA-only).
- In `/etc/systemd/system/picochess.service`, remove the rfcomm dependency so picochess no longer
  waits for a binding that never happens:

  ```ini
  # remove these two lines (USB needs no rfcomm):
  # After=multi-user.target rfcomm_osa.service
  # Wants=rfcomm_osa.service
  ```

**5. Stable device name (recommended).** `/dev/ttyUSB0` numbering can shift if more than one
USB-serial device is present (e.g. if the Citrine is also on USB). Pin a fixed symlink with a udev
rule keyed on the adapter's `idVendor` / `idProduct` (add `ATTRS{serial}` if the adapter has a
unique serial). Read the IDs with
`lsusb` / `udevadm info -a -n /dev/ttyUSB0 | grep -E "idVendor|idProduct|serial"`, then:

```bash
# /etc/udev/rules.d/99-osa.rules   (example for an FTDI adapter)
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", SYMLINK+="osa"
```

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
ls -l /dev/osa        # -> /dev/ttyUSB0
```

Then set `dgt-port = /dev/osa` in `picochess.ini`.

**6. Permissions.** The user running picochess must be in the `dialout` group (or run as root) to
open the serial device: `sudo usermod -aG dialout <user>` (re-login to take effect).

### Quick sanity check

With picochess stopped, confirm the board talks at 9600 8N1 over the cable:

```bash
sudo systemctl stop picochess.service
picocom -b 9600 /dev/ttyUSB0      # type OPEN <Enter> -> expect "- Saitek OSA ... -"
# (Ctrl-A Ctrl-X to quit picocom)
```

Manual debug startup is unchanged except for the port:

```bash
cd /opt/picochess && sudo /opt/picochess/venv/bin/python3 picochess.py \
    --board-type osa --dgt-port /dev/ttyUSB0 --log-level debug --log-file pico.log
```

### Summary — Bluetooth vs USB

| | Bluetooth SPP | USB serial |
|---|---|---|
| Physical link | RFCOMM over Bluetooth Classic | USB-to-TTL adapter on the board's serial port |
| Device node | `/dev/rfcomm0` | `/dev/ttyUSB0` / `/dev/ttyACM0` (or `/dev/osa`) |
| Baud 9600 8N1 | carried by the BT stack (cosmetic) | enforced on the real UART (already set in `connect()`) |
| Pairing | `bluetoothctl` pair/trust + MAC | none |
| Bind service | `rfcomm_osa.service` (`rfcomm bind 0 <MAC>`) | none — disable it |
| `picochess.service` | `After=/Wants= rfcomm_osa.service` | remove that dependency |
| udev | not needed | recommended for a stable name |
| `dgt-port` (`.ini`) | `/dev/rfcomm0` | `/dev/ttyUSB0` (or `/dev/osa`) |
| Driver code | unchanged | **unchanged** |
