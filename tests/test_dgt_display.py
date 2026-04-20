import asyncio
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import chess

from dgt.api import Event
from dgt.display import DgtDisplay
from dgt.menu import DgtMenu
from dgt.translate import DgtTranslate
from dgt.util import EBoard, Mode, PicoCoach, PicoComment, PlayMode, TimeMode
from pgn import ModeInfo
from timecontrol import TimeControl
from uci.engine_provider import EngineProvider
from uci.read import read_engine_ini


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
PGNREPLAY_MODE_FEN = "rnbqkbnr/pppppppp/8/3Q4/8/8/PPPPPPPP/RNBQKBNR"


class DummyTranslate:
    language = "en"
    capital = False
    notation = False

    def text(self, *_args, **_kwargs):
        return SimpleNamespace(
            large_text="",
            medium_text="",
            small_text="",
            web_text="",
            wait=False,
            beep=None,
            maxtime=0,
        )

    def bl(self, *_args, **_kwargs):
        return None


class DummyMenu:
    def __init__(self):
        self.tc_fixed_map = {}
        self.tc_blitz_map = {}
        self.tc_fisch_map = {}
        self.all_books = []
        self.installed_engines = []
        self.remote_engine = False
        self._dgt_fen = ""
        self._flip_board = False
        self._engine_has_960 = False
        self._engine_rdisplay = False
        self._mode = Mode.PONDER

    def set_position_reverse_flipboard(self, flip_board, _play_mode):
        self._flip_board = flip_board

    def get_flip_board(self):
        return self._flip_board

    def get_dgt_fen(self):
        return self._dgt_fen

    def set_dgt_fen(self, fen):
        self._dgt_fen = fen

    def get_engine_has_960(self):
        return self._engine_has_960

    def get_engine_rdisplay(self):
        return self._engine_rdisplay

    def get_mode(self):
        return self._mode


class TestDgtDisplayStartPositionRouting(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        ModeInfo.set_game_ending(result="*")
        self.addCleanup(lambda: ModeInfo.set_game_ending(result="*"))
        self.menu = DummyMenu()
        self.display = DgtDisplay(
            dgttranslate=DummyTranslate(),
            dgtmenu=self.menu,
            time_control=TimeControl(mode=TimeMode.FIXED, fixed=0),
            loop=loop,
        )
        self.display.play_mode = PlayMode.USER_WHITE

    @patch("dgt.display.Observable.fire", new_callable=AsyncMock)
    async def test_standard_start_position_with_move_history_triggers_new_game(self, observable_fire):
        self.display.last_pos_start = False
        self.display._current_game_has_moves = True
        self.display._current_game_start_pos960 = 518

        await self.display._process_fen(chess.STARTING_BOARD_FEN, raw=False)

        event = observable_fire.await_args.args[0]
        self.assertIsInstance(event, Event.NEW_GAME)
        self.assertEqual(518, event.pos960)

    @patch("dgt.display.Observable.fire", new_callable=AsyncMock)
    async def test_ended_game_start_position_triggers_new_game(self, observable_fire):
        ModeInfo.set_game_ending(result="0-1")
        self.display.last_pos_start = False
        self.display._current_game_has_moves = True
        self.display._current_game_start_pos960 = 518

        await self.display._process_fen(chess.STARTING_BOARD_FEN, raw=False)

        event = observable_fire.await_args.args[0]
        self.assertIsInstance(event, Event.NEW_GAME)
        self.assertEqual(518, event.pos960)

    @patch("dgt.display.Observable.fire", new_callable=AsyncMock)
    async def test_different_chess960_start_still_triggers_new_game(self, observable_fire):
        self.menu._engine_has_960 = True
        self.display.last_pos_start = False
        self.display._current_game_has_moves = True
        self.display._current_game_start_pos960 = 518
        chess960_fen = chess.Board.from_chess960_pos(0).board_fen()

        await self.display._process_fen(chess960_fen, raw=False)

        event = observable_fire.await_args.args[0]
        self.assertIsInstance(event, Event.NEW_GAME)
        self.assertEqual(0, event.pos960)

    @patch("dgt.display.Observable.fire", new_callable=AsyncMock)
    async def test_start_position_without_move_history_still_triggers_new_game(self, observable_fire):
        self.display.last_pos_start = False
        self.display._current_game_has_moves = False
        self.display._current_game_start_pos960 = 518

        await self.display._process_fen(chess.STARTING_BOARD_FEN, raw=False)

        event = observable_fire.await_args.args[0]
        self.assertIsInstance(event, Event.NEW_GAME)
        self.assertEqual(518, event.pos960)


class TestDgtDisplay(unittest.IsolatedAsyncioTestCase):
    def create_display(self) -> DgtDisplay:
        with patch("platform.machine", return_value=".." + os.sep + "tests"), patch("subprocess.run"):
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

        return DgtDisplay(trans, menu, TimeControl(), asyncio.get_running_loop())

    @patch("dgt.display.DispatchDgt.fire", new_callable=AsyncMock)
    @patch("dgt.display.Observable.fire", new_callable=AsyncMock)
    async def test_mode_command_restore_to_start_uses_fen_not_new_game(self, observable_fire, _dispatch_fire):
        display = self.create_display()

        await display._process_fen(PGNREPLAY_MODE_FEN, raw=False)
        await display._process_fen(START_FEN, raw=False)

        self.assertEqual(2, observable_fire.await_count)

        mode_event = observable_fire.await_args_list[0].args[0]
        self.assertEqual("EVT_SET_INTERACTION_MODE", mode_event._type)
        self.assertEqual(Mode.PGNREPLAY, mode_event.mode)

        restore_event = observable_fire.await_args_list[1].args[0]
        self.assertEqual("EVT_FEN", restore_event._type)
        self.assertEqual(START_FEN, restore_event.fen)

    @patch("dgt.display.DispatchDgt.fire", new_callable=AsyncMock)
    @patch("dgt.display.Observable.fire", new_callable=AsyncMock)
    async def test_start_position_still_triggers_new_game_without_mode_command(self, observable_fire, _dispatch_fire):
        display = self.create_display()

        await display._process_fen(START_FEN, raw=False)

        self.assertEqual(1, observable_fire.await_count)
        new_game_event = observable_fire.await_args_list[0].args[0]
        self.assertEqual("EVT_NEW_GAME", new_game_event._type)
        self.assertEqual(518, new_game_event.pos960)
