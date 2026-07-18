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

    def test_standard_checkpoint_restores_position_without_move_history(self):
        self.state.push_move(chess.Move.from_uci("e2e4"))
        checkpoint_fen = self.state.game.fen()

        self.state.set_explore_checkpoint()
        self.state.push_move(chess.Move.from_uci("e7e5"))

        self.assertTrue(self.state.restore_explore_checkpoint())
        self.assertEqual(checkpoint_fen, self.state.game.fen())
        self.assertEqual([], self.state.game.move_stack)

    def test_checkpoint_is_independent_and_clear_discards_it(self):
        self.state.set_explore_checkpoint()
        self.state.game.remove_piece_at(chess.E2)

        self.assertTrue(self.state.restore_explore_checkpoint())
        self.assertEqual(chess.PAWN, self.state.game.piece_type_at(chess.E2))

        self.state.explore_surface = "brd"
        self.state.clear_explore_checkpoint()
        self.assertEqual("web", self.state.explore_surface)
        self.assertFalse(self.state.has_compatible_explore_checkpoint())

    def test_checkpoint_cannot_cross_variant_change(self):
        self.state.set_explore_checkpoint()
        self.state.variant = "atomic"

        self.assertFalse(self.state.restore_explore_checkpoint())

    def test_variant_checkpoint_restores_variant_position_without_history(self):
        self.state.variant = "atomic"
        self.state._atomic_board = chess.variant.AtomicBoard()
        move = chess.Move.from_uci("e2e4")
        self.state.push_move(move)
        checkpoint_fen = self.state._atomic_board.fen()

        self.state.set_explore_checkpoint()
        self.state.push_move(chess.Move.from_uci("e7e5"))

        self.assertTrue(self.state.restore_explore_checkpoint())
        self.assertEqual(checkpoint_fen, self.state._atomic_board.fen())
        self.assertEqual([], self.state._atomic_board.move_stack)
        self.assertEqual([], self.state.game.move_stack)


if __name__ == "__main__":
    unittest.main()
