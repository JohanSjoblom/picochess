import json
import asyncio
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import chess

import picotutor_constants as picotutor_c
from dgt.api import DgtApi, EventApi, Message
from dgt.translate import DgtTranslate
from dgt.util import EBoard as EBoardType
from dgt.util import GameResult, Mode, PicoCoach, PlayMode, TimeMode
from server import (
    EventHandler,
    WebDisplay,
    OBOOKSRV_BOOK_FILE,
    OBOOKSRV_BOOK_LABEL,
    _apply_web_analysis_state,
    _build_scanned_setup_board,
    _cached_setup_position_fen,
    _channel_action_requires_remote_auth,
    _clock_event,
    _clock_menu_active,
    _coach_event_value,
    _coach_setting,
    _bounded_tutor_choice,
    _bounded_tutor_threads,
    _tutor_settings_from_shared,
    _board_from_web_pgn_prefix,
    _configured_engine_book_file,
    _display_text_from_label,
    _engine_book_choices,
    _engine_change_events,
    _engine_menu_labels,
    _engine_menu_payload,
    _apply_engine_menu_sort,
    _mode_text,
    _orient_scanned_board_fen,
    _retag_setup_position_side,
    _select_engine_book,
    _select_web_book,
    _time_control_text,
    _update_web_book_selection,
    _validate_setup_position_fen,
    _web_book_choices,
)
from uci.engine_provider import EngineProvider
from utilities import version as pico_version


class TestSettingsTemplate(unittest.TestCase):
    def test_beep_config_uses_valid_ini_values(self):
        template = (Path(__file__).parents[1] / "web/picoweb/templates/settings.html").read_text(encoding="utf-8")

        self.assertIn('return ["none", "some", "all", "sample"];', template)
        self.assertNotIn('return ["none", "Never", "Sometimes", "Always", "Sample"];', template)


class TestServerEventHandler(unittest.TestCase):
    class Client:
        def __init__(self, shared):
            self.shared = shared
            self.messages = []
            self.request = type("Request", (), {"remote_ip": "127.0.0.1"})()

        def real_ip(self):
            return self.request.remote_ip

        def write_message(self, message):
            self.messages.append(message)

    def test_open_sends_current_headers_after_cached_board_state(self):
        cached = {
            "event": "Game",
            "pgn": '[White "User"]\n[Black "Old Engine"]',
            "fen": chess.STARTING_FEN,
        }
        headers = {"White": "User", "Black": "New Engine", "Result": "*"}
        client = self.Client({"last_dgt_move_msg": cached, "headers": headers})

        with patch.object(EventHandler, "clients", set()), patch("server.client_ips", []):
            EventHandler.open(client)

        self.assertEqual(cached, client.messages[0])
        self.assertEqual({"event": "Header", "headers": headers}, client.messages[1])


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
        self.assertEqual("Analysis", text.large_text)

    def test_mode_text_fallback_uses_playing_mode_labels(self):
        expected = {
            Mode.BRAIN: "Ponder On",
            Mode.ANALYSIS: "Move Hint",
            Mode.KIBITZ: "Eval.Score",
            Mode.PONDER: "Analysis",
        }
        for mode, label in expected.items():
            with self.subTest(mode=mode):
                text = _mode_text(mode, None)
                self.assert_display_text(text)
                self.assertEqual(label, text.large_text)

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


