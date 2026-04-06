import unittest

from dgt.util import Mode
from picochess import should_use_tutor_analysis, tutor_analysis_allowed_in_mode


class TestPicochessAnalysisRouting(unittest.TestCase):
    def test_tutor_analysis_is_disabled_in_ponder_mode(self):
        self.assertFalse(tutor_analysis_allowed_in_mode(Mode.PONDER))
        self.assertFalse(
            should_use_tutor_analysis(
                interaction_mode=Mode.PONDER,
                pgn_mode=False,
                engine_should_skip_analyser=False,
                engine_is_playing=False,
                engine_move_was_book=False,
                is_user_turn=True,
            )
        )

    def test_non_playing_analysis_mode_still_prefers_tutor_when_allowed(self):
        self.assertTrue(tutor_analysis_allowed_in_mode(Mode.ANALYSIS))
        self.assertTrue(
            should_use_tutor_analysis(
                interaction_mode=Mode.ANALYSIS,
                pgn_mode=False,
                engine_should_skip_analyser=False,
                engine_is_playing=False,
                engine_move_was_book=False,
                is_user_turn=True,
            )
        )
