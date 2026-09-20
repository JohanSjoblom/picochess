# Windows Port Status

Last reviewed: 2026-09-19

## Purpose

This document is a technical handoff for continuing the PicoChess Windows
port. It records what is implemented, what has been validated, what is only
supported by code inspection, and which Linux assumptions remain.

The current target is 64-bit Windows on `AMD64`, using CPython 3.13, a native
Windows UCI engine, and either the web interface or a DGT e-Board exposed by
Windows as a virtual COM port.

## Status Summary

| Area | Status | Notes |
| --- | --- | --- |
| Python imports and CLI startup | Validated | CPython 3.13.15 x64 |
| PowerShell environment installer | Implemented, validation path tested | Reuses/clones repo, creates `venv`, installs dependencies and portable resources; downloads not exercised locally, no engines or services |
| Windows games helper launcher | Implemented, unvalidated with Scid | Detects a user-installed `tcscid.exe`; failure is isolated to the Games tab |
| Web interface with `noeboard` | Validated baseline | Native Windows engine and local catalogs must be supplied |
| Local Windows UCI engines | Implemented | Catalog is read from `engines/AMD64` |
| DGT board over Bluetooth COM port | Code-supported, hardware-unvalidated | Pair in Windows and pass `COMx` explicitly |
| Automatic Bluetooth pairing | Linux-only | Uses `bluetoothctl`, `rfcomm`, and `/dev` paths |
| RabbitPlugin | Not required | PicoChess implements the DGT serial protocol itself |
| PAM-protected PGN upload | Disabled on Windows | Linux host integration only |
| Host update, shutdown, reboot, and Wi-Fi setup | Linux-only | Depends on Linux services and commands |
| Other physical board families | Unvalidated | Treat each transport separately |
| Retro/MAME window control | Linux desktop-oriented | Uses X11/Wayland tools |
| Local audio and volume control | Partially portable/unvalidated | Several paths depend on Linux audio tools |
| Automated Windows CI | Missing | Windows behavior is not continuously tested |

## Verified Environment

The Windows work so far used:

- Windows 11 x64 (`platform.machine()` reports `AMD64`)
- CPython 3.13.15 x64
- pip 26.2.1
- the repository virtual environment at `venv\Scripts\python.exe`

Runtime and test dependencies were installed successfully. `dgt.board`,
`server`, and PicoChess CLI imports were exercised on Windows. A focused
server/startup run passed 77 of 79 tests; the two failures involved book
selection because this checkout had no local book catalog, not because of a
Windows compatibility failure.

Do not interpret this as full feature validation. No DGT board, DGT clock, or
Windows Stockfish executable was available for an end-to-end hardware game.

## Implemented Windows Accommodations

### Conditional dependencies and imports

`requirements.txt` excludes Linux-only `bluepy` and `pam` dependencies on
Windows. `dgt/board.py` tolerates the absence of `fcntl`, and `server.py`
registers PAM-backed upload support only when Linux host integration is
available.

`upload_pgn.py` still imports `pam` directly. It is not imported by the normal
Windows server path because `server.py` guards that feature. Importing
`upload_pgn.py` directly on Windows remains unsupported.

### Platform and engine directory

Engine catalog discovery uses `platform.machine()`. On 64-bit Windows this is
`AMD64`, so local engine files belong under:

```text
engines/AMD64/
```

A minimal local engine layout is:

```text
engines/AMD64/stockfish.exe
engines/AMD64/stockfish.exe.uci
engines/AMD64/engines.ini
```

The section name in `engines.ini` must match the executable name, including
`.exe`. Local engine discovery does not add the suffix automatically. The
`.exe` auto-suffix logic in `uci/engine.py` applies to a separate remote
Windows-engine path.

See `engines/README.md` for the current catalog and level examples.

### Web-only baseline

The smallest useful Windows configuration is a native Windows engine plus:

```ini
engine = engines\AMD64\stockfish.exe
engine-level = Elo@2200
tutor-engine = engines\AMD64\stockfish.exe
board-type = noeboard
web-server = 8080
```

Start it from the repository root with:

```powershell
venv\Scripts\python.exe picochess.py
```

Then open `http://localhost:8080`. A non-privileged port such as 8080 is
preferred; binding port 80 may require elevated privileges.

