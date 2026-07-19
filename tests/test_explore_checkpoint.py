import asyncio
import unittest

import chess
import chess.variant

from dgt.util import Mode, PlayMode, TimeMode
from picochess import PicochessState
from timecontrol import TimeControl


class TestExploreCheckpoint(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
        self.state = PicochessState(self.loop)

    def test_standard_checkpoint_restores_original_move_history(self):
        anchor_move = chess.Move.from_uci("e2e4")
        temporary_move = chess.Move.from_uci("e7e5")
        self.state.push_move(anchor_move)
        checkpoint_fen = self.state.game.fen()

        self.state.set_explore_checkpoint()
        self.state.push_move(temporary_move)

        self.assertTrue(self.state.restore_explore_checkpoint())
        self.assertEqual(checkpoint_fen, self.state.game.fen())
        self.assertEqual([anchor_move], self.state.game.move_stack)
        self.assertNotIn(temporary_move, self.state.game.move_stack)

    def test_checkpoint_is_independent_and_clear_discards_it(self):
        self.state.set_explore_checkpoint()
        self.state.game.remove_piece_at(chess.E2)

        self.assertTrue(self.state.restore_explore_checkpoint())
        self.assertEqual(chess.PAWN, self.state.game.piece_type_at(chess.E2))

        self.state.explore_surface = "brd"
        self.state.clear_explore_checkpoint()
        self.assertEqual("web", self.state.explore_surface)
        self.assertFalse(self.state.has_compatible_explore_checkpoint())

    def test_checkpoint_recovers_history_after_flexible_position_replacement(self):
        anchor_moves = [
            chess.Move.from_uci("e2e4"),
            chess.Move.from_uci("e7e5"),
            chess.Move.from_uci("g1f3"),
        ]
        for move in anchor_moves:
            self.state.push_move(move)
        checkpoint_fen = self.state.game.fen()
        self.state.set_explore_checkpoint()

        # Flexible PONDER can replace the board after fast or unsettled scans,
        # which necessarily drops the move history accumulated before Explore.
        self.state.game = chess.Board("8/8/8/3k4/8/4K3/8/8 w - - 0 1")
        self.assertEqual([], self.state.game.move_stack)

        self.assertTrue(self.state.restore_explore_checkpoint())
        self.assertEqual(checkpoint_fen, self.state.game.fen())
        self.assertEqual(anchor_moves, self.state.game.move_stack)

    def test_checkpoint_cannot_cross_variant_change(self):
        self.state.set_explore_checkpoint()
        self.state.variant = "atomic"

        self.assertFalse(self.state.restore_explore_checkpoint())

    def test_variant_checkpoint_restores_original_move_history(self):
        self.state.variant = "atomic"
        self.state._atomic_board = chess.variant.AtomicBoard()
        anchor_move = chess.Move.from_uci("e2e4")
        temporary_move = chess.Move.from_uci("e7e5")
        self.state.push_move(anchor_move)
        checkpoint_fen = self.state._atomic_board.fen()

        self.state.set_explore_checkpoint()
        self.state.push_move(temporary_move)

        self.assertTrue(self.state.restore_explore_checkpoint())
        self.assertEqual(checkpoint_fen, self.state._atomic_board.fen())
        self.assertEqual([anchor_move], self.state._atomic_board.move_stack)
        self.assertEqual([anchor_move], self.state.game.move_stack)
        self.assertNotIn(temporary_move, self.state._atomic_board.move_stack)

    def test_checkpoint_restores_playing_and_clock_context_but_leaves_clock_stopped(self):
        anchor_move = chess.Move.from_uci("e2e4")
        self.state.push_move(anchor_move)
        self.state.explore_origin_mode = Mode.NORMAL
        self.state.play_mode = PlayMode.USER_BLACK
        self.state.game_started = True
        self.state.time_control = TimeControl(
            mode=TimeMode.BLITZ,
            blitz=5,
            internal_time={chess.WHITE: 247.5, chess.BLACK: 231.25},
        )
        self.state.time_control.clock_time = {chess.WHITE: 247, chess.BLACK: 231}
        self.state.time_control.moves_to_go = 7

        self.state.set_explore_checkpoint()
        self.state.play_mode = PlayMode.USER_WHITE
        self.state.game_started = False
        self.state.time_control.internal_time[chess.WHITE] = 12
        self.state.time_control.clock_time[chess.BLACK] = 9
        self.state.time_control.moves_to_go = 1

        self.assertTrue(self.state.restore_explore_checkpoint())
        self.assertEqual(PlayMode.USER_BLACK, self.state.play_mode)
        self.assertTrue(self.state.game_started)
        self.assertEqual(247.5, self.state.time_control.internal_time[chess.WHITE])
        self.assertEqual(231.25, self.state.time_control.internal_time[chess.BLACK])
        self.assertEqual({chess.WHITE: 247, chess.BLACK: 231}, self.state.time_control.clock_time)
        self.assertEqual(7, self.state.time_control.moves_to_go)
        self.assertFalse(self.state.time_control.internal_running())
        self.assertTrue(self.state.can_preserve_restored_explore_play_mode(Mode.NORMAL))
        self.assertFalse(self.state.can_preserve_restored_explore_play_mode(Mode.BRAIN))

    def test_return_play_mode_context_only_survives_an_unchanged_completed_restore(self):
        self.state.explore_origin_mode = Mode.NORMAL
        self.state.set_explore_checkpoint()
        self.assertTrue(self.state.restore_explore_checkpoint())

        self.state.clear_explore_checkpoint(preserve_return_context=True)
        self.assertTrue(self.state.can_preserve_restored_explore_play_mode(Mode.NORMAL))

        self.state.push_move(chess.Move.from_uci("e2e4"))
        self.assertFalse(self.state.can_preserve_restored_explore_play_mode(Mode.NORMAL))

        self.state.clear_explore_checkpoint()
        self.assertIsNone(self.state.explore_return_play_mode)

    def test_physical_explore_marks_supported_brd_and_sync_as_temporary(self):
        for mode in (Mode.PONDER, Mode.ANALYSIS, Mode.KIBITZ):
            with self.subTest(mode=mode):
                self.state.interaction_mode = mode
                self.state.explore_surface = "web"
                self.assertFalse(self.state.physical_explore_active())

                self.state.explore_surface = "brd"
                self.assertTrue(self.state.physical_explore_active())

                self.state.explore_surface = "sync"
                self.assertTrue(self.state.physical_explore_active())

        self.state.interaction_mode = Mode.NORMAL
        self.assertFalse(self.state.physical_explore_active())


if __name__ == "__main__":
    unittest.main()