class TestEngineMenuHelpers(unittest.TestCase):
    def setUp(self):
        self.original_modern = EngineProvider.modern_engines
        self.original_retro = EngineProvider.retro_engines
        self.original_favorites = EngineProvider.favorite_engines
        self.original_sort = EngineProvider.engine_menu_sort
        EngineProvider.modern_engines = [{"name": "Modern", "file": "modern", "level_dict": {}}]
        EngineProvider.favorite_engines = [{"name": "Favorite", "file": "favorite", "level_dict": {}}]

    def tearDown(self):
        EngineProvider.modern_engines = self.original_modern
        EngineProvider.retro_engines = self.original_retro
        EngineProvider.favorite_engines = self.original_favorites
        EngineProvider.engine_menu_sort = self.original_sort

    def test_payload_uses_grouped_presentation_order_and_original_files(self):
        EngineProvider.retro_engines = [
            {"name": "Zulu", "file": "retro-0", "level_dict": {}, "manufacturer": "Novag"},
            {"name": "Beta", "file": "retro-1", "level_dict": {}, "manufacturer": "Mephisto"},
            {"name": "Alpha", "file": "retro-2", "level_dict": {}, "manufacturer": "Novag"},
        ]
        EngineProvider.set_engine_menu_sort("manufacturer")

        payload = _engine_menu_payload()
        retro = [entry for entry in payload["engines"] if entry["category"] == "retro"]

        self.assertEqual("manufacturer", payload["engine_menu_sort"])
        self.assertEqual(["retro-1", "retro-2", "retro-0"], [entry["file"] for entry in retro])
        self.assertEqual(["Mephisto", "Novag", "Novag"], [entry["manufacturer"] for entry in retro])

    def test_payload_keeps_legacy_retro_entries_flat(self):
        EngineProvider.retro_engines = [
            {"name": "Zulu", "file": "retro-0", "level_dict": {}},
            {"name": "Alpha", "file": "retro-1", "level_dict": {}},
        ]
        EngineProvider.set_engine_menu_sort("engine")

        payload = _engine_menu_payload()
        retro = [entry for entry in payload["engines"] if entry["category"] == "retro"]

        self.assertEqual(["retro-1", "retro-0"], [entry["file"] for entry in retro])
        self.assertEqual("", retro[0]["manufacturer"])

    def test_payload_groups_modern_and_favorites_when_metadata_exists(self):
        EngineProvider.modern_engines = [
            {"name": "Zulu", "file": "modern-0", "level_dict": {}, "manufacturer": ""},
            {"name": "Alpha", "file": "modern-1", "level_dict": {}, "manufacturer": "Maker"},
        ]
        EngineProvider.retro_engines = []
        EngineProvider.favorite_engines = [
            {"name": "Beta", "file": "fav-0", "level_dict": {}, "manufacturer": "Studio"},
        ]
        EngineProvider.set_engine_menu_sort("manufacturer")

        payload = _engine_menu_payload()
        modern = [entry for entry in payload["engines"] if entry["category"] == "modern"]
        favorites = [entry for entry in payload["engines"] if entry["category"] == "favorites"]

        self.assertEqual(["modern-1", "modern-0"], [entry["file"] for entry in modern])
        self.assertEqual(["Maker", "Other"], [entry["manufacturer"] for entry in modern])
        self.assertEqual(["Studio"], [entry["manufacturer"] for entry in favorites])

    def test_engine_menu_labels_use_dgt_translations(self):
        labels = _engine_menu_labels(DgtTranslate("none", 0, "en", "version"))

        self.assertEqual("Modern", labels["categories"]["modern"])
        self.assertEqual("Retro", labels["categories"]["retro"])
        self.assertEqual("Special", labels["categories"]["favorites"])
        self.assertEqual("Sort Order", labels["categories"]["sort"])

    @patch("server.write_picochess_ini")
    def test_apply_sort_updates_live_dgt_menu_and_persists(self, write_ini):
        class FakeDgtMenu:
            def __init__(self):
                self.value = None

            def set_engine_menu_sort(self, value):
                self.value = value
                return EngineProvider.set_engine_menu_sort(value)

        menu = FakeDgtMenu()
        shared = {"dgtmenu": menu}

        result = _apply_engine_menu_sort(shared, "engine")

        self.assertEqual("engine", result)
        self.assertEqual("engine", menu.value)
        self.assertEqual("engine", shared["system_info"]["engine_menu_sort"])
        write_ini.assert_called_once_with("engine-menu-sort", "engine")

    @patch("server.write_picochess_ini")
    def test_apply_sort_rejects_unknown_value(self, write_ini):
        self.assertIsNone(_apply_engine_menu_sort({}, "elo"))
        write_ini.assert_not_called()


