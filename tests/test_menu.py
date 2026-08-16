import os

import unittest
from unittest.mock import AsyncMock, patch

from dgt.api import EventApi
from dgt.menu import DgtMenu, MenuState
from dgt.translate import DgtTranslate
from dgt.util import Beep, Language, PicoComment, EBoard, PicoCoach, Theme, TimeMode, Voice
from uci.read import read_engine_ini
from uci.engine_provider import EngineProvider


class TestDgtMenu(unittest.IsolatedAsyncioTestCase):
    @patch("subprocess.run")
    def create_menu(self, machine_mock, _, rdisplay=False):
        machine_mock.return_value = ".." + os.sep + "tests"  # return the tests path as the platform engine path
        EngineProvider.modern_engines = read_engine_ini(filename="engines.ini")
        EngineProvider.retro_engines = read_engine_ini(filename="retro.ini")
        EngineProvider.favorite_engines = read_engine_ini(filename="favorites.ini")
        EngineProvider.installed_engines = list(
            EngineProvider.modern_engines + EngineProvider.retro_engines + EngineProvider.favorite_engines
        )
        EngineProvider.set_engine_menu_sort("file")

        trans = DgtTranslate("none", 0, "en", "version")
        menu = DgtMenu(
            clockside="",
            disable_confirm=False,
            ponder_interval=0,
            user_voice="",
            comp_voice="",
            speed_voice=0,
            enable_capital_letters=False,
            disable_short_move=False,
            log_file="",
            engine_server=None,
            rol_disp_norm=False,
            volume_voice=0,
            board_type=EBoard.DGT,
            theme_type="dark",
            rspeed=1.0,
            rsound=True,
            rdisplay=rdisplay,
            rwindow=False,
            rol_disp_brain=False,
            show_enginename=False,
            picocoach=PicoCoach.COACH_OFF,
            picowatcher=False,
            picoexplorer=False,
            picocomment=PicoComment.COM_OFF,
            picocomment_prob=0,
            contlast=False,
            altmove=False,
            dgttranslate=trans,
        )
        return menu

    async def test_brain_and_hand_coach_values_are_in_tutor_cycle(self):
        self.assertEqual(PicoCoach.COACH_BRAIN, PicoCoach.from_str("brain"))
        self.assertEqual(PicoCoach.COACH_HAND, PicoCoach.from_str("hand"))
        self.assertEqual(
            [
                PicoCoach.COACH_ON,
                PicoCoach.COACH_LIFT,
                PicoCoach.COACH_BRAIN,
                PicoCoach.COACH_HAND,
                PicoCoach.COACH_OFF,
            ],
            PicoCoach.items(),
        )

    @patch.dict(os.environ, {}, clear=True)
    @patch("platform.machine")
    async def test_retro_display_config_does_not_require_display_env(self, machine_mock):
        menu = self.create_menu(machine_mock, rdisplay=True)
        self.assertTrue(menu.get_engine_rdisplay())

    @patch("platform.machine")
    async def test_persistent_web_settings_update_live_menu_state(self, machine_mock):
        menu = self.create_menu(machine_mock)

        menu.set_language(Language.DE)
        menu.set_beep(Beep.ON)
        menu.set_voice(Voice.USER, "en", "al")
        menu.set_voice(Voice.COMP, None, None)
        menu.set_voice_speed(4)
        menu.set_voice_volume(12)
        menu.set_ponder_interval(7)
        menu.set_capital_letters(True)
        menu.set_confirm_disabled(True)
        menu.set_short_notation_disabled(True)
        menu.set_enginename(True)
        menu.set_continue_game(True)
        menu.set_alt_move(True)
        menu.set_picocomment(PicoComment.COM_ON_ENG)
        menu.set_comment_factor(70)
        menu.set_picoexplorer(True)
        menu.set_picowatcher(True)
        menu.set_picocoach(PicoCoach.COACH_BRAIN)
        menu.set_board_type(EBoard.CHESSNUT)
        menu.set_clockside("right")
        menu.set_theme(Theme.LIGHT)
        menu.set_retro_display(True)
        menu.set_retro_window(True)
        menu.set_retro_speed(4.0)
        menu.set_retro_sound(False)

        self.assertEqual(Language.DE, menu.menu_system_language)
        self.assertEqual(Beep.ON, menu.menu_system_sound)
        self.assertTrue(menu.menu_system_voice_user_active)
        self.assertFalse(menu.menu_system_voice_comp_active)
        self.assertEqual(4, menu.menu_system_voice_speedfactor)
        self.assertEqual(12, menu.menu_system_voice_volumefactor)
        self.assertEqual(7, menu.get_ponderinterval())
        self.assertTrue(menu.dgttranslate.capital)
        self.assertTrue(menu.get_confirm())
        self.assertTrue(menu.dgttranslate.notation)
        self.assertTrue(menu.get_enginename())
        self.assertTrue(menu.get_game_contlast())
        self.assertTrue(menu.get_game_altmove())
        self.assertEqual(PicoComment.COM_ON_ENG, menu.get_picocomment())
        self.assertEqual(70, menu.get_comment_factor())
        self.assertTrue(menu.get_picoexplorer())
        self.assertTrue(menu.get_picowatcher())
        self.assertEqual(PicoCoach.COACH_BRAIN, menu.get_picocoach())
        self.assertEqual(EBoard.CHESSNUT, menu.menu_system_eboard_type)
        self.assertEqual("right", menu.menu_system_display_clockside)
        self.assertEqual(Theme.LIGHT, menu.menu_system_theme_type)
        self.assertTrue(menu.get_engine_rdisplay())
        self.assertTrue(menu.get_engine_rwindow())
        self.assertEqual(4.0, menu.get_engine_rspeed())
        self.assertFalse(menu.get_engine_rsound())

    @patch("platform.machine")
    async def test_retro_window_change_fires_shared_runtime_event(self, machine_mock):
        menu = self.create_menu(machine_mock, rdisplay=True)
        menu.state = MenuState.RETROSETTINGS_RETROWINDOW

        with patch("dgt.menu.ModeInfo.get_emulation_mode", return_value=True), patch(
            "dgt.menu.write_picochess_ini"
        ) as write_ini, patch("dgt.menu.Observable.fire", new_callable=AsyncMock) as event_fire, patch(
            "dgt.menu.DispatchDgt.fire", new_callable=AsyncMock
        ):
            await menu.main_down()

        self.assertTrue(menu.get_engine_rwindow())
        write_ini.assert_called_once_with("rwindow", True)
        window_events = [
            call.args[0] for call in event_fire.await_args_list if repr(call.args[0]) == EventApi.SET_RETRO_WINDOW
        ]
        self.assertEqual(1, len(window_events))
        self.assertTrue(window_events[0].windowed)

    @patch("platform.machine")
    async def test_web_time_control_updates_dgt_menu_selection(self, machine_mock):
        menu = self.create_menu(machine_mock)
        tc_init = {
            "mode": TimeMode.FIXED,
            "fixed": 0,
            "blitz": 0,
            "fischer": 0,
            "moves_to_go": 0,
            "blitz2": 0,
            "depth": 15,
            "node": 0,
            "internal_time": None,
        }

        menu.set_time_control(tc_init)

        self.assertEqual(TimeMode.DEPTH, menu.get_time_mode())
        self.assertEqual(menu.tc_depth_list.index("15"), menu.get_time_depth())

    @patch("platform.machine")
    async def test_engine_menu_traversal(self, machine_mock):
        menu = self.create_menu(machine_mock)
        menu.set_state_current_engine("")
        text = menu.get_current_engine_name()
        self.assertEqual("Lc0", text.large_text)
        menu.enter_top_menu()
        self.assertEqual(MenuState.TOP, menu.state)
        await menu.main_down()
        # start with engine menu from top menu
        self.assertEqual(MenuState.ENGINE, menu.state)
        menu.main_right()
        self.assertEqual(MenuState.SYS, menu.state)
        menu.main_left()
        self.assertEqual(MenuState.ENGINE, menu.state)
        menu.main_left()
        self.assertEqual(MenuState.BOOK, menu.state)
        menu.main_right()
        self.assertEqual(MenuState.ENGINE, menu.state)
        await menu.main_down()
        self.assertEqual(MenuState.ENG_MODERN, menu.state)
        menu.main_up()
        self.assertEqual(MenuState.ENGINE, menu.state)
        await menu.main_down()
        self.assertEqual(MenuState.ENG_MODERN, menu.state)
        menu.main_right()
        self.assertEqual(MenuState.ENG_RETRO, menu.state)
        menu.main_up()
        self.assertEqual(MenuState.ENGINE, menu.state)
        await menu.main_down()
        self.assertEqual(MenuState.ENG_RETRO, menu.state)
        menu.main_right()
        self.assertEqual(MenuState.RETROSETTINGS, menu.state)
        menu.main_right()
        self.assertEqual(MenuState.ENG_FAV, menu.state)
        menu.main_up()
        self.assertEqual(MenuState.ENGINE, menu.state)
        await menu.main_down()
        self.assertEqual(MenuState.ENG_FAV, menu.state)
        menu.main_right()
        self.assertEqual(MenuState.ENG_MODERN, menu.state)
        menu.main_left()
        self.assertEqual(MenuState.ENG_FAV, menu.state)
        menu.main_left()
        self.assertEqual(MenuState.RETROSETTINGS, menu.state)
        menu.main_left()
        self.assertEqual(MenuState.ENG_RETRO, menu.state)
        menu.main_left()
        # modern engines
        self.assertEqual(MenuState.ENG_MODERN, menu.state)
        modern_engine_name = await menu.main_down()
        self.assertEqual(MenuState.ENG_MODERN_NAME, menu.state)
        self.assertEqual("Lc0", modern_engine_name.large_text)
        modern_engine_name = menu.main_right()
        self.assertEqual("McBrain9932", modern_engine_name.large_text)
        modern_engine_name = menu.main_left()
        self.assertEqual("Lc0", modern_engine_name.large_text)
        menu.main_up()
        self.assertEqual(MenuState.ENG_MODERN, menu.state)
        menu.main_right()
        # retro engines
        self.assertEqual(MenuState.ENG_RETRO, menu.state)
        retro_engine_name = await menu.main_down()
        self.assertEqual(MenuState.ENG_RETRO_NAME, menu.state)
        self.assertEqual("Mep.Academy", retro_engine_name.large_text)
        retro_engine_name = menu.main_right()
        self.assertEqual("M.Amsterdam", retro_engine_name.large_text)
        retro_engine_name = menu.main_left()
        self.assertEqual("Mep.Academy", retro_engine_name.large_text)
        menu.main_up()
        self.assertEqual(MenuState.ENG_RETRO, menu.state)
        menu.main_right()
        self.assertEqual(MenuState.RETROSETTINGS, menu.state)
        menu.main_right()
        # favorite engines
        self.assertEqual(MenuState.ENG_FAV, menu.state)
        fav_engine_name = await menu.main_down()
        self.assertEqual(MenuState.ENG_FAV_NAME, menu.state)
        self.assertEqual("Lc0 v0.27.0", fav_engine_name.large_text)
        fav_engine_name = menu.main_right()
        self.assertEqual("Stockfish DD", fav_engine_name.large_text)
        fav_engine_name = menu.main_left()
        self.assertEqual("Lc0 v0.27.0", fav_engine_name.large_text)
        # level of a favorite engine
        level = await menu.main_down()
        self.assertEqual(MenuState.ENG_FAV_NAME_LEVEL, menu.state)
        self.assertEqual("1 Core", level.large_text)
        level = menu.main_right()
        self.assertEqual("2 Cores", level.large_text)
        level = menu.main_left()
        self.assertEqual("1 Core", level.large_text)

        menu.main_up()
        self.assertEqual(MenuState.ENG_FAV_NAME, menu.state)
        menu.main_up()
        menu.main_right()
        modern_engine_name = await menu.main_down()
        self.assertEqual(MenuState.ENG_MODERN_NAME, menu.state)
        self.assertEqual("Lc0", modern_engine_name.large_text)
        # level of a modern engine
        level = await menu.main_down()
        self.assertEqual(MenuState.ENG_MODERN_NAME_LEVEL, menu.state)
        self.assertEqual("1 Core", level.large_text)
        level = menu.main_right()
        self.assertEqual("2 Cores", level.large_text)
        level = menu.main_left()
        self.assertEqual("1 Core", level.large_text)

        menu.main_up()
        self.assertEqual(MenuState.ENG_MODERN_NAME, menu.state)
        menu.main_up()
        menu.main_right()
        retro_engine_name = await menu.main_down()
        self.assertEqual(MenuState.ENG_RETRO_NAME, menu.state)
        self.assertEqual("Mep.Academy", retro_engine_name.large_text)
        # level of a retro engine
        level = await menu.main_down()
        self.assertEqual(MenuState.ENG_RETRO_NAME_LEVEL, menu.state)
        self.assertEqual("Level 00 - speed", level.large_text)
        level = menu.main_right()
        self.assertEqual("Level 01 - 5s move", level.large_text)
        level = menu.main_left()
        self.assertEqual("Level 00 - speed", level.large_text)

        menu.main_up()
        self.assertEqual(MenuState.ENG_RETRO_NAME, menu.state)

    @patch("platform.machine")
    async def test_grouped_retro_engine_menu_traversal_uses_stable_indexes(self, machine_mock):
        menu = self.create_menu(machine_mock)
        manufacturers = ["Mephisto", "Mephisto", "Novag"]
        for engine, manufacturer in zip(EngineProvider.retro_engines, manufacturers):
            engine["manufacturer"] = manufacturer
        EngineProvider.set_engine_menu_sort("file")

        menu.enter_retro_eng_menu()
        manufacturer = await menu.main_down()
        self.assertEqual(MenuState.ENG_RETRO_MANUFACTURER, menu.state)
        self.assertEqual("Mephisto", manufacturer.web_text)

        manufacturer = menu.main_right()
        self.assertEqual("Novag", manufacturer.web_text)
        engine_name = await menu.main_down()
        self.assertEqual(MenuState.ENG_RETRO_NAME, menu.state)
        self.assertEqual(2, menu.menu_retro_engine_index)
        self.assertEqual(EngineProvider.retro_engines[2]["text"].large_text, engine_name.large_text)

        menu.main_up()
        self.assertEqual(MenuState.ENG_RETRO_MANUFACTURER, menu.state)
        menu.main_left()
        await menu.main_down()
        self.assertEqual(0, menu.menu_retro_engine_index)
        menu.main_right()
        self.assertEqual(1, menu.menu_retro_engine_index)

    @patch("platform.machine")
    async def test_grouped_retro_sort_change_retains_current_engine(self, machine_mock):
        menu = self.create_menu(machine_mock)
        EngineProvider.retro_engines[0]["manufacturer"] = "Zulu"
        EngineProvider.retro_engines[1]["manufacturer"] = "Alpha"
        menu.menu_retro_engine_index = 1

        menu.set_engine_menu_sort("manufacturer")

        self.assertEqual(1, menu.menu_retro_engine_index)
        self.assertEqual(0, menu.menu_retro_manufacturer_index)
        self.assertEqual("Alpha", EngineProvider.get_retro_groups()[0]["manufacturer"])

    @patch("platform.machine")
    async def test_grouped_modern_and_special_engine_menus(self, machine_mock):
        menu = self.create_menu(machine_mock)
        for engine, manufacturer in zip(EngineProvider.modern_engines, ["Open Source", "Other", "Other"]):
            engine["manufacturer"] = manufacturer
        for engine, manufacturer in zip(EngineProvider.favorite_engines, ["Favorites", "Favorites", "Classic"]):
            engine["manufacturer"] = manufacturer

        menu.enter_modern_eng_menu()
        manufacturer = await menu.main_down()
        self.assertEqual(MenuState.ENG_MODERN_MANUFACTURER, menu.state)
        self.assertEqual("Open Source", manufacturer.web_text)
        engine_name = await menu.main_down()
        self.assertEqual(MenuState.ENG_MODERN_NAME, menu.state)
        self.assertEqual(0, menu.menu_modern_engine_index)
        menu.main_up()
        self.assertEqual(MenuState.ENG_MODERN_MANUFACTURER, menu.state)

        menu.enter_fav_eng_menu()
        manufacturer = await menu.main_down()
        self.assertEqual(MenuState.ENG_FAV_MANUFACTURER, menu.state)
        self.assertEqual("Favorites", manufacturer.web_text)
        menu.main_right()
        engine_name = await menu.main_down()
        self.assertEqual(MenuState.ENG_FAV_NAME, menu.state)
        self.assertEqual(2, menu.menu_fav_engine_index)
        self.assertEqual(EngineProvider.favorite_engines[2]["text"].large_text, engine_name.large_text)
        menu.main_up()
        self.assertEqual(MenuState.ENG_FAV_MANUFACTURER, menu.state)

    @patch("platform.machine")
    async def test_flat_retro_engine_sort_changes_navigation_not_indexes(self, machine_mock):
        menu = self.create_menu(machine_mock)
        original_names = [engine["name"] for engine in EngineProvider.retro_engines]
        expected_indexes = sorted(
            range(len(EngineProvider.retro_engines)),
            key=lambda index: (EngineProvider.retro_engines[index]["name"].casefold(), index),
        )
        menu.menu_retro_engine_index = expected_indexes[0]
        menu.set_engine_menu_sort("engine")

        menu.enter_retro_eng_menu()
        await menu.main_down()
        self.assertEqual(MenuState.ENG_RETRO_NAME, menu.state)
        menu.main_right()

        self.assertEqual(expected_indexes[1], menu.menu_retro_engine_index)
        self.assertEqual(original_names, [engine["name"] for engine in EngineProvider.retro_engines])

    @patch("platform.machine")
    async def test_modern_engine_retrieval(self, machine_mock):
        menu = self.create_menu(machine_mock)
        menu.set_state_current_engine("")
        menu.enter_top_menu()
        text = await menu.main_down()
        self.assertEqual("Engine", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Modern", text.medium_text.strip())
        await menu.main_down()  # first engine 'Lc0'
        text = menu.main_left()
        self.assertEqual("Fairy-Stock", text.large_text)  # last engine
        text = await menu.main_down()
        self.assertEqual("3check@1000", text.large_text)  # level of Fairy-Stock
        text = await menu.main_down()
        self.assertFalse(text)  # select Fairy-Stock engine
        self.assertEqual("Fairy-Stock", menu.get_current_engine_name().large_text)

        text = await menu.main_down()
        self.assertEqual("Engine", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Modern", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Fairy-Stock", text.large_text)  # previously selected engine

    @patch("platform.machine")
    async def test_retro_engine_retrieval(self, machine_mock):
        menu = self.create_menu(machine_mock)
        menu.set_state_current_engine("")
        menu.enter_top_menu()
        text = await menu.main_down()
        self.assertEqual("Engine", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Modern", text.medium_text.strip())
        text = menu.main_right()
        self.assertEqual("Retro", text.medium_text.strip())
        await menu.main_down()  # first retro engine 'Mep.Academy'
        text = menu.main_left()
        self.assertEqual("Schachzwerg", text.large_text)  # last retro engine
        text = await menu.main_down()
        self.assertFalse(text)  # select Schachzwerg engine
        self.assertEqual("Schachzwerg", menu.get_current_engine_name().large_text)

        text = await menu.main_down()
        self.assertEqual("Engine", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Retro", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Schachzwerg", text.large_text)  # previously selected engine

    @patch("platform.machine")
    async def test_retro_engine_level_selection(self, machine_mock):
        menu = self.create_menu(machine_mock)
        menu.set_state_current_engine("")
        menu.enter_top_menu()
        text = await menu.main_down()
        self.assertEqual("Engine", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Modern", text.medium_text.strip())
        text = menu.main_right()
        self.assertEqual("Retro", text.medium_text.strip())
        await menu.main_down()  # first retro engine 'Mep.Academy'
        menu.main_right()  # second retro engine
        text = menu.main_right()
        self.assertEqual("Mep. Milano", text.large_text)  # third retro engine
        menu.main_left()  # level selection menu
        text = menu.main_left()
        self.assertEqual("Mep.Academy", text.large_text)
        text = await menu.main_down()
        self.assertEqual("Level 00 - speed", text.large_text)
        text = await menu.main_down()
        self.assertFalse(text)
        self.assertEqual("Mep.Academy", menu.get_current_engine_name().large_text)

        text = await menu.main_down()
        self.assertEqual("Engine", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Retro", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Mep.Academy", text.large_text)  # previously selected engine
        text = await menu.main_down()
        self.assertEqual("Level 00 - speed", text.large_text)  # previously selected engine level

    @patch("platform.machine")
    async def test_modern_engine_after_retro(self, machine_mock):
        # select modern engine
        menu = self.create_menu(machine_mock)
        menu.set_state_current_engine("")
        menu.enter_top_menu()
        text = await menu.main_down()
        self.assertEqual("Engine", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Modern", text.medium_text.strip())
        await menu.main_down()  # first engine 'Lc0'
        text = await menu.main_down()
        self.assertEqual("1 Core", text.large_text)  # level
        text = await menu.main_down()
        self.assertFalse(text)  # select engine

        # select retro engine
        menu.enter_top_menu()
        text = await menu.main_down()
        self.assertEqual("Engine", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Modern", text.medium_text.strip())
        text = menu.main_right()
        self.assertEqual("Retro", text.medium_text.strip())
        await menu.main_down()  # first retro engine 'Mep.Academy'
        text = menu.main_left()
        self.assertEqual("Schachzwerg", text.large_text)  # last retro engine
        text = await menu.main_down()
        self.assertFalse(text)  # select Schachzwerg engine

        # re-select modern engine
        menu.enter_top_menu()
        text = await menu.main_down()
        self.assertEqual("Engine", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Retro", text.medium_text.strip())
        text = menu.main_left()
        self.assertEqual("Modern", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Lc0", text.large_text)  # previous modern engine

    @patch("platform.machine")
    async def test_set_state_current_engine_modern(self, machine_mock):
        menu = self.create_menu(machine_mock)
        menu.set_state_current_engine("zurich")
        menu.enter_top_menu()
        text = await menu.main_down()
        self.assertEqual("Engine", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Modern", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("zurichess", text.large_text)

    @patch("platform.machine")
    async def test_set_state_current_engine_retro(self, machine_mock):
        menu = self.create_menu(machine_mock)
        menu.set_state_current_engine("mame/milano")
        menu.enter_top_menu()
        text = await menu.main_down()
        self.assertEqual("Engine", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Retro", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Mep. Milano", text.large_text)

    @patch("platform.machine")
    async def test_set_state_current_engine_favorite(self, machine_mock):
        menu = self.create_menu(machine_mock)
        menu.set_state_current_engine("mame/milano")
        menu.enter_top_menu()
        text = await menu.main_down()
        self.assertEqual("Engine", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Retro", text.medium_text.strip())
        text = menu.main_right()
        self.assertEqual("Ret-Sett", text.medium_text.strip())
        text = menu.main_right()
        self.assertEqual("Special", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Mephisto Milano", text.large_text)

    @patch("platform.machine")
    async def test_engine_not_in_modern_nor_in_retro(self, machine_mock):
        menu = self.create_menu(machine_mock)
        menu.set_state_current_engine("someEngine")
        self.assertEqual(MenuState.ENG_FAV_NAME, menu.state)
        menu.enter_top_menu()
        text = await menu.main_down()
        self.assertEqual("Engine", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Special", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("someEngine", text.large_text)
        text = menu.main_right()
        self.assertEqual("Stockfish 15", text.large_text)

    @patch("platform.machine")
    async def test_power_menu(self, machine_mock):
        menu = self.create_menu(machine_mock)
        menu.set_state_current_engine("mame/tascr30_king")
        menu.enter_top_menu()
        text = await menu.main_down()
        self.assertEqual("Engine", text.medium_text.strip())
        text = menu.main_right()
        self.assertEqual("System", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Power", text.medium_text.strip())
        text = menu.main_right()
        self.assertEqual("Information", text.large_text.strip())
        text = menu.main_right()
        self.assertEqual("Sound", text.large_text.strip())
        text = menu.main_right()
        self.assertEqual("Language", text.large_text.strip())
        text = menu.main_right()
        self.assertEqual("mailLogfile", text.large_text.strip())
        text = menu.main_right()
        self.assertEqual("Voice", text.large_text.strip())
        text = menu.main_right()
        self.assertEqual("Display", text.large_text.strip())
        text = menu.main_right()
        self.assertEqual("E-Board", text.large_text.strip())
        text = menu.main_right()
        self.assertEqual("Wi-Fi", text.large_text.strip())
        text = menu.main_right()
        self.assertEqual("Bluetooth", text.large_text.strip())
        text = menu.main_right()
        self.assertEqual("Web-Theme", text.large_text.strip())
        text = menu.main_right()
        self.assertEqual("Power", text.large_text.strip())
        text = menu.main_left()
        self.assertEqual("Web-Theme", text.large_text.strip())
        text = menu.main_left()
        self.assertEqual("Bluetooth", text.large_text.strip())
        text = menu.main_left()
        self.assertEqual("Wi-Fi", text.large_text.strip())
        text = menu.main_left()
        self.assertEqual("E-Board", text.large_text.strip())
        text = menu.main_left()
        self.assertEqual("Display", text.large_text.strip())
        text = menu.main_left()
        self.assertEqual("Voice", text.large_text.strip())
        text = menu.main_left()
        self.assertEqual("mailLogfile", text.large_text.strip())
        text = menu.main_left()
        self.assertEqual("Language", text.large_text.strip())
        text = menu.main_left()
        self.assertEqual("Sound", text.large_text.strip())
        text = menu.main_left()
        self.assertEqual("Information", text.large_text.strip())
        text = menu.main_left()
        self.assertEqual("Power", text.large_text.strip())
        text = await menu.main_down()
        self.assertEqual("Shut down", text.large_text.strip())
        text = menu.main_right()
        self.assertEqual("Exit Pico", text.large_text.strip())
        text = menu.main_left()
        self.assertEqual("Shut down", text.large_text.strip())

    @patch("platform.machine")
    async def test_sys_info_ip_refreshes_live_internal_ip(self, machine_mock):
        menu = self.create_menu(machine_mock)
        menu.state = MenuState.SYS_INFO_IP
        menu.int_ip = "192.168.0.99"

        with patch("dgt.menu.get_internal_ip", return_value="10.20.30.40"), patch(
            "dgt.menu.Rev2Info.get_web_only", return_value=False
        ), patch("dgt.menu.DispatchDgt.fire", new_callable=AsyncMock) as dispatch_fire:
            text = await menu.main_down()

        self.assertEqual("10.20.30.40", menu.int_ip)
        self.assertEqual(1, dispatch_fire.await_count)
        self.assertEqual("10 20", dispatch_fire.await_args_list[0].args[0].large_text.strip())
        self.assertEqual("30 40", text.large_text.strip())

    @patch("platform.machine")
    async def test_sys_info_ip_falls_back_to_cached_ip(self, machine_mock):
        menu = self.create_menu(machine_mock)
        menu.state = MenuState.SYS_INFO_IP
        menu.int_ip = "192.168.0.99"

        with patch("dgt.menu.get_internal_ip", return_value=None), patch(
            "dgt.menu.Rev2Info.get_web_only", return_value=True
        ), patch(
            "dgt.menu.DispatchDgt.fire", new_callable=AsyncMock
        ) as dispatch_fire:
            text = await menu.main_down()

        self.assertEqual("192.168.0.99", menu.int_ip)
        self.assertEqual(0, dispatch_fire.await_count)
        self.assertEqual("192.168.0.99", text.web_text.strip())
        self.assertEqual("192.168.0.9", text.large_text.strip())

    @patch("platform.machine")
    async def test_sys_info_ip_temporarily_suppresses_no_eboard_spinner(self, machine_mock):
        menu = self.create_menu(machine_mock)
        menu.state = MenuState.SYS_INFO_IP

        with patch("dgt.menu.get_internal_ip", return_value="10.20.30.40"), patch(
            "dgt.menu.Rev2Info.get_web_only", return_value=True
        ), patch("dgt.menu.DispatchDgt.fire", new_callable=AsyncMock), patch("dgt.menu.time.time", return_value=100.0):
            await menu.main_down()

        with patch("dgt.menu.time.time", return_value=102.0):
            self.assertTrue(menu.is_no_eboard_spinner_suppressed())
        with patch("dgt.menu.time.time", return_value=103.1):
            self.assertFalse(menu.is_no_eboard_spinner_suppressed())

    @patch("platform.machine")
    async def test_node_menu(self, machine_mock):
        menu = self.create_menu(machine_mock)
        menu.set_state_current_engine("")
        text = menu.get_current_engine_name()
        self.assertEqual("Lc0", text.large_text)
        menu.enter_top_menu()
        self.assertEqual(MenuState.TOP, menu.state)
        await menu.main_down()
        # start with engine menu from top menu
        menu.main_left()
        menu.main_left()
        self.assertEqual(MenuState.TIME, menu.state)
        await menu.main_down()
        menu.main_left()
        menu.main_left()
        self.assertEqual(MenuState.TIME_NODE, menu.state)
        menu.main_right()
        menu.main_left()
        self.assertEqual(MenuState.TIME_NODE, menu.state)
        text = await menu.main_down()
        self.assertEqual(MenuState.TIME_NODE_CTRL, menu.state)
        self.assertEqual("Nodes  1", text.large_text.strip())
        text = menu.main_right()
        self.assertEqual("Nodes  5", text.large_text.strip())
        text = menu.main_left()
        self.assertEqual("Nodes  1", text.large_text.strip())
        text = menu.main_left()
        self.assertEqual("Nodes 500", text.large_text.strip())
