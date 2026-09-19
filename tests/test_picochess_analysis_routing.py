import ast
import unittest
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

import chess
import chess.variant

import picochess

from dgt.api import Event, Message
from dgt.util import Mode
from picochess import (
    AnalysisCycleAction,
    AnalysisCycleContext,
    AnalysisSourceAction,
    AnalysisSourceContext,
    GameEndAnalysisContext,
    TutorAnalysisContext,
    analysis_event_matches_position,
    board_fen_after_move,
    decide_analysis_cycle_action,
    decide_analysis_source,
    decide_game_end_analysis_stop,
    decide_tutor_analysis,
    depth_gated_analysis_info,
    engine_move_event_matches_state,
    loaded_pgn_interaction_mode,
    localize_web_san,
    mame_requires_fresh_fen_root,
    pgn_with_board_as_fresh_root,
    previous_position_matching_board_fen,
    RK_STARTING_BOARD_FEN,
    pending_set_position_fen_action,
    remote_move_matches_current_position,
    rollback_picotutor_for_alternative,
    selected_engine_analysis_depth,
    selected_engine_analysis_multipv,
    set_position_new_game_code,
    should_block_takeback,
    should_show_setpieces_after_lift_timeout,
    should_reject_user_move_after_game_end,
    should_process_sliding_move,
    should_resume_game_after_takeback,
    should_resume_clock_after_rejected_engine_move,
    should_report_local_timeout,
    should_load_pgn_moves,
    should_preserve_loaded_pgn_history,
    should_preserve_set_position_history,
    should_stop_analysis_after_game_end,
    should_use_tutor_analysis,
    setup_position_game,
    tutor_analysis_allowed_in_mode,
    user_move_pre_search_messages,
    user_move_task_matches_position,
    web_analysis_payload,
)


class TestLocalTimeoutPolicy(unittest.TestCase):
    def test_local_timeout_is_reported(self):
        self.assertTrue(should_report_local_timeout(False))

    def test_online_timeout_is_left_to_server(self):
        self.assertFalse(should_report_local_timeout(True))


