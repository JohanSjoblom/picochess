import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import chess

import mainloop
from dgt.api import Event, Message
from dgt.display import DgtDisplay
from dgt.util import GameResult, PlayMode, Mode, TimeMode, game_ending_from_result
from pgn import ModeInfo
from timecontrol import TimeControl
from utilities import DisplayMsg
from tests.test_dgt_display import DummyMenu, DummyTranslate


def _game_ends(result, game=None):
    return Message.GAME_ENDS(
        tc_init={},
        result=result,
        play_mode=PlayMode.USER_WHITE,
        game=game or chess.Board(),
        mode=Mode.NORMAL,
    )


class TestGameEndingFromResult(unittest.TestCase):
    def test_declared_results(self):
        board = chess.Board()
        self.assertEqual("1/2-1/2", game_ending_from_result(GameResult.DRAW, board))
        self.assertEqual("1-0", game_ending_from_result(GameResult.WIN_WHITE, board))
        self.assertEqual("0-1", game_ending_from_result(GameResult.WIN_BLACK, board))
        self.assertEqual("1-0", game_ending_from_result(GameResult.KOTH_WHITE, board))
        self.assertEqual("0-1", game_ending_from_result(GameResult.ANTICHESS_BLACK, board))

    def test_mate_and_time_go_to_the_side_that_moved_last(self):
        white_to_move = chess.Board()
        black_to_move = chess.Board()
        black_to_move.push_san("e4")
        self.assertEqual("0-1", game_ending_from_result(GameResult.MATE, white_to_move))
        self.assertEqual("1-0", game_ending_from_result(GameResult.OUT_OF_TIME, black_to_move))

    def test_abort_leaves_the_ending_unchanged(self):
        self.assertIsNone(game_ending_from_result(GameResult.ABORT, chess.Board()))


class TestGameEndingRecordedOnSend(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ModeInfo.set_game_ending(result="*")
        self.addCleanup(lambda: ModeInfo.set_game_ending(result="*"))

    async def test_show_records_the_result_before_any_display_runs(self):
        with patch("utilities.msgdisplay_devices", []):
            await DisplayMsg.show(_game_ends(GameResult.WIN_BLACK))
        self.assertEqual("0-1", ModeInfo.get_game_ending())

    async def test_show_of_abort_keeps_an_earlier_result(self):
        ModeInfo.set_game_ending(result="1-0")
        with patch("utilities.msgdisplay_devices", []):
            await DisplayMsg.show(_game_ends(GameResult.ABORT))
        self.assertEqual("1-0", ModeInfo.get_game_ending())

    async def test_late_display_message_does_not_end_a_new_game(self):
        menu = DummyMenu()
        menu.get_engine_restart = lambda: False
        display = DgtDisplay(
            DummyTranslate(), menu, TimeControl(mode=TimeMode.FIXED, fixed=0), asyncio.get_running_loop()
        )
        # The old game's GAME_ENDS reaches the clock display after a New Game
        # has already reset the game ending.
        ModeInfo.set_game_ending(result="*")
        with patch("dgt.display.DispatchDgt.fire", new_callable=AsyncMock), patch(
            "dgt.display.asyncio.sleep", new_callable=AsyncMock
        ):
            await display._process_message(_game_ends(GameResult.WIN_WHITE))
        self.assertEqual("*", ModeInfo.get_game_ending())


class TestDeclaredResultAfterNewGame(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ModeInfo.set_game_ending(result="*")
        self.addCleanup(lambda: ModeInfo.set_game_ending(result="*"))
        self.controller = object.__new__(mainloop.MainLoop)
        self.controller.state = SimpleNamespace(
            position_checkpoint_restore_pending=False, game_declared=False, game_generation=0
        )
        self.controller._declare_game_result = AsyncMock()

    async def test_resign_is_dropped_when_a_new_game_starts_while_the_search_stops(self):
        async def new_game_meanwhile():
            self.controller.state.game_generation += 1

        self.controller.stop_search_and_clock = AsyncMock(side_effect=new_game_meanwhile)

        await self.controller.process_main_events(Event.DRAWRESIGN(result=GameResult.WIN_BLACK))

        self.controller._declare_game_result.assert_not_awaited()
        self.assertFalse(self.controller.state.game_declared)
        self.assertEqual("*", ModeInfo.get_game_ending())

    async def test_resign_ends_the_game_when_no_new_game_starts(self):
        self.controller.stop_search_and_clock = AsyncMock()

        await self.controller.process_main_events(Event.DRAWRESIGN(result=GameResult.WIN_BLACK))

        self.controller._declare_game_result.assert_awaited_once_with(GameResult.WIN_BLACK, 0)


if __name__ == "__main__":
    unittest.main()
