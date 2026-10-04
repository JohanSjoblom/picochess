"""Minimal MCP server for a PicoChess instance running on this machine.

It talks to the PicoChess web server through the same HTTP endpoints the
browser client uses, so PicoChess itself needs no changes.

Run with the virtual environment in this folder:
    mcp/.venv/Scripts/python.exe mcp/server.py      (Windows)
    mcp/.venv/bin/python mcp/server.py              (Linux, macOS)

Set PICOCHESS_URL to reach PicoChess somewhere other than http://localhost:8080.
"""

import asyncio
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

import chess
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

PICOCHESS_URL = os.environ.get("PICOCHESS_URL", "http://localhost:8080").rstrip("/")
REQUEST_TIMEOUT_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.5
# PicoChess shows an accepted web move within moments; no sign of it means it was ignored.
MOVE_ACCEPT_TIMEOUT_SECONDS = 10.0
ENGINE_REPLY_TIMEOUT_SECONDS = 120.0

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
        raise ToolError(f"PicoChess rejected the request to {path} (HTTP {exc.code}).") from exc
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


async def _wait_for_message(accepts, what: str) -> dict:
    """Poll the latest position message until accepts(message) holds, or fail.

    what completes the sentence "PicoChess did not ...".
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    while True:
        message = await _last_move_message()
        if accepts(message):
            return message
        if loop.time() - started > MOVE_ACCEPT_TIMEOUT_SECONDS:
            raise ToolError(f"PicoChess did not {what} within {MOVE_ACCEPT_TIMEOUT_SECONDS:.0f} seconds.")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


def _game_result(message: dict) -> str:
    """Return the PGN Result tag of a position message; "*" while the game is still open."""
    match = _PGN_RESULT.search(message.get("pgn") or "")
    return match.group(1) if match else "*"


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
    """Return the chess engine PicoChess is currently using.

    Use this when the user asks which engine is loaded or selected. The result
    has engine_name and, when PicoChess has reported it, engine_elo.
    """
    info = await _system_info()
    engine_name = info.get("engine_name")
    if not engine_name:
        raise ToolError("PicoChess is running but has not reported an engine yet. It may still be starting up.")
    result: dict[str, str | int] = {"engine_name": engine_name}
    if info.get("engine_elo"):
        result["engine_elo"] = info["engine_elo"]
    return result


@server.tool(annotations=ToolAnnotations(title="Make a move", read_only_hint=False, open_world_hint=False))
async def make_move(move: str) -> dict[str, str | None]:
    """Play the user's move against the PicoChess engine and return the engine's reply.

    Use this when the user plays a move, for example "1. e4", "e2-e4", "Nf3" or
    "O-O". The first move starts the game. The tool waits for the engine to
    answer and returns your_move and engine_move in SAN, a status, the
    resulting FEN, and the game so far as PGN. engine_move is null when the
    user's move ended the game or the engine is still thinking. With an
    e-board connected, moves are made on the board and this tool refuses.
    """
    # Like the web client: with an e-board, the board is the only move input.
    if (await _system_info()).get("has_board"):
        raise ToolError(
            "PicoChess is connected to an e-board, so moves are made on the board. "
            "Play the move there; PicoChess shows the engine's reply on its displays."
        )
    message = await _last_move_message()
    variant = message.get("variant", "chess")
    if variant != "chess":
        raise ToolError(f"Only standard chess is supported by this tool; PicoChess is playing {variant}.")
    if message.get("play") == "user":
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
    return await _wait_for_engine_reply(board, user_san)


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


if __name__ == "__main__":
    logger.info("serving PicoChess at %s over stdio", PICOCHESS_URL)
    server.run()
