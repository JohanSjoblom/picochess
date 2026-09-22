import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import chess

from alternative_mover import AlternativeMover


class TestAlternativeMover(unittest.TestCase):
    def test_excluded_moves_reset_when_no_legal_moves_remain(self):
        mover = AlternativeMover()
        board = chess.Board()
        legal_moves = set(board.legal_moves)
        for move in legal_moves:
            mover.exclude(move)

        self.assertEqual(legal_moves, mover.all(board))
        self.assertEqual(legal_moves, mover.all(board))

    def test_book_choice_excludes_move_and_returns_ponder(self):
        mover = AlternativeMover()
        board = chess.Board()
        move = chess.Move.from_uci("e2e4")
        reply = chess.Move.from_uci("e7e5")
        reader = Mock()
        reader.weighted_choice.side_effect = [
            SimpleNamespace(move=move),
            SimpleNamespace(move=reply),
        ]

        choice = mover.book(reader, board)

        self.assertEqual(move, choice.move)
        self.assertEqual(reply, choice.ponder)
        # book() advances the supplied board to find a ponder move; callers pass a throwaway copy.
        self.assertEqual([move], board.move_stack)
        self.assertNotIn(move, mover.all(chess.Board()))

    def test_missing_book_move_returns_none_without_changing_board(self):
        mover = AlternativeMover()
        board = chess.Board()
        reader = Mock()
        reader.weighted_choice.side_effect = IndexError

        self.assertIsNone(mover.book(reader, board))
        self.assertEqual([], board.move_stack)
