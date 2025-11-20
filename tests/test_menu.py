import os

import unittest
from unittest.mock import patch

from dgt.menu import DgtMenu, MenuState
from dgt.translate import DgtTranslate
from dgt.util import PicoComment, EBoard, PicoCoach
from uci.read import read_engine_ini
from uci.engine_provider import EngineProvider


class TestDgtMenu(unittest.IsolatedAsyncioTestCase):
    @patch("subprocess.run")
    def create_menu(self, machine_mock, _):
        machine_mock.return_value = ".." + os.sep + "tests"  # return the tests path as the platform engine path
        EngineProvider.modern_engines = read_engine_ini(filename="engines.ini")
        EngineProvider.retro_engines = read_engine_ini(filename="retro.ini")
        EngineProvider.favorite_engines = read_engine_ini(filename="favorites.ini")
        EngineProvider.installed_engines = list(
            EngineProvider.modern_engines + EngineProvider.retro_engines + EngineProvider.favorite_engines
        )

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
            rdisplay=False,
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
        self.assertEqual("zurichess", text.large_text)  # last engine
        text = await menu.main_down()
        self.assertEqual("level     0", text.large_text)  # level of zurichess
        text = await menu.main_down()
        self.assertFalse(text)  # select zurichess engine
        self.assertEqual("zurichess", menu.get_current_engine_name().large_text)

        text = await menu.main_down()
        self.assertEqual("Engine", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("Modern", text.medium_text.strip())
        text = await menu.main_down()
        self.assertEqual("zurichess", text.large_text)  # previously selected engine

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
        self.assertEqual("Web-Theme", text.large_text.strip())
        text = menu.main_right()
        self.assertEqual("Power", text.large_text.strip())
        text = menu.main_left()
        self.assertEqual("Web-Theme", text.large_text.strip())
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
