"""Guards for move entry, event ownership, and takeback handling."""

from __future__ import annotations

import chess

from dgt.api import Message
from dgt.util import Mode


def analysis_event_matches_position(event_fen: str | None, current_fen: str) -> bool:
    """Accept position-tagged analysis only for its source position.

    Untagged events remain valid for compatibility with external or older
    producers using the public Event classes.
    """
    return event_fen is None or event_fen == current_fen


def should_show_setpieces_after_lift_timeout(lifted_piece_char: str, is_hand_mode: bool) -> bool:
    """Return true when a held lifted piece should reach the audible set-pieces threshold."""
    if not lifted_piece_char:
        return False
    return lifted_piece_char in ("K", "k") or not is_hand_mode


def should_reject_user_move_after_game_end(
    interaction_mode: Mode, game_declared: bool, game_ending: str | None
) -> bool:
    """Return true when a playing-mode move should not alter an ended game."""
    if interaction_mode not in (Mode.NORMAL, Mode.BRAIN, Mode.TRAINING, Mode.REMOTE):
        return False
    return bool(game_declared) or (game_ending or "*") != "*"


def should_process_sliding_move(
    interaction_mode: Mode, game_declared: bool, game_ending: str | None
) -> bool:
    """Return whether sliding detection may alter the current game."""
    return not should_reject_user_move_after_game_end(
        interaction_mode,
        game_declared,
        game_ending,
    )


def should_resume_game_after_takeback(
    game_over: bool, game_declared: bool, game_ending: str | None
) -> bool:
    """Return whether takeback has reopened a previously ended game."""
    return not game_over and (
        bool(game_declared) or (game_ending or "*") != "*"
    )


def remote_move_matches_current_position(move: chess.Move, posted_fen: str | None, board: chess.Board) -> bool:
    """Return true when a web move's posted resulting FEN matches the live board."""
    if not posted_fen:
        return True
    if move not in board.legal_moves:
        return False
    try:
        expected = board.copy(stack=False)
        expected.push(move)
        posted_board_fen = posted_fen.split()[0]
    except (IndexError, ValueError, AssertionError):
        return False
    return posted_board_fen == expected.board_fen()


def user_move_task_matches_position(
    move: chess.Move,
    expected_fen: str,
    expected_revision: int,
    board: chess.Board,
    current_fen: str,
    current_revision: int,
    done_computer_fen: str | None,
) -> bool:
    """Return whether a delayed user-move handler still owns the live position."""
    return bool(
        done_computer_fen is None
        and expected_revision == current_revision
        and expected_fen == current_fen
        and board.move_stack
        and board.peek() == move
    )


def engine_move_event_matches_state(
    event_fen: str | None,
    current_fen: str,
    event_search_revision: int | None,
    current_search_revision: int,
    done_computer_fen: str | None,
) -> bool:
    """Return whether an engine result still owns an unannounced live position."""
    return bool(
        done_computer_fen is None
        and analysis_event_matches_position(event_fen, current_fen)
        and (event_search_revision is None or event_search_revision == current_search_revision)
    )


def should_resume_clock_after_rejected_engine_move(
    clock_was_running: bool,
    clock_is_running: bool,
    done_computer_fen: str | None,
) -> bool:
    """Resume only a clock this handler stopped and no newer announced move owns."""
    return clock_was_running and not clock_is_running and done_computer_fen is None


def user_move_pre_search_messages(
    user_move_message: Message,
    tutor_reveal_move: chess.Move | None = None,
    opening_message: Message | None = None,
) -> list[Message]:
    """Return user-move display messages in their required pre-search order."""
    messages = [user_move_message]
    if tutor_reveal_move is not None:
        messages.append(Message.TUTOR_MOVE_REVEAL(move=tutor_reveal_move))
    if opening_message is not None:
        messages.append(opening_message)
    return messages


def should_block_takeback(
    take_back_locked: bool,
    online_mode: bool,
    emulation_mode: bool,
    automatic_takeback: bool,
    ponder_mode: bool = False,
) -> bool:
    """Keep normal takeback guards, except in flexible PONDER analysis."""
    if ponder_mode:
        return False
    return bool(
        take_back_locked
        or online_mode
        or (emulation_mode and not automatic_takeback)
    )
