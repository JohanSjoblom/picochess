#!/usr/bin/env python3

# Copyright (C) 2013-2018 Jean-Francois Romang (jromang@posteo.de)
#                         Shivkumar Shivaji ()
#                         Jürgen Précour (LocutusOfPenguin@posteo.de)
#                         Wilhelm
#                         Dirk ("Molli")
#                         Johan Sjöblom (messier109@gmail.com)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.


import asyncio
import copy
import logging
from typing import Any

import chess
import chess.pgn
import chess.variant
from chess.pgn import Game

from alternative_mover import AlternativeMover
from analysis_depth import BestSeenDepth
from dgt.api import Message
from dgt.menu import DgtMenu
from dgt.translate import DgtTranslate
from dgt.util import GameResult, Mode, PlayMode, TimeMode
from picotutor import PicoTutor
from timecontrol import TimeControl
from uci.rating import Rating
from utilities import AsyncRepeatingTimer, DisplayMsg
import pairing_ipc

logger = logging.getLogger("picochess")


class PicochessState:
    """Class to keep track of state in Picochess."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        dgttranslate: DgtTranslate,
        dgtmenu: DgtMenu,
    ):
        self.automatic_takeback = False
        self.best_move_displayed = None  # temporary copy of done_computer_fen? should be cleaned out
        self.best_move_posted = False  # True when "extra" computer move already posted to Picotutor
        self.book_in_use = ""
        self.comment_file = ""
        self.dgtmenu = dgtmenu
        self.dgttranslate = dgttranslate
        self.done_computer_fen = None  # FEN of last done computer move when not yet pushed to game board
        self.done_move = chess.Move.null()  # last done move by computer, not yet pushed to game board
        self.engine_file = ""
        self.engine_text = None
        self.engine_level = ""
        self.new_engine_level = ""
        self.newgame_happened = False
        self.old_engine_level = ""
        self.error_fen = None
        self.pairing_bridge: pairing_ipc.PairingBridge | None = None
        self.fen_error_occured = False
        self.fen_timer: AsyncRepeatingTimer | None = None
        self.fen_timer_running = False
        self.flag_flexible_ponder = False
        self.flag_last_engine_emu = False
        self.flag_last_engine_online = False
        self.flag_last_engine_pgn = False
        self.flag_picotutor = True
        self.flag_pgn_game_over = False
        self.flag_premove = False
        self.flag_startup = False
        self.game = None or chess.Board()
        self.engine_move_was_book = False
        self.engine_search_revision = 0
        self.game_declared = False  # User declared resignation or draw
        self.game_started = False  # Lifecycle flag: true once play has started, even after takeback to move 0.
        self.interaction_mode = Mode.NORMAL
        self.user_move_revision = 0
        self.last_legal_fens: list[Any] = []
        self.last_move = None
        self.legal_fens: list[Any] = []
        self.legal_fens_after_cmove: list[Any] = []
        self.max_guess = 0
        self.max_guess_black = 0
        self.max_guess_white = 0
        self.pgn_engine_games: list[dict[str, Any]] = []
        self.pgn_engine_game_index = -1
        self.pgn_engine_total_halfmoves: int | None = None
        self.pgn_engine_result = "*"
        self.no_guess_black = 1
        self.no_guess_white = 1
        self.online_decrement = 0
        self.pb_move = chess.Move.null()  # Best ponder move
        self.pgn_book_test = False
        self.pgn_replay_next_move_fen = ""
        self.pgn_replay_next_move = None
        self.pgn_replay_book_cache = {}
        self.loaded_pgn_has_variations = False
        self.loaded_pgn_finished = False
        self.pgn_replay_tutor_regeneration = True
        self.pgn_replay_tutor_regeneration_override: bool | None = None
        self.loaded_pgn_game: Game | None = None
        self.loaded_pgn_filename = ""
        self.mame_recovery_rebase_pending = False
        self.picotutor: PicoTutor | None = None
        self.last_hand_coach_move: chess.Move | None = None
        self.hand_coach_task: asyncio.Task | None = None
        self.brain_hint_task: asyncio.Task | None = None
        self.brain_hint_clock_paused: bool = False
        self.clock_paused_by_board_loss: bool = False
        self.brain_required_piece_type: chess.PieceType | None = None
        self.brain_best_move: chess.Move | None = None
        self.coach_triggered_piece_type: chess.PieceType | None = None
        self.play_mode = PlayMode.USER_WHITE
        self.position_mode = False
        self.set_position_ack_pending = False
        self.set_position_ack_target_fen = ""
        self.set_position_ack_ready = False
        self.setpieces_switch_anchor_fen = ""
        self.setpieces_switch_armed = False
        self.reset_auto = False
        self.searchmoves = AlternativeMover()
        self.seeking_flag = False
        self.set_location = ""
        self.start_time_cmove_done = 0.0
        self.take_back_locked = False
        self.takeback_active = False
        self.tc_init_last = None
        self.think_time = 0
        self.time_control: TimeControl | None = None
        self.rating: Rating | None = None
        self.coach_triggered = False
        self.last_error_fen = ""
        self.artwork_in_use = False
        self.delay_fen_error = 4
        self.main_loop = loop
        self.ignore_next_engine_move = False  # True only after takeback during think
        self.autoplay_pgn_file = False  # Play/Pause button toggles auto replay of pgn file
        self.autoplay_half_moves = 0  # last seen autoplayed half-move (user can deviate)
        self.best_sent_depth = BestSeenDepth()  # best seen depth for a playing enginge
        self.pending_engine_result: str | None = None
        # One PONDER-session checkpoint. It preserves the complete position,
        # move stack, and return mode while the user analyses temporarily.
        self.position_checkpoint_game: chess.Board | None = None
        self.position_checkpoint_variant = None
        self.position_checkpoint_variant_name: str | None = None
        self.position_checkpoint_play_mode: PlayMode | None = None
        self.position_checkpoint_interaction_mode: Mode | None = None
        self.position_checkpoint_game_started: bool | None = None
        self.position_checkpoint_game_declared: bool | None = None
        self.position_checkpoint_time_control: dict[str, Any] | None = None
        self.position_checkpoint_restore_pending = False
        self.position_checkpoint_restore_completing = False
        self.position_checkpoint_restored_play_mode: PlayMode | None = None
        self.position_checkpoint_restored_fen: str | None = None
        self.position_checkpoint_restored_moves: tuple[chess.Move, ...] | None = None
        # Chess variant support (e.g., "3check", "atomic")
        self.variant = "chess"
        self._threecheck_board = None  # chess.variant.ThreeCheckBoard instance when variant == "3check"
        self._atomic_board = None  # chess.variant.AtomicBoard instance when variant == "atomic"
        self._racingkings_board = None  # chess.variant.RacingKingsBoard instance when variant == "racingkings"
        self._antichess_board = None  # chess.variant.AntichessBoard instance when variant == "antichess"

    def save_position_checkpoint(self, interaction_mode: Mode | None = None) -> None:
        """Remember the position, history, and mode from before temporary analysis."""
        self.position_checkpoint_game = self.game.copy(stack=True)
        variant_board = self.get_variant_board()
        self.position_checkpoint_variant = variant_board.copy(stack=True) if variant_board is not None else None
        self.position_checkpoint_variant_name = self.variant
        self.position_checkpoint_play_mode = self.play_mode
        self.position_checkpoint_interaction_mode = interaction_mode
        self.position_checkpoint_game_started = self.game_started
        self.position_checkpoint_game_declared = self.game_declared
        self.position_checkpoint_time_control = self._snapshot_position_checkpoint_time_control()
        self.position_checkpoint_restore_pending = False
        self.position_checkpoint_restore_completing = False
        self._clear_position_checkpoint_restore_context()

    def _snapshot_position_checkpoint_time_control(self) -> dict[str, Any] | None:
        """Copy stopped-clock state without retaining mutable timer dictionaries."""
        if self.time_control is None:
            return None
        return {
            "parameters": copy.deepcopy(self.time_control.get_parameters()),
            "clock_time": copy.deepcopy(self.time_control.clock_time),
            "moves_to_go": self.time_control.moves_to_go,
        }

    def _restore_position_checkpoint_time_control(self) -> None:
        """Restore checkpoint clock values, deliberately leaving the clock stopped."""
        snapshot = self.position_checkpoint_time_control
        if self.time_control is None or snapshot is None:
            return
        self.time_control.stop_internal(log=False)
        parameters = copy.deepcopy(snapshot["parameters"])
        self.time_control.mode = parameters["mode"]
        self.time_control.move_time = parameters["fixed"]
        self.time_control.game_time = parameters["blitz"]
        self.time_control.fisch_inc = parameters["fischer"]
        self.time_control.moves_to_go_orig = parameters["moves_to_go"]
        self.time_control.game_time2 = parameters["blitz2"]
        self.time_control.depth = parameters["depth"]
        self.time_control.node = parameters["node"]
        self.time_control.internal_time = parameters["internal_time"]
        self.time_control.clock_time = copy.deepcopy(snapshot["clock_time"])
        self.time_control.moves_to_go = snapshot["moves_to_go"]
        self.time_control.timer = None
        self.time_control.run_color = None
        self.time_control.active_color = None
        self.time_control.start_time = None

    def has_compatible_position_checkpoint(self) -> bool:
        """Return whether the checkpoint can be restored for the active variant."""
        return bool(
            self.position_checkpoint_game is not None
            and self.position_checkpoint_variant_name == self.variant
        )

    def _clear_position_checkpoint_restore_context(self) -> None:
        self.position_checkpoint_restored_play_mode = None
        self.position_checkpoint_restored_fen = None
        self.position_checkpoint_restored_moves = None

    def can_preserve_position_checkpoint_play_mode(self) -> bool:
        """Return whether play may resume from an unchanged restored checkpoint."""
        return bool(
            self.position_checkpoint_restored_play_mode is not None
            and self.position_checkpoint_restored_fen == self.game.fen()
            and self.position_checkpoint_restored_moves == tuple(self.game.move_stack)
        )

    def restore_position_checkpoint(self) -> bool:
        """Restore the saved position and complete move stack."""
        if not self.has_compatible_position_checkpoint():
            return False
        self.game = self.position_checkpoint_game.copy(stack=True)
        checkpoint_variant = self.position_checkpoint_variant
        if self.variant == "3check":
            self._threecheck_board = checkpoint_variant.copy(stack=True) if checkpoint_variant is not None else None
        elif self.variant == "atomic":
            self._atomic_board = checkpoint_variant.copy(stack=True) if checkpoint_variant is not None else None
        elif self.variant == "racingkings":
            self._racingkings_board = checkpoint_variant.copy(stack=True) if checkpoint_variant is not None else None
        elif self.variant == "antichess":
            self._antichess_board = checkpoint_variant.copy(stack=True) if checkpoint_variant is not None else None
        if self.position_checkpoint_play_mode is not None:
            self.play_mode = self.position_checkpoint_play_mode
        if self.position_checkpoint_game_started is not None:
            self.game_started = self.position_checkpoint_game_started
        if self.position_checkpoint_game_declared is not None:
            self.game_declared = self.position_checkpoint_game_declared
        self._restore_position_checkpoint_time_control()
        self.position_checkpoint_restored_play_mode = self.position_checkpoint_play_mode
        self.position_checkpoint_restored_fen = self.game.fen()
        self.position_checkpoint_restored_moves = tuple(self.game.move_stack)
        return True

    def claim_position_checkpoint_restore_completion(self) -> bool:
        """Claim the one completion path for an active checkpoint restore."""
        if not self.position_checkpoint_restore_pending or self.position_checkpoint_restore_completing:
            return False
        self.position_checkpoint_restore_completing = True
        return True

    def release_position_checkpoint_restore_completion(self) -> None:
        """Release checkpoint completion ownership after success or failure."""
        self.position_checkpoint_restore_completing = False

    def set_ponder_turn(self, turn: chess.Color) -> bool:
        """Retag the current standard-chess PONDER position without touching its checkpoint."""
        if self.interaction_mode != Mode.PONDER or self.variant != "chess":
            return False

        # A side correction starts a fresh disposable line. Keeping the old
        # scratch stack would make later pops restore turns from before the
        # correction. An independent checkpoint, when present, still owns the
        # saved history.
        scratch = self.game.copy(stack=False)
        scratch.turn = bool(turn)
        scratch.ep_square = None
        self.game = scratch
        return True

    def clear_position_checkpoint(self) -> None:
        """Discard the saved PONDER checkpoint."""
        self.position_checkpoint_game = None
        self.position_checkpoint_variant = None
        self.position_checkpoint_variant_name = None
        self.position_checkpoint_play_mode = None
        self.position_checkpoint_interaction_mode = None
        self.position_checkpoint_game_started = None
        self.position_checkpoint_game_declared = None
        self.position_checkpoint_time_control = None
        self.position_checkpoint_restore_pending = False
        self.position_checkpoint_restore_completing = False
        self._clear_position_checkpoint_restore_context()

    def push_move(self, move: chess.Move) -> None:
        """Push a move to the game board and sync variant board if active."""
        self.game.push(move)
        if self.variant == "3check" and self._threecheck_board is not None:
            self._threecheck_board.push(move)
        elif self.variant == "atomic" and self._atomic_board is not None:
            self._atomic_board.push(move)
        elif self.variant == "racingkings" and self._racingkings_board is not None:
            self._racingkings_board.push(move)
        elif self.variant == "antichess" and self._antichess_board is not None:
            self._antichess_board.push(move)

    def pop_move(self) -> chess.Move:
        """Pop a move from the game board and sync variant board if active."""
        move = self.game.pop()
        if self.variant == "3check" and self._threecheck_board is not None:
            try:
                self._threecheck_board.pop()
            except IndexError:
                pass  # History already empty
        elif self.variant == "atomic" and self._atomic_board is not None:
            try:
                self._atomic_board.pop()
            except IndexError:
                pass  # History already empty
        elif self.variant == "racingkings" and self._racingkings_board is not None:
            try:
                self._racingkings_board.pop()
            except IndexError:
                pass  # History already empty
        elif self.variant == "antichess" and self._antichess_board is not None:
            try:
                self._antichess_board.pop()
            except IndexError:
                pass  # History already empty
        return move

    def game_copy(self) -> chess.Board:
        """Return a copy of the game board with variant name attached.

        The _variant_name attribute allows the display layer to reconstruct
        the correct variant FEN (e.g. atomic explosions) from the move_stack.
        """
        copy = self.game.copy()
        if self.variant != "chess":
            copy._variant_name = self.variant
        return copy

    def engine_board_copy(self):
        """Return a board copy suitable for engine communication.

        For variants with a dedicated board (racingkings, atomic, 3check) return
        a copy of the variant board so that python-chess sends the correct
        UCI_Variant to the engine.  Falls back to self.game.copy().
        """
        vb = self.get_variant_board()
        if vb is not None:
            return vb.copy()
        return self.game.copy()

    def new_game_msg(self, newgame: bool):
        """Create a START_NEW_GAME message with variant info attached."""
        msg = Message.START_NEW_GAME(game=self.game_copy(), newgame=newgame)
        if self.variant != "chess":
            msg.variant = self.variant
        return msg

    def get_variant_board(self):
        """Return the variant-specific board, or None for standard chess.

        Returns the appropriate variant board object which can be used for:
        - Legal move generation (atomic has different rules)
        - FEN retrieval (atomic shows explosions, 3check has check counts)
        - Variant detection via class name in display layer
        """
        if self.variant == "atomic" and self._atomic_board is not None:
            return self._atomic_board
        elif self.variant == "3check" and self._threecheck_board is not None:
            return self._threecheck_board
        elif self.variant == "racingkings" and self._racingkings_board is not None:
            return self._racingkings_board
        elif self.variant == "antichess" and self._antichess_board is not None:
            return self._antichess_board
        # KOTH uses standard board with special win condition only
        return None

    def get_board_fen(self) -> str:
        """Return board FEN from variant board if active, otherwise from game.

        For atomic variant, this returns the position with explosions applied.
        For 3check, piece positions are identical to standard chess (included for consistency).
        """
        if self.variant == "atomic" and self._atomic_board is not None:
            return self._atomic_board.board_fen()
        elif self.variant == "3check" and self._threecheck_board is not None:
            return self._threecheck_board.board_fen()
        elif self.variant == "racingkings" and self._racingkings_board is not None:
            return self._racingkings_board.board_fen()
        elif self.variant == "antichess" and self._antichess_board is not None:
            return self._antichess_board.board_fen()
        return self.game.board_fen()

    def get_fen(self) -> str:
        """Return full FEN from variant board if active, otherwise from game.

        For atomic variant, this returns the position with explosions applied.
        This is the full FEN string (pieces + turn + castling + en passant + clocks).
        """
        if self.variant == "atomic" and self._atomic_board is not None:
            return self._atomic_board.fen()
        elif self.variant == "3check" and self._threecheck_board is not None:
            return self._threecheck_board.fen()
        elif self.variant == "racingkings" and self._racingkings_board is not None:
            return self._racingkings_board.fen()
        elif self.variant == "antichess" and self._antichess_board is not None:
            return self._antichess_board.fen()
        return self.game.fen()

    def reset_variant_board(self) -> None:
        """Reset the active variant board to starting position."""
        if self.variant == "3check" and self._threecheck_board is not None:
            self._threecheck_board.reset()
        elif self.variant == "atomic" and self._atomic_board is not None:
            self._atomic_board.reset()
        elif self.variant == "racingkings" and self._racingkings_board is not None:
            self._racingkings_board.reset()
        elif self.variant == "antichess" and self._antichess_board is not None:
            self._antichess_board.reset()

    def get_move_check_board(self):
        """Return the board to use for move legality checks.

        Returns the variant board (atomic/3check/racingkings/antichess) when
        active, otherwise the standard game board.  This is the single point
        of truth for 'which board object do I check legal_moves against?'.
        """
        return self.get_variant_board() or self.game

    async def start_clock(self) -> None:
        """Start the clock."""
        if self.interaction_mode in (
            Mode.NORMAL,
            Mode.BRAIN,
            Mode.OBSERVE,
            Mode.REMOTE,
            Mode.TRAINING,
        ):
            self.game_started = True
            self.time_control.start_internal(self.game.turn, self.main_loop)
            tc_init = self.time_control.get_parameters()
            if self.interaction_mode == Mode.TRAINING:
                pass
            else:
                await DisplayMsg.show(
                    Message.CLOCK_START(turn=self.game.turn, tc_init=tc_init, devs={"ser", "i2c", "web"})
                )
                await asyncio.sleep(0.5)
                # @todo give some time to clock to really do it. Check this solution!
        else:
            logger.warning("wrong function call [start]! mode: %s", self.interaction_mode)

    async def stop_clock(self, refund_seconds: float = 0.0) -> None:
        """Stop the clock."""
        if self.interaction_mode in (
            Mode.NORMAL,
            Mode.BRAIN,
            Mode.OBSERVE,
            Mode.REMOTE,
            Mode.TRAINING,
        ):
            self.time_control.stop_internal(refund_seconds=refund_seconds)
            if self.interaction_mode == Mode.TRAINING:
                pass
            else:
                await DisplayMsg.show(Message.CLOCK_STOP(devs={"ser", "i2c", "web"}))
                await asyncio.sleep(0.7)
                # @todo give some time to clock to really do it. Check this solution!
        else:
            # stop_clock is called once by read_pgn_file when going into PGNREPLAY mode
            if self.interaction_mode != Mode.PGNREPLAY:
                logger.warning("wrong function call [stop]! mode: %s", self.interaction_mode)

    def stop_fen_timer(self) -> None:
        """Stop the fen timer cause another fen string been send."""
        if self.fen_timer_running:
            self.fen_timer.stop()
            self.fen_timer_running = False

    def get_user_color(self):
        if self.play_mode == PlayMode.USER_BLACK:
            return chess.BLACK
        else:
            return chess.WHITE

    def is_user_turn(self) -> bool:
        """Return True if is users turn to move"""
        return (self.game.turn == chess.WHITE and self.play_mode == PlayMode.USER_WHITE) or (
            self.game.turn == chess.BLACK and self.play_mode == PlayMode.USER_BLACK
        )

    def is_not_user_turn(self) -> bool:
        """Return True if it is NOT users turn (only valid in normal, brain or remote mode)."""
        assert self.interaction_mode in (Mode.NORMAL, Mode.BRAIN, Mode.REMOTE, Mode.TRAINING), (
            "wrong mode: %s" % self.interaction_mode
        )
        condition1 = self.play_mode == PlayMode.USER_WHITE and self.game.turn == chess.BLACK
        condition2 = self.play_mode == PlayMode.USER_BLACK and self.game.turn == chess.WHITE
        return condition1 or condition2

    async def set_online_tctrl(self, game_time, fischer_inc) -> None:
        l_game_time = 0
        l_fischer_inc = 0

        logger.debug("molli online set_online_tctrl input %s %s", game_time, fischer_inc)
        l_game_time = int(game_time)
        l_fischer_inc = int(fischer_inc)
        await self.stop_clock()
        self.time_control.stop_internal(log=False)

        self.time_control = TimeControl()
        tc_init = self.time_control.get_parameters()

        if l_fischer_inc == 0:
            tc_init["mode"] = TimeMode.BLITZ
            tc_init["blitz"] = l_game_time
            tc_init["fischer"] = 0
        else:
            tc_init["mode"] = TimeMode.FISCHER
            tc_init["blitz"] = l_game_time
            tc_init["fischer"] = l_fischer_inc

        tc_init["blitz2"] = 0
        tc_init["moves_to_go"] = 0

        lt_white = l_game_time * 60 + l_fischer_inc
        lt_black = l_game_time * 60 + l_fischer_inc
        tc_init["internal_time"] = {chess.WHITE: lt_white, chess.BLACK: lt_black}

        self.time_control = TimeControl(**tc_init)
        text = self.dgttranslate.text("N00_oktime")
        msg = Message.TIME_CONTROL(time_text=text, show_ok=True, tc_init=tc_init)
        await DisplayMsg.show(msg)
        self.stop_fen_timer()

    def check_game_state(self):
        """
        Check if the game has ended or not ; it also sends Message to Displays if the game has ended.

        :param game:
        :param play_mode:
        :return: False is the game continues, Game_Ends() Message if it has ended
        """
        # Check 3check variant win condition first
        if self.variant == "3check" and self._threecheck_board is not None:
            if self._threecheck_board.is_variant_end():
                tc_result = self._threecheck_board.result()
                if tc_result == "1-0":
                    result = GameResult.THREE_CHECK_WHITE
                elif tc_result == "0-1":
                    result = GameResult.THREE_CHECK_BLACK
                else:
                    result = GameResult.DRAW
                return Message.GAME_ENDS(
                    tc_init=self.time_control.get_parameters(),
                    result=result,
                    play_mode=self.play_mode,
                    game=self.game_copy(),
                    mode=self.interaction_mode,
                )

        # Check King of the Hill variant win condition
        if self.variant == "kingofthehill":
            koth_center = {chess.D4, chess.D5, chess.E4, chess.E5}
            # Check if either king is in the center (win for that player)
            white_king = self.game.king(chess.WHITE)
            black_king = self.game.king(chess.BLACK)
            if white_king in koth_center:
                return Message.GAME_ENDS(
                    tc_init=self.time_control.get_parameters(),
                    result=GameResult.KOTH_WHITE,
                    play_mode=self.play_mode,
                    game=self.game_copy(),
                    mode=self.interaction_mode,
                )
            if black_king in koth_center:
                return Message.GAME_ENDS(
                    tc_init=self.time_control.get_parameters(),
                    result=GameResult.KOTH_BLACK,
                    play_mode=self.play_mode,
                    game=self.game_copy(),
                    mode=self.interaction_mode,
                )

        # Check Atomic variant win condition (king exploded)
        if self.variant == "atomic" and self._atomic_board is not None:
            white_king = self._atomic_board.king(chess.WHITE)
            black_king = self._atomic_board.king(chess.BLACK)
            if white_king is None:
                return Message.GAME_ENDS(
                    tc_init=self.time_control.get_parameters(),
                    result=GameResult.ATOMIC_BLACK,
                    play_mode=self.play_mode,
                    game=self.game_copy(),
                    mode=self.interaction_mode,
                )
            if black_king is None:
                return Message.GAME_ENDS(
                    tc_init=self.time_control.get_parameters(),
                    result=GameResult.ATOMIC_WHITE,
                    play_mode=self.play_mode,
                    game=self.game_copy(),
                    mode=self.interaction_mode,
                )

        # Check Racing Kings variant win condition (king reaches 8th rank)
        if self.variant == "racingkings" and self._racingkings_board is not None:
            if self._racingkings_board.is_variant_end():
                rk_result = self._racingkings_board.result()
                if rk_result == "1-0":
                    result = GameResult.RK_WHITE
                elif rk_result == "0-1":
                    result = GameResult.RK_BLACK
                else:
                    result = GameResult.DRAW
                return Message.GAME_ENDS(
                    tc_init=self.time_control.get_parameters(),
                    result=result,
                    play_mode=self.play_mode,
                    game=self.game_copy(),
                    mode=self.interaction_mode,
                )

        # Check Antichess variant win condition (lost all pieces or stalemated)
        if self.variant == "antichess" and self._antichess_board is not None:
            if self._antichess_board.is_variant_end():
                ac_result = self._antichess_board.result()
                if ac_result == "1-0":
                    result = GameResult.ANTICHESS_WHITE
                elif ac_result == "0-1":
                    result = GameResult.ANTICHESS_BLACK
                else:
                    result = GameResult.DRAW
                return Message.GAME_ENDS(
                    tc_init=self.time_control.get_parameters(),
                    result=result,
                    play_mode=self.play_mode,
                    game=self.game_copy(),
                    mode=self.interaction_mode,
                )

        # Standard game end conditions
        # For variant boards with different rules, use variant board for correct state
        if self.variant == "atomic" and self._atomic_board:
            check_board = self._atomic_board
        elif self.variant == "racingkings" and self._racingkings_board:
            check_board = self._racingkings_board
        elif self.variant == "antichess" and self._antichess_board:
            check_board = self._antichess_board
        else:
            check_board = self.game
        if check_board.is_stalemate():
            if self.variant == "antichess":
                # In antichess, the stalemated player wins
                if check_board.turn == chess.BLACK:
                    result = GameResult.ANTICHESS_BLACK
                else:
                    result = GameResult.ANTICHESS_WHITE
            else:
                result = GameResult.STALEMATE
        elif check_board.is_insufficient_material():
            result = GameResult.INSUFFICIENT_MATERIAL
        elif check_board.is_seventyfive_moves():
            result = GameResult.SEVENTYFIVE_MOVES
        elif check_board.is_fivefold_repetition():
            result = GameResult.FIVEFOLD_REPETITION
        elif check_board.is_checkmate():
            result = GameResult.MATE
        else:
            return False

        return Message.GAME_ENDS(
            tc_init=self.time_control.get_parameters(),
            result=result,
            play_mode=self.play_mode,
            game=self.game_copy(),
            mode=self.interaction_mode,
        )

    @staticmethod
    def _num(time_str) -> int:
        try:
            value = int(time_str)
            if value > 999:
                value = 999
            return value
        except ValueError:
            return 1

    async def transfer_time(self, time_list: list, depth=0, node=0):
        """Transfer the time list to a TimeControl Object and a Text Object."""
        i_depth = self._num(depth)
        i_node = self._num(node)

        if i_depth > 0:
            fixed = 671
            timec = TimeControl(TimeMode.FIXED, fixed=fixed, depth=i_depth)
            textc = self.dgttranslate.text("B00_tc_depth", timec.get_list_text())
        elif i_node > 0:
            fixed = 671
            timec = TimeControl(TimeMode.FIXED, fixed=fixed, node=i_node)
            textc = self.dgttranslate.text("B00_tc_node", timec.get_list_text())
        elif len(time_list) == 1:
            fixed = self._num(time_list[0])
            timec = TimeControl(TimeMode.FIXED, fixed=fixed)
            textc = self.dgttranslate.text("B00_tc_fixed", timec.get_list_text())
        elif len(time_list) == 2:
            blitz = self._num(time_list[0])
            fisch = self._num(time_list[1])
            if fisch == 0:
                timec = TimeControl(TimeMode.BLITZ, blitz=blitz)
                textc = self.dgttranslate.text("B00_tc_blitz", timec.get_list_text())
            else:
                timec = TimeControl(TimeMode.FISCHER, blitz=blitz, fischer=fisch)
                textc = self.dgttranslate.text("B00_tc_fisch", timec.get_list_text())
        elif len(time_list) == 3:
            moves_to_go = self._num(time_list[0])
            blitz = self._num(time_list[1])
            blitz2 = self._num(time_list[2])
            if blitz2 == 0:
                timec = TimeControl(TimeMode.BLITZ, blitz=blitz, moves_to_go=moves_to_go, blitz2=blitz2)
                textc = self.dgttranslate.text("B00_tc_tourn", timec.get_list_text())
            else:
                fisch = blitz2
                blitz2 = 0
                timec = TimeControl(
                    TimeMode.FISCHER,
                    blitz=blitz,
                    fischer=fisch,
                    moves_to_go=moves_to_go,
                    blitz2=blitz2,
                )
                textc = self.dgttranslate.text("B00_tc_tourn", timec.get_list_text())
        elif len(time_list) == 4:
            moves_to_go = self._num(time_list[0])
            blitz = self._num(time_list[1])
            fisch = self._num(time_list[2])
            blitz2 = self._num(time_list[3])
            if fisch == 0:
                timec = TimeControl(TimeMode.BLITZ, blitz=blitz, moves_to_go=moves_to_go, blitz2=blitz2)
                textc = self.dgttranslate.text("B00_tc_tourn", timec.get_list_text())
            else:
                timec = TimeControl(
                    TimeMode.FISCHER,
                    blitz=blitz,
                    fischer=fisch,
                    moves_to_go=moves_to_go,
                    blitz2=blitz2,
                )
                textc = self.dgttranslate.text("B00_tc_tourn", timec.get_list_text())
        else:
            timec = TimeControl(TimeMode.BLITZ, blitz=5)
            textc = self.dgttranslate.text("B00_tc_blitz", timec.get_list_text())
        return timec, textc
