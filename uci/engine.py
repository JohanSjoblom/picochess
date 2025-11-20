# Copyright (C) 2013-2018 Jean-Francois Romang (jromang@posteo.de)
#                         Shivkumar Shivaji ()
#                         Jürgen Précour (LocutusOfPenguin@posteo.de)
#                         Johan Sjöblom (messier109@gmail.com)
#
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

from __future__ import annotations

import asyncio
from asyncio import CancelledError
import os
from typing import Optional, Iterable
import logging
import configparser
import copy

import spur  # type: ignore
import paramiko

import chess.engine  # type: ignore
from chess.engine import InfoDict, Limit, UciProtocol, AnalysisResult, PlayResult, EngineTerminatedError
from chess import Board  # type: ignore
from uci.rating import Rating, Result
from utilities import write_picochess_ini

FLOAT_ANALYSIS_WAIT = 0.1  # save CPU in ContinuousAnalysis

# Seconds to wait for an engine to exit before escalating.
ENGINE_QUIT_TIMEOUT = 3.0  # waiting seconds for a normal engine to quit
ENGINE_TERMINATE_TIMEOUT = 2.0  # if not send SIGTERM and wait a bit
ENGINE_KILL_TIMEOUT = 1.0  # finally send SIGKILL, wait time gives OS some time

UCI_ELO = "UCI_Elo"
UCI_ELO_NON_STANDARD = "UCI Elo"
UCI_ELO_NON_STANDARD2 = "UCI_Limit"

logger = logging.getLogger(__name__)


