"""Retro speed changes reach a running MAME engine without a restart (issue #564)."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import mainloop
from dgt.api import Event, Message
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

    async def test_speed_change_falls_back_to_a_restart(self):
        self.controller.engine.set_mame_speed.return_value = False
        await self.controller.process_main_events(Event.RSPEED(rspeed=0.5))
        self.controller.restart_retro_engine.assert_awaited_once()

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


if __name__ == "__main__":
    unittest.main()


class StopBeforeEngineStart(Exception):
    pass


class TestNewRetroMachineSpeed(unittest.IsolatedAsyncioTestCase):
    """Selecting a retro machine starts it at real speed (100%)."""

    def setUp(self):
        self.controller = object.__new__(mainloop.MainLoop)
        self.dgtmenu = SimpleNamespace(
            get_engine_rdisplay=Mock(return_value=False),
            get_engine_rspeed=Mock(return_value=2.0),
            set_retro_speed=Mock(),
        )
        self.controller.state = SimpleNamespace(
            position_checkpoint_restore_pending=False,
            best_sent_depth=SimpleNamespace(reset=Mock()),
            engine_file="/opt/picochess/engines/x86_64/stockfish",
            artwork_in_use=False,
            dgtmenu=self.dgtmenu,
        )
        self.controller.engine = SimpleNamespace(get_pgn_options=Mock(return_value={}), quit=AsyncMock())
        self.controller._clear_set_position_ack = Mock()
        self.controller.get_rid_of_engine_move = AsyncMock()
        self.controller.emulation_mode = Mock(return_value=True)
        self.controller.remote_engine_mode = Mock(return_value=False)
        self.controller.uci_local_shell = None
        self.controller.calc_engine_mame_par = Mock(return_value="-speed 1.0")
        self.controller.loop = None
        for target, attr in ((mainloop.DisplayMsg, "show"),):
            p = patch.object(target, attr, new_callable=AsyncMock)
            p.start()
            self.addCleanup(p.stop)
        self.write_ini = patch.object(mainloop, "write_picochess_ini").start()
        self.addCleanup(patch.stopall)
        self.engine_cls = patch.object(mainloop, "UciEngine", side_effect=StopBeforeEngineStart).start()

    async def select(self, file):
        with self.assertRaises(StopBeforeEngineStart):
            await self.controller.process_main_events(Event.NEW_ENGINE(eng={"file": file}, eng_text={}, options={}, show_ok=False))

    async def test_new_retro_machine_starts_at_real_speed(self):
        await self.select("/opt/picochess/engines/x86_64/mame/ivant")
        self.dgtmenu.set_retro_speed.assert_called_once_with(1.0)
        self.write_ini.assert_called_once_with("rspeed", 1.0)

    async def test_other_engine_keeps_the_retro_speed(self):
        await self.select("/opt/picochess/engines/x86_64/stockfish17")
        self.dgtmenu.set_retro_speed.assert_not_called()
        self.write_ini.assert_not_called()
