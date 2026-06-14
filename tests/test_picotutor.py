import unittest
from unittest.mock import AsyncMock, Mock

import chess
import chess.pgn

from picotutor import PicoTutor
from uci.engine import UciShell


class TestPicotutor(unittest.TestCase):
    def __init__(self, tests=()):
        super().__init__(tests)
        self.uci_shell = UciShell(hostname="", username="", key_file="", password="")

    def test_find_longest_matching_opening_kings_pawn(self):
        tutor = PicoTutor(i_ucishell=self.uci_shell, i_engine_path="engines/x86_64/a-stock8")
        opening_name, _, _ = tutor._find_longest_matching_opening("e4")
        self.assertEqual(opening_name, "Kings Pawn")

    def test_find_longest_matching_opening_open_game(self):
        tutor = PicoTutor(i_ucishell=self.uci_shell, i_engine_path="engines/x86_64/a-stock8")
        opening_name, _, _ = tutor._find_longest_matching_opening("e4 e5 Nf3 Nc6")
        self.assertEqual(opening_name, "Open Game")

    def test_find_longest_matching_opening_italian_game(self):
        tutor = PicoTutor(i_ucishell=self.uci_shell, i_engine_path="engines/x86_64/a-stock8")
        opening_name, _, _ = tutor._find_longest_matching_opening("e4 e5 Nf3 Nc6 Bc4")
        self.assertEqual(opening_name, "Italian Game")

    def test_find_longest_matching_opening_can_be_called_multiple_times(self):
        tutor = PicoTutor(i_ucishell=self.uci_shell, i_engine_path="engines/x86_64/a-stock8")
        opening_name, _, _ = tutor._find_longest_matching_opening("e4")
        self.assertEqual(opening_name, "Kings Pawn")

        opening_name, _, _ = tutor._find_longest_matching_opening("e4 e5")
        self.assertEqual(opening_name, "Open Game")

    def test_get_eval_mistakes_includes_impact_metadata(self):
        tutor = PicoTutor.__new__(PicoTutor)
        move = chess.Move.from_uci("e2e4")
        tutor.evaluated_moves = {
            (1, move, chess.BLACK): {
                "CPL": 126.4,
                "score": -84,
                "mate": -3,
                "user_move": "e4",
                "best_move": "Nf3",
                "nag": chess.pgn.NAG_MISTAKE,
            }
        }

        self.assertEqual(
            tutor.get_eval_mistakes(),
            [
                {
                    "halfmove": 1,
                    "move_no": "1.",
                    "user_move": "e4",
                    "best_move": "Nf3",
                    "cpl": 126,
                    "centipawn_loss": 126,
                    "nag": "?",
                    "score": -84,
                    "mate": -3,
                }
            ],
        )

    def test_get_user_move_eval_stores_better_pv_variations(self):
        tutor = PicoTutor.__new__(PicoTutor)
        e4 = chess.Move.from_uci("e2e4")
        nf3 = chess.Move.from_uci("g1f3")
        tutor.board = chess.Board()
        tutor.board.push(e4)
        tutor.coach_on = True
        tutor.watcher_on = False
        tutor.evaluated_moves = {}
        tutor.op = []
        tutor.hint_move = {chess.WHITE: chess.Move.null(), chess.BLACK: chess.Move.null()}
        tutor.best_history = {chess.WHITE: [], chess.BLACK: [(0, e4, 0, 0)]}
        tutor.obvious_history = {chess.WHITE: [], chess.BLACK: [(0, e4, 0, 0)]}
        tutor.best_moves = {chess.WHITE: [], chess.BLACK: [(1, nf3, 1000, 0), (0, e4, 0, 0)]}
        tutor.best_info = {
            chess.WHITE: [],
            chess.BLACK: [
                {"pv": [e4, chess.Move.from_uci("e7e5")]},
                {"pv": [nf3, chess.Move.from_uci("d7d5")]},
            ],
        }

        tutor.get_user_move_eval()

        value = tutor.evaluated_moves[(1, e4, chess.BLACK)]
        self.assertEqual(value["variations"], [{"moves": ["g1f3", "d7d5"], "score": 1000, "mate": 0}])

    def test_get_better_pv_variations_returns_only_higher_ranked_lines(self):
        tutor = PicoTutor.__new__(PicoTutor)
        nf3 = chess.Move.from_uci("g1f3")
        e4 = chess.Move.from_uci("e2e4")
        d4 = chess.Move.from_uci("d2d4")
        tutor.best_moves = {
            chess.WHITE: [(1, nf3, 40, 0), (0, e4, 20, 0), (2, d4, 10, 0)],
            chess.BLACK: [],
        }
        tutor.best_info = {
            chess.WHITE: [
                {"pv": [e4, chess.Move.from_uci("e7e5")]},
                {"pv": [nf3, chess.Move.from_uci("d7d5")]},
                {"pv": [d4, chess.Move.from_uci("g8f6")]},
            ],
            chess.BLACK: [],
        }

        self.assertEqual(
            tutor._get_better_pv_variations(chess.WHITE, e4),
            [{"moves": ["g1f3", "d7d5"], "score": 40, "mate": 0}],
        )

    def test_get_better_pv_variations_returns_none_when_user_move_is_best(self):
        tutor = PicoTutor.__new__(PicoTutor)
        nf3 = chess.Move.from_uci("g1f3")
        e4 = chess.Move.from_uci("e2e4")
        tutor.best_moves = {
            chess.WHITE: [(1, nf3, 40, 0), (0, e4, 20, 0)],
            chess.BLACK: [],
        }
        tutor.best_info = {
            chess.WHITE: [
                {"pv": [e4, chess.Move.from_uci("e7e5")]},
                {"pv": [nf3, chess.Move.from_uci("d7d5")]},
            ],
            chess.BLACK: [],
        }

        self.assertEqual(tutor._get_better_pv_variations(chess.WHITE, nf3), [])

    def test_get_better_pv_variations_caps_missing_user_move_at_three_lines(self):
        tutor = PicoTutor.__new__(PicoTutor)
        moves = [
            chess.Move.from_uci("g1f3"),
            chess.Move.from_uci("e2e4"),
            chess.Move.from_uci("d2d4"),
            chess.Move.from_uci("c2c4"),
        ]
        tutor.best_moves = {
            chess.WHITE: [
                (0, moves[0], 40, 0),
                (1, moves[1], 30, 0),
                (2, moves[2], 20, 0),
                (3, moves[3], 10, 0),
            ],
            chess.BLACK: [],
        }
        tutor.best_info = {
            chess.WHITE: [
                {"pv": [moves[0], chess.Move.from_uci("d7d5")]},
                {"pv": [moves[1], chess.Move.from_uci("e7e5")]},
                {"pv": [moves[2], chess.Move.from_uci("g8f6")]},
                {"pv": [moves[3], chess.Move.from_uci("e7e6")]},
            ],
            chess.BLACK: [],
        }

        variations = tutor._get_better_pv_variations(chess.WHITE, chess.Move.from_uci("b1c3"))

        self.assertEqual([variation["moves"][0] for variation in variations], ["g1f3", "e2e4", "d2d4"])
        self.assertEqual(len(variations), 3)


class TestPicotutorAnalysisControl(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.uci_shell = UciShell(hostname="", username="", key_file="", password="")

    async def test_set_analysis_enabled_false_disables_running_tutor_analysis(self):
        tutor = PicoTutor(i_ucishell=self.uci_shell, i_engine_path="engines/x86_64/a-stock8")
        tutor.watcher_on = True
        tutor.best_engine = Mock()
        tutor.best_engine.loaded_ok.return_value = True
        tutor.best_engine.stop = AsyncMock()
        tutor.obvious_engine = Mock()
        tutor.obvious_engine.stop = AsyncMock()

        self.assertTrue(tutor.can_use_coach_analyser())

        await tutor.set_analysis_enabled(False)

        self.assertFalse(tutor.can_use_coach_analyser())
        tutor.best_engine.stop.assert_awaited_once()
        tutor.obvious_engine.stop.assert_awaited_once()
