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
from pathlib import Path
import tempfile
import unittest
from unittest.mock import ANY, AsyncMock, Mock, patch

import chess
import chess.engine
from chess.engine import EngineTerminatedError, Limit, UciProtocol as RealUciProtocol
from uci.engine import (
    ContinuousAnalysis,
    CooperativeUciProtocol,
    EngineLease,
    PlayingContinuousAnalysis,
    UciEngine,
    UciShell,
)
from uci.rating import Rating, Result

UCI_ELO = "UCI_Elo"
UCI_ELO_NON_STANDARD = "UCI Elo"


class MockEngine(object):
    def __init__(self, *args, **kwargs):
        self.options = {UCI_ELO: None}
        self.returncode = Mock()
        self.returncode.done.return_value = False
        self.first_game = True
        self.game = None
        self.ponderhit = False

    async def configure(self, options):
        pass

    async def ping(self):
        pass

    def uci(self):
        pass

    def _ucinewgame(self):
        self.send_line("ucinewgame")
        self.first_game = False
        self.ponderhit = False


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

    async def test_wait_until_idle_without_playing_search(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)

        self.assertTrue(await eng.wait_until_idle(timeout=0.25))

    async def test_wait_until_idle_delegates_to_playing_search(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.playing = Mock()
        eng.playing.wait_until_idle = AsyncMock(return_value=False)

        self.assertFalse(await eng.wait_until_idle(timeout=0.25))
        eng.playing.wait_until_idle.assert_awaited_once_with(0.25)

    async def test_cancel_playing_search_cancels_and_waits_for_cleanup(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.playing = Mock()
        eng.playing.is_waiting_for_move.return_value = True
        eng.playing.wait_until_idle = AsyncMock(return_value=True)

        self.assertTrue(await eng.cancel_playing_search(timeout=0.25))

        eng.playing.cancel.assert_called_once_with()
        eng.playing.abort.assert_called_once_with()
        eng.playing.wait_until_idle.assert_awaited_once_with(0.25)

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

    async def test_default_name_overrides_uci_engine_name(self):
        with tempfile.TemporaryDirectory() as directory:
            engine_file = str(Path(directory) / "some_engine")
            Path(engine_file + ".uci").write_text(
                "[DEFAULT]\nName = My Friendly Engine\nHash = 64\n\n[Level@1]\nThreads = 1\n",
                encoding="utf-8",
            )
            eng = UciEngine(engine_file, UciShell(), "", self.loop)
            eng.engine = MockEngine()
            eng.engine.id = {"name": "Engine Reported Name"}
            eng.engine.options = {"Hash": None, "Threads": None}
            eng.engine.configure = AsyncMock()
            eng._set_engine_name()

            startup_ok = await eng.startup({})

            self.assertTrue(startup_ok)
            self.assertEqual("My Friendly Engine", eng.get_name())
            self.assertNotIn("Name", eng.get_pgn_options())
            eng.engine.configure.assert_awaited_once_with({"Hash": "64", "Threads": "1"})

    async def test_name_override_survives_engine_process_restart(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.engine.id = {"name": "First Reported Name"}
        eng._set_engine_name()
        self.assertEqual("First Reported Name", eng.get_name())

        await eng.startup({"Name": "Configured Name"})
        eng.engine.id = {"name": "New Reported Name"}
        eng._set_engine_name()

        self.assertEqual("Configured Name", eng.get_name())

    async def test_mame_capabilities_are_parsed_and_engine_name_is_cleaned(self):
        eng = UciEngine("/tmp/mame/mm5", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.engine.id = {"name": "Mephisto MM V (pos+edit)"}

        eng._set_engine_name()

        self.assertEqual("Mephisto MM V", eng.get_name())
        self.assertTrue(eng.get_mame_capabilities().position)
        self.assertTrue(eng.get_mame_capabilities().edit)
        self.assertFalse(eng.get_mame_capabilities().info)
        self.assertTrue(eng.supports_mame_edit())
        self.assertEqual(" pos + edit", eng.get_mame_capabilities().retro_info())
        self.assertEqual(
            {"position": True, "edit": True, "info": False},
            eng.get_mame_capabilities().as_dict(),
        )

    async def test_old_mame_capabilities_default_to_no_edit_support(self):
        eng = UciEngine("/tmp/mame/boris", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.engine.id = {"name": "Boris (pos)"}

        eng._set_engine_name()

        self.assertEqual("Boris", eng.get_name())
        self.assertTrue(eng.get_mame_capabilities().position)
        self.assertFalse(eng.supports_mame_edit())
        self.assertEqual(" position", eng.get_mame_capabilities().retro_info())

    async def test_mame_name_override_does_not_hide_reported_capabilities(self):
        eng = UciEngine("/tmp/mame/mm5", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.engine.id = {"name": "Mephisto MM V (pos+edit+info)"}
        eng.engine_name_override = "Configured MM V"

        eng._set_engine_name()

        self.assertEqual("Configured MM V", eng.get_name())
        self.assertTrue(eng.get_mame_capabilities().position)
        self.assertTrue(eng.get_mame_capabilities().edit)
        self.assertTrue(eng.get_mame_capabilities().info)
        self.assertEqual(" pos + edit + info", eng.get_mame_capabilities().retro_info())

    async def test_modern_engine_name_is_not_parsed_as_mame_capabilities(self):
        eng = UciEngine("/tmp/modern", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.engine.id = {"name": "Modern Engine (pos+edit)"}

        eng._set_engine_name()

        self.assertEqual("Modern Engine (pos+edit)", eng.get_name())
        self.assertFalse(eng.get_mame_capabilities().position)
        self.assertFalse(eng.supports_mame_edit())

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

    async def test_eval_supports_reported_division_expression(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "((auto / 50 + 1) * 50)"}, Rating(1566, 123.0))
        self.assertEqual(1616, eng.engine_rating)
        self.assertTrue(eng.is_adaptive)

    async def test_eval_supports_int_function(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "max(1320, int(auto / 50 + 1) * 50)"}, Rating(1566, 123.0))
        self.assertEqual(1600, eng.engine_rating)
        self.assertTrue(eng.is_adaptive)

    async def test_eval_function_argument_error_does_not_crash_startup(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        with self.assertLogs("uci.engine", level="ERROR"):
            await eng.startup({UCI_ELO: "max(auto)"}, Rating(1566, 123.0))
        self.assertEqual(-1, eng.engine_rating)
        self.assertNotIn(UCI_ELO, eng.options)

    async def test_eval_arithmetic_error_does_not_crash_startup(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        with self.assertLogs("uci.engine", level="ERROR"):
            await eng.startup({UCI_ELO: "auto / 0"}, Rating(1566, 123.0))
        self.assertEqual(-1, eng.engine_rating)
        self.assertNotIn(UCI_ELO, eng.options)

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

    @patch("uci.engine.write_picochess_ini")
    async def test_update_rating_expression_error_falls_back_without_crashing(self, _):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        await eng.startup({UCI_ELO: "auto + 11"}, Rating(850.5, 123.0))
        eng.uci_elo_eval_fn = "100 / (auto - auto)"

        with self.assertLogs("uci.engine", level="ERROR"):
            new_rating = await eng.update_rating(Rating(850.5, 123.0), Result.WIN)

        self.assertEqual(890, int(new_rating.rating))
        self.assertEqual(900, eng.engine_rating)
        self.assertIsNone(eng.uci_elo_eval_fn)

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

    async def test_engine_ready_timeout_does_not_cancel_pending_ping(self):
        ping_can_finish = asyncio.Event()
        engine = MockEngine()

        async def delayed_ping():
            await ping_can_finish.wait()

        engine.ping = AsyncMock(side_effect=delayed_ping)
        analyser = ContinuousAnalysis(
            engine=engine,
            delay=0,
            loop=asyncio.get_running_loop(),
            engine_debug_name="engine",
            engine_lease=EngineLease(),
        )

        self.assertFalse(await analyser._wait_for_engine_ready(timeout=0.01))
        self.assertIsNotNone(analyser._ready_ping_task)
        self.assertFalse(analyser._ready_ping_task.cancelled())

        ping_can_finish.set()
        self.assertTrue(await analyser._wait_for_engine_ready(timeout=0.1))
        engine.ping.assert_awaited_once()

    async def test_analysis_waits_for_pending_readiness_ping(self):
        ping_started = asyncio.Event()
        ping_can_finish = asyncio.Event()
        engine = MockEngine()

        async def delayed_ping():
            ping_started.set()
            await ping_can_finish.wait()

        engine.ping = AsyncMock(side_effect=delayed_ping)
        engine.analysis = AsyncMock()
        analyser = ContinuousAnalysis(
            engine=engine,
            delay=0,
            loop=asyncio.get_running_loop(),
            engine_debug_name="engine",
            engine_lease=EngineLease(),
        )
        analyser.current_game = chess.Board()
        analyser._running = True

        analysis_task = asyncio.create_task(analyser._analyse_forever(limit=None, multipv=None))
        await ping_started.wait()

        engine.analysis.assert_not_awaited()
        self.assertFalse(analyser._ready_ping_task.cancelled())
        analyser._running = False
        ping_can_finish.set()
        await analysis_task

    async def test_pending_readiness_ping_safely_hands_lease_to_playing_search(self):
        protocol = RealUciProtocol()
        transport = chess.engine.MockTransport(protocol)
        protocol.initialized = True
        protocol.first_game = False
        protocol.game = 1
        transport.expect("isready", [])

        lease = EngineLease()
        analyser = ContinuousAnalysis(
            engine=protocol,
            delay=0,
            loop=asyncio.get_running_loop(),
            engine_debug_name="engine",
            engine_lease=lease,
        )
        analyser.current_game = chess.Board()
        analyser._running = True
        analyser_task = asyncio.create_task(analyser._analyse_forever(limit=None, multipv=None))

        while transport.expectations:
            await asyncio.sleep(0)

        transport.expect("position startpos", [])
        transport.expect("go depth 1", ["bestmove e2e4"])
        playing = PlayingContinuousAnalysis(
            engine=protocol,
            loop=asyncio.get_running_loop(),
            engine_lease=lease,
            engine_debug_name="engine",
        )
        playing.set_game_id(1)
        result_queue = asyncio.Queue()
        await playing.play_move(chess.Board(), Limit(depth=1), False, result_queue)

        try:
            # The old 0.5 second readiness poll must not release the lease while
            # python-chess still owns the ping command.
            await asyncio.sleep(0.55)
            self.assertEqual("continuous", lease.owner())

            # Delivering readyok after the playing request must finish the ping,
            # not hit a cancelled result Future inside python-chess.
            protocol.pipe_data_received(1, b"readyok\n")
            result = await asyncio.wait_for(result_queue.get(), timeout=1.0)
            self.assertEqual(chess.Move.from_uci("e2e4"), result.move)
            self.assertIsNone(lease.owner())
        finally:
            analyser._running = False
            for task in (analyser_task, playing._task, analyser._ready_ping_task):
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except BaseException:
                        pass

    async def test_uci_quit_does_not_cancel_pending_ping_before_late_readyok(self):
        protocol = RealUciProtocol()
        transport = chess.engine.MockTransport(protocol)
        protocol.initialized = True
        transport.expect("isready", [])
        ping_task = asyncio.create_task(protocol.ping())
        while transport.expectations:
            await asyncio.sleep(0)

        transport.expect("quit", [])
        quit_task = asyncio.create_task(protocol.quit())
        while transport.expectations:
            await asyncio.sleep(0)

        protocol.pipe_data_received(1, b"readyok\n")
        await ping_task
        protocol.connection_lost(None)
        await quit_task

    async def test_readiness_engine_termination_is_not_treated_as_pending(self):
        engine = MockEngine()
        engine.ping = AsyncMock(side_effect=EngineTerminatedError("dead"))
        analyser = ContinuousAnalysis(
            engine=engine,
            delay=0,
            loop=asyncio.get_running_loop(),
            engine_debug_name="engine",
            engine_lease=EngineLease(),
        )

        with self.assertRaises(EngineTerminatedError):
            await analyser._wait_for_engine_ready(timeout=0.1)

    async def test_readiness_protocol_failure_is_not_treated_as_pending(self):
        engine = MockEngine()
        engine.ping = AsyncMock(side_effect=AssertionError("CommandState.NEW"))
        analyser = ContinuousAnalysis(
            engine=engine,
            delay=0,
            loop=asyncio.get_running_loop(),
            engine_debug_name="engine",
            engine_lease=EngineLease(),
        )

        with self.assertRaises(AssertionError):
            await analyser._wait_for_engine_ready(timeout=0.1)

    async def test_recovery_cancellation_still_releases_continuous_lease(self):
        engine = MockEngine()
        ping_started = asyncio.Event()
        keep_ping_pending = asyncio.Event()

        async def delayed_ping():
            ping_started.set()
            await keep_ping_pending.wait()

        engine.ping = AsyncMock(side_effect=delayed_ping)
        eng = UciEngine("some_engine", UciShell(), "", asyncio.get_running_loop())
        recovery_started = asyncio.Event()
        allow_recovery_to_finish = asyncio.Event()

        async def recover(_reason):
            recovery_started.set()
            await allow_recovery_to_finish.wait()
            return True

        eng._recover_from_failed_analyser_stop_inner = AsyncMock(side_effect=recover)
        lease = EngineLease()
        analyser = ContinuousAnalysis(
            engine=engine,
            delay=0,
            loop=asyncio.get_running_loop(),
            engine_debug_name="engine",
            engine_lease=lease,
            recover_engine_cb=eng._recover_from_failed_analyser_stop,
        )
        analyser.current_game = chess.Board()
        analyser._running = True

        task = asyncio.create_task(analyser._analyse_forever(limit=None, multipv=None))
        await ping_started.wait()
        task.cancel()
        await recovery_started.wait()
        allow_recovery_to_finish.set()

        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNone(lease.owner())
        self.assertIsNotNone(analyser._ready_ping_task)
        analyser._ready_ping_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await analyser._ready_ping_task

    async def test_readiness_deadline_recovers_before_releasing_lease(self):
        ping_can_finish = asyncio.Event()
        engine = MockEngine()

        async def delayed_ping():
            await ping_can_finish.wait()

        engine.ping = AsyncMock(side_effect=delayed_ping)
        lease = EngineLease()
        recovery_owners = []

        async def recover(_reason):
            recovery_owners.append(lease.owner())
            ping_can_finish.set()
            await asyncio.sleep(0)
            return True

        analyser = ContinuousAnalysis(
            engine=engine,
            delay=0,
            loop=asyncio.get_running_loop(),
            engine_debug_name="engine",
            engine_lease=lease,
            recover_engine_cb=recover,
        )
        analyser.current_game = chess.Board()
        analyser._running = True

        with (
            patch("uci.engine.ENGINE_READY_POLL_TIMEOUT", 0.005),
            patch("uci.engine.ENGINE_READY_DEADLINE", 0.02),
        ):
            await analyser._analyse_forever(limit=None, multipv=None)

        self.assertEqual(["continuous"], recovery_owners)
        self.assertIsNone(lease.owner())
        self.assertTrue(analyser._ready_ping_task.done())

    async def test_shutdown_terminates_ignored_quit_and_finishes_pending_ping(self):
        events = []
        protocol = RealUciProtocol()

        class TerminatingMockTransport(chess.engine.MockTransport):
            def __init__(self, protocol):
                self.return_code = None
                super().__init__(protocol)

            def get_returncode(self):
                return self.return_code

            def terminate(self):
                events.append("terminate")
                self.return_code = -15
                self.protocol.connection_lost(None)

            def close(self):
                events.append("close")

        transport = TerminatingMockTransport(protocol)
        protocol.initialized = True
        transport.expect("isready", [])
        ping_task = asyncio.create_task(protocol.ping())
        while transport.expectations:
            await asyncio.sleep(0)
        ping_task.add_done_callback(lambda _task: events.append("ping_done"))
        transport.expect("quit", [])

        eng = UciEngine("some_engine", UciShell(), "", asyncio.get_running_loop())
        eng.engine = protocol
        eng.transport = transport
        with (
            patch("uci.engine.ENGINE_QUIT_TIMEOUT", 0.01),
            patch("uci.engine.ENGINE_TERMINATE_TIMEOUT", 0.01),
            patch("uci.engine.ENGINE_KILL_TIMEOUT", 0.01),
        ):
            await eng._shutdown_standard_engine()

        await asyncio.sleep(0)
        self.assertTrue(ping_task.done())
        with self.assertRaises(EngineTerminatedError):
            await ping_task
        await asyncio.sleep(0)
        self.assertIn("ping_done", events)
        self.assertLess(events.index("terminate"), events.index("close"))

    async def test_stop_analysis_reports_incomplete_stop_transaction(self):
        eng = UciEngine("some_engine", UciShell(), "", asyncio.get_running_loop())
        eng.analyser = Mock()
        eng.analyser.stop_async = AsyncMock(return_value=False)
        eng.analyser.consume_forced_stop.return_value = True

        self.assertFalse(await eng.stop_analysis())
        self.assertTrue(eng.consume_forced_analyser_stop())

    async def test_quit_continues_direct_shutdown_after_incomplete_analyser_stop(self):
        eng = UciEngine("some_engine", UciShell(), "", asyncio.get_running_loop())
        eng.analyser = Mock()
        eng.stop_analysis = AsyncMock(return_value=False)
        eng._shutdown_standard_engine = AsyncMock()
        eng._close_remote_connection = AsyncMock()

        with patch("uci.engine.asyncio.sleep", new=AsyncMock()):
            await eng.quit()

        eng.stop_analysis.assert_awaited_once_with()
        eng._shutdown_standard_engine.assert_awaited_once_with()
        eng._close_remote_connection.assert_awaited_once_with()

    async def test_stop_async_waits_for_pending_ping_without_recovery(self):
        ping_started = asyncio.Event()
        ping_can_finish = asyncio.Event()
        engine = MockEngine()

        async def delayed_ping():
            ping_started.set()
            await ping_can_finish.wait()

        engine.ping = AsyncMock(side_effect=delayed_ping)
        recover = AsyncMock(return_value=True)
        lease = EngineLease()
        analyser = ContinuousAnalysis(
            engine=engine,
            delay=0,
            loop=asyncio.get_running_loop(),
            engine_debug_name="engine",
            engine_lease=lease,
            recover_engine_cb=recover,
        )
        analyser.game = chess.Board()
        analyser.start(analyser.game)
        await ping_started.wait()

        async def finish_ping():
            await asyncio.sleep(0.02)
            ping_can_finish.set()

        finish_task = asyncio.create_task(finish_ping())
        with (
            patch("uci.engine.ENGINE_READY_POLL_TIMEOUT", 0.005),
            patch("uci.engine.ENGINE_READY_DEADLINE", 0.1),
        ):
            stopped = await analyser.stop_async(timeout=0.01, cancel_timeout=0.1)
        await finish_task

        self.assertTrue(stopped)
        recover.assert_not_awaited()
        self.assertFalse(analyser.consume_forced_stop())
        self.assertIsNone(lease.owner())

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

    async def test_newgame_can_send_scanned_position_to_mame(self):
        eng = UciEngine("engines/aarch64/mame/test", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        command_order = []
        eng.engine.send_line = Mock(side_effect=lambda command: command_order.append(command))
        eng.engine._position = Mock(side_effect=lambda _board: command_order.append("position"))
        eng.engine.analysis = AsyncMock()
        eng.engine.play = AsyncMock()

        async def record_ping():
            command_order.append("isready")

        eng.engine.ping = AsyncMock(side_effect=record_ping)
        board = chess.Board("8/8/8/8/8/8/4K3/7k w - - 0 1")

        with patch("uci.engine.asyncio.sleep", new=AsyncMock()):
            await eng.newgame(board, send_position_to_mame=True)

        eng.engine.send_line.assert_called_once_with("ucinewgame")
        eng.engine._position.assert_called_once()
        sent_board = eng.engine._position.call_args.args[0]
        self.assertEqual(board.fen(), sent_board.fen())
        self.assertIsNot(board, sent_board)
        eng.engine.ping.assert_awaited_once_with()
        self.assertFalse(eng.engine.first_game)
        self.assertEqual(eng.game_id, eng.engine.game)
        self.assertEqual(["ucinewgame", "position", "isready"], command_order)
        eng.engine.analysis.assert_not_awaited()
        eng.engine.play.assert_not_awaited()

    async def test_mame_terminal_position_preserves_final_move_without_waiting(self):
        eng = UciEngine("engines/aarch64/mame/test", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.engine._position = Mock()
        eng.engine.ping = AsyncMock()
        eng.playing = Mock()
        eng.playing.is_waiting_for_move.return_value = False
        board = chess.Board()
        for san in ("f3", "e5", "g4", "Qh4#"):
            board.push_san(san)

        sent = await eng.send_terminal_position_to_mame(board)

        self.assertTrue(sent)
        eng.engine._position.assert_called_once()
        sent_board = eng.engine._position.call_args.args[0]
        self.assertEqual(board.fen(), sent_board.fen())
        self.assertEqual(board.move_stack, sent_board.move_stack)
        self.assertIsNot(board, sent_board)
        eng.engine.ping.assert_not_awaited()

    async def test_terminal_position_is_not_sent_to_non_mame_engine(self):
        eng = UciEngine("engines/aarch64/some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.engine._position = Mock()

        sent = await eng.send_terminal_position_to_mame(chess.Board())

        self.assertFalse(sent)
        eng.engine._position.assert_not_called()

    async def test_mame_terminal_position_skips_when_previous_search_does_not_stop(self):
        eng = UciEngine("engines/aarch64/mame/test", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.engine._position = Mock()
        eng.playing = Mock()
        eng.playing.is_waiting_for_move.return_value = True
        eng.playing.wait_until_idle = AsyncMock(return_value=False)

        with self.assertLogs("uci.engine", level="WARNING") as captured:
            sent = await eng.send_terminal_position_to_mame(chess.Board())

        self.assertFalse(sent)
        eng.playing.wait_until_idle.assert_awaited_once_with(timeout=2.5)
        eng.engine._position.assert_not_called()
        self.assertIn("still thinking", "\n".join(captured.output))

    async def test_mame_terminal_position_is_sent_after_previous_search_stops(self):
        eng = UciEngine("engines/aarch64/mame/test", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.engine._position = Mock()
        eng.playing = Mock()
        eng.playing.is_waiting_for_move.return_value = True
        eng.playing.wait_until_idle = AsyncMock(return_value=True)
        board = chess.Board()
        board.push_san("e4")

        sent = await eng.send_terminal_position_to_mame(board)

        self.assertTrue(sent)
        eng.playing.wait_until_idle.assert_awaited_once_with(timeout=2.5)
        eng.engine._position.assert_called_once()

    async def test_newgame_mame_setup_position_handles_failed_isready(self):
        eng = UciEngine("engines/aarch64/mame/test", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.engine.send_line = Mock()
        eng.engine._position = Mock()
        eng.engine.ping = AsyncMock(side_effect=chess.engine.EngineTerminatedError("engine stopped"))

        with patch("uci.engine.asyncio.sleep", new=AsyncMock()):
            with self.assertLogs("uci.engine", level="WARNING") as captured:
                await eng.newgame(chess.Board(), send_position_to_mame=True)

        eng.engine._position.assert_called_once()
        eng.engine.ping.assert_awaited_once_with()
        self.assertIn("isready ping failed after setup position", "\n".join(captured.output))

    async def test_newgame_scanned_position_flag_does_not_affect_non_mame_engine(self):
        eng = UciEngine("engines/aarch64/some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.engine.send_line = Mock()
        eng.engine._position = Mock()
        eng.engine.ping = AsyncMock()

        with patch("uci.engine.asyncio.sleep", new=AsyncMock()):
            await eng.newgame(chess.Board(), send_position_to_mame=True)

        eng.engine.send_line.assert_not_called()
        eng.engine._position.assert_not_called()
        eng.engine.ping.assert_not_awaited()

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

    async def test_start_analysis_restarts_when_depth_changes(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.set_mode()
        eng.analyser = Mock()
        eng.analyser.is_running.return_value = True
        eng.analyser.get_limit_depth.return_value = 40
        eng.analyser.get_multipv.return_value = None
        eng.analyser.get_fen.return_value = chess.Board().fen()
        eng.playing = Mock()
        eng.playing.is_waiting_for_move.return_value = False

        async def stop_analysis():
            eng.analyser.is_running.return_value = False
            return True

        eng.stop_analysis = AsyncMock(side_effect=stop_analysis)

        started = await eng.start_analysis(chess.Board(), limit=chess.engine.Limit(depth=30))

        self.assertFalse(started)
        eng.stop_analysis.assert_awaited_once_with()
        eng.analyser.start.assert_called_once()
        self.assertEqual(30, eng.analyser.start.call_args.kwargs["limit"].depth)

    async def test_start_analysis_restarts_when_multipv_changes(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.set_mode()
        eng.analyser = Mock()
        eng.analyser.is_running.return_value = True
        eng.analyser.get_limit_depth.return_value = 30
        eng.analyser.get_multipv.return_value = None
        eng.analyser.get_fen.return_value = chess.Board().fen()
        eng.playing = Mock()
        eng.playing.is_waiting_for_move.return_value = False

        async def stop_analysis():
            eng.analyser.is_running.return_value = False
            return True

        eng.stop_analysis = AsyncMock(side_effect=stop_analysis)

        started = await eng.start_analysis(chess.Board(), limit=chess.engine.Limit(depth=30), multipv=3)

        self.assertFalse(started)
        eng.stop_analysis.assert_awaited_once_with()
        eng.analyser.start.assert_called_once_with(ANY, limit=ANY, multipv=3)

    async def test_start_analysis_aborts_when_previous_analyser_did_not_stop(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.set_mode()
        eng.analyser = Mock()
        eng.analyser.is_running.return_value = True
        eng.analyser.get_limit_depth.return_value = 40
        eng.analyser.get_multipv.return_value = None
        eng.analyser.get_fen.return_value = chess.Board().fen()
        eng.playing = Mock()
        eng.playing.is_waiting_for_move.return_value = False
        eng.stop_analysis = AsyncMock(return_value=False)

        started = await eng.start_analysis(chess.Board(), limit=chess.engine.Limit(depth=30))

        self.assertFalse(started)
        eng.stop_analysis.assert_awaited_once_with()
        eng.analyser.start.assert_not_called()

    async def test_start_analysis_treats_default_and_single_multipv_as_equivalent(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.set_mode()
        eng.analyser = Mock()
        eng.analyser.is_running.return_value = True
        eng.analyser.get_limit_depth.return_value = 30
        eng.analyser.get_multipv.return_value = None
        eng.analyser.get_fen.return_value = chess.Board().fen()
        eng.playing = Mock()
        eng.stop_analysis = AsyncMock()

        started = await eng.start_analysis(chess.Board(), limit=chess.engine.Limit(depth=30), multipv=1)

        self.assertTrue(started)
        eng.stop_analysis.assert_not_awaited()
        eng.analyser.start.assert_not_called()

    async def test_get_analysis_returns_empty_while_engine_setup_incomplete(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.analyser = Mock()
        eng.analyser.is_running.return_value = True

        result = await eng.get_analysis(chess.Board())

        self.assertEqual({"info": [], "fen": ""}, result)
        eng.analyser.get_analysis.assert_not_called()

    async def test_is_analyser_running_for_checks_the_current_position(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.analyser = Mock()
        eng.analyser.is_running.return_value = True
        game = chess.Board()
        eng.analyser.get_fen.return_value = game.fen()

        self.assertTrue(eng.is_analyser_running_for(game))

        game.push_uci("e2e4")
        self.assertFalse(eng.is_analyser_running_for(game))

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

    async def test_attaching_replacement_engine_discards_old_readiness_ping(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        old_engine = MockEngine()
        replacement_engine = MockEngine()
        eng.engine = replacement_engine
        eng.analyser = ContinuousAnalysis(
            engine=old_engine,
            delay=0,
            loop=asyncio.get_running_loop(),
            engine_debug_name="engine",
            engine_lease=EngineLease(),
        )
        eng.analyser._ready_ping_task = Mock()
        eng.playing = Mock()

        eng._attach_engine_to_sisters()

        self.assertIs(replacement_engine, eng.analyser.engine)
        self.assertIsNone(eng.analyser._ready_ping_task)

    async def test_recovery_finishes_engine_setup_before_propagating_cancellation(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        recovery_started = asyncio.Event()
        allow_recovery_to_finish = asyncio.Event()

        async def recover(_reason):
            recovery_started.set()
            await allow_recovery_to_finish.wait()
            eng._analysis_allowed = True
            return True

        eng._recover_from_failed_analyser_stop_inner = AsyncMock(side_effect=recover)
        task = asyncio.create_task(eng._recover_from_failed_analyser_stop("protocol failure"))
        await recovery_started.wait()

        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())

        allow_recovery_to_finish.set()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertTrue(eng._analysis_allowed)

    async def test_concurrent_recovery_requests_share_one_engine_restart(self):
        """A protocol failure and NEW_GAME must not restart/configure in parallel."""
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        eng.engine = MockEngine()
        eng.analyser = Mock()
        eng.playing = Mock()
        eng.engine_lease = Mock()
        eng._shutdown_standard_engine = AsyncMock()
        eng._attach_engine_to_sisters = Mock()
        eng._set_engine_name = Mock(return_value=True)

        async def start_engine():
            eng.engine = MockEngine()

        eng._start_engine_process = AsyncMock(side_effect=start_engine)

        first_configure_started = asyncio.Event()
        release_first_configure = asyncio.Event()
        configure_calls = 0

        async def send_options(*, strict=False):
            nonlocal configure_calls
            configure_calls += 1
            if configure_calls == 1:
                first_configure_started.set()
                await release_first_configure.wait()
            return True

        eng.send = AsyncMock(side_effect=send_options)

        protocol_recovery = asyncio.create_task(
            eng._recover_from_failed_analyser_stop(
                "continuous analysis protocol failure: AssertionError: CommandState.NEW"
            )
        )
        await first_configure_started.wait()

        new_game_recovery = asyncio.create_task(
            eng._recover_from_failed_analyser_stop(
                "new game requested after analyser protocol failure"
            )
        )
        await asyncio.sleep(0)
        release_first_configure.set()

        recovered = await asyncio.gather(protocol_recovery, new_game_recovery)

        self.assertEqual([True, True], recovered)
        self.assertEqual(1, eng._shutdown_standard_engine.await_count)
        self.assertEqual(1, eng._start_engine_process.await_count)
        self.assertEqual(1, eng.send.await_count)

    def test_filter_options_excludes_python_chess_managed_options(self):
        eng = UciEngine("some_engine", UciShell(), "", self.loop)
        wanted = {
            "Threads": 2,
            "UCI_Chess960": True,
            "UCI_Variant": "chess",
            "MultiPV": 3,
            "Ponder": True,
        }

        filtered = eng.filter_options(wanted, dict.fromkeys(wanted))

        self.assertEqual({"Threads": 2}, filtered)


class PausingConfigureProtocol(CooperativeUciProtocol):
    """Real python-chess protocol with a controllable configure await point."""

    def __init__(self, configure_started: asyncio.Event, release_configure: asyncio.Event):
        super().__init__()
        self.configure_started = configure_started
        self.release_configure = release_configure

    async def configure(self, options):
        self.configure_started.set()
        await self.release_configure.wait()
        return await super().configure(options)


class TerminatingConfigureTransport(chess.engine.MockTransport):
    """Terminate the real protocol while it dispatches its first setoption."""

    def __init__(self, protocol):
        super().__init__(protocol)
        self.failed_command = None

    def write(self, data):
        super().write(data)
        if data.startswith(b"setoption") and not self.protocol.returncode.done():
            self.failed_command = self.protocol.command
            self.protocol.connection_lost(None)


class VariantFailingTransport(chess.engine.MockTransport):
    """Fail the direct UCI_Variant write before normal configuration."""

    def write(self, data):
        if data.startswith(b"setoption name UCI_Variant"):
            raise OSError("variant write failed")
        super().write(data)


class FailingConfigureProtocol(CooperativeUciProtocol):
    """Real protocol facade that raises a selected configure I/O failure."""

    def __init__(self, error):
        super().__init__()
        self.error = error

    async def configure(self, options):
        raise self.error


class TestEngineRecoveryProtocol(unittest.IsolatedAsyncioTestCase):
    async def _protocol(self, protocol=None, transport_class=chess.engine.MockTransport):
        protocol = protocol or CooperativeUciProtocol()
        transport = transport_class(protocol)
        transport.expect(
            "uci",
            [
                "id name Recovery Test",
                "option name Threads type spin default 1 min 1 max 8",
                "uciok",
            ],
        )
        await protocol.initialize()
        return protocol, transport

    def _engine(self, threads=2):
        eng = UciEngine("some_engine", UciShell(), "", asyncio.get_running_loop())
        eng.options = {"Threads": threads}
        eng.analyser = Mock()
        eng.playing = Mock()
        eng.engine_lease = Mock()
        eng._shutdown_standard_engine = AsyncMock()
        eng._attach_engine_to_sisters = Mock()
        eng._set_engine_name = Mock(return_value=True)
        return eng

    @staticmethod
    def _install_start_sequence(eng, engines):
        pending = iter(engines)

        async def start_engine():
            eng.engine, eng.transport = next(pending)

        eng._start_engine_process = AsyncMock(side_effect=start_engine)

    async def test_real_protocol_configuration_coalesces_successful_recovery(self):
        configure_started = asyncio.Event()
        release_configure = asyncio.Event()
        protocol, transport = await self._protocol(PausingConfigureProtocol(configure_started, release_configure))
        transport.expect("setoption name Threads value 2")
        eng = self._engine()
        self._install_start_sequence(eng, [(protocol, transport)])

        first = asyncio.create_task(eng._recover_from_failed_analyser_stop("protocol failure"))
        await configure_started.wait()
        waiter = asyncio.create_task(eng._recover_from_failed_analyser_stop("new game"))
        await asyncio.sleep(0)
        release_configure.set()

        self.assertEqual([True, True], await asyncio.gather(first, waiter))
        self.assertEqual(1, eng._start_engine_process.await_count)
        self.assertEqual(1, eng._recovery_generation)
        self.assertTrue(eng._analysis_allowed)
        transport.assert_done()

    async def test_terminated_configuration_is_retried_by_waiter(self):
        dying_protocol, dying_transport = await self._protocol(
            transport_class=TerminatingConfigureTransport
        )
        dying_transport.expect("setoption name Threads value 2")
        healthy_protocol, healthy_transport = await self._protocol()
        healthy_transport.expect("setoption name Threads value 2")
        eng = self._engine()
        self._install_start_sequence(
            eng,
            [(dying_protocol, dying_transport), (healthy_protocol, healthy_transport)],
        )

        first = asyncio.create_task(eng._recover_from_failed_analyser_stop("protocol failure"))
        waiter = asyncio.create_task(eng._recover_from_failed_analyser_stop("new game"))
        results = await asyncio.gather(first, waiter)

        self.assertEqual([False, True], results)
        self.assertTrue(dying_protocol.returncode.done())
        self.assertIsInstance(
            dying_transport.failed_command.result.exception(),
            chess.engine.EngineTerminatedError,
        )
        self.assertEqual(2, eng._start_engine_process.await_count)
        self.assertEqual(1, eng._recovery_generation)
        self.assertIs(healthy_protocol, eng.engine)
        healthy_transport.assert_done()

    async def test_cancelled_configuration_propagates_and_waiter_retries(self):
        configure_started = asyncio.Event()
        release_configure = asyncio.Event()
        cancelled_protocol, cancelled_transport = await self._protocol(
            PausingConfigureProtocol(configure_started, release_configure)
        )
        healthy_protocol, healthy_transport = await self._protocol()
        healthy_transport.expect("setoption name Threads value 2")
        eng = self._engine()
        self._install_start_sequence(
            eng,
            [(cancelled_protocol, cancelled_transport), (healthy_protocol, healthy_transport)],
        )

        first = asyncio.create_task(eng._recover_from_failed_analyser_stop("protocol failure"))
        await configure_started.wait()
        waiter = asyncio.create_task(eng._recover_from_failed_analyser_stop("new game"))
        await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first

        self.assertTrue(await asyncio.wait_for(waiter, timeout=1.0))
        self.assertEqual(2, eng._start_engine_process.await_count)
        self.assertEqual(1, eng._recovery_generation)
        self.assertIs(healthy_protocol, eng.engine)
        healthy_transport.assert_done()

    async def test_rejected_option_does_not_complete_recovery(self):
        protocol, transport = await self._protocol()
        eng = self._engine(threads=99)
        self._install_start_sequence(eng, [(protocol, transport)])

        with self.assertLogs("uci.engine", level="WARNING") as logged:
            recovered = await eng._recover_from_failed_analyser_stop("protocol failure")

        self.assertFalse(recovered)
        self.assertEqual(0, eng._recovery_generation)
        self.assertFalse(eng._analysis_allowed)
        eng.analyser.clear_failure.assert_not_called()
        self.assertIn("Threads", "\n".join(logged.output))
        self.assertFalse(protocol.returncode.done())
        transport.assert_done()

    async def test_terminated_protocol_is_not_treated_as_configuration_success(self):
        protocol, transport = await self._protocol()
        protocol.connection_lost(None)
        self.assertEqual(0, await protocol.returncode)
        eng = self._engine()
        eng.engine = protocol
        eng.transport = transport

        self.assertFalse(await eng.send(strict=True))
        self.assertTrue(protocol.returncode.done())
        transport.assert_done()

    async def test_default_send_preserves_io_exception_behavior(self):
        for error in (OSError("I/O failed"), asyncio.InvalidStateError("invalid state")):
            with self.subTest(error=type(error).__name__):
                protocol, transport = await self._protocol(FailingConfigureProtocol(error))
                eng = self._engine()
                eng.engine = protocol
                eng.transport = transport

                with self.assertRaises(type(error)):
                    await eng.send()
                transport.assert_done()

    async def test_strict_send_reports_io_exceptions_as_failure(self):
        for error in (OSError("I/O failed"), asyncio.InvalidStateError("invalid state")):
            with self.subTest(error=type(error).__name__):
                protocol, transport = await self._protocol(FailingConfigureProtocol(error))
                eng = self._engine()
                eng.engine = protocol
                eng.transport = transport

                self.assertFalse(await eng.send(strict=True))
                transport.assert_done()

    async def test_failed_direct_variant_write_does_not_complete_recovery(self):
        protocol, transport = await self._protocol(transport_class=VariantFailingTransport)
        eng = self._engine()
        eng.options["UCI_Variant"] = "atomic"
        self._install_start_sequence(eng, [(protocol, transport)])

        self.assertFalse(await eng._recover_from_failed_analyser_stop("protocol failure"))
        self.assertEqual(0, eng._recovery_generation)
        self.assertFalse(eng._analysis_allowed)
        eng.analyser.clear_failure.assert_not_called()
        transport.assert_done()

    async def test_waiter_restarts_if_successful_replacement_dies_before_liveness_check(self):
        configure_started = asyncio.Event()
        release_configure = asyncio.Event()
        first_protocol, first_transport = await self._protocol(
            PausingConfigureProtocol(configure_started, release_configure)
        )
        first_transport.expect("setoption name Threads value 2")
        second_protocol, second_transport = await self._protocol()
        second_transport.expect("setoption name Threads value 2")
        eng = self._engine()
        self._install_start_sequence(
            eng,
            [(first_protocol, first_transport), (second_protocol, second_transport)],
        )

        clear_calls = 0

        def terminate_after_generation_advances():
            nonlocal clear_calls
            clear_calls += 1
            if clear_calls == 1:
                asyncio.get_running_loop().call_soon(first_protocol.connection_lost, None)

        eng.analyser.clear_failure.side_effect = terminate_after_generation_advances
        first = asyncio.create_task(eng._recover_from_failed_analyser_stop("protocol failure"))
        await configure_started.wait()
        waiter = asyncio.create_task(eng._recover_from_failed_analyser_stop("new game"))
        await asyncio.sleep(0)
        release_configure.set()

        self.assertEqual([True, True], await asyncio.gather(first, waiter))
        self.assertTrue(first_protocol.returncode.done())
        self.assertEqual(2, eng._start_engine_process.await_count)
        self.assertEqual(2, eng._recovery_generation)
        self.assertIs(second_protocol, eng.engine)
        second_transport.assert_done()

    async def test_reopen_engine_rejects_incomplete_configuration(self):
        protocol, transport = await self._protocol()
        eng = self._engine(threads=99)
        eng.quit = AsyncMock()
        self._install_start_sequence(eng, [(protocol, transport)])

        self.assertFalse(await eng.reopen_engine())
        self.assertFalse(eng._analysis_allowed)
        self.assertFalse(protocol.returncode.done())
        transport.assert_done()
