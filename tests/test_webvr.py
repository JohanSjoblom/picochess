import unittest
from unittest.mock import AsyncMock, Mock, patch

from dgt.util import ClockSide
from server import WebVr


class DummyBoard:
    is_pi = False


class TestWebVr(unittest.IsolatedAsyncioTestCase):

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
