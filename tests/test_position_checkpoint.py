import asyncio
import unittest

import chess
import chess.variant

from dgt.util import Mode, PlayMode, TimeMode
from picochess import PicochessState
from timecontrol import TimeControl


class TestPositionCheckpoint(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
        self.state = PicochessState(self.loop)

    def test_checkpoint_restores_exact_position_and_move_history(self):
        anchor_moves = [
            chess.Move.from_uci("e2e4"),
            chess.Move.from_uci("e7e5"),
            chess.Move.from_uci("g1f3"),
        ]
        for move in anchor_moves:
            self.state.push_move(move)
        checkpoint_fen = self.state.game.fen()

        self.state.save_position_checkpoint()
        self.state.push_move(chess.Move.from_uci("b8c6"))

        self.assertTrue(self.state.restore_position_checkpoint())
        self.assertEqual(checkpoint_fen, self.state.game.fen())
        self.assertEqual(anchor_moves, self.state.game.move_stack)

    def test_checkpoint_is_reusable_until_cleared(self):
        self.state.save_position_checkpoint(interaction_mode=Mode.NORMAL)
        self.assertEqual(Mode.NORMAL, self.state.position_checkpoint_interaction_mode)
        self.state.game.remove_piece_at(chess.E2)

        self.assertTrue(self.state.restore_position_checkpoint())
        self.assertEqual(chess.PAWN, self.state.game.piece_type_at(chess.E2))

        self.state.game.remove_piece_at(chess.D2)
        self.assertTrue(self.state.restore_position_checkpoint())
        self.assertEqual(chess.PAWN, self.state.game.piece_type_at(chess.D2))

        self.state.clear_position_checkpoint()
        self.assertFalse(self.state.has_compatible_position_checkpoint())
        self.assertIsNone(self.state.position_checkpoint_interaction_mode)
        self.assertFalse(self.state.restore_position_checkpoint())

    def test_checkpoint_recovers_history_after_flexible_position_replacement(self):
        anchor_moves = [chess.Move.from_uci("e2e4"), chess.Move.from_uci("e7e5")]
        for move in anchor_moves:
            self.state.push_move(move)
        checkpoint_fen = self.state.game.fen()
        self.state.save_position_checkpoint()

        self.state.game = chess.Board("8/8/8/3k4/8/4K3/8/8 w - - 0 1")
        self.assertEqual([], self.state.game.move_stack)

        self.assertTrue(self.state.restore_position_checkpoint())
        self.assertEqual(checkpoint_fen, self.state.game.fen())
        self.assertEqual(anchor_moves, self.state.game.move_stack)

    def test_ponder_side_change_does_not_touch_checkpoint(self):
        anchor_moves = [chess.Move.from_uci("e2e4"), chess.Move.from_uci("e7e5")]
        for move in anchor_moves:
            self.state.push_move(move)
        checkpoint_fen = self.state.game.fen()
        self.state.interaction_mode = Mode.PONDER
        self.state.save_position_checkpoint()

        self.state.push_move(chess.Move.from_uci("g1f3"))
        self.state.game.ep_square = chess.E3
        castling_rights = self.state.game.castling_rights

        self.assertTrue(self.state.set_ponder_turn(chess.BLACK))
        self.assertEqual(chess.BLACK, self.state.game.turn)
        self.assertEqual([], self.state.game.move_stack)
        self.assertIsNone(self.state.game.ep_square)
        self.assertEqual(castling_rights, self.state.game.castling_rights)
        self.assertTrue(self.state.has_compatible_position_checkpoint())

        self.assertTrue(self.state.restore_position_checkpoint())
        self.assertEqual(checkpoint_fen, self.state.game.fen())
        self.assertEqual(anchor_moves, self.state.game.move_stack)

    def test_side_change_is_limited_to_standard_ponder(self):
        self.state.interaction_mode = Mode.ANALYSIS
        self.assertFalse(self.state.set_ponder_turn(chess.BLACK))

        self.state.interaction_mode = Mode.PONDER
        self.state.variant = "atomic"
        self.assertFalse(self.state.set_ponder_turn(chess.BLACK))

    def test_checkpoint_cannot_cross_variant_change(self):
        self.state.save_position_checkpoint()
        self.state.variant = "atomic"
        self.assertFalse(self.state.restore_position_checkpoint())

    def test_variant_checkpoint_restores_move_history(self):
        self.state.variant = "atomic"
        self.state._atomic_board = chess.variant.AtomicBoard()
        anchor_move = chess.Move.from_uci("e2e4")
        temporary_move = chess.Move.from_uci("e7e5")
        self.state.push_move(anchor_move)
        checkpoint_fen = self.state._atomic_board.fen()

        self.state.save_position_checkpoint()
        self.state.push_move(temporary_move)

        self.assertTrue(self.state.restore_position_checkpoint())
        self.assertEqual(checkpoint_fen, self.state._atomic_board.fen())
        self.assertEqual([anchor_move], self.state._atomic_board.move_stack)
        self.assertEqual([anchor_move], self.state.game.move_stack)

    def test_checkpoint_restores_play_and_clock_context_with_clock_stopped(self):
        self.state.push_move(chess.Move.from_uci("e2e4"))
        self.state.play_mode = PlayMode.USER_BLACK
        self.state.game_started = True
        self.state.time_control = TimeControl(
            mode=TimeMode.BLITZ,
            blitz=5,
            internal_time={chess.WHITE: 247.5, chess.BLACK: 231.25},
        )
        self.state.time_control.clock_time = {chess.WHITE: 247, chess.BLACK: 231}
        self.state.time_control.moves_to_go = 7

        self.state.save_position_checkpoint()
        self.state.play_mode = PlayMode.USER_WHITE
        self.state.game_started = False
        self.state.time_control.internal_time[chess.WHITE] = 12
        self.state.time_control.clock_time[chess.BLACK] = 9
        self.state.time_control.moves_to_go = 1

        self.assertTrue(self.state.restore_position_checkpoint())
        self.assertEqual(PlayMode.USER_BLACK, self.state.play_mode)
        self.assertTrue(self.state.game_started)
        self.assertEqual(247.5, self.state.time_control.internal_time[chess.WHITE])
        self.assertEqual(231.25, self.state.time_control.internal_time[chess.BLACK])
        self.assertEqual({chess.WHITE: 247, chess.BLACK: 231}, self.state.time_control.clock_time)
        self.assertEqual(7, self.state.time_control.moves_to_go)
        self.assertFalse(self.state.time_control.internal_running())
        self.assertTrue(self.state.can_preserve_position_checkpoint_play_mode())

        self.state.push_move(chess.Move.from_uci("e7e5"))
        self.assertFalse(self.state.can_preserve_position_checkpoint_play_mode())


if __name__ == "__main__":
    unittest.main()
