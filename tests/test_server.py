import unittest

from dgt.api import DgtApi
from dgt.translate import DgtTranslate
from dgt.util import Mode, TimeMode
from server import _display_text_from_label, _mode_text, _time_control_text


class TestServerDisplayTextHelpers(unittest.TestCase):
    def setUp(self):
        self.translate = DgtTranslate("none", 0, "en", "version")

    def assert_display_text(self, text):
        self.assertEqual(DgtApi.DISPLAY_TEXT, repr(text))
        self.assertTrue(hasattr(text, "devs"))
        self.assertTrue(hasattr(text, "large_text"))

    def test_mode_text_uses_typed_display_text(self):
        text = _mode_text(Mode.PGNREPLAY, self.translate)
        self.assert_display_text(text)

    def test_mode_text_fallback_still_uses_typed_display_text(self):
        text = _mode_text(Mode.PONDER, None)
        self.assert_display_text(text)
        self.assertEqual("Ponder", text.large_text)

    def test_time_control_text_uses_typed_display_text(self):
        tc_init = {
            "mode": TimeMode.FISCHER,
            "fixed": 0,
            "blitz": 5,
            "fischer": 3,
            "moves_to_go": 0,
            "blitz2": 0,
            "depth": 0,
            "node": 0,
            "internal_time": None,
        }
        text = _time_control_text(tc_init, self.translate)
        self.assert_display_text(text)

    def test_display_text_from_label_creates_typed_display_text(self):
        text = _display_text_from_label("PGN Replay")
        self.assert_display_text(text)
        self.assertEqual("PGN Replay", text.web_text)

