import unittest

from dgt.util import Mode
from picochess import (
    should_show_setpieces_after_lift_timeout,
    should_use_tutor_analysis,
    tutor_analysis_allowed_in_mode,
)


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

    def test_king_lift_reaches_setpieces_threshold_before_coach(self):
        self.assertTrue(should_show_setpieces_after_lift_timeout("K", is_hand_mode=False))
        self.assertTrue(should_show_setpieces_after_lift_timeout("k", is_hand_mode=True))

    def test_quick_switch_threshold_still_applies_to_non_hand_lifts(self):
        self.assertTrue(should_show_setpieces_after_lift_timeout("Q", is_hand_mode=False))
        self.assertFalse(should_show_setpieces_after_lift_timeout("Q", is_hand_mode=True))
        self.assertFalse(should_show_setpieces_after_lift_timeout("", is_hand_mode=False))
