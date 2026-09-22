import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import mainloop
from dgt.api import Event
from dgt.util import EBoard, Mode


class TestBoardDisconnectClock(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.controller = object.__new__(mainloop.MainLoop)
        self.controller._board_clock_transition_lock = asyncio.Lock()
        self.controller.board_type = EBoard.DGT
        self.controller.online_mode = Mock(return_value=False)
        self.running = True
        self.controller.state = SimpleNamespace(
            interaction_mode=Mode.NORMAL,
            game_declared=False,
            clock_paused_by_board_loss=False,
            position_mode=False,
            done_computer_fen=None,
            is_not_user_turn=Mock(return_value=False),
            time_control=SimpleNamespace(internal_running=lambda: self.running),
            dgtmenu=SimpleNamespace(inside_main_menu=Mock(return_value=False)),
            stop_clock=AsyncMock(side_effect=self.stop_clock),
            start_clock=AsyncMock(side_effect=self.start_clock),
        )
        self.game_ending = patch.object(mainloop.ModeInfo, "get_game_ending", return_value="*")
        self.game_ending.start()
        self.addCleanup(self.game_ending.stop)

    async def stop_clock(self):
        self.running = False

    async def start_clock(self):
        self.running = True

    async def test_pauses_running_user_clock(self):
        await self.controller._board_connection_lost()
        self.controller.state.stop_clock.assert_awaited_once()
        self.assertTrue(self.controller.state.clock_paused_by_board_loss)

    async def test_does_not_pause_engine_turn(self):
        self.controller.state.is_not_user_turn.return_value = True
        await self.controller._board_connection_lost()
        self.controller.state.stop_clock.assert_not_awaited()

    async def test_does_not_pause_online_game(self):
        self.controller.online_mode.return_value = True
        await self.controller._board_connection_lost()
        self.controller.state.stop_clock.assert_not_awaited()

    async def test_does_not_pause_web_only_game(self):
        self.controller.board_type = EBoard.NOEBOARD
        await self.controller._board_connection_lost()
        self.controller.state.stop_clock.assert_not_awaited()

    async def test_does_not_pause_already_stopped_clock(self):
        self.running = False
        await self.controller._board_connection_lost()
        self.controller.state.stop_clock.assert_not_awaited()

    async def test_reconnect_resumes_once_after_board_loss(self):
        await self.controller._board_connection_lost()
        await self.controller._board_connection_restored()
        await self.controller._board_connection_restored()
        self.controller.state.start_clock.assert_awaited_once()
        self.assertFalse(self.controller.state.clock_paused_by_board_loss)

    async def test_reconnect_does_not_start_clock_without_board_loss_pause(self):
        await self.controller._board_connection_restored()
        self.controller.state.start_clock.assert_not_awaited()

    async def test_reconnect_does_not_resume_clock_while_menu_is_open(self):
        await self.controller._board_connection_lost()
        self.controller.state.dgtmenu.inside_main_menu.return_value = True
        await self.controller._board_connection_restored()
        self.controller.state.start_clock.assert_not_awaited()
        self.assertFalse(self.controller.state.clock_paused_by_board_loss)

    async def test_board_events_route_to_clock_handlers(self):
        self.controller.state.position_checkpoint_restore_pending = False
        await self.controller.process_main_events(Event.BOARD_CONNECTION_LOST())
        await self.controller.process_main_events(Event.BOARD_CONNECTION_RESTORED())
        self.controller.state.stop_clock.assert_awaited_once()
        self.controller.state.start_clock.assert_awaited_once()
