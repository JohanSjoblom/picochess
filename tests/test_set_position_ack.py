"""Exercise Set Pos acknowledgement interleavings without starting hardware."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import chess

import picochess
from dgt.util import EBoard, Mode


class TestSetPositionAck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # MainLoop is local to main(); compile its actual methods without running
        # application startup or copying their implementation into the test.
        source = ast.parse(Path(picochess.__file__).read_text(encoding="utf-8"))
        main_loop = next(
            node for node in ast.walk(source)
            if isinstance(node, ast.ClassDef) and node.name == "MainLoop"
        )
        names = {"_clear_set_position_ack", "_begin_set_position_ack",
                 "_finish_set_position_ack", "process_fen"}
        methods = [node for node in main_loop.body if getattr(node, "name", None) in names]
        namespace = dict(vars(picochess))
        self.show = AsyncMock()
        self.sleep = AsyncMock()
        namespace.update(DisplayMsg=SimpleNamespace(show=self.show),
                         asyncio=SimpleNamespace(sleep=self.sleep))
        exec(compile(ast.Module(body=methods, type_ignores=[]), picochess.__file__, "exec"), namespace)
        controller_type = type("AckController", (), {name: namespace[name] for name in names})
        self.controller = controller_type()
        self.board = chess.Board()
        self.board.push_uci("e2e4")
        self.target = self.board.board_fen()
        self.state = SimpleNamespace(
            game=self.board, get_board_fen=self.board.board_fen,
            get_move_check_board=lambda: self.board, get_variant_board=lambda: None,
            set_position_ack_target_fen=self.target, set_position_ack_pending=True,
            set_position_ack_ready=True, stop_fen_timer=Mock(), position_mode=False,
            position_checkpoint_restore_pending=False, variant="chess", game_started=False,
            last_legal_fens=[], legal_fens=picochess.compute_legal_fens(self.board),
            done_computer_fen=None, interaction_mode=Mode.NORMAL,
        )
        self.controller.state = self.state
        self.controller.board_type = EBoard.CERTABO
        self.controller.engine = SimpleNamespace(has_chess960=lambda: False)
        self.controller.reset_setpieces_window_switch = Mock()

    async def test_legal_move_at_ok_is_accepted_and_ack_is_not_repeated(self):
        move = chess.Move.from_uci("e7e5")
        moved = self.board.copy()
        moved.push(move)

        async def accept_move(move, sliding):
            self.board.push(move)
            return True

        self.controller.user_move = AsyncMock(side_effect=accept_move)

        async def on_ok(message):
            self.assertEqual("POSOK", message.eval_str)
            await self.controller.process_fen(moved.board_fen(), self.state)
            await self.controller._finish_set_position_ack(self.target)

        self.show.side_effect = on_ok
        await self.controller._finish_set_position_ack(self.target)

        self.controller.user_move.assert_awaited_once_with(move, sliding=False)
        self.assertEqual(moved.fen(), self.board.fen())
        self.assertEqual(moved.move_stack, self.board.move_stack)
        self.show.assert_awaited_once()
        self.assertFalse(self.state.set_position_ack_pending)
        self.assertEqual("", self.state.set_position_ack_target_fen)

    async def test_old_ack_sleep_does_not_clear_new_setup_for_same_target(self):
        async def during_sleep(delay):
            self.controller._begin_set_position_ack(self.target, chess.STARTING_BOARD_FEN)

        self.sleep.side_effect = during_sleep
        await self.controller._finish_set_position_ack(self.target)

        self.assertTrue(self.state.set_position_ack_pending)
        self.assertEqual(self.target, self.state.set_position_ack_target_fen)
        self.assertFalse(self.state.set_position_ack_ready)
