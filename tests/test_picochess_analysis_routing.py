import ast
import unittest
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

import chess
import chess.engine
import chess.variant

import mainloop
from analysis_policy import (
    AnalysisCycleAction,
    AnalysisCycleContext,
    AnalysisSourceAction,
    AnalysisSourceContext,
    GameEndAnalysisContext,
    TutorAnalysisContext,
    decide_analysis_cycle_action,
    decide_analysis_source,
    decide_game_end_analysis_stop,
    decide_tutor_analysis,
    selected_engine_analysis_multipv,
    should_stop_analysis_after_game_end,
    tutor_analysis_allowed_in_mode,
)
from analysis_depth import depth_gated_analysis_info, selected_engine_analysis_depth
from web_analysis import web_analysis_payload
from board_position import board_fen_after_move, previous_position_matching_board_fen
from position_setup import (
    RK_STARTING_BOARD_FEN,
    loaded_pgn_interaction_mode,
    mame_requires_fresh_fen_root,
    pending_set_position_fen_action,
    pgn_with_board_as_fresh_root,
    set_position_new_game_code,
    setup_position_game,
    should_load_pgn_moves,
    should_preserve_loaded_pgn_history,
    should_preserve_set_position_history,
)
from move_policy import (
    analysis_event_matches_position,
    engine_move_event_matches_state,
    remote_move_matches_current_position,
    should_block_takeback,
    should_process_sliding_move,
    should_reject_user_move_after_game_end,
    should_resume_clock_after_rejected_engine_move,
    should_resume_game_after_takeback,
    should_show_setpieces_after_lift_timeout,
    user_move_pre_search_messages,
    user_move_task_matches_position,
)

from dgt.api import Event, EventApi, Message
from dgt.util import Mode
from mainloop import (
    rollback_picotutor_for_alternative,
    should_report_local_timeout,
)
from picostate import PicochessState


def start_patch(test_case, target, attribute, replacement):
    patcher = patch.object(target, attribute, replacement)
    patcher.start()
    test_case.addCleanup(patcher.stop)


class TestLocalTimeoutPolicy(unittest.TestCase):
    def test_local_timeout_is_reported(self):
        self.assertTrue(should_report_local_timeout(False))

    def test_online_timeout_is_left_to_server(self):
        self.assertFalse(should_report_local_timeout(True))

    def test_local_timeout_is_reported_only_once(self):
        self.assertFalse(should_report_local_timeout(False, already_reported=True))


