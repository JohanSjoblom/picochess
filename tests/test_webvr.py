import unittest
from unittest.mock import AsyncMock, Mock, patch

from dgt.api import Dgt
from dgt.util import ClockSide
from server import WebVr


class DummyBoard:
    is_pi = False


class TestWebVr(unittest.IsolatedAsyncioTestCase):

    async def test_result_text_tag_survives_stop_and_is_cleared_by_other_text(self):
        web = WebVr(shared={}, dgtboard=DummyBoard(), loop=None)
        web.side_running = ClockSide.NONE
        message = Dgt.DISPLAY_TEXT(web_text="Checkmate", large_text="Mate", devs={"web"})
        message.game_result = True
        with patch("server.EventHandler.write_to_clients") as send:
            web.display_text_on_clock(message)
            self.assertTrue(send.call_args.args[0]["game_result"])
            await web.stop_clock({"web"})
            self.assertTrue(send.call_args.args[0]["game_result"])
            web.display_text_on_clock(Dgt.DISPLAY_TEXT(web_text="Analysis", large_text="Analysis", devs={"web"}))
            self.assertNotIn("game_result", send.call_args.args[0])
            self.assertFalse(web.shared["clock_game_result"])

    async def test_set_clock_refreshes_stopped_time_display_immediately(self):
        web = WebVr(shared={}, dgtboard=DummyBoard(), loop=None)
        web.side_running = ClockSide.NONE
        web.clock_show_time = True
        web._display_time = Mock()

        web.set_clock(61, 61, {"web"})

        web._display_time.assert_called_once_with(61, 61)

    async def test_set_clock_preserves_active_timed_text(self):
        web = WebVr(shared={}, dgtboard=DummyBoard(), loop=None)
        web.side_running = ClockSide.NONE
        web.clock_show_time = False
        web._display_time = Mock()

        web.set_clock(61, 61, {"web"})

        web._display_time.assert_not_called()

    async def test_display_time_restores_stopped_clock_after_timed_message(self):
        shared = {"clock_text": "12...c5b6"}
        web = WebVr(shared=shared, dgtboard=DummyBoard(), loop=None)
        web.side_running = ClockSide.NONE
        web.clock_show_time = False
        web.l_time = 61
        web.r_time = 62
        message = Mock(devs={"web"}, force=False)

        with patch("server.EventHandler.write_to_clients") as write_to_clients:
            web.display_time_on_clock(message)

        self.assertTrue(web.clock_show_time)
        self.assertNotEqual("12...c5b6", shared["clock_text"])
        self.assertIn("ctime-l", shared["clock_text"])
        event = write_to_clients.call_args.args[0]
        self.assertEqual("Clock", event["event"])
        self.assertFalse(event["running"])

    async def test_display_time_clears_timed_message_before_clock_is_set(self):
        shared = {"clock_text": "12...c5b6"}
        web = WebVr(shared=shared, dgtboard=DummyBoard(), loop=None)
        web.side_running = ClockSide.NONE
        web.clock_show_time = False
        message = Mock(devs={"web"}, force=False)

        with patch("server.EventHandler.write_to_clients") as write_to_clients:
            web.display_time_on_clock(message)

        self.assertEqual("", shared["clock_text"])
        self.assertEqual("", write_to_clients.call_args.args[0]["msg"])
        self.assertFalse(write_to_clients.call_args.args[0]["running"])

    async def test_runclock_accumulates_fractional_delay(self):
        web = WebVr(shared={}, dgtboard=DummyBoard(), loop=None)
        web.side_running = ClockSide.LEFT
        web.l_time = 60
        web.r_time = 60
        web._last_runclock_time = 100.0
        web._runclock_elapsed_carry = 0.0
        web._display_time = Mock()

        tick_times = [101.1, 102.2, 103.3, 104.4, 105.5, 106.6, 107.7, 108.8, 109.9, 111.0]

        with patch("server.DisplayMsg.show", new=AsyncMock()):
            with patch("server.time.time", side_effect=tick_times):
                for _ in tick_times:
                    await web._runclock()

        self.assertEqual(49, web.l_time)
        self.assertEqual(60, web.r_time)


if __name__ == "__main__":
    unittest.main()
