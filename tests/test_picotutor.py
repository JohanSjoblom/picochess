import unittest
from unittest.mock import AsyncMock, Mock

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
