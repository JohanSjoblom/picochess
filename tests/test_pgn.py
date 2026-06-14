import asyncio

import chess  # type: ignore[import]
import datetime
import unittest

from dgt.util import PlayMode
from pgn import PgnDisplay, add_picotutor_variations_to_game

EMPTY_GAME = """[Event "PicoChess Game"]
[Site "?"]
[Date "{0}"]
[Round "?"]
[White "?"]
[Black "?"]
[Result "*"]
[Time "{1}"]
[WhiteElo "-"]
[BlackElo "-"]
[PicoTimeControl "0"]
[PicoRemTimeW "0"]
[PicoRemTimeB "0"]

*"""


class FakeMessage:
    def __init__(self, game, play_mode):
        self.game = game
        self.play_mode = play_mode
        self.tc_init = {"internal_time": {chess.WHITE: 0, chess.BLACK: 0}}


class FakePicoTutor:
    def __init__(self, eval_moves):
        self.eval_moves = eval_moves

    def get_eval_moves(self):
        return self.eval_moves


class TestPgnDisplay(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.testee = PgnDisplay("test", None, {}, self.loop)

    def test_generate_pgn(self):
        game = chess.Board()
        msg = FakeMessage(game, PlayMode.USER_WHITE)

        pgn = self.testee._generate_pgn_from_message(msg)
        empty_game = EMPTY_GAME.format(datetime.date.today().strftime("%Y.%m.%d"), self.testee.startime)

        self.assertEqual(str(pgn), empty_game)

    def test_add_picotutor_evaluation_adds_better_pv_as_sibling_variation(self):
        board = chess.Board()
        user_move = chess.Move.from_uci("e2e4")
        board.push(user_move)
        game = chess.pgn.Game.from_board(board)
        self.testee.set_picotutor(
            FakePicoTutor(
                {
                    (1, user_move, chess.BLACK): {
                        "nag": chess.pgn.NAG_MISTAKE,
                        "best_move": "Nf3",
                        "user_move": "e4",
                        "CPL": 1000,
                        "score": 0,
                        "variations": [{"moves": ["g1f3", "d7d5"], "score": 1000, "mate": 0}],
                    }
                }
            )
        )

        self.testee.add_picotutor_evaluation(game)

        self.assertEqual([variation.move.uci() for variation in game.variations], ["e2e4", "g1f3"])
        side_line = game.variations[1]
        self.assertEqual(side_line.parent, game)
        self.assertEqual(side_line.variations[0].move.uci(), "d7d5")

    def test_add_picotutor_evaluation_does_not_duplicate_existing_first_move(self):
        board = chess.Board()
        user_move = chess.Move.from_uci("e2e4")
        board.push(user_move)
        game = chess.pgn.Game.from_board(board)
        self.testee.set_picotutor(
            FakePicoTutor(
                {
                    (1, user_move, chess.BLACK): {
                        "nag": chess.pgn.NAG_MISTAKE,
                        "best_move": "Nf3",
                        "user_move": "e4",
                        "CPL": 1000,
                        "score": 0,
                        "variations": [{"moves": ["g1f3", "d7d5"], "score": 1000, "mate": 0}],
                    }
                }
            )
        )

        self.testee.add_picotutor_evaluation(game)
        self.testee.add_picotutor_evaluation(game)

        self.assertEqual([variation.move.uci() for variation in game.variations], ["e2e4", "g1f3"])

    def test_add_picotutor_evaluation_ignores_invalid_variation_data(self):
        board = chess.Board()
        user_move = chess.Move.from_uci("e2e4")
        board.push(user_move)
        game = chess.pgn.Game.from_board(board)
        self.testee.set_picotutor(
            FakePicoTutor(
                {
                    (1, user_move, chess.BLACK): {
                        "nag": chess.pgn.NAG_MISTAKE,
                        "best_move": "Nf3",
                        "user_move": "e4",
                        "CPL": 1000,
                        "score": 0,
                        "variations": [
                            {"moves": ["not-a-move"], "score": 1000, "mate": 0},
                            {"moves": ["e7e5"], "score": 900, "mate": 0},
                        ],
                    }
                }
            )
        )

        self.testee.add_picotutor_evaluation(game)

        self.assertEqual([variation.move.uci() for variation in game.variations], ["e2e4"])

    def test_add_picotutor_variations_to_game_exports_without_comments(self):
        board = chess.Board()
        user_move = chess.Move.from_uci("e2e4")
        board.push(user_move)
        game = chess.pgn.Game.from_board(board)
        add_picotutor_variations_to_game(
            game,
            FakePicoTutor(
                {
                    (1, user_move, chess.BLACK): {
                        "variations": [{"moves": ["g1f3", "d7d5"], "score": 1000, "mate": 0}],
                    }
                }
            ),
        )

        pgn_text = game.accept(chess.pgn.StringExporter(headers=False, comments=False, variations=True))

        self.assertEqual(pgn_text, "1. e4 ( 1. Nf3 d5 ) *")
