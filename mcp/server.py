"""Minimal MCP server for a PicoChess instance running on this machine.

It talks to the PicoChess web server through the same HTTP endpoints the
browser client uses, so PicoChess itself needs no changes.

Run with the virtual environment in this folder:
    mcp/.venv/Scripts/python.exe mcp/server.py      (Windows)
    mcp/.venv/bin/python mcp/server.py              (Linux, macOS)

Set PICOCHESS_URL to reach PicoChess somewhere other than http://localhost:8080.
"""

import asyncio
import csv
import io
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Literal

import chess
import chess.pgn
import websockets
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from websockets.asyncio.client import connect as websocket_connect

PICOCHESS_URL = os.environ.get("PICOCHESS_URL", "http://localhost:8080").rstrip("/")
REQUEST_TIMEOUT_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.5
# PicoChess shows an accepted web move within moments; no sign of it means it was ignored.
MOVE_ACCEPT_TIMEOUT_SECONDS = 10.0
ENGINE_REPLY_TIMEOUT_SECONDS = 120.0
# After the connect snapshot, how long to wait for analysis of the current position.
ANALYSIS_WAIT_SECONDS = 3.0
# Half-moves of the expected continuation shown with a hint.
HINT_LINE_PLIES = 8
# A new position can take a while with MAME engines, which are set up eagerly.
SETUP_TIMEOUT_SECONDS = 30.0
# How long to wait for PicoChess to save or restore the analysis-mode checkpoint before
# reporting; with an e-board, the restore then waits for the user to set up the pieces.
CHECKPOINT_WAIT_SECONDS = 5.0
# After a restarted engine reports ready, PicoChess publishes its playing Elo within about a second.
ENGINE_SETTLE_SECONDS = 1.5

_MOVE_NUMBER = re.compile(r"^\d+\s*\.+\s*")
_PGN_RESULT = re.compile(r'^\[Result "([^"]*)"\]', re.MULTILINE)

# On a stdio MCP server stdout carries the protocol, so log to stderr only.
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("picochess-mcp")

server = MCPServer(
    name="picochess",
    instructions="Tools for the PicoChess chess computer running on this machine.",
)


def _request_json(path: str, params: dict[str, str], post: bool = False) -> dict:
    """Call a PicoChess endpoint like the browser does and return its JSON body ({} when empty).

    GET sends the parameters in the query string; POST sends them form-encoded.
    """
    query = urllib.parse.urlencode(params)
    if post:
        request = urllib.request.Request(f"{PICOCHESS_URL}{path}", data=query.encode("ascii"), method="POST")
    else:
        request = urllib.request.Request(f"{PICOCHESS_URL}{path}?{query}")
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
    # ToolError reaches the model with its message; other exceptions are reported as crashes.
    except urllib.error.HTTPError as exc:
        # PicoChess explains rejections in a JSON "error" field, e.g. why a FEN is invalid.
        reason = ""
        try:
            reason = json.loads(exc.read().decode("utf-8")).get("error", "")
        except (ValueError, AttributeError, OSError):
            pass
        detail = f": {reason}" if reason else f" (HTTP {exc.code})"
        raise ToolError(f"PicoChess rejected the request to {path}{detail}.") from exc
    except OSError as exc:
        raise ToolError(
            f"PicoChess is not reachable at {PICOCHESS_URL}. Start PicoChess and try again. ({exc})"
        ) from exc
    return json.loads(body) if body.strip() else {}


async def _system_info() -> dict:
    """Return PicoChess's system information, as shown by the web client."""
    return await asyncio.to_thread(_request_json, "/info", {"action": "get_system_info"})


async def _last_move_message() -> dict:
    """Return PicoChess's latest position message ({} before the first move of a session)."""
    return await asyncio.to_thread(_request_json, "/dgt", {"action": "get_last_move"})


async def _post_channel_action(params: dict[str, str]) -> None:
    """Send a /channel action, as the web client's buttons and board do."""
    await asyncio.to_thread(_request_json, "/channel", params, True)


async def _wait_until(fetch, accepts, what: str, timeout: float | None = None) -> dict:
    """Poll fetch() until accepts(result) holds, or fail.

    what completes the sentence "PicoChess did not ...". timeout defaults to
    MOVE_ACCEPT_TIMEOUT_SECONDS.
    """
    if timeout is None:
        timeout = MOVE_ACCEPT_TIMEOUT_SECONDS
    loop = asyncio.get_running_loop()
    started = loop.time()
    while True:
        result = await fetch()
        if accepts(result):
            return result
        if loop.time() - started > timeout:
            raise ToolError(f"PicoChess did not {what} within {timeout:.0f} seconds.")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def _wait_for_message(accepts, what: str, timeout: float | None = None) -> dict:
    """Poll the latest position message until accepts(message) holds, or fail."""
    return await _wait_until(_last_move_message, accepts, what, timeout)


async def _current_settings() -> dict:
    """Return the current settings the web menus show: engine and level, PicoTutor and more."""
    return await asyncio.to_thread(_request_json, "/info", {"action": "get_current_settings"})


async def _clock_state() -> dict:
    """Return {"running": bool} for the game clock, as the web client reads it."""
    return await asyncio.to_thread(_request_json, "/info", {"action": "get_clock_state"})


def _game_result(message: dict) -> str:
    """Return the PGN Result tag of a position message; "*" while the game is still open."""
    match = _PGN_RESULT.search(message.get("pgn") or "")
    return match.group(1) if match else "*"


def _same_position(fen_a: str | None, fen_b: str | None) -> bool:
    """Compare placement, side to move and castling; PicoChess FEN variants differ in en passant."""
    return bool(fen_a and fen_b) and fen_a.split(" ")[:3] == fen_b.split(" ")[:3]


async def _websocket_snapshot(analysis_fen: str | None = None) -> list[dict]:
    """Read the messages PicoChess sends a newly connected web client.

    PicoChess replays the latest position, analysis and system information to every
    new client, ending with SystemInfo. With analysis_fen, keep listening briefly if
    the replay holds no analysis of that position, as after a fresh move.
    """
    url = PICOCHESS_URL.replace("http", "ws", 1) + "/event"
    messages: list[dict] = []
    loop = asyncio.get_running_loop()
    try:
        async with websocket_connect(url, open_timeout=REQUEST_TIMEOUT_SECONDS) as websocket:
            while not any(m.get("event") == "SystemInfo" for m in messages):
                try:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=REQUEST_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    break
                messages.append(json.loads(raw))
            deadline = loop.time() + ANALYSIS_WAIT_SECONDS
            while analysis_fen and _analysis_for(messages, analysis_fen) is None:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                messages.append(json.loads(raw))
    except (OSError, websockets.exceptions.WebSocketException) as exc:
        raise ToolError(f"PicoChess is not reachable at {PICOCHESS_URL}. Start PicoChess and try again. ({exc})") from exc
    return messages


def _analysis_for(messages: list[dict], fen: str) -> dict | None:
    """Return the deepest Analysis payload computed for this position, if any."""
    matching = [
        m["analysis"]
        for m in messages
        if m.get("event") == "Analysis" and m.get("analysis") and _same_position(m["analysis"].get("fen"), fen)
    ]
    return max(matching, key=lambda a: a.get("depth") or 0) if matching else None


async def _current_analysis() -> tuple[chess.Board, dict, dict]:
    """Return the current board, system info, and the analysis of exactly this position."""
    info = await _system_info()
    message = await _last_move_message()
    variant = message.get("variant", "chess")
    if variant != "chess":
        raise ToolError(f"Only standard chess is supported by this tool; PicoChess is playing {variant}.")
    board = _game_from_message(message).end().board()
    analysis = _analysis_for(await _websocket_snapshot(board.fen()), board.fen())
    if analysis is None:
        raise ToolError(
            "PicoChess has no analysis of the current position yet. Its engine or Tutor analyses on "
            "the user's turn once the game has started; try again in a moment."
        )
    return board, info, analysis


