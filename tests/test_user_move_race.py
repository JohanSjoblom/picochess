#!/usr/bin/env python3

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import chess

import mainloop
from dgt.util import EBoard, Mode, PicoCoach


class TestUserMoveRace(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Position immediately before the Bxe6 capture reported in issue #555.
        self.board = chess.Board(
            "r4rk1/2pp1ppp/p3n3/1p3b2/3q4/P3R3/BP3QPP/6K1 w - - 0 25"
        )
        self.move = chess.Move.from_uci("a2e6")
        self.push_move = Mock(side_effect=self.board.push)
        self.time_control = SimpleNamespace(
            add_time=Mock(),
            add_game2=Mock(),
            sub_online_time=Mock(),
            moves_to_go_orig=0,
            game_time=0,
            game_time2=0,
        )
        self.state = SimpleNamespace(
            take_back_locked=True,
            interaction_mode=Mode.NORMAL,
            game_declared=False,
            game=self.board,
            get_move_check_board=lambda: self.board,
            get_fen=self.board.fen,
            push_move=self.push_move,
            dgtmenu=SimpleNamespace(get_picocoach=Mock(return_value=PicoCoach.COACH_OFF)),
            brain_required_piece_type=None,
            hand_coach_task=None,
            user_move_revision=0,
            engine_search_revision=7,
            done_computer_fen=None,
            pb_move=chess.Move.null(),
            time_control=self.time_control,
            online_decrement=0,
            best_sent_depth=Mock(),
            searchmoves=SimpleNamespace(reset=Mock()),
            done_move=chess.Move.null(),
            ignore_next_engine_move=False,
            position_mode=False,
            check_game_state=Mock(return_value=False),
            game_generation=0,
            last_move=chess.Move.null(),
            takeback_active=False,
            automatic_takeback=False,
            is_not_user_turn=lambda: self.board.turn == chess.BLACK,
        )
        self.controller = object.__new__(mainloop.MainLoop)
        self.controller.state = self.state
        self.controller._user_move_commit_lock = asyncio.Lock()
        self.controller.board_type = EBoard.NOEBOARD
        self.controller._release_coach_position_mode_for_move = Mock()
        self.controller.cancel_brain_hint_timer = Mock()
        self.controller.eng_plays = Mock(return_value=True)
        self.controller.online_mode = Mock(return_value=False)
        self.controller.emulation_mode = Mock(return_value=False)
        self.controller.picotutor_mode = Mock(return_value=False)
        self.controller._set_game_started = Mock()
        self.controller._update_variant_shared = Mock()
        self.controller._publish_analysis_events_for_position = AsyncMock()
        self.controller._deliver_picotutor_messages = AsyncMock()
        self.controller._announce_user_move_before_search = AsyncMock(return_value=False)
        self.controller._think_after_current_user_move = AsyncMock(return_value=True)
        self.controller._current_opening_message = Mock(return_value=None)
        self.controller.analyse = AsyncMock()
        self.controller.pgn_mode = Mock(return_value=False)
        self.controller.set_picotutor_position = AsyncMock()

        self.game_ending = patch.object(mainloop.ModeInfo, "get_game_ending", return_value="*")
        self.show = patch.object(mainloop.DisplayMsg, "show", new=AsyncMock())
        self.game_ending.start()
        self.show.start()
        self.addCleanup(self.game_ending.stop)
        self.addCleanup(self.show.stop)

    async def _wait_for_revision(self, revision):
        for _ in range(100):
            if self.state.user_move_revision == revision:
                return
            await asyncio.sleep(0)
        self.fail(f"user move revision did not reach {revision}")

    async def test_newest_move_waits_for_lock_and_is_the_only_commit(self):
        stop_started = asyncio.Event()
        release_stop = asyncio.Event()
        stop_calls = 0
        active_stops = 0
        max_active_stops = 0

        async def delayed_stop(*, ponder_hit=False):
            nonlocal stop_calls, active_stops, max_active_stops
            stop_calls += 1
            active_stops += 1
            max_active_stops = max(max_active_stops, active_stops)
            try:
                if stop_calls == 1:
                    stop_started.set()
                    await release_stop.wait()
                return mainloop.SearchStopOutcome()
            finally:
                active_stops -= 1

        self.controller.stop_search_and_clock_with_outcome = delayed_stop

        older = asyncio.create_task(self.controller.user_move(self.move, sliding=False))
        await stop_started.wait()
        newer = asyncio.create_task(self.controller.user_move(self.move, sliding=False))
        await self._wait_for_revision(2)

        self.assertFalse(newer.done())
        self.assertEqual(1, stop_calls)
        release_stop.set()

        self.assertEqual([True, True], await asyncio.gather(older, newer))
        self.assertEqual(2, stop_calls)
        self.assertEqual(1, max_active_stops)
        self.push_move.assert_called_once_with(self.move)
        self.time_control.add_time.assert_called_once_with(chess.WHITE)
        self.controller._think_after_current_user_move.assert_awaited_once()
        self.assertEqual([self.move], self.board.move_stack)
        self.assertFalse(hasattr(self.state, "error_fen"))

    async def test_task_superseded_during_analysis_never_stops_or_mutates_cache(self):
        self.state.interaction_mode = Mode.PONDER
        self.controller.eng_plays.return_value = False
        self.controller.is_coach_analyser = Mock(return_value=False)
        first_analysis_started = asyncio.Event()
        release_first_analysis = asyncio.Event()
        analysis_calls = 0
        source_fen = self.board.fen()

        async def get_analysis(_game):
            nonlocal analysis_calls
            analysis_calls += 1
            if analysis_calls == 1:
                first_analysis_started.set()
                await release_first_analysis.wait()
                return {
                    "info": [{"depth": 12, "pv": [self.move, chess.Move.from_uci("g8h8")]}],
                    "fen": source_fen,
                }
            return {"info": None, "fen": source_fen}

        self.controller.engine = SimpleNamespace(get_analysis=get_analysis)
        self.controller.send_analyse = AsyncMock(return_value=[])
        self.controller.stop_search_and_clock_with_outcome = AsyncMock(
            return_value=mainloop.SearchStopOutcome()
        )

        older = asyncio.create_task(self.controller.user_move(self.move, sliding=False))
        await first_analysis_started.wait()
        newer = asyncio.create_task(self.controller.user_move(self.move, sliding=False))
        await self._wait_for_revision(2)
        await newer
        release_first_analysis.set()

        self.assertTrue(await older)
        self.push_move.assert_called_once_with(self.move)
        self.controller.stop_search_and_clock_with_outcome.assert_awaited_once()
        self.controller.send_analyse.assert_not_awaited()
        self.state.best_sent_depth.reset.assert_called_once_with()
        self.controller.analyse.assert_awaited_once_with()
        self.assertEqual(chess.Move.null(), self.state.pb_move)

    async def test_newest_analysis_hit_owns_the_cached_ponder_move(self):
        self.state.interaction_mode = Mode.PONDER
        self.controller.eng_plays.return_value = False
        self.controller.is_coach_analyser = Mock(return_value=False)
        first_analysis_started = asyncio.Event()
        release_first_analysis = asyncio.Event()
        source_fen = self.board.fen()
        older_reply = chess.Move.from_uci("g8h8")
        newer_reply = chess.Move.from_uci("g8f7")
        analysis_calls = 0

        async def get_analysis(_game):
            nonlocal analysis_calls
            analysis_calls += 1
            if analysis_calls == 1:
                first_analysis_started.set()
                await release_first_analysis.wait()
                reply = older_reply
            else:
                reply = newer_reply
            return {
                "info": [{"depth": 12, "pv": [self.move, reply]}],
                "fen": source_fen,
            }

        self.controller.engine = SimpleNamespace(get_analysis=get_analysis)
        self.controller.stop_search_and_clock_with_outcome = AsyncMock(
            return_value=mainloop.SearchStopOutcome()
        )

        older = asyncio.create_task(self.controller.user_move(self.move, sliding=False))
        await first_analysis_started.wait()
        newer = asyncio.create_task(self.controller.user_move(self.move, sliding=False))
        await self._wait_for_revision(2)
        await newer
        release_first_analysis.set()

        self.assertTrue(await older)
        self.push_move.assert_called_once_with(self.move)
        self.controller.stop_search_and_clock_with_outcome.assert_awaited_once()
        self.assertEqual(newer_reply, self.state.pb_move)
        self.state.best_sent_depth.set_best.assert_called_once()

    async def test_incomplete_stop_keeps_existing_move_acceptance_behavior(self):
        self.controller.stop_search_and_clock_with_outcome = AsyncMock(
            return_value=mainloop.SearchStopOutcome(
                analysis_stop_completed=False,
                forced_analyser_stop=True,
                engine_idle=None,
            )
        )

        self.assertTrue(await self.controller.user_move(self.move, sliding=False))

        self.push_move.assert_called_once_with(self.move)
        self.time_control.add_time.assert_called_once_with(chess.WHITE)
        self.controller._think_after_current_user_move.assert_awaited_once()

    async def _assert_pending_move_is_committed(self, mode, move):
        announced_position = self.board.copy()
        announced_position.push(self.move)
        self.state.interaction_mode = mode
        self.state.done_move = self.move
        self.state.done_computer_fen = announced_position.board_fen()
        self.controller.stop_search_and_clock_with_outcome = AsyncMock(
            return_value=mainloop.SearchStopOutcome()
        )

        self.assertTrue(await self.controller.user_move(move, sliding=False))

        self.push_move.assert_called_once_with(move)
        self.controller.stop_search_and_clock_with_outcome.assert_awaited_once()
        self.assertIsNone(self.state.done_computer_fen)
        self.assertEqual(chess.Move.null(), self.state.done_move)

    async def test_training_executes_announced_pending_move(self):
        await self._assert_pending_move_is_committed(Mode.TRAINING, self.move)

    async def test_training_replaces_announced_pending_move(self):
        await self._assert_pending_move_is_committed(
            Mode.TRAINING, chess.Move.from_uci("a2b3")
        )

    async def test_pgn_replay_executes_announced_pending_move(self):
        await self._assert_pending_move_is_committed(Mode.PGNREPLAY, self.move)

    async def test_pgn_replay_replaces_announced_pending_move(self):
        await self._assert_pending_move_is_committed(
            Mode.PGNREPLAY, chess.Move.from_uci("a2b3")
        )

    def _publish_best_move_while_stopping(self, engine_move):
        waiting = False
        self.controller.board_type = EBoard.DGT
        self.state.get_board_fen = self.board.board_fen
        self.state.get_variant_board = Mock(return_value=None)
        self.state.game_copy = self.board.copy
        self.state.stop_clock = AsyncMock()
        self.state.start_clock = AsyncMock()
        self.state.time_control.internal_running = Mock(return_value=False)
        self.state.time_control.get_parameters = Mock(return_value={})
        self.state.searchmoves.exclude = Mock()
        self.state.legal_fens = []
        self.state.last_legal_fens = []
        self.state.legal_fens_after_cmove = []
        self.state.flag_startup = True
        self.state.best_move_posted = False
        self.state.engine_move_was_book = False
        self.state.newgame_happened = False
        self.state.variant = "chess"
        self.state.error_fen = None
        self.state.fen_error_occured = False
        self.state.position_checkpoint_restore_pending = False
        self.state.set_position_ack_target_fen = None
        self.state.play_mode = mainloop.PlayMode.USER_WHITE
        self.state.stop_fen_timer = Mock()
        self.state.is_not_user_turn = Mock(return_value=True)
        self.state.pop_move = Mock(side_effect=self.board.pop)
        self.state.dgtmenu.get_flip_board = Mock(return_value=True)
        self.controller.start_fen_timer = Mock()

        async def wait_until_idle(_timeout):
            nonlocal waiting
            await self.controller.process_main_events(
                mainloop.Event.BEST_MOVE(
                    move=engine_move,
                    ponder=None,
                    inbook=False,
                    fen=self.state.get_fen(),
                    search_revision=7,
                )
            )
            waiting = True
            return True

        self.controller.engine = Mock()
        self.controller.engine.is_thinking.return_value = True
        self.controller.engine.is_waiting.side_effect = lambda: waiting
        self.controller.engine.stop_with_outcome = AsyncMock(
            return_value=SimpleNamespace(completed=True, forced=False)
        )
        self.controller.engine.wait_until_idle = AsyncMock(side_effect=wait_until_idle)

    async def test_training_move_owns_result_released_by_its_engine_stop(self):
        self.state.interaction_mode = Mode.TRAINING
        self._publish_best_move_while_stopping(self.move)

        self.assertTrue(await self.controller.user_move(self.move, sliding=False))

        self.push_move.assert_called_once_with(self.move)
        self.assertIsNone(self.state.done_computer_fen)
        self.assertEqual(chess.Move.null(), self.state.done_move)
        self.assertEqual(8, self.state.engine_search_revision)

    async def test_sliding_replacement_owns_result_released_by_earlier_stop(self):
        replacement = chess.Move.from_uci("a2b3")
        alternatives = mainloop.compute_legal_fens(self.board)
        replacement_fen = alternatives[list(self.board.legal_moves).index(replacement)]
        self.state.last_legal_fens = alternatives
        self.state.take_back_locked = False
        self.board.push(self.move)
        self._publish_best_move_while_stopping(chess.Move.from_uci("g8h8"))
        self.state.last_legal_fens = alternatives

        await self.controller.process_fen(replacement_fen, self.state)

        self.push_move.assert_called_once_with(replacement)
        self.assertEqual(replacement, self.board.peek())
        self.assertIsNone(self.state.done_computer_fen)
        self.assertEqual(chess.Move.null(), self.state.done_move)
        self.controller.start_fen_timer.assert_not_called()

    async def _commit_analysis_hit(self, outcome):
        self.state.interaction_mode = Mode.PONDER
        self.controller.eng_plays.return_value = False
        self.controller.is_coach_analyser = Mock(return_value=False)
        reply = chess.Move.from_uci("g8h8")
        self.controller.engine = SimpleNamespace(
            get_analysis=AsyncMock(
                return_value={
                    "info": [{"depth": 12, "pv": [self.move, reply]}],
                    "fen": self.board.fen(),
                }
            )
        )
        self.controller.stop_search_and_clock_with_outcome = AsyncMock(
            return_value=outcome
        )

        self.assertTrue(await self.controller.user_move(self.move, sliding=False))
        return reply

    async def test_completed_forced_stop_keeps_ponder_but_clears_depth_cache(self):
        reply = await self._commit_analysis_hit(
            mainloop.SearchStopOutcome(
                analysis_stop_completed=True,
                forced_analyser_stop=True,
                engine_idle=True,
            )
        )

        self.assertEqual(reply, self.state.pb_move)
        self.state.best_sent_depth.set_best.assert_called_once()
        self.state.best_sent_depth.reset.assert_called_once_with()

    async def test_incomplete_forced_stop_keeps_existing_analysis_cache_behavior(self):
        reply = await self._commit_analysis_hit(
            mainloop.SearchStopOutcome(
                analysis_stop_completed=False,
                forced_analyser_stop=True,
                engine_idle=None,
            )
        )

        self.assertEqual(reply, self.state.pb_move)
        self.state.best_sent_depth.set_best.assert_called_once()
        self.state.best_sent_depth.reset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
