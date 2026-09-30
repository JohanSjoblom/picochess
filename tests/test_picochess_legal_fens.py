import unittest

import chess
import chess.variant

from board_position import compute_legal_fens


class TestComputeLegalFens(unittest.TestCase):
    @staticmethod
    def _legal_fens_with_full_history(board):
        board_copy = board.copy()
        fens = []
        for move in board_copy.legal_moves:
            board_copy.push(move)
            fens.append(board_copy.board_fen())
            board_copy.pop()
        return fens

    def test_standard_board_and_history_are_unchanged(self):
        board = chess.Board()
        board.push_uci("e2e4")
        board.push_uci("e7e5")
        original_fen = board.fen()
        original_stack = tuple(board.move_stack)

        legal_fens = compute_legal_fens(board)

        self.assertEqual(len(legal_fens), board.legal_moves.count())
        self.assertEqual(board.fen(), original_fen)
        self.assertEqual(tuple(board.move_stack), original_stack)

    def test_history_does_not_affect_legal_fen_output(self):
        board_with_history = chess.Board()
        board_with_history.push_uci("g1f3")
        board_with_history.push_uci("g8f6")
        stackless_board = board_with_history.copy(stack=False)

        self.assertEqual(compute_legal_fens(board_with_history), compute_legal_fens(stackless_board))

    def test_variant_board_and_history_are_unchanged(self):
        standard_board = chess.Board()
        variant_board = chess.variant.AtomicBoard()
        variant_board.push_uci("e2e4")
        original_fen = variant_board.fen()
        original_stack = tuple(variant_board.move_stack)

        legal_fens = compute_legal_fens(standard_board, variant_board)

        self.assertEqual(len(legal_fens), variant_board.legal_moves.count())
        self.assertEqual(variant_board.fen(), original_fen)
        self.assertEqual(tuple(variant_board.move_stack), original_stack)

    def test_threecheck_state_produces_same_fens_without_copying_history(self):
        variant_board = chess.variant.ThreeCheckBoard()
        for move in ("e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6", "h5f7"):
            variant_board.push_uci(move)
        original_fen = variant_board.fen()
        original_stack = tuple(variant_board.move_stack)

        legal_fens = compute_legal_fens(chess.Board(), variant_board)

        self.assertEqual(legal_fens, self._legal_fens_with_full_history(variant_board))
        self.assertEqual(variant_board.fen(), original_fen)
        self.assertEqual(tuple(variant_board.move_stack), original_stack)
