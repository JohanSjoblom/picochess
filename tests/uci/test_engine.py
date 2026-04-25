#!/usr/bin/env python3

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

import chess
from uci.engine import ContinuousAnalysis, EngineLease, PlayingContinuousAnalysis, UciEngine, UciShell
from uci.rating import Rating, Result

UCI_ELO = "UCI_Elo"
UCI_ELO_NON_STANDARD = "UCI Elo"


class MockEngine(object):
    def __init__(self, *args, **kwargs):
        self.options = {UCI_ELO: None}

    async def configure(self, options):
        pass

    async def ping(self):
        pass

    def uci(self):
        pass


@patch("chess.engine.UciProtocol", new=MockEngine)
class TestEngine(unittest.IsolatedAsyncioTestCase):
    def __init__(self, tests=()):
        super().__init__(tests)
        self.loop = asyncio.get_event_loop()

    async def test_engine_uses_elo(self):
        eng = UciEngine("some_test_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "1400"})
        self.assertEqual(1400, eng.engine_rating)

    async def test_engine_uses_elo_non_standard_option(self):
        eng = UciEngine("some_test_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO_NON_STANDARD: "1400"})
        self.assertEqual(1400, eng.engine_rating)

    async def test_engine_uses_rating(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "aUtO"}, Rating(1345.5, 123.0))
        self.assertEqual(1350, eng.engine_rating)  # rounded to next 50

    async def test_engine_uses_rating_non_standard_option(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO_NON_STANDARD: "aUtO"}, Rating(1345.5, 123.0))
        self.assertEqual(1350, eng.engine_rating)  # rounded to next 50

    async def test_engine_adaptive_when_using_auto(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "auto"}, Rating(1345.5, 123.0))
        self.assertTrue(eng.is_adaptive)
        self.assertEqual(1350, eng.engine_rating)  # rounded to next 50

    async def test_engine_adaptive_when_using_auto_non_standard_option(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO_NON_STANDARD: "auto"}, Rating(1345.5, 123.0))
        self.assertTrue(eng.is_adaptive)
        self.assertEqual(1350, eng.engine_rating)  # rounded to next 50

    async def test_engine_not_adaptive_when_using_auto_and_no_rating(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "auto"}, None)
        self.assertFalse(eng.is_adaptive)
        self.assertEqual(-1, eng.engine_rating)

    async def test_engine_not_adaptive_when_not_using_auto(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "1234"}, Rating(1345.5, 123.0))
        self.assertFalse(eng.is_adaptive)
        self.assertEqual(1234, eng.engine_rating)

    async def test_engine_has_rating_as_information_when_not_adaptive(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "1234"}, None)
        self.assertFalse(eng.is_adaptive)
        self.assertEqual(1234, eng.engine_rating)

    async def test_engine_has_rating_as_information_when_not_adaptive_non_standard_option(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO_NON_STANDARD: "1234"}, None)
        self.assertFalse(eng.is_adaptive)
        self.assertEqual(1234, eng.engine_rating)

    async def test_invalid_value_for_uci_elo(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "XXX"}, Rating(450.5, 123.0))
        self.assertEqual(-1, eng.engine_rating)

    async def test_engine_does_not_eval_for_no_rating(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "max(auto, 800)"}, None)
        self.assertEqual(-1, eng.engine_rating)

    async def test_analysis_false_uses_legacy_play_without_engine_analyser(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.playing = Mock()

        await eng.startup({"Analysis": "false"})

        self.assertTrue(eng.is_legacy_engine())
        self.assertTrue(eng.should_skip_engine_analyser())
        self.assertNotIn("Analysis", eng.options)
        eng.playing.set_allow_info_loop.assert_called_once_with(False)

    async def test_engine_uses_eval_for_rating(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "max(auto, 800)"}, Rating(450.5, 123.0))
        self.assertEqual(800, eng.engine_rating)

    async def test_engine_uses_eval_for_rating_non_standard_option(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO_NON_STANDARD: "max(auto, 800)"}, Rating(450.5, 123.0))
        self.assertEqual(800, eng.engine_rating)

    async def test_simple_eval(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "auto + 100"}, Rating(850.5, 123.0))
        self.assertEqual(950, eng.engine_rating)

    async def test_fancy_eval_rejects_code_injection(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        with self.assertLogs("uci.engine", level="ERROR"):
            await eng.startup(
                {UCI_ELO: 'exec("import random; random.seed();") or max(800, (auto + random.randint(10,80)))'},
                Rating(850.5, 123.0),
            )
        self.assertEqual(-1, eng.engine_rating)  # rejected, not evaluated

    async def test_eval_syntax_error(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        with self.assertLogs("uci.engine", level="ERROR"):
            await eng.startup({UCI_ELO: "max(auto,"}, Rating(450.5, 123.0))
        self.assertEqual(-1, eng.engine_rating)

    async def test_eval_error(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        with self.assertLogs("uci.engine", level="ERROR"):
            await eng.startup({UCI_ELO: 'max(auto, "abc")'}, Rating(450.5, 123.0))
        self.assertEqual(-1, eng.engine_rating)

    @patch("uci.engine.write_picochess_ini")
    async def test_update_rating(self, _):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "auto"}, Rating(849.5, 123.0))
        self.assertEqual(850, eng.engine_rating)
        await eng.update_rating(Rating(850.5, 123.0), Result.WIN)
        self.assertEqual(900, eng.engine_rating)

    @patch("uci.engine.write_picochess_ini")
    async def test_update_rating_with_eval(self, _):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "auto + 11"}, Rating(850.5, 123.0))
        self.assertEqual(861, eng.engine_rating)
        new_rating = await eng.update_rating(Rating(850.5, 123.0), Result.WIN)
        self.assertEqual(890, int(new_rating.rating))
        self.assertEqual(901, eng.engine_rating)

    async def test_continuous_analysis_recovers_after_protocol_failure(self):
        recover = AsyncMock(return_value=True)
        analyser = ContinuousAnalysis(
            engine=MockEngine(),
            delay=0,
            loop=asyncio.get_running_loop(),
            engine_debug_name="engine",
            engine_lease=EngineLease(),
            recover_engine_cb=recover,
        )
        analyser.game = chess.Board()
        analyser._analysis_data = [{"depth": 8}]
        analyser._running = True

        calls = 0

        async def fake_analyse_forever(limit, multipv):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise AssertionError("CommandState.NEW")
            analyser._running = False

        analyser._analyse_forever = fake_analyse_forever

        await analyser._watching_analyse()

        self.assertEqual(2, calls)
        recover.assert_awaited_once()
        self.assertFalse(analyser.needs_recovery())
        self.assertIsNone(analyser._analysis_data)

    async def test_continuous_analysis_marks_forced_stop_after_timeout(self):
        analyser = ContinuousAnalysis(
            engine=MockEngine(),
            delay=0,
            loop=asyncio.get_running_loop(),
            engine_debug_name="engine",
            engine_lease=EngineLease(),
        )

        async def hung_task():
            await asyncio.sleep(60)

        analyser._task = asyncio.create_task(hung_task())
        analyser._running = True

        stopped = await analyser.stop_async(timeout=0.01, cancel_timeout=0.1)

        self.assertTrue(stopped)
        self.assertTrue(analyser.consume_forced_stop())
        self.assertFalse(analyser.consume_forced_stop())

    async def test_continuous_analysis_stop_async_requests_active_stop(self):
        analyser = ContinuousAnalysis(
            engine=MockEngine(),
            delay=0,
            loop=asyncio.get_running_loop(),
            engine_debug_name="engine",
            engine_lease=EngineLease(),
        )

        async def task_body():
            while analyser._running:
                await asyncio.sleep(0)

        analyser._active_analysis = object()
        analyser._send_guarded_stop = AsyncMock()
        analyser._running = True
        analyser._task = asyncio.create_task(task_body())

        stopped = await analyser.stop_async(timeout=0.1, cancel_timeout=0.1)

        self.assertTrue(stopped)
        analyser._send_guarded_stop.assert_awaited_once_with(analyser._active_analysis, guard_window=0.20)

    async def test_playing_force_uses_active_analysis_stop(self):
        playing = PlayingContinuousAnalysis(
            engine=MockEngine(),
            loop=asyncio.get_running_loop(),
            engine_lease=EngineLease(),
            engine_debug_name="engine",
            allow_info_loop=True,
        )
        playing.engine.send_line = Mock()
        playing._waiting = True
        playing._search_started.set()
        playing._search_generation = 1
        playing._analysis_started_ts = playing.loop.time() - 1.0
        playing._active_analysis = Mock()

        playing.force()

        playing._active_analysis.stop.assert_called_once_with()
        playing.engine.send_line.assert_not_called()

    async def test_playing_force_falls_back_to_send_line_without_active_analysis(self):
        playing = PlayingContinuousAnalysis(
            engine=MockEngine(),
            loop=asyncio.get_running_loop(),
            engine_lease=EngineLease(),
            engine_debug_name="engine",
            allow_info_loop=False,
        )
        playing.engine.send_line = Mock()
        playing._waiting = True
        playing._search_started.set()
        playing._search_generation = 1
        playing._analysis_started_ts = playing.loop.time() - 1.0

        playing.force()

        playing.engine.send_line.assert_called_once_with("stop")

    async def test_playing_delayed_stop_is_bound_to_search_generation(self):
        playing = PlayingContinuousAnalysis(
            engine=MockEngine(),
            loop=asyncio.get_running_loop(),
            engine_lease=EngineLease(),
            engine_debug_name="engine",
            allow_info_loop=False,
        )
        playing.engine.send_line = Mock()
        playing._waiting = True
        playing._search_started.set()
        playing._search_generation = 1
        playing._analysis_started_ts = playing.loop.time()

        playing._request_stop_or_delay(guard_window=0.01)
        playing._search_generation = 2

        await asyncio.sleep(0.02)

        playing.engine.send_line.assert_not_called()

    async def test_newgame_recovers_failed_analyser_state(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.analyser = ContinuousAnalysis(
            engine=eng.engine,
            delay=0,
            loop=asyncio.get_running_loop(),
            engine_debug_name="engine",
            engine_lease=EngineLease(),
        )
        eng.playing = Mock()
        eng.analyser._failure_reason = "continuous analysis protocol failure: AssertionError: CommandState.NEW"
        eng._recover_from_failed_analyser_stop = AsyncMock(return_value=True)

        await eng.newgame(chess.Board())

        eng._recover_from_failed_analyser_stop.assert_awaited_once_with(
            "new game requested after analyser protocol failure"
        )
        self.assertFalse(eng.analyser.needs_recovery())
        self.assertEqual(2, eng.game_id)

    async def test_start_analysis_skips_while_engine_is_shutting_down(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng._shutting_down = True
        eng.analyser = Mock()
        eng.analyser.is_running.return_value = False
        eng.playing = Mock()
        eng.playing.is_waiting_for_move.return_value = False

        started = await eng.start_analysis(chess.Board())

        self.assertFalse(started)
        eng.analyser.start.assert_not_called()

    async def test_start_analysis_waits_until_mode_is_set(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.analyser = Mock()
        eng.analyser.is_running.return_value = False
        eng.playing = Mock()
        eng.playing.is_waiting_for_move.return_value = False

        started_before_mode = await eng.start_analysis(chess.Board())

        self.assertFalse(started_before_mode)
        eng.analyser.start.assert_not_called()

        eng.set_mode()

        started_after_mode = await eng.start_analysis(chess.Board())

        self.assertFalse(started_after_mode)
        eng.analyser.start.assert_called_once()

    async def test_get_analysis_returns_empty_while_engine_setup_incomplete(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.analyser = Mock()
        eng.analyser.is_running.return_value = True

        result = await eng.get_analysis(chess.Board())

        self.assertEqual({"info": [], "fen": ""}, result)
        eng.analyser.get_analysis.assert_not_called()

    @patch("uci.engine.asyncio.sleep", new_callable=AsyncMock)
    async def test_quit_awaits_stop_analysis_before_shutdown(self, _):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.analyser = Mock()
        eng.playing = Mock()
        eng.playing.is_waiting_for_move.return_value = False
        order = []

        async def fake_stop_analysis():
            order.append("stop_analysis")

        async def fake_shutdown():
            order.append("shutdown")

        eng.stop_analysis = AsyncMock(side_effect=fake_stop_analysis)
        eng._shutdown_standard_engine = AsyncMock(side_effect=fake_shutdown)
        eng._close_remote_connection = AsyncMock()

        await eng.quit()

        self.assertEqual(["stop_analysis", "shutdown"], order)
        self.assertTrue(eng._shutting_down)
        eng.stop_analysis.assert_awaited_once()
        eng._shutdown_standard_engine.assert_awaited_once()

    async def test_recovery_is_skipped_while_engine_is_shutting_down(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng._shutting_down = True
        eng.analyser = Mock()
        eng._shutdown_standard_engine = AsyncMock()
        eng._start_engine_process = AsyncMock()

        recovered = await eng._recover_from_failed_analyser_stop("engine switch in progress")

        self.assertTrue(recovered)
        eng.analyser.clear_failure.assert_called_once()
        eng._shutdown_standard_engine.assert_not_awaited()
        eng._start_engine_process.assert_not_awaited()