def _line_san(fen: str, pv: list[str]) -> str:
    """Number a SAN principal variation from its position, e.g. "8. O-O Nf6 9. Qb3"."""
    board = chess.Board(fen)
    moves = []
    try:
        for san in pv:
            moves.append(board.parse_san(san))
            board.push(moves[-1])
    except ValueError:
        pass
    if not moves:
        return " ".join(pv)
    return chess.Board(fen).variation_san(moves)


def _assessment(centipawns: int | None, mate: int | None) -> str:
    """Describe a score from White's point of view in words."""
    if mate:
        return f"{'White' if mate > 0 else 'Black'} mates in {abs(mate)}"
    if centipawns is None:
        return "unknown"
    pawns = centipawns / 100
    if abs(pawns) < 0.3:
        return "roughly equal"
    return f"{'White' if pawns > 0 else 'Black'} is better by about {abs(pawns):.1f} pawns"


_USER_COLORS = {"user_white": chess.WHITE, "user_black": chess.BLACK}
_PLAYING_MODES = ("normal", "brain", "training")
# Menu names for interaction modes whose internal names differ.
_MODE_LABELS = {"ponder": "analysis", "analysis": "move hint", "kibitz": "eval score"}
# set_mode values: Mode.PONDER is the menu's "Analysis"; PicoChess's "analysis" is "Move Hint".
_SET_MODE_VALUES = {"play": "normal", "analysis": "ponder"}
# system_info time_control modes without a running game clock.
_NO_GAME_CLOCK_MODES = ("fixed", "depth", "nodes")
# Coach modes that respond to lifting pieces on an e-board.
_LIFT_COACH_VALUES = ("lift", "hand")


def _tutor_summary(settings: dict, info: dict) -> dict[str, str | bool]:
    """Describe the PicoTutor settings and when they have an effect."""
    watcher = bool(settings.get("tutor_watcher"))
    coach = str(settings.get("tutor_coach", "off"))
    explorer = bool(settings.get("tutor_explorer"))
    notes = []
    if info.get("interaction_mode") == "ponder":
        notes.append("PicoTutor is inactive in analysis mode; Watcher and Coach apply again in play mode")
    if coach in _LIFT_COACH_VALUES and not info.get("has_board"):
        notes.append(f"Coach {coach} responds to lifting pieces, which needs an e-board")
    result: dict[str, str | bool] = {"watcher": watcher, "coach": coach, "explorer": explorer}
    if notes:
        result["note"] = "; ".join(notes)
    return result


def _mode_label(mode: str | None) -> str:
    return _MODE_LABELS.get(mode or "", mode or "unknown")


def _game_from_message(message: dict) -> chess.pgn.Game:
    """Rebuild the game, with its move history, from a position message."""
    pgn = message.get("pgn")
    game = chess.pgn.read_game(io.StringIO(pgn)) if pgn else None
    if game is None:
        game = chess.pgn.Game()
        if message.get("fen"):
            game.setup(chess.Board(message["fen"]))
    return game


def _move_label(board: chess.Board, move: chess.Move) -> str:
    """Return a move with its number, like "12. Nf3" or "12... Nf6", for the position before it."""
    dots = "." if board.turn == chess.WHITE else "..."
    return f"{board.fullmove_number}{dots} {board.san(move)}"


def _played_moves(game: chess.pgn.Game) -> list[tuple[chess.Board, chess.Move]]:
    """Return each mainline move with the position before it."""
    played = []
    board = game.board()
    for move in game.mainline_moves():
        played.append((board.copy(stack=False), move))
        board.push(move)
    return played


def _tutor_marks(message: dict, played: list[tuple[chess.Board, chess.Move]]) -> dict[int, dict]:
    """Return PicoTutor's ratings of moves in this game, by their index in played.

    PicoTutor keeps the moves it marked or found inaccurate (its web WATCHER
    list), keyed by the half-move count after the move. Its list can outlive a
    takeback, so a rating counts only when the game's move at that point is the
    rated move.
    """
    by_ply = {before.ply() + 1: (index, before.san(move)) for index, (before, move) in enumerate(played)}
    marks = {}
    for mistake in message.get("mistakes") or []:
        index, san = by_ply.get(mistake.get("halfmove"), (None, None))
        if index is None or san != mistake.get("user_move"):
            continue
        mark = {"rating": mistake.get("nag") or "inaccurate", "best_move": mistake.get("best_move")}
        if mistake.get("centipawn_loss") is not None:
            mark["centipawn_loss"] = mistake["centipawn_loss"]
        marks[index] = mark
    return marks


_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_openings: tuple[dict[str, tuple[str, str]], dict[str, str]] | None = None


def _opening_books() -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """Load the opening names PicoTutor's Explorer uses, once.

    Returns names by SAN move sequence from the standard start position, as
    (ECO code, name), and names by board FEN, which also recognise
    transpositions.
    """
    global _openings
    if _openings is None:
        by_moves: dict[str, tuple[str, str]] = {}
        by_fen: dict[str, str] = {}
        try:
            with open(os.path.join(_REPO_DIR, "chess-eco_pos.txt"), encoding="utf-8", errors="replace") as file:
                rows = csv.DictReader((line for line in file if not line.startswith("#")), delimiter="|")
                for row in rows:
                    if row.get("moves"):
                        by_moves[row["moves"]] = (row.get("eco") or "", row.get("opening_name") or "")
        except OSError as exc:
            logger.warning("opening names by moves unavailable: %s", exc)
        try:
            with open(os.path.join(_REPO_DIR, "opening_name_fen.txt"), encoding="utf-8", errors="replace") as file:
                lines = file.read().splitlines()
            # The file alternates a FEN line and the opening name.
            for fen_line, name in zip(lines[0::2], lines[1::2]):
                if fen_line.split() and name.strip():
                    by_fen[fen_line.split()[0]] = name.strip()
        except OSError as exc:
            logger.warning("opening names by position unavailable: %s", exc)
        _openings = (by_moves, by_fen)
    return _openings


def _opening(game: chess.pgn.Game, played: list[tuple[chess.Board, chess.Move]]) -> str | None:
    """Name the opening of the latest named position in the game, as PicoTutor's Explorer does."""
    by_moves, by_fen = _opening_books()
    from_start = game.board().fen() == chess.STARTING_FEN
    sans = [before.san(move) for before, move in played]
    for count in range(len(played), 0, -1):
        if from_start and " ".join(sans[:count]) in by_moves:
            eco, name = by_moves[" ".join(sans[:count])]
            return f"{eco} {name}".strip()
        before, move = played[count - 1]
        after = before.copy(stack=False)
        after.push(move)
        if after.board_fen() in by_fen:
            return by_fen[after.board_fen()]
    return None


def _color_name(color: chess.Color) -> str:
    return "white" if color == chess.WHITE else "black"


def _game_status(board: chess.Board, result: str, info: dict) -> str:
    """Describe whose turn it is in words the user can act on."""
    mode = info.get("interaction_mode")
    user_color = _USER_COLORS.get(info.get("play_mode"))
    if result != "*":
        return f"game over ({result})"
    if mode not in _PLAYING_MODES or user_color is None:
        return f"{_mode_label(mode)} mode, {_color_name(board.turn)} to move"
    if not board.move_stack:
        return "new game: waiting for the first move"
    if info.get("pending_engine_move"):
        return "the engine has chosen its move: make it on the e-board"
    if board.turn != user_color:
        return "the engine is thinking"
    return "your move"


