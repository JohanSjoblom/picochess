"""Policy for setup positions and loading PGN game history."""

from __future__ import annotations

import chess
from chess.pgn import Game

from dgt.util import Mode


RK_STARTING_BOARD_FEN = "8/8/8/8/8/8/krbnNBRK/qrbnNBRQ"


def should_preserve_set_position_history(
    event_game: chess.Board | None,
    is_mame_engine: bool,
    supports_position: bool,
    supports_edit: bool,
) -> bool:
    """Return whether browser Set Pos should keep the selected PGN prefix."""
    return event_game is not None and not mame_requires_fresh_fen_root(
        is_mame_engine,
        supports_position,
        supports_edit,
    )


def setup_position_game(
    fen: str,
    uci960: bool,
    event_game: chess.Board | None,
    preserve_history: bool = True,
) -> chess.Board:
    """Build the live game for a setup-position event.

    The web Set Pos action normally promotes the selected PGN prefix, including
    its move stack, into the live game. Interfaces without move-history editing
    support can request the selected FEN as a fresh root. A physical eboard Scan
    has no event game and therefore always treats the scanned FEN as a fresh
    root.
    """
    if event_game is not None and preserve_history:
        return event_game.copy(stack=True)
    return chess.Board(fen, chess960=uci960)


def set_position_new_game_code(fen: str, uci960: bool, variant: str) -> int | None:
    """Return the New Game code when a Set Pos target is a starting layout."""
    fen_parts = str(fen or "").split()
    if not fen_parts:
        return None
    board_fen = fen_parts[0]
    if variant == "racingkings" and board_fen == RK_STARTING_BOARD_FEN:
        return 518
    try:
        position = chess.Board(f"{board_fen} w - - 0 1").chess960_pos(ignore_castling=True)
    except (TypeError, ValueError):
        return None
    if position == 518 or (uci960 and position is not None):
        return position
    return None


def pending_set_position_fen_action(
    fen: str,
    target_fen: str,
    allow_chess960: bool,
    variant: str,
) -> tuple[str, int | None]:
    """Classify a physical FEN while an explicit Set Pos is awaiting OK."""
    new_game_code = set_position_new_game_code(fen, allow_chess960, variant)
    if new_game_code is not None:
        return "new_game", new_game_code
    if fen == target_fen:
        return "target", None
    return "wait", None


def should_load_pgn_moves(stop_at_halfmove: int | None) -> bool:
    """Return whether mainline moves should be applied while loading a PGN."""
    return stop_at_halfmove != 0


def mame_requires_fresh_fen_root(
    is_mame_engine: bool,
    supports_position: bool,
    supports_edit: bool,
) -> bool:
    """Return whether MAME must replace history with the current FEN."""
    return is_mame_engine and supports_position and not supports_edit


def should_preserve_loaded_pgn_history(
    is_mame_engine: bool,
    start_replay: bool,
    supports_position: bool,
    supports_edit: bool,
) -> bool:
    """Return whether Read Game should retain the loaded move stack."""
    return start_replay or not mame_requires_fresh_fen_root(
        is_mame_engine,
        supports_position,
        supports_edit,
    )


def pgn_with_board_as_fresh_root(source_game: Game, board: chess.Board) -> Game:
    """Rebase a PGN on ``board`` while retaining its descriptive headers."""
    rebased_game = Game.from_board(board.copy(stack=False))
    setup_headers = {
        key: rebased_game.headers[key]
        for key in ("SetUp", "FEN")
        if key in rebased_game.headers
    }
    rebased_game.headers.update(source_game.headers)
    rebased_game.headers.pop("SetUp", None)
    rebased_game.headers.pop("FEN", None)
    rebased_game.headers.update(setup_headers)
    return rebased_game


def loaded_pgn_interaction_mode(
    previous_mode: Mode,
    start_replay: bool,
    has_custom_fen: bool,
    loaded_game_finished: bool,
) -> Mode:
    """Choose the mode for a successfully loaded PGN."""
    if start_replay:
        return Mode.PGNREPLAY
    if not loaded_game_finished:
        if previous_mode in (Mode.NORMAL, Mode.BRAIN, Mode.TRAINING):
            return previous_mode
        return Mode.NORMAL
    if has_custom_fen:
        return Mode.KIBITZ
    if previous_mode in (Mode.NORMAL, Mode.BRAIN, Mode.TRAINING):
        return previous_mode
    return Mode.NORMAL