class TestRepeatedLocalTimeoutHandling(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        source = ast.parse(Path(picochess.__file__).read_text(encoding="utf-8"))
        main_loop = next(
            node for node in ast.walk(source)
            if isinstance(node, ast.ClassDef) and node.name == "MainLoop"
        )
        method = next(
            node for node in main_loop.body
            if getattr(node, "name", None) == "process_main_events"
        )
        self.show = AsyncMock()
        namespace = dict(vars(picochess))
        namespace["DisplayMsg"] = SimpleNamespace(show=self.show)
        exec(
            compile(
                ast.Module(body=[method], type_ignores=[]),
                picochess.__file__,
                "exec",
            ),
            namespace,
        )
        controller_type = type(
            "TimeoutController",
            (),
            {"process_main_events": namespace["process_main_events"]},
        )
        self.controller = controller_type()
        self.controller.state = SimpleNamespace(
            position_checkpoint_restore_pending=False,
            stop_clock=AsyncMock(),
        )
        self.controller.online_mode = Mock(return_value=False)

    async def test_each_local_flag_fall_is_reported(self):
        event = Event.OUT_OF_TIME(color=chess.WHITE)

        await self.controller.process_main_events(event)
        await self.controller.process_main_events(event)

        self.assertEqual(2, self.controller.state.stop_clock.await_count)
        self.assertEqual(2, self.show.await_count)
        self.assertTrue(
            all(
                isinstance(args[0], Message.LOST_ON_TIME)
                for args, _ in self.show.await_args_list
            )
        )


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

    def test_web_san_uses_interface_piece_letters(self):
        expected_piece_letters = {
            "en": "KQRBN",
            "de": "KDTLS",
            "nl": "KDTLP",
            "fr": "RDTFC",
            "es": "RDTAC",
            "it": "RDTAC",
        }
        for language, expected in expected_piece_letters.items():
            with self.subTest(language=language):
                self.assertEqual(expected, localize_web_san("KQRBN", language))

        self.assertEqual("Dxd5+", localize_web_san("Qxd5+", "nl"))
        self.assertEqual("e8=P+", localize_web_san("e8=N+", "nl"))

    def test_web_san_keeps_english_and_unknown_languages_unchanged(self):
        self.assertEqual("Nc6", localize_web_san("Nc6", "en"))
        self.assertEqual("Nc6", localize_web_san("Nc6", "unknown"))

    def test_web_analysis_payload_localizes_each_pv_move(self):
        board = chess.Board()
        info_list = [
            {
                "depth": 10,
                "score": chess.engine.PovScore(chess.engine.Cp(25), chess.WHITE),
                "pv": [chess.Move.from_uci("g1f3"), chess.Move.from_uci("g8f6")],
            }
        ]

        payload = web_analysis_payload(info_list, board.fen(), "engine", language="nl")

        self.assertEqual(["Pf3", "Pf6"], payload["pv"])

    def test_new_game_clears_preserved_mame_history(self):
        source = (Path(__file__).parents[1] / "picochess.py").read_text(encoding="utf-8")
        new_game_handler = source.split("elif isinstance(event, Event.NEW_GAME):", 1)[1]

        self.assertIn("clear_preserved_mame_history(self.shared)", new_game_handler[:500])

    def test_successful_engine_change_clears_preserved_mame_history(self):
        source = (Path(__file__).parents[1] / "picochess.py").read_text(encoding="utf-8")
        success_branch = """else:
                    clear_preserved_mame_history(self.shared)
                    self.state.searchmoves.reset()
                    msg = Message.ENGINE_READY("""

        self.assertIn(success_branch, source)

    @patch("picochess.platform.machine", return_value="aarch64")
    def test_aarch64_non_playing_modes_cap_selected_engine_depth(self, _machine):
        self.assertEqual(30, selected_engine_analysis_depth(engine_plays=False))

    @patch("picochess.platform.machine", return_value="aarch64")
    def test_aarch64_playing_modes_keep_selected_engine_depth(self, _machine):
        self.assertEqual(40, selected_engine_analysis_depth(engine_plays=True))

    @patch("picochess.platform.machine", return_value="x86_64")
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
            should_use_tutor_analysis(
                interaction_mode=Mode.PONDER,
                pgn_mode=False,
                engine_should_skip_analyser=False,
                engine_is_playing=False,
                engine_move_was_book=False,
                is_user_turn=True,
            )
        )

    def test_non_playing_analysis_mode_still_prefers_tutor_when_allowed(self):
        self.assertTrue(tutor_analysis_allowed_in_mode(Mode.ANALYSIS))
        self.assertTrue(
            should_use_tutor_analysis(
                interaction_mode=Mode.ANALYSIS,
                pgn_mode=False,
                engine_should_skip_analyser=False,
                engine_is_playing=False,
                engine_move_was_book=False,
                is_user_turn=True,
            )
        )

    def test_playing_user_turn_prefers_tutor_for_cpu_saving(self):
        for engine_move_was_book in (False, True):
            with self.subTest(engine_move_was_book=engine_move_was_book):
                self.assertTrue(
                    should_use_tutor_analysis(
                        interaction_mode=Mode.NORMAL,
                        pgn_mode=False,
                        engine_should_skip_analyser=False,
                        engine_is_playing=True,
                        engine_move_was_book=engine_move_was_book,
                        is_user_turn=True,
                    )
                )

    def test_playing_engine_turn_keeps_tutor_out_of_playing_search(self):
        self.assertFalse(
            should_use_tutor_analysis(
                interaction_mode=Mode.NORMAL,
                pgn_mode=False,
                engine_should_skip_analyser=False,
                engine_is_playing=True,
                engine_move_was_book=False,
                is_user_turn=False,
            )
        )

    def test_tutor_analysis_routing_matrix(self):
        """Lock every current input combination before routing is reorganized."""
        for mode, pgn_mode, skip_engine, engine_plays, book_move, user_turn in product(
            Mode.items(),
            (False, True),
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
                book_move=book_move,
                user_turn=user_turn,
            ):
                self.assertEqual(
                    expected,
                    should_use_tutor_analysis(
                        interaction_mode=mode,
                        pgn_mode=pgn_mode,
                        engine_should_skip_analyser=skip_engine,
                        engine_is_playing=engine_plays,
                        engine_move_was_book=book_move,
                        is_user_turn=user_turn,
                    ),
                )
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
        source = ast.parse(Path(picochess.__file__).read_text(encoding="utf-8"))
        main_loop = next(
            node for node in ast.walk(source)
            if isinstance(node, ast.ClassDef) and node.name == "MainLoop"
        )
        method = next(
            node for node in main_loop.body
            if getattr(node, "name", None) == "_think_after_current_user_move"
        )
        namespace = dict(vars(picochess))
        exec(compile(ast.Module(body=[method], type_ignores=[]), picochess.__file__, "exec"), namespace)
        controller_type = type(
            "SearchOwnerController",
            (),
            {"_think_after_current_user_move": namespace["_think_after_current_user_move"]},
        )
        self.controller = controller_type()
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