def _parse_move(board: chess.Board, text: str) -> chess.Move:
    """Read a move such as "1. e4", "e2-e4", "e2e4", "Nf3", "O-O" or "e8=Q"."""
    cleaned = _MOVE_NUMBER.sub("", text.strip())
    if not cleaned:
        raise ToolError("No move was given. Use a move such as e4, Nf3 or e2-e4.")
    try:
        # python-chess SAN parsing also accepts long forms such as e2-e4 and e2e4.
        return board.parse_san(cleaned)
    except chess.AmbiguousMoveError as exc:
        raise ToolError(f"{text} is ambiguous here. Name the piece's starting square, for example Nbd2.") from exc
    except chess.IllegalMoveError as exc:
        raise ToolError(f"{text} is not a legal move in the current position ({board.fen()}).") from exc
    except ValueError:
        pass
    try:
        move = chess.Move.from_uci(re.sub(r"[-x:+#=\s]", "", cleaned).lower())
    except ValueError as exc:
        raise ToolError(f"Could not read the move {text!r}. Use a move such as e4, Nf3 or e2-e4.") from exc
    if move not in board.legal_moves:
        raise ToolError(f"{text} is not a legal move in the current position ({board.fen()}).")
    return move


def _shows_position(message: dict, board: chess.Board) -> bool:
    """Return whether a PicoChess message reports the position on this board."""
    return message.get("fen", "").split(" ")[0] == board.board_fen()


def _engine_reply(board: chess.Board, message: dict) -> chess.Move | None:
    """Return the engine's reply to the position on board, if message reports one.

    Until PicoChess handles the new move, get_last_move still returns the previous
    engine reply, so the reply must be legal here and produce the reported position.
    """
    if message.get("play") != "computer":
        return None
    try:
        move = chess.Move.from_uci(message.get("move", ""))
    except ValueError:
        return None
    if move not in board.legal_moves:
        return None
    after = board.copy(stack=False)
    after.push(move)
    return move if _shows_position(message, after) else None


def _game_over_status(board: chess.Board) -> str | None:
    outcome = board.outcome()
    if outcome is None:
        return None
    return f"game over: {outcome.result()} ({outcome.termination.name.lower().replace('_', ' ')})"


async def _wait_for_engine_reply(board: chess.Board, user_san: str) -> dict[str, str | None]:
    """Poll PicoChess after posting a user move until the engine has answered it."""
    loop = asyncio.get_running_loop()
    started = loop.time()
    accepted = False
    while True:
        message = await _last_move_message()
        reply = _engine_reply(board, message)
        if reply is not None:
            after = board.copy(stack=False)
            after.push(reply)
            return {
                "your_move": user_san,
                "engine_move": board.san(reply),
                "status": _game_over_status(after) or "engine replied",
                "fen": message.get("fen"),
                "pgn": message.get("pgn"),
            }
        if _shows_position(message, board):
            accepted = True
            game_over = _game_over_status(board)
            if game_over:
                return {
                    "your_move": user_san,
                    "engine_move": None,
                    "status": game_over,
                    "fen": message.get("fen"),
                    "pgn": message.get("pgn"),
                }
        elapsed = loop.time() - started
        if not accepted and elapsed > MOVE_ACCEPT_TIMEOUT_SECONDS:
            raise ToolError(
                "PicoChess did not accept the move. Web moves are accepted only when PicoChess runs "
                "without an e-board (board-type = noeboard) and it is the user's turn."
            )
        if elapsed > ENGINE_REPLY_TIMEOUT_SECONDS:
            return {
                "your_move": user_san,
                "engine_move": None,
                "status": "engine still thinking",
                "fen": message.get("fen"),
                "pgn": message.get("pgn"),
            }
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


@server.tool(annotations=ToolAnnotations(title="Get engine", read_only_hint=True, open_world_hint=False))
async def get_engine() -> dict[str, str | int]:
    """Return the chess engine PicoChess is currently using, and its level.

    Use this when the user asks which engine is loaded or selected, or how
    strong it plays. The result has engine_name and, when PicoChess has
    reported them, engine_elo and engine_level, such as "Elo@2200". Without a
    level the engine plays at its full strength.
    """
    info, settings = await asyncio.gather(_system_info(), _current_settings())
    engine_name = info.get("engine_name")
    if not engine_name:
        raise ToolError("PicoChess is running but has not reported an engine yet. It may still be starting up.")
    result: dict[str, str | int] = {"engine_name": engine_name}
    if info.get("engine_elo"):
        result["engine_elo"] = info["engine_elo"]
    if settings.get("engine_level"):
        result["engine_level"] = settings["engine_level"]
    return result


async def _engine_catalog() -> list[dict]:
    """Return the installed engines once each, in PicoChess's menu order, with their menu category."""
    payload = await asyncio.to_thread(_request_json, "/info", {"action": "get_engines"})
    engines: dict[str, dict] = {}
    for engine in payload.get("engines") or []:
        # The Special (favorites) list repeats engines from the other lists.
        engines.setdefault(engine.get("file", ""), engine)
    return list(engines.values())