class TestRepeatedLocalTimeoutHandling(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.show = AsyncMock()
        start_patch(self, mainloop.DisplayMsg, "show", self.show)
        start_patch(
            self,
            mainloop.ModeInfo,
            "get_online_mode",
            Mock(return_value=False),
        )
        self.controller = object.__new__(mainloop.MainLoop)
        self.controller.state = SimpleNamespace(
            position_checkpoint_restore_pending=False,
            stop_clock=AsyncMock(),
            local_timeout_reported=False,
        )

    async def test_only_first_local_flag_fall_is_reported(self):
        event = Event.OUT_OF_TIME(color=chess.WHITE)

        await self.controller.process_main_events(event)
        await self.controller.process_main_events(event)

        self.assertEqual(1, self.controller.state.stop_clock.await_count)
        self.assertEqual(1, self.show.await_count)
        self.assertTrue(self.controller.state.local_timeout_reported)
        self.assertTrue(
            all(
                isinstance(args[0], Message.LOST_ON_TIME)
                for args, _ in self.show.await_args_list
            )
        )


class TestNewGameHistoryLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_new_game_invalidates_preserved_history_before_move_cleanup(self):
        controller = object.__new__(mainloop.MainLoop)
        old_scope = {"gameid": "old", "revision": 1}
        controller.shared = {
            "preserved_mame_history": {"pgn": "1. e4 *"},
            "web_history_scope": old_scope,
        }
        controller.state = SimpleNamespace(position_checkpoint_restore_pending=False)
        controller.state.local_timeout_reported = True
        controller._clear_set_position_ack = Mock()
        controller._clear_position_checkpoint = Mock()

        class StopAfterHistoryCheck(Exception):
            pass

        async def check_history_before_continuing():
            self.assertNotIn("preserved_mame_history", controller.shared)
            self.assertNotEqual(old_scope, controller.shared["web_history_scope"])
            self.assertFalse(controller.state.local_timeout_reported)
            raise StopAfterHistoryCheck

        controller.get_rid_of_engine_move = check_history_before_continuing

        with self.assertRaises(StopAfterHistoryCheck):
            await controller.process_main_events(Event.NEW_GAME(pos960=518))


class TestPicochessAnalysisRouting(unittest.TestCase):
    def test_takeback_scan_returns_nearest_earlier_repeated_position(self):
        game = chess.Board()
        knight_cycle = ("g1f3", "g8f6", "f3g1", "f6g8")
        for move in knight_cycle * 2:
            game.push_uci(move)

        previous = previous_position_matching_board_fen(game, chess.STARTING_BOARD_FEN)

        self.assertIsNotNone(previous)
        self.assertEqual(4, len(previous.move_stack))
        self.assertEqual(chess.STARTING_BOARD_FEN, previous.board_fen())

    def test_takeback_scan_does_not_match_current_or_unknown_position(self):
        game = chess.Board()
        game.push_uci("e2e4")

        self.assertIsNone(
            previous_position_matching_board_fen(game, game.board_fen())
        )
        self.assertIsNone(
            previous_position_matching_board_fen(game, "8/8/8/8/8/8/8/8")
        )

    def test_depth_gate_passes_first_line_and_preserves_the_original_list(self):
        best_seen_depth = Mock()
        best_seen_depth.is_better.return_value = True
        game = chess.Board()
        info_list = [{"depth": 12}, {"depth": 11}]

        result = depth_gated_analysis_info(best_seen_depth, info_list, game.fen(), game)

        self.assertIs(info_list, result)
        best_seen_depth.is_better.assert_called_once_with(info_list[0], game.fen(), game)

    def test_depth_gate_suppresses_rejected_analysis(self):
        game = chess.Board()
        info_list = [{"depth": 12}]
        best_seen_depth = Mock()
        best_seen_depth.is_better.return_value = False

        result = depth_gated_analysis_info(
            best_seen_depth, info_list, game.fen(), game
        )

        self.assertIsNone(result)
        best_seen_depth.is_better.assert_called_once_with(
            info_list[0], game.fen(), game
        )

    def test_depth_gate_preserves_accepted_empty_analysis(self):
        game = chess.Board()
        for info_list in (None, []):
            with self.subTest(info_list=info_list):
                best_seen_depth = Mock()
                best_seen_depth.is_better.return_value = True

                result = depth_gated_analysis_info(
                    best_seen_depth, info_list, game.fen(), game
                )

                self.assertIs(info_list, result)
                best_seen_depth.is_better.assert_called_once_with(
                    None, game.fen(), game
                )

    def test_position_tagged_analysis_events_reject_stale_positions(self):
        self.assertTrue(analysis_event_matches_position("current", "current"))
        self.assertFalse(analysis_event_matches_position("previous", "current"))

    def test_keyboard_preview_matches_full_history_copy_without_mutating_game(self):
        game = chess.Board()
        game.push_uci("e2e4")
        game.push_uci("e7e5")
        history = tuple(game.move_stack)
        move = chess.Move.from_uci("g1f3")
        expected = game.copy(stack=True)
        expected.push(move)

        self.assertEqual(expected.board_fen(), board_fen_after_move(game, move))
        self.assertEqual(history, tuple(game.move_stack))

    def test_keyboard_preview_preserves_atomic_capture_effects(self):
        game = chess.variant.AtomicBoard("7k/8/8/3p4/4P3/8/8/K7 w - - 0 1")
        move = chess.Move.from_uci("e4d5")
        expected = game.copy(stack=True)
        expected.push(move)

        self.assertEqual(expected.board_fen(), board_fen_after_move(game, move))
        self.assertEqual([], game.move_stack)

    def test_legacy_untagged_analysis_events_remain_compatible(self):
        legacy_events = (
            Event.NEW_DEPTH(depth=12),
            Event.NEW_PV(pv=[chess.Move.from_uci("e2e4")]),
            Event.NEW_SCORE(score=25, mate=0),
        )

        for event in legacy_events:
            with self.subTest(event=event):
                self.assertFalse(hasattr(event, "fen"))
                self.assertTrue(analysis_event_matches_position(getattr(event, "fen", None), "current"))

    def test_position_tagged_best_move_rejects_stale_position(self):
        event = Event.BEST_MOVE(
            move=chess.Move.from_uci("e7e5"),
            ponder=None,
            inbook=False,
            fen="previous",
            search_revision=3,
        )

        self.assertFalse(analysis_event_matches_position(event.fen, "current"))
        self.assertEqual(3, event.search_revision)

    def test_legacy_untagged_best_move_remains_compatible(self):
        event = Event.BEST_MOVE(
            move=chess.Move.from_uci("e7e5"),
            ponder=None,
            inbook=False,
        )

        self.assertFalse(hasattr(event, "fen"))
        self.assertFalse(hasattr(event, "search_revision"))
        self.assertTrue(analysis_event_matches_position(getattr(event, "fen", None), "current"))

    def test_user_move_task_requires_position_revision_and_no_pending_engine_move(self):
        board = chess.Board()
        move = chess.Move.from_uci("e2e4")
        board.push(move)
        current_fen = board.fen()

        self.assertTrue(
            user_move_task_matches_position(move, current_fen, 1, board, current_fen, 1, None)
        )
        self.assertFalse(
            user_move_task_matches_position(move, current_fen, 1, board, current_fen, 2, None)
        )
        self.assertFalse(
            user_move_task_matches_position(move, current_fen, 1, board, current_fen, 1, "pending")
        )

        board.pop()
        board.push(move)
        self.assertFalse(user_move_task_matches_position(move, current_fen, 1, board, board.fen(), 2, None))

    def test_rebased_user_move_position_is_owned_without_its_move_stack(self):
        board = chess.Board()
        move = chess.Move.from_uci("e2e4")
        board.push(move)
        rebased = board.copy(stack=False)
        current_fen = rebased.fen()

        self.assertFalse(
            user_move_task_matches_position(move, current_fen, 1, rebased, current_fen, 1, None)
        )
        self.assertTrue(
            user_move_task_matches_position(
                move, current_fen, 1, rebased, current_fen, 1, None, require_last_move=False
            )
        )
        self.assertFalse(
            user_move_task_matches_position(
                move, current_fen, 1, rebased, current_fen, 2, None, require_last_move=False
            )
        )

    def test_engine_move_event_requires_latest_search_and_no_pending_move(self):
        self.assertTrue(engine_move_event_matches_state("current", "current", 4, 4, None))
        self.assertFalse(engine_move_event_matches_state("current", "current", 3, 4, None))
        self.assertFalse(engine_move_event_matches_state("previous", "current", 4, 4, None))
        self.assertFalse(engine_move_event_matches_state("current", "current", 4, 4, "pending"))

    def test_legacy_engine_move_revision_remains_compatible(self):
        self.assertTrue(engine_move_event_matches_state(None, "current", None, 4, None))

    def test_rejected_engine_move_only_resumes_unclaimed_stopped_clock(self):
        self.assertTrue(should_resume_clock_after_rejected_engine_move(True, False, None))
        self.assertFalse(should_resume_clock_after_rejected_engine_move(False, False, None))
        self.assertFalse(should_resume_clock_after_rejected_engine_move(True, True, None))
        self.assertFalse(should_resume_clock_after_rejected_engine_move(True, False, "pending"))

    def test_analysis_cycle_action_preserves_early_exit_side_effect_boundaries(self):
        cases = (
            (False, False, AnalysisCycleAction.CONTINUE),
            (False, True, AnalysisCycleAction.STOP_AFTER_GAME_END),
            (True, False, AnalysisCycleAction.RECONCILE_CHECKPOINT_RESTORE),
            (True, True, AnalysisCycleAction.RECONCILE_CHECKPOINT_RESTORE),
        )
        for checkpoint_pending, game_end_stopped, expected in cases:
            with self.subTest(
                checkpoint_pending=checkpoint_pending,
                game_end_stopped=game_end_stopped,
            ):
                self.assertEqual(
                    expected,
                    decide_analysis_cycle_action(
                        AnalysisCycleContext(
                            checkpoint_restore_pending=checkpoint_pending,
                            game_end_analysis_stopped=game_end_stopped,
                        )
                    ),
                )

    def test_analysis_source_matrix_preserves_existing_branch_precedence(self):
        def previous_source_selection(
            tutor_is_primary,
            engine_plays,
            pgn_mode,
            is_user_turn,
            engine_thinking,
            tutor_analyser_available,
        ):
            if tutor_is_primary:
                return AnalysisSourceAction.TUTOR_PRIMARY
            if not engine_plays and not pgn_mode:
                return AnalysisSourceAction.ENGINE_NON_PLAYING
            if not pgn_mode:
                if not is_user_turn and engine_thinking:
                    return AnalysisSourceAction.ENGINE_THINKING
                if tutor_analyser_available:
                    return AnalysisSourceAction.TUTOR_WEB_ONLY
                return AnalysisSourceAction.ENGINE_CURRENT
            return AnalysisSourceAction.NONE

        for values in product((False, True), repeat=6):
            with self.subTest(
                tutor_is_primary=values[0],
                engine_plays=values[1],
                pgn_mode=values[2],
                is_user_turn=values[3],
                engine_thinking=values[4],
                tutor_analyser_available=values[5],
            ):
                self.assertEqual(
                    previous_source_selection(*values),
                    decide_analysis_source(AnalysisSourceContext(*values)),
                )

    def test_web_analysis_payload_keeps_english_san_for_browser_figurines(self):
        board = chess.Board()
        info_list = [
            {
                "depth": 10,
                "score": chess.engine.PovScore(chess.engine.Cp(25), chess.WHITE),
                "pv": [chess.Move.from_uci("g1f3"), chess.Move.from_uci("g8f6")],
            }
        ]

        payload = web_analysis_payload(info_list, board.fen(), "engine")

        self.assertEqual(["Nf3", "Nf6"], payload["pv"])

        king_board = chess.Board("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
        king_info = [{
            "depth": 10,
            "score": chess.engine.PovScore(chess.engine.Cp(25), chess.WHITE),
            "pv": [chess.Move.from_uci("e1e2")],
        }]
        self.assertEqual(
            ["Ke2"], web_analysis_payload(king_info, king_board.fen(), "engine")["pv"]
        )

    def test_successful_engine_change_clears_preserved_mame_history(self):
        source = (Path(__file__).parents[1] / "mainloop.py").read_text(encoding="utf-8")
        success_branch = """else:
                clear_preserved_mame_history(self.shared)
                self.state.searchmoves.reset()
                msg = Message.ENGINE_READY("""

        self.assertIn(success_branch, source)

    @patch("analysis_depth.platform.machine", return_value="aarch64")
    def test_aarch64_non_playing_modes_cap_selected_engine_depth(self, _machine):
        self.assertEqual(30, selected_engine_analysis_depth(engine_plays=False))

    @patch("analysis_depth.platform.machine", return_value="aarch64")
    def test_aarch64_playing_modes_keep_selected_engine_depth(self, _machine):
        self.assertEqual(40, selected_engine_analysis_depth(engine_plays=True))

    @patch("analysis_depth.platform.machine", return_value="x86_64")
    def test_desktop_non_playing_modes_keep_selected_engine_depth(self, _machine):
        self.assertEqual(40, selected_engine_analysis_depth(engine_plays=False))

    def test_ponder_requests_three_lines_from_capable_engine(self):
        option = chess.engine.Option("MultiPV", "spin", 1, 1, 500, None)

        self.assertEqual(3, selected_engine_analysis_multipv(Mode.PONDER, {"MultiPV": option}))

    def test_ponder_caps_request_to_engine_multipv_maximum(self):
        option = chess.engine.Option("MultiPV", "spin", 1, 1, 2, None)

        self.assertEqual(2, selected_engine_analysis_multipv(Mode.PONDER, {"MultiPV": option}))

    def test_ponder_keeps_single_pv_when_engine_has_no_multipv_option(self):
        self.assertIsNone(selected_engine_analysis_multipv(Mode.PONDER, {}))

    def test_move_entry_and_replay_modes_request_three_lines(self):
        option = chess.engine.Option("MultiPV", "spin", 1, 1, 500, None)

        for mode in (Mode.ANALYSIS, Mode.KIBITZ, Mode.PGNREPLAY):
            with self.subTest(mode=mode):
                self.assertEqual(3, selected_engine_analysis_multipv(mode, {"MultiPV": option}))

    def test_other_modes_keep_selected_engine_single_pv(self):
        option = chess.engine.Option("MultiPV", "spin", 1, 1, 500, None)

        for mode in (Mode.NORMAL, Mode.BRAIN, Mode.TRAINING, Mode.OBSERVE):
            with self.subTest(mode=mode):
                self.assertIsNone(selected_engine_analysis_multipv(mode, {"MultiPV": option}))

    def test_web_analysis_payload_carries_three_lines_and_mirrors_pv1(self):
        board = chess.Board()
        info_list = [
            {
                "multipv": 1,
                "depth": 18,
                "score": chess.engine.PovScore(chess.engine.Cp(35), chess.WHITE),
                "pv": [chess.Move.from_uci("e2e4"), chess.Move.from_uci("e7e5")],
            },
            {
                "multipv": 2,
                "depth": 17,
                "score": chess.engine.PovScore(chess.engine.Cp(20), chess.WHITE),
                "pv": [chess.Move.from_uci("d2d4"), chess.Move.from_uci("d7d5")],
            },
            {
                "multipv": 3,
                "depth": 16,
                "score": chess.engine.PovScore(chess.engine.Cp(10), chess.WHITE),
                "pv": [chess.Move.from_uci("c2c4"), chess.Move.from_uci("e7e5")],
            },
            {
                "multipv": 4,
                "depth": 15,
                "score": chess.engine.PovScore(chess.engine.Cp(5), chess.WHITE),
                "pv": [chess.Move.from_uci("g1f3"), chess.Move.from_uci("d7d5")],
            },
        ]

        payload = web_analysis_payload(info_list, board.fen(), "tutor", suppress_engine_line=True)

        self.assertEqual(3, len(payload["lines"]))
        self.assertEqual([1, 2, 3], [line["multipv"] for line in payload["lines"]])
        self.assertEqual(["e4", "e5"], payload["lines"][0]["pv"])
        self.assertEqual(["d4", "d5"], payload["lines"][1]["pv"])
        self.assertEqual(["c4", "e5"], payload["lines"][2]["pv"])
        self.assertEqual(payload["lines"][0]["depth"], payload["depth"])
        self.assertEqual(payload["lines"][0]["score"], payload["score"])
        self.assertEqual(payload["lines"][0]["mate"], payload["mate"])
        self.assertEqual(payload["lines"][0]["pv"], payload["pv"])
        self.assertEqual("tutor", payload["source"])
        self.assertTrue(payload["suppress_engine_line"])

    def test_web_analysis_payload_filters_incomplete_lines(self):
        info_list = [
            {
                "multipv": 1,
                "depth": 2,
                "score": chess.engine.PovScore(chess.engine.Cp(12), chess.WHITE),
                "pv": [chess.Move.from_uci("e2e4")],
            },
            {"multipv": 2, "depth": 2, "pv": [chess.Move.from_uci("d2d4")]},
        ]

        payload = web_analysis_payload(info_list, chess.Board().fen(), "engine")

        self.assertEqual(1, len(payload["lines"]))
        self.assertEqual(1, payload["lines"][0]["multipv"])
        self.assertEqual(payload["lines"][0]["pv"], payload["pv"])

    def test_web_analysis_payload_waits_for_complete_pv1(self):
        info_list = [
            {"multipv": 1, "depth": 2, "pv": [chess.Move.from_uci("e2e4")]},
            {
                "multipv": 2,
                "depth": 2,
                "score": chess.engine.PovScore(chess.engine.Cp(12), chess.WHITE),
                "pv": [chess.Move.from_uci("d2d4")],
            },
        ]

        self.assertIsNone(web_analysis_payload(info_list, chess.Board().fen(), "engine"))

    def test_unfinished_custom_fen_load_returns_to_normal_play(self):
        mode = loaded_pgn_interaction_mode(
            previous_mode=Mode.KIBITZ,
            start_replay=False,
            has_custom_fen=True,
            loaded_game_finished=False,
        )

        self.assertEqual(Mode.NORMAL, mode)

    def test_unfinished_custom_fen_load_preserves_previous_playing_mode(self):
        mode = loaded_pgn_interaction_mode(
            previous_mode=Mode.BRAIN,
            start_replay=False,
            has_custom_fen=True,
            loaded_game_finished=False,
        )

        self.assertEqual(Mode.BRAIN, mode)

    def test_finished_custom_fen_load_uses_kibitz(self):
        mode = loaded_pgn_interaction_mode(
            previous_mode=Mode.NORMAL,
            start_replay=False,
            has_custom_fen=True,
            loaded_game_finished=True,
        )

        self.assertEqual(Mode.KIBITZ, mode)

    def test_pgn_replay_takes_precedence_over_unfinished_custom_fen(self):
        mode = loaded_pgn_interaction_mode(
            previous_mode=Mode.NORMAL,
            start_replay=True,
            has_custom_fen=True,
            loaded_game_finished=False,
        )

        self.assertEqual(Mode.PGNREPLAY, mode)

    def test_pgn_load_applies_all_moves_without_picostop(self):
        self.assertTrue(should_load_pgn_moves(stop_at_halfmove=None))

    def test_pgn_load_honors_positive_picostop(self):
        self.assertTrue(should_load_pgn_moves(stop_at_halfmove=2))

    def test_picostop_zero_does_not_load_moves(self):
        self.assertFalse(should_load_pgn_moves(stop_at_halfmove=0))

    def test_read_game_history_policy_is_limited_to_pos_only_mame(self):
        self.assertTrue(
            should_preserve_loaded_pgn_history(False, False, False, False)
        )
        self.assertTrue(
            should_preserve_loaded_pgn_history(True, False, True, True)
        )
        self.assertFalse(
            should_preserve_loaded_pgn_history(True, False, True, False)
        )
        self.assertTrue(
            should_preserve_loaded_pgn_history(True, False, False, False)
        )
        self.assertTrue(
            should_preserve_loaded_pgn_history(True, True, True, False)
        )

    def test_only_pos_without_edit_requires_fresh_mame_root(self):
        self.assertTrue(mame_requires_fresh_fen_root(True, True, False))
        self.assertFalse(mame_requires_fresh_fen_root(True, True, True))
        self.assertFalse(mame_requires_fresh_fen_root(True, False, False))
        self.assertFalse(mame_requires_fresh_fen_root(False, True, False))

    def test_rebased_loaded_pgn_keeps_headers_but_replaces_setup(self):
        source = chess.pgn.Game()
        source.headers["Event"] = "Loaded game"
        board = source.board()
        board.push_uci("e2e4")
        final_fen = board.fen()

        rebased = pgn_with_board_as_fresh_root(source, board)

        self.assertEqual("Loaded game", rebased.headers["Event"])
        self.assertEqual("1", rebased.headers["SetUp"])
        self.assertEqual(final_fen, rebased.headers["FEN"])
        self.assertEqual([], list(rebased.mainline_moves()))

    def test_set_position_preserves_selected_pgn_prefix(self):
        selected_game = chess.Board("4k3/8/8/8/8/8/P7/4K3 w - - 0 1")
        selected_game.push_uci("a2a4")

        live_game = setup_position_game(
            selected_game.fen(),
            uci960=False,
            event_game=selected_game,
        )

        self.assertEqual(selected_game.fen(), live_game.fen())
        self.assertEqual(selected_game.move_stack, live_game.move_stack)
        self.assertEqual(selected_game.root().fen(), live_game.root().fen())

    def test_set_position_can_use_selected_fen_as_fresh_root(self):
        selected_game = chess.Board("4k3/8/8/8/8/8/P7/4K3 w - - 0 1")
        selected_game.push_uci("a2a4")

        live_game = setup_position_game(
            selected_game.fen(),
            uci960=False,
            event_game=selected_game,
            preserve_history=False,
        )

        self.assertEqual(selected_game.fen(), live_game.fen())
        self.assertEqual([], live_game.move_stack)
        self.assertEqual(selected_game.fen(), live_game.root().fen())

    def test_set_position_history_policy_is_limited_to_pos_only_mame(self):
        selected_game = chess.Board()
        selected_game.push_uci("e2e4")

        self.assertTrue(
            should_preserve_set_position_history(
                selected_game,
                is_mame_engine=False,
                supports_position=False,
                supports_edit=False,
            )
        )
        self.assertTrue(
            should_preserve_set_position_history(
                selected_game,
                is_mame_engine=True,
                supports_position=True,
                supports_edit=True,
            )
        )
        self.assertFalse(
            should_preserve_set_position_history(
                selected_game,
                is_mame_engine=True,
                supports_position=True,
                supports_edit=False,
            )
        )
        self.assertTrue(
            should_preserve_set_position_history(
                selected_game,
                is_mame_engine=True,
                supports_position=False,
                supports_edit=False,
            )
        )

    def test_scan_position_is_a_fresh_root_without_history(self):
        fen = "4k3/8/8/8/8/8/P7/4K3 b - - 0 1"

        live_game = setup_position_game(fen, uci960=False, event_game=None)

        self.assertEqual(fen, live_game.fen())
        self.assertEqual([], live_game.move_stack)
        self.assertEqual(fen, live_game.root().fen())

    def test_standard_start_set_position_routes_to_new_game(self):
        self.assertEqual(
            518,
            set_position_new_game_code(chess.STARTING_FEN, uci960=False, variant="chess"),
        )

    def test_chess960_start_set_position_routes_to_its_new_game(self):
        board = chess.Board.from_chess960_pos(0)

        self.assertEqual(
            0,
            set_position_new_game_code(board.fen(), uci960=True, variant="chess"),
        )
        self.assertIsNone(
            set_position_new_game_code(board.fen(), uci960=False, variant="chess"),
        )

    def test_racing_kings_start_set_position_routes_to_new_game(self):
        fen = f"{RK_STARTING_BOARD_FEN} w - - 0 1"

        self.assertEqual(518, set_position_new_game_code(fen, uci960=False, variant="racingkings"))

    def test_non_start_set_position_remains_a_setup(self):
        self.assertIsNone(
            set_position_new_game_code(
                "8/8/8/8/8/8/4K3/7k w - - 0 1",
                uci960=False,
                variant="chess",
            )
        )

    def test_pending_set_position_treats_start_as_new_game(self):
        action, new_game_code = pending_set_position_fen_action(
            chess.STARTING_BOARD_FEN,
            chess.STARTING_BOARD_FEN,
            allow_chess960=False,
            variant="chess",
        )

        self.assertEqual("new_game", action)
        self.assertEqual(518, new_game_code)

    def test_pending_set_position_accepts_only_its_target(self):
        target = "8/8/8/8/8/8/4K3/7k"

        self.assertEqual(
            ("target", None),
            pending_set_position_fen_action(
                target,
                target,
                allow_chess960=False,
                variant="chess",
            ),
        )

    def test_pending_set_position_waits_on_move_or_takeback_positions(self):
        target = chess.Board()
        target.push_uci("e2e4")
        historical_position = target.board_fen()
        target.push_uci("e7e5")
        move_position = target.copy()
        move_position.push_uci("g1f3")

        for intermediate_fen in (move_position.board_fen(), historical_position):
            with self.subTest(fen=intermediate_fen):
                self.assertEqual(
                    ("wait", None),
                    pending_set_position_fen_action(
                        intermediate_fen,
                        target.board_fen(),
                        allow_chess960=False,
                        variant="chess",
                    ),
                )

    def test_user_move_opening_is_queued_before_engine_search(self):
        board = chess.Board()
        move = chess.Move.from_uci("e2e4")
        game_before = board.copy()
        board.push(move)
        user_move_message = Message.USER_MOVE_DONE(
            move=move,
            fen=game_before.fen(),
            turn=game_before.turn,
            game=board,
        )
        opening_message = Message.SHOW_TEXT(text_string="King's Pawn Game")

        messages = user_move_pre_search_messages(
            user_move_message,
            opening_message=opening_message,
        )

        self.assertIs(messages[0], user_move_message)
        self.assertIs(messages[1], opening_message)

    def test_tutor_reveal_keeps_its_order_before_opening(self):
        user_move_message = Message.USER_MOVE_DONE(
            move=chess.Move.from_uci("e2e4"),
            fen=chess.Board().fen(),
            turn=chess.WHITE,
            game=chess.Board(),
        )
        tutor_move = chess.Move.from_uci("d2d4")
        opening_message = Message.SHOW_TEXT(text_string="Queen's Pawn Game")

        messages = user_move_pre_search_messages(
            user_move_message,
            tutor_reveal_move=tutor_move,
            opening_message=opening_message,
        )

        self.assertIs(messages[0], user_move_message)
        self.assertIsInstance(messages[1], Message.TUTOR_MOVE_REVEAL)
        self.assertEqual(messages[1].move, tutor_move)
        self.assertIs(messages[2], opening_message)

    def test_tutor_analysis_is_disabled_in_ponder_mode(self):
        self.assertFalse(tutor_analysis_allowed_in_mode(Mode.PONDER))
        self.assertFalse(
            decide_tutor_analysis(
                TutorAnalysisContext(
                    interaction_mode=Mode.PONDER,
                    pgn_mode=False,
                    engine_should_skip_analyser=False,
                    engine_is_playing=False,
                    is_user_turn=True,
                )
            )
        )

    def test_non_playing_analysis_mode_still_prefers_tutor_when_allowed(self):
        self.assertTrue(tutor_analysis_allowed_in_mode(Mode.ANALYSIS))
        self.assertTrue(
            decide_tutor_analysis(
                TutorAnalysisContext(
                    interaction_mode=Mode.ANALYSIS,
                    pgn_mode=False,
                    engine_should_skip_analyser=False,
                    engine_is_playing=False,
                    is_user_turn=True,
                )
            )
        )

    def test_playing_user_turn_prefers_tutor_for_cpu_saving(self):
        self.assertTrue(
            decide_tutor_analysis(
                TutorAnalysisContext(
                    interaction_mode=Mode.NORMAL,
                    pgn_mode=False,
                    engine_should_skip_analyser=False,
                    engine_is_playing=True,
                    is_user_turn=True,
                )
            )
        )

    def test_playing_engine_turn_keeps_tutor_out_of_playing_search(self):
        self.assertFalse(
            decide_tutor_analysis(
                TutorAnalysisContext(
                    interaction_mode=Mode.NORMAL,
                    pgn_mode=False,
                    engine_should_skip_analyser=False,
                    engine_is_playing=True,
                    is_user_turn=False,
                )
            )
        )

    def test_tutor_analysis_routing_matrix(self):
        """Lock every current input combination before routing is reorganized."""
        for mode, pgn_mode, skip_engine, engine_plays, user_turn in product(
            Mode.items(),
            (False, True),
            (False, True),
            (False, True),
            (False, True),
        ):
            expected = mode != Mode.PONDER and (
                pgn_mode or skip_engine or not engine_plays or user_turn
            )
            with self.subTest(
                mode=mode,
                pgn_mode=pgn_mode,
                skip_engine=skip_engine,
                engine_plays=engine_plays,
                user_turn=user_turn,
            ):
                self.assertEqual(
                    expected,
                    decide_tutor_analysis(
                        TutorAnalysisContext(
                            interaction_mode=mode,
                            pgn_mode=pgn_mode,
                            engine_should_skip_analyser=skip_engine,
                            engine_is_playing=engine_plays,
                            is_user_turn=user_turn,
                        )
                    ),
                )

    def test_ponder_always_allows_takeback(self):
        for guard in (
            {"take_back_locked": True},
            {"online_mode": True},
            {"emulation_mode": True},
            {
                "take_back_locked": True,
                "online_mode": True,
                "emulation_mode": True,
            },
        ):
            args = {
                "take_back_locked": False,
                "online_mode": False,
                "emulation_mode": False,
                "automatic_takeback": False,
                "ponder_mode": True,
            }
            args.update(guard)
            with self.subTest(guard=guard):
                self.assertFalse(should_block_takeback(**args))

    def test_normal_takeback_guards_remain_unchanged(self):
        self.assertTrue(should_block_takeback(True, False, False, False))
        self.assertTrue(should_block_takeback(False, True, False, False))
        self.assertTrue(should_block_takeback(False, False, True, False))
        self.assertFalse(should_block_takeback(False, False, True, True))
        self.assertFalse(should_block_takeback(False, False, False, False))

    def test_king_lift_reaches_setpieces_threshold_before_coach(self):
        self.assertTrue(should_show_setpieces_after_lift_timeout("K", is_hand_mode=False))
        self.assertTrue(should_show_setpieces_after_lift_timeout("k", is_hand_mode=True))

    def test_quick_switch_threshold_still_applies_to_non_hand_lifts(self):
        self.assertTrue(should_show_setpieces_after_lift_timeout("Q", is_hand_mode=False))
        self.assertFalse(should_show_setpieces_after_lift_timeout("Q", is_hand_mode=True))
        self.assertFalse(should_show_setpieces_after_lift_timeout("", is_hand_mode=False))

    def test_playing_mode_rejects_moves_after_declared_game_end(self):
        self.assertTrue(
            should_reject_user_move_after_game_end(
                interaction_mode=Mode.NORMAL,
                game_declared=True,
                game_ending="*",
            )
        )
        self.assertTrue(
            should_reject_user_move_after_game_end(
                interaction_mode=Mode.NORMAL,
                game_declared=False,
                game_ending="0-1",
            )
        )
        self.assertTrue(
            should_reject_user_move_after_game_end(
                interaction_mode=Mode.REMOTE,
                game_declared=False,
                game_ending="0-1",
            )
        )

    def test_non_playing_mode_can_still_review_after_game_end(self):
        self.assertFalse(
            should_reject_user_move_after_game_end(
                interaction_mode=Mode.ANALYSIS,
                game_declared=True,
                game_ending="0-1",
            )
        )

    def test_playing_mode_accepts_moves_when_game_has_no_result(self):
        self.assertFalse(
            should_reject_user_move_after_game_end(
                interaction_mode=Mode.NORMAL,
                game_declared=False,
                game_ending="*",
            )
        )

    def test_sliding_move_cannot_mutate_ended_playing_game(self):
        self.assertFalse(
            should_process_sliding_move(
                interaction_mode=Mode.NORMAL,
                game_declared=False,
                game_ending="1-0",
            )
        )

    def test_sliding_move_remains_available_during_active_game(self):
        self.assertTrue(
            should_process_sliding_move(
                interaction_mode=Mode.NORMAL,
                game_declared=False,
                game_ending="*",
            )
        )

    def test_non_playing_mode_keeps_sliding_after_game_end(self):
        self.assertTrue(
            should_process_sliding_move(
                interaction_mode=Mode.ANALYSIS,
                game_declared=True,
                game_ending="1-0",
            )
        )

    def test_takeback_reopens_a_finished_game_at_a_playable_position(self):
        self.assertTrue(
            should_resume_game_after_takeback(
                game_over=False,
                game_declared=False,
                game_ending="1-0",
            )
        )
        self.assertTrue(
            should_resume_game_after_takeback(
                game_over=False,
                game_declared=True,
                game_ending="*",
            )
        )

    def test_takeback_does_not_reopen_a_terminal_or_active_game(self):
        self.assertFalse(
            should_resume_game_after_takeback(
                game_over=True,
                game_declared=False,
                game_ending="1-0",
            )
        )
        self.assertFalse(
            should_resume_game_after_takeback(
                game_over=False,
                game_declared=False,
                game_ending="*",
            )
        )

    def test_playing_mode_stops_analysis_after_game_end(self):
        self.assertTrue(
            should_stop_analysis_after_game_end(
                interaction_mode=Mode.NORMAL,
                game_over=True,
                game_declared=False,
                game_ending="*",
            )
        )
        self.assertTrue(
            should_stop_analysis_after_game_end(
                interaction_mode=Mode.BRAIN,
                game_over=False,
                game_declared=True,
                game_ending="*",
            )
        )
        self.assertTrue(
            should_stop_analysis_after_game_end(
                interaction_mode=Mode.TRAINING,
                game_over=False,
                game_declared=False,
                game_ending="1-0",
            )
        )

    def test_non_playing_mode_can_still_analyse_finished_positions(self):
        self.assertFalse(
            should_stop_analysis_after_game_end(
                interaction_mode=Mode.ANALYSIS,
                game_over=True,
                game_declared=True,
                game_ending="0-1",
            )
        )
        self.assertFalse(
            should_stop_analysis_after_game_end(
                interaction_mode=Mode.PONDER,
                game_over=True,
                game_declared=False,
                game_ending="1-0",
            )
        )

    def test_playing_mode_keeps_analysis_available_during_active_game(self):
        self.assertFalse(
            should_stop_analysis_after_game_end(
                interaction_mode=Mode.NORMAL,
                game_over=False,
                game_declared=False,
                game_ending="*",
            )
        )

    def test_game_end_analysis_stop_matrix(self):
        """Keep playing and review modes distinct for every game-end signal."""
        playing_modes = (Mode.NORMAL, Mode.BRAIN, Mode.TRAINING)
        for mode, game_over, game_declared, game_ending in product(
            Mode.items(),
            (False, True),
            (False, True),
            (None, "*", "1-0"),
        ):
            has_ended = game_over or game_declared or game_ending == "1-0"
            expected = mode in playing_modes and has_ended
            with self.subTest(
                mode=mode,
                game_over=game_over,
                game_declared=game_declared,
                game_ending=game_ending,
            ):
                self.assertEqual(
                    expected,
                    should_stop_analysis_after_game_end(
                        interaction_mode=mode,
                        game_over=game_over,
                        game_declared=game_declared,
                        game_ending=game_ending,
                    ),
                )
                self.assertEqual(
                    expected,
                    decide_game_end_analysis_stop(
                        GameEndAnalysisContext(
                            interaction_mode=mode,
                            game_over=game_over,
                            game_declared=game_declared,
                            game_ending=game_ending,
                        )
                    ),
                )

    def test_remote_move_matches_current_live_position(self):
        board = chess.Board()
        move = chess.Move.from_uci("e2e4")
        posted = board.copy()
        posted.push(move)

        self.assertTrue(remote_move_matches_current_position(move, posted.fen(), board))

    def test_remote_move_rejects_stale_pgn_position(self):
        live_board = chess.Board()
        live_board.push(chess.Move.from_uci("e2e4"))
        live_board.push(chess.Move.from_uci("e7e5"))

        stale_board = chess.Board()
        move = chess.Move.from_uci("d2d4")
        stale_board.push(move)

        self.assertFalse(remote_move_matches_current_position(move, stale_board.fen(), live_board))

    def test_remote_move_rejects_stale_illegal_move(self):
        live_board = chess.Board()
        live_board.push(chess.Move.from_uci("e2e4"))
        live_board.push(chess.Move.from_uci("e7e5"))

        stale_board = chess.Board()
        move = chess.Move.from_uci("e2e4")
        stale_board.push(move)

        self.assertFalse(remote_move_matches_current_position(move, stale_board.fen(), live_board))

    def test_remote_move_without_fen_keeps_legacy_acceptance(self):
        self.assertTrue(
            remote_move_matches_current_position(
                chess.Move.from_uci("e2e4"),
                "",
                chess.Board(),
            )
        )


class TestPicochessAlternativeTutorRollback(unittest.IsolatedAsyncioTestCase):
    async def test_successful_rollback_does_not_force_resync(self):
        board = chess.Board()
        picotutor = Mock()
        picotutor.pop_last_move = AsyncMock(return_value=True)
        resync = AsyncMock()

        valid = await rollback_picotutor_for_alternative(picotutor, board, resync)

        self.assertTrue(valid)
        picotutor.pop_last_move.assert_awaited_once_with(board)
        resync.assert_not_awaited()

    async def test_failed_rollback_resynchronizes_before_replacement_search(self):
        board = chess.Board()
        picotutor = Mock()
        picotutor.pop_last_move = AsyncMock(return_value=False)
        resync = AsyncMock()

        valid = await rollback_picotutor_for_alternative(picotutor, board, resync)

        self.assertFalse(valid)
        picotutor.pop_last_move.assert_awaited_once_with(board)
        resync.assert_awaited_once_with()


class TestUserMoveSearchOwnership(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.controller = object.__new__(mainloop.MainLoop)
        self.controller.think = AsyncMock()
        self.board = chess.Board()
        self.move = chess.Move.from_uci("e2e4")
        self.board.push(self.move)
        self.controller.state = SimpleNamespace(
            game=self.board,
            get_fen=self.board.fen,
            user_move_revision=1,
            done_computer_fen=None,
        )

    async def test_current_user_move_starts_exactly_one_search(self):
        started = await self.controller._think_after_current_user_move(
            self.move, self.board.fen(), 1, None
        )

        self.assertTrue(started)
        self.controller.think.assert_awaited_once_with(
            None,
            user_move_owner=(self.move, self.board.fen(), 1),
        )

    async def test_replayed_same_move_invalidates_old_task(self):
        original_fen = self.board.fen()
        self.board.pop()
        self.board.push(self.move)
        self.controller.state.user_move_revision = 2

        started = await self.controller._think_after_current_user_move(
            self.move, original_fen, 1, None
        )

        self.assertFalse(started)
        self.controller.think.assert_not_awaited()

    async def test_pending_engine_move_invalidates_delayed_user_task(self):
        self.controller.state.done_computer_fen = "pending"

        started = await self.controller._think_after_current_user_move(
            self.move, self.board.fen(), 1, None
        )

        self.assertFalse(started)
        self.controller.think.assert_not_awaited()


class TestThinkAfterMameRecoveryRebase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        start_patch(self, mainloop.Observable, "fire", AsyncMock())
        self.controller = object.__new__(mainloop.MainLoop)
        self.controller._set_game_started = Mock()
        # Returning None stops think() right after it decides to start a search.
        self.controller._prepare_engine_for_search = AsyncMock(return_value=None)
        self.controller.bookreader = None
        self.move = chess.Move.from_uci("e2e4")
        board = chess.Board()
        board.push(self.move)
        self.owner = (self.move, board.fen(), 1)
        self.controller.state = SimpleNamespace(
            engine_search_revision=0,
            game=board,
            get_fen=lambda: self.controller.state.game.fen(),
            user_move_revision=1,
            done_computer_fen=None,
            variant="chess",
        )

        async def rebase():
            self.controller.state.game = self.controller.state.game.copy(stack=False)
            return True

        self.controller._apply_pending_mame_recovery_rebase = AsyncMock(side_effect=rebase)

    async def test_rebase_before_search_keeps_the_user_move_search(self):
        await self.controller.think(None, user_move_owner=self.owner)

        self.assertFalse(self.controller.state.game.move_stack)
        self.controller._prepare_engine_for_search.assert_awaited_once_with(1)

    async def test_rebase_does_not_revive_a_superseded_user_move(self):
        self.controller.state.user_move_revision = 2

        await self.controller.think(None, user_move_owner=self.owner)

        self.controller._prepare_engine_for_search.assert_not_awaited()


class TestEngineSearchIdlePreparation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.controller = object.__new__(mainloop.MainLoop)
        self.controller.engine = Mock()
        self.controller.engine.stop = AsyncMock()
        self.controller.engine.wait_until_idle = AsyncMock(return_value=True)
        self.controller.engine.cancel_playing_search = AsyncMock(return_value=True)
        self.controller.state = SimpleNamespace(engine_search_revision=7)

    async def test_idle_engine_needs_no_stop(self):
        self.controller.engine.is_waiting.return_value = True

        self.assertTrue(await self.controller._prepare_engine_for_search(7))

        self.controller.engine.stop.assert_not_awaited()
        self.controller.engine.wait_until_idle.assert_not_awaited()

    async def test_busy_engine_is_stopped_before_search(self):
        self.controller.engine.is_waiting.return_value = False

        self.assertTrue(await self.controller._prepare_engine_for_search(7))

        self.controller.engine.stop.assert_awaited_once_with()
        self.controller.engine.wait_until_idle.assert_awaited_once_with(mainloop.ENGINE_SEARCH_IDLE_TIMEOUT)
        self.controller.engine.cancel_playing_search.assert_not_awaited()

    async def test_stuck_engine_is_cancelled_after_timeout(self):
        self.controller.engine.is_waiting.return_value = False
        self.controller.engine.wait_until_idle.return_value = False

        self.assertTrue(await self.controller._prepare_engine_for_search(7))

        self.controller.engine.cancel_playing_search.assert_awaited_once_with(
            mainloop.ENGINE_SEARCH_CANCEL_TIMEOUT
        )

    async def test_failed_cancellation_refuses_new_search(self):
        self.controller.engine.is_waiting.return_value = False
        self.controller.engine.wait_until_idle.return_value = False
        self.controller.engine.cancel_playing_search.return_value = False

        self.assertFalse(await self.controller._prepare_engine_for_search(7))

    async def test_superseded_wait_does_not_cancel_newer_search(self):
        self.controller.engine.is_waiting.return_value = False

        async def supersede_search(_timeout):
            self.controller.state.engine_search_revision = 8
            return False

        self.controller.engine.wait_until_idle.side_effect = supersede_search

        self.assertIsNone(await self.controller._prepare_engine_for_search(7))
        self.controller.engine.cancel_playing_search.assert_not_awaited()


class TestEngineSearchIdleFailure(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fire = AsyncMock()
        start_patch(self, mainloop.Observable, "fire", self.fire)
        self.controller = object.__new__(mainloop.MainLoop)
        self.controller.state = SimpleNamespace(pending_engine_result=None)

    async def test_idle_failure_uses_existing_best_move_recovery(self):
        await self.controller._publish_engine_search_failure("test-fen", 12)

        self.assertEqual("*", self.controller.state.pending_engine_result)
        self.fire.assert_awaited_once()
        event = self.fire.await_args.args[0]
        self.assertEqual(EventApi.BEST_MOVE, repr(event))
        self.assertIsNone(event.move)
        self.assertEqual("test-fen", event.fen)
        self.assertEqual(12, event.search_revision)


class TestThinkEngineIdleContract(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fire = AsyncMock()
        start_patch(self, mainloop.Observable, "fire", self.fire)
        self.controller = object.__new__(mainloop.MainLoop)
        self.controller._apply_pending_mame_recovery_rebase = AsyncMock()
        self.controller._set_game_started = Mock()
        self.controller._prepare_engine_for_search = AsyncMock(return_value=True)
        self.controller._publish_engine_search_failure = AsyncMock()
        self.controller._cache_engine_abort_result = AsyncMock()
        self.controller.online_mode = Mock(return_value=False)
        self.controller.emulation_mode = Mock(return_value=False)
        self.controller.pgn_mode = Mock(return_value=False)
        self.controller.bookreader = None
        self.controller.engine = Mock()

        async def finish_without_move(result_queue, **_kwargs):
            await result_queue.put(None)

        self.controller.engine.go = AsyncMock(side_effect=finish_without_move)
        board = chess.Board()
        self.controller.state = SimpleNamespace(
            engine_search_revision=0,
            game=board,
            get_fen=board.fen,
            get_variant_board=Mock(return_value=None),
            start_clock=AsyncMock(),
            time_control=SimpleNamespace(uci=Mock(return_value={})),
            searchmoves=SimpleNamespace(all=Mock(return_value=[])),
            variant="chess",
            automatic_takeback=True,
            ignore_next_engine_move=False,
        )

    async def test_failed_idle_preparation_never_starts_clock_or_engine(self):
        self.controller._prepare_engine_for_search.return_value = False

        await self.controller.think(None)

        self.controller.state.start_clock.assert_not_awaited()
        self.controller.engine.go.assert_not_awaited()
        self.controller._publish_engine_search_failure.assert_awaited_once_with(
            self.controller.state.game.fen(),
            1,
        )

    async def test_ready_engine_starts_clock_and_exactly_one_search(self):
        await self.controller.think(None)

        self.controller.state.start_clock.assert_awaited_once_with()
        self.controller.engine.go.assert_awaited_once()


class TestStopSearchTimeout(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.controller = object.__new__(mainloop.MainLoop)
        self.controller.engine = Mock()
        self.controller.engine.stop = AsyncMock()
        self.controller.engine.consume_forced_analyser_stop.return_value = False
        self.controller.engine.wait_until_idle = AsyncMock(return_value=True)
        self.controller.emulation_mode = Mock(return_value=False)

    async def test_default_wait_is_bounded_and_succeeds(self):
        self.assertTrue(await self.controller.stop_search())
        self.controller.engine.wait_until_idle.assert_awaited_once_with(
            mainloop.ENGINE_SEARCH_IDLE_TIMEOUT
        )

    async def test_timeout_is_reported_to_caller(self):
        self.controller.engine.wait_until_idle.return_value = False

        self.assertFalse(await self.controller.stop_search())


class TestInteractionModeSwitch(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.controller = object.__new__(mainloop.MainLoop)
        self.controller.state = SimpleNamespace(
            best_sent_depth=SimpleNamespace(reset=Mock()),
            interaction_mode=Mode.NORMAL,
            position_checkpoint_restore_pending=False,
            can_preserve_position_checkpoint_play_mode=Mock(return_value=False),
            done_computer_fen=None,
            newgame_happened=True,
            picotutor=None,
        )
        self.controller.get_rid_of_engine_move = AsyncMock()
        self.controller._set_pgn_replay_autoplay = Mock()
        self.controller.stop_search_and_clock = AsyncMock()
        self.controller._save_position_checkpoint = AsyncMock()
        self.controller._clear_position_checkpoint = Mock()
        self.controller.engine_mode = AsyncMock()
        self.controller.set_wait_state = AsyncMock()

    @staticmethod
    def mode_event(mode):
        return Event.SET_INTERACTION_MODE(
            mode=mode,
            mode_text=SimpleNamespace(large_text=mode.name),
            show_ok=True,
        )

    async def test_play_to_analysis_stops_play_before_entering_ponder(self):
        order = []

        async def stop_old_mode():
            self.assertEqual(Mode.NORMAL, self.controller.state.interaction_mode)
            order.append("stop")

        async def activate_new_mode():
            self.assertEqual(Mode.PONDER, self.controller.state.interaction_mode)
            order.append("engine_mode")

        self.controller.stop_search_and_clock.side_effect = stop_old_mode
        self.controller.engine_mode.side_effect = activate_new_mode

        await self.controller.process_main_events(self.mode_event(Mode.PONDER))

        self.assertEqual(["stop", "engine_mode"], order)
        self.assertEqual(Mode.PONDER, self.controller.state.interaction_mode)
        self.assertFalse(self.controller.state.newgame_happened)
        self.controller.get_rid_of_engine_move.assert_awaited_once_with()
        self.controller.stop_search_and_clock.assert_awaited_once_with()
        self.controller._save_position_checkpoint.assert_awaited_once_with(Mode.NORMAL)
        self.controller._clear_position_checkpoint.assert_not_called()
        self.controller.set_wait_state.assert_awaited_once()
        self.controller.state.best_sent_depth.reset.assert_called_once_with()

    async def test_analysis_to_play_stops_analysis_before_entering_normal(self):
        self.controller.state.interaction_mode = Mode.PONDER
        order = []

        async def stop_old_mode():
            self.assertEqual(Mode.PONDER, self.controller.state.interaction_mode)
            order.append("stop")

        async def activate_new_mode():
            self.assertEqual(Mode.NORMAL, self.controller.state.interaction_mode)
            order.append("engine_mode")

        self.controller.stop_search_and_clock.side_effect = stop_old_mode
        self.controller.engine_mode.side_effect = activate_new_mode

        await self.controller.process_main_events(self.mode_event(Mode.NORMAL))

        self.assertEqual(["stop", "engine_mode"], order)
        self.assertEqual(Mode.NORMAL, self.controller.state.interaction_mode)
        self.controller.get_rid_of_engine_move.assert_not_awaited()
        self.controller.stop_search_and_clock.assert_awaited_once_with()
        self.controller._save_position_checkpoint.assert_not_awaited()
        self.controller._clear_position_checkpoint.assert_called_once_with()
        self.controller._set_pgn_replay_autoplay.assert_called_once_with(
            False, mode=Mode.NORMAL
        )
        self.controller.set_wait_state.assert_awaited_once()
        self.controller.state.best_sent_depth.reset.assert_called_once_with()


class TestTutorMessageOwnership(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.show = AsyncMock()
        self.sleep = AsyncMock()
        start_patch(self, mainloop.DisplayMsg, "show", self.show)
        start_patch(self, mainloop.asyncio, "sleep", self.sleep)
        self.controller = object.__new__(mainloop.MainLoop)
        self.board = chess.Board()
        self.move = chess.Move.from_uci("e2e4")
        self.board.push(self.move)
        self.controller.state = SimpleNamespace(
            game=self.board,
            get_fen=self.board.fen,
            user_move_revision=1,
            done_computer_fen=None,
        )
        self.owner = (self.move, self.board.fen(), 1)

    async def test_current_move_delivers_all_tutor_messages(self):
        messages = [("warning", 3.0), ("hint", None)]

        await self.controller._deliver_picotutor_messages(messages, self.owner)

        self.assertEqual(
            [call("warning"), call("hint")],
            self.show.await_args_list,
        )
        self.sleep.assert_awaited_once_with(3.0)
        self.assertEqual([], messages)

    async def test_replacement_move_discards_remaining_tutor_messages(self):
        async def replace_move(_delay):
            self.controller.state.user_move_revision = 2

        self.sleep.side_effect = replace_move
        messages = [("warning", 3.0), ("threat", 5.0), ("hint", None)]

        await self.controller._deliver_picotutor_messages(messages, self.owner)

        self.show.assert_awaited_once_with("warning")
        self.sleep.assert_awaited_once_with(3.0)
        self.assertEqual([], messages)


class TestEarlyUserMoveInvalidation(unittest.TestCase):
    def setUp(self):
        self.source = ast.parse(Path(mainloop.__file__).read_text(encoding="utf-8"))
        self.main_loop = next(
            node for node in ast.walk(self.source)
            if isinstance(node, ast.ClassDef) and node.name == "MainLoop"
        )
        self.controller = object.__new__(mainloop.MainLoop)
        self.controller.state = SimpleNamespace(user_move_revision=7)

    def test_invalidation_advances_the_owner_revision(self):
        revision = self.controller._invalidate_user_move_tasks()

        self.assertEqual(8, revision)
        self.assertEqual(8, self.controller.state.user_move_revision)

    def test_user_move_invalidates_before_waiting_for_engine_and_clock(self):
        user_move = next(
            node for node in self.main_loop.body
            if getattr(node, "name", None) == "user_move"
        )
        invalidate = next(
            node for node in ast.walk(user_move)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_invalidate_user_move_tasks"
        )
        stop = next(
            node for node in ast.walk(user_move)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "stop_search_and_clock"
        )

        self.assertLess(invalidate.lineno, stop.lineno)

    def test_takeback_paths_invalidate_before_waiting_for_engine_and_clock(self):
        for method_name in ("takeback", "process_fen"):
            with self.subTest(method=method_name):
                method = next(
                    node for node in self.main_loop.body
                    if getattr(node, "name", None) == method_name
                )
                invalidations = [
                    node for node in ast.walk(method)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "_invalidate_user_move_tasks"
                ]
                stops = [
                    node for node in ast.walk(method)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "stop_search_and_clock"
                ]

                self.assertTrue(
                    any(stop.lineno == invalidate.lineno + 1 for invalidate in invalidations for stop in stops)
                )


class TestCoachPositionOwnership(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        source = ast.parse(Path(mainloop.__file__).read_text(encoding="utf-8"))
        self.main_loop = next(
            node for node in ast.walk(source)
            if isinstance(node, ast.ClassDef) and node.name == "MainLoop"
        )
        self.show = AsyncMock()
        self.sleep = AsyncMock()
        start_patch(self, mainloop.DisplayMsg, "show", self.show)
        start_patch(self, mainloop.asyncio, "sleep", self.sleep)
        self.controller = object.__new__(mainloop.MainLoop)
        self.board = chess.Board()
        self.dgtmenu = SimpleNamespace(get_dgt_fen=Mock(return_value=self.board.board_fen()))
        self.controller.board_type = mainloop.dgt.util.EBoard.NOEBOARD
        self.controller.state = SimpleNamespace(
            interaction_mode=Mode.NORMAL,
            play_mode=mainloop.PlayMode.USER_WHITE,
            game=self.board,
            get_fen=self.board.fen,
            get_board_fen=self.board.board_fen,
            user_move_revision=4,
            coach_triggered=True,
            position_mode=False,
            error_fen="transient",
            dgtmenu=self.dgtmenu,
            stop_clock=AsyncMock(),
            start_clock=AsyncMock(),
            stop_fen_timer=Mock(),
            done_computer_fen=None,
            is_user_turn=lambda: self.board.turn == chess.WHITE,
            time_control=SimpleNamespace(internal_running=Mock(return_value=False)),
            picotutor=SimpleNamespace(
                get_pos_analysis=AsyncMock(
                    return_value=(chess.Move.null(), 25, 0, [])
                )
            ),
        )

    async def test_completed_coach_releases_position_mode_and_restarts_clock(self):
        await self.controller.call_pico_coach()

        self.assertFalse(self.controller.state.position_mode)
        self.assertFalse(self.controller.state.coach_triggered)
        self.assertIsNone(self.controller.state.error_fen)
        self.controller.state.start_clock.assert_awaited_once_with()

    async def test_coach_does_not_claim_position_mode_during_engine_turn(self):
        self.controller.state.game.turn = chess.BLACK

        await self.controller.call_pico_coach()

        self.assertFalse(self.controller.state.position_mode)
        self.assertTrue(self.controller.state.coach_triggered)
        self.controller.state.stop_clock.assert_not_awaited()
        self.controller.state.start_clock.assert_not_awaited()
        self.show.assert_not_awaited()

    async def test_physical_position_change_stops_coach_and_gives_back_the_clock(self):
        self.controller.board_type = mainloop.dgt.util.EBoard.DGT
        self.dgtmenu.get_dgt_fen.return_value = "8/8/8/8/8/8/8/8"

        await self.controller.call_pico_coach()

        # The return event's position-mode path still clears the Coach display.
        self.assertTrue(self.controller.state.position_mode)
        self.controller.state.start_clock.assert_awaited_once_with()
        self.show.assert_not_awaited()

    async def test_abandoned_coach_does_not_restart_clock_for_pending_engine_move(self):
        self.controller.board_type = mainloop.dgt.util.EBoard.DGT
        self.dgtmenu.get_dgt_fen.return_value = "8/8/8/8/8/8/8/8"
        self.controller.state.done_computer_fen = "pending"

        await self.controller.call_pico_coach()

        self.controller.state.start_clock.assert_not_awaited()

    async def test_abandoned_coach_does_not_restart_running_clock(self):
        self.controller.board_type = mainloop.dgt.util.EBoard.DGT
        self.dgtmenu.get_dgt_fen.return_value = "8/8/8/8/8/8/8/8"
        self.controller.state.time_control.internal_running.return_value = True

        await self.controller.call_pico_coach()

        self.controller.state.start_clock.assert_not_awaited()

    async def test_move_during_coach_stops_old_output_and_does_not_restart_clock(self):
        async def advance_revision(delay):
            if delay == 2:
                self.controller._release_coach_position_mode_for_move()
                self.controller.state.user_move_revision += 1

        self.sleep.side_effect = advance_revision

        await self.controller.call_pico_coach()

        self.assertFalse(self.controller.state.position_mode)
        self.assertFalse(self.controller.state.coach_triggered)
        self.controller.state.start_clock.assert_not_awaited()
        self.assertEqual(1, self.show.await_count)

    def test_confirmed_move_releases_coach_mode_before_invalidating_old_tasks(self):
        self.controller.state.position_mode = True
        self.controller._release_coach_position_mode_for_move()

        self.assertFalse(self.controller.state.position_mode)
        self.assertFalse(self.controller.state.coach_triggered)

        user_move = next(
            node for node in self.main_loop.body
            if getattr(node, "name", None) == "user_move"
        )
        release = next(
            node for node in ast.walk(user_move)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_release_coach_position_mode_for_move"
        )
        invalidate = next(
            node for node in ast.walk(user_move)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_invalidate_user_move_tasks"
        )
        self.assertLess(release.lineno, invalidate.lineno)


class TestOnlineTimeControl(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.show = AsyncMock()
        start_patch(self, mainloop.DisplayMsg, "show", self.show)
        self.state = object.__new__(PicochessState)
        self.state.stop_clock = AsyncMock()
        self.state.stop_fen_timer = Mock()
        self.state.dgttranslate = SimpleNamespace(text=Mock(return_value="ok"))
        self.state.time_control = Mock()

    async def test_online_time_control_replaces_old_clock_and_publishes_it(self):
        old_time_control = self.state.time_control

        await self.state.set_online_tctrl("5", "3")

        self.state.stop_clock.assert_awaited_once_with()
        old_time_control.stop_internal.assert_called_once_with(log=False)
        parameters = self.state.time_control.get_parameters()
        self.assertEqual(mainloop.TimeMode.FISCHER, parameters["mode"])
        self.assertEqual(5, parameters["blitz"])
        self.assertEqual(3, parameters["fischer"])
        self.assertEqual(
            {chess.WHITE: 303, chess.BLACK: 303},
            parameters["internal_time"],
        )
        self.show.assert_awaited_once()
        self.state.stop_fen_timer.assert_called_once_with()

    def test_switch_online_awaits_time_control_before_resetting_start_time(self):
        source = ast.parse(Path(mainloop.__file__).read_text(encoding="utf-8"))
        switch_online = next(
            node for node in ast.walk(source)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "switch_online"
        )
        set_tctrl_await = next(
            node for node in ast.walk(switch_online)
            if isinstance(node, ast.Await)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "set_online_tctrl"
        )
        reset_call = next(
            node for node in ast.walk(switch_online)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "reset_start_time"
        )

        self.assertLess(set_tctrl_await.lineno, reset_call.lineno)


class TestAlternativeMovePendingState(unittest.TestCase):
    def setUp(self):
        self.controller = object.__new__(mainloop.MainLoop)
        self.controller.state = SimpleNamespace(
            done_computer_fen="pending engine position",
            done_move=chess.Move.from_uci("e7e5"),
        )

    def test_clearing_pending_move_allows_replacement_result(self):
        self.controller._clear_pending_engine_move()

        self.assertIsNone(self.controller.state.done_computer_fen)
        self.assertEqual(chess.Move.null(), self.controller.state.done_move)
        self.assertTrue(
            engine_move_event_matches_state(
                "replacement position",
                "replacement position",
                2,
                2,
                self.controller.state.done_computer_fen,
            )
        )

    def test_both_alternative_move_paths_clear_pending_state(self):
        source = ast.parse(Path(mainloop.__file__).read_text(encoding="utf-8"))
        process_events = next(
            node for node in ast.walk(source)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "process_main_events"
        )
        clear_calls = [
            node for node in ast.walk(process_events)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_clear_pending_engine_move"
        ]

        self.assertEqual(2, len(clear_calls))


class TestUserMoveLegalFenPublication(unittest.TestCase):
    def setUp(self):
        self.source_text = Path(mainloop.__file__).read_text(encoding="utf-8")
        source = ast.parse(self.source_text)
        self.main_loop = next(
            node for node in ast.walk(source)
            if isinstance(node, ast.ClassDef) and node.name == "MainLoop"
        )
        self.controller = object.__new__(mainloop.MainLoop)
        self.controller.state = SimpleNamespace(
            interaction_mode=Mode.NORMAL,
            last_legal_fens=[],
            legal_fens=["stale"],
            game=chess.Board(),
            get_variant_board=lambda: None,
        )

    def test_playing_mode_publishes_replacement_positions_and_clears_current_cache(self):
        previous_legal_fens = ["position after Ke1", "position after Kg2"]

        self.controller._publish_user_move_legal_fens(previous_legal_fens)

        self.assertEqual(previous_legal_fens, self.controller.state.last_legal_fens)
        self.assertEqual([], self.controller.state.legal_fens)

    def test_analysis_mode_refreshes_current_position_alternatives(self):
        self.controller.state.interaction_mode = Mode.ANALYSIS
        previous_legal_fens = ["previous position"]

        self.controller._publish_user_move_legal_fens(previous_legal_fens)

        self.assertEqual(previous_legal_fens, self.controller.state.last_legal_fens)
        self.assertEqual(
            mainloop.compute_legal_fens(self.controller.state.game),
            self.controller.state.legal_fens,
        )

    def test_publication_occurs_after_push_and_before_tutor_await(self):
        user_move = next(
            node for node in self.main_loop.body
            if getattr(node, "name", None) == "user_move"
        )
        calls = [node for node in ast.walk(user_move) if isinstance(node, ast.Call)]
        state_push = next(
            node for node in calls
            if ast.get_source_segment(self.source_text, node.func) == "self.state.push_move"
        )
        publication = next(
            node for node in calls
            if ast.get_source_segment(self.source_text, node.func)
            == "self._publish_user_move_legal_fens"
        )
        tutor_push = next(
            node for node in calls
            if ast.get_source_segment(self.source_text, node.func)
            == "self.state.picotutor.push_move"
        )

        self.assertLess(state_push.lineno, publication.lineno)
        self.assertLess(publication.lineno, tutor_push.lineno)


class TestPonderHitContinuationClockEvents(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fire = AsyncMock()
        start_patch(self, mainloop.Observable, "fire", self.fire)
        self.controller = object.__new__(mainloop.MainLoop)
        self.board = chess.Board()
        self.pre_move_fen = self.board.fen()
        self.user_move = chess.Move.from_uci("e2e4")
        self.reply = chess.Move.from_uci("e7e5")
        self.controller.state = SimpleNamespace(
            game=self.board,
            get_fen=self.board.fen,
            best_sent_depth=SimpleNamespace(set_best=Mock()),
            pb_move=chess.Move.null(),
        )
        self.info = {
            "depth": 22,
            "pv": [self.user_move, self.reply, chess.Move.from_uci("g1f3")],
            "score": chess.engine.PovScore(chess.engine.Cp(30), chess.WHITE),
        }

    def fired_events(self):
        return [fired.args[0] for fired in self.fire.await_args_list]

    async def test_continuation_survives_the_user_move_push(self):
        events = await self.controller.send_analyse(
            self.info, self.pre_move_fen, ponder_move=self.reply, defer_events=True
        )
        self.fire.assert_not_awaited()
        self.assertEqual(3, len(events))
        # The depth handover is cached while the analysed position is still live.
        self.controller.state.best_sent_depth.set_best.assert_called_once_with(
            self.info, self.pre_move_fen, self.board, self.reply
        )
        self.board.push(self.user_move)
        await self.controller._publish_analysis_events_for_position(events, self.board.fen())

        published = self.fired_events()
        self.assertEqual(3, len(published))
        for event in published:
            with self.subTest(event=event):
                self.assertEqual(self.board.fen(), event.fen)
                self.assertTrue(analysis_event_matches_position(event.fen, self.board.fen()))
        self.board.push(self.reply)
        for event in published:
            with self.subTest(stale_event=event):
                self.assertFalse(analysis_event_matches_position(event.fen, self.board.fen()))

    async def test_regular_clock_analysis_stays_tied_to_its_position(self):
        await self.controller.send_analyse(self.info, self.pre_move_fen)
        self.board.push(self.user_move)

        events = self.fired_events()
        self.assertEqual(3, len(events))
        for event in events:
            with self.subTest(event=event):
                self.assertFalse(analysis_event_matches_position(event.fen, self.board.fen()))

    def test_user_move_publishes_continuation_after_push(self):
        source_text = Path(mainloop.__file__).read_text(encoding="utf-8")
        source = ast.parse(source_text)
        user_move = next(
            node for node in ast.walk(source)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "user_move"
        )
        calls = [
            node for node in ast.walk(user_move)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "send_analyse"
        ]

        self.assertEqual(1, len(calls))
        keywords = {keyword.arg: keyword.value for keyword in calls[0].keywords}
        self.assertIs(True, keywords["defer_events"].value)
        # user_move also calls self.state.picotutor.push_move, so match the game push exactly.
        push = next(
            node for node in ast.walk(user_move)
            if isinstance(node, ast.Call)
            and ast.get_source_segment(source_text, node.func) == "self.state.push_move"
        )
        publish = next(
            node for node in ast.walk(user_move)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_publish_analysis_events_for_position"
        )
        self.assertLess(calls[0].lineno, push.lineno)
        self.assertLess(push.lineno, publish.lineno)
