import unittest

import chess

from picochess import BestSeenDepth


class TestBestSeenDepth(unittest.TestCase):
    def test_reset_allows_lower_depth_after_position_handover(self):
        tracker = BestSeenDepth()
        board = chess.Board()
        info = {"depth": 37}
        ponder_move = chess.Move.from_uci("e2e4")

        tracker.set_best(info, board.fen(), board, ponder_move)

        next_board = board.copy()
        next_board.push(ponder_move)
        next_info = {"depth": 25}

        self.assertFalse(tracker.is_better(next_info, next_board.fen(), next_board))

        tracker.reset()

        self.assertTrue(tracker.is_better(next_info, next_board.fen(), next_board))
