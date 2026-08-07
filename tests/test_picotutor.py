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
                "depth": 16,
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
                    "depth": 16,
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
        tutor.best_history = {chess.WHITE: [], chess.BLACK: [(0, e4, 0, 0, 10)]}
        tutor.obvious_history = {chess.WHITE: [], chess.BLACK: [(0, e4, 0, 0)]}
        tutor.best_moves = {chess.WHITE: [], chess.BLACK: [(1, nf3, 1000, 0), (0, e4, 0, 0)]}
        tutor.best_info = {
            chess.WHITE: [],
            chess.BLACK: [
                {"pv": [e4, chess.Move.from_uci("e7e5")], "depth": 10},
                {"pv": [nf3, chess.Move.from_uci("d7d5")], "depth": 10},
            ],
        }

        tutor.get_user_move_eval()

        value = tutor.evaluated_moves[(1, e4, chess.BLACK)]
        self.assertEqual(value["depth"], 10)
        self.assertEqual(value["variations"], [{"moves": ["g1f3", "d7d5"], "score": 1000, "mate": 0}])

    def test_get_user_move_eval_keeps_low_depth_as_internal_unrated_attempt(self):
        tutor = PicoTutor.__new__(PicoTutor)
        e4 = chess.Move.from_uci("e2e4")
        nf3 = chess.Move.from_uci("g1f3")
        tutor.board = chess.Board()
        tutor.board.push(e4)
        tutor.coach_on = True
        tutor.watcher_on = False
        tutor.evaluated_moves = {}
        tutor.best_history = {chess.WHITE: [], chess.BLACK: [(0, e4, 0, 0, 8)]}
        tutor.obvious_history = {chess.WHITE: [], chess.BLACK: [(0, e4, 0, 0)]}
        tutor.best_moves = {chess.WHITE: [], chess.BLACK: [(1, nf3, 200, 0), (0, e4, 0, 0)]}
        tutor.best_info = {
            chess.WHITE: [],
            chess.BLACK: [
                {"pv": [e4], "depth": 9},
                {"pv": [nf3], "depth": 8},
            ],
        }

        self.assertEqual(tutor.get_user_move_eval(), ("", 0))
        self.assertEqual(tutor.get_eval_moves(), {})
        self.assertEqual(tutor.get_eval_mistakes(), [])

    def test_get_user_move_eval_allows_low_depth_blunder_for_retro_takeback(self):
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
        tutor.best_history = {chess.WHITE: [], chess.BLACK: [(0, e4, 0, 0, 8)]}
        tutor.obvious_history = {chess.WHITE: [], chess.BLACK: [(0, e4, 0, 0)]}
        tutor.best_moves = {chess.WHITE: [], chess.BLACK: [(1, nf3, 300, 0), (0, e4, 0, 0)]}
        tutor.best_info = {
            chess.WHITE: [],
            chess.BLACK: [
                {"pv": [e4], "depth": 8},
                {"pv": [nf3], "depth": 9},
            ],
        }

        self.assertEqual(tutor.get_user_move_eval(), ("", 0))
        self.assertEqual(tutor.get_user_move_eval(allow_low_depth_blunder=True), ("??", 0))
        value = tutor.evaluated_moves[(1, e4, chess.BLACK)]
        self.assertEqual(value["quality_reason"], "retro_blunder_below_minimum_depth")
        self.assertEqual(value["CPL"], 300)
        self.assertEqual(tutor.get_eval_moves(), {})
        self.assertEqual(tutor.get_eval_mistakes(), [])

    def test_get_user_move_eval_reports_missing_analysis_as_unrated(self):
        tutor = PicoTutor.__new__(PicoTutor)
        e4 = chess.Move.from_uci("e2e4")
        tutor.board = chess.Board()
        tutor.board.push(e4)
        tutor.coach_on = False
        tutor.watcher_on = True
        tutor.evaluated_moves = {}
        tutor.best_info = {chess.WHITE: [], chess.BLACK: None}

        self.assertEqual(tutor.get_user_move_eval(), ("", 0))
        self.assertEqual(tutor.get_eval_mistakes(), [])

    def test_get_user_move_eval_ignores_depth_of_unrelated_multipv_line(self):
        tutor = PicoTutor.__new__(PicoTutor)
        e4 = chess.Move.from_uci("e2e4")
        nf3 = chess.Move.from_uci("g1f3")
        d4 = chess.Move.from_uci("d2d4")
        tutor.board = chess.Board()
        tutor.board.push(e4)
        tutor.coach_on = True
        tutor.watcher_on = False
        tutor.evaluated_moves = {}
        tutor.op = []
        tutor.hint_move = {chess.WHITE: chess.Move.null(), chess.BLACK: chess.Move.null()}
        tutor.best_history = {chess.WHITE: [], chess.BLACK: [(0, e4, 0, 0, 15)]}
        tutor.obvious_history = {chess.WHITE: [], chess.BLACK: [(0, e4, 0, 0)]}
        tutor.best_moves = {
            chess.WHITE: [],
            chess.BLACK: [(1, nf3, 200, 0), (0, e4, 0, 0), (2, d4, -50, 0)],
        }
        tutor.best_info = {
            chess.WHITE: [],
            chess.BLACK: [
                {"pv": [e4], "depth": 15},
                {"pv": [nf3], "depth": 16},
                {"pv": [d4], "depth": 8},
            ],
        }

        tutor.get_user_move_eval()

        value = tutor.evaluated_moves[(1, e4, chess.BLACK)]
        self.assertEqual(value["depth"], 15)
        self.assertNotEqual(value.get("quality"), "insufficient_depth")

    def test_get_user_move_eval_rejects_missing_deep_user_line(self):
        tutor = PicoTutor.__new__(PicoTutor)
        e4 = chess.Move.from_uci("e2e4")
        nf3 = chess.Move.from_uci("g1f3")
        tutor.board = chess.Board()
        tutor.board.push(e4)
        tutor.coach_on = True
        tutor.watcher_on = False
        tutor.evaluated_moves = {}
        tutor.best_history = {chess.WHITE: [], chess.BLACK: [(None, e4, 0, 0, 0)]}
        tutor.obvious_history = {chess.WHITE: [], chess.BLACK: [(0, e4, 0, 0)]}
        tutor.best_moves = {chess.WHITE: [], chess.BLACK: [(0, nf3, 200, 0), (1, nf3, 100, 0)]}
        tutor.best_info = {
            chess.WHITE: [],
            chess.BLACK: [
                {"pv": [nf3], "depth": 17},
                {"pv": [nf3], "depth": 17},
            ],
        }

        self.assertEqual(tutor.get_user_move_eval(), ("", 0))
        value = tutor.evaluated_moves[(1, e4, chess.BLACK)]
        self.assertEqual(value["quality_reason"], "missing_user_line")
        self.assertEqual(tutor.get_eval_moves(), {})

    def test_missing_shallow_line_allows_only_exact_deep_bad_move_evaluation(self):
        e4 = chess.Move.from_uci("e2e4")
        nf3 = chess.Move.from_uci("g1f3")

        def build_tutor(best_score, current_score):
            tutor = PicoTutor.__new__(PicoTutor)
            tutor.board = chess.Board()
            tutor.board.push(e4)
            tutor.coach_on = True
            tutor.watcher_on = False
            tutor.evaluated_moves = {}
            tutor.op = []
            tutor.hint_move = {chess.WHITE: chess.Move.null(), chess.BLACK: chess.Move.null()}
            tutor.best_history = {chess.WHITE: [], chess.BLACK: [(1, e4, current_score, 0, 10)]}
            tutor.obvious_history = {chess.WHITE: [], chess.BLACK: [(None, e4, 0, 0)]}
            tutor.best_moves = {
                chess.WHITE: [],
                chess.BLACK: [(0, nf3, best_score, 0), (1, e4, current_score, 0)],
            }
            tutor.best_info = {
                chess.WHITE: [],
                chess.BLACK: [
                    {"pv": [nf3], "depth": 10},
                    {"pv": [e4], "depth": 10},
                ],
            }
            return tutor

        bad_move_tutor = build_tutor(best_score=200, current_score=0)
        self.assertEqual(bad_move_tutor.get_user_move_eval()[0], "?")
        stored = bad_move_tutor.evaluated_moves[(1, e4, chess.BLACK)]
        self.assertEqual(stored["CPL"], 200)
        self.assertNotIn("deep_low_diff", stored)

        surprising_move_tutor = build_tutor(best_score=400, current_score=400)
        self.assertEqual(surprising_move_tutor.get_user_move_eval()[0], "")

    def test_history_annotations_require_previous_depth_threshold(self):
        e4 = chess.Move.from_uci("e2e4")
        e5 = chess.Move.from_uci("e7e5")
        nf3 = chess.Move.from_uci("g1f3")
        d4 = chess.Move.from_uci("d2d4")

        def build_tutor(
            previous_depth,
            best_score=100,
            current_score=60,
            low_score=-20,
            before_score=0,
            previous_pv=0,
        ):
            tutor = PicoTutor.__new__(PicoTutor)
            tutor.board = chess.Board()
            for move in (e4, e5, nf3):
                tutor.board.push(move)
            tutor.coach_on = True
            tutor.watcher_on = False
            tutor.evaluated_moves = {}
            tutor.op = []
            tutor.hint_move = {chess.WHITE: chess.Move.null(), chess.BLACK: chess.Move.null()}
            tutor.best_history = {
                chess.WHITE: [],
                chess.BLACK: [
                    (previous_pv, e4, before_score, 0, previous_depth),
                    (1, nf3, current_score, 0, 10),
                ],
            }
            tutor.obvious_history = {chess.WHITE: [], chess.BLACK: [(0, nf3, low_score, 0)]}
            tutor.best_moves = {
                chess.WHITE: [],
                chess.BLACK: [(0, d4, best_score, 0), (1, nf3, current_score, 0)],
            }
            tutor.best_info = {
                chess.WHITE: [],
                chess.BLACK: [
                    {"pv": [d4], "depth": 10},
                    {"pv": [nf3], "depth": 10},
                ],
            }
            return tutor

        valid_history_tutor = build_tutor(10)
        self.assertEqual(valid_history_tutor.get_user_move_eval()[0], "?!")
        self.assertEqual(valid_history_tutor.evaluated_moves[(3, nf3, chess.BLACK)]["score_hist_diff"], 60)
        shallow_history_tutor = build_tutor(9)
        self.assertEqual(shallow_history_tutor.get_user_move_eval()[0], "")
        self.assertNotIn("score_hist_diff", shallow_history_tutor.evaluated_moves[(3, nf3, chess.BLACK)])
        self.assertEqual(build_tutor(10, previous_pv=None).get_user_move_eval()[0], "")
        self.assertEqual(
            build_tutor(10, best_score=10, current_score=0, low_score=80, before_score=60).get_user_move_eval()[0],
            "!?",
        )
        self.assertEqual(
            build_tutor(9, best_score=10, current_score=0, low_score=80, before_score=60).get_user_move_eval()[0],
            "",
        )

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
