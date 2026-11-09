"""MAME New Game must discard a search without waiting for the move key."""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

import chess
import chess.engine

from uci.engine import EngineLease, PlayingContinuousAnalysis, UciEngine, UciShell


class TestMameSearchReset(unittest.IsolatedAsyncioTestCase):
    async def make_engine(self):
        protocol = chess.engine.UciProtocol()
        transport = chess.engine.MockTransport(protocol)
        transport.expect("uci", ["id name Test MAME", "uciok"])
        await protocol.initialize()
        protocol.first_game = False
        protocol.game = 1
        engine = UciEngine("/engines/mame/test", UciShell(), "", asyncio.get_running_loop())
        engine.engine = protocol
        engine.engine_lease = EngineLease()
        engine.playing = PlayingContinuousAnalysis(
            protocol, asyncio.get_running_loop(), engine.engine_lease, "engine"
        )
        return engine, transport

    async def start_search(self, engine, transport):
        board = chess.Board()
        board.push_uci("e2e4")
        transport.expect("position startpos moves e2e4")
        transport.expect("go movetime 30000")
        results = asyncio.Queue()
        await engine.playing.play_move(board, chess.engine.Limit(time=30), False, results)

        async def wait_for_search():
            while engine.playing._active_analysis is None:
                await asyncio.sleep(0)

        await asyncio.wait_for(wait_for_search(), 1)
        return results

    async def test_reset_without_bestmove_allows_next_search(self):
        for pending_ping in (False, True):
            with self.subTest(pending_ping=pending_ping):
                engine, transport = await self.make_engine()
                results = await self.start_search(engine, transport)
                if pending_ping:
                    # Reproduce the cancelled NEW next_command that makes the
                    # following communicate() assert in python-chess 1.11.2.
                    transport.expect("stop")
                    ping = asyncio.create_task(engine.engine.ping())
                    await asyncio.sleep(0)
                    ping.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await ping
                    self.assertIsNotNone(engine.engine.next_command)

                self.assertTrue(await asyncio.wait_for(engine.discard_search_for_mame_reset(), 1))
                self.assertIsNone(await asyncio.wait_for(results.get(), 1))
                self.assertFalse(engine.is_thinking())
                self.assertIsNone(engine.engine_lease._owner)
                self.assertIsNone(engine.engine.command)
                self.assertIsNone(engine.engine.next_command)

                transport.expect("ucinewgame")
                await engine.newgame(chess.Board())
                results = await self.start_search(engine, transport)
                engine.engine.pipe_data_received(1, b"bestmove e7e5\n")
                result = await asyncio.wait_for(results.get(), 1)
                self.assertEqual(result.move, chess.Move.from_uci("e7e5"))
                transport.assert_done()

    async def test_reset_before_search_task_starts_releases_result_consumer(self):
        engine, transport = await self.make_engine()
        results = asyncio.Queue()
        await engine.playing.play_move(chess.Board(), chess.engine.Limit(time=30), False, results)
        self.assertTrue(await asyncio.wait_for(engine.discard_search_for_mame_reset(), 1))
        self.assertIsNone(await asyncio.wait_for(results.get(), 1))
        self.assertFalse(engine.is_thinking())
        transport.assert_done()

    async def test_reset_aborts_if_analyser_stop_is_incomplete(self):
        engine, transport = await self.make_engine()
        engine.stop_analysis = AsyncMock(return_value=False)
        self.assertFalse(await engine.discard_search_for_mame_reset())
        transport.assert_done()

    async def test_force_timeout_defaults_and_explicit_override(self):
        for mame, requested, expected in (
            (True, None, 5.0), (False, None, 2.0), (True, 8.0, 8.0), (True, 0, None),
        ):
            with self.subTest(mame=mame, requested=requested):
                engine, _ = await self.make_engine()
                engine.is_mame = mame
                engine.playing = Mock()
                engine._monitor_force_completion = AsyncMock()
                engine.force_move(timeout=requested)
                await asyncio.sleep(0)
                engine.playing.force.assert_called_once_with()
                if expected is None:
                    engine._monitor_force_completion.assert_not_awaited()
                else:
                    engine._monitor_force_completion.assert_awaited_once_with(
                        expected, engine.playing, engine.playing._task
                    )

    async def test_old_watchdog_does_not_cancel_replacement_search(self):
        engine, _ = await self.make_engine()
        old_task = asyncio.create_task(asyncio.sleep(0))
        playing = Mock()
        engine.playing = playing
        replacement = asyncio.create_task(asyncio.sleep(10))
        playing._task = replacement
        try:
            await engine._monitor_force_completion(0.1, playing, old_task)
            playing.cancel.assert_not_called()
            playing.abort.assert_not_called()
            self.assertFalse(replacement.done())
        finally:
            replacement.cancel()
            await asyncio.gather(replacement, return_exceptions=True)

    async def test_force_timeout_cancels_its_own_search(self):
        engine, _ = await self.make_engine()
        playing = Mock()
        task = asyncio.create_task(asyncio.sleep(10))
        playing._task = task
        engine.playing = playing
        try:
            with patch("uci.engine.asyncio.wait", new=AsyncMock(return_value=(set(), {task}))):
                await engine._monitor_force_completion(5, playing, task)
            playing.cancel.assert_called_once_with()
            playing.abort.assert_called_once_with()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
