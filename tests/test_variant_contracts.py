import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import chess
import chess.variant

from dgt.menu import DgtMenu
from dgt.translate import DgtTranslate
from dgt.util import GameResult
from mainloop import MainLoop
from picostate import PicochessState
from timecontrol import TimeControl


class TestVariantContracts(unittest.TestCase):
    """Exercise the board, legality, and result contract for every variant."""

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
        self.state = PicochessState(
            self.loop,
            Mock(spec=DgtTranslate),
            Mock(spec=DgtMenu),
        )
        self.state.time_control = TimeControl()

    def _assert_result(self, expected):
        message = self.state.check_game_state()
        self.assertTrue(message)
        self.assertEqual(expected, message.result)

    def test_variant_boards_keep_push_pop_and_checkpoint_in_sync(self):
        variants = {
            "atomic": chess.variant.AtomicBoard,
            "3check": chess.variant.ThreeCheckBoard,
            "racingkings": chess.variant.RacingKingsBoard,
            "antichess": chess.variant.AntichessBoard,
        }
        for name, board_class in variants.items():
            with self.subTest(variant=name):
                state = PicochessState(
                    self.loop,
                    Mock(spec=DgtTranslate),
                    Mock(spec=DgtMenu),
                )
                board = board_class()
                state.variant = name
                fen_parts = board.fen().split()
                if name == "3check":
                    fen_parts.pop(4)
                state.game = chess.Board(" ".join(fen_parts))
                setattr(state, {
                    "atomic": "_atomic_board",
                    "3check": "_threecheck_board",
                    "racingkings": "_racingkings_board",
                    "antichess": "_antichess_board",
                }[name], board)

                first_move = next(iter(board.legal_moves))
                state.push_move(first_move)
                state.save_position_checkpoint()
                checkpoint_fen = board.fen()
                second_move = next(iter(board.legal_moves))
                state.push_move(second_move)

                self.assertTrue(state.restore_position_checkpoint())
                self.assertEqual(checkpoint_fen, state.get_fen())
                self.assertEqual([first_move], state.game.move_stack)
                self.assertEqual([first_move], state.get_variant_board().move_stack)

                self.assertEqual(first_move, state.pop_move())
                self.assertEqual([], state.game.move_stack)
                self.assertEqual([], state.get_variant_board().move_stack)

                state.push_move(first_move)
                state.reset_variant_board()
                self.assertEqual([], state.get_variant_board().move_stack)

    def test_mainloop_selects_one_variant_board_and_clears_the_others(self):
        variants = {
            "atomic": chess.variant.AtomicBoard,
            "3check": chess.variant.ThreeCheckBoard,
            "racingkings": chess.variant.RacingKingsBoard,
            "antichess": chess.variant.AntichessBoard,
            "kingofthehill": None,
        }
        attributes = (
            "_atomic_board",
            "_threecheck_board",
            "_racingkings_board",
            "_antichess_board",
        )
        for name, board_class in variants.items():
            with self.subTest(variant=name):
                controller = object.__new__(MainLoop)
                controller.state = PicochessState(
                    self.loop,
                    Mock(spec=DgtTranslate),
                    Mock(spec=DgtMenu),
                )
                controller.state._atomic_board = chess.variant.AtomicBoard()
                controller.state.variant = "atomic"
                controller.engine = SimpleNamespace(variant=name)
                controller.shared = {}
                controller._clear_position_checkpoint = Mock()

                with patch("mainloop.ModeInfo.set_variant") as set_variant:
                    controller._init_variant_from_engine()

                self.assertEqual(name, controller.state.variant)
                self.assertEqual(name, controller.shared["variant"])
                set_variant.assert_called_once_with(name)
                for attribute in attributes:
                    selected = getattr(controller.state, attribute)
                    if board_class is not None and isinstance(selected, board_class):
                        self.assertIs(controller.state.get_variant_board(), selected)
                    else:
                        self.assertIsNone(selected)

    def test_switching_back_to_chess_clears_variant_state(self):
        controller = object.__new__(MainLoop)
        controller.state = self.state
        controller.state.variant = "atomic"
        controller.state._atomic_board = chess.variant.AtomicBoard()
        controller.engine = SimpleNamespace(variant="chess")
        controller.shared = {}
        controller._clear_position_checkpoint = Mock()

        with patch("mainloop.ModeInfo.set_variant"):
            controller._init_variant_from_engine()

        self.assertEqual("chess", controller.state.variant)
        self.assertIsNone(controller.state.get_variant_board())
        self.assertEqual(chess.STARTING_FEN, controller.state.game.fen())

    def test_atomic_move_uses_explosion_rules_and_ends_game(self):
        fen = "7k/6p1/8/8/8/8/6Q1/K7 w - - 0 1"
        self.state.variant = "atomic"
        self.state.game = chess.Board(fen)
        self.state._atomic_board = chess.variant.AtomicBoard(fen)
        move = chess.Move.from_uci("g2g7")

        self.assertTrue(self.state.get_move_check_board().is_legal(move))
        self.state.push_move(move)

        self.assertIsNone(self.state._atomic_board.king(chess.BLACK))
        self.assertIsNotNone(self.state.game.king(chess.BLACK))
        self._assert_result(GameResult.ATOMIC_WHITE)

    def test_threecheck_third_check_ends_game_and_preserves_counter(self):
        variant_fen = "7k/8/8/8/8/8/5R2/K7 w - - 1+3 0 1"
        self.state.variant = "3check"
        self.state.game = chess.Board("7k/8/8/8/8/8/5R2/K7 w - - 0 1")
        self.state._threecheck_board = chess.variant.ThreeCheckBoard(variant_fen)
        move = chess.Move.from_uci("f2f8")

        self.assertTrue(self.state.get_move_check_board().is_legal(move))
        self.state.push_move(move)

        self.assertTrue(self.state._threecheck_board.is_variant_end())
        self.assertIn("0+3", self.state.get_fen())
        self._assert_result(GameResult.THREE_CHECK_WHITE)

    def test_racing_kings_back_rank_move_ends_game(self):
        fen = "8/K7/8/8/8/8/7k/8 w - - 0 1"
        self.state.variant = "racingkings"
        self.state.game = chess.Board(fen)
        self.state._racingkings_board = chess.variant.RacingKingsBoard(fen)
        move = chess.Move.from_uci("a7a8")

        self.assertTrue(self.state.get_move_check_board().is_legal(move))
        self.state.push_move(move)

        self.assertTrue(self.state._racingkings_board.is_variant_end())
        self._assert_result(GameResult.RK_WHITE)

    def test_king_of_the_hill_center_move_ends_game(self):
        fen = "7k/8/8/8/8/3K4/8/8 w - - 0 1"
        self.state.variant = "kingofthehill"
        self.state.game = chess.Board(fen)
        move = chess.Move.from_uci("d3d4")

        self.assertIs(self.state.game, self.state.get_move_check_board())
        self.assertTrue(self.state.get_move_check_board().is_legal(move))
        self.state.push_move(move)

        self._assert_result(GameResult.KOTH_WHITE)

    def test_chess960_castling_uses_the_live_chess960_board(self):
        board = chess.Board.from_chess960_pos(0)
        for square, piece in list(board.piece_map().items()):
            if piece.color == chess.WHITE and piece.piece_type not in (chess.KING, chess.ROOK):
                board.remove_piece_at(square)
            elif piece.color == chess.BLACK and piece.piece_type != chess.KING:
                board.remove_piece_at(square)
        self.state.game = board
        castle = chess.Move.from_uci("g1f1")

        self.assertTrue(self.state.game.chess960)
        self.assertIs(self.state.game, self.state.get_move_check_board())
        self.assertTrue(self.state.get_move_check_board().is_castling(castle))
        self.assertTrue(self.state.get_move_check_board().is_legal(castle))
        self.state.push_move(castle)

        self.assertEqual(chess.KING, self.state.game.piece_type_at(chess.C1))
        self.assertEqual(chess.ROOK, self.state.game.piece_type_at(chess.D1))

    def test_antichess_piece_exhaustion_ends_game(self):
        fen = "8/8/8/8/8/8/8/7k w - - 0 1"
        self.state.variant = "antichess"
        self.state.game = chess.Board(fen)
        self.state._antichess_board = chess.variant.AntichessBoard(fen)

        self.assertTrue(self.state.get_move_check_board().is_variant_end())
        self._assert_result(GameResult.ANTICHESS_WHITE)


if __name__ == "__main__":
    unittest.main()
