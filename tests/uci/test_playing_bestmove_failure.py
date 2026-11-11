"""An engine that ends a search with an unusable bestmove must not hang the game.

The MAME chessengine plugin sends "bestmove ----" after a position it can't set up, and a
plugin bug once made it send an illegal move. The search then ends with the EngineError,
so the caller can tell it apart from "bestmove 0000" (a resignation, or the PGN replay
engine's wrong guess) (#581). These tests run the real UCI protocol against a small
scripted engine.
"""

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

import chess
import chess.engine
from chess.engine import Limit

from uci.engine import EngineLease, PlayingContinuousAnalysis

SCRIPTED_ENGINE = """
import sys, time

reply, delay = sys.argv[1], float(sys.argv[2])
for line in sys.stdin:
    command = line.strip()
    if command == "uci":
        print("id name scripted\\nuciok", flush=True)
    elif command == "isready":
        print("readyok", flush=True)
    elif command.startswith("go"):
        time.sleep(delay)
        print("info depth 1 score cp 5 pv e2e4", flush=True)
        print("bestmove " + reply, flush=True)
    elif command == "quit":
        break
"""


class TestPlayingBestmoveFailure(unittest.IsolatedAsyncioTestCase):
    async def search(self, reply: str, delay: float, allow_info_loop: bool):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "scripted_engine.py"
            script.write_text(SCRIPTED_ENGINE)
            transport, engine = await chess.engine.popen_uci([sys.executable, str(script), reply, str(delay)])
            lease = EngineLease()
            playing = PlayingContinuousAnalysis(
                engine=engine,
                loop=asyncio.get_running_loop(),
                engine_lease=lease,
                engine_debug_name="engine",
                allow_info_loop=allow_info_loop,
            )
            results: asyncio.Queue = asyncio.Queue()
            # python-chess reports the parse error to the loop's exception handler
            asyncio.get_running_loop().set_exception_handler(lambda _loop, _context: None)
            await playing.play_move(chess.Board(), Limit(time=0.1), False, results)
            try:
                result = await asyncio.wait_for(results.get(), 3)
            finally:
                transport.close()
            return result, lease._owner

    def assert_engine_error(self, outcome):
        result, owner = outcome
        self.assertIsInstance(result, chess.engine.EngineError)
        self.assertNotIsInstance(result, chess.engine.EngineTerminatedError)
        self.assertIsNone(owner)

    async def test_failure_with_info_loop_completes_and_releases_the_lease(self):
        self.assert_engine_error(await self.search("----", 0, True))

    async def test_late_failure_with_info_loop_completes_and_releases_the_lease(self):
        self.assert_engine_error(await self.search("----", 0.3, True))

    async def test_failure_without_info_loop_completes_and_releases_the_lease(self):
        self.assert_engine_error(await self.search("----", 0, False))

    async def test_illegal_move_is_reported_as_engine_error(self):
        for allow_info_loop in (True, False):
            with self.subTest(allow_info_loop=allow_info_loop):
                self.assert_engine_error(await self.search("d7f3", 0, allow_info_loop))

    async def test_null_move_is_a_result_not_an_error(self):
        # "bestmove 0000" keeps its meaning: resignation, or the PGN replay engine's wrong guess
        for allow_info_loop in (True, False):
            with self.subTest(allow_info_loop=allow_info_loop):
                result, owner = await self.search("0000", 0, allow_info_loop)
                self.assertIsInstance(result, chess.engine.PlayResult)
                self.assertEqual(result.move, chess.Move.null())
                self.assertIsNone(owner)

    async def test_valid_move_with_info_loop_is_not_failed(self):
        result, owner = await self.search("e2e4", 0, True)
        self.assertEqual(result.move, chess.Move.from_uci("e2e4"))
        self.assertIsNone(owner)
