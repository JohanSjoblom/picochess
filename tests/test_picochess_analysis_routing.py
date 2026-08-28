import unittest

import chess

from dgt.api import Message
from dgt.util import Mode
from picochess import (
    loaded_pgn_interaction_mode,
    mame_requires_fresh_fen_root,
    pgn_with_board_as_fresh_root,
    remote_move_matches_current_position,
    selected_engine_analysis_multipv,
    should_block_takeback,
    should_show_setpieces_after_lift_timeout,
    should_reject_user_move_after_game_end,
    should_load_pgn_moves,
    should_preserve_loaded_pgn_history,
    should_preserve_set_position_history,
    should_stop_analysis_after_game_end,
    should_use_tutor_analysis,
    setup_position_game,
    tutor_analysis_allowed_in_mode,
    user_move_pre_search_messages,
    web_analysis_payload,
)


class TestPicochessAnalysisRouting(unittest.TestCase):
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