def _find_engine(engines: list[dict], name: str) -> dict:
    """Find an engine by its name, exactly or by a unique part of it, ignoring case."""
    wanted = name.strip().casefold()
    exact = [engine for engine in engines if engine.get("name", "").casefold() == wanted]
    matches = exact or [engine for engine in engines if wanted in engine.get("name", "").casefold()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ToolError(f"No installed engine is called {name!r}. Use list_engines to see the installed engines.")
    names = ", ".join(sorted({engine.get("name", "") for engine in matches}))
    raise ToolError(f"{name!r} matches several engines: {names}. Give the full name.")


def _find_level(engine: dict, level: str) -> str:
    """Find an engine level by its name, or by its number, as in "1800" for "Elo@1800"."""
    levels = engine.get("levels") or []
    wanted = level.strip().casefold()
    for name in levels:
        if name.casefold() == wanted or name.casefold().split("@")[-1] == wanted:
            return name
    if not levels:
        raise ToolError(f"{engine.get('name')} has no levels; it always plays at its own strength.")
    raise ToolError(f"{engine.get('name')} has no level {level!r}. Its levels are: {', '.join(levels)}.")


@server.tool(annotations=ToolAnnotations(title="List engines", read_only_hint=True, open_world_hint=False))
async def list_engines() -> dict[str, Any]:
    """List the chess engines installed in PicoChess, with their levels.

    Use this when the user asks which engines or strengths are available. Each
    engine has its name, its Elo at full strength when known, its menu category
    ("modern", or "retro" for emulated chess computers) and its levels, such
    as "Elo@1800". Engines without levels play at their own fixed strength.
    """
    engines = await _engine_catalog()
    return {
        "engines": [
            {
                "name": engine.get("name"),
                "elo": engine.get("elo") or None,
                "category": engine.get("category"),
                "levels": engine.get("levels") or [],
            }
            for engine in engines
        ]
    }


@server.tool(
    annotations=ToolAnnotations(
        title="Change engine or level",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
async def set_engine(engine: str | None = None, level: str | None = None) -> dict[str, str | int]:
    """Change PicoChess's engine, its playing strength, or both, like the web client's Engine menu.

    engine is an engine name from list_engines, or a unique part of it; leave
    it out to change only the level of the current engine. level is a level
    name such as "Elo@1800", or just its number, "1800"; leave it out to use
    the engine's default strength. A game in progress continues with the new
    engine, except that a retro engine (an emulated chess computer) starts a
    new game: ask the user first when a game is in progress. If the engine is
    thinking, it stops and thinks again with the new settings.
    """
    if engine is None and level is None:
        raise ToolError("Give an engine, a level, or both.")
    engines = await _engine_catalog()
    settings = await _current_settings()
    if engine is None:
        target = next((e for e in engines if e.get("file") == settings.get("engine_file")), None)
        if target is None:
            raise ToolError("PicoChess has not reported its current engine. Name the engine to use.")
    else:
        target = _find_engine(engines, engine)
    level_name = _find_level(target, level) if level is not None else ""

    await _post_channel_action({"action": "new_engine", "file": target["file"], "level": level_name})

    # PicoChess restarts the engine even for a new level, and reports the selection before the
    # engine is ready. When it is, system information briefly shows the engine's catalog Elo,
    # and then, for an Elo level, the level's Elo.
    expected_elo = level_name.split("@")[-1] if level_name.casefold().startswith("elo@") else None
    loop = asyncio.get_running_loop()
    ready_since: float | None = None

    async def fetch() -> tuple[dict, dict]:
        current, info = await asyncio.gather(_current_settings(), _system_info())
        return current, info

    def ready(state: tuple[dict, dict]) -> bool:
        nonlocal ready_since
        current, info = state
        if current.get("engine_file") != target["file"] or (current.get("engine_level") or "") != level_name:
            return False
        if info.get("engine_name") in (None, "", "NN"):
            return False
        if ready_since is None and str(info.get("engine_elo")) == str(target.get("elo")):
            ready_since = loop.time()
        if expected_elo is not None:
            return str(info.get("engine_elo")) == expected_elo
        return ready_since is not None and loop.time() - ready_since >= ENGINE_SETTLE_SECONDS

    # Starting an engine can take a while, and an emulated chess computer longer still.
    try:
        await _wait_until(fetch, ready, "change the engine", SETUP_TIMEOUT_SECONDS)
    except ToolError as exc:
        raise ToolError(
            f"PicoChess did not switch to {target.get('name')} {level_name} within "
            f"{SETUP_TIMEOUT_SECONDS:.0f} seconds. The engine may have failed to start; PicoChess then keeps "
            "the previous engine. Check with get_engine."
        ) from exc
    return await get_engine()


@server.tool(annotations=ToolAnnotations(title="Get the game", read_only_hint=True, open_world_hint=False))
async def get_game() -> dict[str, Any]:
    """Return the current game: the position, the moves so far, whose turn it is, and the Tutor's feedback.

    Use this when the user asks about the position, the move list so far, the
    latest move, what the engine played, whether it is their move, how good
    their moves were, or which opening this is. moves holds every move of the
    game in SAN; last_move is the latest. time_control is, for example, "5+3".
    Works with and without an e-board.
    status says what happens next. board is a text diagram with White at the
    bottom; uppercase letters are White pieces and dots are empty squares.
    With an e-board, PicoChess reveals which move the engine chose only after it
    has been made on the board; until then status says the move is pending.

    opening names the latest position found in PicoTutor Explorer's opening
    lists. tutor_ratings lists the moves PicoTutor's Watcher marked (!!, !,
    !?, ?!, ?, ??) or found inaccurate, with the better move; moves it found
    fine are not listed. tutor_last_rating is its verdict on the user's latest
    move, or the latest move outside play mode: "no remark" means the Watcher
    rated it without objection or has not rated it yet.
    """
    info, message, settings = await asyncio.gather(_system_info(), _last_move_message(), _current_settings())
    variant = message.get("variant", "chess")
    if variant != "chess":
        return {
            "status": f"PicoChess is playing {variant}; this tool describes standard chess only",
            "variant": variant,
            "fen": message.get("fen"),
            "pgn": message.get("pgn"),
        }

    game = _game_from_message(message)
    moves = list(game.mainline_moves())
    board = game.end().board()
    result = _game_result(message)
    # Outside the playing modes there is no user-versus-engine side to name.
    user_color = None
    if info.get("interaction_mode") in _PLAYING_MODES:
        user_color = _USER_COLORS.get(info.get("play_mode"))

    last_move = None
    last_move_by = None
    if moves:
        before = board.copy()
        before.pop()
        last_move = before.san(moves[-1])
        mover = before.turn
        if user_color is None:
            last_move_by = _color_name(mover)
        else:
            last_move_by = "you" if mover == user_color else "the engine"

    played = _played_moves(game)
    marks = _tutor_marks(message, played)
    tutor_ratings = []
    for index, mark in sorted(marks.items()):
        before, move = played[index]
        notes = []
        if mark.get("best_move") and mark["best_move"] != before.san(move):
            notes.append(f"best was {mark['best_move']}")
        if mark.get("centipawn_loss"):
            notes.append(f"{mark['centipawn_loss']} centipawns lost")
        detail = f" ({', '.join(notes)})" if notes else ""
        tutor_ratings.append(f"{_move_label(before, move)} {mark['rating']}{detail}")

    # The Tutor's verdict on the move the user most likely asks about: their own latest
    # move when playing the engine, otherwise the latest move.
    tutor_last_rating = None
    rated = [i for i, (before, _) in enumerate(played) if user_color is None or before.turn == user_color]
    tutor_active = settings.get("tutor_watcher") and info.get("interaction_mode") != "ponder"
    if rated and (rated[-1] in marks or tutor_active):
        before, move = played[rated[-1]]
        mark = marks.get(rated[-1])
        tutor_last_rating = {"move": _move_label(before, move), "rating": "no remark"}
        if mark:
            tutor_last_rating.update(mark)

    return {
        "status": _game_status(board, result, info),
        "opening": _opening(game, played),
        "tutor_last_rating": tutor_last_rating,
        "tutor_ratings": tutor_ratings,
        "to_move": _color_name(board.turn),
        "your_color": _color_name(user_color) if user_color is not None else None,
        "last_move": last_move,
        "last_move_by": last_move_by,
        "moves": game.board().variation_san(moves) if moves else "",
        "result": result,
        "e_board": bool(info.get("has_board")),
        "engine_move_pending": bool(info.get("pending_engine_move")),
        "time_control": info.get("time_label"),
        "board": str(board),
        "fen": board.fen(),
        "pgn": message.get("pgn"),
    }


@server.tool(annotations=ToolAnnotations(title="Get a hint", read_only_hint=True, open_world_hint=False))
async def get_hint() -> dict[str, str | int | None]:
    """Suggest the best move in the current position, like the + button (button 3) on the PicoChess clock.

    Use this when the user asks for a hint or the best move. The hint comes from
    the analysis PicoChess is already running, by its Tutor or engine, for exactly
    the current position. It returns the move in SAN, the expected continuation,
    up to two other candidate moves, the search depth and the source. It leaves
    out the evaluation; use get_evaluation for that.
    """
    board, info, analysis = await _current_analysis()
    user_color = None
    if info.get("interaction_mode") in _PLAYING_MODES:
        user_color = _USER_COLORS.get(info.get("play_mode"))
    if user_color is not None and board.turn != user_color:
        raise ToolError("It is the engine's turn; a hint is for the user's move.")
    pv = analysis.get("pv") or []
    if not pv:
        raise ToolError("PicoChess's analysis of this position has no move yet; try again in a moment.")
    others = [
        candidate["pv"][0]
        for candidate in (analysis.get("lines") or [])[1:]
        if candidate.get("pv")
    ]
    return {
        "hint": pv[0],
        "line": _line_san(analysis["fen"], pv[:HINT_LINE_PLIES]),
        "other_candidates": ", ".join(others) or None,
        "depth": analysis.get("depth"),
        "source": analysis.get("source"),
    }


@server.tool(annotations=ToolAnnotations(title="Get the top moves", read_only_hint=True, open_world_hint=False))
async def get_top_moves() -> dict[str, Any]:
    """List the best moves PicoChess's analysis has found in the current position, as in the web client.

    Use this when the user asks for the top moves, the candidate moves, or the
    analysis lines. Each line has its first move, an evaluation (in words, in
    centipawns from White's point of view, or a mate count), the search depth
    and the expected continuation. There are up to three lines: three in
    analysis mode, three in play mode on the user's turn while the Tutor is on,
    and one otherwise, including while the engine is thinking about its move.
    """
    board, info, analysis = await _current_analysis()
    lines = analysis.get("lines") or [
        {"depth": analysis.get("depth"), "score": analysis.get("score"), "mate": analysis.get("mate"), "pv": analysis.get("pv")}
    ]
    top_moves = []
    for line in lines:
        pv = line.get("pv") or []
        if not pv:
            continue
        mate = line.get("mate") or None
        centipawns = None if mate else line.get("score")
        top_moves.append(
            {
                "move": pv[0],
                "assessment": _assessment(centipawns, mate),
                "centipawns_white": centipawns,
                "mate_white": mate,
                "depth": line.get("depth"),
                "line": _line_san(analysis["fen"], pv[:HINT_LINE_PLIES]),
            }
        )
    if not top_moves:
        raise ToolError("PicoChess's analysis of this position has no moves yet; try again in a moment.")
    return {
        "to_move": _color_name(board.turn),
        "mode": _mode_label(info.get("interaction_mode")),
        "source": analysis.get("source"),
        "line_count": len(top_moves),
        "top_moves": top_moves,
    }


@server.tool(annotations=ToolAnnotations(title="Get the evaluation", read_only_hint=True, open_world_hint=False))
async def get_evaluation() -> dict[str, str | int | None]:
    """Evaluate the current position, like the - button (button 1) on the PicoChess clock.

    Use this when the user asks who is better or for the score. Returns an
    assessment in words, the score in centipawns from White's point of view
    (100 is one pawn; positive favours White) or a mate count (positive: White
    mates), the score from the user's point of view in a playing mode, the search
    depth and the source (Tutor or engine). It does not reveal the best move.
    """
    board, info, analysis = await _current_analysis()
    mate = analysis.get("mate") or None
    # With a mate, PicoChess reports a large placeholder score; the mate count is the evaluation.
    centipawns = None if mate else analysis.get("score")
    result: dict[str, str | int | None] = {
        "assessment": _assessment(centipawns, mate),
        "centipawns_white": centipawns,
        "mate_white": mate,
        "depth": analysis.get("depth"),
        "source": analysis.get("source"),
        "to_move": _color_name(board.turn),
    }
    if info.get("interaction_mode") in _PLAYING_MODES:
        user_color = _USER_COLORS.get(info.get("play_mode"))
        if user_color is not None and centipawns is not None:
            result["centipawns_for_you"] = centipawns if user_color == chess.WHITE else -centipawns
    return result


@server.tool(annotations=ToolAnnotations(title="Make a move", read_only_hint=False, open_world_hint=False))
async def make_move(move: str) -> dict[str, str | None]:
    """Play the user's move and, in play mode, return the engine's reply.

    Use this when the user plays a move, for example "1. e4", "e2-e4", "Nf3" or
    "O-O". The first move starts the game. In play mode the tool waits for the
    engine to answer and returns your_move and engine_move in SAN, a status,
    the resulting FEN, and the game so far as PGN; engine_move is null when the
    user's move ended the game or the engine is still thinking. In analysis
    mode the user enters moves for both sides and the engine does not reply;
    use get_hint or get_evaluation for its view. With an e-board connected,
    moves are made on the board and this tool refuses.
    """
    info = await _system_info()
    # Like the web client: with an e-board, the board is the only move input.
    if info.get("has_board"):
        raise ToolError(
            "PicoChess is connected to an e-board, so moves are made on the board. "
            "Play the move there; PicoChess shows the engine's reply on its displays."
        )
    playing = info.get("interaction_mode") in _PLAYING_MODES
    message = await _last_move_message()
    variant = message.get("variant", "chess")
    if variant != "chess":
        raise ToolError(f"Only standard chess is supported by this tool; PicoChess is playing {variant}.")
    # In analysis modes the latest message is always the user's own move.
    if playing and message.get("play") == "user":
        raise ToolError("The engine is still thinking about its move. Wait for its reply before moving.")
    # PicoChess silently ignores moves after a game end. A lost-on-time game keeps
    # "*", because local play may continue after the flag falls.
    result = _game_result(message)
    if result != "*":
        raise ToolError(f"The game is over ({result}). Start a new game with new_game.")

    board = chess.Board(message["fen"]) if message.get("fen") else chess.Board()
    user_move = _parse_move(board, move)
    user_san = board.san(user_move)
    board.push(user_move)
    # Like the web client, post the position after the move: PicoChess compares it with its own result.
    await _post_channel_action(
        {
            "action": "move",
            "source": chess.square_name(user_move.from_square),
            "target": chess.square_name(user_move.to_square),
            "promotion": chess.piece_symbol(user_move.promotion) if user_move.promotion else "",
            "fen": board.fen(),
        }
    )
    if playing:
        return await _wait_for_engine_reply(board, user_san)

    # Analysis modes: no engine reply, only confirm that PicoChess shows the move.
    message = await _wait_for_message(lambda m: _shows_position(m, board), "accept the move")
    return {
        "your_move": user_san,
        "engine_move": None,
        "status": f"move entered in {_mode_label(info.get('interaction_mode'))} mode; "
        f"{_color_name(board.turn)} to move",
        "fen": message.get("fen"),
        "pgn": message.get("pgn"),
    }


@server.tool(
    annotations=ToolAnnotations(
        title="Pause or resume the clock",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
async def pause_resume_clock(action: Literal["pause", "resume"]) -> dict[str, str | bool]:
    """Pause or resume the game clock on the user's turn, like the web client's play/pause button.

    Use action "pause" or "resume". It works only on the user's turn and only
    with a game clock (blitz, Fischer or tournament time); fixed move time,
    depth and nodes have no game clock. While the engine thinks, use
    force_engine_move instead. Before the first move, "resume" starts the clock
    and the game.
    """
    info = await _system_info()
    message = await _last_move_message()
    user_color = _USER_COLORS.get(info.get("play_mode"))
    if info.get("interaction_mode") not in _PLAYING_MODES or user_color is None:
        raise ToolError(f"The clock is paused and resumed only in a playing mode, not {_mode_label(info.get('interaction_mode'))} mode.")
    # Fixed, depth and nodes modes never run PicoChess's game clock, so pause_resume
    # would try to start it instead of stopping it.
    time_mode = (info.get("time_control") or {}).get("mode")
    if time_mode in _NO_GAME_CLOCK_MODES:
        label = info.get("time_label") or time_mode
        raise ToolError(f"The time control ({label}) has no game clock to pause or resume.")
    result = _game_result(message)
    if result != "*":
        raise ToolError(f"The game is over ({result}).")
    if info.get("pending_engine_move"):
        raise ToolError("The engine's move is waiting to be made on the e-board; the clock can be paused on your turn.")
    board = _game_from_message(message).end().board()
    if board.turn != user_color:
        raise ToolError(
            "It is the engine's turn. The clock can be paused only on your turn; "
            "use force_engine_move to make the engine move now."
        )

    want_running = action == "resume"
    if bool((await _clock_state()).get("running")) == want_running:
        state = "running" if want_running else "paused"
        return {"status": f"the clock was already {state}", "clock_running": want_running}

    # On the user's turn pause_resume toggles the clock. Should the turn change in the
    # meantime, PicoChess treats it as the play/pause action for the new state.
    await _post_channel_action({"action": "pause_resume"})
    await _wait_until(
        _clock_state,
        lambda clock: bool(clock.get("running")) == want_running,
        f"{action} the clock",
    )
    return {"status": "clock running" if want_running else "clock paused", "clock_running": want_running}


@server.tool(
    annotations=ToolAnnotations(
        title="Make the engine move now",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    )
)
async def force_engine_move() -> dict[str, str | None]:
    """Make the engine stop thinking and play the best move it has found so far.

    Use this when the user is tired of waiting for the engine, like "Move now"
    in the PicoChess web client. It works only while the engine is thinking
    about its move. Without an e-board the result includes the engine's move;
    with an e-board PicoChess shows the move on its displays and the user makes
    it on the board.
    """
    info = await _system_info()
    message = await _last_move_message()
    user_color = _USER_COLORS.get(info.get("play_mode"))
    if info.get("interaction_mode") not in _PLAYING_MODES or user_color is None:
        raise ToolError(f"The engine plays a move only in a playing mode, not {_mode_label(info.get('interaction_mode'))} mode.")
    result = _game_result(message)
    if result != "*":
        raise ToolError(f"The game is over ({result}).")
    if info.get("pending_engine_move"):
        raise ToolError(
            "The engine has already chosen its move; make it on the e-board, or ask for a different "
            "one with request_alternative_move."
        )
    board = _game_from_message(message).end().board()
    if board.turn == user_color:
        raise ToolError("It is your move, so the engine is not thinking.")

    # pause_resume forces a move only while the engine thinks. Should the engine finish
    # in the meantime, PicoChess treats it as the next play/pause action instead.
    await _post_channel_action({"action": "pause_resume"})

    loop = asyncio.get_running_loop()
    started = loop.time()
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        if info.get("has_board"):
            if (await _system_info()).get("pending_engine_move"):
                return {
                    "status": "the engine has chosen its move: it is shown on PicoChess's displays; "
                    "make it on the e-board",
                    "engine_move": None,
                    "fen": board.fen(),
                }
        else:
            message = await _last_move_message()
            reply = _engine_reply(board, message)
            if reply is not None:
                return {"status": "engine moved", "engine_move": board.san(reply), "fen": message.get("fen")}
        if loop.time() - started > MOVE_ACCEPT_TIMEOUT_SECONDS:
            raise ToolError(f"The engine did not move within {MOVE_ACCEPT_TIMEOUT_SECONDS:.0f} seconds.")


@server.tool(
    annotations=ToolAnnotations(
        title="Ask for an alternative move",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    )
)
async def request_alternative_move() -> dict[str, str | None]:
    """Ask the engine to replace the move it has chosen but that is not yet made on the e-board.

    Use this when the user wants the engine to play something else, like the
    play/pause button in the PicoChess web client. It works only with an
    e-board, after the engine has chosen its move and before the user has made
    that move on the board. The engine then searches again, excluding moves it
    already proposed. PicoChess shows the new move on its own displays; the user
    makes it on the board.
    """
    info = await _system_info()
    if not info.get("has_board"):
        raise ToolError(
            "An alternative move can be requested only with an e-board. Without one, "
            "PicoChess plays the engine's move immediately."
        )
    if info.get("interaction_mode") not in _PLAYING_MODES:
        raise ToolError(f"An alternative move is possible only in a playing mode, not {_mode_label(info.get('interaction_mode'))} mode.")
    if not info.get("pending_engine_move"):
        raise ToolError(
            "No engine move is waiting to be made on the board. Ask for an alternative after the "
            "engine has chosen its move and before making it on the board."
        )

    # pause_resume means "alternative move" only while an engine move is pending on the
    # e-board; in other states it starts or stops the clock, hence the checks above.
    before = await _last_move_message()
    await _post_channel_action({"action": "pause_resume"})

    loop = asyncio.get_running_loop()
    started = loop.time()
    accepted = False
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        info = await _system_info()
        message = await _last_move_message()
        pending = bool(info.get("pending_engine_move"))
        # PicoChess clears the pending flag and publishes a "reload" message when it
        # discards the announced move; the flag returns when the new move is chosen.
        if not pending or (message.get("play") == "reload" and message != before):
            accepted = True
        elapsed = loop.time() - started
        if accepted and pending:
            return {
                "status": "the engine has chosen another move: it is shown on PicoChess's displays; "
                "make it on the e-board",
                "fen": message.get("fen"),
                "pgn": message.get("pgn"),
            }
        if not accepted and elapsed > MOVE_ACCEPT_TIMEOUT_SECONDS:
            raise ToolError(f"PicoChess did not start an alternative search within {MOVE_ACCEPT_TIMEOUT_SECONDS:.0f} seconds.")
        if elapsed > ENGINE_REPLY_TIMEOUT_SECONDS:
            return {"status": "the engine is still searching for an alternative move", "fen": message.get("fen"), "pgn": message.get("pgn")}


@server.tool(
    annotations=ToolAnnotations(
        title="Start a new game", read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
    )
)
async def new_game() -> dict[str, str | None]:
    """Start a new standard chess game in PicoChess, discarding any game in progress.

    When a game is in progress, ask the user to confirm first, as the PicoChess
    web client does. Afterwards the user starts the game by playing a move with
    make_move.
    """
    await _post_channel_action({"action": "new_game"})
    start = chess.Board()
    message = await _wait_for_message(
        lambda m: m.get("play") == "newgame" and _shows_position(m, start),
        "start a new game",
    )
    return {"status": "new game started", "fen": message.get("fen"), "pgn": message.get("pgn")}


@server.tool(
    annotations=ToolAnnotations(
        title="Choose your colour",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
async def play_as(color: Literal["white", "black"]) -> dict[str, Any]:
    """Choose which colour the user plays against the engine, like the web client's Switch sides button.

    Use this when the user wants to play Black or White, or to swap sides. The
    game keeps its moves. If it becomes the engine's turn, the engine moves:
    choosing black before the first move lets the engine open as White.
    Without an e-board this returns the engine's move; with one, PicoChess
    shows it on its displays for the user to make on the board. Choosing the
    side to move while the engine is thinking stops it, and the user moves for
    that side instead. Play mode only; in analysis mode the user enters moves
    for both sides.
    """
    info = await _system_info()
    if info.get("interaction_mode") not in _PLAYING_MODES:
        raise ToolError(
            f"PicoChess is in {_mode_label(info.get('interaction_mode'))} mode, where you enter moves for both "
            "sides. Switch to play mode with set_mode first."
        )
    wanted = chess.WHITE if color == "white" else chess.BLACK
    board = _game_from_message(await _last_move_message()).end().board()
    if _USER_COLORS.get(info.get("play_mode")) == wanted:
        status = f"you already play {color}"
        switched = False
    else:
        # The web client's Switch sides button acts like the clock's lever.
        await _post_channel_action({"action": "clockbutton", "button": "64"})
        info = await _wait_until(
            _system_info, lambda i: _USER_COLORS.get(i.get("play_mode")) == wanted, f"switch you to {color}"
        )
        status = f"you now play {color}"
        switched = True

    result: dict[str, Any] = {"status": status, "your_color": color, "engine_move": None, "fen": board.fen()}
    if board.is_game_over():
        result["status"] += f"; {_game_over_status(board)}"
    elif board.turn == wanted:
        result["status"] += "; your move"
    elif info.get("has_board") or not switched:
        result["status"] += "; the engine is thinking"
        if info.get("has_board"):
            result["status"] += ", and PicoChess shows its move on its displays for you to make on the e-board"
    else:
        loop = asyncio.get_running_loop()
        started = loop.time()
        result["status"] += "; the engine is thinking"
        while loop.time() - started <= ENGINE_REPLY_TIMEOUT_SECONDS:
            message = await _last_move_message()
            reply = _engine_reply(board, message)
            if reply is not None:
                after = board.copy(stack=False)
                after.push(reply)
                result["status"] = f"{status}; " + (_game_over_status(after) or "the engine moved, your move")
                result["engine_move"] = board.san(reply)
                result["fen"] = message.get("fen")
                break
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    return result


@server.tool(
    annotations=ToolAnnotations(
        title="Set the time control",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
async def set_time_control(
    minutes: int | None = None,
    increment_seconds: int = 0,
    seconds_per_move: int | None = None,
    depth: int | None = None,
) -> dict[str, Any]:
    """Set the time control, like the web client's Time menu. Give exactly one kind.

    - minutes, with optional increment_seconds: a game clock for each side,
      such as 5 minutes, or 15 minutes plus 10 seconds per move ("15+10").
    - seconds_per_move: the engine thinks for that long on each move; there
      is no game clock.
    - depth: the engine searches to that many half-moves on each move; there
      is no game clock.
    The new time control applies at once: both clocks restart with the full
    time, also in a game in progress. PicoChess saves it for later games. Not
    while the engine is thinking.
    """
    kinds = [kind for kind in (minutes, seconds_per_move, depth) if kind is not None]
    if len(kinds) != 1:
        raise ToolError("Give exactly one of minutes, seconds_per_move or depth.")
    if kinds[0] < 1 or increment_seconds < 0:
        raise ToolError("Times and depths must be positive, and the increment cannot be negative.")
    if increment_seconds and minutes is None:
        raise ToolError("increment_seconds goes with minutes.")

    if minutes is not None and increment_seconds:
        params = {"time_mode": "2", "time": str(minutes), "fischer": str(increment_seconds)}
        expected: dict[str, Any] = {"mode": "fischer", "value": [minutes, increment_seconds]}
    elif minutes is not None:
        params = {"time_mode": "1", "time": str(minutes)}
        expected = {"mode": "blitz", "value": minutes}
    elif seconds_per_move is not None:
        params = {"time_mode": "0", "time": str(seconds_per_move)}
        expected = {"mode": "fixed", "value": seconds_per_move}
    else:
        params = {"time_mode": "4", "time": str(depth)}
        expected = {"mode": "depth", "value": depth}

    info, message = await asyncio.gather(_system_info(), _last_move_message())
    board = _game_from_message(message).end().board()
    user_color = _USER_COLORS.get(info.get("play_mode"))
    engine_turn = (
        info.get("interaction_mode") in _PLAYING_MODES
        and user_color is not None
        and board.turn != user_color
        and not board.is_game_over()
        and not info.get("pending_engine_move")
    )
    if engine_turn:
        raise ToolError("The engine is thinking. Change the time control on your turn, or between games.")

    await _post_channel_action({"action": "new_time", **params})
    await _wait_until(
        _current_settings, lambda s: s.get("time_control") == expected, "change the time control"
    )
    info = await _system_info()
    return {"status": "time control changed", "time_control": info.get("time_label")}


def _move_count(message: dict) -> int:
    return len(list(_game_from_message(message).mainline_moves()))


@server.tool(
    annotations=ToolAnnotations(
        title="Take back moves",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    )
)
async def take_back(half_moves: int | None = None) -> dict[str, Any]:
    """Take back moves, like Takeback in the web client's Position menu.

    By default this takes back the user's latest move: in play mode, the
    engine's reply and the user's move before it, so it is the user's turn
    again; while the engine is still thinking, only the user's move. In
    analysis mode it takes back the latest move. half_moves takes back exactly
    that many moves instead, counting each side's move separately. After an
    odd number in play mode, the user continues with the other colour, as
    after a takeback on an e-board; their colour is in your_color.

    With an e-board, take the moves back on the board as well; board and fen
    show the position to set up. PicoChess refuses takebacks with online
    engines, with retro engines in play mode, and when its takeback lock is on.
    """
    info, message = await asyncio.gather(_system_info(), _last_move_message())
    played = _played_moves(_game_from_message(message))
    if not played:
        raise ToolError("There are no moves to take back.")
    if half_moves is None:
        user_color = _USER_COLORS.get(info.get("play_mode")) if info.get("interaction_mode") in _PLAYING_MODES else None
        if user_color is None:
            half_moves = 1
        else:
            user_moves = [i for i, (before, _) in enumerate(played) if before.turn == user_color]
            if not user_moves:
                raise ToolError("You have not made a move yet, so there is none of yours to take back.")
            half_moves = len(played) - user_moves[-1]
    if not 1 <= half_moves <= len(played):
        raise ToolError(f"half_moves must be between 1 and {len(played)}, the number of moves played.")

    # PicoChess takes back one move per request.
    for taken in range(1, half_moves + 1):
        expected = len(played) - taken
        await _post_channel_action({"action": "take_back"})
        try:
            message = await _wait_for_message(lambda m: _move_count(m) == expected, "take back the move")
        except ToolError as exc:
            done = f" after taking back {taken - 1} of {half_moves}" if taken > 1 else ""
            raise ToolError(
                f"PicoChess did not take back the move{done}. It refuses takebacks with online engines, "
                "with retro engines in play mode, and when its takeback lock is on."
            ) from exc

    game = await get_game()
    result: dict[str, Any] = {
        "status": f"took back {half_moves} half-move{'s' if half_moves > 1 else ''}; {game['status']}",
        "your_color": game["your_color"],
        "last_move": game["last_move"],
        "moves": game["moves"],
        "fen": game["fen"],
    }
    if game["e_board"]:
        result["status"] += "; take the moves back on the e-board too"
        result["board"] = game["board"]
    return result


@server.tool(
    annotations=ToolAnnotations(
        title="Resign the game", read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False
    )
)
async def resign_game() -> dict[str, str | None]:
    """Resign the current game against the PicoChess engine, so the engine wins.

    Ask the user to confirm first, as the PicoChess web client does. Returns the
    final result (for example 0-1) and the finished game as PGN.
    """
    message = await _last_move_message()
    if not message or message.get("play") == "newgame":
        raise ToolError("No game is in progress, so there is nothing to resign.")
    result = _game_result(message)
    if result != "*":
        raise ToolError(f"The game is already over ({result}). Start a new game with new_game.")

    await _post_channel_action({"action": "resign_game"})
    message = await _wait_for_message(lambda m: _game_result(m) != "*", "end the game")
    return {"status": "you resigned", "result": _game_result(message), "pgn": message.get("pgn")}


@server.tool(
    annotations=ToolAnnotations(
        title="Switch between play and analysis",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
async def set_mode(mode: Literal["play", "analysis"], keep_analysis_position: bool = False) -> dict[str, str | None]:
    """Switch PicoChess between playing against the engine and free analysis.

    "play" is PicoChess's Normal mode: the user plays one side and the engine
    replies. "analysis" is the menu's Analysis mode: the user enters moves for
    both sides, the engine only analyses, and hints and evaluations follow the
    position.

    Entering analysis mode saves the game as it is. Switching back to play
    returns to that saved game, discarding the analysed moves, like the menu's
    "Return to" tile; the game continues where it was left. With an e-board,
    PicoChess then asks the user to set the pieces back and returns to play
    once the board matches; status says so, and board and fen show the
    position to set up. To continue playing from the analysed position
    instead, pass keep_analysis_position=true; ask the user which they want
    if it is unclear.
    """
    target = _SET_MODE_VALUES[mode]
    info = await _system_info()
    current = info.get("interaction_mode")
    if current == target:
        # Re-selecting Analysis mode would replace PicoChess's return-point checkpoint.
        status = f"already in {mode} mode"
    elif (
        mode == "play"
        and current == "ponder"
        and info.get("position_checkpoint_available")
        and not keep_analysis_position
    ):
        return await _return_from_analysis(info)
    else:
        await _post_channel_action({"action": "set_mode", "mode": target})
        info = await _wait_until(_system_info, lambda i: i.get("interaction_mode") == target, f"switch to {mode} mode")
        status = f"switched to {mode} mode"
        if mode == "play" and current == "ponder":
            status += ", continuing from the analysed position"

    board = _game_from_message(await _last_move_message()).end().board()
    user_color = _USER_COLORS.get(info.get("play_mode")) if mode == "play" else None
    if mode == "analysis":
        status += "; enter moves for both sides, the engine analyses without replying"
        if current != target:
            # PicoChess saves the game on entering analysis mode and publishes it moments later.
            try:
                await _wait_until(
                    _system_info,
                    lambda i: i.get("position_checkpoint_available"),
                    "save the game",
                    CHECKPOINT_WAIT_SECONDS,
                )
                status += "; the game is saved, and switching back to play returns to it"
            except ToolError:
                pass
    elif user_color is not None:
        status += f"; you play {_color_name(user_color)}"
    return {
        "status": status,
        "to_move": _color_name(board.turn),
        "your_color": _color_name(user_color) if user_color is not None else None,
    }


async def _return_from_analysis(info: dict) -> dict[str, str | None]:
    """Restore the game saved when analysis mode began, like the menu's "Return to" tile."""
    return_mode = info.get("position_checkpoint_return_mode") or "normal"
    return_label = "play" if return_mode == "normal" else _mode_label(return_mode)
    await _post_channel_action({"action": "restore_position_checkpoint"})

    def returned(i: dict) -> bool:
        return i.get("interaction_mode") == return_mode

    what = "return to the game saved when analysis mode began"
    if info.get("has_board"):
        # PicoChess returns only once the e-board shows the restored position, which may take the user a while.
        try:
            info = await _wait_until(_system_info, returned, what, CHECKPOINT_WAIT_SECONDS)
        except ToolError:
            board = _game_from_message(await _last_move_message()).end().board()
            return {
                "status": (
                    "restoring the game saved when analysis mode began: set the pieces on the e-board as in "
                    f"board; PicoChess confirms when they match and then returns to {return_label} mode"
                ),
                "to_move": _color_name(board.turn),
                "your_color": None,
                "board": str(board),
                "fen": board.fen(),
            }
    else:
        info = await _wait_until(_system_info, returned, what)

    board = _game_from_message(await _last_move_message()).end().board()
    user_color = _USER_COLORS.get(info.get("play_mode")) if return_mode in _PLAYING_MODES else None
    status = f"returned to the game saved when analysis mode began, in {return_label} mode"
    if user_color is not None:
        status += f"; you play {_color_name(user_color)}"
    return {
        "status": status,
        "to_move": _color_name(board.turn),
        "your_color": _color_name(user_color) if user_color is not None else None,
    }


@server.tool(annotations=ToolAnnotations(title="Get PicoTutor settings", read_only_hint=True, open_world_hint=False))
async def get_tutor() -> dict[str, str | bool]:
    """Return PicoTutor's Watcher, Coach and Explorer settings, as in the web client's Tutor menu.

    Use this when the user asks whether the Tutor, Watcher, Coach or Explorer
    is on. See set_tutor for what each setting does. note, when present, says
    when a setting has no effect.
    """
    settings, info = await asyncio.gather(_current_settings(), _system_info())
    return _tutor_summary(settings, info)


@server.tool(
    annotations=ToolAnnotations(
        title="Change PicoTutor settings",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
async def set_tutor(
    watcher: bool | None = None,
    coach: Literal["off", "on", "lift", "brain", "hand"] | None = None,
    explorer: bool | None = None,
) -> dict[str, str | bool]:
    """Turn PicoTutor's Watcher, Coach or Explorer on or off, like the web client's Tutor menu.

    Pass only the settings to change; the others keep their values. PicoChess
    saves them, so they also apply after a restart.
    - watcher: PicoTutor rates each of the user's moves (!!, !, !?, ?!, ?, ??),
      warns of mates, and after a blunder shows the threat and a better move.
    - coach: how PicoTutor helps on the user's turn. Any value other than "off"
      also makes PicoTutor analyse, so hints and evaluations come from it.
      "on": hints and evaluations on request. "lift": as "on", and lifting the
      king and putting it back asks for a hint and an evaluation. "brain":
      Hand & Brain training; PicoChess names the kind of piece to move.
      "hand": lifting a piece and putting it back asks whether that piece is
      part of a good move. "lift" and "hand" need an e-board.
    - explorer: PicoChess names the opening of the current position.
    PicoChess shows and announces the Tutor's feedback on its own displays.
    In analysis mode PicoTutor is inactive. note, when present, says when a
    setting has no effect.
    """
    if watcher is None and coach is None and explorer is None:
        raise ToolError("Give at least one of watcher, coach or explorer to change.")
    wanted: dict[str, Any] = {}
    if watcher is not None:
        wanted["tutor_watcher"] = watcher
    if coach is not None:
        wanted["tutor_coach"] = coach
    if explorer is not None:
        wanted["tutor_explorer"] = explorer

    current = await _current_settings()
    # PicoChess applies each setting in turn, so send them one at a time like the Tutor menu does.
    for key, value in wanted.items():
        if current.get(key) == value:
            continue
        val = value if isinstance(value, str) else ("true" if value else "false")
        await _post_channel_action({"action": "picotutor", "tutor": key.removeprefix("tutor_"), "val": val})

    settings = await _wait_until(
        _current_settings,
        lambda s: all(s.get(key) == value for key, value in wanted.items()),
        "apply the Tutor settings",
    )
    return _tutor_summary(settings, await _system_info())


@server.tool(
    annotations=ToolAnnotations(
        title="Set up a position", read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
    )
)
async def set_position(fen: str) -> dict[str, str | bool | None]:
    """Replace the current game with the position in a FEN, like Position > Set Pos in the web client.

    The game continues from that position without earlier moves; the FEN's
    side-to-move field says who moves next. When a game is in progress, ask the
    user to confirm first. Works with and without an e-board. With an e-board,
    PicoChess then guides the user by voice to set up the pieces and confirms
    when the board matches; that can take a while and does not block this tool.
    """
    fen = fen.strip()
    try:
        chess.Board(fen)
    except ValueError as exc:
        raise ToolError(f"This is not a valid FEN: {exc}") from exc

    info = await _system_info()
    # For a MAME engine on its own turn PicoChess rejects Set Pos and treats the request
    # as "move now", so refuse here instead.
    if info.get("is_mame") and info.get("interaction_mode") in _PLAYING_MODES:
        user_color = _USER_COLORS.get(info.get("play_mode"))
        current = _game_from_message(await _last_move_message()).end().board()
        if user_color is not None and current.turn != user_color:
            raise ToolError("With a MAME engine, a position can be set only on your turn. Wait for the engine's move first.")

    response = await asyncio.to_thread(_request_json, "/channel", {"action": "set_position", "fen": fen}, True)
    new_fen = response.get("fen") or fen
    await _wait_for_message(
        lambda m: _same_position(m.get("fen"), new_fen), "set up the new position", SETUP_TIMEOUT_SECONDS
    )
    status = "position set"
    if info.get("has_board"):
        status += (
            ": set up the pieces on the e-board to match. PicoChess guides you by voice "
            "and confirms when the board matches"
        )
    return {
        "status": status,
        "fen": new_fen,
        "to_move": _color_name(chess.Board(new_fen).turn),
        "e_board": bool(info.get("has_board")),
    }


@server.tool(
    annotations=ToolAnnotations(
        title="Scan the e-board", read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
    )
)
async def scan_board(
    side_to_move: Literal["white", "black"] = "white",
    board_reversed: bool = False,
    castling: str = "KQkq",
) -> dict[str, str | None]:
    """Replace the current game with the position on the e-board, like Position > Scan in the web client.

    E-board only: the user first places the pieces on the board. side_to_move
    says who moves next. Set board_reversed when the board is turned around, with
    Black's pieces starting on the near side. castling lists the castling rights
    still allowed, as in a FEN (default KQkq, or "-" for none); PicoChess drops
    any the placement makes impossible. When a game is in progress, ask the user
    to confirm first.
    """
    info = await _system_info()
    if not info.get("has_board"):
        raise ToolError("Scanning needs an e-board. Without one, set a position with set_position and a FEN.")
    castling = castling.strip() or "-"
    if castling != "-" and set(castling) - set("KQkq"):
        raise ToolError('castling must use the letters K, Q, k and q, or "-" for none.')

    def flag(value: bool) -> str:
        return "true" if value else "false"

    # The same parameters as the web client's Scan sliders.
    response = await asyncio.to_thread(
        _request_json,
        "/channel",
        {
            "action": "scan_board",
            "sideToPlay": flag(side_to_move == "white"),
            "boardSide": flag(board_reversed),
            "uci960": "false",
            "whiteCastleKing": flag("K" in castling),
            "whiteCastleQueen": flag("Q" in castling),
            "blackCastleKing": flag("k" in castling),
            "blackCastleQueen": flag("q" in castling),
        },
        True,
    )
    new_fen = response.get("fen")
    if not response.get("success") or not new_fen:
        raise ToolError(
            "PicoChess could not read a legal position from the e-board. Check that every piece is "
            "placed, both kings are on the board, and the side to move is right."
        )
    await _wait_for_message(
        lambda m: _same_position(m.get("fen"), new_fen), "set up the scanned position", SETUP_TIMEOUT_SECONDS
    )
    return {
        "status": "position scanned from the e-board",
        "fen": new_fen,
        "to_move": _color_name(chess.Board(new_fen).turn),
        "castling": new_fen.split(" ")[2],
    }


if __name__ == "__main__":
    logger.info("serving PicoChess at %s over stdio", PICOCHESS_URL)
    server.run()
