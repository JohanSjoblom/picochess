import json
import unittest

from dgt.api import DgtApi, EventApi
from dgt.translate import DgtTranslate
from dgt.util import Mode, TimeMode
from server import (
    OBOOKSRV_BOOK_FILE,
    _apply_web_analysis_state,
    _channel_action_requires_remote_auth,
    _configured_engine_book_file,
    _display_text_from_label,
    _engine_book_choices,
    _engine_change_events,
    _mode_text,
    _select_engine_book,
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
        json.dumps({"books": books})

    def test_select_web_book_zero_index_keeps_obooksrv_pseudo_entry(self):
        selected = _select_web_book(0)
        self.assertEqual(OBOOKSRV_BOOK_FILE, selected["file"])

    def test_update_web_book_selection_only_updates_web_shared_state(self):
        shared = {}
        selected = _update_web_book_selection(shared, 0)
        self.assertEqual(OBOOKSRV_BOOK_FILE, shared["web_book_file"])
        self.assertEqual(OBOOKSRV_BOOK_FILE, selected["file"])
        self.assertNotIn("system_info", shared)


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


class TestServerEngineBookSelection(unittest.TestCase):
    def test_engine_book_choices_exclude_obooksrv_and_are_json_safe(self):
        books = _engine_book_choices()
        self.assertTrue(books)
        self.assertNotEqual(OBOOKSRV_BOOK_FILE, books[0]["file"])
        json.dumps({"books": books})

    def test_engine_book_choices_exclude_web_only_obooksrv_entry(self):
        self.assertEqual(len(_web_book_choices()) - 1, len(_engine_book_choices()))
        self.assertIsNone(_select_engine_book(OBOOKSRV_BOOK_FILE))

    def test_select_engine_book_resolves_configured_book_file(self):
        selected = _select_engine_book(_configured_engine_book_file())
        self.assertIsNotNone(selected)
        self.assertNotEqual(OBOOKSRV_BOOK_FILE, selected["file"])
        self.assertTrue(selected["label"])


class TestServerWebAnalysisState(unittest.TestCase):
    def test_none_analysis_clears_cached_state(self):
        shared = {
            "analysis_state": {"source": "engine", "depth": 12},
            "analysis_state_engine": {"source": "engine", "depth": 12},
            "analysis_state_tutor": {"source": "tutor", "depth": 10},
            "suppress_engine_analysis": True,
        }
        reset_calls = []

        payload = _apply_web_analysis_state(shared, None, reset_engine_analysis_state=lambda: reset_calls.append(True))

        self.assertIsNone(payload)
        self.assertNotIn("analysis_state", shared)
        self.assertNotIn("analysis_state_engine", shared)
        self.assertNotIn("analysis_state_tutor", shared)
        self.assertNotIn("suppress_engine_analysis", shared)
        self.assertTrue(shared["analysis_web_enabled"])
        self.assertEqual([True], reset_calls)

    def test_tutor_analysis_fills_missing_fen_and_preserves_engine_cache(self):
        shared = {
            "analysis_state_engine": {"source": "engine", "depth": 8},
            "last_dgt_move_msg": {"fen": "some-fen"},
        }

        payload = _apply_web_analysis_state(shared, {"source": "tutor", "depth": 14}, reset_engine_analysis_state=None)

        self.assertEqual("some-fen", payload["fen"])
        self.assertEqual(payload, shared["analysis_state_tutor"])
        self.assertEqual({"source": "engine", "depth": 8}, shared["analysis_state_engine"])


class TestServerChannelAuth(unittest.TestCase):
    def test_high_impact_channel_actions_require_remote_auth(self):
        for action in (
            "new_engine",
            "new_engine_book",
            "new_time",
            "set_mode",
            "sys_shutdown",
            "sys_reboot",
            "sys_exit",
            "sys_update",
            "sys_update_engines",
            "eboard",
            "wifi_hotspot",
            "bt_toggle",
            "bt_fix",
        ):
            self.assertTrue(_channel_action_requires_remote_auth(action), action)

    def test_gameplay_and_web_book_actions_remain_unauthenticated(self):
        for action in (
            "move",
            "promotion",
            "new_game",
            "take_back",
            "altmove",
            "contlast",
            "new_book",
            "scan_board",
        ):
            self.assertFalse(_channel_action_requires_remote_auth(action), action)