class TestServerClockMenuHelpers(unittest.TestCase):
    class ClockMenu:
        def __init__(self, main=False, update=False):
            self.main = main
            self.update = update

        def inside_main_menu(self):
            return self.main

        def inside_updt_menu(self):
            return self.update

    def test_clock_menu_active_only_for_clock_menus(self):
        self.assertFalse(_clock_menu_active({}))
        self.assertTrue(_clock_menu_active({"dgtmenu": self.ClockMenu(main=True)}))
        self.assertTrue(_clock_menu_active({"dgtmenu": self.ClockMenu(update=True)}))
        self.assertFalse(_clock_menu_active({"dgtmenu": self.ClockMenu()}))


class TestServerTutorCoachHelpers(unittest.TestCase):
    def test_brain_and_hand_coach_settings_round_trip(self):
        cases = {
            PicoCoach.COACH_BRAIN: "brain",
            PicoCoach.COACH_HAND: "hand",
            PicoCoach.COACH_LIFT: "lift",
            PicoCoach.COACH_ON: "on",
            PicoCoach.COACH_OFF: "off",
        }
        for enum_value, setting in cases.items():
            with self.subTest(setting=setting):
                self.assertEqual(setting, _coach_setting(enum_value))
                self.assertEqual(enum_value, _coach_event_value(setting))

    def test_tutor_threads_accept_only_session_choices(self):
        with patch("server.platform.machine", return_value="x86_64"):
            self.assertEqual(1, _bounded_tutor_threads("1"))
            self.assertEqual(4, _bounded_tutor_threads("4"))
            self.assertIsNone(_bounded_tutor_threads("5"))
        with patch("server.platform.machine", return_value="aarch64"):
            self.assertEqual(2, _bounded_tutor_threads("2"))
            self.assertIsNone(_bounded_tutor_threads("3"))
        with patch("server.platform.machine", return_value="arm64"):
            self.assertEqual(4, _bounded_tutor_threads("4"))
        self.assertIsNone(_bounded_tutor_threads("1.5"))
        self.assertIsNone(_bounded_tutor_threads(True))

    def test_tutor_analysis_settings_accept_only_offered_choices(self):
        for value in picotutor_c.DEEP_MULTIPV_CHOICES:
            self.assertEqual(value, _bounded_tutor_choice(str(value), picotutor_c.DEEP_MULTIPV_CHOICES))
        for value in picotutor_c.DEEP_DEPTH_CHOICES:
            self.assertEqual(value, _bounded_tutor_choice(str(value), picotutor_c.DEEP_DEPTH_CHOICES))
        self.assertIsNone(_bounded_tutor_choice("6", picotutor_c.DEEP_MULTIPV_CHOICES))
        self.assertIsNone(_bounded_tutor_choice("18", picotutor_c.DEEP_DEPTH_CHOICES))

    def test_tutor_settings_report_live_requested_threads(self):
        tutor = Mock()
        tutor.get_deep_thread_choices.return_value = (1, 2, 3, 4)
        tutor.get_requested_deep_threads.return_value = 2
        tutor.get_requested_deep_multipv.return_value = 15
        tutor.get_requested_deep_depth.return_value = 28

        settings = _tutor_settings_from_shared({"picotutor": tutor})

        self.assertEqual(2, settings["tutor_threads"])
        self.assertEqual([1, 2, 3, 4], settings["tutor_thread_choices"])
        self.assertEqual(15, settings["tutor_multipv"])
        self.assertEqual(28, settings["tutor_depth"])


class TestServerWebDisplayTutorCoach(unittest.IsolatedAsyncioTestCase):
    async def test_system_info_includes_picochess_version(self):
        shared = {}
        display = WebDisplay(shared, asyncio.get_running_loop())

        display._create_system_info()

        self.assertEqual(pico_version, shared["system_info"]["version"])

    async def test_non_brain_coach_clears_stale_brain_hint(self):
        shared = {"brain_hint": {"squares": ["e2"]}}
        display = WebDisplay(shared, asyncio.get_running_loop())

        with patch("server.EventHandler.write_to_clients") as write_to_clients:
            await display.task(Message.PICOCOACH(picocoach=4))

        self.assertNotIn("brain_hint", shared)
        write_to_clients.assert_any_call({"event": "BrainHint", "squares": []})


