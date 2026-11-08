"""
Saitek OSA e-board driver for picochess v4.

Protocol reverse-engineered from the user's "LOG OSA.txt" capture of a real
session against a board that announces itself as:

    - Saitek OSA (9600 baud), Version 1.4 -

This driver is the OSA counterpart of the Novag Citrine driver: it plugs into
picochess through the exact same two objects (an ``EBoard``-protocol board and
a ``DisplayMsg`` consumer), but speaks the OSA serial protocol instead of the
Novag one.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LED HANDLING AT A GLANCE — WHO DRIVES WHAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  This variant sends NO DSA / MOSAL message 27 writes at all (no LED
  addressing code exists in this file). ALL move guidance, for BOTH a normal
  move AND a capture, is 100% FIRMWARE: FROM and TO are blinked entirely by
  the board's own native logic, including on a capture (where the firmware
  simply shows nothing extra for the occupied TO square — this driver does
  not attempt to fill that gap). Compatible with any board whose firmware
  handles its own move display, including Renaissance, PRECISELY BECAUSE this
  driver never touches the LEDs itself.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SERIAL PARAMETERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  9 600 baud · 8 data bits · 1 stop bit · no parity · NO flow control
  Link: Bluetooth SPP, presented as a serial device — bound to /dev/rfcomm0
  (the Novag Citrine uses /dev/rfcomm1). Over rfcomm the baud rate is handled
  by the Bluetooth stack; 9600 is kept to match the board's announced setting.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMMANDS  (PC → board, ASCII text, terminated with \\r\\n)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  OPEN              start communication  -> board replies its ID string
  CLOSE             end communication
  NEW               start a new game     -> board replies "New Game"
  ANALYSIS          analysis mode: the board's *internal* engine stays
                    silent and the board only reports the human's moves.
                    This is OSA's "external engine / referee" equivalent and
                    must be active whenever we expect a human move back.
  NORMAL            normal display mode (not used: it un-flips the board)
  PLAY              play mode
  BOARD OFF         disable the board (LEDs) before injecting our move
  BOARD ON          enable the board (lights up the move we just sent)
  MOVE <FROM>-<TO>  inject the engine's move, UPPERCASE coordinates,
                    e.g. "MOVE E7-E6", "MOVE O-O", "MOVE E7-E8/Q"
  POSITION          dump the current position as an ASCII diagram
  ?                 list every OSA keyword

  Move-injection choreography (one full ply), exactly as in the log:

      (human move arrives)                 board ->  "  2. e4-e5   00:31"
      BOARD OFF                            PC   ->   acknowledge / disarm
      MOVE D7-D5                           PC   ->   the engine's reply
      BOARD ON                             PC   ->   light the move
      ANALYSIS                             PC   ->   show it + re-arm next move

  ANALYSIS alone displays the injected move and re-arms reception of the next
  human move; NORMAL is not needed. The board is also put in analysis
  at connect / new game so the internal engine stays silent.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MESSAGES  (board → PC)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  "  1. e2-e4   00:00"   a White move  (left column, prefixed by "N.")
  "          e7-e6   00:29"   a Black move  (right column, no number)
  "Qd8xd6   00:57"       capture, with piece letter ('x' = capture)
  "e5xd6ep  00:39"       en-passant capture ('ep' suffix)
  "Bf1-b5+  00:31"       check  ('+' suffix)
  "Qh5-g5++ 00:37"       checkmate ('++' suffix)
  "O-O" / "O-O-O"        castling (letter O, never zero)
  "New Game"             a new game on the board — the user reset the pieces
                         to the starting position (or pressed NEW GAME)
  "Takeback"             the user physically played a move backwards on the
                         board (one line per ply undone, sometimes garbled
                         e.g. "TTTTTakeback")
  "1-0" / "0-1" / "1/2-1/2"   game result line
  "- Saitek OSA ... -"   ID string (reply to OPEN)
  "???"                  the board rejected the last command/move

IMPORTANT
  * LINE FRAMING IS MIXED. The board terminates its *prompt* and its
    *human-move* lines with the single byte 0x17 (the "[17]" seen in the raw
    capture was this byte, not a logging artifact), e.g.
        b'  1. e2-e4    00:00  \\x17'      <- a human move
        b'>\\x17'                          <- the idle prompt ('>' + 0x17)
    while command replies and the echo of an injected move use CRLF, e.g.
        b'                      e7-e5    00:36\\r\\n'
    The read loop therefore treats 0x17 as a line separator too (and strips the
    leading '>' of the prompt); otherwise human moves never form a complete
    line and never reach picochess.
  * The board ECHOES the move we inject (the "MOVE E7-E5" comes back as a
    normal move line such as "e7-e6  00:29" or "Qd8xd6  00:57").  This driver
    tracks a signature of the last injected move and discards that echo so it
    is never mistaken for a human move.
  * White moves carry the leading "N." move number, Black moves do not — that
    is only a display column, NOT a human-vs-engine indicator, so it is never
    used to classify a move.
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
# Serial parameters (OSA over Bluetooth SPP / rfcomm)
# ─────────────────────────────────────────────────────────────────────────────
_BAUD     = 9_600
_BYTESIZE = 8
_PARITY   = "N"      # none
_STOPBITS = 1
_XONXOFF  = False    # no software flow control
_RTSCTS   = False    # no hardware flow control
_EOL      = "\r\n"   # line terminator for PC -> board (CRLF). If your board
                     # needs bare CR, change this to "\r".

# The OSA board is synchronous on 0x17: after a command it returns the single
# byte 0x17 once that command has been integrated and it is ready for the next
# — the byte the reference BASIC driver blocks on with
#     Print #2, cmd
#     Do : dat = Input(1, #2) : Loop Until dat = Chr(&H17)
# So we wait for that 0x17 after each command before sending the next. We
# proceed the INSTANT it arrives (board speed), never sleeping blindly.
#
# Two timeouts, because they bound two very different waits:
#  * _ACK_TIMEOUT — OPEN / NEW: the board genuinely takes ~2-3 s to reset and
#    reply (ID string / "New Game"), and it ALWAYS replies, so we wait long.
#    This is where 0x17 fixed the old "no New Game within 6 s / garbled ID".
#  * _CMD_ACK_TIMEOUT — fast in-game commands (BOARD OFF/ON, MOVE, NORMAL,
#    ANALYSIS, PLAY). LOG_OSA.txt shows that on this board EVERY command — not
#    just the slow handshake ones — returns to the ">" idle prompt and emits a
#    0x17 the instant it is integrated: there is a ">" + 0x17 in front of every
#    single command the PC sends (BOARD OFF, MOVE, BOARD ON, NORMAL, ANALYSIS).
#    So in normal play none of these ever reach this timeout — each _send
#    unblocks the moment its 0x17 arrives (board speed). This cap is therefore a
#    pure safety net for a genuinely dropped/garbled ack (e.g. a Bluetooth
#    glitch); it does NOT add per-move latency. A timeout here is logged so a
#    never-acking command is visible.
_CMD_ACK_TIMEOUT = 1.2
_ACK_TIMEOUT     = 3.5

# How long (seconds) a "New Game" reply is still treated as the ack to a NEW we
# sent ourselves, rather than a physical user reset. It must cover the gap
# between issuing NEW and the board emitting "New Game" (which arrives just
# before that command's 0x17 ack), with margin.
_NEWGAME_SUPPRESS_WINDOW = 6.0

# One physical take-back on the board is reported by the OSA board as a BURST of
# "Takeback" lines, often garbled (e.g. "Takeback", "TTTTTTTTTTTakeback"), all
# arriving back-to-back — LOG_OSA.txt: "WHEN MOVE TAKE BACK BOARD SEND Tackback
# each time". picochess pops exactly ONE ply per Event.TAKE_BACK (state.pop_move),
# so firing one event per line pops several plies for a single physical undo:
# after the very first take-back the move stack is already emptied / desynced and
# every later take-back is gated out by picochess (`if game.move_stack and …`) —
# i.e. "take-back stops working after the first one". We therefore coalesce a
# burst into a single Event.TAKE_BACK: the first "Takeback" fires, and any further
# take-back line within this window is swallowed. A real second physical undo
# takes far longer than this to perform, so it is never lost.
_TAKEBACK_DEBOUNCE = 1.0
# A take-back seen while we are still waiting for the HUMAN's actual reply to
# our own last MOVE/BOARD ON/ANALYSIS (i.e. _awaiting_human_reply is True) is
# treated as a manipulation error, not a real undo: it can only be a reversed-
# order pickup on that pending move (whether it's the human physically
# replaying our own injected move, or the human's own next capture) -- there
# is no legitimate earlier ply to undo yet. In that -- and ONLY that -- case
# we do not forward Event.TAKE_BACK; we immediately re-send the move sequence
# (BOARD OFF / MOVE / BOARD ON / ANALYSIS) instead. Any take-back seen outside
# that window is genuine and forwarded normally.

_RESEND_SETTLE_DELAY = 1.5  # seconds to wait BEFORE starting the manipulation-
                            # error resend. Evidence (log): firing BOARD OFF
                            # immediately after the take-back burst got no
                            # 0x17 ack within the normal 1.2s window, and the
                            # very next command (MOVE) was then rejected
                            # outright ('???') -- the board was still busy
                            # digesting the take-back burst internally. The
                            # move logic self-corrects regardless (the real
                            # completion echo is still recognised later), but
                            # the '???' appears to leave the firmware's native
                            # LED guidance dark for the rest of that move. This
                            # delay gives the board time to finish settling
                            # before we touch it again. Tune based on testing;
                            # 1.5s is a first guess, not a measured minimum.

# Like take-backs, a single physical reset / NEW GAME press can make the OSA
# board emit the "New Game" line MORE THAN ONCE (a short burst). picochess
# aborts the running game and starts a fresh one on EVERY Event.NEW_GAME, so one
# event per burst line makes it announce "abort" + "new game" several times for a
# single reset. We coalesce the burst: the first board-originated "New Game"
# fires Event.NEW_GAME, any further one within this window is swallowed. A real
# second manual reset takes far longer than this, so it is never lost. (This is
# independent of the _pending_new_acks counter, which only suppresses the reply
# to a NEW *we* sent.)
_NEWGAME_DEBOUNCE = 1.5

# ─────────────────────────────────────────────────────────────────────────────
# Promotion letter -> chess piece type
# ─────────────────────────────────────────────────────────────────────────────
_PROMO: dict[str, chess.PieceType] = {
    "Q": chess.QUEEN,
    "R": chess.ROOK,
    "B": chess.BISHOP,
    "N": chess.KNIGHT,
}

# A line that contains a real move: a coordinate pair "e2-e4"/"e4xd5" or castling.
# (Squares are lower-case on the wire; the optional leading piece letter and the
#  trailing "+/++/ep/time" are handled by the parser, not here.)
_LOOKS_LIKE_MOVE = re.compile(r"[a-h][1-8][-x][a-h][1-8]|O-O-O|O-O")

# A coordinate move inside a token, e.g. "e2-e4", "e5xd6", "f1b5", "e7-e8/Q".
_COORD_RE = re.compile(r"([a-h][1-8])[-x]?([a-h][1-8])(?:ep)?(?:[/=]([QRBNqrbn]))?")

# A game-result line on its own.
_RESULT_RE = re.compile(r"^\s*(1-0|0-1|1/2-1/2|½-½)\s*$")


# ─────────────────────────────────────────────────────────────────────────────
# Move conversion helpers
# ─────────────────────────────────────────────────────────────────────────────

def _strip_move_decorations(token: str) -> str:
    """Remove the move-number prefix, the trailing clock time and any check/mate
    markers, leaving just the bare move text (e.g. ``Qd8xd6`` or ``O-O``)."""
    t = token.strip()
    t = re.sub(r"\s+\d{1,2}:\d{2}.*$", "", t)   # trailing "   00:31" + rest
    t = re.sub(r"^\d+\.\s*", "", t)             # leading "12. "
    t = t.rstrip("+#").strip()                  # check / mate markers
    return t


def _move_signature(token: str) -> str:
    """
    Reduce any OSA move text — whatever its decoration — to a compact,
    direction-independent signature used purely for echo detection.

        "  2. e4-e5   00:31"  -> "E4E5"
        "Qd8xd6  00:57"       -> "D8D6"
        "e5xd6ep  00:39"      -> "E5D6"
        "E7-E8/Q"             -> "E7E8Q"
        "O-O"                 -> "OO"
        "O-O-O"               -> "OOO"

    Comparing signatures (rather than reconstructing a chess.Move) avoids the
    castling-square ambiguity that would otherwise depend on whose turn it is.
    """
    t = _strip_move_decorations(token).upper()
    if t in ("O-O", "0-0"):
        return "OO"
    if t in ("O-O-O", "0-0-0"):
        return "OOO"
    # NB: piece letter (K/Q/R/B/N) is never followed by a digit, so the first
    # "[A-H][1-8]" match is always the from-square, never the piece letter.
    m = re.search(r"([A-H][1-8]).{0,2}?([A-H][1-8])(?:EP)?(?:[/=]?([QRBN]))?", t)
    if not m:
        return ""
    promo = m.group(3) or ""
    return m.group(1) + m.group(2) + promo


def _uci_to_osa(move: chess.Move, board: chess.Board) -> str:
    """
    Convert a python-chess Move to the payload that follows ``MOVE `` on the
    wire (UPPERCASE, dash separator):

        e2e4  -> "E2-E4"
        e1g1  -> "O-O"      (king-side castling)
        e1c1  -> "O-O-O"    (queen-side castling)
        e7e8q -> "E7-E8/Q"  (promotion)
    """
    uci = board.uci(move)

    if uci in ("e1g1", "e8g8") and board.piece_type_at(move.from_square) == chess.KING:
        return "O-O"
    if uci in ("e1c1", "e8c8") and board.piece_type_at(move.from_square) == chess.KING:
        return "O-O-O"

    frm, to = uci[0:2].upper(), uci[2:4].upper()
    if len(uci) == 5:                       # promotion
        return f"{frm}-{to}/{uci[4].upper()}"
    return f"{frm}-{to}"


def _osa_to_move(token: str, turn: chess.Color) -> Optional[chess.Move]:
    """
    Parse a board move line into a chess.Move.

    ``turn`` is the side that just moved, needed only to resolve castling
    target squares. Returns ``None`` when the text cannot be parsed.
    """
    t = _strip_move_decorations(token)
    up = t.upper()

    if up in ("O-O", "0-0"):
        return chess.Move(chess.E1, chess.G1) if turn == chess.WHITE \
            else chess.Move(chess.E8, chess.G8)
    if up in ("O-O-O", "0-0-0"):
        return chess.Move(chess.E1, chess.C1) if turn == chess.WHITE \
            else chess.Move(chess.E8, chess.C8)

    m = _COORD_RE.search(t)
    if not m:
        return None
    from_sq = chess.parse_square(m.group(1).lower())
    to_sq   = chess.parse_square(m.group(2).lower())
    promo   = _PROMO.get(m.group(3).upper()) if m.group(3) else None
    return chess.Move(from_sq, to_sq, promotion=promo)


# ─────────────────────────────────────────────────────────────────────────────
# OsaDisplay — intercepts COMPUTER_MOVE messages and forwards them to the board
# ─────────────────────────────────────────────────────────────────────────────

class OsaDisplay(DisplayMsg):
    """
    Registers as a display device so it receives every message via
    ``DisplayMsg.show()``.  On ``COMPUTER_MOVE`` it injects the move into the
    OSA board; on ``PLAY_MODE`` it records which colour the user plays.
    """

    def __init__(self, osa_board, loop):
        super().__init__(loop)
        self._osa_board = osa_board

    async def message_consumer(self):
        while True:
            message = await self.msg_queue.get()
            try:
                if isinstance(message, Message.COMPUTER_MOVE):
                    if not message.is_user_move:
                        move = message.move
                        game = message.game
                        logger.info("OsaDisplay: forwarding computer move %s to OSA board",
                                    move.uci())
                        await self._osa_board.send_move(move, game)
                elif isinstance(message, Message.PLAY_MODE):
                    from dgt.util import PlayMode
                    mode = message.play_mode
                    # user plays Black  ⇒  the computer plays White
                    computer_white = (mode == PlayMode.USER_BLACK)
                    logger.info("OsaDisplay: PLAY_MODE %s (computer_white=%s)",
                                mode, computer_white)
                    await self._osa_board.set_computer_color(computer_white)
            except Exception as exc:
                logger.error("OsaDisplay: error processing message: %s", exc)
            finally:
                self.msg_queue.task_done()


# ─────────────────────────────────────────────────────────────────────────────
# OsaBoard
# ─────────────────────────────────────────────────────────────────────────────

class OsaBoard:
    """
    Async driver for a Saitek OSA electronic chess board.

    Lifecycle
    ---------
    1.  ``await board.connect(port)``  – open serial, OPEN/NEW/ANALYSIS, read loop.
    2.  background ``_read_loop`` fires Observable events:
            Event.KEYBOARD_MOVE – every human move received
            Event.NEW_GAME      – the board's NEW GAME button
            Event.TAKE_BACK     – a take-back on the board
    3.  ``await board.send_move(move, chess_board)`` – inject the engine's move.
    4.  ``board.set_turn(color)`` – keep castling resolution in sync.
    5.  ``await board.new_game()`` – picochess started a fresh game.
    6.  ``await board.disconnect()`` – clean shutdown.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._port: Optional[str] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._read_task: Optional[asyncio.Task] = None

        # Echo suppression: signature of the last move we injected.
        self._last_sent_sig: Optional[str] = None

        # Number of "New Game" replies still expected as acks to NEW commands
        # we sent ourselves (so they are not misread as the user pressing NEW).
        # Bounded in time (_suppress_newgame_until) so the counter cannot drift:
        # a "New Game" arriving after the window is always treated as a real
        # user reset and forwarded to picochess.
        self._pending_new_acks = 0
        self._suppress_newgame_until = 0.0

        # The OSA board is synchronous on 0x17: it emits that single byte once
        # it has finished processing a command and is ready for the next one
        # (the exact byte the reference BASIC driver blocks on with
        # "Do dat=Input(1,#2) Loop Until dat=Chr(&H17)" after every Print #2).
        # The read loop sets this event on every 0x17; each command then waits
        # for it instead of sleeping a fixed amount.
        self._ack_event = asyncio.Event()

        # Serialise command/ack cycles so two coroutines can never interleave a
        # write with another command's 0x17 wait (mirrors the BASIC model where
        # exactly one command is in flight at a time).
        self._cmd_lock = asyncio.Lock()

        # Current side to move (for castling-square resolution).
        self._turn = chess.WHITE

        # True once "BOARD ON" has been sent (so send_move knows whether it
        # must "BOARD OFF" first). After OPEN/NEW the board is showing -> True.
        self._board_on = True

        # Referee/orientation bookkeeping (kept for parity with the Citrine
        # driver; OSA has no physical flip, so this is informational only).
        self._computer_is_white = None    # None until the first PLAY_MODE

        # True once a move (human or engine) has been played in the current game.
        # picochess re-emits Message.PLAY_MODE whenever the side TO MOVE changes
        # (set_wait_state derives play_mode from game.turn), e.g. after a
        # take-back. A physical board's orientation is fixed for the game, so we
        # only honour an orientation flip BEFORE the first move; any PLAY_MODE
        # after play starts is a turn change, not a colour choice, and must NOT
        # flip the board (doing so left it dark after a take-back).
        self._game_started = False

        # Grace window after connect during which the "New Game" reply to our
        # own NEW command must NOT be re-fired as a board-button event.
        self._connect_time = 0.0

        # Timestamp of the last take-back we forwarded, to coalesce the board's
        # repeated/garbled "Takeback" burst into a single Event.TAKE_BACK.
        self._last_takeback_time = 0.0

        # Raw payload of the last MOVE we sent (for the manipulation-error
        # resend below) and whether we're still awaiting the human's real
        # reply to it.
        self._last_sent_payload: Optional[str] = None
        self._awaiting_human_reply = False  # True from our own MOVE/BOARD ON/
                                             # ANALYSIS until the human's real
                                             # reply move is confirmed

        # Timestamp of the last board-originated "New Game" we forwarded, to
        # coalesce a repeated "New Game" burst into a single Event.NEW_GAME
        # (otherwise picochess announces "abort" + "new game" once per line).
        self._last_newgame_time = 0.0

        # Pending trailing-edge ANALYSIS re-arm after a board "New Game" burst.
        # Rescheduled on every burst line so it runs only once the board has
        # settled (ANALYSIS sent mid-reset is silently dropped by the board).
        self._newgame_arm_task: Optional[asyncio.Task] = None

        self.board_version = "Saitek OSA"

        # EBoard-protocol attributes required by picochess/server.py
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
        """Open the serial port and put the OSA board into external-engine mode."""
        self._port = port
        logger.info("OsaBoard: opening %s …", port)
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
            logger.error("OsaBoard: cannot open %s: %s", port, exc)
            return False

        self._connected = True
        self._connect_time = self._loop.time()
        logger.info("OsaBoard: serial port %s opened", port)

        # Start the reader FIRST so we can wait for the board's acknowledgments
        # during the handshake (the board has a 2-3 s reply latency).
        self._board_on = True
        self._turn = chess.WHITE
        self._last_sent_sig = None
        self._ack_event.clear()
        self._read_task = self._loop.create_task(self._read_loop())
        await asyncio.sleep(0.1)

        await self._handshake()

        # Tell picochess to start a fresh game, in sync with the board that we
        # just reset (NEW) during the handshake.
        logger.info("OsaBoard: sending NEW_GAME to picochess at startup")
        await Observable.fire(Event.NEW_GAME(pos960=518))

        # NEW_GAME alone does NOT refresh the displays at startup: picochess's
        # NEW_GAME handler only emits START_NEW_GAME when it believes the game
        # actually changed (move_stack non-empty, etc.), which is false on a
        # fresh boot — so the web display never gets the initial position. Real
        # eboards report their scanned FEN at startup and that drives the board
        # display; the OSA board never sends a FEN, so we push the starting
        # position explicitly. Event.KEYBOARD_FEN -> Message.DGT_FEN updates the
        # web board directly, with no side effects (no process_fen / restore /
        # wrong-fen logic).
        logger.info("OsaBoard: pushing start position to displays")
        await Observable.fire(Event.KEYBOARD_FEN(fen=chess.STARTING_BOARD_FEN))

        # Arm the board for the human's move now, instead of relying on the
        # first PLAY_MODE -> set_computer_color to do it. After NEW the OSA board
        # sits in its native NORMAL mode (internal engine active); the handshake
        # leaves it there on purpose (post-NEW is the only state PLAY flips from
        # for the engine-White case). But on a fresh boot picochess does not
        # reliably re-emit PLAY_MODE for the startup NEW_GAME (same reason the
        # comment above notes START_NEW_GAME is withheld), so set_computer_color
        # is never called and the board stays in NORMAL.
        #
        # _arm_after_reset sends ANALYSIS + BOARD ON, the human-White default —
        # the orientation the board itself boots into. We can await it directly
        # here (we are in connect, NOT the read loop, so the read loop stays free
        # to deliver the 0x17 acks). _computer_is_white is left None, so if the
        # user picks Black, the PLAY_MODE(True) that follows still passes
        # set_computer_color's guard and performs the BOARD OFF + PLAY flip.
        await self._arm_after_reset()

        logger.info("OsaBoard: ready on %s", port)
        return True

    async def _handshake(self) -> None:
        """OPEN / NEW / ANALYSIS / BOARD ON, each blocking on the board's 0x17
        acknowledgment before the next command — the board is synchronous on
        0x17 (like the reference BASIC driver), so this is the only reliable way
        to pace the handshake. ANALYSIS sent before the board has finished
        resetting from NEW is otherwise silently dropped and the internal engine
        stays on."""
        # OPEN -> the board replies its ID string, then acks with 0x17 (slow).
        await self._send("OPEN", ack_timeout=_ACK_TIMEOUT)

        # NEW -> the board resets, replies "New Game", then acks with 0x17.
        # Arm the suppression BEFORE sending: the "New Game" line arrives DURING
        # the ack wait (just before this command's 0x17), so the counter must
        # already be set or that reply would be misread as a physical reset.
        self._pending_new_acks += 1
        self._suppress_newgame_until = self._loop.time() + _NEWGAME_SUPPRESS_WINDOW
        await self._send("NEW", ack_timeout=_ACK_TIMEOUT)

        # Do NOT arm ANALYSIS / BOARD ON here. The board is left in the clean
        # post-NEW state, which is the ONLY state PLAY flips from. The board is
        # then armed PER COLOUR on the first PLAY_MODE (set_computer_color):
        # Black -> ANALYSIS + BOARD ON ; White -> BOARD OFF + PLAY (flip). This
        # keeps a single NEW per game (no re-NEW needed to undo an ANALYSIS).
        self._board_on = False
        logger.info("OsaBoard: handshake complete (post-NEW; armed per colour on PLAY_MODE)")

    async def new_game(self) -> None:
        """picochess started a fresh game (not the board's own NEW GAME button)."""
        if not self._connected:
            return
        self._turn = chess.WHITE
        self._last_sent_sig = None
        self._awaiting_human_reply = False
        self._board_on = False
        self._computer_is_white = None
        self._game_started = False        # new game -> orientation choice allowed again
        # Arm the "New Game" suppression BEFORE sending NEW (see _handshake): the
        # board's "New Game" reply lands during the ack wait, so the counter must
        # already be set or it gets misread as a physical user reset.
        self._pending_new_acks += 1
        self._suppress_newgame_until = self._loop.time() + _NEWGAME_SUPPRESS_WINDOW
        await self._send("NEW", ack_timeout=_ACK_TIMEOUT)
        # No ANALYSIS / BOARD ON here: leave the board in the clean post-NEW
        # state (the only state PLAY flips from) and let set_computer_color arm
        # it per colour on the PLAY_MODE picochess emits next. One NEW per game.
        logger.debug("OsaBoard: new game sent (post-NEW; armed per colour on PLAY_MODE)")

    async def send_move(self, move: chess.Move, board: chess.Board) -> None:
        """
        Inject the engine's move, show it, then re-arm for the next move.

        Sequence:  BOARD OFF · MOVE x · BOARD ON · ANALYSIS
        NORMAL is never sent: it resets the board orientation (it un-flips an
        engine-as-White board), and ANALYSIS alone displays the injected move.
        """
        if not self._connected:
            return
        payload = _uci_to_osa(move, board)
        self._last_sent_sig = _move_signature(payload)
        self._last_sent_payload = payload

        if self._board_on:
            await self._send("BOARD OFF")
            self._board_on = False

        cmd = f"MOVE {payload}"
        logger.info("OsaBoard → move %s  (cmd %r)", move.uci(), cmd)
        await self._send(cmd)

        await self._send("BOARD ON")     # light up the move on the board
        self._board_on = True
        await self._send("ANALYSIS")      # display the move + re-arm reception
        self._awaiting_human_reply = True  # any take-back until the human's
                                            # real reply move is confirmed is a
                                            # manipulation error, not a real undo

        # NO extra BOARD ON here. The per-move tail is exactly
        # MOVE -> BOARD ON -> ANALYSIS  for BOTH colours:
        # the injected move is already displayed (LED + on the physical board)
        # by the BOARD ON above. Adding a BOARD ON after ANALYSIS re-touches the
        # board just after reception of the next move was re-armed and is not
        # part of the protocol.

        self._turn = not board.turn      # opponent is to move now
        self._game_started = True        # orientation is now fixed for this game

        # The OSA board never reports back that the engine's move has been
        # replayed on it (no confirmation — that is normal for this board).
        # picochess would otherwise wait forever for that confirmation and the
        # game would not advance. So we synthesise it here: tell picochess the
        # engine's move has been played on the board. picochess recognises it
        # as the move it was waiting for, commits it, and hands over to the
        # human. (The board's serial echo of the same move is still discarded
        # by the _last_sent_sig check, so picochess receives it only once.)
        await Observable.fire(Event.KEYBOARD_MOVE(move=move))

    def set_turn(self, turn: chess.Color) -> None:
        """Keep the driver's notion of side-to-move in sync (for castling)."""
        self._turn = turn

    async def set_computer_color(self, computer_white: bool) -> None:
        """Set which colour the computer plays, flipping the board when the
        computer is White.

        Engine-as-White requires the board's PLAY mode for that colour. Per the
        Termite reference, the start sequence is
            NEW -> BOARD OFF -> PLAY -> MOVE -> BOARD ON -> ANALYSIS
        (the MOVE/BOARD ON/ANALYSIS tail lives in send_move). PLAY is NOT
        a toggle and there is no direct un-flip; a NEW (new game) restores
        White-in-front / human-White, which is why new_game resets the flag.

        The gate on _game_started is essential: picochess re-emits PLAY_MODE on
        every change of side-to-move (set_wait_state derives play_mode from
        game.turn), e.g. after a take-back. Acting on that mid-game would send a
        spurious BOARD OFF + PLAY and darken the board. So a PLAY_MODE change
        once play has started only updates our flag, never the board.
        """
        if not self._connected:
            return
        if computer_white == self._computer_is_white:
            return                                    # no change
        if self._game_started:
            logger.info("OsaBoard: ignoring mid-game PLAY_MODE (computer_white=%s) "
                        "— orientation is fixed once play has started", computer_white)
            self._computer_is_white = computer_white
            return
        self._computer_is_white = computer_white
        if computer_white:
            # USER_BLACK: computer plays White and moves first -> FLIP the board.
            # The board is in the clean post-NEW state (handshake/new_game sent
            # NEW and nothing since), which is the only state PLAY flips from, so
            # BOARD OFF -> PLAY reproduces the Termite sequence NEW -> BOARD OFF
            # -> PLAY exactly. No NORMAL (it would block the flip) and no re-NEW
            # (board already post-NEW). send_move injects the first White move.
            logger.info("OsaBoard: computer plays White -> BOARD OFF + PLAY (flip)")
            await self._send("BOARD OFF")
            self._board_on = False
            await self._send("PLAY")
        else:
            # USER_WHITE: human plays White and moves first. Arm the board for the
            # human's move: ANALYSIS (silence the internal engine / referee mode)
            # + BOARD ON. No PLAY -> default orientation (White in front).
            logger.info("OsaBoard: computer plays Black -> ANALYSIS + BOARD ON")
            await self._send("ANALYSIS")
            await self._send("BOARD ON")
            self._board_on = True

    # ─────────────────────────────────────────────────────────────────────────
    # EBoard-protocol stubs (no-ops — OSA has no Revelation LEDs / clock display)
    # ─────────────────────────────────────────────────────────────────────────

    def light_squares_on_revelation(self, uci_move: str) -> None: pass
    def light_square_on_revelation(self, square: str) -> None: pass
    def clear_light_on_revelation(self) -> None: pass
    def run(self) -> None: pass
    def set_text_rp(self, text: bytes, beep: int) -> None: pass
    def set_text_xl(self, text: str, beep: int, left_icons=None, right_icons=None) -> None: pass
    def set_text_3k(self, text: bytes, beep: int) -> None: pass
    def set_and_run(self, lr, lh, lm, ls, rr, rh, rm, rs) -> None: pass
    def end_text(self) -> None: pass
    def promotion_done(self, uci_move: str) -> None: pass

    async def disconnect(self) -> None:
        """Cleanly shut down the connection."""
        if self._newgame_arm_task and not self._newgame_arm_task.done():
            self._newgame_arm_task.cancel()
            self._newgame_arm_task = None

        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None

        if self._writer:
            try:
                await self._send("CLOSE", wait_ack=False)
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None

        self._reader = None
        self._connected = False
        logger.info("OsaBoard: disconnected from %s", self._port)

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _arm_after_reset(self) -> None:
        """Re-arm analysis mode after a reset, OFF the read loop.

        Sends ANALYSIS (silence the internal engine) + BOARD ON. Run as a task
        (or awaited from connect, which is not the read loop) so the read loop
        stays free to deliver the 0x17 acks these commands wait on.
        """
        await self._send("ANALYSIS")     # disable internal engine
        await self._send("BOARD ON")     # enable the board
        self._board_on = True

    async def _arm_after_newgame_settle(self) -> None:
        """Trailing-edge ANALYSIS re-arm after a board-initiated New Game burst.

        A physical reset can emit several "New Game" lines while the board is
        still resetting, and ANALYSIS sent during that window is silently
        dropped (the internal engine stays on, board stuck in NORMAL). Each
        "New Game" line in _handle_line reschedules this task, so it fires only
        once the burst has been quiet for _NEWGAME_DEBOUNCE — by then the board
        has settled and accepts ANALYSIS. Cancellation (a further burst line, or
        disconnect) simply aborts this pending re-arm.
        """
        try:
            await asyncio.sleep(_NEWGAME_DEBOUNCE)
        except asyncio.CancelledError:
            return
        if not self._connected:
            return
        await self._arm_after_reset()

    async def _send(self, text: str, wait_ack: bool = True,
                    ack_timeout: float = _CMD_ACK_TIMEOUT) -> None:
        """Write *text* + CRLF to the board and, by default, block until the
        board returns its 0x17 'integrated / ready' byte — the byte the
        reference BASIC driver loops on after every Print #2. We proceed the
        instant the 0x17 arrives (board speed).

        ``ack_timeout`` bounds the wait: the short default for fast in-game
        commands (so a command that never acks does not stall the game), and the
        long ``_ACK_TIMEOUT`` for the slow OPEN / NEW handshake replies. A
        timeout is logged (WARNING) so a never-acking command is visible.

        Pass ``wait_ack=False`` for fire-and-forget writes (e.g. CLOSE on a board
        that may already be going away). The whole write+ack cycle is serialised
        by ``_cmd_lock`` so a second command can never start before the first is
        acked.
        """
        if self._writer is None:
            return
        data = (text + _EOL).encode("ascii")
        async with self._cmd_lock:
            # Clear BEFORE writing so we only catch the ack for THIS command and
            # not a stale 0x17 left set by a previous one / an idle prompt.
            if wait_ack:
                self._ack_event.clear()
            logger.debug("OsaBoard → raw %r", data)
            try:
                self._writer.write(data)
                await self._writer.drain()
            except Exception as exc:
                logger.error("OsaBoard: write error: %s", exc)
                self._connected = False
                return
            if not wait_ack:
                return
            try:
                await asyncio.wait_for(self._ack_event.wait(), timeout=ack_timeout)
                logger.debug("OsaBoard: 0x17 ack for %r", text)
            except asyncio.TimeoutError:
                logger.warning("OsaBoard: no 0x17 ack for %r within %.1f s "
                               "(continuing)", text, ack_timeout)

    async def _read_loop(self) -> None:
        """Read CRLF/CR/LF-terminated lines from the board and dispatch them."""
        assert self._reader is not None
        buf = b""
        # The OSA board terminates its *prompt* and its *human-move* lines with
        # the single byte 0x17 (shown as "[17]" by the original capture tool),
        # NOT with CRLF — while its command replies and the echo of injected
        # moves do use CRLF. So 0x17 must be treated as a line separator too,
        # otherwise human moves stay stuck in the buffer and never reach
        # picochess. The prompt itself is ">" + 0x17; the leading ">" is dropped.
        separators = (b"\r\n", b"\r", b"\n", b"\x17")
        while True:
            try:
                chunk = await self._reader.read(256)
                if not chunk:
                    logger.warning("OsaBoard: device closed the connection")
                    break
                # Raw RX dump: %r shows 0x17 as \x17 and reveals garbled bursts
                # (e.g. the repeated "Takeback" stream) exactly as they arrive.
                # Enable by running picochess with log_level = debug.
                logger.debug("OsaBoard ← raw %r", chunk)
                buf += chunk
                while True:
                    # earliest separator wins; on a tie prefer the longest
                    # (so "\r\n" beats a bare "\r" at the same position)
                    best_idx, best_len = -1, 0
                    for sep in separators:
                        idx = buf.find(sep)
                        if idx < 0:
                            continue
                        if best_idx < 0 or idx < best_idx or \
                           (idx == best_idx and len(sep) > best_len):
                            best_idx, best_len = idx, len(sep)
                    if best_idx < 0:
                        break   # no complete line yet — wait for more data
                    raw = buf[:best_idx]
                    # Remember whether THIS separator was a 0x17 byte before we
                    # consume it from the buffer.
                    sep_was_ack = buf[best_idx:best_idx + best_len] == b"\x17"
                    buf = buf[best_idx + best_len:]
                    line = raw.decode("ascii", errors="ignore")
                    line = line.replace("\x17", "").strip().lstrip(">").strip()
                    if line:
                        await self._handle_line(line)
                    # The board's "command processed / ready" signal is the BARE
                    # prompt ">" + 0x17 (empty content). A 0x17 that TERMINATES a
                    # content line — i.e. the echo of an injected move,
                    # "  2. e2-e4   00:27  \x17" — is the move-report terminator,
                    # NOT a ready signal: the board emits its real ready prompt
                    # ">"+0x17 a moment later (hence the DOUBLE [17] seen after a
                    # MOVE in the Termite capture). Releasing _send on the echo's
                    # 0x17 fires the next command (BOARD ON) ~300 ms before the
                    # board is ready, so the move is registered but never lit.
                    # Only the bare prompt (no content) counts as the ack.
                    if sep_was_ack and not line:
                        self._ack_event.set()
            except asyncio.CancelledError:
                logger.debug("OsaBoard: read loop cancelled")
                break
            except Exception as exc:
                logger.error("OsaBoard: read error: %s", exc)
                break
        self._connected = False

    async def _handle_line(self, line: str) -> None:
        """Route one decoded line to the right handler."""
        logger.debug("OsaBoard ← %r", line)
        lo = line.lower()

        # ── Board identification (reply to OPEN) ─────────────────────────────
        if "saitek osa" in lo or "osa" in lo and "version" in lo:
            self.board_version = line.strip(" -")
            logger.info("OsaBoard: identified as '%s'", self.board_version)
            return

        # ── Command/move rejected by the board ───────────────────────────────
        if line.strip() == "???":
            logger.warning("OsaBoard: board rejected the last command (???)")
            return

        # ── New game from the board ──────────────────────────────────────────
        # The board sends "New Game" both (a) as the reply to a NEW command we
        # sent ourselves (during connect / new_game) and (b) when the user
        # resets the pieces to the start position / presses NEW GAME. Case (a)
        # must be swallowed (otherwise a spurious Event.NEW_GAME sets picochess's
        # newgame_happened flag). Case (b) MUST be forwarded so picochess starts
        # a new game.
        #
        # We only swallow a "New Game" if it is one we provoked AND it arrives
        # within the suppression window after our NEW (the board replies within
        # ~2-3 s). Anything else is a genuine user reset -> forwarded. The
        # counter is reset on every genuine reset so it can never drift and
        # start eating real New Games.
        if lo == "new game" or lo.startswith("new game"):
            now = self._loop.time()
            if self._pending_new_acks > 0 and now < self._suppress_newgame_until:
                self._pending_new_acks -= 1
                logger.debug("OsaBoard: swallowed expected 'New Game' ack "
                             "(%d still pending)", self._pending_new_acks)
                return
            # A single physical reset can emit several "New Game" lines (a burst,
            # like the garbled "Takeback" stream). The two things we must do
            # happen on the two EDGES of that burst:
            #
            #  * LEADING edge  -> tell picochess ONCE. picochess aborts + starts a
            #    fresh game on every Event.NEW_GAME, so firing per line makes it
            #    announce "abort"/"new game" repeatedly.
            #  * TRAILING edge -> re-arm ANALYSIS. DURING the burst the board is
            #    still resetting, and ANALYSIS sent mid-reset is silently dropped
            #    (the internal engine stays on -> board stuck in NORMAL). So we
            #    arm only once the burst has been quiet for _NEWGAME_DEBOUNCE,
            #    i.e. the board has settled and will accept ANALYSIS.
            #
            # Every "New Game" line (re)schedules the trailing-edge task, so it
            # always fires after the LAST line of the burst, never mid-reset.
            is_repeat = (now - self._last_newgame_time) < _NEWGAME_DEBOUNCE
            self._last_newgame_time = now
            if self._newgame_arm_task and not self._newgame_arm_task.done():
                self._newgame_arm_task.cancel()
            self._newgame_arm_task = self._loop.create_task(
                self._arm_after_newgame_settle())

            if is_repeat:
                logger.debug("OsaBoard: swallowed repeated New Game %r "
                             "(re-arm rescheduled)", line)
                return

            # leading edge -> genuine user reset -> tell picochess, clear counter
            self._pending_new_acks = 0
            logger.info("OsaBoard: New Game from board (user reset) -> picochess")
            self._turn = chess.WHITE
            self._board_on = False
            self._last_sent_sig = None
            self._awaiting_human_reply = False
            self._computer_is_white = None
            self._game_started = False    # new game -> orientation choice allowed again
            await Observable.fire(Event.NEW_GAME(pos960=518))
            # ANALYSIS re-arm is handled on the TRAILING edge by
            # _arm_after_newgame_settle (scheduled above), once the board has
            # finished resetting. After its reset the OSA board sits in its native
            # NORMAL mode (internal engine active) and nothing else switches it to
            # ANALYSIS — picochess does not re-emit PLAY_MODE for a board NEW_GAME.
            # _computer_is_white is left None, so if the user then picks Black via
            # picochess, the PLAY_MODE(True) that follows still passes
            # set_computer_color's guard and performs the BOARD OFF + PLAY flip.
            return

        # ── Take-back on the board ───────────────────────────────────────────
        # Sent when the user plays a move backwards on the board (undo). The
        # board reports ONE physical undo as a burst of "Takeback" lines, often
        # garbled (e.g. "TTTTTakeback"). picochess pops one ply per event, so we
        # must forward exactly ONE event per physical undo: fire on the first
        # line of a burst, swallow the rest within _TAKEBACK_DEBOUNCE. The window
        # is extended on every swallowed repeat so a long garbled stream stays
        # collapsed to a single take-back.
        if "takeback" in lo:
            now = self._loop.time()
            if now - self._last_takeback_time < _TAKEBACK_DEBOUNCE:
                self._last_takeback_time = now      # keep collapsing the burst
                logger.debug("OsaBoard: swallowed repeated take-back %r", line)
                return
            self._last_takeback_time = now

            # ── Manipulation-error case: reversed-order pickup ──────────────
            # A take-back seen while we're still waiting for the human's real
            # reply to our own MOVE/BOARD ON/ANALYSIS cannot be a genuine undo
            # (no new ply has been confirmed yet to undo) -- it can only be a
            # reversed-order pickup on that pending move (capturing piece
            # lifted after, not before, the captured one). Do NOT forward
            # Event.TAKE_BACK; re-send the move sequence instead, so the
            # firmware is put back on our move rather than left believing an
            # undo is under way. This is the ONLY case that resends anything.
            if self._awaiting_human_reply:
                logger.info(
                    "OsaBoard: take-back %r right after our own MOVE/BOARD ON/"
                    "ANALYSIS -> manipulation error, re-sending %s",
                    line, self._last_sent_payload)
                self._loop.create_task(
                    self._resend_move_sequence(self._last_sent_payload))
                return

            # ── Genuine take-back ────────────────────────────────────────────
            logger.info("OsaBoard: take-back received: %r", line)
            # Just forward it. Do NOT send anything to the board here: the OSA
            # board displays and chains take-backs on its own, and any command
            # sent now (BOARD ON / ANALYSIS) interrupts that native LED
            # sequence. The board is no longer left dark either — the spurious
            # PLAY_MODE flip that used to send BOARD OFF + PLAY is suppressed
            # mid-game (see set_computer_color), so there is nothing to re-arm.
            await Observable.fire(Event.TAKE_BACK(take_back="TAKEBACK"))
            return

        # ── Game result line ─────────────────────────────────────────────────
        if _RESULT_RE.match(line):
            # picochess derives the result from the position itself (the mating
            # move is delivered as a normal KEYBOARD_MOVE), so we only log it.
            logger.info("OsaBoard: game result reported: %s", line.strip())
            return

        # ── A move line ──────────────────────────────────────────────────────
        if _LOOKS_LIKE_MOVE.search(line):
            await self._handle_move_line(line)
            return

        logger.debug("OsaBoard: ignored: %r", line)

    async def _handle_move_line(self, line: str) -> None:
        """Suppress our own echoed move; forward real human moves to picochess."""
        sig = _move_signature(line)

        # ── Echo suppression ─────────────────────────────────────────────────
        if self._last_sent_sig and sig and sig == self._last_sent_sig:
            logger.debug("OsaBoard: suppressed echo of %r", line)
            self._last_sent_sig = None
            return

        move = _osa_to_move(line, self._turn)
        if move is None:
            logger.warning("OsaBoard: cannot parse move line %r", line)
            return

        logger.info("OsaBoard: human move %s", move.uci())
        self._turn = not self._turn
        self._game_started = True        # orientation is now fixed for this game
        self._awaiting_human_reply = False  # real reply confirmed; a take-back
                                             # from here on is genuine again
        await Observable.fire(Event.KEYBOARD_MOVE(move=move))

    async def _resend_move_sequence(self, payload: str) -> None:
        """Manipulation-error recovery (see the take-back handler above): a
        take-back arriving while we're still awaiting the human's reply to our
        own last move can only be a reversed-order pickup, not a real undo.
        Re-send the move sequence immediately -- BOARD OFF / MOVE / BOARD ON /
        ANALYSIS, the same tail as a normal send_move -- so the firmware is put
        back on displaying/tracking OUR move rather than left believing an
        undo is under way. Runs as its own task (called from within the read
        loop's call chain, which must stay free to deliver acks for these
        very sends). picochess's move stack is never touched here.

        IMPORTANT: the board replies to MOVE almost immediately (tens of ms) —
        this is the board's own protocol echo of the command, NOT a report of
        the human's physical completion. _last_sent_sig is what makes that
        echo recognised and swallowed; if it was already consumed by an
        earlier echo (the normal case, since it always arrives fast) it will
        be None by the time we get here, so we must re-arm it before
        re-sending or this second echo is mistaken for a genuine human move
        (and forwarded to picochess as one -- observed: rejected as illegal,
        and _awaiting_human_reply wrongly cleared, leaving the NEXT real
        take-back unguarded).

        DISPROVEN HYPOTHESIS (do not re-add without new evidence): re-sending
        PLAY here, on the theory that a flipped board needs it re-asserted for
        the firmware's native LED guidance to resume, was tried and made
        things WORSE -- the board rejected the following MOVE outright ('???'
        response), and BOARD OFF itself failed to ack within the normal
        window right beforehand. This matches set_computer_color's own
        warning that PLAY only flips from the clean post-NEW state; sending
        it again mid-game does not re-arm anything, it confuses the board.

        CURRENT FIX: wait _RESEND_SETTLE_DELAY before sending anything. Two
        separate captures show BOARD OFF getting no ack within 1.2s right
        after the take-back burst, and the command immediately following it
        (PLAY, then plain MOVE on retest) being rejected with '???' -- i.e.
        the board was still busy digesting the burst. The move-tracking side
        recovers regardless (the real completion echo is still recognised
        later), but the '???' appears to leave the firmware's native LED
        guidance dark for the rest of that move. Giving the board a moment to
        settle before touching it again is the current, untested-on-bench
        attempt at fixing that.

        Note: _last_sent_sig is re-armed BEFORE the sleep, not after -- if the
        board recovers on its own during the wait and sends the completion
        line, it must still be recognised as our echo, not as a fresh (and
        by now stale) human move.
        """
        self._last_sent_sig = _move_signature(payload)
        await asyncio.sleep(_RESEND_SETTLE_DELAY)
        try:
            await self._send("BOARD OFF")
            self._board_on = False
            await self._send(f"MOVE {payload}")
            await self._send("BOARD ON")
            self._board_on = True
            await self._send("ANALYSIS")
        except asyncio.CancelledError:
            raise
