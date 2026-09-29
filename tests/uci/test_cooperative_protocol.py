import asyncio
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import chess
import chess.engine

from uci.engine import (
    CooperativeTolerantUciProtocol,
    CooperativeUciProtocol,
    TolerantUciProtocol,
    UciEngine,
    UciShell,
)


class RecordingProtocol(CooperativeUciProtocol):
    def __init__(self):
        super().__init__()
        self.config["MultiPV"] = 30
        self.lines = []

    def _line_received(self, line):
        self.lines.append((1, line))

    def error_line_received(self, line):
        self.lines.append((2, line))


class TestCooperativeProtocol(unittest.IsolatedAsyncioTestCase):
    async def test_single_pv_and_startup_use_original_parser_immediately(self):
        for width in (None, 1):
            protocol = RecordingProtocol()
            protocol.config.clear()
            if width is not None:
                protocol.config["MultiPV"] = width
            protocol.pipe_data_received(1, b"info string update\n" * 120)
            self.assertEqual(len(protocol.lines), 120)
            self.assertIsNone(protocol._output_task)
            self.assertEqual(protocol._output_bytes, 0)

    async def test_switch_to_single_pv_drains_queued_lines_before_direct_input(self):
        protocol = RecordingProtocol()
        protocol.pipe_data_received(1, b"info string old\n" * 20 + b"partial")
        task = protocol._output_task
        protocol.config["MultiPV"] = 1
        protocol.pipe_data_received(1, b" tail\nbestmove e2e4\n")
        self.assertEqual(protocol.lines, [])
        await asyncio.wait_for(task, 1)
        self.assertEqual(protocol.lines, [(1, "info string old")] * 20 + [
            (1, "partial tail"), (1, "bestmove e2e4"),
        ])
        protocol.pipe_data_received(1, b"info string new search\n")
        self.assertEqual(protocol.lines[-1], (1, "info string new search"))
        self.assertIsNone(protocol._output_task)

    async def test_switch_to_multipv_preserves_direct_parser_partial_line(self):
        protocol = RecordingProtocol()
        protocol.config["MultiPV"] = 1
        protocol.pipe_data_received(1, b"info string partial")
        self.assertIsNone(protocol._output_task)
        protocol.config["MultiPV"] = 2
        protocol.pipe_data_received(1, b" tail\ninfo string next\n")
        self.assertEqual(protocol.lines, [])
        await asyncio.wait_for(protocol._output_task, 1)
        self.assertEqual(protocol.lines, [(1, "info string partial tail"), (1, "info string next")])

    async def test_stopped_deep_tutor_skips_queued_info_but_delivers_bestmove(self):
        protocol, transport = await self.initialized_protocol()
        protocol.discard_stopped_info = True
        board = chess.Board()
        self.expect_analysis(transport, board, 30, first=True)
        analysis = await asyncio.wait_for(protocol.analysis(board, multipv=30), 1)
        protocol.pipe_data_received(1, b"info depth 10 multipv 1 score cp 20 pv e2e4\n")
        await asyncio.wait_for(protocol._output_task, 1)
        self.assertEqual(analysis.info["depth"], 10)

        transport.expect("stop")
        analysis.stop()
        protocol.pipe_data_received(1, b"info depth 11 multipv 1 score cp 30 pv e2e4\n" * 100)
        protocol.pipe_data_received(1, b"in")
        protocol.pipe_data_received(1, b"fo depth 12 multipv 2 score cp 10 pv d2d4\n")
        protocol.pipe_data_received(1, b"best")
        protocol.pipe_data_received(1, b"move e2e4\n")
        self.assertEqual((await asyncio.wait_for(analysis.wait(), 1)).move, chess.Move.from_uci("e2e4"))
        self.assertEqual(analysis.info["depth"], 10)
        self.assertFalse(protocol._stopped_tutor_search)
        self.assertEqual(protocol._output_bytes, 0)

        board.push_uci("e2e4")
        transport.expect("position startpos moves e2e4")
        transport.expect("go infinite")
        next_analysis = await asyncio.wait_for(protocol.analysis(board, multipv=30), 1)
        protocol.pipe_data_received(1, b"info depth 13 multipv 1 score cp 15 pv e7e5\n")
        await asyncio.wait_for(protocol._output_task, 1)
        self.assertEqual(next_analysis.info["depth"], 13)
        transport.expect("stop", ["bestmove e7e5"])
        next_analysis.stop()
        self.assertEqual((await asyncio.wait_for(next_analysis.wait(), 1)).move, chess.Move.from_uci("e7e5"))
        transport.assert_done()

    async def test_other_multipv_search_keeps_info_after_stop(self):
        protocol, transport = await self.initialized_protocol()
        board = chess.Board()
        self.expect_analysis(transport, board, 30, first=True)
        analysis = await asyncio.wait_for(protocol.analysis(board, multipv=30), 1)
        transport.expect("stop")
        analysis.stop()
        protocol.pipe_data_received(1, b"info depth 12 multipv 1 score cp 20 pv e2e4\nbestmove e2e4\n")
        await asyncio.wait_for(analysis.wait(), 1)
        self.assertEqual(analysis.info["depth"], 12)
        transport.assert_done()

    async def initialized_protocol(self, protocol_cls=CooperativeUciProtocol):
        protocol = protocol_cls()
        transport = chess.engine.MockTransport(protocol)
        transport.expect("uci", [
            "info string starting up",
            "id name Test engine",
            "option name MultiPV type spin default 1 min 1 max 100",
            "uciok",
        ])
        await asyncio.wait_for(protocol.initialize(), 1)
        return protocol, transport

    def expect_analysis(self, transport, board, multipv, first=False):
        transport.expect(f"setoption name MultiPV value {multipv}")
        if first:
            transport.expect("ucinewgame")
            transport.expect("isready", ["readyok"])
        moves = " ".join(move.uci() for move in board.move_stack)
        transport.expect("position startpos" + (f" moves {moves}" if moves else ""))
        transport.expect("go infinite")

    async def test_output_burst_allows_other_loop_work_without_losing_lines(self):
        protocol = RecordingProtocol()
        expected = [(1, f"info string line {n}") for n in range(120)]
        protocol.pipe_data_received(1, "\n".join(line for _, line in expected).encode() + b"\n")
        observed = []
        asyncio.get_running_loop().call_soon(lambda: observed.append(len(protocol.lines)))
        await asyncio.wait_for(protocol._output_task, 1)
        self.assertGreater(observed[0], 0)
        self.assertLess(observed[0], len(expected))
        self.assertEqual(protocol.lines, expected)
        self.assertEqual(protocol._output_bytes, 0)

    async def test_fragmented_lines_utf8_and_stderr_are_preserved(self):
        protocol = RecordingProtocol()
        protocol.pipe_data_received(1, b"info string caf\xc3")
        protocol.pipe_data_received(2, b"diagnostic\r")
        protocol.pipe_data_received(1, b"\xa9\r\ninfo string next\npartial")
        protocol.pipe_data_received(2, b"\n")
        await asyncio.wait_for(protocol._output_task, 1)
        self.assertEqual(protocol.lines, [(1, "info string caf\u00e9"), (1, "info string next"), (2, "diagnostic")])
        protocol.pipe_data_received(1, b" tail\n")
        await asyncio.wait_for(protocol._output_task, 1)
        self.assertEqual(protocol.lines[-1], (1, "partial tail"))
        self.assertEqual(protocol._output_bytes, 0)

    async def test_time_budget_yields_before_line_limit(self):
        protocol = RecordingProtocol()
        protocol.OUTPUT_BATCH_LINES = 1000
        actual_loop = protocol.loop
        protocol.loop = Mock(wraps=actual_loop)
        clock = 0.0
        protocol.loop.time.side_effect = lambda: clock
        receive = protocol._line_received

        def expensive_line(line):
            nonlocal clock
            clock += 0.003
            receive(line)

        protocol._line_received = expensive_line
        protocol.pipe_data_received(1, b"info string update\n" * 20)
        observed = []
        actual_loop.call_soon(lambda: observed.append(len(protocol.lines)))
        await asyncio.wait_for(protocol._output_task, 1)
        self.assertEqual(observed, [2])
        self.assertEqual(len(protocol.lines), 20)

    async def test_multipv_and_bestmove_are_delivered_before_connection_lost(self):
        protocol, transport = await self.initialized_protocol()
        board = chess.Board()
        for san in ("e4", "e5", "Nf3", "Nc6", "Bc4", "Nf6"):
            board.push_san(san)
        roots = list(board.legal_moves)[:30]
        self.assertEqual(len(roots), 30)
        self.expect_analysis(transport, board, 30, first=True)
        analysis = await asyncio.wait_for(protocol.analysis(board, multipv=30), 1)
        payload = []
        for depth in (10, 20):
            for index, move in enumerate(roots, 1):
                payload.append(f"info depth {depth} multipv {index} score cp {100-index} pv {move.uci()}")
        payload.append(f"bestmove {roots[0].uci()}")
        protocol.pipe_data_received(1, ("\n".join(payload) + "\n").encode())
        protocol.connection_lost(None)
        best = await asyncio.wait_for(analysis.wait(), 1)
        await asyncio.wait_for(protocol.returncode, 1)
        self.assertEqual(best.move, roots[0])
        infos = [info async for info in analysis]
        self.assertEqual(len(infos), 60)
        self.assertEqual([info["depth"] for info in infos], [10] * 30 + [20] * 30)
        self.assertEqual(len(analysis.multipv), 30)
        for index, info in enumerate(analysis.multipv):
            self.assertEqual(info["depth"], 20)
            self.assertEqual(info["pv"], [roots[index]])
            self.assertEqual(info["score"].pov(board.turn).score(), 99-index)
        transport.assert_done()

    async def test_stop_and_new_position_keep_search_results_separate(self):
        protocol, transport = await self.initialized_protocol()
        board = chess.Board()
        self.expect_analysis(transport, board, 2, first=True)
        first = await asyncio.wait_for(protocol.analysis(board, multipv=2), 1)
        protocol.pipe_data_received(1, b"info depth 12 multipv 1 score cp 20 pv e2e4\n")
        transport.expect("stop", [
            "info depth 13 multipv 2 score cp 10 pv d2d4",
            "bestmove e2e4",
        ])
        # Starting a new search asks python-chess to stop the current search.
        board.push_uci("e2e4")
        self.expect_analysis(transport, board, 1)
        second = await asyncio.wait_for(protocol.analysis(board, multipv=1), 1)
        self.assertEqual((await first.wait()).move, chess.Move.from_uci("e2e4"))
        protocol.pipe_data_received(1, b"info depth 9 score cp -30 pv e7e5\n")
        self.assertIsNone(protocol._output_task)
        self.assertEqual(second.info["depth"], 9)
        transport.expect("stop", ["bestmove e7e5"])
        second.stop()
        self.assertEqual((await asyncio.wait_for(second.wait(), 1)).move, chess.Move.from_uci("e7e5"))
        self.assertEqual(len(first.multipv), 2)
        self.assertEqual(first.multipv[1]["pv"], [chess.Move.from_uci("d2d4")])
        self.assertEqual(second.info["pv"], [chess.Move.from_uci("e7e5")])
        transport.assert_done()

    async def test_engine_exit_without_bestmove_retains_info_and_reports_failure(self):
        protocol, transport = await self.initialized_protocol()
        self.expect_analysis(transport, chess.Board(), 2, first=True)
        analysis = await asyncio.wait_for(protocol.analysis(chess.Board(), multipv=2), 1)
        protocol.pipe_data_received(1, b"info depth 12 score cp 20 pv e2e4\n")
        protocol.connection_lost(None)
        with self.assertRaises(chess.engine.EngineTerminatedError):
            await asyncio.wait_for(analysis.wait(), 1)
        self.assertEqual(analysis.info["depth"], 12)
        self.assertEqual(analysis.info["pv"], [chess.Move.from_uci("e2e4")])
        self.assertEqual(await protocol.returncode, 0)

    async def test_remote_tolerant_protocol_still_filters_init_chatter(self):
        protocol, transport = await self.initialized_protocol(CooperativeTolerantUciProtocol)
        self.assertTrue(protocol.initialized)
        self.assertTrue(protocol._ready_seen)
        transport.assert_done()

    async def test_bad_line_does_not_discard_following_lines(self):
        protocol = RecordingProtocol()
        original = protocol._line_received

        def receive(line):
            if line == "bad":
                raise ValueError("bad engine line")
            original(line)

        protocol._line_received = receive
        handler = Mock()
        protocol.loop.set_exception_handler(handler)
        try:
            protocol.pipe_data_received(1, b"bad\ninfo string valid\n")
            await asyncio.wait_for(protocol._output_task, 1)
            self.assertEqual(protocol.lines, [(1, "info string valid")])
            self.assertIsInstance(handler.call_args.args[1]["exception"], ValueError)
        finally:
            protocol.loop.set_exception_handler(None)

    async def test_local_engine_subprocess_initialization_search_and_quit(self):
        script = """import sys
for command in sys.stdin:
    command = command.strip()
    if command == 'uci':
        print('id name Test engine')
        print('option name MultiPV type spin default 1 min 1 max 100')
        print('uciok', flush=True)
    elif command == 'isready':
        print('readyok', flush=True)
    elif command.startswith('go '):
        for depth in range(1, 21):
            for pv in range(1, 31):
                print(f'info depth {depth} multipv {pv} score cp 20 pv e2e4 e7e5')
        print('bestmove e2e4', flush=True)
    elif command == 'quit':
        break
"""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test_engine"
            path.write_text(f"#!{sys.executable}\n" + script)
            path.chmod(0o755)
            engine = UciEngine(str(path), UciShell(), "", asyncio.get_running_loop())
            await asyncio.wait_for(engine._open_local_engine(), 3)
            try:
                self.assertIsInstance(engine.engine, CooperativeUciProtocol)
                analysis = await asyncio.wait_for(engine.engine.analysis(chess.Board(), multipv=30), 3)
                best = await asyncio.wait_for(analysis.wait(), 3)
                self.assertEqual(best.move, chess.Move.from_uci("e2e4"))
                self.assertEqual(len(analysis.multipv), 30)
                self.assertTrue(all(info["depth"] == 20 for info in analysis.multipv))
                await asyncio.wait_for(engine.engine.quit(), 3)
            finally:
                engine.transport.close()
                await asyncio.wait_for(engine.engine.returncode, 3)

    async def test_initialization_failure_closes_local_transport(self):
        engine = UciEngine("test_engine", UciShell(), "", asyncio.get_running_loop())
        transport = Mock()
        protocol = Mock()
        protocol.initialize = AsyncMock(side_effect=chess.engine.EngineError("bad init"))
        with patch.object(CooperativeUciProtocol, "popen", new=AsyncMock(return_value=(transport, protocol))):
            with self.assertRaises(chess.engine.EngineError):
                await engine._open_local_engine()
        transport.close.assert_called_once_with()

    async def test_mame_local_start_keeps_existing_protocol(self):
        engine = UciEngine("/engines/mame/test_engine", UciShell(), "parameters", asyncio.get_running_loop())
        with patch("chess.engine.popen_uci", new_callable=AsyncMock, return_value=(Mock(), Mock())) as popen:
            with patch.object(CooperativeUciProtocol, "popen", new_callable=AsyncMock) as cooperative:
                await engine._open_local_engine()
        popen.assert_awaited_once_with([engine.file, engine.mame_par])
        cooperative.assert_not_awaited()

    async def test_remote_protocol_selection_keeps_tolerance_and_mame_behavior(self):
        for mame, suppress_info, expected in (
            (False, False, CooperativeUciProtocol),
            (False, True, CooperativeTolerantUciProtocol),
            (True, False, chess.engine.UciProtocol),
            (True, True, TolerantUciProtocol),
        ):
            with self.subTest(mame=mame, suppress_info=suppress_info):
                engine = UciEngine("test_engine", UciShell(), "", asyncio.get_running_loop())
                engine.is_mame = mame
                engine.suppress_info = suppress_info
                engine.remote_host = "test-host"
                channel = Mock()
                channel.wait_closed = AsyncMock()
                protocol = Mock()
                protocol.initialize = AsyncMock()
                connection = Mock()
                connection.create_subprocess = AsyncMock(return_value=(channel, protocol))
                with patch("uci.engine.asyncssh.connect", new=AsyncMock(return_value=connection)):
                    await engine._open_remote_engine()
                self.assertIs(connection.create_subprocess.call_args.args[0], expected)
                protocol.initialize.assert_awaited_once_with()
                await asyncio.sleep(0)
