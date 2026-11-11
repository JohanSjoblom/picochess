"""Retro speed changes reach a running MAME engine without a restart (issue #564)."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import mainloop
from dgt.api import Event, Message
from dgt.util import Mode, PlayMode
from pgn import PgnDisplay
from server import WebDisplay
from uci.engine import UciEngine


class TestRetroSpeedEvents(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.controller = object.__new__(mainloop.MainLoop)
        self.controller.state = SimpleNamespace(
            position_checkpoint_restore_pending=False,
            dgtmenu=SimpleNamespace(set_retro_speed=Mock(), get_engine_rspeed=Mock(return_value=2.0)),
        )
        self.controller.engine = SimpleNamespace(set_mame_speed=Mock(return_value=True))
        self.controller.emulation_mode = Mock(return_value=True)
        self.controller.calc_engine_mame_par = Mock(return_value="-speed 2.0 -sound none")
        self.controller.restart_retro_engine = AsyncMock()
        self.controller.update_elo_display = AsyncMock()
        show = patch.object(mainloop.DisplayMsg, "show", new_callable=AsyncMock)
        self.show = show.start()
        self.addCleanup(show.stop)

    async def test_speed_change_goes_to_the_running_engine(self):
        await self.controller.process_main_events(Event.RSPEED(rspeed=2.0))
        self.controller.state.dgtmenu.set_retro_speed.assert_called_once_with(2.0)
        self.controller.engine.set_mame_speed.assert_called_once_with(2.0, "-speed 2.0 -sound none")
        self.controller.restart_retro_engine.assert_not_awaited()
        shown = self.show.await_args.args[0]
        self.assertIsInstance(shown, Message.RSPEED)
        self.assertEqual(2.0, shown.rspeed)
        self.controller.update_elo_display.assert_awaited_once()

    async def test_speed_change_falls_back_to_a_restart(self):
        self.controller.engine.set_mame_speed.return_value = False
        await self.controller.process_main_events(Event.RSPEED(rspeed=0.5))
        self.controller.restart_retro_engine.assert_awaited_once()
        self.controller.update_elo_display.assert_not_awaited()  # the restart updates it

    async def test_speed_change_outside_emulation_only_saves_the_setting(self):
        self.controller.emulation_mode.return_value = False
        await self.controller.process_main_events(Event.RSPEED(rspeed=1.5))
        self.controller.state.dgtmenu.set_retro_speed.assert_called_once_with(1.5)
        self.controller.engine.set_mame_speed.assert_not_called()
        self.controller.restart_retro_engine.assert_not_awaited()

    async def test_sound_or_display_change_restarts_the_engine(self):
        await self.controller.process_main_events(Event.RETRO_RESTART())
        self.controller.restart_retro_engine.assert_awaited_once()
        self.controller.engine.set_mame_speed.assert_not_called()

    async def test_restart_event_outside_emulation_does_nothing(self):
        self.controller.emulation_mode.return_value = False
        await self.controller.process_main_events(Event.RETRO_RESTART())
        self.controller.restart_retro_engine.assert_not_awaited()


class TestSetMameSpeed(unittest.TestCase):
    def make_engine(self, is_mame=True, running=True):
        engine = object.__new__(UciEngine)
        engine.is_mame = is_mame
        engine.file = "/opt/picochess/engines/x86_64/mame/ivant"
        engine.mame_par = "-speed 1.0 -sound none"
        returncode = Mock()
        returncode.done.return_value = not running
        engine.engine = SimpleNamespace(send_line=Mock(), returncode=returncode)
        return engine

    def test_sends_the_speed_in_percent(self):
        engine = self.make_engine()
        self.assertTrue(engine.set_mame_speed(1.5, "-speed 1.5 -sound none"))
        engine.engine.send_line.assert_called_once_with("setoption name Speed value 150")
        self.assertEqual("-speed 1.5 -sound none", engine.mame_par)

    def test_max_speed_is_sent_as_zero(self):
        engine = self.make_engine()
        self.assertTrue(engine.set_mame_speed(0.0, "-nothrottle -sound none"))
        engine.engine.send_line.assert_called_once_with("setoption name Speed value 0")
        self.assertEqual("-nothrottle -sound none", engine.mame_par)

    def test_not_a_mame_engine(self):
        engine = self.make_engine(is_mame=False)
        self.assertFalse(engine.set_mame_speed(2.0, "-speed 2.0"))
        engine.engine.send_line.assert_not_called()
        self.assertEqual("-speed 1.0 -sound none", engine.mame_par)

    def test_engine_process_has_ended(self):
        engine = self.make_engine(running=False)
        self.assertFalse(engine.set_mame_speed(2.0, "-speed 2.0"))
        engine.engine.send_line.assert_not_called()

    def test_no_engine_open(self):
        engine = self.make_engine()
        engine.engine = None
        self.assertFalse(engine.set_mame_speed(2.0, "-speed 2.0"))

    def test_send_failure_is_reported(self):
        engine = self.make_engine()
        engine.engine.send_line.side_effect = RuntimeError("closed")
        self.assertFalse(engine.set_mame_speed(2.0, "-speed 2.0"))
        self.assertEqual("-speed 1.0 -sound none", engine.mame_par)


class TestSpeedMetadataReachesWebAndPgn(unittest.IsolatedAsyncioTestCase):
    """A live speed change updates the speed the web page and the PGN headers show."""

    async def test_live_change_updates_web_and_pgn_speed(self):
        controller = object.__new__(mainloop.MainLoop)
        controller.state = SimpleNamespace(
            position_checkpoint_restore_pending=False,
            interaction_mode=Mode.NORMAL,
            dgtmenu=FakeRetroMenu(1.0),
        )
        controller.engine = SimpleNamespace(set_mame_speed=Mock(return_value=True), is_adaptive=False, engine_rating=0)
        controller.emulation_mode = Mock(return_value=True)
        controller.calc_engine_mame_par = Mock(return_value="-speed 2.0 -sound none")
        controller.restart_retro_engine = AsyncMock()

        loop = asyncio.get_running_loop()
        pgn_display = PgnDisplay("test", None, {}, loop)
        shared = {
            "headers": {},
            "system_info": {"rspeed": 1.0, "engine_name": "Chesster"},
            "game_info": {"play_mode": PlayMode.USER_WHITE},
        }
        web_display = WebDisplay(shared, loop)

        with patch.object(mainloop.DisplayMsg, "show", new_callable=AsyncMock) as show:
            await controller.process_main_events(Event.RSPEED(rspeed=2.0))
        infos = [c.args[0] for c in show.await_args_list if isinstance(c.args[0], Message.SYSTEM_INFO)]
        self.assertEqual([{"rspeed": 2.0}], [m.info for m in infos])

        with (
            patch("server.EventHandler.write_to_clients") as write_to_clients,
            patch.object(WebDisplay, "engine_name", "Chesster"),
            patch("server.ModeInfo.get_emulation_mode", return_value=True),
            patch("server.ModeInfo.get_pgn_mode", return_value=False),
        ):
            for message in infos:
                await pgn_display._process_message(message)
                await web_display.task(message)
            # the same speed again sends no new headers
            write_to_clients.reset_mock()
            await web_display.task(Message.SYSTEM_INFO(info={"rspeed": 2.0}))
            write_to_clients.assert_not_called()
        self.assertEqual(2.0, pgn_display.rspeed)
        self.assertEqual(2.0, shared["system_info"]["rspeed"])
        # the web page shows the speed in the engine's header name right away
        self.assertEqual("Chesster (200%)", shared["headers"].get("Black"))


class FakeRetroMenu(SimpleNamespace):
    """Just the retro settings of the DGT menu."""

    def __init__(self, rspeed):
        super().__init__(rspeed=rspeed, engine_index=None)

    def get_engine_rdisplay(self):
        return False

    def get_engine_rspeed(self):
        return self.rspeed

    def set_retro_speed(self, rspeed):
        self.rspeed = rspeed

    def set_engine_index(self, index):
        self.engine_index = index


class StopHere(Exception):
    pass


class TestNewRetroMachineSpeed(unittest.IsolatedAsyncioTestCase):
    """Selecting a retro machine starts it at real speed (100%), saved only when the selection succeeds."""

    OLD_FILE = "/opt/picochess/engines/x86_64/mame/ivant"
    NEW_FILE = "/opt/picochess/engines/x86_64/mame/chesster"

    def setUp(self):
        self.controller = object.__new__(mainloop.MainLoop)
        self.dgtmenu = FakeRetroMenu(2.0)
        self.controller.state = SimpleNamespace(
            position_checkpoint_restore_pending=False,
            best_sent_depth=SimpleNamespace(reset=Mock()),
            engine_file=self.OLD_FILE,
            artwork_in_use=False,
            dgtmenu=self.dgtmenu,
            rating=None,
            new_game_msg=Mock(return_value="new game"),
            engine_board_copy=Mock(),
            old_engine_level="",
            new_engine_level="",
        )
        self.controller.engine = SimpleNamespace(get_pgn_options=Mock(return_value={"Level": "5"}), quit=AsyncMock())
        self.controller._clear_set_position_ack = Mock()
        self.controller.get_rid_of_engine_move = AsyncMock()
        self.controller.stop_search = AsyncMock()
        self.controller._init_variant_from_engine = Mock()
        self.controller.engine_mode = AsyncMock()
        self.controller.emulation_mode = Mock(return_value=False)  # skip the new-game reset, tested elsewhere
        self.controller.online_mode = Mock(return_value=False)
        self.controller.pgn_mode = Mock(return_value=False)
        self.controller.remote_engine_mode = Mock(return_value=False)
        self.controller.uci_local_shell = None
        self.controller.calc_engine_mame_par = lambda: "-speed %s" % self.dgtmenu.get_engine_rspeed()
        self.controller.loop = None
        self.controller.shared = {}
        patch.object(mainloop.DisplayMsg, "show", new_callable=AsyncMock).start()
        patch.object(mainloop.ModeInfo, "set_retro_features").start()
        patch.object(mainloop.EngineProvider, "installed_engines", [{"file": self.OLD_FILE}]).start()
        self.write_ini = patch.object(mainloop, "write_picochess_ini").start()
        self.addCleanup(patch.stopall)
        self.started = []  # (file, mame_par) of each engine start

    def engine_factory(self, *loaded):
        """UciEngine stand-in: the n-th engine started loads ok if loaded[n]."""

        def make(file, uci_shell, mame_par, loop):
            self.started.append((file, mame_par))
            ok = loaded[len(self.started) - 1]
            return SimpleNamespace(
                open_engine=AsyncMock(),
                loaded_ok=Mock(return_value=ok),
                startup=AsyncMock(return_value=True),
                newgame=AsyncMock(),
                quit=AsyncMock(),
                get_mame_capabilities=Mock(return_value=SimpleNamespace(retro_info=Mock(return_value=""))),
            )

        patch.object(mainloop, "UciEngine", side_effect=make).start()

    async def select(self, file):
        await self.controller.process_main_events(
            Event.NEW_ENGINE(eng={"file": file}, eng_text={}, options={}, show_ok=False)
        )

    async def test_new_retro_machine_starts_at_real_speed_and_saves_it(self):
        self.engine_factory(True)
        # stop right after the success branch has saved the settings
        patch.object(mainloop, "clear_preserved_mame_history", side_effect=StopHere).start()
        with self.assertRaises(StopHere):
            await self.select(self.NEW_FILE)
        self.assertEqual([(self.NEW_FILE, "-speed 1.0")], self.started)
        self.assertEqual(1.0, self.dgtmenu.rspeed)
        self.write_ini.assert_called_once_with("rspeed", 1.0)

    async def test_failed_retro_selection_restores_old_engine_and_speed(self):
        self.engine_factory(False, True)
        patch.object(mainloop.MainLoop, "set_wait_state", side_effect=StopHere, create=True).start()
        with self.assertRaises(StopHere):
            await self.select(self.NEW_FILE)
        self.assertEqual([(self.NEW_FILE, "-speed 1.0"), (self.OLD_FILE, "-speed 2.0")], self.started)
        self.assertEqual(self.OLD_FILE, self.controller.state.engine_file)
        self.assertEqual(2.0, self.dgtmenu.rspeed)
        self.assertEqual(0, self.dgtmenu.engine_index)
        self.assertNotIn("rspeed", [c.args[0] for c in self.write_ini.call_args_list])

    async def test_other_engine_keeps_the_retro_speed(self):
        self.engine_factory(True)
        patch.object(mainloop, "clear_preserved_mame_history", side_effect=StopHere).start()
        with self.assertRaises(StopHere):
            await self.select("/opt/picochess/engines/x86_64/stockfish17")
        self.assertEqual(2.0, self.dgtmenu.rspeed)
        self.write_ini.assert_not_called()


if __name__ == "__main__":
    unittest.main()
