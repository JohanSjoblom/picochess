import asyncio
import unittest

import chess
import chess.variant

from picochess import PicochessState


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


if __name__ == "__main__":
    unittest.main()