## DGT Bluetooth e-Board on Windows

### Architecture

DGT Bluetooth boards use Bluetooth Classic RFCOMM as a serial byte stream, not
BLE/GATT. The practical Windows path is:

1. Windows pairs with the board.
2. The Windows Bluetooth stack exposes a virtual COM port.
3. PicoChess opens that port with `pyserial`.
4. PicoChess performs the DGT protocol handshake and requests a board dump.
5. `dgt/board.py` converts the 64-square board dump into raw FEN and emits
   `Message.DGT_FEN` through the existing board pipeline.

The board does not need to send a textual FEN. PicoChess constructs it from the
DGT piece bytes.

### Pairing and configuration

1. Turn on the Windows Bluetooth adapter and the DGT Bluetooth e-Board.
2. Open `Control Panel > Hardware and Sound > Devices and Printers` and choose
   `Add a device`.
3. Select `DGT_BT_XXXXX` and choose to enter the pairing code.
4. Enter `0000` (four zeros).
5. Find the assigned COM port in Windows Device Manager.
6. Configure PicoChess, for example:

```ini
board-type = dgt
dgt-port = COM7
```

The equivalent command-line option is:

```powershell
venv\Scripts\python.exe picochess.py --board-type dgt --dgt-port COM7
```

Only one process can own the serial port. Close any chess application or board
utility using the same COM port before starting PicoChess.

### RabbitPlugin

RabbitPlugin is not required for PicoChess. It is a DLL integration that lets
applications such as Fritz consume DGT board data. PicoChess already implements
the DGT serial protocol, board-dump parsing, and FEN delivery.

Windows pairing and its Bluetooth stack create the virtual COM port;
RabbitPlugin selects and consumes an already assigned port for Fritz. It is not
part of PicoChess's transport architecture and should not be added as a
runtime dependency.

### Current caveats

Passing `--dgt-port COM7` reaches the existing explicit serial-device path and
avoids Linux `/dev` discovery. This is code-supported but has not yet been
verified with a physical board on Windows.

The current channel classification treats a device as Bluetooth only when its
name contains `rfc`, which is designed for Linux `rfcomm` paths. A Windows
Bluetooth port such as `COM7` is therefore labeled as USB. Basic serial
communication and FEN parsing should remain available, but the following may
be wrong or skipped:

- Bluetooth-specific stabilization timing
- Bluetooth connection labels
- automatic battery-status query
- Revelation/DGT Bluetooth name-specific behavior

A future change should represent transport type separately from the device
path instead of inferring it from the string `rfc`.

If the COM port cannot be opened, first check that it exists, is the correct
outgoing/serial port, and is not held by another process. PicoChess currently
does not enumerate or auto-select Windows COM ports.

## Bluetooth Library Decision

No additional Python Bluetooth library is needed for the virtual-COM approach.
`pyserial==3.5` is already a dependency and accepts Windows names such as
`COM7`.

If Windows cannot provide a stable virtual COM port, the preferred native
fallback is PyWinRT RFCOMM. Relevant modular packages have CPython 3.13 x64
wheels, but WinRT exposes asynchronous streams rather than a pyserial object,
so it would require a transport adapter around the existing parser.

Libraries considered and not selected:

- Bleak: BLE/GATT only; wrong protocol for this DGT path.
- PyBluez: unmaintained and unsuitable as a new dependency.
- PyQt Bluetooth: RFCOMM-capable but adds Qt and event-loop complexity.
- `winsdk`: superseded by modular PyWinRT packages.
- `pywin32`/`ctypes`: possible for low-level enumeration, but not the preferred
  transport.
- `pythonnet` with 32feet.NET: possible but unnecessarily heavy.

The local CPython `socket` module exposes some generic Bluetooth constants but
not the Windows RFCOMM constants needed for a direct socket implementation in
this environment.

## Linux-Oriented Features Still Outside the Port

The following features should be treated as unsupported or unvalidated on
Windows until each path is audited and tested:

