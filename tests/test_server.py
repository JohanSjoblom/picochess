import unittest

from dgt.api import DgtApi, EventApi
from dgt.translate import DgtTranslate
from dgt.util import Mode, TimeMode
from server import (
    OBOOKSRV_BOOK_FILE,
    _display_text_from_label,
    _engine_change_events,
    _mode_text,
    _select_web_book,
    _time_control_text,
    _update_web_book_selection,
    _web_book_choices,
)


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


class TestServerWebBookSelection(unittest.TestCase):
    def test_web_book_choices_include_obooksrv_first(self):
        books = _web_book_choices()
        self.assertTrue(books)
        self.assertEqual(0, books[0]["index"])
        self.assertEqual(OBOOKSRV_BOOK_FILE, books[0]["file"])

    def test_select_web_book_zero_index_keeps_obooksrv_pseudo_entry(self):
        selected = _select_web_book(0)
        self.assertEqual(OBOOKSRV_BOOK_FILE, selected["file"])

    def test_update_web_book_selection_only_updates_web_shared_state(self):
        shared = {}
        selected = _update_web_book_selection(shared, 0)
        self.assertEqual(OBOOKSRV_BOOK_FILE, shared["web_book_file"])
        self.assertEqual(selected["label"], shared["system_info"]["book_name"])


class TestServerWebEngineSelection(unittest.TestCase):
    def setUp(self):
        self.translate = DgtTranslate("none", 0, "en", "version")
        self.engine_text = _display_text_from_label("Engine")
        self.engine = {
            "file": "/opt/picochess/engines/test/engine",
            "text": self.engine_text,
            "level_dict": {
                "Elo@1600": {"UCI_Elo": 1600},
                "Elo@1800": {"UCI_Elo": 1800},
            },
        }

    def assert_display_text(self, text):
        self.assertEqual(DgtApi.DISPLAY_TEXT, repr(text))

    def test_engine_change_events_apply_selected_level_before_engine_switch(self):
        level_event, engine_event = _engine_change_events(self.engine, "Elo@1600", self.translate)

        self.assertEqual(EventApi.LEVEL, repr(level_event))
        self.assertEqual("Elo@1600", level_event.level_name)
        self.assert_display_text(level_event.level_text)
        self.assertEqual(EventApi.NEW_ENGINE, repr(engine_event))
        self.assertEqual({"UCI_Elo": 1600}, engine_event.options)
        self.assertIs(self.engine, engine_event.eng)
        self.assertIs(self.engine_text, engine_event.eng_text)

    def test_engine_change_events_clear_stale_level_when_selection_is_missing(self):
        level_event, engine_event = _engine_change_events(self.engine, "", self.translate)

        self.assertEqual(EventApi.LEVEL, repr(level_event))
        self.assertEqual("", level_event.level_name)
        self.assert_display_text(level_event.level_text)
        self.assertEqual(EventApi.NEW_ENGINE, repr(engine_event))
        self.assertEqual({}, engine_event.options)
        self.assertIs(self.engine, engine_event.eng)

    def test_engine_change_events_clear_invalid_levels(self):
        level_event, engine_event = _engine_change_events(self.engine, "Missing", self.translate)

        self.assertEqual("", level_event.level_name)
        self.assertEqual({}, engine_event.options)
