"""Exercise Set Pos acknowledgement interleavings without starting hardware."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import chess

import mainloop
from dgt.util import EBoard, Mode, PlayMode
from dgt.api import Event


class TestSetPositionAck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        names = {"_clear_set_position_ack", "_begin_set_position_ack",
                 "_finish_set_position_ack", "process_fen", "process_main_events"}
        self.show = AsyncMock()
        self.sleep = AsyncMock()
        show_patch = patch.object(mainloop.DisplayMsg, "show", self.show)
        show_patch.start()
        self.addCleanup(show_patch.stop)
        sleep_patch = patch.object(mainloop.asyncio, "sleep", self.sleep)
        sleep_patch.start()
        self.addCleanup(sleep_patch.stop)
        controller_type = type(
            "AckController",
            (),
            {name: getattr(mainloop.MainLoop, name) for name in names},
        )
        self.controller = controller_type()
        self.board = chess.Board()
        self.board.push_uci("e2e4")
        self.target = self.board.board_fen()
        self.state = SimpleNamespace(
            game=self.board, get_board_fen=self.board.board_fen,
            get_move_check_board=lambda: self.board, get_variant_board=lambda: None,
            set_position_ack_target_fen=self.target, set_position_ack_pending=True,
            set_position_ack_ready=True, stop_fen_timer=Mock(), position_mode=False,
            position_checkpoint_restore_pending=False, variant="chess", game_started=False,
            last_legal_fens=[], legal_fens=mainloop.compute_legal_fens(self.board),
            done_computer_fen=None, interaction_mode=Mode.NORMAL, game_generation=0,
        )
        self.controller.state = self.state
        self.controller.board_type = EBoard.CERTABO
        self.controller.engine = SimpleNamespace(has_chess960=lambda: False, is_mame_engine=lambda: False)
        self.controller.reset_setpieces_window_switch = Mock()

    async def test_recovery_events_clear_setup_before_engine_work(self):
        class EngineWorkFailed(Exception):
            pass

        self.controller._clear_position_checkpoint = Mock()
        self.controller.shared = {}

        async def engine_work():
            self.assertEqual("", self.state.set_position_ack_target_fen)
            self.assertFalse(self.state.set_position_ack_pending)
            self.assertFalse(self.state.set_position_ack_ready)
            self.assertIsNone(self.state.error_fen)
            self.state.stop_fen_timer.assert_called_once()
            raise EngineWorkFailed()

        self.controller.get_rid_of_engine_move = AsyncMock(side_effect=engine_work)
        for event in (Event.NEW_GAME(pos960=518), Event.NEW_ENGINE()):
            with self.subTest(event=type(event).__name__):
                self.state.set_position_ack_target_fen = self.target
                self.state.set_position_ack_pending = True
                self.state.set_position_ack_ready = True
                self.state.error_fen = chess.STARTING_BOARD_FEN
                self.state.stop_fen_timer.reset_mock()
                with self.assertRaises(EngineWorkFailed):
                    await self.controller.process_main_events(event)
                # A failed engine operation must not bring the setup guard back.
                self.assertEqual("", self.state.set_position_ack_target_fen)
                await self.controller._finish_set_position_ack(self.target)
                self.show.assert_not_awaited()

    async def test_mame_new_game_discards_search_before_force_move_path(self):
        class NewGamePrepared(Exception):
            pass

        self.controller._clear_position_checkpoint = Mock()
        self.controller.shared = {}
        self.state.engine_search_revision = 0
        self.controller._invalidate_engine_search_results = (
            mainloop.MainLoop._invalidate_engine_search_results.__get__(self.controller)
        )
        self.controller.get_rid_of_engine_move = (
            mainloop.MainLoop.get_rid_of_engine_move.__get__(self.controller)
        )
        self.controller.eng_plays = lambda: True
        self.controller._set_game_started = Mock(side_effect=NewGamePrepared)
        thinking = True

        async def discard_search():
            nonlocal thinking
            thinking = False
            return True

        self.controller.engine = SimpleNamespace(
            is_mame_engine=lambda: True, is_thinking=lambda: thinking,
            discard_search_for_mame_reset=AsyncMock(side_effect=discard_search),
            force_move=Mock(),
        )
        with self.assertRaises(NewGamePrepared):
            await self.controller.process_main_events(Event.NEW_GAME(pos960=518))
        self.controller.engine.discard_search_for_mame_reset.assert_awaited_once_with()
        self.controller.engine.force_move.assert_not_called()
        self.assertEqual(1, self.state.engine_search_revision)

    async def test_mame_new_game_resets_search_at_untouched_start_position(self):
        class EngineReset(Exception):
            pass

        controller = object.__new__(mainloop.MainLoop)
        controller.shared = {}
        controller.state = Mock(
            game=chess.Board(), game_generation=0, engine_search_revision=0,
            interaction_mode=Mode.NORMAL, play_mode=PlayMode.USER_WHITE,
            best_move_posted=False, done_computer_fen=None, game_declared=False,
            variant="chess", stop_clock=AsyncMock(),
        )
        controller._clear_set_position_ack = Mock()
        controller._clear_position_checkpoint = Mock()
        controller._set_game_started = Mock()
        controller._set_pgn_replay_autoplay = Mock()
        controller._reset_loaded_pgn_lifecycle = Mock()
        controller.reset_setpieces_window_switch = Mock()
        controller._update_variant_shared = Mock()
        controller.game_end_event = Mock()
        controller.eng_plays = lambda: True
        controller.emulation_mode = lambda: True
        controller.pgn_mode = lambda: False
        controller.online_mode = lambda: False
        thinking = True

        async def discard_search():
            nonlocal thinking
            thinking = False
            return True

        controller.engine = SimpleNamespace(
            is_mame_engine=lambda: True, is_thinking=lambda: thinking,
            is_waiting=lambda: not thinking, has_chess960=lambda: False,
            discard_search_for_mame_reset=AsyncMock(side_effect=discard_search),
            force_move=Mock(), newgame=AsyncMock(side_effect=EngineReset),
        )
        with patch.object(mainloop.ModeInfo, "get_game_ending", return_value="*"):
            with self.assertRaises(EngineReset):
                await controller.process_main_events(Event.NEW_GAME(pos960=518))
        controller.engine.newgame.assert_awaited_once()
        controller.engine.force_move.assert_not_called()

    async def test_legal_move_at_ok_is_accepted_and_ack_is_not_repeated(self):
        move = chess.Move.from_uci("e7e5")
        moved = self.board.copy()
        moved.push(move)
        legal_fens_before_move = list(self.state.legal_fens)

        async def accept_move(move, sliding, legal_fens_before_move):
            self.board.push(move)
            return True

        self.controller.user_move = AsyncMock(side_effect=accept_move)

        async def on_ok(message):
            self.assertEqual("POSOK", message.eval_str)
            self.assertFalse(hasattr(message, "game"))
            await self.controller.process_fen(moved.board_fen(), self.state)
            await self.controller._finish_set_position_ack(self.target)

        self.show.side_effect = on_ok
        await self.controller._finish_set_position_ack(self.target)

        self.controller.user_move.assert_awaited_once_with(
            move,
            sliding=False,
            legal_fens_before_move=legal_fens_before_move,
        )
        self.assertEqual(moved.fen(), self.board.fen())
        self.assertEqual(moved.move_stack, self.board.move_stack)
        self.show.assert_awaited_once()
        self.assertFalse(self.state.set_position_ack_pending)
        self.assertEqual("", self.state.set_position_ack_target_fen)

    async def test_old_ack_sleep_does_not_clear_new_setup_for_same_target(self):
        async def during_sleep(delay):
            self.controller._begin_set_position_ack(self.target, chess.STARTING_BOARD_FEN)

        self.sleep.side_effect = during_sleep
        await self.controller._finish_set_position_ack(self.target)

        self.assertTrue(self.state.set_position_ack_pending)
        self.assertEqual(self.target, self.state.set_position_ack_target_fen)
        self.assertFalse(self.state.set_position_ack_ready)