- PicoChess-managed Bluetooth pairing (`bluetoothctl`, `rfcomm`, `/dev/rfcomm*`)
- automatic serial discovery through `/dev/ttyACM*` and `/dev/ttyUSB*`
- DGT Pi and other I2C/GPIO hardware
- Wi-Fi and hotspot management
- systemd service management, host updates, shutdown, and reboot
- PAM-authenticated PGN upload
- PipeWire, PulseAudio, and ALSA volume commands
- X11/Wayland artwork switching through `xdotool`, `ydotool`, or `swaymsg`
- Linux `.sh` installer and maintenance scripts (use `install-picochess-windows.ps1` for the Windows environment)
- ChessLink, Certabo, Chessnut, iChessOne, and other board transports without
  an explicit Windows validation record

Do not add broad Windows conditionals around these features without following
the owning subsystem. Preserve PicoChess's shared `asyncio` architecture and
do not introduce threads for normal transport work.

## Validation Commands

Use the repository virtual environment, not the system Python:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-picochess-windows.ps1 -ValidateOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-picochess-windows.ps1 -SkipGamesServer -PicoChessArguments --help
venv\Scripts\python.exe -c "from dgt.board import DgtBoard; print('dgt.board import OK')"
venv\Scripts\python.exe -c "import server; print('server import OK')"
venv\Scripts\python.exe picochess.py --help
venv\Scripts\python.exe -m unittest tests.test_server
venv\Scripts\python.exe -m unittest tests.uci.test_ucishell
```

For the full unit suite, use the repository's configured test environment when
available. On Linux the project convention is `venv/bin/tox -e unit`; on
Windows, invoke the corresponding `venv\Scripts\tox.exe -e unit` if tox is
installed in that environment.

A meaningful DGT Windows hardware test must verify:

1. Windows pairing creates a stable COM port.
2. PicoChess opens the explicit port without RabbitPlugin.
3. The version handshake completes.
4. The initial board position arrives as `DGT_MSG_BOARD_DUMP`.
5. Piece movement produces updated raw FEN and enters the normal move pipeline.
6. DGT clock communication works, if a clock is attached.
7. Disconnect/reconnect behavior is usable.
8. Bluetooth timing, labeling, and battery behavior are corrected or explicitly
   accepted as limitations.

## Recommended Next Work

1. Run the DGT COM hardware test above and retain logs around serial connection,
   board version, board dump, and raw FEN.
2. Add an explicit transport/channel option or Windows COM metadata detection
   so Bluetooth COM ports are not classified as USB.
3. Add Windows COM-port enumeration and clearer open-failure diagnostics only
   if manual `dgt-port` configuration proves insufficient.
4. Add a Windows CI job covering dependency installation, imports, focused
   platform tests, and CLI startup.
5. Guard or refactor the direct `pam` import in `upload_pgn.py` if that module
   needs to become independently importable on Windows.
6. Validate one native Windows UCI engine end to end and document the tested
   binary, catalog, level, and shutdown behavior.
7. Audit additional board and audio paths individually; do not infer support
   merely because the main process starts.

## Important Code Locations

- `requirements.txt`: platform dependency markers
- `configuration.py`: `--dgt-port` and board options
- `dgt/board.py`: DGT serial opening, Linux Bluetooth setup, handshake, and FEN
  conversion
- `picochess.py`: startup, board construction, and async application lifecycle
- `server.py`: web server and Linux host-integration guards
- `upload_pgn.py`: remaining direct PAM dependency
- `uci/read.py`: architecture-specific engine catalog discovery
- `uci/engine.py`: local/remote UCI process handling
- `utilities.py`: existing Windows executable handling
- `engines/README.md`: operator-facing Windows engine and DGT pairing setup
- `tests/test_server.py`: Linux host-integration guard coverage
- `tests/uci/test_ucishell.py`: remote Windows shell coverage

## Rules for Future AI Work

- Check current code before relying on older analysis. Earlier notes that called
  `fcntl` and the `server.py` PAM import startup blockers predate their guards.
- Keep verified behavior separate from code-supported but untested behavior.
- Do not require or install RabbitPlugin for PicoChess.
- Do not replace RFCOMM with a BLE library.
- Preserve Linux behavior while adding Windows alternatives.
- Prefer explicit, narrow platform boundaries over scattered `if Windows`
  branches.
- Use async tasks and non-blocking I/O in accordance with the repository
  architecture.
- Do not claim physical-board support until handshake, FEN, movement, and
  reconnect behavior have been tested on hardware.
