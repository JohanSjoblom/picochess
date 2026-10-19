import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

import chess

import picostate
from dgt.util import Mode
from picostate import PicochessState


class TestClockSettle(unittest.IsolatedAsyncioTestCase):
    """An engine search must not wait for the clock to settle, but CLOCK_STOP still does (#529)."""

    def setUp(self):
        self.state = object.__new__(PicochessState)
        self.state.interaction_mode = Mode.NORMAL
        self.state.game = chess.Board()
        self.state.main_loop = None
        self.state.clock_settle_until = 0.0
        self.state.time_control = Mock()
        self.state.time_control.get_parameters.return_value = {}
        self.calls = Mock()
        self.sleep = AsyncMock(side_effect=lambda seconds: self.calls.sleep(seconds))
        self.show = AsyncMock(side_effect=lambda message: self.calls.show(repr(message)))
        self.state.time_control.stop_internal.side_effect = lambda **kwargs: self.calls.stop_internal()
        self.now = 100.0
        # Replace only picostate's references, not the real asyncio/time modules the event loop uses.
        for name, replacement in (
            ("asyncio", SimpleNamespace(sleep=self.sleep)),
            ("time", SimpleNamespace(monotonic=lambda: self.now)),
        ):
            patcher = patch.object(picostate, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(picostate.DisplayMsg, "show", self.show)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_default_start_waits_for_the_clock(self):
        await self.state.start_clock()

        self.sleep.assert_awaited_once_with(0.5)
        self.assertEqual(0.0, self.state.clock_settle_until)

    async def test_unsettled_start_returns_at_once(self):
        await self.state.start_clock(settle=False)

        self.sleep.assert_not_awaited()
        self.state.time_control.start_internal.assert_called_once()
        self.assertEqual(100.5, self.state.clock_settle_until)

    async def test_stop_after_unsettled_start_waits_for_the_rest_of_the_settle_time(self):
        await self.state.start_clock(settle=False)
        self.now = 100.2
        self.calls.reset_mock()

        await self.state.stop_clock()

        # Time is stopped at once; only the CLOCK_STOP message waits for the clock to settle.
        self.assertEqual("stop_internal", self.calls.mock_calls[0][0])
        self.assertEqual(self.calls.mock_calls[1], call.sleep(unittest.mock.ANY))
        self.assertAlmostEqual(0.3, self.calls.mock_calls[1].args[0])
        self.assertEqual("show", self.calls.mock_calls[2][0])
        self.assertEqual(call.sleep(0.7), self.calls.mock_calls[3])
        self.assertEqual(0.0, self.state.clock_settle_until)

    async def test_stop_after_settled_clock_does_not_wait_extra(self):
        await self.state.start_clock(settle=False)
        self.now = 101.0  # the engine searched longer than the settle time
        self.sleep.reset_mock()

        await self.state.stop_clock()

        self.sleep.assert_awaited_once_with(0.7)


if __name__ == "__main__":
    unittest.main()
