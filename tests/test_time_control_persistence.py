import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

import mainloop
from dgt.api import Event
from dgt.util import TimeMode
from timecontrol import TimeControl


class TestTimeControlPersistence(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.write_ini = Mock()
        self.show = AsyncMock()
        self.write_patcher = patch.object(mainloop, "write_picochess_ini", self.write_ini)
        self.show_patcher = patch.object(mainloop.DisplayMsg, "show", self.show)
        self.write_patcher.start()
        self.show_patcher.start()
        self.addCleanup(self.write_patcher.stop)
        self.addCleanup(self.show_patcher.stop)

        self.controller = object.__new__(mainloop.MainLoop)
        self.controller.state = SimpleNamespace(
            time_control=Mock(),
            dgtmenu=Mock(),
            stop_fen_timer=Mock(),
            position_checkpoint_restore_pending=False,
        )
        self.controller.pgn_mode = Mock(return_value=False)
        self.controller.online_mode = Mock(return_value=False)
        self.controller.engine = Mock()

    async def set_time_control(self, time_control):
        await self.controller.process_main_events(
            Event.SET_TIME_CONTROL(
                tc_init=time_control.get_parameters(),
                time_text=Mock(),
                show_ok=False,
            )
        )

    async def test_fischer_clears_stale_depth_and_node_overrides(self):
        await self.set_time_control(TimeControl(TimeMode.FISCHER, blitz=5, fischer=3))

        self.assertEqual(
            [call("time", "5 3"), call("depth", "0"), call("node", "0")],
            self.write_ini.call_args_list,
        )

    async def test_depth_control_keeps_explicit_override(self):
        await self.set_time_control(TimeControl(TimeMode.FIXED, depth=5))

        self.assertEqual(
            [call("time", "671"), call("depth", "5"), call("node", "0")],
            self.write_ini.call_args_list,
        )
        self.controller.engine.drop_engine_uci_option.assert_has_calls(
            [call("PicoDepth"), call("PicoNode")]
        )


if __name__ == "__main__":
    unittest.main()
