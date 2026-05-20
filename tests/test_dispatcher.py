import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from dispatcher import Dispatcher
from dgt.api import Dgt
from dgt.menu import DgtMenu
from dgt.translate import DgtTranslate
from dgt.util import ClockSide, EBoard, PicoCoach, PicoComment
from uci.engine_provider import EngineProvider
from uci.read import read_engine_ini


class TestDispatcherMenuCompatibility(unittest.IsolatedAsyncioTestCase):
    def create_menu(self):
        with patch("subprocess.run") as machine_mock:
            machine_mock.return_value = ".." + os.sep + "tests"
            EngineProvider.modern_engines = read_engine_ini(filename="engines.ini")
            EngineProvider.retro_engines = read_engine_ini(filename="retro.ini")
            EngineProvider.favorite_engines = read_engine_ini(filename="favorites.ini")
            EngineProvider.installed_engines = list(
                EngineProvider.modern_engines + EngineProvider.retro_engines + EngineProvider.favorite_engines
            )

        trans = DgtTranslate("none", 0, "en", "version")
        return DgtMenu(
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

    async def test_display_text_and_clock_start_do_not_require_newer_update_menu(self):
        menu = self.create_menu()
        dispatcher = Dispatcher(menu, asyncio.get_running_loop())
        dispatcher.register("web")

        with patch("dispatcher.DisplayDgt.show", new_callable=AsyncMock) as show:
            await dispatcher._process_message(Dgt.CLOCK_VERSION(main=2, sub=0, devs={"web"}), "web")
            await dispatcher._process_message(
                Dgt.DISPLAY_TEXT(
                    web_text="Mode",
                    large_text="Mode",
                    medium_text="Mode",
                    small_text="Mode",
                    beep=False,
                    maxtime=0,
                    devs={"web"},
                    wait=True,
                    ld=None,
                    rd=None,
                ),
                "web",
            )
            await dispatcher._process_message(Dgt.CLOCK_START(side=ClockSide.LEFT, wait=True, devs={"web"}), "web")

        self.assertEqual(3, show.await_count)

    def test_picochess_display_marker_is_device_scoped(self):
        menu = self.create_menu()

        menu.enable_picochess_displayed("web")
        self.assertTrue(menu.inside_picochess_time("web"))
        self.assertFalse(menu.inside_picochess_time("ser"))

        menu.disable_picochess_displayed("web")
        self.assertFalse(menu.inside_picochess_time("web"))


if __name__ == "__main__":
    unittest.main()