class TestServerWebDisplayGameEnd(unittest.IsolatedAsyncioTestCase):
    async def test_game_ends_publishes_inactive_game_before_final_fen(self):
        board = chess.Board()
        for move in ("f2f3", "e7e5", "g2g4", "d8h4"):
            board.push(chess.Move.from_uci(move))
        shared = {"headers": {}, "system_info": {"game_started": True}}
        display = WebDisplay(shared, asyncio.get_running_loop())

        with patch("server.EventHandler.write_to_clients") as write_to_clients:
            await display.task(
                Message.GAME_ENDS(
                    tc_init={},
                    result=GameResult.MATE,
                    play_mode=PlayMode.USER_WHITE,
                    game=board,
                    mode=Mode.NORMAL,
                )
            )

        calls = [call.args[0] for call in write_to_clients.call_args_list]
        self.assertEqual({"event": "SystemInfo", "msg": {"game_started": False}}, calls[0])
        self.assertEqual("0-1", shared["headers"]["Result"])
        self.assertEqual("Fen", calls[-1]["event"])
        self.assertEqual("reload", calls[-1]["play"])
        self.assertIn("0-1", calls[-1]["pgn"])
        self.assertFalse(shared["system_info"]["game_started"])


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

    @patch("server.get_opening_books")
    def test_web_books_are_alphabetical_after_obooksrv(self, get_opening_books):
        get_opening_books.return_value = [
            {"file": "zulu.bin", "text": "Zulu"},
            {"file": "alpha.bin", "text": "Alpha"},
            {"file": "beta.bin", "text": "beta"},
        ]

        books = _web_book_choices()

        self.assertEqual(
            [OBOOKSRV_BOOK_LABEL, "Alpha", "beta", "Zulu"],
            [book["label"] for book in books],
        )
        self.assertEqual([0, 1, 2, 3], [book["index"] for book in books])


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

    @patch("server.get_opening_books")
    def test_engine_books_are_alphabetical(self, get_opening_books):
        get_opening_books.return_value = [
            {"file": "zulu.bin", "text": "Zulu"},
            {"file": "alpha.bin", "text": "Alpha"},
            {"file": "beta.bin", "text": "beta"},
        ]

        books = _engine_book_choices()

        self.assertEqual(["Alpha", "beta", "Zulu"], [book["label"] for book in books])
        self.assertEqual([0, 1, 2], [book["index"] for book in books])


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


class TestServerClockState(unittest.TestCase):
    def test_clock_event_caches_text_and_running_state(self):
        shared = {}

        event = _clock_event(shared, "<span>1:00</span>", running=True)

        self.assertEqual({"event": "Clock", "msg": "<span>1:00</span>", "running": True}, event)
        self.assertEqual("<span>1:00</span>", shared["clock_text"])
        self.assertTrue(shared["clock_running"])


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
            "pause_resume",
            "restore_position_checkpoint",
            "scan_board",
            "set_position_side",
        ):
            self.assertFalse(_channel_action_requires_remote_auth(action), action)