class TestTutorMessageOwnership(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        source = ast.parse(Path(picochess.__file__).read_text(encoding="utf-8"))
        main_loop = next(
            node for node in ast.walk(source)
            if isinstance(node, ast.ClassDef) and node.name == "MainLoop"
        )
        method = next(
            node for node in main_loop.body
            if getattr(node, "name", None) == "_deliver_picotutor_messages"
        )
        self.show = AsyncMock()
        self.sleep = AsyncMock()
        namespace = dict(vars(picochess))
        namespace["DisplayMsg"] = SimpleNamespace(show=self.show)
        namespace["asyncio"] = SimpleNamespace(sleep=self.sleep)
        exec(compile(ast.Module(body=[method], type_ignores=[]), picochess.__file__, "exec"), namespace)
        controller_type = type(
            "TutorMessageOwnerController",
            (),
            {"_deliver_picotutor_messages": namespace["_deliver_picotutor_messages"]},
        )
        self.controller = controller_type()
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
        self.source = ast.parse(Path(picochess.__file__).read_text(encoding="utf-8"))
        self.main_loop = next(
            node for node in ast.walk(self.source)
            if isinstance(node, ast.ClassDef) and node.name == "MainLoop"
        )
        method = next(
            node for node in self.main_loop.body
            if getattr(node, "name", None) == "_invalidate_user_move_tasks"
        )
        namespace = dict(vars(picochess))
        exec(compile(ast.Module(body=[method], type_ignores=[]), picochess.__file__, "exec"), namespace)
        controller_type = type(
            "UserMoveInvalidationController",
            (),
            {"_invalidate_user_move_tasks": namespace["_invalidate_user_move_tasks"]},
        )
        self.controller = controller_type()
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


class TestAlternativeMovePendingState(unittest.TestCase):
    def setUp(self):
        source = ast.parse(Path(picochess.__file__).read_text(encoding="utf-8"))
        main_loop = next(
            node for node in ast.walk(source)
            if isinstance(node, ast.ClassDef) and node.name == "MainLoop"
        )
        method = next(
            node for node in main_loop.body
            if getattr(node, "name", None) == "_clear_pending_engine_move"
        )
        namespace = dict(vars(picochess))
        exec(compile(ast.Module(body=[method], type_ignores=[]), picochess.__file__, "exec"), namespace)
        controller_type = type(
            "AlternativeMoveController",
            (),
            {"_clear_pending_engine_move": namespace["_clear_pending_engine_move"]},
        )
        self.controller = controller_type()
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
        source = ast.parse(Path(picochess.__file__).read_text(encoding="utf-8"))
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
        self.source_text = Path(picochess.__file__).read_text(encoding="utf-8")
        source = ast.parse(self.source_text)
        self.main_loop = next(
            node for node in ast.walk(source)
            if isinstance(node, ast.ClassDef) and node.name == "MainLoop"
        )
        method = next(
            node for node in self.main_loop.body
            if getattr(node, "name", None) == "_publish_user_move_legal_fens"
        )
        namespace = dict(vars(picochess))
        exec(compile(ast.Module(body=[method], type_ignores=[]), picochess.__file__, "exec"), namespace)
        controller_type = type(
            "LegalFenPublicationController",
            (),
            {"_publish_user_move_legal_fens": namespace["_publish_user_move_legal_fens"]},
        )
        self.controller = controller_type()
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
            picochess.compute_legal_fens(self.controller.state.game),
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