class EngineLease:
    """Coordinate exclusive access to a single engine analysis session."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._owner: str | None = None
        self._interrupt_event = asyncio.Event()
        self._requester: str | None = None

    async def acquire(self, owner: str, preempt: bool = False) -> None:
        """
        Acquire exclusive access for ``owner``.

        When ``preempt`` is True, request the current owner to stop and release.
        """
        if self._owner == owner:
            return

        requester = owner if preempt else None
        if requester:
            self._requester = requester
            self._interrupt_event.set()

        try:
            await self._lock.acquire()
        except Exception:
            if requester and self._requester == requester:
                self._requester = None
                self._interrupt_event.clear()
            raise

        self._owner = owner
        self._requester = None
        self._interrupt_event.clear()

    def release(self, owner: str) -> None:
        """Release the lease if ``owner`` currently holds it."""
        if owner != self._owner:
            return

        self._owner = None
        self._interrupt_event.clear()
        if self._lock.locked():
            self._lock.release()

    def interrupt_requested(self, owner: str) -> bool:
        """Return True if ``owner`` has been asked to release the lease."""
        return self._owner == owner and self._interrupt_event.is_set()

    def owner(self) -> str | None:
        """Return the current lease owner (if any)."""
        return self._owner


class WindowsShellType:
    """Shell type supporting Windows for spur."""

    supports_which = True

    def generate_run_command(self, command_args, store_pid, cwd=None, update_env=None, new_process_group=False):
        if not update_env:
            update_env = {}
        if new_process_group:
            raise spur.ssh.UnsupportedArgumentError("'new_process_group' is not supported when using a windows shell")

        commands = []
        if command_args[0] == "kill":
            command_args = self.generate_kill_command(command_args[-1]).split()

        if store_pid:
            commands.append("powershell (Get-WmiObject Win32_Process -Filter ProcessId=$PID).ParentProcessId")

        if cwd is not None:
            commands.append(
                "cd {0} 2>&1 || ( echo. & echo spur-cd: %errorlevel% & exit 1 )".format(self.win_escape_sh(cwd))
            )
            commands.append("echo. & echo spur-cd: 0")

        update_env_commands = ["SET {0}={1}".format(key, value) for key, value in update_env.items()]
        commands += update_env_commands
        commands.append(
            "( (powershell Get-Command {0} > nul 2>&1) && echo 0) || (echo %errorlevel% & exit 1)".format(
                self.win_escape_sh(command_args[0])
            )
        )

        commands.append(" ".join(command_args))
        return " & ".join(commands)

    def generate_kill_command(self, pid):
        return "taskkill /F /PID {0}".format(pid)

    @staticmethod
    def win_escape_sh(value):
        return '"' + value + '"'


class UciShell(object):
    """Handle the uci engine shell."""

    def __init__(self, hostname=None, username=None, key_file=None, password=None, windows=False):
        super(UciShell, self).__init__()
        if hostname:
            logger.info("connecting to [%s]", hostname)
            shell_params = {
                "hostname": hostname,
                "username": username,
                "missing_host_key": paramiko.AutoAddPolicy(),
            }
            if key_file:
                shell_params["private_key_file"] = key_file
            else:
                shell_params["password"] = password
            if windows:
                shell_params["shell_type"] = WindowsShellType()

            self._shell = spur.SshShell(**shell_params)
        else:
            self._shell = None

    def __getattr__(self, attr):
        """Dispatch unknown attributes to SshShell."""
        return getattr(self._shell, attr)

    def get(self):
        return self if self._shell is not None else None


class ContinuousAnalysis:
    """class for continous analysis from a chess engine"""

    def __init__(
        self,
        engine: UciProtocol,
        delay: float,
        loop: asyncio.AbstractEventLoop,
        engine_debug_name: str,
        engine_lease: EngineLease,
    ):
        """
        A continuous analysis generator that runs as a background async task.

        :param delay: Time interval to do CPU saving sleep between analysis.
        """
        self.game = None  # latest position requested to be analysed
        self.limit_reached = False  # True when limit reached for position
        self.current_game = None  # latest position being analysed
        self.delay = delay
        self._running = False
        self._task = None
        self._analysis_data = None  # InfoDict list
        self.loop = loop  # main loop everywhere
        self.whoami = engine_debug_name  # picotutor or engine
        self.limit = None  # limit for analysis - set in start
        self.multipv = None  # multipv for analysis - set in start
        self.lock = asyncio.Lock()
        self.engine: UciProtocol = engine
        self.set_game_id(1)  # initial game identifier
        self.engine_lease = engine_lease
        if not self.engine:
            logger.error("%s ContinuousAnalysis initialised without engine", self.whoami)

    def set_game_id(self, game_id: int):
        """Set the current game identifier."""
        self.game_id = game_id
        self.current_game_id = game_id

    def is_limit_reached(self) -> bool:
        """return True if limit was reached for position being analysed"""
        return self.limit_reached

    async def _watching_analyse(self):
        """Internal function for continuous analysis in the background."""
        debug_once_limit = True
        debug_once_game = True
        self.limit_reached = False  # True when depth limit reached for position
        while self._running:
            try:
                if not self._game_analysable(self.game):
                    if debug_once_game:
                        logger.debug("%s no game to analyse", self.whoami)
                        debug_once_game = False  # dont flood log
                    await asyncio.sleep(self.delay * 2)
                    continue
                # important to check limit AND that game is still same - bug fix 13.4.2025
                if self.limit_reached and self.current_game_id == self.game_id and self.get_fen() == self.game.fen():
                    if debug_once_limit:
                        logger.debug("%s analysis limited", self.whoami)
                        debug_once_limit = False  # dont flood log
                    await asyncio.sleep(self.delay * 2)
                    continue
                async with self.lock:
                    # new limit, position, possibly new game_id infinite analysis
                    self.current_game = self.game.copy()  # position
                    self.limit_reached = False
                    self.current_game_id = self.game_id  # new id for each game
                    self._analysis_data = None
                debug_once_limit = True  # ok to debug once more after coming here again
                debug_once_game = True
                await self._analyse_forever(self.limit, self.multipv)
            except asyncio.CancelledError:
                logger.debug("%s cancelled", self.whoami)
                # same situation as in stop
                self._task = None
                self._running = False
            except chess.engine.EngineTerminatedError:
                logger.debug("Engine terminated while analysing - maybe user switched engine")
                # have to stop analysing
                self._task = None
                self._running = False
            except chess.engine.AnalysisComplete:
                logger.debug("%s ran out of information", self.whoami)
                asyncio.sleep(self.delay * 2)  # maybe it helps to wait some extra?

    async def _analyse_forever(self, limit: Limit | None, multipv: int | None) -> None:
        """Analyse forever if no limit sent, yielding the lease while pre-empted."""
        await self.engine_lease.acquire(owner="continuous")
        try:
            with await self.engine.analysis(
                board=self.current_game, limit=limit, multipv=multipv, game=self.game_id
            ) as analysis:
                async for info in analysis:
                    if self.engine_lease.interrupt_requested("continuous"):
                        try:
                            analysis.stop()
                        except Exception:
                            logger.debug("failed sending stop in infinite analysis")
                        return

                    async with self.lock:
                        if (
                            not self._running
                            or self.current_game_id != self.game_id
                            or self.current_game.fen() != self.game.fen()
                            or self.engine_lease.interrupt_requested("continuous")
                        ):
                            self._analysis_data = None  # drop ref into library
                            try:
                                analysis.stop()  # ask engine to stop analysing
                            except Exception:
                                logger.debug("failed sending stop in infinite analysis")
                            return  # quit analysis
                        updated = self._update_analysis_data(analysis)  # update to latest
                    if updated:
                        #  self._analysis data got a value
                        #  self.debug_analyser()  # normally commented out
                        if limit:
                            # @todo change 0 to -1 to get all multipv finished
                            info_limit: InfoDict = self._analysis_data[0]
                            if "depth" in info_limit and limit.depth:
                                if info_limit.get("depth") >= limit.depth:
                                    self.limit_reached = True
                                    return  # limit reached
                    await asyncio.sleep(self.delay)  # save cpu
        finally:
            self.engine_lease.release("continuous")

    def debug_analyser(self):
        """use this debug call to see how low and deep depth evolves"""
        # lock is on when we come here
        if self._analysis_data:
            j: InfoDict = self._analysis_data[0]
            if "depth" in j:
                logger.debug("%s deep depth: %d", self.whoami, j.get("depth"))

    async def get_latest_seen_depth(self) -> int:
        """return the latest depth seen in analysis info"""
        result = 0
        async with self.lock:
            if self._analysis_data:
                j: InfoDict = self._analysis_data[0]
                result = j.get("depth", 0)
        return result

    def _update_analysis_data(self, analysis: AnalysisResult) -> bool:
        """internal function for updating while analysing
        returns True if data was updated"""
        # lock is on when we come here
        result = False
        if analysis.multipv:
            self._analysis_data = analysis.multipv
            result = True
        return result

    def _game_analysable(self, game: chess.Board) -> bool:
        """return True if game is analysable"""
        if game is None:
            return False
        if game.is_game_over():
            return False
        return True

    def start(self, game: chess.Board, limit: Limit | None = None, multipv: int | None = None):
        """Starts the analysis.

        :param game: The current position to analyse.
        :param limit: limit the analysis, None means forever
        :param multipv: analyse with multipv, None means 1
        """
        if not self._running:
            if not self.engine:
                logger.error("%s ContinuousAnalysis cannot start without engine", self.whoami)
            else:
                self.game = game.copy()  # remember this game position
                self.limit_reached = False  # True when limit reached for position
                self.limit = limit
                self.multipv = multipv
                self._running = True
                self._task = self.loop.create_task(self._watching_analyse())
                logging.debug("%s started", self.whoami)
        else:
            logging.info("%s ContinuousAnalysis already running - strange!", self.whoami)

    def get_limit_depth(self) -> int | None:
        """return the limit.depth used by analysis - None if no limit or no limit.depth"""
        if self.limit:
            return self.limit.depth
        return None

    def update_limit(self, limit: Limit | None):
        """update the limit for the analysis - first check if needed"""
        if self._running:
            self.limit = limit  # None is also OK here
        else:
            logger.debug("%s not running - cannot update", self.whoami)

    def stop(self):
        """Stops the continuous analysis - in a nice way
        it lets infinite analyser stop by itself"""
        if self._running:
            self._running = False  # causes infinite analysis loop to send stop to engine
            logging.debug("%s asking to stop running", self.whoami)

    def cancel(self):
        """force the analyser to stop by cancelling the async task"""
        if self._running:
            if self._task is not None:
                logger.debug("%s cancelling by killing task", self.whoami)
                self._task.cancel()
                self._task = None
                self._running = False
            else:
                logger.debug("ContinousAnalyser strange - running but task is none")

    def get_fen(self) -> str:
        """return the fen the analysis is based on"""
        return self.current_game.fen() if self.current_game else ""

    async def get_analysis(self) -> dict:
        """:return: deepcopied first low and latest best lists of InfoDict
        key 'low': first low limited shallow list of InfoDict (multipv)
        key 'best': a deep list of InfoDict (multipv)
        """
        # due to the nature of the async analysis update it
        # continues to update it all the time, deepcopy needed
        async with self.lock:
            result = {
                "info": copy.deepcopy(self._analysis_data),
                "fen": copy.deepcopy(self.current_game.fen()),
                "game": self.current_game_id,
            }
            return result

    async def update_game(self, new_game: chess.Board):
        """Updates the position for analysis. The game id is still the same"""
        async with self.lock:
            self.game = new_game.copy()  # remember this game position
            self.limit_reached = False  # True when limit reached for position
            # dont reset self._analysis_data to None
            # let the main loop self._analyze_position manage it

    def is_running(self) -> bool:
        """
        Checks if the analysis is running.

        :return: True if analysis is running, otherwise False.
        """
        return self._running

    def get_current_game(self) -> Optional[chess.Board]:
        """
        Retrieves the current board being analyzed.

        :return: A copy of the current chess board or None if no board is set.
        """
        return self.current_game.copy() if self.current_game else None


# Issue 109 - new class to get engine moves from uci engine
# by using analysis() instead of play() calls to the engine
# The idea is to have a sister class to ContinuousAnalysis
# ContinuousAnalysis is used for only analysing positions, not playing
# This UciEngine class can be used for playing and getting info while engine is thinking
class PlayingContinuousAnalysis:
    """Lightweight async engine handler for timed searches (play-like)."""

    def __init__(
        self,
        engine: UciProtocol,
        loop: asyncio.AbstractEventLoop,
        engine_lease: EngineLease,
        engine_debug_name: str,
        allow_info_loop: bool = True,
    ):
        self.engine = engine
        self.loop = loop
        self.latest_info = {}
        self.latest_fen: str = ""
        self._waiting = False
        self._task: asyncio.Task | None = None
        self._force_event = asyncio.Event()
        self._cancel_event = asyncio.Event()
        self.whoami = f"{engine_debug_name} (playing)"
        self.engine_lease = engine_lease
        self.allow_info_loop = allow_info_loop
        self.set_game_id(1)

    def set_game_id(self, game_id: int):
        """Set the current game identifier."""
        self.game_id = game_id

    def set_allow_info_loop(self, allow: bool):
        """Toggle whether analysis() info loop should run."""
        self.allow_info_loop = allow

    async def play_move(
        self,
        game: chess.Board,
        limit: Limit,
        ponder: bool,
        result_queue: asyncio.Queue,
        root_moves=None,
    ):
        """Start engine move search. Ends automatically on bestmove."""
        self._waiting = True
        self.latest_info = {}
        self.latest_fen = ""
        self._force_event.clear()
        self._cancel_event.clear()

        async def _engine_task():
            lease_acquired = False
            # Capture the outcome so we can release `_waiting` and the lease
            # before the consumer sees a result.
            should_queue = False
            queue_payload: PlayResult | None = None
            try:
                await self.engine_lease.acquire(owner="playing", preempt=True)
                lease_acquired = True
                self.latest_fen = game.fen()
                best_move = None
                ponder_move = None
                info_snapshot: InfoDict | None = None

                if self.allow_info_loop:
                    analysis = await self.engine.analysis(
                        board=copy.deepcopy(game),
                        limit=limit,
                        game=self.game_id,
                        root_moves=root_moves,
                        info=chess.engine.INFO_ALL,
                    )

                    async for info in analysis:
                        self.latest_info = info
                        if self._force_event.is_set() or self._cancel_event.is_set():
                            analysis.stop()
                            break

                    # Ensure the search is halted even if no info loop iterations ran
                    try:
                        analysis.stop()
                    except Exception:
                        pass

                    try:
                        best = await analysis.wait()
                        if best:
                            best_move = best.move
                            ponder_move = best.ponder
                    except CancelledError:
                        raise
                    except Exception:
                        logger.debug("%s analysis.wait() failed to provide best move", self.whoami)

                    info_snapshot = copy.deepcopy(analysis.info)
                else:
                    play_response = await self.engine.play(
                        board=copy.deepcopy(game),
                        limit=limit,
                        game=self.game_id,
                        ponder=ponder,
                        root_moves=root_moves,
                        info=chess.engine.INFO_ALL,
                    )
                    if play_response:
                        best_move = play_response.move
                        ponder_move = play_response.ponder
                        self.latest_info = play_response.info or {}
                        info_snapshot = copy.deepcopy(play_response.info)

                if self._cancel_event.is_set():
                    should_queue = True
                    queue_payload = None
                else:
                    play_result = PlayResult(
                        move=best_move,
                        ponder=ponder_move,
                        info=info_snapshot,
                    )
                    play_result.analysed_fen = self.latest_fen
                    should_queue = True
                    queue_payload = play_result

            except CancelledError:
                should_queue = True
                queue_payload = None
                raise
            except (EngineTerminatedError, chess.engine.EngineError):
                logger.warning("%s engine terminated during play_move", self.whoami)
                should_queue = True
                queue_payload = None
            except Exception as e:
                logger.exception("%s unexpected error during play_move: %s", self.whoami, e)
                should_queue = True
                queue_payload = None
            finally:
                self._waiting = False
                if lease_acquired:
                    self.engine_lease.release("playing")
                    lease_acquired = False
                if should_queue:
                    await result_queue.put(queue_payload)

        self._task = self.loop.create_task(_engine_task())

    async def get_analysis(self) -> dict:
        """Return latest info dict (safe to call even if not waiting)."""
        if self._waiting:
            return {"info": self.latest_info, "fen": self.latest_fen}
        return {"info": {}, "fen": ""}

    def force(self):
        """Ask the engine to stop thinking and return a bestmove as soon as possible."""
        if self._waiting:
            self._force_event.set()
            if hasattr(self.engine, "send_line"):
                self.engine.send_line("stop")

    def cancel(self):
        """Cancel any ongoing search (e.g., engine shutdown)."""
        self._cancel_event.set()
        self._force_event.set()
        if hasattr(self.engine, "send_line"):
            self.engine.send_line("stop")

    def is_waiting_for_move(self) -> bool:
        """True if engine is currently thinking about a move."""
        return self._waiting

    async def wait_until_idle(self, timeout: float | None = None) -> bool:
        """
        Wait until the playing loop is idle.

        :return: True if the engine stopped thinking before the timeout.
        """
        if not self._waiting:
            return True

        if timeout is None or timeout <= 0:
            while self._waiting:
                await asyncio.sleep(0.05)
            return True

        deadline = self.loop.time() + timeout
        while self._waiting:
            remaining = deadline - self.loop.time()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(0.05, remaining))
        return True

    def abort(self):
        """Hard-cancel the current playing task (used when force fails)."""
        if self._task and not self._task.done():
            self._task.cancel()


class UciEngine(object):
    """Handle the uci engine communication."""

    # The rewrite for the new python chess module:
    # This UciEngine class can be in two modes:
    # WATCHING = user plays both sides
    # - an analysis generator to ask latest info is running
    #   in this mode you can send multipv larger than zero
    #   which is what the PicoTutor instance will do
    #   in PicoTutor the PicoTutor engine is not playing
    #   its just watching
    # PLAYING = user plays against computer
    # - self.res is no longer used
    # - self.pondering indicates if engine is to ponder
    #   without pondering analysis will be "static" one-timer

    def __init__(
        self,
        file: str,
        uci_shell: UciShell,
        mame_par: str,
        loop: asyncio.AbstractEventLoop,
        engine_debug_name: str = "engine",
    ):
        """initialise engine with file and mame_par info"""
        super(UciEngine, self).__init__()
        logger.info("mame parameters=%s", mame_par)
        self.pondering = False  # normal mode no pondering
        self.loop = loop  # main loop everywhere
        self.analyser: ContinuousAnalysis | None = None
        self.playing: PlayingContinuousAnalysis | None = None
        # previous existing attributes:
        self.is_adaptive = False
        self.engine_rating = -1
        self.uci_elo_eval_fn = None  # saved UCI_Elo eval function
        self.file = file
        self.mame_par = mame_par
        self.is_mame = "/mame/" in self.file
        self.is_script = "/script/" in self.file
        self.legacy_analysis_mode = False
        self.transport = None  # find out correct type
        self.engine: UciProtocol | None = None
        self.engine_name = "NN"
        self.options: dict = {}
        self.res: PlayResult = None
        self.level_support = False
        self.shell = None  # check if uci files can be used any more
        self.whoami = engine_debug_name
        self.engine_lock = asyncio.Lock()
        self.engine_lease: EngineLease | None = None
        self.game_id = 1

    async def open_engine(self):
        """Open engine. Call after __init__"""
        try:
            logger.info("file %s", self.file)
            if self.is_mame:
                mfile = [self.file, self.mame_par]
            else:
                mfile = [self.file]
            logger.info("mfile %s", mfile)
            logger.info("opening engine")
            self.transport, self.engine = await chess.engine.popen_uci(mfile)
            # Instantiate the two “sisters”
            self.engine_lease = EngineLease()
            self.analyser = ContinuousAnalysis(
                engine=self.engine,
                delay=FLOAT_ANALYSIS_WAIT,
                loop=self.loop,
                engine_debug_name=self.whoami,
                engine_lease=self.engine_lease,
            )
            self.playing = PlayingContinuousAnalysis(
                engine=self.engine,
                loop=self.loop,
                engine_lease=self.engine_lease,
                engine_debug_name=self.whoami,
                allow_info_loop=not self._should_disable_info_loop(),
            )
            self.analyser.set_game_id(self.game_id)
            self.playing.set_game_id(self.game_id)
            if self.engine:
                if "name" in self.engine.id:
                    self.engine_name = self.engine.id["name"]
            else:
                logger.error("engine executable %s not found", self.file)
        except OSError:
            logger.exception("OS error in starting engine %s", self.file)
            self.transport = None
            self.engine = None
        except TypeError:
            logger.exception("engine executable not found %s", self.file)
            self.transport = None
            self.engine = None
        except chess.engine.EngineTerminatedError:
            logger.exception("engine terminated - could not execute file %s", self.file)
            self.transport = None
            self.engine = None

    async def reopen_engine(self) -> bool:
        """Re-open engine. Return True if engine re-opened ok."""
        try:
            # @todo - might need to do more here to make sure both "sisters" are ok
            # in this situation the engine is not responding properly and is assumed dead
            # part 1 : call quit or copy specialized code here
            await self.quit()
            # part 2 : copied from open_engine
            logger.info("file %s", self.file)
            if self.is_mame:
                mfile = [self.file, self.mame_par]
            else:
                mfile = [self.file]
            logger.info("re-opening engine %s", mfile)
            self.transport, self.engine = await chess.engine.popen_uci(mfile)
            # Dont instantiate the two “sisters” - they already exist, but update engine
            if self.analyser:
                self.analyser.engine = self.engine
            if self.playing:
                self.playing.engine = self.engine
            # game id remains the same
            if self.engine:
                if "name" in self.engine.id:
                    self.engine_name = self.engine.id["name"]
                    await self.send()
                    return True  # we have an engine that states its name
        except OSError:
            logger.exception("OS error in starting engine %s", self.file)
            self.transport = None
            self.engine = None
        except TypeError:
            logger.exception("engine executable not found %s", self.file)
            self.transport = None
            self.engine = None
        except chess.engine.EngineTerminatedError:
            logger.exception("engine terminated - could not execute file %s", self.file)
            self.transport = None
            self.engine = None
        return False

    def loaded_ok(self) -> bool:
        """check if engine was loaded ok"""
        return self.engine is not None

    def get_name(self) -> str:
        """Get engine name that was reported by engine"""
        return self.engine_name

    def is_mame_engine(self) -> bool:
        """Return True if this engine runs through the MAME/MESS emulation layer."""
        return self.is_mame

    def is_script_engine(self) -> bool:
        """Return True if this engine is provided via a script wrapper."""
        return self.is_script

    def is_legacy_engine(self) -> bool:
        """Return True if this engine requested legacy analysis handling via config."""
        return self.legacy_analysis_mode

    def should_skip_engine_analyser(self) -> bool:
        """Return True if PicoChess should avoid running the engine analyser."""
        return self.is_mame or self.is_script or self.legacy_analysis_mode

    def _should_disable_info_loop(self) -> bool:
        """Return True if PlayingContinuousAnalysis must avoid analysis() info loops."""
        return self.is_mame or self.legacy_analysis_mode

    def _apply_playing_mode_policy(self):
        """Ensure PlayingContinuousAnalysis matches the current info-loop policy."""
        if self.playing:
            self.playing.set_allow_info_loop(not self._should_disable_info_loop())

    def get_options(self):
        """Get engine options."""
        return self.engine.options if self.engine else {}

    def get_pgn_options(self):
        """Get options."""
        return self.options

    def option(self, name: str, value):
        """Set OptionName with value."""
        self.options[name] = value

    def filter_options(self, wanted: dict, allowed: dict) -> dict:
        """
        Return a new dict containing only the keys from `wanted`
        that are present in `allowed`.
        """
        return {k: v for k, v in wanted.items() if k in allowed}

    async def send(self):
        """Send options to engine."""
        if not self.engine:
            logger.warning("send called but no engine is loaded")
            return
        try:
            # issue 85 - remove options not allowed by engine before sending
            options = self.filter_options(self.options, self.engine.options)
            await self.engine.configure(options)
            try:
                await self.engine.ping()  # send isready and wait for answer
            except CancelledError:
                logger.debug("ping isready cancelled - we are probably closing down")
        except chess.engine.EngineError as e:
            logger.warning(e)

    def has_levels(self):
        """Return engine level support."""
        has_lv = self.has_skill_level() or self.has_handicap_level() or self.has_limit_strength() or self.has_strength()
        return self.level_support or has_lv

    def has_skill_level(self):
        """Return engine skill level support."""
        return bool(self.engine and "Skill Level" in self.engine.options)

    def has_handicap_level(self):
        """Return engine handicap level support."""
        return bool(self.engine and "Handicap Level" in self.engine.options)

    def has_limit_strength(self):
        """Return engine limit strength support."""
        return bool(self.engine and "UCI_LimitStrength" in self.engine.options)

    def has_strength(self):
        """Return engine strength support."""
        return bool(self.engine and "Strength" in self.engine.options)

    def has_chess960(self):
        """Return chess960 support."""
        return bool(self.engine and "UCI_Chess960" in self.engine.options)

    def has_ponder(self):
        """Return ponder support."""
        return bool(self.engine and "Ponder" in self.engine.options)

    def get_file(self):
        """Get File."""
        return self.file

    async def quit(self):
        """Quit engine."""
        if self.analyser and self.analyser.is_running():
            self.analyser.cancel()  # quit can force full cancel
        if self.playing and self.playing.is_waiting_for_move():
            self.playing.cancel()  # quit can force full cancel
        if self.is_mame:
            os.system("sudo pkill -9 -f mess")  # RR - MAME sometimes refuses to exit
        else:
            await self._shutdown_standard_engine()
        await asyncio.sleep(1)  # give it some time to quit

    async def _shutdown_standard_engine(self) -> None:
        """Attempt a graceful shutdown and escalate if the engine ignores us."""
        if not self.engine and not self.transport:
            return

        graceful = False
        if self.engine:
            try:
                await asyncio.wait_for(self.engine.quit(), timeout=ENGINE_QUIT_TIMEOUT)
                graceful = True
            except CancelledError:
                raise
            except EngineTerminatedError:
                graceful = True
            except asyncio.TimeoutError:
                logger.warning(
                    "%s engine failed to quit within %.1fs - terminating",
                    self.engine_name,
                    ENGINE_QUIT_TIMEOUT,
                )
            except Exception:
                logger.exception("error while shutting down %s", self.engine_name)

        if not graceful:
            await self._force_kill_transport()
        else:
            await self._wait_for_transport_exit(ENGINE_TERMINATE_TIMEOUT)

        if self.transport:
            try:
                self.transport.close()
            except Exception:
                logger.debug("transport close failed for %s", self.engine_name, exc_info=True)
        self.transport = None
        self.engine = None

    async def _force_kill_transport(self) -> None:
        """Send terminate/kill signals if the engine process ignores quit."""
        if not self.transport:
            return

        if not await self._terminate_and_wait():
            logger.warning("%s engine still running - killing process", self.engine_name)
            try:
                self.transport.kill()
            except ProcessLookupError:
                pass
            except Exception:
                logger.debug("transport kill failed for %s", self.engine_name, exc_info=True)
            await self._wait_for_transport_exit(ENGINE_KILL_TIMEOUT)

    async def _terminate_and_wait(self) -> bool:
        """Send SIGTERM and wait for the engine to exit."""
        if not self.transport or self._transport_exited():
            return True
        try:
            self.transport.terminate()
        except ProcessLookupError:
            return True
        except Exception:
            logger.debug("transport terminate failed for %s", self.engine_name, exc_info=True)
        return await self._wait_for_transport_exit(ENGINE_TERMINATE_TIMEOUT)

    async def _wait_for_transport_exit(self, timeout: float) -> bool:
        """Wait until the current transport exits or timeout elapses."""
        if self._transport_exited():
            return True
        if not self.transport or timeout <= 0:
            return False
        deadline = self.loop.time() + timeout
        while not self._transport_exited():
            remaining = deadline - self.loop.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(0.1, remaining))
        return self._transport_exited()

    def _transport_exited(self) -> bool:
        """Return True if there is no transport or it already exited."""
        if not self.transport:
            return True
        try:
            get_returncode = getattr(self.transport, "get_returncode", None)
            if not get_returncode:
                return True
            return get_returncode() is not None
        except Exception:
            logger.debug("could not read returncode for %s", self.engine_name, exc_info=True)
            return True

    def stop(self):
        """Stop background ContinuousAnalyser and/or force engine to move"""
        self.stop_analysis()
        if not self.is_waiting():
            self.force_move()

    def stop_analysis(self):
        """Stop background ContinuousAnalyser"""
        if self.analyser and self.analyser.is_running():
            self.analyser.cancel()  # @todo - find out why we need cancel and not stop

    def force_move(self, timeout: float = 2.0):
        """
        Force engine to move by issuing a stop and, if needed, cancelling a hung search.

        :param timeout: Seconds to wait for the engine to comply before treating it as hung.
        """
        if not self.engine or not self.playing:
            return

        if not self.playing.is_waiting_for_move():
            return

        logger.debug("forcing engine to make a move")
        # new chess lib does not have a stop call
        # issue 109 - use PlayingContinuousAnalysis force
        self.playing.force()

        if timeout and timeout > 0:
            self.loop.create_task(self._monitor_force_completion(timeout))

    async def _monitor_force_completion(self, timeout: float):
        """Wait for force() to finish, cancelling the search if it hangs."""
        try:
            if not self.playing:
                return
            finished = await self.playing.wait_until_idle(timeout)
            if finished:
                return
            logger.warning("force move timed out after %.1fs - cancelling hung engine", timeout)
            self.playing.cancel()
            self.playing.abort()
        except Exception:
            logger.exception("force move watchdog failed")

    def pause_pgn_audio(self):
        """Stop engine."""
        logger.info("pause audio old")
        # this is especially for pgn_engine
        if self.engine and hasattr(self.engine, "send_line"):
            self.engine.send_line("stop")

    def get_engine_limit(self, time_dict: dict) -> Limit:
        """convert time_dict to engine Limit for engine go command"""
        max_time = None
        try:
            logger.debug("molli: timedict: %s", str(time_dict))
            if "movestogo" in time_dict:
                moves = int(time_dict["movestogo"])
            else:
                moves = None
            if "wtime" in time_dict:
                white_t = float(time_dict["wtime"]) / 1000.0
            elif "movetime" in time_dict:
                # send max_time to search exactly N seconds
                white_t = None
                max_time = float(time_dict["movetime"]) / 1000.0
            else:
                white_t = None
                logger.debug("not sending white time to engine")
            if "btime" in time_dict:
                black_t = float(time_dict["btime"]) / 1000.0
            elif "movetime" in time_dict:
                # send max_time to search exactly N seconds
                black_t = None
                max_time = float(time_dict["movetime"]) / 1000.0
            else:
                black_t = None
                logger.warning("not sending black time to engine")
            white_inc = float(time_dict["winc"]) / 1000.0 if "winc" in time_dict else None
            black_inc = float(time_dict["binc"]) / 1000.0 if "binc" in time_dict else None
        except ValueError as e:
            logger.warning("wrong time control values %s", e)
            white_t = black_t = None
            white_inc = black_inc = 0
        use_time = Limit(
            time=max_time,
            white_clock=white_t,
            black_clock=black_t,
            white_inc=white_inc,
            black_inc=black_inc,
            remaining_moves=moves,
        )
        return use_time

    def get_engine_uci_options(self, time_dict: dict, limit: Limit):
        """add possible engine restrictions PicoDepth and PicoNode from uci options
        - ini file or user set values can be in input parameter time_dict
        - Result: add nodes and depth to the input parameter limit"""
        # issue #87 set Node and Depth restrictions for go
        # engine uci options in self.options have priority over time_dict
        # Node/Depth is a pair - take both from same priority source
        # this guarantees that we dont mix ini and uci file settings
        if "PicoNode" in self.options or "PicoDepth" in self.options:
            if "PicoDepth" in self.options and int(self.options["PicoDepth"]) > 0:
                limit.depth = int(self.options["PicoDepth"])
            # its allowed to send both uci Depth and Node to engine
            if "PicoNode" in self.options and int(self.options["PicoNode"]) > 0:
                limit.nodes = int(self.options["PicoNode"])
        else:
            if "depth" in time_dict and int(time_dict["depth"]) > 0:
                limit.depth = int(time_dict["depth"])
            # picochess will not send both, but prepare for future
            # not doing elif here like picochess - just if
            if "node" in time_dict and int(time_dict["node"]) > 0:
                limit.nodes = int(time_dict["node"])

    def drop_engine_uci_option(self, option: str):
        """drop an engine uci dummy option from self.options"""
        # user can override PicoDepth/PicoNode by dropping uci option
        # see priorities in get_engine_uci_opitons above
        if option in self.options:
            del self.options[option]
        logger.debug("user dropped dummyengine uci option %s", option)

    async def go(
        self,
        time_dict: dict,
        game: Board,
        result_queue: asyncio.Queue,
        root_moves: Optional[Iterable[chess.Move]],
        expected_turn: chess.Color | None = None,
    ) -> None:
        """Go engine.
        parameter game will not change, it is deep copied"""
        if not self.engine:
            logger.error("go called but no engine loaded")
            return

        if not self.playing:
            logger.warning("go called but playing engine not initialised yet")
            return

        async with self.engine_lock:
            if expected_turn is not None and game.turn != expected_turn:
                logger.warning(
                    "%s go() called with mismatching turn: board turn=%s expected=%s",
                    self.whoami,
                    game.turn,
                    expected_turn,
                )
            limit: Limit = self.get_engine_limit(time_dict)  # time restrictions
            self.get_engine_uci_options(time_dict, limit)  # possibly restrict Node/Depth
            await self.playing.play_move(
                game, limit=limit, ponder=self.pondering, result_queue=result_queue, root_moves=root_moves
            )

    async def start_analysis(self, game: chess.Board, limit: Limit | None = None, multipv: int | None = None) -> bool:
        """start analyser - returns True if if it was already running
        in current game position, which means result can be expected

        parameters:
        game: the game position to be analysed
        limit: limit for analysis - None means forever
        multipv: multipv for analysis - None means 1"""
        result = False
        if self.analyser and self.analyser.is_running():
            if limit and limit.depth != self.analyser.get_limit_depth():
                logger.debug("%s picotutor limit change: %d- mode/engine switch?", self.whoami, limit.depth)
                self.analyser.update_limit(limit)
            if game.fen() != self.analyser.get_fen():
                await self.analyser.update_game(game)  # new position
                logger.debug("%s new analysis position", self.whoami)
            else:
                result = True  # was running - results to be expected
                # logger.debug("continue with old analysis position")
        else:
            if self.engine:
                async with self.engine_lock:
                    if not self.playing:
                        logger.debug("%s cannot start analysis - playing engine not initialised", self.whoami)
                    elif not self.playing.is_waiting_for_move():
                        self.analyser.start(game, limit=limit, multipv=multipv)
                    else:
                        # issue 109 - it is not allowed to start the analyser sister if playing is running
                        logger.debug("%s cannot start analysis - engine is thinking", self.whoami)
            else:
                logger.warning("start analysis requested but no engine loaded")
        return result

    def is_analyser_running(self) -> bool:
        """check if analyser is running"""
        return self.analyser and self.analyser.is_running()

    async def get_thinking_analysis(self, game: chess.Board) -> dict:
        """get analysis info from playing engine - returns dict with info and fen"""
        # failed answer is empty lists
        result = {"info": [], "fen": ""}
        if self.playing and self.playing.is_waiting_for_move():
            latest = await self.playing.get_analysis()
            info_dict = latest.get("info") if latest else {}
            analysed_fen = latest.get("fen") if latest else ""
            if info_dict:
                result = {"info": [info_dict], "fen": analysed_fen or game.fen(), "game": None}
            else:
                result = {"info": [], "fen": analysed_fen or game.fen(), "game": None}
        else:
            logger.debug("get_thinking_analysis called but engine not thinking or playing engine missing")
        return result

    async def get_analysis(self, game: chess.Board) -> dict:
        """get analysis info from engine - returns dict with info and fen
        key 'info': list of InfoDict (multipv)
        key 'fen': analysed board position fen"""
        # failed answer is empty lists
        result = {"info": [], "fen": ""}
        if self.analyser and self.analyser.is_running():
            if self.analyser.get_fen() == game.fen():
                result = await self.analyser.get_analysis()
            else:
                logger.debug("analysis for old position")
                logger.debug("current new position is %s", game.fen())
        else:
            logger.debug("caller has forgot to start analysis")
        return result

    def is_analysis_limit_reached(self) -> bool:
        """return True if limit was reached for position being analysed"""
        if self.analyser and self.analyser.is_running():
            return self.analyser.is_limit_reached()
        return False

    async def get_latest_seen_depth(self) -> int:
        """return the latest depth seen in analysis info"""
        result = 0
        if self.analyser and self.analyser.is_running():
            result = await self.analyser.get_latest_seen_depth()
        else:
            # this is the famous - this should not happen log
            logger.debug("get_latest_seen_depth from engine but analyser not running")
        return result

    def is_thinking(self):
        """Engine thinking."""
        # as of issue 109 we have to check the playing sister
        return bool(self.playing and self.playing.is_waiting_for_move())

    def is_pondering(self):
        """Engine pondering."""
        # in the new chess module we are possibly idle
        # but have to inform picochess.py that we could
        # be pondering anyway
        return self.pondering

    def is_waiting(self):
        """Engine waiting."""
        # as of issue 109 we have to check the playing sister
        # @todo - check if all calls from picochess.py is really needed any more
        if self.playing:
            return not self.playing.is_waiting_for_move()
        return True

    def is_ready(self):
        """Engine waiting."""
        return True  # should not be needed any more

    async def newgame(self, game: Board, send_ucinewgame: bool = True):
        """Engine sometimes need this to setup internal values.
        parameter game will not change"""
        if self.engine:
            async with self.engine_lock:
                # as seen in issue #78 need to prevent simultaneous newgame and start analysis
                self.game_id += 1
                if self.analyser:
                    self.analyser.set_game_id(self.game_id)  # chess lib signals ucinewgame in next call to engine
                    await self.analyser.update_game(game)  # analysing sister starts from new game
                if self.playing:
                    self.playing.set_game_id(self.game_id)  # chess lib signals ucinewgame in next call to engine
                    self.playing.cancel()  # cancel any ongoing playing sister
                await asyncio.sleep(0.3)  # wait for analyser to stop
                # @todo we could wait for ping() isready here - but it could break pgn_engine logic
                # do not self.engine.send_line("ucinewgame"), see read_pgn_file in picochess.py
                # it will confuse the engine when switching between playing/non-playing modes
                # but: issue #72 at least mame engines need ucinewgame to be sent
                # we force it here and to avoid breaking read_pgn_file I added a default parameter
                # due to errors with readyok response crash issue #78 restrict to mame
                if (self.is_mame or "PGN Replay" in self.engine_name) and send_ucinewgame:
                    # most calls except read_pgn_file newgame, and load new engine
                    logger.debug("sending ucinewgame to engine")
                    self.engine.send_line("ucinewgame")  # force ucinewgame to engine
        else:
            logger.error("newgame requested but no engine loaded")

    def set_mode(self, ponder: bool = True):
        """Set engine ponder mode for a playing engine"""
        self.pondering = ponder  # True in BRAIN mode = Ponder On menu

    async def startup(self, options: dict, rating: Optional[Rating] = None):
        """Startup engine."""
        parser = configparser.ConfigParser()

        if not options:
            if self.shell is None:
                success = bool(parser.read(self.get_file() + ".uci"))
            else:
                try:
                    with self.shell.open(self.get_file() + ".uci", "r") as file:
                        parser.read_file(file)
                    success = True
                except FileNotFoundError:
                    success = False
            if success:
                options = dict(parser[parser.sections().pop()])

        self.level_support = bool(options)

        self.options = options.copy()
        analysis_option = None
        if "Analysis" in self.options:
            analysis_option = self.options["Analysis"]
            del self.options["Analysis"]
        allow_analysis = self._parse_bool_flag(analysis_option) if analysis_option is not None else True
        self.legacy_analysis_mode = not allow_analysis
        self._engine_rating(rating)
        logger.debug("setting engine with options %s", self.options)
        await self.send()
        self._apply_playing_mode_policy()

        logger.debug("Loaded engine [%s]", self.get_name())
        logger.debug("Supported options [%s]", self.get_options())

    @staticmethod
    def _parse_bool_flag(value) -> bool:
        """Interpret PicoChess-specific boolean flags."""
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in ("1", "true", "yes", "on", "y")

    def _engine_rating(self, rating: Optional[Rating] = None):
        """
        Set engine_rating; replace UCI_Elo 'auto' value with rating.
        Delete UCI_Elo from the options if no rating is given.
        """
        uci_elo_option_string = None
        if UCI_ELO in self.options:
            uci_elo_option_string = UCI_ELO
        elif UCI_ELO_NON_STANDARD in self.options:
            uci_elo_option_string = UCI_ELO_NON_STANDARD
        elif UCI_ELO_NON_STANDARD2 in self.options:
            uci_elo_option_string = UCI_ELO_NON_STANDARD2
        if uci_elo_option_string is not None:
            uci_elo_option = self.options[uci_elo_option_string].strip()
            if uci_elo_option.lower() == "auto" and rating is not None:
                self._set_rating(self._round_engine_rating(int(rating.rating)))
            elif uci_elo_option.isnumeric():
                self.engine_rating = int(uci_elo_option)
            elif "auto" in uci_elo_option and rating is not None:
                uci_elo_with_rating = uci_elo_option.replace("auto", str(int(rating.rating)))
                try:
                    evaluated = eval(uci_elo_with_rating)
                    if str(evaluated).isnumeric():
                        self._set_rating(int(evaluated))
                        self.uci_elo_eval_fn = uci_elo_option  # save evaluation function for updating engine ELO later
                    else:
                        del self.options[uci_elo_option_string]
                except Exception as e:  # noqa - catch all exceptions for eval()
                    logger.error(f"invalid option set for {uci_elo_option_string}={uci_elo_with_rating}, exception={e}")
                    del self.options[uci_elo_option_string]
            else:
                del self.options[uci_elo_option_string]

    def _set_rating(self, value: int):
        self.engine_rating = value
        self._set_uci_elo_to_engine_rating()
        self.is_adaptive = True

    def _round_engine_rating(self, value: int) -> int:
        """Round the value up to the next 50, minimum=500"""
        return max(500, int(value / 50 + 1) * 50)

    async def update_rating(self, rating: Rating, result: Result) -> Rating:
        """Send the new ELO value to the engine and save the ELO and rating deviation"""
        if not self.is_adaptive or result is None or self.engine_rating < 0:
            return rating
        new_rating = rating.rate(Rating(self.engine_rating, 0), result)
        if self.uci_elo_eval_fn is not None:
            # evaluation function instead of auto?
            self.engine_rating = eval(self.uci_elo_eval_fn.replace("auto", str(int(new_rating.rating))))
        else:
            self.engine_rating = self._round_engine_rating(int(new_rating.rating))
        self._save_rating(new_rating)
        self._set_uci_elo_to_engine_rating()
        await self.send()
        return new_rating

    def _set_uci_elo_to_engine_rating(self):
        if UCI_ELO in self.options:
            self.options[UCI_ELO] = str(int(self.engine_rating))
        elif UCI_ELO_NON_STANDARD in self.options:
            self.options[UCI_ELO_NON_STANDARD] = str(int(self.engine_rating))
        elif UCI_ELO_NON_STANDARD2 in self.options:
            self.options[UCI_ELO_NON_STANDARD2] = str(int(self.engine_rating))

    def _save_rating(self, new_rating: Rating):
        write_picochess_ini("pgn-elo", max(500, int(new_rating.rating)))
        write_picochess_ini("rating-deviation", int(new_rating.rating_deviation))

    async def handle_bestmove_0000(self, game: chess.Board, timeout: float = 2.0) -> str:
        """
        Handle 'bestmove 0000' from a UCI engine using python-chess UciProtocol.

        Returns PGN-style result strings:
            "1-0"       → White wins (Black checkmated or resigned)
            "0-1"       → Black wins (White checkmated or resigned)
            "1/2-1/2"   → Stalemate or draw
            "*"         → Engine dead/unresponsive (game not yet decided)
        """

        # --- Phase 1: Legitimate terminal states ---
        if game.is_checkmate():
            return "0-1" if game.turn == chess.WHITE else "1-0"

        if (
            game.is_stalemate()
            or game.is_insufficient_material()
            or game.is_seventyfive_moves()
            or game.is_fivefold_repetition()
        ):
            return "1/2-1/2"

        # --- Phase 2: No legal reason for 0000 → probe engine health ---
        try:
            if not self.engine:
                raise chess.engine.EngineTerminatedError("engine not available")
            await asyncio.wait_for(self.engine.ping(), timeout=timeout)
            # Engine alive ⇒ interpret as resignation
            return "0-1" if game.turn == chess.WHITE else "1-0"

        except (asyncio.TimeoutError, chess.engine.EngineTerminatedError, OSError):
            # Engine not responsive ⇒ crashed/hung
            return "*"
        except AssertionError as exc:
            logger.warning("engine ping failed with unexpected state: %s", exc)
            # Engine not responsive ⇒ crashed/hung
            return "*"