class TestServerSetPositionFromPgn(unittest.TestCase):
    def test_scanned_position_drops_unavailable_castling_rights(self):
        parsed = _build_scanned_setup_board(
            "8/8/8/8/8/8/4K3/7k",
            side_to_play=True,
            castling="KQkq",
            uci960_enabled=False,
        )

        self.assertTrue(parsed.is_valid())
        self.assertEqual("8/8/8/8/8/8/4K3/7k w - - 0 1", parsed.fen())

    def test_scanned_position_rejects_kingless_board(self):
        with self.assertRaisesRegex(ValueError, "No valid board position scanned"):
            _build_scanned_setup_board(
                "8/8/8/8/8/8/8/8",
                side_to_play=True,
                castling="KQkq",
                uci960_enabled=False,
            )

    def test_raw_dgt_scan_white_bottom_keeps_raw_coordinates(self):
        raw_spanish = "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R"

        oriented = _orient_scanned_board_fen(
            raw_spanish,
            board_reversed=False,
            eboard_type=EBoardType.DGT,
            raw_board_fen=True,
        )

        self.assertEqual(raw_spanish, oriented)

    def test_raw_dgt_scan_black_bottom_flips_coordinates(self):
        raw_spanish = "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R"

        oriented = _orient_scanned_board_fen(
            raw_spanish,
            board_reversed=True,
            eboard_type=EBoardType.DGT,
            raw_board_fen=True,
        )

        self.assertEqual("R2KQBNR/PPP1PPPP/2N5/3P4/3p2B1/5n2/ppp1pppp/rnbkqb1r", oriented)

    def test_non_dgt_scan_keeps_existing_orientation_rule(self):
        board_fen = "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R"

        oriented = _orient_scanned_board_fen(
            board_fen,
            board_reversed=False,
            eboard_type=EBoardType.CHESSNUT,
            raw_board_fen=True,
        )

        self.assertEqual(board_fen, oriented)

    def test_normalized_dgt_scan_keeps_existing_orientation_rule(self):
        board_fen = "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R"

        oriented = _orient_scanned_board_fen(
            board_fen,
            board_reversed=False,
            eboard_type=EBoardType.DGT,
            raw_board_fen=False,
        )

        self.assertEqual(board_fen, oriented)

    def test_retag_setup_position_side_changes_turn_only(self):
        fen = "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 1"

        retagged, uci960 = _retag_setup_position_side(fen, side_to_play=False)

        self.assertFalse(uci960)
        self.assertEqual("r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R", retagged.board_fen())
        self.assertEqual(chess.BLACK, retagged.turn)
        self.assertEqual("KQkq", retagged.castling_xfen())

    def test_retag_setup_position_side_rejects_invalid_position(self):
        with self.assertRaisesRegex(ValueError, "Invalid FEN position"):
            _retag_setup_position_side("8/8/8/8/8/8/8/8 w - - 0 1", side_to_play=False)

    def test_cached_setup_position_fen_accepts_new_position_cache(self):
        shared = {
            "last_dgt_move_msg": {
                "event": "Game",
                "move": "0000",
                "fen": "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 1",
            }
        }

        self.assertEqual(shared["last_dgt_move_msg"]["fen"], _cached_setup_position_fen(shared))

    def test_cached_setup_position_fen_rejects_played_move_cache(self):
        shared = {
            "last_dgt_move_msg": {
                "event": "Fen",
                "move": "e1g1",
                "fen": "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQ1RK1 b kq - 1 1",
            }
        }

        self.assertEqual("", _cached_setup_position_fen(shared))

    def test_web_pgn_prefix_reconstructs_selected_position_with_move_stack(self):
        pgn_text = """[Event "Example"]
[Site "?"]
[Date "2026.06.12"]
[Round "?"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 e5 2. Nf3 *
"""
        board = chess.Board()
        for san in ("e4", "e5", "Nf3"):
            board.push_san(san)

        parsed, uci960 = _board_from_web_pgn_prefix(pgn_text, board.fen())

        self.assertFalse(uci960)
        self.assertEqual(board.fen(), parsed.fen())
        self.assertEqual(3, len(parsed.move_stack))

    def test_web_pgn_prefix_rejects_fen_mismatch(self):
        pgn_text = """[Event "Example"]
[Result "*"]

1. e4 *
"""
        wrong_board = chess.Board()
        wrong_board.push_san("d4")

        with self.assertRaisesRegex(ValueError, "does not end at the selected FEN"):
            _board_from_web_pgn_prefix(pgn_text, wrong_board.fen())

    def test_chess960_fen_validation_uses_variant_hint(self):
        board = chess.Board.from_chess960_pos(0)

        parsed, uci960 = _validate_setup_position_fen(board.fen(), uci960_hint=True)

        self.assertTrue(uci960)
        self.assertTrue(parsed.is_valid())

    def test_chess960_web_pgn_prefix_reconstructs_selected_position(self):
        board = chess.Board.from_chess960_pos(0)
        move = next(iter(board.legal_moves))
        san = board.san(move)
        board.push(move)
        pgn_text = f"""[Event "Chess960"]
[Variant "Chess960"]
[SetUp "1"]
[FEN "{chess.Board.from_chess960_pos(0).fen()}"]
[Result "*"]

1. {san} *
"""

        parsed, uci960 = _board_from_web_pgn_prefix(pgn_text, board.fen(), uci960_hint=True)

        self.assertTrue(uci960)
        self.assertEqual(board.fen(), parsed.fen())
        self.assertEqual(1, len(parsed.move_stack))
