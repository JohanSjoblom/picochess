"""
Novag Citrine e-board driver for picochess v4.

Protocol details reverse-engineered from citinter.py (Eticha) and confirmed
against the official Novag Citrine PC Communication Protocol documents.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SERIAL PARAMETERS  (fixed by hardware – cannot be changed)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  57 600 baud · 8 data bits · 1 stop bit · no parity · NO flow control
  (important: neither XON/XOFF nor RTS/CTS must be active)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMMANDS  (PC → Citrine, all terminated with \r\n)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Xon        enable move-echo transmission (note: no space, capital X)
  Xoff       disable transmission
  Uon        enable Referee mode (external engine plays for the board side)
  Uoff       disable Referee mode
  I          query ID  -> board replies "UCB CITRINE VI.xx\r\n"
  N          new game
  F          flip colour (board takes opposite side)
  L          query current level -> "Level sd N\r\n" or "Level in N\r\n"
  m<move>    send computer move  e.g. "me2e4", "mO-O", "me7e8/q"
             The board echoes it back as "M e2-e4\r\n" – this driver
             suppresses that echo automatically.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MESSAGES  (Citrine → PC)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  M e2-e4\r\n        move played on the board (or echoed computer move)
  M O-O\r\n          king-side castling
  M O-O-O\r\n        queen-side castling
  M e7-e8/Q\r\n      promotion  (piece letter after '/')
  M e4xd5\r\n        capture  ('x' instead of '-')
  T x x\r\n          take-back request
  # N type\r\n       game over: N<5 -> draw, N>=5 -> checkmate
  New Game\r\n       user pressed the NEW GAME button on the board
  UCB CITRINE...     ID response (from 'I' command)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IMPORTANT OPERATING NOTES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  * Must send "Uon" (Referee mode) so the Citrine does not play its own
    moves; picochess feeds moves via 'm<move>'.
  * The board echoes every computer move sent via 'm…' back as 'M …'.
    This driver tracks the last sent move and ignores the echo.
  * Castling arrives as "M O-O" / "M O-O-O", not as coordinates.
  * Promotions use slash notation: "M e7-e8/Q".
  * Captures may use 'x': "M e4xd5".
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import chess
import serial_asyncio  # type: ignore  (pip install pyserial-asyncio)

from dgt.api import Event, Message
from utilities import Observable, DisplayMsg

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Serial parameters (mandated by Novag hardware – do not change)
# ─────────────────────────────────────────────────────────────────────────────
_BAUD     = 57_600
_BYTESIZE = 8
_PARITY   = "N"      # none
_STOPBITS = 1
_XONXOFF  = False    # ← must be False  (Citrine has no flow control)
_RTSCTS   = False    # ← must be False

# ─────────────────────────────────────────────────────────────────────────────
# Promotion letter -> chess piece type
# ─────────────────────────────────────────────────────────────────────────────
_PROMO: dict[str, chess.PieceType] = {
    "Q": chess.QUEEN,
    "R": chess.ROOK,
    "B": chess.BISHOP,
    "N": chess.KNIGHT,
}

# Regex that matches a coordinate move: "e2-e4", "e4xd5", "e2e4", "e7-e8/Q"
_COORD_RE = re.compile(
    r"([a-h][1-8])[-x]?([a-h][1-8])(?:[/]([QRBNqrbn]))?",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────────
# Move conversion helpers
# ─────────────────────────────────────────────────────────────────────────────

def _uci_to_novag(move: chess.Move, board: chess.Board) -> str:
    """
    Convert a python-chess Move to the Novag 'm' command payload.

    The returned string is appended directly after the leading 'm':
      chess.Move e2e4  →  "e2e4"
      castling e1g1    →  "O-O"
      castling e1c1    →  "O-O-O"
      promotion e7e8q  →  "e7e8/q"
    """
    uci = board.uci(move)

    # King-side castling
    if uci == "e1g1" and board.piece_type_at(chess.E1) == chess.KING:
        return "O-O"
    if uci == "e8g8" and board.piece_type_at(chess.E8) == chess.KING:
        return "O-O"
    # Queen-side castling
    if uci == "e1c1" and board.piece_type_at(chess.E1) == chess.KING:
        return "O-O-O"
    if uci == "e8c8" and board.piece_type_at(chess.E8) == chess.KING:
        return "O-O-O"
    # Promotion: append "/" + piece letter
    if len(uci) == 5:
        return uci[:4] + "/" + uci[4]
    # Normal move
    return uci


def _novag_to_move(body: str, turn: chess.Color) -> Optional[chess.Move]:
    """
    Parse the body of a "M …" line into a chess.Move.

    Parameters
    ----------
    body : str
        Text after the "M " prefix, stripped.
        Examples: "e2-e4", "O-O", "O-O-O", "e7-e8/Q", "e4xd5"
        The Citrine always uses letter-O notation for castling, never digit-0.
    turn : chess.Color
        Current side to move – needed to resolve castling target squares.

    Returns None when parsing fails.
    """
    s = body.strip()

    # ── Strip optional move-number prefix  e.g. "4   O-O", "10,  O-O" → "O-O"
    # The Citrine sometimes prepends the half-move count with spaces or ", ".
    s = re.sub(r"^\d+[,\s]\s*", "", s)

    # ── Castling (Citrine always sends "O-O" / "O-O-O" with letter O) ─────────
    if s.upper() == "O-O":
        return chess.Move(chess.E1, chess.G1) if turn == chess.WHITE \
               else chess.Move(chess.E8, chess.G8)
    if s.upper() == "O-O-O":
        return chess.Move(chess.E1, chess.C1) if turn == chess.WHITE \
               else chess.Move(chess.E8, chess.C8)

    # ── Coordinate move (handles '-', 'x', or no separator; optional '/P') ──
    m = _COORD_RE.search(s)
    if m:
        from_sq   = chess.parse_square(m.group(1).lower())
        to_sq     = chess.parse_square(m.group(2).lower())
        promo_str = m.group(3)
        promotion = _PROMO.get(promo_str.upper()) if promo_str else None
        return chess.Move(from_sq, to_sq, promotion=promotion)

    return None


def _normalise_for_echo(text: str) -> str:
    """Strip separators for echo comparison."""
    return text.upper().replace("-", "").replace("X", "").replace("/", "").strip()


# ─────────────────────────────────────────────────────────────────────────────
# NovagBoard
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# NovagDisplay — intercepts COMPUTER_MOVE messages and forwards to Citrine
# ─────────────────────────────────────────────────────────────────────────────

class NovagDisplay(DisplayMsg):
    """
    Registers as a display device so it receives all messages via DisplayMsg.show().
    When a COMPUTER_MOVE arrives, it forwards the move to the Citrine via send_move().
    """

    def __init__(self, citrine_board, loop):
        super().__init__(loop)
        self._citrine_board = citrine_board

    async def message_consumer(self):
        """Consume messages and forward COMPUTER_MOVE to Citrine."""
        while True:
            message = await self.msg_queue.get()
            try:
                if isinstance(message, Message.COMPUTER_MOVE):
                    if not message.is_user_move:
                        move = message.move
                        game = message.game
                        logger.info("NovagDisplay: forwarding computer move %s to Citrine", move.uci())
                        await self._citrine_board.send_move(move, game)
                elif isinstance(message, Message.PLAY_MODE):
                    from dgt.util import PlayMode
                    mode = message.play_mode
                    # user plays Black  ⇒  the computer plays White  ⇒  send 'F'
                    # so the Citrine is inverted (Black side at the bottom).
                    computer_white = (mode == PlayMode.USER_BLACK)
                    logger.info("NovagDisplay: PLAY_MODE %s — orienting Citrine (computer_white=%s)",
                                mode, computer_white)
                    await self._citrine_board.set_computer_color(computer_white)
            except Exception as exc:
                logger.error("NovagDisplay: error processing message: %s", exc)
            finally:
                self.msg_queue.task_done()

class NovagBoard:
    """
    Async driver for the Novag Citrine electronic chess board.

    Lifecycle
    ---------
    1.  ``await board.connect(port)``
            Opens the serial port, sends Xon + Uon, starts the read loop.
    2.  The background ``_read_loop`` task fires Observable events:
            Event.KEYBOARD_MOVE  – for every human move received
            Event.NEW_GAME       – when user presses the board's NEW GAME key
            Event.TAKE_BACK      – when user requests take-back on the board
    3.  ``await board.send_move(move, chess_board)``
            Sends the computer's move and records it to suppress the echo.
    4.  ``board.set_turn(color)``
            Keep the driver in sync with the current side to move (needed
            for correct castling square resolution).
    5.  ``await board.new_game()``
            Restart the board when picochess starts a new game.
    6.  ``await board.disconnect()``
            Clean shutdown.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop   = loop
        self._port: Optional[str]               = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected  = False
        self._read_task: Optional[asyncio.Task] = None

        # Last computer move sent (normalised), used to suppress echo
        self._last_sent: Optional[str] = None

        # Current side to move – maintained externally via set_turn()
        self._turn = chess.WHITE

        # Referee-mode orientation: False = computer plays Black (default after N),
        # True = computer plays White. Flipped with the 'F' command via
        # set_computer_color() so the Citrine is inverted when the user plays Black.
        self._computer_is_white = False

        # Orientation is chosen once per game (at setup, before the first human
        # move). After play starts it is frozen, so the PLAY_MODE messages that
        # picochess re-emits after every take-back (derived from game.turn, i.e.
        # alternating USER_WHITE/USER_BLACK) can no longer trigger a spurious 'F'
        # board flip — which previously broke successive take-backs.
        self._orientation_locked = False

        self.board_version = "Novag Citrine"

        # EBoard protocol attributes (required by picochess/server.py)
        self.is_pi                = False
        self.is_revelation        = False
        self.enable_revelation_pi = False
        self.l_time               = 0
        self.r_time               = 0
        self.disable_end          = True
        self.in_settime           = False
        self.low_time             = False

    # ─────────────────────────────────────────────────────────────────────────
    # Public interface
    # ─────────────────────────────────────────────────────────────────────────

    async def connect(self, port: str) -> bool:
        """
        Open the serial port and initialise the Citrine for external play.

        Returns True on success, False on failure.
        """
        self._port = port
        logger.info("NovagBoard: opening %s …", port)
        try:
            self._reader, self._writer = await serial_asyncio.open_serial_connection(
                url=port,
                baudrate=_BAUD,
                bytesize=_BYTESIZE,
                parity=_PARITY,
                stopbits=_STOPBITS,
                xonxoff=_XONXOFF,
                rtscts=_RTSCTS,
            )
        except Exception as exc:
            logger.error("NovagBoard: cannot open %s: %s", port, exc)
            return False

        self._connected = True
        logger.info("NovagBoard: serial port %s opened", port)

        # Short pause to let the hardware settle
        await asyncio.sleep(0.05)

        # Enable move-echo (sent twice, as in citinter.py)
        await self._send("Xon")
        await asyncio.sleep(0.1)
        await self._send("Xon")
        await asyncio.sleep(0.1)

        # Query board identity (reply handled in _read_loop)
        await self._send("I")
        await asyncio.sleep(0.3)

        # Start fresh game first, THEN disable Citrine engine
        # (N resets Referee mode, so Uon must come after N)
        await self._send("N")
        await asyncio.sleep(0.3)
        await self._send("Uon")
        await asyncio.sleep(0.3)
        await self._send("Uon")   # sent twice to ensure Referee mode is active
        await asyncio.sleep(0.1)

        # Launch background reader
        self._read_task = self._loop.create_task(self._read_loop())

        logger.info("NovagBoard: ready on %s", port)
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # EBoard protocol stubs (no-ops – Citrine has no LEDs or clock display)
    # ─────────────────────────────────────────────────────────────────────────

    def light_squares_on_revelation(self, uci_move: str) -> None:
        pass

    def light_square_on_revelation(self, square: str) -> None:
        pass

    def clear_light_on_revelation(self) -> None:
        pass

    def run(self) -> None:
        pass

    def set_text_rp(self, text: bytes, beep: int) -> None:
        pass

    def set_text_xl(self, text: str, beep: int, left_icons=None, right_icons=None) -> None:
        pass

    def set_text_3k(self, text: bytes, beep: int) -> None:
        pass

    def set_and_run(self, lr, lh, lm, ls, rr, rh, rm, rs) -> None:
        pass

    def end_text(self) -> None:
        pass

    def promotion_done(self, uci_move: str) -> None:
        pass

    async def disconnect(self) -> None:
        """Cleanly shut down the board connection."""
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None

        if self._writer:
            try:
                await self._send("Xoff")
                await self._send("Uoff")
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None

        self._reader    = None
        self._connected = False
        logger.info("NovagBoard: disconnected from %s", self._port)

    async def new_game(self) -> None:
        """
        Signal a new game to the Citrine.

        Must be called when picochess starts a fresh game (not in response
        to the board's own NEW GAME button – that arrives as an event).
        """
        if not self._connected:
            return
        self._turn       = chess.WHITE
        self._last_sent  = None
        self._computer_is_white = False   # N resets the board to computer=Black
        self._orientation_locked = False  # allow orientation to be set for the new game
        # Briefly exit Referee mode, send N, re-enter Referee mode
        await self._send("Uoff")
        await asyncio.sleep(0.05)
        await self._send("N")
        await asyncio.sleep(0.1)
        await self._send("Uon")
        await asyncio.sleep(0.05)
        logger.debug("NovagBoard: new game sent")

    async def send_move(self, move: chess.Move, board: chess.Board) -> None:
        """
        Send the computer's move to the Citrine.

        Parameters
        ----------
        move  : the engine's chosen move (legal, not yet pushed to board)
        board : the chess.Board position *before* the move is pushed
        """
        if not self._connected:
            return
        payload = _uci_to_novag(move, board)
        # Store normalised version for echo suppression
        self._last_sent = _normalise_for_echo(payload)
        cmd = "m" + payload
        logger.info("NovagBoard → move %s  (cmd %r)", move.uci(), cmd)
        await self._send(cmd)
        await asyncio.sleep(0.15)
        await self._send(cmd)          # second send — Citrine needs it to light LEDs
        self._turn = not board.turn    # next to move is the opponent

    def set_turn(self, turn: chess.Color) -> None:
        """
        Keep the driver in sync with the current side to move.

        picochess should call this after every move (human or computer)
        so that castling moves arriving from the board are decoded correctly.
        """
        self._turn = turn

    async def set_computer_color(self, computer_white: bool) -> None:
        """
        Orient the Citrine so that the *computer* plays ``computer_white``.

        'F' on the Citrine is a *toggle* ("board takes opposite side"), so we
        only send it when the requested orientation differs from the current
        one. This makes the call idempotent: repeated PLAY_MODE messages, new
        games, etc. never desynchronise the physical board.

        Called by NovagDisplay on Message.PLAY_MODE. When the user switches to
        Black, the computer plays White → 'F' is sent → the Citrine is inverted
        (Black side at the bottom), matching the web display.
        """
        if not self._connected:
            return
        if self._orientation_locked:
            logger.debug("NovagBoard: orientation locked — ignoring PLAY_MODE "
                         "(computer_is_white stays %s)", self._computer_is_white)
            return
        if computer_white != self._computer_is_white:
            await self._send("F")
            self._computer_is_white = computer_white
            logger.info("NovagBoard: 'F' sent — computer_is_white=%s (board inverted=%s)",
                        computer_white, computer_white)
        else:
            logger.debug("NovagBoard: orientation already correct (computer_is_white=%s)", computer_white)

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _send(self, text: str) -> None:
        """Write *text* followed by CRLF to the serial port."""
        if self._writer is None:
            return
        data = (text + "\r\n").encode("ascii")
        logger.debug("NovagBoard → raw %r", data)
        try:
            self._writer.write(data)
            await self._writer.drain()
        except Exception as exc:
            logger.error("NovagBoard: write error: %s", exc)
            self._connected = False

    async def _read_loop(self) -> None:
        """
        Background coroutine: read lines from the Citrine and dispatch events.

        Lines are ASCII text terminated with \\r\\n (or bare \\r or \\n).
        """
        assert self._reader is not None
        buf = b""

        while True:
            try:
                chunk = await self._reader.read(256)
                if not chunk:
                    logger.warning("NovagBoard: device closed the connection")
                    break
                buf += chunk

                # Extract all complete lines from the buffer
                while True:
                    found = False
                    for sep in (b"\r\n", b"\n", b"\r"):
                        idx = buf.find(sep)
                        if idx >= 0:
                            line_bytes = buf[:idx]
                            buf = buf[idx + len(sep):]
                            line = line_bytes.decode("ascii", errors="ignore").strip()
                            if line:
                                await self._handle_line(line)
                            found = True
                            break
                    if not found:
                        break   # wait for more data

            except asyncio.CancelledError:
                logger.debug("NovagBoard: read loop cancelled")
                break
            except Exception as exc:
                logger.error("NovagBoard: read error: %s", exc)
                break

        self._connected = False

    async def _handle_line(self, line: str) -> None:
        """Route one decoded line to the appropriate handler."""
        logger.debug("NovagBoard ← %r", line)

        # ── Board identification ──────────────────────────────────────────────
        if "UCB" in line or line.upper().startswith("CITRINE"):
            self.board_version = line.strip()
            logger.info("NovagBoard: identified as '%s'", self.board_version)
            return

        # ── Acknowledgement / informational lines ─────────────────────────────
        lo = line.lower()
        if lo.startswith(("xmit", "uon", "uoff", "level", "game ")):
            return

        # ── New-game button pressed on the Citrine ────────────────────────────
        if lo == "new game" or lo.startswith("new game"):
            logger.info("NovagBoard: New Game button pressed on board")
            # The board's own N resets it to the default orientation
            # (computer=Black). Resync our trackers WITHOUT sending 'F'.
            self._turn = chess.WHITE
            self._computer_is_white = False
            self._orientation_locked = False
            await Observable.fire(Event.NEW_GAME(pos960=518))
            # Re-enable Referee mode — N resets it on the Citrine
            await asyncio.sleep(0.2)
            await self._send("Uon")
            await asyncio.sleep(0.2)
            await self._send("Uon")
            return

        # ── Take-back  "T <n> <n>" ────────────────────────────────────────────
        # "T   2   g1-f3"  sans virgule = takeback d'un coup Blanc
        # "T   2,  b8-c6"  avec virgule = takeback d'un coup Noir
        # Les deux sont de vrais takebacks — la virgule indique juste la couleur
        if line.startswith("T ") and len(line) >= 4:
            logger.info("NovagBoard: take-back received: %r", line)
            await Observable.fire(Event.TAKE_BACK(take_back="TAKEBACK"))
            return

        # ── Game-over  "# N <info>" ───────────────────────────────────────────
        if line.startswith("#"):
            await self._handle_game_over(line)
            return

        # ── Move  "M <body>" ──────────────────────────────────────────────────
        if line.startswith("M "):
            await self._handle_move_line(line[2:].strip())
            return

        logger.debug("NovagBoard: ignored: %r", line)

    async def _handle_game_over(self, line: str) -> None:
        """
        Parse a game-over line "# N …" from the Citrine.

        N < 5  → draw (50-move rule / repetition / insufficient material)
        N ≥ 5  → checkmate
        """
        logger.info("NovagBoard: game-over: %r", line)
        parts = line.split()
        try:
            n = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            n = 0

        if n < 5:
            await Observable.fire(Event.DRAWRESULT(result=True))
        else:
            await Observable.fire(Event.MATERESULT(result=True))

    async def _handle_move_line(self, body: str) -> None:
        """
        Process the body of an "M …" line.

        The Citrine echoes every computer move we sent via 'm…' back as
        'M …'.  We detect and discard that echo; real human moves are
        forwarded as KEYBOARD_MOVE events.
        """
        # ── Echo suppression ─────────────────────────────────────────────────
        if self._last_sent is not None:
            if _normalise_for_echo(body) == self._last_sent:
                logger.debug("NovagBoard: suppressed echo of %r", body)
                self._last_sent = None   # consume the echo
                return

        # ── Parse human move ─────────────────────────────────────────────────
        move = _novag_to_move(body, self._turn)
        if move is None:
            logger.warning("NovagBoard: cannot parse move body %r", body)
            return

        logger.info("NovagBoard: human move %s", move.uci())

        # A real move has been played: freeze the board orientation for the rest
        # of the game so post-take-back PLAY_MODE messages cannot flip it.
        self._orientation_locked = True

        # Flip turn tracker
        self._turn = not self._turn

        # Dispatch the event – identical to what DGT/Chessnut/etc. drivers do
        await Observable.fire(Event.KEYBOARD_MOVE(move=move))
