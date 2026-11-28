"""Artwork views of a retro engine: menu item and board gesture (both kings lifted and put back)."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import chess

import mainloop
from board_position import without_kings
from dgt.api import Event
from dgt.util import EBoard, Mode, PicoCoach
from picostate import PicochessState
from uci.engine import UciEngine

GAME = "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQK2R"


def remove(board_fen, *squares):
    board = chess.BaseBoard(board_fen)
    for square in squares:
        board.remove_piece_at(square)
    return board.board_fen()


class TestWithoutKings(unittest.TestCase):
    def test_positions(self):
        no_kings, one_missing = without_kings(GAME)
        self.assertEqual(remove(GAME, chess.E1, chess.E8), no_kings)
        self.assertEqual({remove(GAME, chess.E1), remove(GAME, chess.E8)}, one_missing)


class TestKingsLift(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.controller = object.__new__(mainloop.MainLoop)
        self.game_fen = GAME
        self.controller.state = SimpleNamespace(
            kings_lifted_fen="",
            get_board_fen=lambda: self.game_fen,
            artwork_in_use=True,
            dgtmenu=SimpleNamespace(get_engine_rdisplay=Mock(return_value=True)),
        )
        self.controller.emulation_mode = Mock(return_value=True)
        self.white_off = remove(GAME, chess.E1)
        self.black_off = remove(GAME, chess.E8)
        self.both_off = remove(GAME, chess.E1, chess.E8)

    def run_fens(self, *fens):
        return [self.controller.kings_lift_completed(fen) for fen in fens]

    def test_lift_both_and_put_back(self):
        self.assertEqual(
            [False, False, False, True],
            self.run_fens(self.white_off, self.both_off, self.black_off, GAME),
        )
        self.assertEqual([False], self.run_fens(GAME))  # only once

    def test_kings_lifted_and_returned_at_the_same_time(self):
        self.assertEqual([False, True], self.run_fens(self.both_off, GAME))

    def test_one_king_does_not_count(self):
        self.assertEqual([False, False], self.run_fens(self.white_off, GAME))
        self.assertEqual([False, False, False, False], self.run_fens(self.white_off, GAME, self.black_off, GAME))

    def test_other_position_in_between_cancels(self):
        # kings on the centre squares (resign or draw), then everything put back
        centre = chess.BaseBoard(self.both_off)
        centre.set_piece_at(chess.D4, chess.Piece.from_symbol("K"))
        self.assertEqual(
            [False, False, False, False, False],
            self.run_fens(self.white_off, self.both_off, centre.board_fen(), self.white_off, GAME),
        )

    def test_engine_move_in_between_cancels(self):
        self.run_fens(self.both_off)
        self.game_fen = remove(GAME, chess.A2)
        self.assertEqual([False], self.run_fens(self.game_fen))

    def test_only_with_artwork(self):
        self.controller.state.artwork_in_use = False
        self.assertEqual([False, False], self.run_fens(self.both_off, GAME))

    async def test_menu_event_sends_next_view_only_with_artwork(self):
        self.controller.engine = SimpleNamespace(next_mame_view=Mock(return_value=True))
        self.controller.state.position_checkpoint_restore_pending = False
        await self.controller.process_main_events(Event.NEXT_RETRO_VIEW())
        self.controller.engine.next_mame_view.assert_called_once_with()
        self.controller.state.artwork_in_use = False
        await self.controller.process_main_events(Event.NEXT_RETRO_VIEW())
        self.controller.engine.next_mame_view.assert_called_once_with()


class TestProcessFenGesture(unittest.IsolatedAsyncioTestCase):
    def make(self):
        controller = object.__new__(mainloop.MainLoop)
        state = object.__new__(PicochessState)
        state.__dict__.update(
            kings_lifted_fen="", position_mode=False, setpieces_switch_anchor_fen="", setpieces_switch_armed=False,
            coach_triggered=False, set_position_ack_pending=False, set_position_ack_target_fen="",
            position_checkpoint_restore_pending=False,
            variant="chess", game=chess.Board(GAME + " w KQkq - 0 1"), game_started=True, flag_startup=False,
            artwork_in_use=True, last_legal_fens=[], legal_fens=[], legal_fens_after_cmove=[],
            take_back_locked=False, automatic_takeback=False, delay_fen_error=4, done_computer_fen=None,
            fen_error_occured=False, error_fen=None, interaction_mode=Mode.NORMAL, game_declared=False,
            _atomic_board=None, _threecheck_board=None, _racingkings_board=None, _antichess_board=None,
            dgtmenu=SimpleNamespace(
                get_engine_rdisplay=Mock(return_value=True),
                get_picocoach=Mock(return_value=PicoCoach.COACH_LIFT),
                get_flip_board=Mock(return_value=True),
            ),
        )
        state.stop_fen_timer = Mock()
        controller.state = state
        controller.board_type = EBoard.CHESSNUT
        controller.engine = SimpleNamespace(next_mame_view=Mock(return_value=True))
        controller.emulation_mode = Mock(return_value=True)
        controller.online_mode = Mock(return_value=False)
        controller.pgn_mode = Mock(return_value=False)
        controller.picotutor_mode = Mock(return_value=True)
        controller.call_pico_coach = AsyncMock()
        controller.switch_artwork_window = AsyncMock()
        controller.start_fen_timer = Mock()
        return controller

    async def feed(self, controller, *fens):
        with patch.object(mainloop.DisplayMsg, "show", new_callable=AsyncMock):
            for fen in fens:
                await controller.process_fen(fen, controller.state)

    async def test_both_kings_show_the_next_view_without_window_switch_or_coach(self):
        controller = self.make()
        await self.feed(controller, remove(GAME, chess.E1), remove(GAME, chess.E1, chess.E8))
        controller.state.coach_triggered = True  # kings held long enough for Coach
        await self.feed(controller, remove(GAME, chess.E8), GAME)
        controller.engine.next_mame_view.assert_called_once_with()
        controller.switch_artwork_window.assert_not_awaited()
        controller.call_pico_coach.assert_not_awaited()

    async def test_kings_held_until_the_set_pieces_message(self):
        controller = self.make()
        await self.feed(controller, remove(GAME, chess.E1, chess.E8))
        controller.state.position_mode = True
        await self.feed(controller, GAME)
        controller.engine.next_mame_view.assert_called_once_with()
        controller.switch_artwork_window.assert_not_awaited()
        self.assertFalse(controller.state.position_mode)

    async def test_one_piece_still_switches_the_window(self):
        controller = self.make()
        await self.feed(controller, remove(GAME, chess.A2), GAME)
        controller.switch_artwork_window.assert_awaited_once()
        controller.engine.next_mame_view.assert_not_called()

    async def test_one_king_still_calls_coach(self):
        controller = self.make()
        await self.feed(controller, remove(GAME, chess.E1))
        controller.state.coach_triggered = True
        await self.feed(controller, GAME)
        controller.call_pico_coach.assert_awaited_once()
        controller.engine.next_mame_view.assert_not_called()

    def make_hand_coach(self):
        controller = self.make()
        controller.state.dgtmenu.get_picocoach = Mock(return_value=PicoCoach.COACH_HAND)
        controller.state.__dict__.update(
            fen_timer_running=True, hand_coach_task=None, last_hand_coach_move=None,
            coach_triggered_piece_type=None, flag_flexible_ponder=False,
        )
        controller.cancel_brain_hint_timer = Mock()
        controller.call_hand_coach = AsyncMock()
        return controller

    async def expire_fen_timer(self, controller, fen):
        controller.state.error_fen = fen
        with patch.object(mainloop.DisplayMsg, "show", new_callable=AsyncMock), patch.object(
            mainloop.asyncio, "sleep", new_callable=AsyncMock
        ):
            await controller.expired_fen_timer()
        # let a started Hand Coach task run
        await mainloop.asyncio.sleep(0)

    async def test_hand_coach_skipped_while_both_kings_are_lifted(self):
        controller = self.make_hand_coach()
        await self.feed(controller, remove(GAME, chess.E1), remove(GAME, chess.E1, chess.E8))
        await self.expire_fen_timer(controller, remove(GAME, chess.E1, chess.E8))
        controller.call_hand_coach.assert_not_awaited()
        self.assertFalse(controller.state.coach_triggered)
        await self.feed(controller, remove(GAME, chess.E8))
        await self.expire_fen_timer(controller, remove(GAME, chess.E8))
        controller.call_hand_coach.assert_not_awaited()
        await self.feed(controller, GAME)
        controller.engine.next_mame_view.assert_called_once_with()
        controller.call_hand_coach.assert_not_awaited()
        controller.switch_artwork_window.assert_not_awaited()

    async def test_hand_coach_still_shown_for_one_king(self):
        controller = self.make_hand_coach()
        await self.feed(controller, remove(GAME, chess.E1))
        await self.expire_fen_timer(controller, remove(GAME, chess.E1))
        controller.call_hand_coach.assert_awaited_once_with(chess.KING)
        self.assertTrue(controller.state.coach_triggered)
        await self.feed(controller, GAME)
        controller.engine.next_mame_view.assert_not_called()


class TestNextMameView(unittest.TestCase):
    def make(self, is_mame=True):
        engine = object.__new__(UciEngine)
        engine.is_mame = is_mame
        engine.file = "/opt/picochess/engines/aarch64/mame/stratos"
        engine.engine = SimpleNamespace(send_line=Mock(), returncode=None)
        return engine

    def test_sends_the_plugin_option(self):
        engine = self.make()
        self.assertTrue(engine.next_mame_view())
        engine.engine.send_line.assert_called_once_with("setoption name View value next")

    def test_not_sent_to_other_engines(self):
        engine = self.make(is_mame=False)
        self.assertFalse(engine.next_mame_view())
        engine.engine.send_line.assert_not_called()


if __name__ == "__main__":
    unittest.main()
