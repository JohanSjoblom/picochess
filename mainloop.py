#!/usr/bin/env python3

# Copyright (C) 2013-2018 Jean-Francois Romang (jromang@posteo.de)
#                         Shivkumar Shivaji ()
#                         Jürgen Précour (LocutusOfPenguin@posteo.de)
#                         Wilhelm
#                         Dirk ("Molli")
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


import sys
import signal
import time
import os
import subprocess
import copy
import gc
import logging
import math
import traceback
from typing import Any
import asyncio
from pathlib import Path

import chess.pgn
from chess.pgn import Game
import chess.polyglot
import chess.engine
import chess.variant
from chess.engine import InfoDict, Limit, PlayResult
import dgt.util

from analysis_policy import (
    AnalysisCycleAction,
    AnalysisCycleContext,
    AnalysisSourceAction,
    AnalysisSourceContext,
    TutorAnalysisContext,
    decide_analysis_cycle_action,
    decide_analysis_source,
    decide_tutor_analysis,
    selected_engine_analysis_multipv,
    should_stop_analysis_after_game_end,
    tutor_analysis_allowed_in_mode,
)
from analysis_depth import depth_gated_analysis_info, selected_engine_analysis_depth
from web_analysis import WebAnalysisSnapshot, web_analysis_payload
from alternative_mover import AlternativeMover
from picostate import PicochessState
from board_position import (
    board_fen_after_move,
    boards_match_position_and_history,
    compare_fen,
    compute_legal_fens,
    previous_position_matching_board_fen,
)
from position_setup import (
    RK_STARTING_BOARD_FEN,
    loaded_pgn_interaction_mode,
    mame_requires_fresh_fen_root,
    pending_set_position_fen_action,
    pgn_with_board_as_fresh_root,
    set_position_new_game_code,
    setup_position_game,
    should_load_pgn_moves,
    should_preserve_loaded_pgn_history,
    should_preserve_set_position_history,
)
from move_policy import (
    analysis_event_matches_position,
    engine_move_event_matches_state,
    remote_move_matches_current_position,
    should_block_takeback,
    should_process_sliding_move,
    should_reject_user_move_after_game_end,
    should_resume_clock_after_rejected_engine_move,
    should_resume_game_after_takeback,
    should_show_setpieces_after_lift_timeout,
    user_move_pre_search_messages,
    user_move_task_matches_position,
)

from uci.engine import UciShell, UciEngine
from uci.engine_provider import EngineProvider
from uci.rating import Rating, determine_result

from timecontrol import TimeControl
from utilities import (
    get_location,
    update_pico_v4,
    update_pico_engines,
    get_opening_books,
    shutdown,
    reboot,
    exit_pico,
    checkout_tag,
    ensure_important_headers,
    keep_essential_headers,
)
from utilities import (
    Observable,
    DisplayMsg,
    version,
    evt_queue,
    write_picochess_ini,
    get_engine_mame_par,
    get_window_command,
    is_wayland_session,
)
from utilities import AsyncRepeatingTimer
from pgn import Emailer, PgnDisplay, ModeInfo, pgn_has_variations, pgn_variation_review_points
from server import EventHandler, clear_preserved_mame_history, publish_preserved_mame_history
from picotalker import PicoTalkerDisplay
from web_history import history_scope
from dispatcher import Dispatcher

from dgt.api import Message, Event
from dgt.util import (
    GameResult,
    TimeMode,
    Mode,
    PlayMode,
    PicoComment,
    PicoCoach,
    flip_board_fen,
    game_result_from_header,
)
from dgt.board import DgtBoard
from eboard.eboard import EBoard
from picotutor import PicoTutor


logger = logging.getLogger("picochess")


FLOAT_MIN_BACKGROUND_TIME = 1.0  # how often to send PV,SCORE,DEPTH


ENGINE_SEARCH_IDLE_TIMEOUT = 3.0


ENGINE_SEARCH_CANCEL_TIMEOUT = 1.0


ENGINE_SHUTDOWN_IDLE_TIMEOUT = 3.0


ONLINE_PREFIX = "Online"


def track_event_task(task: asyncio.Task, event_tasks: set[asyncio.Task]) -> None:
    """Keep an event-handler task alive and consume its result when it finishes."""
    event_tasks.add(task)

    def event_task_done(completed_task: asyncio.Task) -> None:
        event_tasks.discard(completed_task)
        try:
            completed_task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Unhandled exception while processing main event")

    task.add_done_callback(event_task_done)


async def process_queued_event(event, handler, queue: asyncio.Queue) -> None:
    """Process one queued event and complete its queue bookkeeping afterwards."""
    try:
        await handler(event)
    finally:
        queue.task_done()


def should_report_local_timeout(online_mode: bool) -> bool:
    """Report each local flag fall; online servers own their timeout policy."""
    return not online_mode


def log_pgn(state: PicochessState):
    logger.debug("molli pgn: pgn_book_test: %s", str(state.pgn_book_test))
    logger.debug("molli pgn: game turn: %s", state.game.turn)
    logger.debug("molli pgn: max_guess_white: %s", state.max_guess)
    logger.debug("molli pgn: max_guess_white: %s", state.max_guess_white)
    logger.debug("molli pgn: max_guess_black: %s", state.max_guess_black)
    logger.debug("molli pgn: no_guess_white: %s", state.no_guess_white)
    logger.debug("molli pgn: no_guess_black: %s", state.no_guess_black)


def read_online_result():
    result_line = ""
    winner = ""

    try:
        with open("online_game.txt", "r", encoding="utf-8") as log_u:
            lines = log_u.readlines()
            for i, line in enumerate(lines, start=1):
                if i == 9:
                    result_line = line[12:].strip()
                elif i == 10:
                    winner = line[7:].strip()
    except FileNotFoundError:
        logger.error("Could not read online game file: file not found")
    except OSError as e:
        logger.error("Could not read online game file: %s", e)

    return (str(result_line), str(winner))


def read_online_user_info() -> tuple[str, str, str, str, int, int]:
    own_user, opp_user = "unknown", "unknown"
    login, own_color = "failed", ""
    game_time, fischer_inc = 0, 0

    try:
        with open("online_game.txt", "r", encoding="utf-8") as log_u:
            for line in log_u:
                if "=" not in line:
                    continue
                key, value = line.strip().split("=", 1)

                if key == "LOGIN":
                    login = value
                elif key == "COLOR":
                    own_color = value
                elif key == "OWN_USER":
                    own_user = value
                elif key == "OPPONENT_USER":
                    opp_user = value
                elif key == "GAME_TIME":
                    try:
                        game_time = int(value)
                    except ValueError:
                        logger.warning("Invalid GAME_TIME value: %s", value)
                elif key == "FISCHER_INC":
                    try:
                        fischer_inc = int(value)
                    except ValueError:
                        logger.warning("Invalid FISCHER_INC value: %s", value)
    except FileNotFoundError:
        logger.warning("Online game file not found")
    except Exception as e:
        logger.error("Error reading online game file: %s", e)

    logger.debug("online game_time %s fischer_inc: %s", game_time, fischer_inc)
    return login, own_color, own_user, opp_user, game_time, fischer_inc


def mame_history_snapshot_pgn(game_or_board, headers: dict | None = None) -> str:
    """Serialize a game or board for temporary browser history restoration."""
    if isinstance(game_or_board, chess.pgn.Game):
        snapshot_game = copy.deepcopy(game_or_board)
    else:
        snapshot_game = chess.pgn.Game.from_board(game_or_board)
        snapshot_game.headers.update(keep_essential_headers(headers or {}))
    return snapshot_game.accept(
        chess.pgn.StringExporter(headers=True, comments=True, variations=True)
    )


async def rollback_picotutor_for_alternative(picotutor, game: chess.Board, resync) -> bool:
    """Undo the previously posted engine move before requesting an alternative."""
    valid = await picotutor.pop_last_move(game)
    if not valid:
        await resync()
    return valid


class MainLoop:
    """main turned into a class"""

    def __init__(
        self,
        own_user,
        opp_user,
        game_time,
        fischer_inc,
        login,
        state: PicochessState,
        pgn_display: PgnDisplay,
        pico_talker: PicoTalkerDisplay,
        dgtdispatcher: Dispatcher,
        dgtboard: EBoard,
        board_type,
        loop: asyncio.AbstractEventLoop,
        args,
        shared: dict,
        non_main_tasks: set[asyncio.Task],
        shutdown_requested: asyncio.Event,
        shutdown_complete: asyncio.Event,
    ):
        self.loop = loop
        self._task = None  # placeholder for message consumer task
        self.own_user = own_user
        self.opp_user = opp_user
        self.game_time = game_time
        self.fischer_inc = fischer_inc
        self.login = login
        self.state = state
        self.pgn_display = pgn_display
        self.engine = None  # placeholder for UciEngine
        self.state.fen_timer = None  # this and next line could be removed?
        self.state.fen_timer_running = False  # already set in picostate init
        self.args = args
        self.pico_talker = pico_talker
        self.dgtdispatcher = dgtdispatcher
        self.dgtboard = dgtboard
        self.board_type = board_type
        # @todo start background analyser only when new game starts
        self.background_analyse_timer = AsyncRepeatingTimer(
            FLOAT_MIN_BACKGROUND_TIME, self._pv_score_depth_analyser, loop=self.loop
        )
        self.shared = shared
        self.shared.setdefault("system_info", {})["game_started"] = self.state.game_started
        self.non_main_tasks = non_main_tasks
        self.event_tasks: set[asyncio.Task] = set()
        self._board_clock_transition_lock = asyncio.Lock()
        self.shutdown_task: asyncio.Task | None = None
        self.shutdown_requested = shutdown_requested
        self.shutdown_complete = shutdown_complete
        self.update_status = None
        self.git_status = None
        ###########################################

        # Keep the normal startup path untouched unless the configured engine has gone missing.
        self.requested_engine_file = self.args.engine
        self.state.engine_file = self.requested_engine_file
        if self.state.engine_file is None:
            resolved_engine = EngineProvider.resolve_engine(None)
            if resolved_engine is None:
                logger.error("no installed engines available at startup")
                self.state.engine_file = ""
            else:
                self.state.engine_file = resolved_engine["file"]
        elif not EngineProvider.has_engine(self.state.engine_file):
            resolved_engine = EngineProvider.resolve_engine(self.state.engine_file)
            if resolved_engine is None:
                logger.error("no installed engines available at startup")
                self.state.engine_file = self.requested_engine_file or ""
            else:
                self.state.engine_file = resolved_engine["file"]
                logger.warning(
                    "configured engine '%s' not found; starting with '%s'",
                    self.requested_engine_file,
                    self.state.engine_file,
                )

        self.engine_remote_home = self.args.engine_remote_home

        self.uci_local_shell = UciShell(hostname="", username="", key_file="", password="")
        self.uci_remote_shell = None
        if self.args.engine_remote_server:
            self.uci_remote_shell = UciShell(
                hostname=self.args.engine_remote_server,
                username=self.args.engine_remote_user,
                key_file=self.args.engine_remote_key,
                password=self.args.engine_remote_pass,
                remote_home=self.engine_remote_home,
                windows=self.remote_windows(),
            )
        self.tutor_remote_engine = self.args.tutor_remote_engine

        # ensure dgtmenu knows which engine will actually be loaded so the startup
        # announcement reflects the saved configuration
        if self.state.dgtmenu and self.state.engine_file:
            self.state.dgtmenu.set_state_current_engine(self.state.engine_file)

        self.all_books = get_opening_books()
        if not self.all_books:
            logger.error("no opening books available; continuing without book support")
            self.book_index = None
            self.state.book_in_use = ""
            self.bookreader = None
        else:
            try:
                self.book_index = [book["file"] for book in self.all_books].index(args.book)
            except ValueError:
                logger.error("selected book not present, defaulting to %s", self.all_books[0]["file"])
                self.book_index = 0
            self.state.book_in_use = self.all_books[self.book_index]["file"]
            try:
                self.bookreader = chess.polyglot.open_reader(self.all_books[self.book_index]["file"])
            except OSError as exc:
                book_file = self.all_books[self.book_index]["file"]
                logger.warning("failed to open book '%s': %s", book_file, exc)
                self.bookreader = None
                self.state.book_in_use = ""
        self.state.searchmoves = AlternativeMover()
        self.state.artwork_in_use = False

        # Register signal handlers for kill signal
        signal.signal(signal.SIGTERM, self.exit_sigterm)
        signal.signal(signal.SIGINT, self.exit_sigterm)

    async def display_ip_info(self):
        """Fire an IP_INFO message with the IP adr."""
        location, ext_ip, int_ip = get_location()

        if self.state.set_location == "auto":
            pass
        else:
            location = self.state.set_location

        info = {"location": location, "ext_ip": ext_ip, "int_ip": int_ip, "version": version}
        await DisplayMsg.show(Message.IP_INFO(info=info))

    async def initialise(self, time_text):
        """Due to use of async some initialisation is moved here"""

        # issue 106 - get update and git status information for the user
        self.update_status = await asyncio.to_thread(self.get_last_update_status)
        logger.info("Update status: %s", self.update_status)
        # This is shown for a very short time - you can also see it in the menu
        if self.update_status:
            self.state.dgttranslate.set_last_updated_info(self.update_status)
            msg = Message.SHOW_TEXT(text_string=self.update_status)
            await DisplayMsg.show(msg)
        self.git_status = await asyncio.to_thread(self.get_git_status)
        if self.git_status:
            self.state.dgttranslate.set_git_info(self.git_status)

        engine_file_to_load = self.state.engine_file  # assume not mame
        if "/mame/" in self.state.engine_file and self.state.dgtmenu.get_engine_rdisplay():
            engine_file_art = self.state.engine_file + "_art"
            my_file = Path(engine_file_art)
            if my_file.is_file():
                self.state.artwork_in_use = True
                engine_file_to_load = engine_file_art  # load mame

        uci_shell = self.uci_remote_shell if self.remote_engine_mode() and self.uci_remote_shell else self.uci_local_shell

        self.engine = UciEngine(
            file=engine_file_to_load,
            uci_shell=uci_shell,
            mame_par=self.calc_engine_mame_par(),
            loop=self.loop,
        )
        await self.engine.open_engine()
        if engine_file_to_load != self.state.engine_file:
            await asyncio.sleep(1)  # mame artwork wait

        await self.display_ip_info()
        await asyncio.sleep(1.0)

        if not self.engine.loaded_ok():
            logger.error("engine %s not started", self.state.engine_file)
            await asyncio.sleep(3)
            await DisplayMsg.show(Message.ENGINE_FAIL())
            await asyncio.sleep(2)
            sys.exit(-1)

        # Startup - internal
        self.state.game = chess.Board()  # Create the current game
        self.state.legal_fens = compute_legal_fens(self.state.game, self.state.get_variant_board())  # Compute the legal FENs
        self.state.flag_startup = True

        if self.args.pgn_elo and self.args.pgn_elo.isnumeric() and self.args.rating_deviation:
            self.state.rating = Rating(float(self.args.pgn_elo), float(self.args.rating_deviation))
        self.args.engine_level = None if self.args.engine_level == "None" else self.args.engine_level
        if self.args.engine_level == '""':
            self.args.engine_level = None
        engine_opt, level_index = await self.get_engine_level_dict(self.args.engine_level)
        if self.args.engine_level and level_index is None:
            logger.warning(
                "configured engine level '%s' not found for engine '%s'; using engine default",
                self.args.engine_level,
                self.state.engine_file,
            )
            self.args.engine_level = None
        startup_ok = await self.engine.startup(engine_opt, self.state.rating)
        ModeInfo.set_retro_features(self.engine.get_mame_capabilities().retro_info())

        # Initialize variant support from engine settings
        self._init_variant_from_engine()

        if (
            self.emulation_mode()
            and self.state.dgtmenu.get_engine_rdisplay()
            and self.state.artwork_in_use
            and not is_wayland_session()
            and not self.state.dgtmenu.get_engine_rwindow()
        ):
            # Preserve the old X11 fullscreen fallback. Wayland startup mode
            # is controlled by MAME -window/-nowindow parameters.
            cmd = get_window_command("toggle_fullscreen")
            if cmd:
                process = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await process.communicate()

        # Startup - external
        self.state.engine_level = self.args.engine_level
        self.state.old_engine_level = self.state.engine_level
        self.state.new_engine_level = self.state.engine_level

        if self.state.engine_level:
            level_text = self.state.dgttranslate.text("B00_level", self.state.engine_level)
            level_text.beep = False
        else:
            level_text = None
            self.state.engine_level = ""

        if self.args.pgn_user:
            user_name = self.args.pgn_user
        else:
            if self.args.email:
                user_name = self.args.email.split("@")[0]
            else:
                user_name = "Player"
        sys_info = {
            "version": version,
            "engine_name": self.engine.get_name(),
            "is_mame": self.engine.is_mame_engine(),
            "mame_capabilities": self.engine.get_mame_capabilities().as_dict(),
            "retro_info_only": (
                self.engine.get_mame_capabilities().info
                and not self.engine.get_mame_capabilities().position
                and not self.engine.get_mame_capabilities().edit
            ),
            "user_name": user_name,
            "user_elo": self.args.pgn_elo,
            "rspeed": round(float(self.args.rspeed), 2),
        }
        if self.git_status:
            sys_info["git_status"] = self.git_status

        await DisplayMsg.show(Message.SYSTEM_INFO(info=sys_info))
        await DisplayMsg.show(
            Message.STARTUP_INFO(
                info={
                    "interaction_mode": self.state.interaction_mode,
                    "play_mode": self.state.play_mode,
                    "books": self.all_books,
                    "book_index": self.book_index,
                    "level_text": level_text,
                    "level_name": self.state.engine_level,
                    "tc_init": self.state.time_control.get_parameters(),
                    "time_text": time_text,
                }
            )
        )

        # engines setup
        await DisplayMsg.show(
            Message.ENGINE_STARTUP(
                installed_engines=EngineProvider.installed_engines,
                file=self.state.engine_file,
                level_index=level_index,
                has_960=self.engine.has_chess960(),
                has_ponder=self.engine.has_ponder(),
            )
        )
        await DisplayMsg.show(Message.ENGINE_SETUP())
        if startup_ok:
            # Confirm startup after startup announcements to keep spoken order:
            # "picochess", "engine setup", "ok".
            await DisplayMsg.show(Message.PICOCOMMENT(picocomment="ok"))
            await self.show_loaded_mame_capabilities()
        # update_elo_display sends "rspeed", "user_elo", "engine_elo" in SYSTEM_INFO
        await self.update_elo_display()

        # set timecontrol restore data set for normal engines after leaving emulation mode
        pico_time = self.args.def_timectrl

        if self.emulation_mode():
            self.state.flag_last_engine_emu = True
            time_control_l, time_text_l = await self.state.transfer_time(pico_time.split(), depth=0, node=0)
            self.state.tc_init_last = time_control_l.get_parameters()

        if self.pgn_mode():
            ModeInfo.set_pgn_mode(mode=True)
            self.state.flag_last_engine_pgn = True
            await self.det_pgn_guess_tctrl()
        else:
            ModeInfo.set_pgn_mode(mode=False)

        if self.online_mode():
            ModeInfo.set_online_mode(mode=True)
            await self.set_wait_state(self.state.new_game_msg(newgame=True))
        else:
            ModeInfo.set_online_mode(mode=False)
            await self.engine.newgame(self.state.engine_board_copy())

        self.state.comment_file = self.get_comment_file()
        tutor_engine = self.args.tutor_engine
        remote_tutor_override = self.tutor_remote_engine
        # try remote tutor first if configured and remote shell exists
        self.state.picotutor = None
        if remote_tutor_override and self.uci_remote_shell:
            logger.info("using remote tutor engine via ssh: %s", remote_tutor_override)
            self.state.picotutor = PicoTutor(
                i_ucishell=self.uci_remote_shell,
                i_engine_path=tutor_engine,
                i_comment_file=self.state.comment_file,
                i_lang=self.args.language,
                loop=self.loop,
                remote_binary_override=remote_tutor_override,
            )
            await self.state.picotutor.set_analysis_enabled(
                tutor_analysis_allowed_in_mode(self.state.interaction_mode)
            )
            await self.state.picotutor.set_status(
                self.state.dgtmenu.get_picowatcher(),
                self.state.dgtmenu.get_picocoach(),
                self.state.dgtmenu.get_picoexplorer(),
                self.state.dgtmenu.get_picocomment(),
            )
            await self.state.picotutor.open_engine()
            # fallback if remote tutor failed to load
            if not self.state.picotutor.best_engine or not self.state.picotutor.obvious_engine:
                logger.warning("remote tutor failed to start - falling back to local tutor")
                self.state.picotutor = None

        if not self.state.picotutor:
            self.state.picotutor = PicoTutor(
                i_ucishell=self.uci_local_shell,
                i_engine_path=tutor_engine,
                i_comment_file=self.state.comment_file,
                i_lang=self.args.language,
                loop=self.loop,
            )
            await self.state.picotutor.set_analysis_enabled(
                tutor_analysis_allowed_in_mode(self.state.interaction_mode)
            )
            await self.state.picotutor.set_status(
                self.state.dgtmenu.get_picowatcher(),
                self.state.dgtmenu.get_picocoach(),
                self.state.dgtmenu.get_picoexplorer(),
                self.state.dgtmenu.get_picocomment(),
            )
            await self.state.picotutor.open_engine()
        if self.shared is not None:
            self.shared["picotutor"] = self.state.picotutor
        self.pgn_display.set_picotutor(self.state.picotutor)  # needed for comments in pgn
        # set_mode in picotutor init set to False

        ModeInfo.set_game_ending(result="*")

        text = self.state.dgtmenu.get_current_engine_name()
        self.state.engine_text = text
        self.state.dgtmenu.enter_top_menu()

        if self.state.dgtmenu.get_enginename():
            msg = Message.ENGINE_NAME(engine_name=self.state.engine_text)
            await DisplayMsg.show(msg)

        # board connection wait moved to wait_for_board_connection to avoid blocking startup

    def get_last_update_status(self) -> str | None:
        """
        Runs the check-update-status.sh script and returns its output as a string.
        Returns None if there was an error running the script.
        """
        script_path = "/opt/picochess/check-update-status.sh"

        try:
            result = subprocess.run(
                [script_path],
                cwd="/opt/picochess",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,  # capture as string
                check=False,  # don't raise exception on non-zero exit
            )

            # Return stripped output
            return result.stdout.strip()

        except Exception:
            # Optionally log or print error
            logger.info("Error running update status script")
            return None

    def get_git_status(self) -> str | None:
        """
        Runs the check-git-status.sh script and returns the git status string.
        Returns None if there was an error running the script.
        """
        script_path = "/opt/picochess/check-git-status.sh"

        try:
            result = subprocess.run(
                [script_path],
                cwd="/opt/picochess",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,  # capture output as string
                check=False,  # don't raise exception on non-zero exit
            )

            # Return the full output string from the shell script
            return result.stdout.strip()

        except Exception:
            logger.info("Error running git status script:")
            return None

    async def _cache_engine_abort_result(self):
        """Ensure the fallback result for a missing engine move is cached."""
        if self.pgn_mode() or self.online_mode():
            return
        if self.state.pending_engine_result is None:
            # For any engine that produces bestmove 0000 or an illegal move we always
            # ping it (isready) in handle_bestmove_0000() to decide between resignation and crash.
            vb = self.state.get_variant_board()
            self.state.pending_engine_result = await self.engine.handle_bestmove_0000(
                self.state.game.copy(), variant_board=vb.copy() if vb else None
            )

    async def _prepare_engine_for_search(self, search_revision: int) -> bool | None:
        """Stop an obsolete playing search without waiting forever."""
        if search_revision != self.state.engine_search_revision:
            return None
        if self.engine.is_waiting():
            return True

        logger.warning("engine still busy before new search; requesting stop")
        await self.engine.stop()
        idle = await self.engine.wait_until_idle(ENGINE_SEARCH_IDLE_TIMEOUT)
        if search_revision != self.state.engine_search_revision:
            return None
        if idle:
            return True

        logger.error(
            "engine did not become idle after %.1fs; cancelling old search",
            ENGINE_SEARCH_IDLE_TIMEOUT,
        )
        idle = await self.engine.cancel_playing_search(ENGINE_SEARCH_CANCEL_TIMEOUT)
        if search_revision != self.state.engine_search_revision:
            return None
        return idle

    async def _publish_engine_search_failure(self, search_fen: str, search_revision: int) -> None:
        """Route a known idle/cancellation failure through normal engine recovery."""
        self.state.pending_engine_result = "*"
        await Observable.fire(
            Event.BEST_MOVE(
                move=None,
                ponder=None,
                inbook=False,
                fen=search_fen,
                search_revision=search_revision,
            )
        )

    async def think(
        self,
        msg: Message | None,
        searchlist=False,
        tutor_reveal_move: chess.Move | None = None,
        user_move_owner: tuple[chess.Move, str, int] | None = None,
    ):
        """
        Start a new search on the current game.

        If a move is found in the opening book, fire an event in a few seconds.

        ``msg`` may be None when the caller already emitted the move and any
        related pre-search display messages.
        """
        self.state.engine_search_revision += 1
        search_revision = self.state.engine_search_revision
        await self._apply_pending_mame_recovery_rebase()
        if search_revision != self.state.engine_search_revision:
            logger.info("skipping superseded engine search revision %s", search_revision)
            return
        self._set_game_started(True)
        if msg is not None:
            await DisplayMsg.show(msg)
        if tutor_reveal_move is not None:
            await DisplayMsg.show(Message.TUTOR_MOVE_REVEAL(move=tutor_reveal_move))
        if search_revision != self.state.engine_search_revision:
            logger.info("skipping superseded engine search revision %s", search_revision)
            return
        if user_move_owner is not None:
            owner_move, owner_fen, owner_revision = user_move_owner
            if not user_move_task_matches_position(
                owner_move,
                owner_fen,
                owner_revision,
                self.state.game,
                self.state.get_fen(),
                self.state.user_move_revision,
                self.state.done_computer_fen,
            ):
                logger.info("skipping obsolete search after user move [%s]", owner_move)
                return
        search_fen = self.state.get_fen()
        book_res = None
        if self.bookreader and self.state.variant not in ("atomic", "racingkings", "antichess"):
            # Skip opening book for atomic/racingkings/antichess - non-standard rules
            # For 3check variant, use standard FEN for book lookup
            if self.state.variant == "3check" and self.state._threecheck_board is not None:
                # Strip check-count field (field 5 of 7) from 3check extended FEN
                parts = self.state._threecheck_board.fen().split()
                book_lookup_board = chess.Board(f"{parts[0]} {parts[1]} {parts[2]} {parts[3]} {parts[5]} {parts[6]}")
            else:
                book_lookup_board = self.state.game.copy(stack=False)
            book_res = self.state.searchmoves.book(self.bookreader, book_lookup_board)
        if (book_res and not self.emulation_mode() and not self.online_mode() and not self.pgn_mode()) or (
            book_res and (self.pgn_mode() and self.state.pgn_book_test)
        ):
            if not self.online_mode() or self.state.game.fullmove_number > 1:
                await self.state.start_clock()
            if search_revision != self.state.engine_search_revision:
                logger.info("skipping superseded book search revision %s", search_revision)
                return
            await Observable.fire(
                Event.BEST_MOVE(
                    move=book_res.move,
                    ponder=book_res.ponder,
                    inbook=True,
                    fen=search_fen,
                    search_revision=search_revision,
                )
            )
        else:
            engine_ready = await self._prepare_engine_for_search(search_revision)
            if engine_ready is None:
                logger.info("skipping superseded engine search revision %s", search_revision)
                return
            if not engine_ready:
                logger.error("engine remained busy; refusing to start overlapping search")
                await self._publish_engine_search_failure(search_fen, search_revision)
                return
            if search_revision != self.state.engine_search_revision:
                logger.info("skipping superseded engine search revision %s", search_revision)
                return
            if not self.online_mode() or self.state.game.fullmove_number > 1:
                await self.state.start_clock()
            if search_revision != self.state.engine_search_revision:
                logger.info("skipping superseded engine search revision %s", search_revision)
                return
            uci_dict = self.state.time_control.uci()
            if searchlist:
                # molli: otherwise might lead to problems with internal books
                root_moves = self.state.searchmoves.all(self.state.game)
            else:
                root_moves = None
            try:
                # engine moves are received here
                # webplay: Event.BEST_MOVE pushes the move on display
                # dgt board: BEST_MOVE 1) informs 2) user moves, 3) dgt event to process_fen() push
                result_queue = asyncio.Queue()  # engines move result
                # For variant chess, pass the variant board to engine for correct FEN
                variant_board = None
                if self.state.variant == "3check" and self.state._threecheck_board is not None:
                    variant_board = self.state._threecheck_board.copy()
                elif self.state.variant == "atomic" and self.state._atomic_board is not None:
                    variant_board = self.state._atomic_board.copy()
                elif self.state.variant == "racingkings" and self.state._racingkings_board is not None:
                    variant_board = self.state._racingkings_board.copy()
                elif self.state.variant == "antichess" and self.state._antichess_board is not None:
                    variant_board = self.state._antichess_board.copy()
                if search_revision != self.state.engine_search_revision:
                    logger.info("skipping superseded engine search revision %s", search_revision)
                    return
                await self.engine.go(
                    time_dict=uci_dict,
                    game=self.state.game,
                    result_queue=result_queue,
                    root_moves=root_moves,
                    expected_turn=self.state.game.turn,
                    variant_board=variant_board,
                )
                engine_res: PlayResult = await result_queue.get()  # on engine error its None
                if engine_res:
                    logger.debug("engine moved %s", engine_res.move.uci())
                    if self.state.ignore_next_engine_move:
                        self.state.ignore_next_engine_move = False  # make sure we handle next move
                        logger.debug("ignored engine move - takeback or state change forced move")
                    else:
                        move = engine_res.move if engine_res.move != chess.Move.null() else None
                        ponder_move = engine_res.ponder
                        if not ponder_move:
                            logger.debug("engine sent no ponder move")
                        if move is None:
                            await self._cache_engine_abort_result()
                        info: InfoDict | None = engine_res.info
                        analysed_fen = getattr(engine_res, "analysed_fen", "")
                        if move and not ponder_move and info and "pv" in info:
                            pv_line = info["pv"]
                            if pv_line and pv_line[0] == move and len(pv_line) > 1:
                                logger.debug("engine sent info - extracting ponder move")
                                ponder_move = pv_line[1]  # not likely to happen
                        if move and not ponder_move:
                            # no ponder means we should allow the next analysis info to be sent ASAP
                            self.state.best_sent_depth.reset()
                        if info:
                            # send pv, score, not sendpv as it's sent by BEST_MOVE below
                            ponder_cache = ponder_move if ponder_move else chess.Move.null()
                            # Fast clock feedback only; not a full analysis update.
                            await self.send_analyse(
                                info,
                                analysed_fen,
                                send_pv=False,
                                ponder_move=ponder_cache,
                            )
                            # Immediately push the engine's final analysis to the web Engine:
                            # line.  The 1-second analyse() timer may never fire before a fast
                            # engine (Stockfish) finishes its move, so do it right here while
                            # the info is fresh.
                            await self.send_web_analysis([info], analysed_fen, "engine")
                        await Observable.fire(
                            Event.BEST_MOVE(
                                move=move,
                                ponder=ponder_move,
                                inbook=False,
                                fen=analysed_fen or search_fen,
                                search_revision=search_revision,
                            )
                        )
                else:
                    logger.error("Engine returned Exception when asked to make a move")
                    await self._cache_engine_abort_result()
                    await Observable.fire(
                        Event.BEST_MOVE(
                            move=None,
                            ponder=None,
                            inbook=False,
                            fen=search_fen,
                            search_revision=search_revision,
                        )
                    )
            except Exception as e:
                # most likely never reached, engine exceptions in UciEngine return None above
                logger.error("fatal - engine failed to make a move %s", e)
                await Observable.fire(
                    Event.BEST_MOVE(
                        move=None,
                        ponder=None,
                        inbook=False,
                        fen=search_fen,
                        search_revision=search_revision,
                    )
                )
        # set state variables wait for computer move
        # @todo: should we add set self.state.done_computer_fen = None
        self.state.automatic_takeback = False
        self.state.ignore_next_engine_move = False  # dont ignore engine move we now request

    async def stop_search(self, timeout: float = ENGINE_SEARCH_IDLE_TIMEOUT) -> bool:
        """Stop current search."""
        await self.engine.stop()
        if self.engine.consume_forced_analyser_stop():
            logger.debug("forced analyser stop detected - resetting best depth cache")
            self.state.best_sent_depth.reset()
        if self.emulation_mode():
            return True
        idle = await self.engine.wait_until_idle(timeout)
        if not idle:
            logger.warning("engine still not idle after %.1fs", timeout)
        return idle

    async def stop_search_and_clock(self, ponder_hit=False):
        """Depending on the interaction mode stop search and clock."""
        logger.debug(
            "stop_search_and_clock called (mode=%s, ponder_hit=%s, thinking=%s, waiting=%s)\n%s",
            self.state.interaction_mode,
            ponder_hit,
            self.engine.is_thinking(),
            self.engine.is_waiting(),
            "".join(traceback.format_stack(limit=6)),
        )
        if self.state.interaction_mode in (Mode.NORMAL, Mode.BRAIN, Mode.TRAINING):
            await self.state.stop_clock()
            if self.engine.is_waiting():
                logger.debug("engine already waiting")
            else:
                # @ todo check and simplify this logic
                if ponder_hit:
                    pass  # we send the self.engine.hit() lateron!
                else:
                    await self.stop_search()
        elif self.state.interaction_mode in (Mode.REMOTE, Mode.OBSERVE):
            await self.state.stop_clock()
            await self.stop_search()
        elif self.state.interaction_mode in (Mode.ANALYSIS, Mode.KIBITZ, Mode.PONDER, Mode.PGNREPLAY):
            await self.stop_search()

    def get_comment_file(self) -> str:
        comment_path = self.state.engine_file + "_comments_" + self.args.language + ".txt"
        logger.debug("molli comment file: %s", comment_path)
        comment_file = Path(comment_path)
        if comment_file.is_file():
            logger.debug("molli comment file exists")
            return comment_path
        else:
            logger.debug("molli comment file does not exist")
            return ""

    async def call_pico_coach(self):
        if not tutor_analysis_allowed_in_mode(self.state.interaction_mode):
            return
        if (
            (self.state.game.turn == chess.WHITE and self.state.play_mode == PlayMode.USER_WHITE)
            or (self.state.game.turn == chess.BLACK and self.state.play_mode == PlayMode.USER_BLACK)
        ) and not (self.state.game.is_checkmate() or self.state.game.is_stalemate()):
            claimed_position_mode = self.state.coach_triggered
            if claimed_position_mode:
                self.state.position_mode = True
            coach_fen = self.state.get_fen()
            coach_board_fen = self.state.get_board_fen()
            coach_revision = self.state.user_move_revision
            await self.state.stop_clock()
            await asyncio.sleep(0.5)
            if not self._coach_call_is_current(coach_fen, coach_board_fen, coach_revision):
                return
            self.state.stop_fen_timer()
            await asyncio.sleep(0.5)
            if not self._coach_call_is_current(coach_fen, coach_board_fen, coach_revision):
                return
            eval_str = "ANALYSIS"
            msg = Message.PICOTUTOR_MSG(eval_str=eval_str)
            await DisplayMsg.show(msg)
            await asyncio.sleep(2)
            if not self._coach_call_is_current(coach_fen, coach_board_fen, coach_revision):
                return

            (
                t_best_move,
                t_best_score,
                t_best_mate,
                t_alt_best_moves,
            ) = await self.state.picotutor.get_pos_analysis()
            logger.debug(
                "call_pico_coach analysis result: best_move=%s best_score=%s best_mate=%s alt_moves=%d",
                t_best_move,
                t_best_score,
                t_best_mate,
                len(t_alt_best_moves),
            )
            if not self._coach_call_is_current(coach_fen, coach_board_fen, coach_revision):
                return

            tutor_str = "POS" + str(t_best_score)
            msg = Message.PICOTUTOR_MSG(eval_str=tutor_str, score=t_best_score)
            await DisplayMsg.show(msg)
            await asyncio.sleep(5)
            if not self._coach_call_is_current(coach_fen, coach_board_fen, coach_revision):
                return

            if t_best_mate:
                l_mate = int(t_best_mate)
                if t_best_move != chess.Move.null():
                    game_tutor = self.state.game.copy(stack=False)
                    san_move = game_tutor.san(t_best_move)
                    game_tutor.push(t_best_move)  # for picotalker (last move spoken)
                    tutor_str = "BEST" + san_move
                    msg = Message.PICOTUTOR_MSG(eval_str=tutor_str, game=game_tutor)
                    await DisplayMsg.show(msg)
                    await asyncio.sleep(5)
                    if not self._coach_call_is_current(coach_fen, coach_board_fen, coach_revision):
                        return
            else:
                l_mate = 0
            if l_mate > 0:
                eval_str = "PICMATE_" + str(abs(l_mate))
                msg = Message.PICOTUTOR_MSG(eval_str=eval_str)
                await DisplayMsg.show(msg)
                await asyncio.sleep(5)
                if not self._coach_call_is_current(coach_fen, coach_board_fen, coach_revision):
                    return
            elif l_mate < 0:
                eval_str = "USRMATE_" + str(abs(l_mate))
                msg = Message.PICOTUTOR_MSG(eval_str=eval_str)
                await DisplayMsg.show(msg)
                await asyncio.sleep(5)
                if not self._coach_call_is_current(coach_fen, coach_board_fen, coach_revision):
                    return
            else:
                l_max = 0
                for alt_move in t_alt_best_moves:
                    l_max = l_max + 1
                    if l_max <= 3:
                        game_tutor = self.state.game.copy(stack=False)
                        san_move = game_tutor.san(alt_move)
                        game_tutor.push(alt_move)  # for picotalker (last move spoken)

                        tutor_str = "BEST" + san_move
                        msg = Message.PICOTUTOR_MSG(eval_str=tutor_str, game=game_tutor)
                        await DisplayMsg.show(msg)
                        await asyncio.sleep(5)
                        if not self._coach_call_is_current(coach_fen, coach_board_fen, coach_revision):
                            return
                    else:
                        break
            if claimed_position_mode:
                self.state.position_mode = False
                self.state.coach_triggered = False
                self.state.error_fen = None
            await self.state.start_clock()

    def _coach_call_is_current(
        self,
        expected_fen: str,
        expected_board_fen: str,
        expected_revision: int,
    ) -> bool:
        """Keep Coach output tied to the position that requested it."""
        if (
            self.state.user_move_revision != expected_revision
            or self.state.get_fen() != expected_fen
        ):
            return False
        if self.board_type == dgt.util.EBoard.NOEBOARD:
            return True
        return self.state.dgtmenu.get_dgt_fen() == expected_board_fen

    def _release_coach_position_mode_for_move(self) -> None:
        """Let a confirmed legal move enter Tutor while an old Coach display winds down."""
        if self.state.position_mode and self.state.coach_triggered:
            logger.info("ending Coach position mode for confirmed user move")
            self.state.position_mode = False
            self.state.coach_triggered = False

    async def call_hand_coach(self, piece_type: chess.PieceType | None):
        """Experimental Brain and hand: suggest the best move for a lifted piece type."""
        if not (
            self.picotutor_mode()
            and self.state.dgtmenu.get_picocoach() == PicoCoach.COACH_HAND
            and self.state.interaction_mode == Mode.NORMAL
            and (
                (self.state.game.turn == chess.WHITE and self.state.play_mode == PlayMode.USER_WHITE)
                or (self.state.game.turn == chess.BLACK and self.state.play_mode == PlayMode.USER_BLACK)
            )
            and not self.state.game.is_checkmate()
            and not self.state.game.is_stalemate()
        ):
            return
        if piece_type is None:
            await DisplayMsg.show(Message.PICOTUTOR_MSG(eval_str="HAND_NOPIECE"))
            return

        best_move = await self.state.picotutor.get_best_move_for_piece_type(piece_type)
        if best_move is None:
            self.state.last_hand_coach_move = None
            await DisplayMsg.show(Message.PICOTUTOR_MSG(eval_str="HAND_NOPIECE"))
            return

        piece_name = self._piece_type_name(piece_type)
        logger.info("Brain and hand: best %s move is %s", piece_name, best_move)
        self.state.last_hand_coach_move = best_move
        await DisplayMsg.show(Message.PICOTUTOR_MSG(eval_str="HAND_" + piece_name))
        await asyncio.sleep(2)
        game_tutor = self.state.game.copy(stack=False)
        san_move = game_tutor.san(best_move)
        game_tutor.push(best_move)
        await DisplayMsg.show(Message.PICOTUTOR_MSG(eval_str="BEST" + san_move, game=game_tutor))

    def _piece_type_name(self, piece_type: chess.PieceType | None) -> str:
        return {
            chess.PAWN: "PAWN",
            chess.KNIGHT: "KNIGHT",
            chess.BISHOP: "BISHOP",
            chess.ROOK: "ROOK",
            chess.QUEEN: "QUEEN",
            chess.KING: "KING",
        }.get(piece_type, "PAWN")

    def _user_turn_and_alive(self) -> bool:
        return (
            (
                (self.state.game.turn == chess.WHITE and self.state.play_mode == PlayMode.USER_WHITE)
                or (self.state.game.turn == chess.BLACK and self.state.play_mode == PlayMode.USER_BLACK)
            )
            and not self.state.game.is_checkmate()
            and not self.state.game.is_stalemate()
        )

    async def _brain_hint_after_delay(self):
        """Experimental Brain and hand: tell the user which piece type to play."""
        if not (
            self._user_turn_and_alive()
            and self.picotutor_mode()
            and self.state.dgtmenu.get_picocoach() == PicoCoach.COACH_BRAIN
            and self.state.interaction_mode == Mode.NORMAL
        ):
            return

        best_move = None
        if self.bookreader:
            try:
                best_move = self.bookreader.weighted_choice(
                    self.state.game.copy(stack=False)
                ).move
                logger.debug("Brain and hand: book hint move %s", best_move)
            except IndexError:
                pass

        if best_move is None:
            best_engine = getattr(self.state.picotutor, "best_engine", None)
            for _ in range(30):
                await asyncio.sleep(0.1)
                if not (
                    self._user_turn_and_alive()
                    and self.picotutor_mode()
                    and self.state.dgtmenu.get_picocoach() == PicoCoach.COACH_BRAIN
                    and self.state.interaction_mode == Mode.NORMAL
                ):
                    return
                if best_engine and best_engine.is_analysis_limit_reached():
                    break
            result = await self.state.picotutor.get_pos_analysis()
            if not result:
                return
            best_move, _score, _mate, _alt_best_moves = result

        if not best_move or best_move == chess.Move.null():
            return
        piece_type = self.state.game.piece_type_at(best_move.from_square)
        if piece_type is None:
            await DisplayMsg.show(Message.PICOTUTOR_MSG(eval_str="BRAIN_NOPIECE"))
            return

        self.state.brain_required_piece_type = piece_type
        self.state.brain_best_move = best_move
        piece_name = self._piece_type_name(piece_type)
        logger.info("Brain and hand: use a %s", piece_name)
        await DisplayMsg.show(Message.PICOTUTOR_MSG(eval_str="BRAIN_" + piece_name))
        hint_display = self.state.dgtmenu.get_brain_hint_display()
        countdown = self.state.dgtmenu.get_brain_hint_countdown()
        if not countdown:
            await self.state.stop_clock()
            self.state.brain_hint_clock_paused = True
        if hint_display > 0:
            try:
                await asyncio.sleep(hint_display)
                if self.state.brain_hint_clock_paused and self.state.brain_hint_task is asyncio.current_task():
                    self.state.brain_hint_clock_paused = False
                    await self.state.start_clock()
            except asyncio.CancelledError:
                if self.state.brain_hint_task is asyncio.current_task():
                    self.state.brain_hint_clock_paused = False
                raise

    def start_brain_hint_timer(self):
        """Start/restart the experimental Brain and hand piece-type hint."""
        self.cancel_brain_hint_timer(resume_paused_clock=False)
        self.state.brain_required_piece_type = None
        if (
            self.picotutor_mode()
            and self.state.dgtmenu.get_picocoach() == PicoCoach.COACH_BRAIN
            and self.state.interaction_mode == Mode.NORMAL
            and self._user_turn_and_alive()
        ):
            self.state.brain_hint_task = asyncio.ensure_future(self._brain_hint_after_delay())

    async def _resume_clock_after_brain_hint_cancel(self):
        """Resume the clock if a Brain hint, not a move, ended the pause."""
        await asyncio.sleep(0)
        if (
            not self.state.brain_hint_clock_paused
            and self.state.game_started
            and self._user_turn_and_alive()
            and self.state.interaction_mode == Mode.NORMAL
            and not self.state.position_mode
            and not self.state.takeback_active
            and not self.state.error_fen
            and not self.state.done_computer_fen
        ):
            await self.state.start_clock()

    def cancel_brain_hint_timer(self, preserve_best_move: bool = False, resume_paused_clock: bool = True):
        """Cancel pending Brain and hand hints without touching playing modes."""
        clock_was_paused = self.state.brain_hint_clock_paused
        if self.state.brain_hint_task and not self.state.brain_hint_task.done():
            self.state.brain_hint_task.cancel()
        self.state.brain_hint_task = None
        self.state.brain_hint_clock_paused = False
        self.state.brain_required_piece_type = None
        if not preserve_best_move:
            self.state.brain_best_move = None
        if clock_was_paused and resume_paused_clock:
            asyncio.ensure_future(self._resume_clock_after_brain_hint_cancel())

    async def _handle_same_square_input(self, from_square: chess.Square):
        """Use a same-square web move as a Brain and hand re-request gesture."""
        coach_mode = self.state.dgtmenu.get_picocoach()
        if coach_mode == PicoCoach.COACH_HAND and self.picotutor_mode():
            piece_type = self.state.game.piece_type_at(from_square)
            if piece_type is None:
                return
            if self.state.hand_coach_task and not self.state.hand_coach_task.done():
                self.state.hand_coach_task.cancel()
            self.state.last_hand_coach_move = None
            self.state.hand_coach_task = asyncio.ensure_future(self.call_hand_coach(piece_type))
        elif coach_mode == PicoCoach.COACH_BRAIN and self.picotutor_mode():
            self.start_brain_hint_timer()

    def reset_setpieces_window_switch(self):
        self.state.setpieces_switch_anchor_fen = ""
        self.state.setpieces_switch_armed = False

    def _clear_set_position_ack(self) -> None:
        """Release any explicit Set Pos physical-board synchronization."""
        self.state.set_position_ack_pending = False
        self.state.set_position_ack_target_fen = ""
        self.state.set_position_ack_ready = False
        self.state.stop_fen_timer()
        self.state.error_fen = None

    def _begin_set_position_ack(self, target_fen: str, physical_fen: str) -> None:
        """Claim Set Pos synchronization before the event handler first yields."""
        self._clear_set_position_ack()
        self.state.set_position_ack_target_fen = target_fen
        self.state.set_position_ack_pending = physical_fen != target_fen

    def _owns_set_position_ack(self, target_fen: str | None) -> bool:
        return target_fen is None or target_fen == self.state.set_position_ack_target_fen

    async def _finish_set_position_ack(self, target_fen: str) -> None:
        """Acknowledge one matching physical position and release its guard."""
        if (
            target_fen != self.state.set_position_ack_target_fen
            or not self.state.set_position_ack_ready
        ):
            return
        self.state.set_position_ack_ready = False
        self.state.set_position_ack_pending = False
        # Release physical input before announcing OK or yielding to another event.
        self.state.set_position_ack_target_fen = ""
        self.state.stop_fen_timer()
        self.state.error_fen = None
        self.state.position_mode = False
        await DisplayMsg.show(Message.PICOTUTOR_MSG(eval_str="POSOK"))
        await asyncio.sleep(1)

    async def switch_artwork_window(self):
        if self.emulation_mode() and self.state.dgtmenu.get_engine_rdisplay() and self.state.artwork_in_use:
            cmd = get_window_command("switch_window")
            if cmd:
                process = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await process.communicate()

    def calc_engine_mame_par(self):
        return get_engine_mame_par(
            self.state.dgtmenu.get_engine_rspeed(),
            self.state.dgtmenu.get_engine_rsound(),
            engine_rwindow=self.state.dgtmenu.get_engine_rwindow(),
        )

    async def show_loaded_mame_capabilities(self):
        """Temporarily show reported Lua capabilities after a MAME load."""
        if self.engine.is_mame_engine():
            await DisplayMsg.show(
                Message.ENGINE_RETRO_INFO(
                    features=self.engine.get_mame_capabilities().retro_info().strip() or "/"
                )
            )

    def preserve_mame_history_for_web(self, game_or_board, selected_fen: str, reason: str) -> None:
        """Preserve the prefix used to compose outgoing browser history."""
        try:
            pgn_text = mame_history_snapshot_pgn(
                game_or_board,
                self.shared.get("headers", {}),
            )
            publish_preserved_mame_history(self.shared, pgn_text, selected_fen, reason)
        except Exception:
            logger.exception("failed to preserve MAME browser history: reason=%s", reason)

    def pgn_mode(self):
        if "pgn_" in self.state.engine_file:
            return True
        else:
            return False

    def remote_windows(self):
        windows = False
        if "\\" in self.engine_remote_home:
            windows = True
        else:
            windows = False
        return windows

    async def get_engine_level_dict(self, engine_level):
        """Transfer an engine level to its level_dict plus an index."""
        for eng in EngineProvider.installed_engines:
            if eng["file"] == self.state.engine_file:
                level_list = sorted(eng["level_dict"])
                try:
                    level_index = level_list.index(engine_level)
                    return eng["level_dict"][level_list[level_index]], level_index
                except ValueError:
                    break
        return {}, None

    async def set_fen_from_pgn(self, pgn_fen):
        bit_board = chess.Board(pgn_fen)
        bit_board.set_fen(bit_board.fen())
        logger.debug("molli PGN Fen: %s", bit_board.fen())
        if bit_board.is_valid():
            logger.debug("molli PGN fen is valid!")
            self.state.game = chess.Board(bit_board.fen())
            # Sync variant boards with new position
            if self.state.variant == "3check" and self.state._threecheck_board is not None:
                self.state._threecheck_board.set_fen(bit_board.fen())
            elif self.state.variant == "atomic" and self.state._atomic_board is not None:
                self.state._atomic_board.set_fen(bit_board.fen())
            elif self.state.variant == "racingkings" and self.state._racingkings_board is not None:
                self.state._racingkings_board.set_fen(bit_board.fen())
            elif self.state.variant == "antichess" and self.state._antichess_board is not None:
                self.state._antichess_board.set_fen(bit_board.fen())
            self.state.done_computer_fen = None
            self.state.done_move = self.state.pb_move = chess.Move.null()
            self.state.searchmoves.reset()
            self.state.game_declared = False
            self.state.legal_fens = compute_legal_fens(self.state.game, self.state.get_variant_board())
            self.state.legal_fens_after_cmove = []
            self.state.last_legal_fens = []
            await self.set_picotutor_position(new_game=True)
        else:
            logger.debug("molli PGN fen is invalid!")

    async def set_picotutor_position(self, new_game=False, position: chess.Board | None = None):
        """tutor is either off sync or we are starting from a new position
        set tutor back to same position as main board game"""
        if self.picotutor_mode():
            # An announced physical-board engine move may not have been pushed
            # into state.game yet.  In that case the caller supplies the
            # already-advanced position that PicoTutor must analyse.
            target_position = position if position is not None else self.state.game
            await self.state.picotutor.set_position(target_position.copy(), new_game=new_game)
            if self.state.play_mode == PlayMode.USER_BLACK:
                await self.state.picotutor.set_user_color(chess.BLACK, self.pgn_mode() or not self.eng_plays())
            else:
                await self.state.picotutor.set_user_color(chess.WHITE, self.pgn_mode() or not self.eng_plays())

    def picotutor_mode(self):
        enabled = False

        # PONDER is an independent physical-analysis sandbox. Keep the
        # tutor board, move history, and evaluations frozen at its anchor;
        # selected-engine analysis is the only backend analysis in PONDER.
        if not tutor_analysis_allowed_in_mode(self.state.interaction_mode):
            return False

        # Disable PicoTutor for chess variants (3check, etc.)
        if self.state.variant != "chess":
            return False

        # issue #61 - pgn_mode shall not prevent picotutor
        if (
            self.state.flag_picotutor
            and not self.online_mode()
            and (
                self.state.dgtmenu.get_picowatcher()
                or (self.state.dgtmenu.get_picocoach() != PicoCoach.COACH_OFF)
                or self.state.dgtmenu.get_picoexplorer()
            )
            and self.state.picotutor is not None
        ):
            enabled = True
        else:
            enabled = False

        return enabled

    def online_mode(self):
        online = False
        if len(self.engine.get_name()) >= 6:
            if self.engine.get_name()[0:6] == ONLINE_PREFIX:
                online = True
            else:
                online = False
        return online

    def _init_variant_from_engine(self):
        """Initialize variant state from engine settings."""
        prev_variant = self.state.variant
        if self.engine and hasattr(self.engine, "variant"):
            new_variant = self.engine.variant
            if new_variant != prev_variant:
                self._clear_position_checkpoint()
            # Variants with non-standard board state should reset when switching away.
            # Racing Kings has a custom start position; Atomic keeps explosions only
            # on its variant board while self.state.game keeps standard captures.
            # Antichess can also diverge from standard-chess legal-state assumptions.
            if (prev_variant == "racingkings" and new_variant != "racingkings") or (
                prev_variant == "atomic" and new_variant != "atomic"
            ) or (
                prev_variant == "antichess" and new_variant != "antichess"
            ):
                self.state.game = chess.Board()
            self.state.variant = new_variant
            if self.state.variant == "3check":
                self.state._threecheck_board = chess.variant.ThreeCheckBoard()
                self.state._atomic_board = None
                self.state._racingkings_board = None
                self.state._antichess_board = None
                # Sync with existing move_stack from game (for engine switch mid-game)
                if self.state.game.move_stack:
                    logger.info("3check: syncing with existing %d moves", len(self.state.game.move_stack))
                    for move in self.state.game.move_stack:
                        self.state._threecheck_board.push(move)
                logger.info("3check variant initialized")
            elif self.state.variant == "kingofthehill":
                logger.info("King of the Hill variant initialized")
                self.state._threecheck_board = None
                self.state._atomic_board = None
                self.state._racingkings_board = None
                self.state._antichess_board = None
            elif self.state.variant == "atomic":
                self.state._atomic_board = chess.variant.AtomicBoard()
                self.state._threecheck_board = None
                self.state._racingkings_board = None
                self.state._antichess_board = None
                # Sync with existing move_stack from game (for engine switch mid-game)
                if self.state.game.move_stack:
                    logger.info("atomic: syncing with existing %d moves", len(self.state.game.move_stack))
                    for move in self.state.game.move_stack:
                        self.state._atomic_board.push(move)
                logger.info("Atomic variant initialized")
            elif self.state.variant == "racingkings":
                self.state._racingkings_board = chess.variant.RacingKingsBoard()
                self.state._threecheck_board = None
                self.state._atomic_board = None
                self.state._antichess_board = None
                # Sync with existing move_stack from game (for engine switch mid-game)
                if self.state.game.move_stack:
                    logger.info("racingkings: syncing with existing %d moves", len(self.state.game.move_stack))
                    for move in self.state.game.move_stack:
                        self.state._racingkings_board.push(move)
                else:
                    # Fresh game: set main board to RK starting position
                    # (standard chess.Board defaults to standard chess starting FEN)
                    self.state.game = chess.Board("8/8/8/8/8/8/krbnNBRK/qrbnNBRQ w - - 0 1")
                logger.info("Racing Kings variant initialized")
            elif self.state.variant == "antichess":
                self.state._antichess_board = chess.variant.AntichessBoard()
                self.state._threecheck_board = None
                self.state._atomic_board = None
                self.state._racingkings_board = None
                # Sync with existing move_stack from game (for engine switch mid-game)
                if self.state.game.move_stack:
                    logger.info("antichess: syncing with existing %d moves", len(self.state.game.move_stack))
                    for move in self.state.game.move_stack:
                        self.state._antichess_board.push(move)
                logger.info("Antichess variant initialized")
            else:
                self.state._threecheck_board = None
                self.state._atomic_board = None
                self.state._racingkings_board = None
                self.state._antichess_board = None
        else:
            self.state.variant = "chess"
            self.state._threecheck_board = None
            self.state._atomic_board = None
            self.state._racingkings_board = None
            self.state._antichess_board = None

        # Update shared dict for web interface
        self._update_variant_shared()
        ModeInfo.set_variant(self.state.variant)

    def _update_variant_shared(self):
        """Update shared dict with variant info for web interface."""
        if self.shared is not None:
            self.shared["variant"] = self.state.variant
            if self.state.variant == "3check" and self.state._threecheck_board:
                self.shared["checks_remaining"] = {
                    "white": self.state._threecheck_board.remaining_checks[chess.WHITE],
                    "black": self.state._threecheck_board.remaining_checks[chess.BLACK],
                }
            else:
                self.shared.pop("checks_remaining", None)

    def _prepare_engine_move(self, game_copy: chess.Board, move: chess.Move, pb_move: chess.Move = None) -> None:
        """Record an announced engine move: set done_computer_fen, done_move, pb_move, legal_fens_after_cmove.

        game_copy must already have move pushed onto it.
        For variant boards a copy at N+1 (move applied) is used so that FENs reflect
        the correct post-move position rather than the live board still at N.
        """
        if pb_move is None:
            pb_move = chess.Move.null()
        vb = self.state.get_variant_board()
        vb_after = None
        if vb is not None:
            vb_after = vb.copy()
            vb_after.push(move)
        self.state.done_computer_fen = vb_after.board_fen() if vb_after is not None else game_copy.board_fen()
        self.state.done_move = move
        self.state.pb_move = pb_move
        self.state.legal_fens_after_cmove = compute_legal_fens(game_copy, vb_after)

    async def set_wait_state(self, msg: Message, start_search=True, preserve_play_mode=False):
        """Enter engine waiting (normal mode) and maybe (by parameter) start pondering."""
        if not self.state.done_computer_fen:
            self.state.legal_fens = compute_legal_fens(self.state.game, self.state.get_variant_board())
            self.state.last_legal_fens = []
        if self.state.interaction_mode in (Mode.NORMAL, Mode.BRAIN):  # @todo handle Mode.REMOTE too and TRAINING?
            if self.state.done_computer_fen:
                logger.debug("best move displayed, dont search and also keep play mode: %s", self.state.play_mode)
                start_search = False
            elif preserve_play_mode:
                logger.debug("preserving play mode: %s", self.state.play_mode)
                if self.picotutor_mode():
                    await self.state.picotutor.set_user_color(
                        self.state.get_user_color(), self.pgn_mode() or not self.eng_plays()
                    )
            else:
                old_mode = self.state.play_mode
                self.state.play_mode = (
                    PlayMode.USER_WHITE if self.state.game.turn == chess.WHITE else PlayMode.USER_BLACK
                )
                if old_mode != self.state.play_mode:
                    logger.debug("new play mode: %s", self.state.play_mode)
                    text = self.state.play_mode.value  # type: str
                    if self.picotutor_mode():
                        await self.state.picotutor.set_user_color(
                            self.state.get_user_color(), self.pgn_mode() or not self.eng_plays()
                        )
                    await DisplayMsg.show(
                        Message.PLAY_MODE(
                            play_mode=self.state.play_mode, play_mode_text=self.state.dgttranslate.text(text)
                        )
                    )
        if start_search:
            if not self.engine.is_waiting():
                logger.warning("engine not waiting")
            # Go back to analysing or observing - all modes except REMOTE?
            if self.state.interaction_mode in (
                Mode.BRAIN,
                Mode.ANALYSIS,
                Mode.KIBITZ,
                Mode.PONDER,
                Mode.TRAINING,
                Mode.OBSERVE,
                Mode.REMOTE,
                Mode.PGNREPLAY,
            ):
                await DisplayMsg.show(msg)
                await self.analyse()
                return
        if not self.state.reset_auto:
            if self.state.automatic_takeback:
                await self.stop_search_and_clock()
                self.state.reset_auto = True
            await DisplayMsg.show(msg)
        else:
            await DisplayMsg.show(msg)  # molli: fix for web display refresh
            if self.state.automatic_takeback and self.state.takeback_active:
                if self.state.play_mode == PlayMode.USER_WHITE:
                    text_pl = "K20_playmode_white_user"
                else:
                    text_pl = "K20_playmode_black_user"
                await DisplayMsg.show(Message.SHOW_TEXT(text_string=text_pl))
            self.state.automatic_takeback = False
            self.state.takeback_active = False
            self.state.reset_auto = False
            await self._apply_pending_mame_recovery_rebase()

        self.state.stop_fen_timer()

    async def _apply_pending_mame_recovery_rebase(self) -> None:
        """Make a reopened pos-only MAME recovery position a fresh root."""
        if not self.state.mame_recovery_rebase_pending:
            return

        self.state.mame_recovery_rebase_pending = False
        capabilities = self.engine.get_mame_capabilities()
        if not mame_requires_fresh_fen_root(
            self.engine.is_mame_engine(),
            capabilities.position,
            capabilities.edit,
        ):
            return
        if not self.state.game.move_stack:
            return

        logger.info(
            "MAME recovery: edit unsupported; using current FEN as a fresh game root"
        )
        self.preserve_mame_history_for_web(
            self.state.game,
            self.state.game.fen(en_passant="fen"),
            "engine_recovery",
        )
        self.state.game = self.state.game.copy(stack=False)
        self._reset_loaded_pgn_lifecycle()
        self.state.best_sent_depth.reset()
        self.state.searchmoves.reset()
        self.state.take_back_locked = True
        self.state.legal_fens = compute_legal_fens(self.state.game)
        self.state.legal_fens_after_cmove = []
        self.state.last_legal_fens = []
        await self.set_picotutor_position(new_game=True)
        await DisplayMsg.show(self.state.new_game_msg(newgame=False))

    async def takeback(self):
        if self.state.game.move_stack:
            self._invalidate_user_move_tasks()
        await self.stop_search_and_clock()
        l_error = False
        try:
            self.state.pop_move()
            l_error = False
        except Exception:
            l_error = True
            logger.debug("takeback not possible!")
        if not l_error:
            self._update_variant_shared()  # Update check counts after takeback
            self._resume_game_after_takeback()
            if self.picotutor_mode():
                if self.state.best_move_posted:
                    await self.state.picotutor.pop_posted_engine_move(self.state.game)
                    self.state.best_move_posted = False
                await self.state.picotutor.pop_last_move(self.state.game)
            self.state.done_computer_fen = None
            self.state.done_move = self.state.pb_move = chess.Move.null()
            self.state.searchmoves.reset()
            self.state.takeback_active = True
            # it seems call to set_wait_state assumes its always user move
            # so after engine move takeback user needs to press lever
            await self.set_wait_state(Message.TAKE_BACK(game=self.state.game.copy()))
            await self._apply_pending_mame_recovery_rebase()

            if self.pgn_mode():  # molli pgn
                log_pgn(self.state)
                if self.state.max_guess_white > 0:
                    if self.state.game.turn == chess.WHITE:
                        if self.state.no_guess_white > self.state.max_guess_white:
                            await self.get_next_pgn_move()
                elif self.state.max_guess_black > 0:
                    if self.state.game.turn == chess.BLACK:
                        if self.state.no_guess_black > self.state.max_guess_black:
                            await self.get_next_pgn_move()

    async def get_next_pgn_move(self):
        log_pgn(self.state)
        await asyncio.sleep(0.5)

        if self.state.max_guess_black > 0:
            self.state.no_guess_black = 1
        elif self.state.max_guess_white > 0:
            self.state.no_guess_white = 1

        if not self.engine.is_waiting():
            await self.stop_search_and_clock()

        self.state.last_legal_fens = []
        self.state.legal_fens_after_cmove = []
        self.state.best_move_displayed = self.state.done_computer_fen
        if self.state.best_move_displayed:
            self.state.done_computer_fen = None
            self.state.done_move = self.state.pb_move = chess.Move.null()

        # issue #61 - in issue #23 - PR #35 these 3 lines were wrongly removed
        # without these lines there is no automatic replay with pgn engine
        # switching sides makes pgn engine make the next move
        # This might confuse the picotutor - Need to debug tutor push move
        self.state.play_mode = (
            PlayMode.USER_WHITE if self.state.play_mode == PlayMode.USER_BLACK else PlayMode.USER_BLACK
        )
        msg = Message.SET_PLAYMODE(play_mode=self.state.play_mode)

        if self.state.time_control.mode == TimeMode.FIXED:
            self.state.time_control.reset()

        self.state.legal_fens = []

        cond1 = self.state.game.turn == chess.WHITE and self.state.play_mode == PlayMode.USER_BLACK
        cond2 = self.state.game.turn == chess.BLACK and self.state.play_mode == PlayMode.USER_WHITE
        if cond1 or cond2:
            self.state.time_control.reset_start_time()
            await self.think(msg)
        else:
            await DisplayMsg.show(msg)
            await self.state.start_clock()
            self.state.legal_fens = compute_legal_fens(self.state.game, self.state.get_variant_board())

    async def switch_online(self):
        color = ""
        if self.online_mode():
            login, own_color, own_user, opp_user, game_time, fischer_inc = read_online_user_info()
            logger.debug("molli own_color in switch_online [%s]", own_color)
            logger.debug("molli self.own_user in switch_online [%s]", own_user)
            logger.debug("molli self.opp_user in switch_online [%s]", opp_user)
            logger.debug("molli game_time in switch_online [%s]", game_time)
            logger.debug("molli fischer_inc in switch_online [%s]", fischer_inc)

            ModeInfo.set_online_mode(mode=True)
            ModeInfo.set_online_self.own_user(name=own_user)
            ModeInfo.set_online_opponent(name=opp_user)

            if len(own_color) > 1:
                color = own_color[2]
            else:
                color = own_color

            logger.debug("molli switch_online start timecontrol")
            await self.state.set_online_tctrl(game_time, fischer_inc)
            self.state.time_control.reset_start_time()

            logger.debug("molli switch_online new_color: %s", color)
            if (
                (color == "b" or color == "B")
                and self.state.game.turn == chess.WHITE
                and self.state.play_mode == PlayMode.USER_WHITE
                and self.state.done_move == chess.Move.null()
            ):
                # switch to black color for user and send a 'go' to the engine
                self.state.play_mode = PlayMode.USER_BLACK
                text = self.state.play_mode.value  # type: str
                msg = Message.PLAY_MODE(
                    play_mode=self.state.play_mode, play_mode_text=self.state.dgttranslate.text(text)
                )

                await self.stop_search_and_clock()

                self.state.last_legal_fens = []
                self.state.legal_fens_after_cmove = []
                self.state.legal_fens = []

                await self.think(msg)

        else:
            ModeInfo.set_online_mode(mode=False)

        if self.pgn_mode():
            ModeInfo.set_pgn_mode(mode=True)
        else:
            ModeInfo.set_pgn_mode(mode=False)

    async def process_fen(self, fen: str, state: PicochessState):
        """Process given fen like doMove, undoMove, takebackPosition, handleSliding."""
        handled_fen = True
        self.state.error_fen = None
        # Use variant board for legal move enumeration when available (atomic has
        # different legal moves than standard chess).  The same board must be used
        # for both FEN computation AND move-index lookup — mixing them produces
        # wrong moves.
        _move_board = self.state.get_move_check_board()
        legal_fens_pico = compute_legal_fens(self.state.game, self.state.get_variant_board())
        if (
            self.board_type == dgt.util.EBoard.DGT
            and not self.state.dgtmenu.get_flip_board()
            and fen
        ):
            flipped_fen = flip_board_fen(fen)
            known_fens = set(legal_fens_pico)
            known_fens.update(self.state.legal_fens)
            known_fens.update(self.state.last_legal_fens)
            known_fens.update(self.state.legal_fens_after_cmove)
            known_fens.add(self.state.get_board_fen())
            if self.state.set_position_ack_target_fen:
                known_fens.add(self.state.set_position_ack_target_fen)
            if self.state.done_computer_fen:
                known_fens.add(self.state.done_computer_fen)
            if flipped_fen != fen and flipped_fen in known_fens and fen not in known_fens:
                logger.info(
                    "DGT board orientation inferred from position; switching to B-in-front orientation"
                )
                self.state.dgtmenu.set_position_reverse_flipboard(True, self.state.play_mode)
                self.state.dgtmenu.set_dgt_fen(flipped_fen)
                fen = flipped_fen

        # A checkpoint restore updates the logical position first, then
        # waits for the physical pieces. During that window no scan may
        # fall through to flexible PONDER setup.
        if self.state.position_checkpoint_restore_pending:
            if fen == self.state.get_board_fen():
                await self._finish_position_checkpoint_restore()
            else:
                self.state.stop_fen_timer()
                self.state.error_fen = fen
                self.state.position_mode = True
                self.start_fen_timer()
            return

        # Set Pos has already installed its logical target. Until the
        # physical board matches, intermediate placements are setup input,
        # not moves, sliding moves, engine-move completion, or takebacks.
        if self.state.set_position_ack_target_fen:
            action, new_game_code = pending_set_position_fen_action(
                fen,
                self.state.set_position_ack_target_fen,
                bool(self.engine and self.engine.has_chess960()),
                self.state.variant,
            )
            if action == "new_game":
                logger.info("starting position cancels pending Set Pos")
                self._clear_set_position_ack()
                await Observable.fire(Event.NEW_GAME(pos960=new_game_code))
            elif action == "target":
                if self.state.set_position_ack_ready:
                    await self._finish_set_position_ack(
                        self.state.set_position_ack_target_fen
                    )
            else:
                self.state.stop_fen_timer()
                self.state.error_fen = fen
                if self.state.set_position_ack_ready:
                    self.start_fen_timer()
            return

        starting_board_fen = (
            RK_STARTING_BOARD_FEN if self.state.variant == "racingkings" else chess.STARTING_BOARD_FEN
        )
        is_starting_board_fen = fen == starting_board_fen
        ended_game_start_reset = (
            is_starting_board_fen
            and bool(self.state.game.move_stack)
            and not self.state.game_started
        )

        # Check for same position (use variant board_fen for atomic explosions)
        if ended_game_start_reset:
            logger.info("start position after ended game detected; treating as new game")
            handled_fen = False
        elif fen == self.state.get_board_fen():
            logger.debug("Already in this fen: %s", fen)
            self.state.flag_startup = False
            setpieces_switch_pending = bool(
                self.state.position_mode and self.state.setpieces_switch_anchor_fen
            )
            if self.state.set_position_ack_pending:
                self.state.set_position_ack_pending = False
                if not (self.state.position_mode and self.state.delay_fen_error == 1):
                    await DisplayMsg.show(Message.PICOTUTOR_MSG(eval_str="POSOK"))
                    await asyncio.sleep(1)
            # molli: Chess tutor
            if (
                self.picotutor_mode()
                and self.state.dgtmenu.get_picocoach() in (PicoCoach.COACH_LIFT, PicoCoach.COACH_HAND)
                and fen != chess.STARTING_BOARD_FEN
                and not (self.state.variant == "racingkings" and fen == RK_STARTING_BOARD_FEN)
                and not self.state.take_back_locked
                and self.state.coach_triggered
                and not self.state.position_mode
                and not self.state.automatic_takeback
            ):
                if self.state.dgtmenu.get_picocoach() == PicoCoach.COACH_HAND:
                    if self.state.hand_coach_task and not self.state.hand_coach_task.done():
                        await self.state.hand_coach_task
                    elif self.state.coach_triggered_piece_type is not None:
                        await self.call_hand_coach(self.state.coach_triggered_piece_type)
                else:
                    await self.call_pico_coach()
                self.state.coach_triggered = False
            elif self.state.position_mode:
                self.state.position_mode = False
                if self.state.delay_fen_error == 1:
                    # position finally alright!
                    tutor_str = "POSOK"
                    msg = Message.PICOTUTOR_MSG(eval_str=tutor_str)
                    await DisplayMsg.show(msg)
                    self.state.delay_fen_error = 4
                    await asyncio.sleep(1)
                    if not self.state.done_computer_fen:
                        await self.state.start_clock()
                await DisplayMsg.show(Message.EXIT_MENU())
                if setpieces_switch_pending:
                    await self.switch_artwork_window()
            elif self.emulation_mode() and self.state.dgtmenu.get_engine_rdisplay() and self.state.artwork_in_use:
                # switch windows/tasks
                await self.switch_artwork_window()
            self.reset_setpieces_window_switch()
        # Check if we have to undo a previous move (sliding)
        elif fen in self.state.last_legal_fens and should_process_sliding_move(
            self.state.interaction_mode,
            self.state.game_declared,
            ModeInfo.get_game_ending(),
        ):
            logger.info("sliding move detected")
            if self.state.interaction_mode in (Mode.NORMAL, Mode.BRAIN, Mode.TRAINING):
                if self.state.is_not_user_turn():
                    await self.stop_search()
                    self.state.pop_move()
                    if self.picotutor_mode():
                        if self.state.best_move_posted:
                            await self.state.picotutor.pop_posted_engine_move(
                                self.state.game
                            )  # bestmove already sent to tutor
                            self.state.best_move_posted = False
                        await self.state.picotutor.pop_last_move(self.state.game)  # no switch of sides
                    logger.info("user move in computer turn, reverting to: %s", self.state.game.fen())
                elif self.state.done_computer_fen:
                    self.state.done_computer_fen = None
                    self.state.done_move = chess.Move.null()
                    self.state.pop_move()
                    if self.picotutor_mode():
                        if self.state.best_move_posted:
                            await self.state.picotutor.pop_posted_engine_move(
                                self.state.game
                            )  # bestmove already sent to tutor
                            self.state.best_move_posted = False
                        await self.state.picotutor.pop_last_move(self.state.game)  # no switch of sides
                    logger.info(
                        "user move while computer move is displayed, reverting to: %s",
                        self.state.game.fen(),
                    )
                else:
                    handled_fen = False
                    logger.error("last_legal_fens not cleared: %s", self.state.game.fen())
            elif self.state.interaction_mode == Mode.REMOTE:
                if self.state.is_not_user_turn():
                    self.state.pop_move()
                    if self.picotutor_mode():
                        if self.state.best_move_posted:
                            await self.state.picotutor.pop_posted_engine_move(
                                self.state.game
                            )  # bestmove already sent to tutor
                            self.state.best_move_posted = False
                        await self.state.picotutor.pop_last_move(self.state.game)
                    logger.info("user move in remote turn, reverting to: %s", self.state.game.fen())
                elif self.state.done_computer_fen:
                    self.state.done_computer_fen = None
                    self.state.done_move = chess.Move.null()
                    self.state.pop_move()
                    if self.picotutor_mode():
                        if self.state.best_move_posted:
                            await self.state.picotutor.pop_posted_engine_move(
                                self.state.game
                            )  # bestmove already sent to tutor
                            self.state.best_move_posted = False
                        await self.state.picotutor.pop_last_move(self.state.game)
                    logger.info(
                        "user move while remote move is displayed, reverting to: %s",
                        self.state.game.fen(),
                    )
                else:
                    handled_fen = False
                    logger.error("last_legal_fens not cleared: %s", self.state.game.fen())
            else:
                self.state.pop_move()
                if self.picotutor_mode():
                    if self.state.best_move_posted:
                        await self.state.picotutor.pop_posted_engine_move(self.state.game)  # bestmove already sent to tutor
                        self.state.best_move_posted = False
                    await self.state.picotutor.pop_last_move(self.state.game)
                    # just to be sure set fen pos.
                    # @todo - check valid here - dont reset position if valid
                    await self.set_picotutor_position()
                logger.info("wrong color move -> sliding, reverting to: %s", self.state.game.fen())
            legal_moves = list(_move_board.legal_moves)
            move = legal_moves[state.last_legal_fens.index(fen)]
            ok = await self.user_move(
                move,
                sliding=True,
                legal_fens_before_move=list(self.state.last_legal_fens),
            )
            if not ok:
                handled_fen = False

        # allow playing/correcting moves for pico's side in TRAINING mode:
        elif fen in legal_fens_pico and self.state.interaction_mode in (Mode.TRAINING, Mode.PGNREPLAY):
            legal_moves = list(_move_board.legal_moves)
            move = legal_moves[legal_fens_pico.index(fen)]

            if self.state.done_computer_fen:
                if fen == self.state.done_computer_fen:
                    pass
                else:
                    if self.state.interaction_mode == Mode.PGNREPLAY:
                        # its a legal move, so let the user deviate from PGN replay but stop autoplay
                        self._set_pgn_replay_autoplay(False)
                    else:  # TRAINING mode as before, user did an alternativ move for Pico engine
                        await DisplayMsg.show(Message.WRONG_FEN())  # display set pieces/pico's move
                        await asyncio.sleep(3)
                        # display set pieces again and accept new players move as pico's move
                        await DisplayMsg.show(
                            Message.ALTERNATIVE_MOVE(game=self.state.game.copy(), play_mode=self.state.play_mode)
                        )
                        await asyncio.sleep(2)
                        await DisplayMsg.show(
                            Message.COMPUTER_MOVE(
                                move=move,
                                ponder=False,
                                game=self.state.game_copy(),
                                wait=False,
                                is_user_move=False,
                            )
                        )
                        await asyncio.sleep(2)
            logger.debug("user move did a move for pico")

            ok = await self.user_move(
                move,
                sliding=False,
                legal_fens_before_move=list(self.state.legal_fens),
            )
            if not ok:
                handled_fen = False

        # standard legal move
        elif fen in self.state.legal_fens and fen != self.state.done_computer_fen:
            # Verify the move is actually legal from the CURRENT position.
            # legal_fens may be stale if left over from a previous game that
            # executed concurrently (asyncio.create_task per event).
            # legal_fens_pico is freshly computed from self.state.game at the
            # top of this function and acts as a reliable staleness detector.
            # Use its index to avoid stale-index mismatches too.
            if fen not in legal_fens_pico:
                logger.warning(
                    "process_fen: discarding stale legal_fens entry %s "
                    "(not legal from current position %s)",
                    fen,
                    self.state.game.fen(),
                )
                handled_fen = False
            else:
                logger.debug("standard move detected")
                self.state.newgame_happened = False
                legal_moves = list(_move_board.legal_moves)
                move = legal_moves[legal_fens_pico.index(fen)]
                ok = await self.user_move(
                    move,
                    sliding=False,
                    legal_fens_before_move=list(self.state.legal_fens),
                )
                if not ok:
                    handled_fen = False

        # molli: allow direct play of an alternative move for pico
        elif (
            fen in legal_fens_pico
            and fen not in self.state.legal_fens
            and fen != self.state.done_computer_fen
            and self.state.done_computer_fen
            and self.state.interaction_mode in (Mode.NORMAL, Mode.BRAIN)
            and not self.online_mode()
            and not self.emulation_mode()
            and not self.pgn_mode()
            and self.state.dgtmenu.get_game_altmove()
            and not self.state.takeback_active
        ):
            legal_moves = list(_move_board.legal_moves)
            self.state.done_move = legal_moves[legal_fens_pico.index(fen)]
            await DisplayMsg.show(
                Message.ALTERNATIVE_MOVE(game=self.state.game.copy(), play_mode=self.state.play_mode)
            )
            await asyncio.sleep(1.5)
            if self.state.done_move:
                await DisplayMsg.show(
                    Message.COMPUTER_MOVE(
                        move=self.state.done_move,
                        ponder=False,
                        game=self.state.game_copy(),
                        wait=False,
                        is_user_move=False,
                    )
                )
                await asyncio.sleep(1.5)
            await DisplayMsg.show(Message.COMPUTER_MOVE_DONE())
            logger.info("user did a move for pico")
            if self.state.best_move_posted and self.picotutor_mode():
                # issue 86 - user force alt direct move for pico - pop comp move
                valid = await self.state.picotutor.pop_last_move(self.state.game)
            else:
                valid = True
            # if valid is True tutor board and game are in sync (no comp move)
            # now proceed and push the forced direct alt move to both
            self.state.best_move_posted = False
            self.state.best_move_displayed = None
            self.state.push_move(self.state.done_move)
            self._update_variant_shared()
            if self.picotutor_mode():
                if valid:
                    valid = await self.state.picotutor.push_move(self.state.done_move, self.state.game)
                if not valid:
                    await self.set_picotutor_position()
            self.state.done_computer_fen = None
            self.state.done_move = chess.Move.null()
            game_end = self.state.check_game_state()
            if game_end:
                self.state.legal_fens = []
                self.state.legal_fens_after_cmove = []
                if self.online_mode():
                    await self.stop_search_and_clock()
                    self.state.stop_fen_timer()
                await self.stop_search_and_clock()
                self.game_end_event()
                await DisplayMsg.show(game_end)
            else:
                self.state.searchmoves.reset()
                self.state.time_control.add_time(not self.state.game.turn)

                # molli new tournament time control
                if (
                    self.state.time_control.moves_to_go_orig > 0
                    and (self.state.game.fullmove_number - 1) == self.state.time_control.moves_to_go_orig
                ):
                    self.state.time_control.add_game2(not self.state.game.turn)
                    t_player = False
                    msg = Message.TIMECONTROL_CHECK(
                        player=t_player,
                        movestogo=self.state.time_control.moves_to_go_orig,
                        time1=self.state.time_control.game_time,
                        time2=self.state.time_control.game_time2,
                    )
                    await DisplayMsg.show(msg)

                await self.state.start_clock()

            self.state.legal_fens = compute_legal_fens(
                self.state.game, self.state.get_variant_board()
            )  # calc. new legal moves based on alt. move
            self.state.last_legal_fens = []

        # Player has done the computer or remote move on the board
        elif fen == self.state.done_computer_fen:
            logger.info("done move detected")
            assert self.state.interaction_mode in (
                Mode.NORMAL,
                Mode.BRAIN,
                Mode.REMOTE,
                Mode.TRAINING,
                Mode.PGNREPLAY,
            ), (
                "wrong mode: %s" % self.state.interaction_mode
            )
            await DisplayMsg.show(Message.COMPUTER_MOVE_DONE())

            self.state.best_move_posted = False
            self.state.push_move(self.state.done_move)
            self._update_variant_shared()
            # Keep this clear after push_move(): analysis gating uses done_computer_fen
            # to block stale analysis while waiting for the engine move to be executed.
            self.state.done_computer_fen = None
            self.state.done_move = chess.Move.null()

            if self.online_mode() or self.emulation_mode():
                # for online or emulation engine the user time alraedy runs with move announcement
                # => subtract time between announcement and execution
                end_time_cmove_done = time.time()
                cmove_time = math.floor(end_time_cmove_done - self.state.start_time_cmove_done)
                if cmove_time > 0:
                    self.state.time_control.sub_online_time(self.state.game.turn, cmove_time)
                cmove_time = 0
                self.state.start_time_cmove_done = 0

            game_end = self.state.check_game_state()
            if game_end:
                await self.update_elo(game_end.result)
                self.state.legal_fens = []
                self.state.legal_fens_after_cmove = []
                if self.online_mode():
                    await self.stop_search_and_clock()
                    self.state.stop_fen_timer()
                await self.stop_search_and_clock()
                if not self.pgn_mode():
                    self.game_end_event()
                    await DisplayMsg.show(game_end)
            else:
                self.state.searchmoves.reset()

                self.state.time_control.add_time(not self.state.game.turn)

                # molli new tournament time control
                if (
                    self.state.time_control.moves_to_go_orig > 0
                    and (self.state.game.fullmove_number - 1) == self.state.time_control.moves_to_go_orig
                ):
                    self.state.time_control.add_game2(not self.state.game.turn)
                    t_player = False
                    msg = Message.TIMECONTROL_CHECK(
                        player=t_player,
                        movestogo=self.state.time_control.moves_to_go_orig,
                        time1=self.state.time_control.game_time,
                        time2=self.state.time_control.game_time2,
                    )
                    await DisplayMsg.show(msg)

                if self.state.game.fullmove_number < 1:
                    ModeInfo.reset_opening()
                opening_message = self._current_opening_message()
                if opening_message is not None:
                    await DisplayMsg.show(opening_message)
                    await asyncio.sleep(0.7)

                if not self.online_mode() or self.state.game.fullmove_number > 1:
                    await self.state.start_clock()
                else:
                    await DisplayMsg.show(Message.EXIT_MENU())  # show clock
                    end_time_cmove_done = 0

                self.state.legal_fens = compute_legal_fens(self.state.game, self.state.get_variant_board())
                self.start_brain_hint_timer()

                if self.pgn_mode():
                    log_pgn(self.state)
                    if self.state.game.turn == chess.WHITE:
                        if self.state.max_guess_white > 0:
                            if self.state.no_guess_white > self.state.max_guess_white:
                                self.state.last_legal_fens = []
                                await self.get_next_pgn_move()
                        else:
                            self.state.last_legal_fens = []
                            await self.get_next_pgn_move()
                    elif self.state.game.turn == chess.BLACK:
                        if self.state.max_guess_black > 0:
                            if self.state.no_guess_black > self.state.max_guess_black:
                                self.state.last_legal_fens = []
                                await self.get_next_pgn_move()
                        else:
                            self.state.last_legal_fens = []
                            await self.get_next_pgn_move()

            self.state.last_legal_fens = []
            self.state.newgame_happened = False

        # molli: Premove/fast move: Player has done the computer move and his own move in rapid sequence
        elif (
            fen in self.state.legal_fens_after_cmove
            and self.state.flag_premove
            and self.state.done_move != chess.Move.null()
        ):  # and self.state.interaction_mode in (Mode.NORMAL, Mode.BRAIN, Mode.TRAINING):
            logger.info("standard move after computer move detected")
            # molli: execute computer move first
            self.state.push_move(self.state.done_move)
            self._update_variant_shared()
            self.state.done_computer_fen = None
            self.state.done_move = chess.Move.null()
            self.state.best_move_posted = False
            self.state.searchmoves.reset()

            self.state.time_control.add_time(not self.state.game.turn)
            # molli new tournament time control
            if (
                self.state.time_control.moves_to_go_orig > 0
                and (self.state.game.fullmove_number - 1) == self.state.time_control.moves_to_go_orig
            ):
                self.state.time_control.add_game2(not self.state.game.turn)
                t_player = False
                msg = Message.TIMECONTROL_CHECK(
                    player=t_player,
                    movestogo=self.state.time_control.moves_to_go_orig,
                    time1=self.state.time_control.game_time,
                    time2=self.state.time_control.game_time2,
                )
                await DisplayMsg.show(msg)

            self.state.last_legal_fens = []
            self.state.legal_fens_after_cmove = []
            self.state.legal_fens = compute_legal_fens(
                self.state.game, self.state.get_variant_board()
            )  # molli new legal fance based on cmove

            # standard user move handling
            legal_moves = list(_move_board.legal_moves)
            move = legal_moves[state.legal_fens.index(fen)]
            ok = await self.user_move(
                move,
                sliding=False,
                legal_fens_before_move=list(self.state.legal_fens),
            )
            if ok:
                self.state.newgame_happened = False
            else:
                handled_fen = False

        # Check if this is a previous legal position and allow user to restart from this position
        else:
            if should_block_takeback(
                take_back_locked=self.state.take_back_locked,
                online_mode=self.online_mode(),
                emulation_mode=self.emulation_mode(),
                automatic_takeback=self.state.automatic_takeback,
                ponder_mode=self.state.interaction_mode == Mode.PONDER,
            ):
                handled_fen = False
            else:
                handled_fen = False
                game_copy = previous_position_matching_board_fen(
                    self.state.game, fen
                )
                if game_copy is not None:
                    # Racing Kings: if all moves have been popped we are back
                    # at the RK starting position.  Treat this as a NEW GAME,
                    # not a takeback, so that Event.NEW_GAME fires below.
                    if (
                        not game_copy.move_stack
                        and self.state.variant == "racingkings"
                        and fen == RK_STARTING_BOARD_FEN
                    ):
                        logger.info("racingkings: takeback reached starting position – treating as new game")
                    else:
                        handled_fen = True
                        logger.info("current game fen      : %s", self.state.game.fen())
                        logger.info("undoing game until fen: %s", fen)
                        self._invalidate_user_move_tasks()
                        await self.stop_search_and_clock()
                        while len(game_copy.move_stack) < len(self.state.game.move_stack):
                            self.state.pop_move()

                            if self.picotutor_mode():
                                if self.state.best_move_posted:  # molli computer move already sent to tutor!
                                    await self.state.picotutor.pop_posted_engine_move(self.state.game)
                                    self.state.best_move_posted = False
                                await self.state.picotutor.pop_last_move(self.state.game)

                        # its a complete new pos, delete saved values
                        self.state.done_computer_fen = None
                        self.state.done_move = self.state.pb_move = chess.Move.null()
                        self.state.searchmoves.reset()
                        self.state.takeback_active = True
                        self._update_variant_shared()  # sync check counts etc. after multi-pop
                        self._resume_game_after_takeback()
                        await self.set_wait_state(
                            Message.TAKE_BACK(game=self.state.game.copy())
                        )  # new: force stop no matter if picochess turn

                if self.pgn_mode():  # molli pgn
                    log_pgn(self.state)
                    if self.state.max_guess_white > 0:
                        if self.state.game.turn == chess.WHITE:
                            if self.state.no_guess_white > self.state.max_guess_white:
                                await self.get_next_pgn_move()
                    elif self.state.max_guess_black > 0:
                        if self.state.game.turn == chess.BLACK:
                            if self.state.no_guess_black > self.state.max_guess_black:
                                await self.get_next_pgn_move()

        logger.debug("fen: %s result: %s", fen, handled_fen)
        self.state.stop_fen_timer()
        if handled_fen:
            self.state.flag_startup = False
            self.state.error_fen = None
            self.state.fen_error_occured = False
            self.reset_setpieces_window_switch()
            if self.state.position_mode and self.state.delay_fen_error == 1:
                tutor_str = "POSOK"
                msg = Message.PICOTUTOR_MSG(eval_str=tutor_str)
                await DisplayMsg.show(msg)
                await asyncio.sleep(1)
                if not self.state.done_computer_fen:
                    await self.state.start_clock()
                await DisplayMsg.show(Message.EXIT_MENU())
            self.state.position_mode = False
        else:
            if is_starting_board_fen:
                pos960 = 518
                self.state.error_fen = None
                self.reset_setpieces_window_switch()
                if self.state.position_mode and self.state.delay_fen_error == 1:
                    tutor_str = "POSOK"
                    msg = Message.PICOTUTOR_MSG(eval_str=tutor_str)
                    await DisplayMsg.show(msg)
                    if not self.state.done_computer_fen:
                        await self.state.start_clock()
                self.state.position_mode = False
                await Observable.fire(Event.NEW_GAME(pos960=pos960))
            else:
                if self.state.setpieces_switch_anchor_fen and fen != self.state.setpieces_switch_anchor_fen:
                    self.state.setpieces_switch_armed = True
                self.state.error_fen = fen
                self.start_fen_timer()

    async def _think_after_current_user_move(
        self,
        move: chess.Move,
        expected_fen: str,
        expected_revision: int,
        message: Message | None,
    ) -> bool:
        """Start a search only while the requesting user-move task still owns the position."""
        if not user_move_task_matches_position(
            move,
            expected_fen,
            expected_revision,
            self.state.game,
            self.state.get_fen(),
            self.state.user_move_revision,
            self.state.done_computer_fen,
        ):
            logger.info("skipping obsolete search after user move [%s]", move)
            return False
        await self.think(
            message,
            user_move_owner=(move, expected_fen, expected_revision),
        )
        return True

    def _invalidate_user_move_tasks(self) -> int:
        """Invalidate delayed feedback and searches owned by an earlier user move."""
        self.state.user_move_revision += 1
        return self.state.user_move_revision

    def _clear_pending_engine_move(self) -> None:
        """Release an announced move before requesting its replacement."""
        self.state.done_computer_fen = None
        self.state.done_move = chess.Move.null()

    def _publish_user_move_legal_fens(self, legal_fens_before_move: list[Any]) -> None:
        """Make replacement positions available as soon as a user move is pushed."""
        self.state.last_legal_fens = legal_fens_before_move
        if self.state.interaction_mode in (
            Mode.NORMAL,
            Mode.BRAIN,
            Mode.REMOTE,
            Mode.TRAINING,
        ):
            self.state.legal_fens = []
        else:
            self.state.legal_fens = compute_legal_fens(
                self.state.game,
                self.state.get_variant_board(),
            )

    async def user_move(
        self,
        move: chess.Move,
        sliding: bool,
        legal_fens_before_move: list[Any] | None = None,
    ) -> bool:
        """Handle an user move."""

        eval_str = ""
        pending_picotutor_msgs: list[tuple[Message, float | None]] = []
        opening_handled_before_search = False

        self.state.take_back_locked = False

        logger.info("user move [%s] sliding: %s", move, sliding)
        game_ending = ModeInfo.get_game_ending()
        if should_reject_user_move_after_game_end(
            self.state.interaction_mode, self.state.game_declared, game_ending
        ):
            logger.info(
                "ignoring user move [%s] after game end: mode=%s declared=%s result=%s",
                move,
                self.state.interaction_mode,
                self.state.game_declared,
                game_ending,
            )
            return False

        # Use variant board for legality check (atomic has different legal moves after explosions)
        move_check_board = self.state.get_move_check_board()
        if move not in move_check_board.legal_moves:
            logger.warning("illegal move [%s]", move)
            return False
        else:
            if (
                self.state.dgtmenu.get_picocoach() == PicoCoach.COACH_BRAIN
                and self.state.interaction_mode == Mode.NORMAL
                and self.state.brain_required_piece_type is not None
                and not sliding
            ):
                moved_piece_type = self.state.game.piece_type_at(move.from_square)
                if moved_piece_type != self.state.brain_required_piece_type:
                    logger.info(
                        "Brain and hand: wrong piece type (expected %s, got %s)",
                        self.state.brain_required_piece_type,
                        moved_piece_type,
                    )
                    await DisplayMsg.show(Message.PICOTUTOR_MSG(eval_str="BRAIN_WRONG"))
                    await asyncio.sleep(1)
                    await DisplayMsg.show(
                        Message.PICOTUTOR_MSG(
                            eval_str="BRAIN_" + self._piece_type_name(self.state.brain_required_piece_type)
                        )
                    )
                    return False

            self._release_coach_position_mode_for_move()
            user_move_revision = self._invalidate_user_move_tasks()
            self.cancel_brain_hint_timer(preserve_best_move=True, resume_paused_clock=False)
            self.state.brain_required_piece_type = None
            if self.state.hand_coach_task and not self.state.hand_coach_task.done():
                self.state.hand_coach_task.cancel()
            self.state.hand_coach_task = None

            if self.state.interaction_mode == Mode.BRAIN:
                ponder_hit = move == self.state.pb_move
                logger.info(
                    "pondering move: [%s] res: Ponder%s",
                    self.state.pb_move,
                    "Hit" if ponder_hit else "Miss",
                )
            else:
                ponder_hit = False
            if sliding and ponder_hit:
                logger.warning("sliding detected, turn ponderhit off")
                ponder_hit = False

            # before pushing a user move check if we got a ponder hit - for analysis modes
            if not self.eng_plays():
                ponder_hit = False
                # which analyser to use? same logic as in analyse() - try tutor first
                if self.is_coach_analyser() and self.state.picotutor.can_use_coach_analyser():
                    play_result = await self.state.picotutor.get_analysis_chosen_move(move)
                    if play_result.info:
                        # ponder hit from tutor list - make an info_list to trigger ponder hit below
                        info_list = [play_result.info]  # construct a list for "pv first" below
                    else:
                        info_list = None  # no ponder hit in tutor
                    analysed_fen = getattr(play_result, "analysed_fen", "")
                else:
                    # tutor not replacing engine analysis, so try normal engine analysis
                    info_result = await self.engine.get_analysis(self.state.game)
                    info_list: list[InfoDict] | None = info_result.get("info")
                    analysed_fen = info_result.get("fen")
                if info_list:
                    info = info_list[0]  # pv first
                    if info and "pv" in info:
                        pv_moves = info["pv"]
                        expected_ponder_move = pv_moves[0] if pv_moves else chess.Move.null()
                        if move == expected_ponder_move:
                            # ponder hit! user chose the best ponder move
                            ponder_reply = pv_moves[1] if pv_moves and len(pv_moves) > 1 else chess.Move.null()
                            send_pv = pv_moves and len(pv_moves) > 1
                            # Fast clock feedback only; not a full analysis update.
                            await self.send_analyse(
                                info, analysed_fen, send_pv=bool(send_pv), ponder_move=ponder_reply
                            )
                            if not send_pv:
                                self.state.pb_move = chess.Move.null()
                                self.state.best_sent_depth.reset()
                            ponder_hit = True
                if not ponder_hit:
                    # user deviated from analysed line (or no info available) - reset cache
                    self.state.best_sent_depth.reset()

            # Clock logic after user move
            #
            await self.stop_search_and_clock(ponder_hit=ponder_hit)
            if (
                self.state.interaction_mode in (Mode.NORMAL, Mode.BRAIN, Mode.OBSERVE, Mode.REMOTE, Mode.TRAINING)
                and not sliding
            ):
                self.state.time_control.add_time(self.state.game.turn)
                # molli new tournament time control
                if (
                    self.state.time_control.moves_to_go_orig > 0
                    and self.state.game.fullmove_number == self.state.time_control.moves_to_go_orig
                ):
                    self.state.time_control.add_game2(self.state.game.turn)
                    t_player = True
                    msg = Message.TIMECONTROL_CHECK(
                        player=t_player,
                        movestogo=self.state.time_control.moves_to_go_orig,
                        time1=self.state.time_control.game_time,
                        time2=self.state.time_control.game_time2,
                    )
                    await DisplayMsg.show(msg)
                if self.online_mode():
                    # molli for online pseudo time sync
                    if self.state.online_decrement > 0:
                        self.state.time_control.sub_online_time(self.state.game.turn, self.state.online_decrement)

            #
            # Remember game_before user move for picotutor thread
            # And for sending USER_MOVE_DONE below
            #
            # Tutor feedback needs the complete position before the move,
            # but none of the preceding move history.
            game_before = self.state.game.copy(stack=False)
            self.state.push_move(move)  # this is where user move is made
            if legal_fens_before_move is not None:
                # Publish the previous position's alternatives immediately.
                # A DGT replacement move may arrive while Tutor feedback is
                # awaiting display; delayed process_fen cleanup must not leave
                # that event looking like a stale current-position move.
                self._publish_user_move_legal_fens(legal_fens_before_move)
            user_move_fen = self.state.get_fen()
            user_move_owner = (move, user_move_fen, user_move_revision)
            self._set_game_started(True)
            self._update_variant_shared()
            logger.debug("user did a move for user")
            #
            # Set and reset information after user move
            #
            self.state.done_computer_fen = None
            self.state.done_move = chess.Move.null()
            self.state.searchmoves.reset()  # empty list of excluded engine rootmoves
            self.state.ignore_next_engine_move = False  # real user move has been made

            #
            # Picotutor check
            #
            eval_str = ""
            if self.picotutor_mode() and not self.state.position_mode:
                l_mate = ""
                t_hint_move = chess.Move.null()
                valid = await self.state.picotutor.push_move(move, self.state.game)
                regenerate_pgn_replay_tutor = (
                    self.state.interaction_mode != Mode.PGNREPLAY
                    or self.state.pgn_replay_tutor_regeneration
                )
                # get evalutaion result and give user feedback
                if self.state.dgtmenu.get_picowatcher() and regenerate_pgn_replay_tutor:
                    if valid:
                        eval_str, l_mate = self.state.picotutor.get_user_move_eval(
                            allow_low_depth_blunder=self.emulation_mode()
                        )
                    else:
                        # invalid move from tutor side!? Something went wrong
                        eval_str = "ER"
                        await self.set_picotutor_position()
                        l_mate = ""
                        eval_str = ""  # no error message
                    if eval_str != "" and self.state.last_move != move:  # molli takeback_mame
                        msg = Message.PICOTUTOR_MSG(eval_str=eval_str)
                        delay = 3.0 if "??" in eval_str else 1.0
                        pending_picotutor_msgs.append((msg, delay))
                    if l_mate:
                        n_mate = int(l_mate)
                    else:
                        n_mate = 0
                    if n_mate < 0:
                        msg_str = "USRMATE_" + str(abs(n_mate))
                        msg = Message.PICOTUTOR_MSG(eval_str=msg_str)
                        pending_picotutor_msgs.append((msg, 1.5))
                    elif n_mate > 1:
                        n_mate = n_mate - 1
                        msg_str = "PICMATE_" + str(abs(n_mate))
                        msg = Message.PICOTUTOR_MSG(eval_str=msg_str)
                        pending_picotutor_msgs.append((msg, 1.5))
                    # get additional info in case of blunder
                    if eval_str == "??" and self.state.last_move != move:
                        t_hint_move = chess.Move.null()
                        threat_move = chess.Move.null()
                        (
                            t_hint_move,
                            t_pv_user_move,
                        ) = self.state.picotutor.get_user_move_info()

                        try:
                            # move 0 was bad because of threat 1 response
                            threat_move = t_pv_user_move[1]
                        except IndexError:
                            threat_move = chess.Move.null()

                        if threat_move != chess.Move.null():
                            game_tutor = game_before.copy(stack=False)
                            game_tutor.push(move)
                            san_move = game_tutor.san(threat_move)
                            game_tutor.push(t_pv_user_move[1])  # 1st counter move

                            tutor_str = "THREAT" + san_move
                            msg = Message.PICOTUTOR_MSG(eval_str=tutor_str, game=game_tutor)
                            pending_picotutor_msgs.append((msg, 5.0))

                        if t_hint_move != chess.Move.null():
                            game_tutor = game_before.copy(stack=False)
                            san_move = game_tutor.san(t_hint_move)
                            game_tutor.push(t_hint_move)
                            tutor_str = "HINT" + san_move
                            msg = Message.PICOTUTOR_MSG(eval_str=tutor_str, game=game_tutor)
                            pending_picotutor_msgs.append((msg, 5.0))

                if self.state.game.fullmove_number < 1:
                    ModeInfo.reset_opening()

            #
            # Start engine think
            #
            if self.state.interaction_mode in (Mode.NORMAL, Mode.BRAIN, Mode.TRAINING):
                msg = Message.USER_MOVE_DONE(
                    move=move, fen=game_before.fen(), turn=game_before.turn, game=self.state.game.copy()
                )
                tutor_reveal_move = None
                if self.picotutor_mode():
                    if (
                        self.state.dgtmenu.get_picocoach() == PicoCoach.COACH_HAND
                        and self.state.last_hand_coach_move is not None
                    ):
                        tutor_reveal_move = self.state.last_hand_coach_move
                        self.state.last_hand_coach_move = None
                    elif (
                        self.state.dgtmenu.get_picocoach() == PicoCoach.COACH_BRAIN
                        and self.state.brain_best_move is not None
                    ):
                        tutor_reveal_move = self.state.brain_best_move
                        self.state.brain_best_move = None
                game_end = self.state.check_game_state()
                if game_end:
                    await self.update_elo(game_end.result)
                    # molli: for online/emulation mode we have to publish this move as well to the engine
                    if self.online_mode():
                        logger.info("starting think()")
                        await self._deliver_picotutor_messages(
                            pending_picotutor_msgs, user_move_owner
                        )
                        await self._think_after_current_user_move(
                            move, user_move_fen, user_move_revision, msg
                        )
                    elif self.emulation_mode():
                        if self.engine is not None and user_move_task_matches_position(
                            *user_move_owner,
                            self.state.game,
                            self.state.get_fen(),
                            self.state.user_move_revision,
                            self.state.done_computer_fen,
                        ):
                            await self.engine.send_terminal_position_to_mame(self.state.game.copy())
                        else:
                            logger.info("skipping obsolete or unavailable MAME terminal move [%s]", move)
                        await DisplayMsg.show(msg)
                        await self._deliver_picotutor_messages(
                            pending_picotutor_msgs, user_move_owner
                        )
                        self.game_end_event()
                        await DisplayMsg.show(game_end)
                        self.state.legal_fens_after_cmove = []  # molli
                    else:
                        await DisplayMsg.show(msg)
                        await self._deliver_picotutor_messages(
                            pending_picotutor_msgs, user_move_owner
                        )
                        self.game_end_event()
                        await DisplayMsg.show(game_end)
                        self.state.legal_fens_after_cmove = []  # molli
                else:
                    if self.state.interaction_mode in (Mode.NORMAL, Mode.TRAINING):
                        if not self.state.check_game_state():
                            # molli: automatic takeback of blunder moves for mame engines
                            if self.emulation_mode() and eval_str == "??" and self.state.last_move != move:
                                # Ensure tutor feedback is shown before takeback prompt/move display.
                                await self._deliver_picotutor_messages(
                                    pending_picotutor_msgs, user_move_owner
                                )
                                # molli: do not send move to engine
                                # wait for take back or lever button in case of no takeback
                                if self.board_type == dgt.util.EBoard.NOEBOARD:
                                    await Observable.fire(Event.TAKE_BACK(take_back="PGN_TAKEBACK"))
                                else:
                                    self.state.takeback_active = True
                                    self.state.automatic_takeback = True  # to be reset in think!
                                    await self.set_wait_state(Message.TAKE_BACK(game=self.state.game.copy()))
                            else:
                                # send move to engine
                                logger.debug("starting think()")
                                if self.state.takeback_active and self.state.is_not_user_turn():
                                    # Allow additional takebacks to settle before starting engine search.
                                    await asyncio.sleep(0.6)
                                if self.state.is_not_user_turn():
                                    opening_handled_before_search = await self._announce_user_move_before_search(
                                        msg, tutor_reveal_move
                                    )
                                    await self._deliver_picotutor_messages(
                                        pending_picotutor_msgs, user_move_owner
                                    )
                                    await self._think_after_current_user_move(
                                        move, user_move_fen, user_move_revision, None
                                    )
                                else:
                                    logger.debug("skipping think() after takeback debounce: user turn")
                    else:
                        assert self.state.interaction_mode == Mode.BRAIN
                        logger.debug("new implementation of ponderhit - starting think")
                        if self.state.takeback_active and self.state.is_not_user_turn():
                            # Allow additional takebacks to settle before starting engine search.
                            await asyncio.sleep(0.6)
                        if self.state.is_not_user_turn():
                            opening_handled_before_search = await self._announce_user_move_before_search(
                                msg, tutor_reveal_move
                            )
                            await self._deliver_picotutor_messages(
                                pending_picotutor_msgs, user_move_owner
                            )
                            await self._think_after_current_user_move(
                                move, user_move_fen, user_move_revision, None
                            )
                        else:
                            logger.debug("skipping think() after takeback debounce: user turn")

                self.state.last_move = move
            elif self.state.interaction_mode == Mode.REMOTE:
                msg = Message.USER_MOVE_DONE(
                    move=move, fen=game_before.fen(), turn=game_before.turn, game=self.state.game.copy()
                )
                game_end = self.state.check_game_state()
                await DisplayMsg.show(msg)
                await self._deliver_picotutor_messages(
                    pending_picotutor_msgs, user_move_owner
                )
                if game_end:
                    self.game_end_event()
                    await DisplayMsg.show(game_end)
                else:
                    await self.observe()
            elif self.state.interaction_mode == Mode.OBSERVE:
                msg = Message.REVIEW_MOVE_DONE(
                    move=move, fen=game_before.fen(), turn=game_before.turn, game=self.state.game.copy()
                )
                game_end = self.state.check_game_state()
                if game_end:
                    await DisplayMsg.show(msg)
                    await self._deliver_picotutor_messages(
                        pending_picotutor_msgs, user_move_owner
                    )
                    self.game_end_event()
                    await DisplayMsg.show(game_end)
                else:
                    await DisplayMsg.show(msg)
                    await self._deliver_picotutor_messages(
                        pending_picotutor_msgs, user_move_owner
                    )
                    await self.observe()
            else:  # self.state.interaction_mode in (Mode.ANALYSIS, Mode.KIBITZ, Mode.PONDER, Mode.PGNREPLAY):
                msg = Message.REVIEW_MOVE_DONE(
                    move=move, fen=game_before.fen(), turn=game_before.turn, game=self.state.game.copy()
                )
                game_end = self.state.check_game_state()
                if game_end:
                    await DisplayMsg.show(msg)
                    await self._deliver_picotutor_messages(
                        pending_picotutor_msgs, user_move_owner
                    )
                    self.game_end_event()
                    await DisplayMsg.show(game_end)
                else:
                    await DisplayMsg.show(msg)
                    await self._deliver_picotutor_messages(
                        pending_picotutor_msgs, user_move_owner
                    )
                    await self.analyse()

            await self._deliver_picotutor_messages(
                pending_picotutor_msgs, user_move_owner
            )

            #
            # More picotutor logic (eval above)
            # @todo check this one also
            #
            if (
                self.picotutor_mode()
                and not self.state.position_mode
                and not self.state.takeback_active
                and not self.state.automatic_takeback
            ):
                if not opening_handled_before_search:
                    opening_message = self._current_opening_message()
                    if opening_message is not None:
                        await DisplayMsg.show(opening_message)
                        await asyncio.sleep(0.7)

                if self.state.dgtmenu.get_picocomment() != PicoComment.COM_OFF and not game_end:
                    game_comment = ""
                    game_comment = self.state.picotutor.get_game_comment(
                        pico_comment=self.state.dgtmenu.get_picocomment(),
                        com_factor=self.state.dgtmenu.get_comment_factor(),
                    )
                    if game_comment:
                        await DisplayMsg.show(Message.SHOW_TEXT(text_string=game_comment))
                        await asyncio.sleep(0.7)
            self.state.takeback_active = False

            return True

    def _current_opening_message(self) -> Message | None:
        """Build and cache the opening message for the current tutor position."""
        if not (self.picotutor_mode() and self.state.dgtmenu.get_picoexplorer()):
            return None
        opening_eco, opening_name, _, opening_in_book = self.state.picotutor.get_opening()
        if not (opening_in_book and opening_name):
            return None
        logger.debug("opening book set to %s", opening_name)
        ModeInfo.set_opening(self.state.book_in_use, str(opening_name), opening_eco)
        return Message.SHOW_TEXT(text_string=opening_name)

    async def _announce_user_move_before_search(
        self,
        user_move_message: Message,
        tutor_reveal_move: chess.Move | None,
    ) -> bool:
        """Announce a user move and its opening before starting engine search."""
        opening_handled = (
            self.picotutor_mode()
            and not self.state.position_mode
            and not self.state.takeback_active
            and not self.state.automatic_takeback
        )
        opening_message = self._current_opening_message() if opening_handled else None
        for message in user_move_pre_search_messages(
            user_move_message,
            tutor_reveal_move=tutor_reveal_move,
            opening_message=opening_message,
        ):
            await DisplayMsg.show(message)
        return opening_handled

    async def _deliver_picotutor_messages(
        self,
        pending_messages: list[tuple[Message, float | None]],
        user_move_owner: tuple[chess.Move, str, int] | None = None,
    ) -> None:
        """Send queued feedback while its user move still owns the position."""
        if not pending_messages:
            return
        for message, delay in pending_messages:
            if user_move_owner is not None and not user_move_task_matches_position(
                *user_move_owner,
                self.state.game,
                self.state.get_fen(),
                self.state.user_move_revision,
                self.state.done_computer_fen,
            ):
                logger.info(
                    "discarding obsolete Tutor messages after user move [%s]",
                    user_move_owner[0],
                )
                pending_messages.clear()
                return
            await DisplayMsg.show(message)
            if delay and delay > 0:
                await asyncio.sleep(delay)
        pending_messages.clear()

    async def observe(self) -> InfoDict | None:
        """Start a new ponder search on the current game."""
        info = await self.analyse()
        await self.state.start_clock()
        return info

    async def update_elo(self, result):
        if self.engine.is_adaptive:
            self.state.rating = await self.engine.update_rating(
                self.state.rating,
                determine_result(result, self.state.play_mode, self.state.game.turn == chess.WHITE),
            )

    async def update_elo_display(self):
        if self.emulation_mode():
            await DisplayMsg.show(Message.SYSTEM_INFO(info={"rspeed": self.state.dgtmenu.get_engine_rspeed()}))
        if self.state.interaction_mode in (Mode.NORMAL, Mode.BRAIN, Mode.TRAINING):
            if self.engine.is_adaptive:
                await DisplayMsg.show(
                    Message.SYSTEM_INFO(
                        info={"user_elo": int(self.state.rating.rating), "engine_elo": self.engine.engine_rating}
                    )
                )
            elif self.engine.engine_rating > 0:
                user_elo = self.args.pgn_elo
                if self.state.rating is not None:
                    user_elo = str(int(self.state.rating.rating))
                await DisplayMsg.show(
                    Message.SYSTEM_INFO(info={"user_elo": user_elo, "engine_elo": self.engine.engine_rating})
                )

    def start_fen_timer(self):
        """Start the fen timer in case an unhandled fen string been received from board."""
        delay = 0
        if self.state.position_mode:
            delay = self.state.delay_fen_error  # if a fen error already occured don't wait too long for next check
        else:
            delay = 4
            self.state.delay_fen_error = 4
        self.state.fen_timer = AsyncRepeatingTimer(delay, self.expired_fen_timer, self.loop, repeating=False)
        self.state.fen_timer.start()
        self.state.fen_timer_running = True

    # Analysis routing has four main cases.
    # IMPORTANT: `analyse()` has two outputs:
    # 1) clock/DGT output via send_analyse() (depth-gated by best_sent_depth)
    # 2) web client output via send_web_analysis() (source-tagged engine/tutor).
    #
    # 1. Engine is playing and tutor is on:
    #   - Engine turn: use engine PlayingContinuousAnalysis (engine-thinking info).
    #   - User turn: stop engine ContinuousAnalysis and let Tutor own the only
    #     deep search.  Preserve the completed playing search as the latest
    #     clock/web Engine snapshot; publish fresh Tutor output to the web.
    # 2. Engine is playing and tutor is off:
    #   - User turn: use engine ContinuousAnalysis for clock updates.
    #   - Engine turn: use engine PlayingContinuousAnalysis.
    # 3. Engine is not playing and tutor is on:
    #   - Tutor (best engine ContinuousAnalysis) drives clock and web client output.
    # 4. Engine is not playing and tutor is off:
    #   - Engine ContinuousAnalysis drives clock and web client output.
    #
    # Goal: for clock-driving analysis we run only one deep analyser at a time:
    # A. picotutor best_engine ContinuousAnalysis
    #    - tutor-on analysis paths when it's user turn
    # B. engine ContinuousAnalysis
    #    - tutor-off analysis paths, especially when engine is not playing and we analyse both sides
    # C. engine PlayingContinuousAnalysis
    #    - engine-thinking path when it's engine's turn (used regardless of tutor on/off)
    # (ignore picotutor obvious_engine here; it is shallow helper analysis)
    def is_coach_analyser(self) -> bool:  # noqa: E306 - policy comment belongs directly above this helper
        """Return True when tutor analysis should replace engine analysis."""
        return decide_tutor_analysis(
            TutorAnalysisContext(
                interaction_mode=self.state.interaction_mode,
                pgn_mode=self.pgn_mode(),
                engine_should_skip_analyser=bool(self.engine and self.engine.should_skip_engine_analyser()),
                engine_is_playing=self.eng_plays(),
                is_user_turn=self.state.is_user_turn(),
            )
        )

    def need_engine_analyser(self) -> bool:
        """return true if engine is analysing moves based on PlayMode"""
        if self.state.position_checkpoint_restore_pending:
            return False
        if self.pgn_mode() or (self.engine and self.engine.should_skip_engine_analyser()):
            return False
        if self.playing_game_analysis_stopped():
            return False
        if self.eng_plays() and self.state.loaded_pgn_finished:
            return False
        # Save CPU at idle startup: skip analyser on the untouched standard
        # starting position until the game lifecycle has actually begun.
        if (
            self.eng_plays()
            and not self.state.game_started
            and self.state.variant == "chess"
            and self.state.game is not None
            and not self.state.game.move_stack
            and self.state.game.fen() == chess.STARTING_FEN
        ):
            return False
        # Engine move has already been selected/displayed but not pushed on the game yet.
        # In this waiting window the old position is stale, so avoid launching the
        # engine ContinuousAnalysis sister for it.
        if self.eng_plays() and self.state.done_computer_fen is not None:
            return False
        engine_thinking = bool(self.engine and self.engine.is_thinking())
        # reverse the first if in analyse(), meaning: it does not use tutor analysis
        result = not (self.is_coach_analyser() and self.state.picotutor.can_use_coach_analyser())
        # skip engine analyser when engine is thinking about its move
        # (engine play will get info from PlayingContinuousAnalyser instead)
        result = result and not (self.eng_plays() and not self.state.is_user_turn() and engine_thinking)
        return result

    def tutor_analysis_enabled_for_current_mode(self) -> bool:
        """Return whether tutor analysis should run for the current mode."""
        if not tutor_analysis_allowed_in_mode(self.state.interaction_mode):
            return False
        if self.playing_game_analysis_stopped():
            return False
        if self.eng_plays() and self.state.loaded_pgn_finished:
            return False
        return not (
            self.state.interaction_mode == Mode.PGNREPLAY
            and not self.state.pgn_replay_tutor_regeneration
        )

    def eng_plays(self) -> bool:
        """return true if engine is playing moves"""
        return bool(self.state.interaction_mode in (Mode.NORMAL, Mode.BRAIN, Mode.TRAINING))

    def playing_game_analysis_stopped(self) -> bool:
        """Return true when a completed playing-mode game must not analyse."""
        return should_stop_analysis_after_game_end(
            interaction_mode=self.state.interaction_mode,
            game_over=self.state.game.is_game_over(),
            game_declared=self.state.game_declared,
            game_ending=ModeInfo.get_game_ending(),
        )

    def _set_game_started(self, started: bool) -> None:
        """Update active-game lifecycle state and publish it to web clients."""
        started = bool(started)
        self.state.game_started = started
        self.shared.setdefault("system_info", {})
        if self.shared["system_info"].get("game_started") == started:
            return
        self.shared["system_info"]["game_started"] = started
        EventHandler.write_to_clients({"event": "SystemInfo", "msg": {"game_started": started}})

    def _publish_position_checkpoint_available(self) -> None:
        """Publish whether the current variant has a reusable checkpoint."""
        self.shared.setdefault("system_info", {})
        update = {
            "position_checkpoint_available": self.state.has_compatible_position_checkpoint(),
            "position_checkpoint_return_mode": (
                self.state.position_checkpoint_interaction_mode.name.lower()
                if self.state.position_checkpoint_interaction_mode is not None
                else None
            ),
        }
        self.shared["system_info"].update(update)
        EventHandler.write_to_clients({"event": "SystemInfo", "msg": update})

    def _clear_position_checkpoint(self) -> None:
        """End the temporary-analysis checkpoint and any pending physical restore."""
        restore_was_pending = self.state.position_checkpoint_restore_pending
        if restore_was_pending:
            self.state.stop_fen_timer()
            self.state.error_fen = None
            self.state.fen_error_occured = False
            self.state.position_mode = False
            self.state.delay_fen_error = 4
        self.state.clear_position_checkpoint()
        self._publish_position_checkpoint_available()

    async def _finish_position_checkpoint_restore(self) -> None:
        """Complete synchronization and return to the mode saved by the checkpoint."""
        if not self.state.claim_position_checkpoint_restore_completion():
            logger.debug("checkpoint restore completion already claimed or no longer pending")
            return
        return_event_queued = False
        try:
            logger.info("position checkpoint restore complete")
            return_mode = self.state.position_checkpoint_interaction_mode
            self.state.stop_fen_timer()
            self.state.error_fen = None
            self.state.fen_error_occured = False
            self.state.position_mode = False
            self.state.delay_fen_error = 4
            await DisplayMsg.show(Message.PICOTUTOR_MSG(eval_str="POSOK"))
            await asyncio.sleep(1)
            await DisplayMsg.show(Message.EXIT_MENU())
            self.state.position_checkpoint_restore_pending = False
            if return_mode is not None and return_mode != Mode.PONDER:
                logger.info("returning from temporary analysis to %s", return_mode)
                await Observable.fire(
                    Event.SET_INTERACTION_MODE(
                        mode=return_mode,
                        mode_text=self.state.dgttranslate.text(return_mode.value),
                        show_ok=True,
                    )
                )
                # The event is queued, not processed inline. Keep ownership
                # until that mode transition clears the checkpoint.
                return_event_queued = True
            else:
                await self._start_or_stop_analysis_as_needed()
        finally:
            if not return_event_queued:
                self.state.release_position_checkpoint_restore_completion()

    async def _save_position_checkpoint(self, return_mode: Mode) -> None:
        """Start a temporary-analysis checkpoint after entering PONDER."""
        if self.state.interaction_mode != Mode.PONDER:
            logger.warning("position checkpoints can only be saved in PONDER")
            return
        self.state.save_position_checkpoint(interaction_mode=return_mode)
        # Normally Tutor is already at this position because PONDER never
        # pushed moves to it. If the checkpoint is saved after the user has
        # already changed the PONDER position, establish that new anchor
        # once and then leave Tutor frozen there.
        if (
            self.state.picotutor is not None
            and not boards_match_position_and_history(self.state.picotutor.board, self.state.game)
        ):
            await self.state.picotutor.set_analysis_enabled(False)
            await self.state.picotutor.set_position(self.state.game.copy(), new_game=False)
        self._publish_position_checkpoint_available()
        logger.info(
            "temporary analysis checkpoint saved at %s for return to %s",
            self.state.get_fen(),
            return_mode,
        )

    async def _restore_position_checkpoint(self) -> None:
        """Restore the PONDER checkpoint, synchronize, and return to its saved mode."""
        if self.state.interaction_mode != Mode.PONDER:
            logger.warning("position checkpoints can only be restored in PONDER")
            return
        if not self.state.has_compatible_position_checkpoint():
            logger.warning("checkpoint restore requested without a compatible checkpoint")
            self._publish_position_checkpoint_available()
            return
        if (
            self.state.position_checkpoint_restore_pending
            or self.state.position_checkpoint_restore_completing
        ):
            logger.info("position checkpoint restore already in progress")
            return

        # Claim the complete restore transaction before its first await so
        # duplicate requests cannot start a second restore concurrently.
        self.state.position_checkpoint_restore_pending = True
        try:
            await self.engine.stop_analysis()
            self.state.stop_fen_timer()
            self.state.error_fen = None
            self.state.position_mode = False
            if not self.state.restore_position_checkpoint():
                self.state.position_checkpoint_restore_pending = False
                self._publish_position_checkpoint_available()
                return
        except Exception:
            self.state.position_checkpoint_restore_pending = False
            raise
        self._set_game_started(self.state.game_started)

        # Block all analyser output before the first await below.  The
        # logical position is restored now; the e-board may still show the
        # explored branch for an arbitrary amount of time.
        self.state.position_mode = True
        self._update_variant_shared()
        self.state.best_sent_depth.reset()
        self.state.done_computer_fen = None
        self.state.done_move = self.state.pb_move = chess.Move.null()
        self.state.searchmoves.reset()
        self.state.takeback_active = False
        self.state.automatic_takeback = False
        self.state.legal_fens = compute_legal_fens(
            self.state.game, self.state.get_variant_board()
        )
        self.state.legal_fens_after_cmove = []
        self.state.last_legal_fens = []
        await self.engine.newgame(self.state.engine_board_copy(), False)
        await DisplayMsg.show(Message.WEB_ANALYSIS(analysis=None))
        await DisplayMsg.show(self.state.new_game_msg(newgame=False))

        physical_fen = self.state.dgtmenu.get_dgt_fen() if self.state.dgtmenu is not None else ""
        if self.board_type == dgt.util.EBoard.NOEBOARD or physical_fen == self.state.get_board_fen():
            await self._finish_position_checkpoint_restore()
            return

        await self._start_or_stop_analysis_as_needed()
        await DisplayMsg.show(Message.WRONG_FEN())

    async def _set_ponder_turn(self, turn: chess.Color) -> None:
        """Change the current PONDER position's side to move."""
        physical_fen = self.state.dgtmenu.get_dgt_fen() if self.state.dgtmenu is not None else ""
        if (
            self.state.position_mode
            or self.state.fen_timer_running
            or (
                self.board_type != dgt.util.EBoard.NOEBOARD
                and physical_fen != self.state.get_board_fen()
            )
        ):
            logger.info("PONDER side change requires a settled e-board position")
            await DisplayMsg.show(Message.WRONG_FEN())
            return
        if not self.state.set_ponder_turn(turn):
            logger.warning("side change is only available in standard PONDER")
            return

        logger.info(
            "PONDER side changed to %s",
            "white" if turn == chess.WHITE else "black",
        )
        self.state.stop_fen_timer()
        self.state.error_fen = None
        self.state.fen_error_occured = False
        self.state.position_mode = False
        self.state.best_sent_depth.reset()
        self.state.done_computer_fen = None
        self.state.done_move = self.state.pb_move = chess.Move.null()
        self.state.searchmoves.reset()
        self.state.game_declared = False
        self.state.takeback_active = False
        self.state.automatic_takeback = False
        self.state.legal_fens = compute_legal_fens(self.state.game)
        self.state.legal_fens_after_cmove = []
        self.state.last_legal_fens = []
        await self.engine.newgame(self.state.engine_board_copy(), False)
        await DisplayMsg.show(Message.WEB_ANALYSIS(analysis=None))
        await DisplayMsg.show(Message.SHOW_TEXT(text_string="NEW_POSITION"))
        await DisplayMsg.show(self.state.new_game_msg(newgame=False))
        await self._start_or_stop_analysis_as_needed()

    def _set_pgn_replay_autoplay(self, enabled: bool, mode: Mode | None = None) -> None:
        """Update PGN replay autoplay and publish it to connected web clients."""
        enabled = bool(enabled)
        self.state.autoplay_pgn_file = enabled
        mode_name = (mode or self.state.interaction_mode).name.lower()
        self.shared.setdefault("system_info", {})
        update = {
            "interaction_mode": mode_name,
            "pgn_replay_autoplay": enabled,
        }
        self.shared["system_info"].update(update)
        EventHandler.write_to_clients({"event": "SystemInfo", "msg": update})

    def _set_pgn_replay_tutor_regeneration(self, enabled: bool, override: bool = False) -> None:
        """Update PGN replay tutor regeneration and publish it to web clients."""
        enabled = bool(enabled)
        self.state.pgn_replay_tutor_regeneration = enabled
        if override:
            self.state.pgn_replay_tutor_regeneration_override = enabled
        self.shared.setdefault("system_info", {})
        update = {"pgn_replay_tutor_regeneration": enabled}
        self.shared["system_info"].update(update)
        EventHandler.write_to_clients({"event": "SystemInfo", "msg": update})

    def _reset_loaded_pgn_lifecycle(self) -> None:
        """Clear PGN/replay state when starting a fresh playable game."""
        self.state.loaded_pgn_game = None
        self.state.loaded_pgn_filename = ""
        self.state.loaded_pgn_has_variations = False
        self.state.loaded_pgn_finished = False
        self.state.pgn_replay_tutor_regeneration = True
        self.state.pgn_replay_tutor_regeneration_override = None
        self.shared.pop("loaded_pgn_game", None)

    async def get_rid_of_engine_move(self):
        """in some mode switches we need to get rid of a move engine is thinking about"""
        if self.eng_plays() and self.engine.is_thinking():
            # force a move and skip it to get rid of engine thinking
            self.state.ignore_next_engine_move = True
            self.engine.force_move()
            await asyncio.sleep(0.5)  # wait for forced move to be handled

    async def _start_or_stop_analysis_as_needed(self):
        """start or stop engine analyser as needed (tutor handles this on its own)"""
        if self.engine:
            if self.need_engine_analyser():
                limit = Limit(depth=selected_engine_analysis_depth(self.eng_plays()))
                # Use variant board if available for correct position representation
                analysis_board = self.state.get_move_check_board()
                multipv = selected_engine_analysis_multipv(
                    self.state.interaction_mode,
                    self.engine.get_options(),
                )
                await self.engine.start_analysis(analysis_board, limit=limit, multipv=multipv)
            else:
                await self.engine.stop_analysis()

    def debug_pv_info(self, info: InfoDict):
        if info and "pv" in info and info["pv"]:
            logger.debug(
                "engine pv move: %s - depth %d - score %s",
                info.get("pv")[0].uci(),
                info.get("depth"),
                str(info["score"]),
            )
        else:
            logger.debug("empty InfoDict")

    async def analyse(self, triggered_by_timer: bool = False, allow_autoplay: bool = True) -> InfoDict | None:
        """analyse, observe etc depening on mode - create analysis info
        this is executed periodically in the background_analyse_timer task"""
        checkpoint_restore_pending = self.state.position_checkpoint_restore_pending
        cycle_action = decide_analysis_cycle_action(
            AnalysisCycleContext(
                checkpoint_restore_pending=checkpoint_restore_pending,
                game_end_analysis_stopped=(
                    False if checkpoint_restore_pending else self.playing_game_analysis_stopped()
                ),
            )
        )
        if cycle_action == AnalysisCycleAction.RECONCILE_CHECKPOINT_RESTORE:
            # The logical board already contains the checkpoint, but the
            # physical board does not yet match it.  Do not display a
            # cached evaluation for a position the user has not restored.
            await self._start_or_stop_analysis_as_needed()
            return None
        info: InfoDict | None = None
        info_list: list[InfoDict] | None = None
        info_list_source: str | None = None
        web_engine_snapshot: WebAnalysisSnapshot | None = None
        web_tutor_snapshot: WebAnalysisSnapshot | None = None
        analysed_fen = ""  # analysis is only valid for this fen
        if cycle_action == AnalysisCycleAction.STOP_AFTER_GAME_END:
            await self._start_or_stop_analysis_as_needed()
            if self.state.picotutor is not None:
                await self.state.picotutor.set_analysis_enabled(False)
            return None
        tutor_analyser_available = self.state.picotutor.can_use_coach_analyser()
        source_action = decide_analysis_source(
            AnalysisSourceContext(
                tutor_is_primary=self.is_coach_analyser() and tutor_analyser_available,
                engine_plays=self.eng_plays(),
                pgn_mode=self.pgn_mode(),
                is_user_turn=self.state.is_user_turn(),
                engine_thinking=bool(self.engine and self.engine.is_thinking()),
                tutor_analyser_available=tutor_analyser_available,
            )
        )
        if source_action == AnalysisSourceAction.TUTOR_PRIMARY:
            # here picotutor engine replaces playing engine analysis to save cpu
            result = await self.state.picotutor.get_analysis()
            info_list = result.get("info")
            info_list_source = "tutor"
            analysed_fen = result.get("fen", "")
            web_tutor_snapshot = WebAnalysisSnapshot(info_list, analysed_fen)
            if self.state.picotutor.get_board().fen() != self.state.game.fen():
                logger.warning("picotutor board out of sync with game")
            info_list = depth_gated_analysis_info(
                self.state.best_sent_depth, info_list, analysed_fen, self.state.game
            )
        elif source_action == AnalysisSourceAction.ENGINE_NON_PLAYING:
            # we need to analyse both sides without tutor - use engine analyser
            result = await self.engine.get_analysis(self.state.game)
            info_list = result.get("info")
            info_list_source = "engine"
            analysed_fen = result.get("fen", "")
            web_engine_snapshot = WebAnalysisSnapshot(info_list, analysed_fen)
            info_list = depth_gated_analysis_info(
                self.state.best_sent_depth, info_list, analysed_fen, self.state.game
            )
            await self._start_or_stop_analysis_as_needed()
        else:
            # Issue #109 and #49 before that - how to get engine thinking
            if source_action == AnalysisSourceAction.ENGINE_THINKING:
                result = await self.engine.get_thinking_analysis(self.state.game)
                info_list = result.get("info")
                info_list_source = "engine-thinking"
                analysed_fen = result.get("fen", "")
                web_engine_snapshot = WebAnalysisSnapshot(info_list, analysed_fen)
            elif source_action == AnalysisSourceAction.TUTOR_WEB_ONLY:
                # PicoTutor owns current user-turn analysis.  Keep the
                # selected engine's final playing-search snapshot; do
                # not start or poll a second deep analyser merely to
                # refresh the web Engine line.
                result = await self.state.picotutor.get_analysis()
                info_candidate_list: list[InfoDict] | None = result.get("info")
                web_tutor_snapshot = WebAnalysisSnapshot(
                    info_candidate_list, result.get("fen", "")
                )
            elif source_action == AnalysisSourceAction.ENGINE_CURRENT:
                analysis_board = self.state.get_move_check_board()
                result = await self.engine.get_analysis(analysis_board)
                info_list = result.get("info")
                info_list_source = "engine"
                analysed_fen = result.get("fen", "")
                web_engine_snapshot = WebAnalysisSnapshot(info_list, analysed_fen)
                info_list = depth_gated_analysis_info(
                    self.state.best_sent_depth, info_list, analysed_fen, self.state.game
                )
            await self._start_or_stop_analysis_as_needed()
        if web_engine_snapshot and web_engine_snapshot.info:
            await self.send_web_analysis(
                web_engine_snapshot.info,
                web_engine_snapshot.fen,
                "engine",
                suppress_engine_line=False,
            )
        if web_tutor_snapshot and web_tutor_snapshot.info:
            await self.send_web_analysis(
                web_tutor_snapshot.info,
                web_tutor_snapshot.fen,
                "tutor",
                suppress_engine_line=not self.eng_plays(),
            )
        if info_list and (info_list_source != "tutor" or not self.eng_plays()):
            info = info_list[0]  # pv first
            await self.send_analyse(info, analysed_fen)
        # autoplay is temporarily piggybacking on this once-a-second analyse call
        # @todo give it a separate timer task when this is stable
        if allow_autoplay and self.state.autoplay_pgn_file and self.can_do_next_pgn_replay_move():
            next_move = self._get_cached_pgn_next_move()
            wait_for_replay_tutor = (
                self.state.pgn_replay_tutor_regeneration
                and self.state.picotutor.can_use_coach_analyser()
            )
            if self._pgn_next_move_in_book(next_move):
                await asyncio.sleep(1.0)
                await self.autoplay_pgnreplay_move(allow_game_ends=True, next_move=next_move)  # book move
            elif wait_for_replay_tutor:
                if analysed_fen == self.state.get_fen():
                    latest_depth = await self.state.picotutor.get_latest_seen_depth()
                    min_depth = max(self.state.picotutor.get_applied_deep_depth() - 2, 1)
                    if latest_depth >= min_depth:
                        await self.autoplay_pgnreplay_move(allow_game_ends=True, next_move=next_move)  # tutor ready
            else:
                if triggered_by_timer:
                    await self.autoplay_pgnreplay_move(allow_game_ends=True, next_move=next_move)  # timer triggered
        elif self.state.interaction_mode == Mode.PGNREPLAY and self.state.game.is_game_over():
            if self.state.autoplay_pgn_file:
                self._set_pgn_replay_autoplay(False)
                logger.debug("PGN replay ended; autoplay stopped")
        return info

    async def send_analyse(
        self, info: InfoDict, analysed_fen: str, send_pv: bool = True, ponder_move: chess.Move | None = None
    ):
        """send pv, depth, and score events for a specific analysed fen
        with send_pv False pv message is not sent - use if its previous move InfoDict
        ponder_move overrides the cached ponder the optimiser remembers (None keeps previous behaviour)
        this is executed periodically in the background_analyse_timer task"""
        if not info:
            return
        current_fen = self.state.get_fen()
        if analysed_fen != current_fen:
            logger.debug("ignoring analysis info for old fen: %s != %s", analysed_fen, current_fen)
            return
        # ask for score from white's perspective
        (move, score, mate) = PicoTutor.get_score(info)
        if "depth" in info:
            depth = info.get("depth")
            cache_ponder = move
            if ponder_move is not None:
                cache_ponder = ponder_move
            self.state.best_sent_depth.set_best(info, analysed_fen, self.state.game, cache_ponder)
            # send depth before score as score is assembling depth in receiver end
            await Observable.fire(Event.NEW_DEPTH(depth=depth, fen=analysed_fen))
        if send_pv:
            pv_move_to_send = ponder_move if ponder_move and ponder_move != chess.Move.null() else move
            pv_moves = list(info.get("pv") or [])
            if pv_moves:
                if pv_move_to_send and pv_move_to_send != chess.Move.null():
                    pv_moves[0] = pv_move_to_send
                pv_to_send = pv_moves
            else:
                pv_to_send = [pv_move_to_send] if pv_move_to_send != chess.Move.null() else []
            if pv_to_send:
                self.state.pb_move = pv_to_send[0]  # backward compatibility
                await Observable.fire(Event.NEW_PV(pv=pv_to_send, fen=analysed_fen))
        if score is not None:
            await Observable.fire(Event.NEW_SCORE(score=score, mate=mate, fen=analysed_fen))

    async def send_web_analysis(
        self,
        info_list: list[InfoDict],
        analysed_fen: str,
        source: str,
        suppress_engine_line: bool = False,
    ):
        """Send full analysis info to the web client without depth gating."""
        if not info_list:
            return
        current_fen = self.state.get_fen()
        if analysed_fen != current_fen:
            logger.debug("ignoring web analysis for old fen: %s != %s", analysed_fen, current_fen)
            return
        analysis_payload = web_analysis_payload(
            info_list,
            analysed_fen,
            source,
            suppress_engine_line=suppress_engine_line,
            language=getattr(self.state.dgttranslate, "language", "en"),
        )
        if analysis_payload is None:
            logger.debug("skip web analysis for %s: no complete score/mate lines yet", source)
            return
        await DisplayMsg.show(Message.WEB_ANALYSIS(analysis=analysis_payload))

    async def autoplay_pgnreplay_move(
        self, allow_game_ends, next_move: chess.Move | None = None
    ) -> chess.Move:
        """play the next PGN move if one found - return None if next move was found
        for future its allowed to return chess.Move.null() if move not found"""
        if next_move is None:
            next_move = self._get_cached_pgn_next_move()
        moves_game = len(self.state.game.move_stack)  # half_move dont work in library
        moves_pgn = -1
        if next_move:
            await self.do_pgn_replay_move(next_move)
            self.state.autoplay_half_moves = moves_game + 1  # remember last seen autoplay move
        elif allow_game_ends:
            # preferred elif instead of if here to avoid checking end of game often
            moves_pgn = self.state.picotutor.get_pgn_halfmove_clock()  # slow call
            if moves_game == moves_pgn:
                # signal end of pgn replay game - not using PGN_GAME_ENDS ...
                # lets first see if we can use same GAME_ENDS as for normal endings
                try:
                    result = game_result_from_header(self.shared["headers"].get("Result", ""))
                except ValueError:
                    result = GameResult.ABORT
                # @todo deviated from the original moves with takeback result in ABORT
                # because the PGN game header "Result" changed when you deviated
                self.game_end_event()  # sets autoplay to False
                await DisplayMsg.show(
                    Message.GAME_ENDS(
                        tc_init=self.state.time_control.get_parameters(),
                        result=result,
                        play_mode=self.state.play_mode,
                        game=self.state.game.copy(),
                        mode=self.state.interaction_mode,
                    )
                )
        if not next_move:
            self._set_pgn_replay_autoplay(False)  # always stop autoplay, not only else/elif
            logger.debug(
                "No more PGN replay moves: halfmoves game %d, pgn %d, last seen automove %d",
                moves_game,
                moves_pgn,
                self.state.autoplay_half_moves,
            )
        return next_move

    async def expired_fen_timer(self):
        """Handle times up for an unhandled fen string send from board."""
        game_fen = ""
        self.state.fen_timer_running = False
        external_fen = ""
        internal_fen = ""

        if self.state.error_fen:
            logger.debug("fen_timer expired %s", self.state.error_fen)
            game_fen = self.state.get_board_fen()
            internal_fen = game_fen
            external_fen = self.state.error_fen
            fen_res = compare_fen(external_fen, internal_fen)
            if self.state.set_position_ack_target_fen:
                if self.state.set_position_ack_ready:
                    if fen_res:
                        await DisplayMsg.show(Message.POSITION_FAIL(fen_result=fen_res))
                    else:
                        await self._finish_set_position_ack(
                            self.state.set_position_ack_target_fen
                        )
                return
            if self.state.position_checkpoint_restore_pending:
                logger.info("waiting for physical checkpoint position")
                if fen_res:
                    await DisplayMsg.show(Message.POSITION_FAIL(fen_result=fen_res))
                else:
                    await self._finish_position_checkpoint_restore()
                return
            if fen_res and len(fen_res) > 4:
                lifted_piece_char = fen_res[4]
                is_hand_mode = (
                    self.state.dgtmenu.get_picocoach() == PicoCoach.COACH_HAND
                    and self.picotutor_mode()
                )
                if lifted_piece_char in ("K", "k") or is_hand_mode:
                    self.state.coach_triggered = True
            if (
                self.state.interaction_mode in (Mode.NORMAL, Mode.TRAINING, Mode.BRAIN)
                and self.state.error_fen != chess.STARTING_BOARD_FEN
                and not (self.state.variant == "racingkings" and self.state.error_fen == RK_STARTING_BOARD_FEN)
                and (game_fen == chess.STARTING_BOARD_FEN or (self.state.variant == "racingkings" and game_fen == RK_STARTING_BOARD_FEN))
                and self.state.flag_startup
                and self.state.dgtmenu.get_game_contlast()
                and not self.online_mode()
                and not self.pgn_mode()
                and not self.emulation_mode()
            ):
                # molli: read the pgn of last game and restore correct game status and times
                self.state.flag_startup = False
                await DisplayMsg.show(Message.RESTORE_GAME())
                await asyncio.sleep(2)

                l_pgn_file_name = "last_game.pgn"
                await self.read_pgn_file(l_pgn_file_name)

            # issue #78 - fast moving ponder mode - commit c253f2c 15.6.2025 was first
            # see also issue #82 - allow switching sides in PONDER mode
            elif (
                self.state.interaction_mode == Mode.PONDER
                and self.state.flag_flexible_ponder
                and not self.state.coach_triggered
            ):
                if (not self.state.newgame_happened) or self.state.flag_startup:
                    # molli: no error in analysis(ponder) mode => start new game with current fen
                    # and try to keep same player to play (white or black) but check
                    # if it is a legal position (otherwise switch sides or return error)
                    fen1 = self.state.error_fen
                    fen2 = self.state.error_fen
                    if self.state.game.turn == chess.WHITE:
                        fen1 += " w KQkq - 0 1"
                        fen2 += " b KQkq - 0 1"
                    else:
                        fen1 += " b KQkq - 0 1"
                        fen2 += " w KQkq - 0 1"

                    bit_board = chess.Board(fen1)
                    bit_board.set_fen(bit_board.fen())  # let python-chess correct castling rights
                    if bit_board.is_valid():
                        accepted_fen = bit_board.fen()
                    else:
                        bit_board = chess.Board(fen2)
                        bit_board.set_fen(bit_board.fen())
                        accepted_fen = bit_board.fen() if bit_board.is_valid() else None

                    if accepted_fen:
                        self.state.game = chess.Board(accepted_fen)
                        # Sync variant boards with new position
                        if self.state.variant == "3check" and self.state._threecheck_board is not None:
                            self.state._threecheck_board.set_fen(accepted_fen)
                        elif self.state.variant == "atomic" and self.state._atomic_board is not None:
                            self.state._atomic_board.set_fen(accepted_fen)
                        self._update_variant_shared()
                        await self.engine.newgame(self.state.engine_board_copy(), False)
                        self.state.best_sent_depth.reset()
                        self.state.done_computer_fen = None
                        self.state.done_move = self.state.pb_move = chess.Move.null()
                        self.state.searchmoves.reset()
                        self.state.game_declared = False
                        self.state.legal_fens = compute_legal_fens(self.state.game, self.state.get_variant_board())
                        self.state.legal_fens_after_cmove = []
                        self.state.last_legal_fens = []
                        await DisplayMsg.show(Message.SHOW_TEXT(text_string="NEW_POSITION"))
                        await DisplayMsg.show(self.state.new_game_msg(newgame=False))
                        await self.set_picotutor_position(new_game=True)  # issue #78 new code
                        await self._start_or_stop_analysis_as_needed()
                    else:
                        logger.info("wrong fen %s for 4 secs", self.state.error_fen)
                        if not self.state.set_position_ack_pending:
                            await DisplayMsg.show(Message.WRONG_FEN())

            else:
                logger.info("wrong fen %s for 4 secs", self.state.error_fen)
                if self.online_mode():
                    # show computer opponents move again
                    if self.state.seeking_flag:
                        await DisplayMsg.show(Message.SEEKING())
                    elif self.state.best_move_displayed:
                        await DisplayMsg.show(
                            Message.COMPUTER_MOVE(
                                move=self.state.done_move,
                                ponder=False,
                                game=self.state.game_copy(),
                                wait=False,
                                is_user_move=False,
                            )
                        )
                fen_res = ""
                internal_fen = self.state.get_board_fen()
                external_fen = self.state.error_fen
                fen_res = compare_fen(external_fen, internal_fen)

                if self.state.setpieces_switch_anchor_fen:
                    if external_fen == self.state.setpieces_switch_anchor_fen:
                        if self.state.setpieces_switch_armed:
                            self.state.setpieces_switch_armed = False
                            await self.switch_artwork_window()
                    else:
                        self.state.setpieces_switch_armed = True

                if (not self.state.position_mode) and fen_res:
                    lifted_piece_char = fen_res[4] if len(fen_res) > 4 else ""
                    is_king_lift = lifted_piece_char in ("K", "k")
                    is_hand_mode = (
                        self.state.dgtmenu.get_picocoach() == PicoCoach.COACH_HAND
                        and self.picotutor_mode()
                    )
                    self.state.coach_triggered_piece_type = None
                    if is_king_lift or is_hand_mode:
                        self.state.coach_triggered = True
                        if not self.picotutor_mode():
                            self.state.position_mode = True
                        self.cancel_brain_hint_timer()
                        if is_hand_mode and lifted_piece_char:
                            piece_char_map = {
                                "P": chess.PAWN,
                                "N": chess.KNIGHT,
                                "B": chess.BISHOP,
                                "R": chess.ROOK,
                                "Q": chess.QUEEN,
                                "K": chess.KING,
                                "p": chess.PAWN,
                                "n": chess.KNIGHT,
                                "b": chess.BISHOP,
                                "r": chess.ROOK,
                                "q": chess.QUEEN,
                                "k": chess.KING,
                            }
                            self.state.coach_triggered_piece_type = piece_char_map.get(lifted_piece_char)
                            if self.state.coach_triggered_piece_type is not None:
                                if self.state.hand_coach_task and not self.state.hand_coach_task.done():
                                    self.state.hand_coach_task.cancel()
                                self.state.last_hand_coach_move = None
                                self.state.hand_coach_task = asyncio.ensure_future(
                                    self.call_hand_coach(self.state.coach_triggered_piece_type)
                                )
                    else:
                        self.state.position_mode = True
                        self.state.coach_triggered = False
                    if external_fen != chess.STARTING_BOARD_FEN and not (
                        self.state.variant == "racingkings" and external_fen == RK_STARTING_BOARD_FEN
                    ):
                        if (
                            should_show_setpieces_after_lift_timeout(lifted_piece_char, is_hand_mode)
                            and not self.state.set_position_ack_pending
                        ):
                            if not is_king_lift:
                                if not self.state.setpieces_switch_anchor_fen:
                                    self.state.setpieces_switch_anchor_fen = external_fen
                                    self.state.setpieces_switch_armed = False
                            await DisplayMsg.show(Message.WRONG_FEN())
                            await asyncio.sleep(2)
                    self.state.delay_fen_error = 4
                    # molli: Picochess correction messages
                    # show incorrect square(s) and piece to put or be removed
                elif self.state.position_mode and fen_res:
                    self.state.delay_fen_error = 1
                    if not self.online_mode():
                        await self.state.stop_clock()
                    msg = Message.POSITION_FAIL(fen_result=fen_res)
                    await DisplayMsg.show(msg)
                    await asyncio.sleep(1)
                else:
                    await DisplayMsg.show(Message.EXIT_MENU())
                    self.state.delay_fen_error = 4

                _start_fen = RK_STARTING_BOARD_FEN if self.state.variant == "racingkings" else chess.STARTING_BOARD_FEN
                if (
                    self.state.interaction_mode in (Mode.NORMAL, Mode.TRAINING, Mode.BRAIN)
                    and game_fen != _start_fen
                    and self.state.flag_startup
                ):
                    if self.state.dgtmenu.get_enginename():
                        msg = Message.ENGINE_NAME(engine_name=self.state.engine_text)
                        await DisplayMsg.show(msg)

                    if self.pgn_mode():
                        headers = self.shared.get("headers", {}) or {}
                        pgn_white = headers.get("White", "")
                        pgn_black = headers.get("Black", "")
                        pgn_game_name = headers.get("Event", "")
                        pgn_problem = headers.get("Problem", "")
                        pgn_fen = headers.get("FEN", "")
                        pgn_result = headers.get("Result", "")

                        async def show_pgn_headers():
                            update_speed = 1.0
                            if pgn_white:
                                await DisplayMsg.show(Message.SHOW_TEXT(text_string=pgn_white))
                                await asyncio.sleep(update_speed)
                            if pgn_black:
                                await DisplayMsg.show(Message.SHOW_TEXT(text_string=pgn_black))
                                await asyncio.sleep(update_speed)
                            if pgn_result:
                                await DisplayMsg.show(Message.SHOW_TEXT(text_string=pgn_result))
                                await asyncio.sleep(update_speed)
                            if "mate in" in pgn_problem or "Mate in" in pgn_problem:
                                await DisplayMsg.show(Message.SHOW_TEXT(text_string=pgn_problem))
                            else:
                                await DisplayMsg.show(Message.SHOW_TEXT(text_string=pgn_game_name))
                            await asyncio.sleep(update_speed)

                        if "mate in" in pgn_problem or "Mate in" in pgn_problem:
                            await self.set_fen_from_pgn(pgn_fen)
                        asyncio.create_task(show_pgn_headers())

                else:
                    if self.state.done_computer_fen and not self.state.position_mode:
                        await DisplayMsg.show(Message.EXIT_MENU())
                self.state.fen_error_occured = True  # to be reset in fen_handling
        self.state.flag_startup = False
        self.state.newgame_happened = False
        self.state.last_error_fen = external_fen

    async def read_pgn_file(
        self,
        file_name: str,
        start_replay: bool = False,
        pgn_game: Game | None = None,
        show_headers: bool = True,
    ):
        """Read game from PGN file"""
        logger.debug("molli: read game from pgn file")

        using_loaded_pgn_object = pgn_game is not None
        show_pgn_headers = show_headers and not using_loaded_pgn_object
        l_filename = "games" + os.sep + file_name
        if pgn_game is None:
            try:
                with open(l_filename, encoding="utf-8-sig") as l_file_pgn:
                    l_game_pgn: Game | None = chess.pgn.read_game(l_file_pgn)
            except OSError:
                return
        else:
            l_game_pgn = pgn_game
            l_filename = file_name

        logger.debug("molli: read game filename %s", l_filename)
        if l_game_pgn is None:
            logger.warning("No PGN game found in %s", l_filename)
            return
        clear_preserved_mame_history(self.shared)
        loaded_pgn_has_variations = pgn_has_variations(l_game_pgn)
        self.state.loaded_pgn_has_variations = loaded_pgn_has_variations
        replay_regeneration_override = self.state.pgn_replay_tutor_regeneration_override
        if start_replay and replay_regeneration_override is not None:
            self.state.pgn_replay_tutor_regeneration = replay_regeneration_override
            self.state.pgn_replay_tutor_regeneration_override = None
        else:
            self.state.pgn_replay_tutor_regeneration = not loaded_pgn_has_variations
            if not start_replay:
                self.state.pgn_replay_tutor_regeneration_override = None
        self.shared.setdefault("system_info", {})
        self.shared["system_info"].update(
            {
                "loaded_pgn_has_variations": loaded_pgn_has_variations,
                "pgn_replay_tutor_regeneration": self.state.pgn_replay_tutor_regeneration,
            }
        )

        await self.stop_search_and_clock()
        # reset best depth so new analysis results are not filtered by previous game
        self.state.best_sent_depth.reset()

        # forget possible previously loaded PGN game
        self.state.picotutor.set_pgn_game_to_step(None)
        if self.picotutor_mode():
            await self.state.picotutor.newgame()

        fen_header_raw = l_game_pgn.headers.get("FEN") if l_game_pgn.headers else None
        fen_header = str(fen_header_raw).strip() if fen_header_raw else ""
        fen_board_valid = True
        try:
            base_board = l_game_pgn.board()
            self.state.game = base_board.copy()
        except ValueError:
            fen_board_valid = False
            logger.warning("Invalid board setup in PGN headers: %s", fen_header)
            self.state.game = chess.Board()
        l_move = chess.Move.null()

        update_speed = 1.0
        is_pico_save_game: bool = False
        if l_game_pgn.headers["Event"]:
            event_str = l_game_pgn.headers["Event"]
            if (event_str or "").startswith("PicoChess"):
                is_pico_save_game = True  # game was saved by Pico
            logger.debug(f"is_pico_save_game: {is_pico_save_game}")  # TODO clarify usage of is_pico_save_game
            if show_pgn_headers:
                await DisplayMsg.show(Message.SHOW_TEXT(text_string=str(event_str)))
                await asyncio.sleep(update_speed)

        if show_pgn_headers:
            if l_game_pgn.headers["White"]:
                await DisplayMsg.show(Message.SHOW_TEXT(text_string=str(l_game_pgn.headers["White"])))
                await asyncio.sleep(update_speed)

            await DisplayMsg.show(Message.SHOW_TEXT(text_string="versus"))
            await asyncio.sleep(update_speed)

            if l_game_pgn.headers["Black"]:
                await DisplayMsg.show(Message.SHOW_TEXT(text_string=str(l_game_pgn.headers["Black"])))
                await asyncio.sleep(update_speed)

        result_header_raw = l_game_pgn.headers.get("Result") if l_game_pgn.headers else None
        result_header = str(result_header_raw).strip() if result_header_raw else ""
        loaded_game_finished = bool(result_header and result_header not in ("*", "?"))
        self.state.loaded_pgn_finished = loaded_game_finished
        if result_header_raw and show_pgn_headers:
            display_result = result_header or str(result_header_raw)
            await DisplayMsg.show(Message.SHOW_TEXT(text_string=display_result))
            await asyncio.sleep(update_speed)

        # make sure we have "?" in important missing headers to
        # prevent overwrite by existing user or engine names or elos etc
        ensure_important_headers(l_game_pgn.headers)
        self.state.loaded_pgn_game = copy.deepcopy(l_game_pgn)
        self.state.loaded_pgn_filename = file_name
        self.shared["loaded_pgn_game"] = copy.deepcopy(l_game_pgn)

        if show_pgn_headers:
            await DisplayMsg.show(Message.READ_GAME)

        # check if we should stop loading pgn game "in the middle"
        # this feature can be used to "jump to" a certain position in pgn
        # PicoStop value shall be given in half moves
        try:
            if "PicoStop" in l_game_pgn.headers and l_game_pgn.headers["PicoStop"]:
                l_stop_at_halfmove = int(l_game_pgn.headers["PicoStop"])
            else:
                l_stop_at_halfmove = None
        except ValueError:
            l_stop_at_halfmove = None

        if start_replay and not l_stop_at_halfmove:
            # no PicoStop override found above - check game result
            if result_header and result_header not in ("*", "?"):
                # a game with a final result was loaded - issue #54
                if self.board_type == dgt.util.EBoard.NOEBOARD:
                    # @todo cant use zero on web display because Pico code below
                    # does a pop and user_move just to update web display - see todo below
                    # maybe this is ok, or some other web display update could be found?
                    l_stop_at_halfmove = 1
                else:
                    l_stop_at_halfmove = 0  # for DGT board its better with zero

        mame_engine_selected = self.engine.is_mame_engine()
        published_pgn_game = l_game_pgn
        load_pgn_moves = should_load_pgn_moves(l_stop_at_halfmove)
        if load_pgn_moves:
            for l_move in l_game_pgn.mainline_moves():
                self.state.push_move(l_move)
                if l_stop_at_halfmove and len(self.state.game.move_stack) >= l_stop_at_halfmove:
                    # stop loading pgn game moves... Store them so user can step through them
                    break
            self._update_variant_shared()

        # take back last move in order to send it with user_move for web publishing
        # @ todo Pico V3 made user + engine move here = unnecessary waiting for engine move
        # Pico V4 only makes an engine move... just to update the web screen and main states?
        # maybe there is a smarter way to do this?
        if start_replay and load_pgn_moves and l_move and l_stop_at_halfmove != 0:
            self.state.pop_move()
            self._update_variant_shared()

        mame_capabilities = self.engine.get_mame_capabilities()
        preserve_loaded_history = should_preserve_loaded_pgn_history(
            is_mame_engine=mame_engine_selected,
            start_replay=start_replay,
            supports_position=mame_capabilities.position,
            supports_edit=mame_capabilities.edit,
        )
        if not preserve_loaded_history and self.state.game.move_stack:
            logger.info(
                "MAME Read Game: edit unsupported; using loaded final FEN as a fresh game root"
            )
            self.preserve_mame_history_for_web(
                l_game_pgn,
                self.state.game.fen(en_passant="fen"),
                "read_game",
            )
            self.state.game = self.state.game.copy(stack=False)
            published_pgn_game = pgn_with_board_as_fresh_root(l_game_pgn, self.state.game)

        # Normally PGN loading leaves ucinewgame and position transmission
        # to python-chess.  MAME needs the issue #72 eager ucinewgame and
        # the same immediate position setup used by Scan and Set Pos.
        mame_load = mame_engine_selected and not start_replay
        if mame_load:
            logger.info("MAME Read Game: sending loaded position immediately")
        await self.engine.newgame(
            self.state.engine_board_copy(),
            send_ucinewgame=mame_load,
            send_position_to_mame=mame_load,
        )
        if fen_header and fen_board_valid:
            # publish FEN-started game to displays/engine listeners
            await DisplayMsg.show(self.state.new_game_msg(newgame=False))

        # switch temporarly picotutor off
        old_flag_picotutor = self.state.flag_picotutor
        self.state.flag_picotutor = False
        old_interaction_mode = self.state.interaction_mode
        if start_replay:
            self.state.interaction_mode = Mode.PGNREPLAY
        self._set_pgn_replay_autoplay(False)  # if you load a 2nd PGN it will autosave from move 1
        if start_replay:
            self.state.dgtmenu.set_mode(Mode.PGNREPLAY)
            self.state.dgtmenu.exit_menu()  # leave menu so that PAUSE_RESUME avoids "no function"

        if start_replay and l_move and l_stop_at_halfmove != 0:
            # publish current position to webserver
            await self.user_move(l_move, sliding=True)

        if fen_header and not fen_board_valid:
            logger.warning("FEN header found but could not apply board setup: %s", fen_header)
        else:
            self.state.interaction_mode = loaded_pgn_interaction_mode(
                old_interaction_mode,
                start_replay,
                has_custom_fen=bool(fen_header),
                loaded_game_finished=loaded_game_finished,
            )
            self.state.dgtmenu.set_mode(self.state.interaction_mode)

        # restore picotutor flag to previous state
        self.state.flag_picotutor = old_flag_picotutor
        # always fix the picotutor if-to-analyse both sides and depth
        await self.engine.stop_analysis()  # stop possible engine analyser
        if self.eng_plays():
            await self.state.picotutor.stop()  # stop possible old tutor analysers
        await self.state.picotutor.set_analysis_enabled(self.tutor_analysis_enabled_for_current_mode())
        await self.state.picotutor.set_mode(self.pgn_mode() or not self.eng_plays())

        await self.stop_search_and_clock()
        await self.engine_mode()
        turn = self.state.game.turn
        self.state.done_computer_fen = None
        self.state.done_move = self.state.pb_move = chess.Move.null()
        self.state.play_mode = PlayMode.USER_WHITE if turn == chess.WHITE else PlayMode.USER_BLACK

        # game state should be done now, start picotutor
        await self.set_picotutor_position(new_game=True)

        # ensure analysis optimisation is fresh after header display/setup
        self.state.best_sent_depth.reset()

        self.state.tc_init_last = self.state.time_control.get_parameters()
        self.state.time_control.reset()  # fallback is same as ini setting
        # if we find settings from the file we use them to override fallback
        l_pico_depth = 0
        try:
            if "PicoDepth" in l_game_pgn.headers and l_game_pgn.headers["PicoDepth"]:
                l_pico_depth = int(l_game_pgn.headers["PicoDepth"])
            else:
                l_pico_depth = 0
        except ValueError:
            l_pico_depth = 0

        l_pico_node = 0
        try:
            if "PicoNode" in l_game_pgn.headers and l_game_pgn.headers["PicoNode"]:
                l_pico_node = int(l_game_pgn.headers["PicoNode"])
            else:
                l_pico_node = 0
        except ValueError:
            l_pico_node = 0

        # override time control if its found in pgn file
        if "PicoTimeControl" in l_game_pgn.headers and l_game_pgn.headers["PicoTimeControl"]:
            l_pico_tc = str(l_game_pgn.headers["PicoTimeControl"])
            self.state.time_control, time_text = await self.state.transfer_time(
                l_pico_tc.split(), depth=l_pico_depth, node=l_pico_node
            )

        # override remaining thinking time
        try:
            if "PicoRemTimeW" in l_game_pgn.headers and l_game_pgn.headers["PicoRemTimeW"]:
                lt_white = int(l_game_pgn.headers["PicoRemTimeW"])
            else:
                lt_white = None
        except ValueError:
            lt_white = None

        try:
            if "PicoRemTimeB" in l_game_pgn.headers and l_game_pgn.headers["PicoRemTimeB"]:
                lt_black = int(l_game_pgn.headers["PicoRemTimeB"])
            else:
                lt_black = None
        except ValueError:
            lt_black = None

        # send TIME_CONTROL event based on info collected above
        tc_init = self.state.time_control.get_parameters()
        if lt_white and lt_black:
            tc_init["internal_time"] = {chess.WHITE: lt_white, chess.BLACK: lt_black}
        text = self.state.dgttranslate.text("N00_oktime")
        await Observable.fire(Event.SET_TIME_CONTROL(tc_init=tc_init, time_text=text, show_ok=False))
        await self.state.stop_clock()
        await DisplayMsg.show(Message.EXIT_MENU())

        self.state.searchmoves.reset()
        self.state.game_declared = False

        self.state.legal_fens = compute_legal_fens(self.state.game, self.state.get_variant_board())
        self.state.legal_fens_after_cmove = []
        self.state.last_legal_fens = []
        await self.stop_search_and_clock()

        game_end = self.state.check_game_state()
        if not start_replay:
            self._set_game_started(not loaded_game_finished and not game_end)
        system_info_update = {
            "game_started": self.state.game_started,
            "interaction_mode": self.state.interaction_mode.name.lower(),
            "loaded_pgn_has_variations": loaded_pgn_has_variations,
            "loaded_pgn_finished": loaded_game_finished,
            "pgn_replay_tutor_regeneration": self.state.pgn_replay_tutor_regeneration,
            "pgn_replay_autoplay": self.state.autoplay_pgn_file,
        }
        self.shared.setdefault("system_info", {})
        self.shared["system_info"].update(system_info_update)
        EventHandler.write_to_clients({"event": "SystemInfo", "msg": system_info_update})
        logger.info(
            "loaded PGN %s: mode=%s game_started=%s finished=%s variations=%s tutor_regeneration=%s",
            l_filename,
            self.state.interaction_mode.name.lower(),
            self.state.game_started,
            loaded_game_finished,
            loaded_pgn_has_variations,
            self.state.pgn_replay_tutor_regeneration,
        )

        self.shared["headers"] = published_pgn_game.headers  # update headers from live game
        EventHandler.write_to_clients({"event": "Header", "headers": dict(self.shared["headers"])})
        await asyncio.sleep(0.1)  # give time to write_to_clients
        if not start_replay:
            pgn_str = published_pgn_game.accept(
                chess.pgn.StringExporter(headers=True, comments=True, variations=True)
            )
            try:
                mov = self.state.game.peek().uci()
            except IndexError:
                mov = chess.Move.null().uci()
            result = {
                "pgn": pgn_str,
                "fen": self.state.get_fen(),
                "event": "Fen",
                "move": mov,
                "play": "reload",
                "variant": self.shared.get("variant", "chess"),
                "mistakes": pgn_variation_review_points(l_game_pgn),
                "history_scope": dict(history_scope(self.shared)),
            }
            self.shared["last_dgt_move_msg"] = result
            EventHandler.write_to_clients(result)

        if game_end:
            self.state.play_mode = PlayMode.USER_WHITE if turn == chess.WHITE else PlayMode.USER_BLACK
            self.state.legal_fens = []
            self.state.legal_fens_after_cmove = []
            self.game_end_event()
            await DisplayMsg.show(game_end)
        else:
            self.state.play_mode = PlayMode.USER_WHITE if turn == chess.WHITE else PlayMode.USER_BLACK
            if self.eng_plays():
                # we continue in a mode where engine is playing, not analysis
                text = self.state.play_mode.value
                msg = Message.PLAY_MODE(
                    play_mode=self.state.play_mode,
                    play_mode_text=self.state.dgttranslate.text(text),
                )
                await DisplayMsg.show(msg)
                await asyncio.sleep(1)

        self.state.take_back_locked = True  # important otherwise problems for setting up the position
        if start_replay and load_pgn_moves:
            pgn_game_to_step = None if l_stop_at_halfmove is None else l_game_pgn
            if pgn_game_to_step:
                # this PGN game was not loaded to the end (above) - remember it
                self.state.picotutor.set_pgn_game_to_step(pgn_game_to_step)
                self.state.autoplay_half_moves = 0  # remember last seen autoplay move
                if self.state.interaction_mode == Mode.PGNREPLAY:
                    self._start_pgn_replay_autoplay()

    def emulation_mode(self):
        emulation = False
        if "(mame" in self.engine.get_name() or "(mess" in self.engine.get_name() or self.engine.is_mame:
            emulation = True
        ModeInfo.set_emulation_mode(emulation)
        return emulation

    async def set_emulation_tctrl(self):
        logger.debug("molli: set_emulation_tctrl")
        if self.emulation_mode():
            pico_depth = 0
            pico_node = 0
            pico_tctrl_str = ""

            await self.state.stop_clock()
            self.state.time_control.stop_internal(log=False)

            uci_options = self.engine.get_pgn_options()
            pico_tctrl_str = ""

            try:
                if "PicoTimeControl" in uci_options:
                    pico_tctrl_str = str(uci_options["PicoTimeControl"])
            except IndexError:
                pico_tctrl_str = ""

            try:
                if "PicoDepth" in uci_options:
                    pico_depth = int(uci_options["PicoDepth"])
            except IndexError:
                pico_depth = 0

            try:
                if "PicoNode" in uci_options:
                    pico_node = int(uci_options["PicoNode"])
            except IndexError:
                pico_node = 0

            if pico_tctrl_str:
                logger.debug("molli: set_emulation_tctrl input %s", pico_tctrl_str)
                self.state.time_control, time_text = await self.state.transfer_time(
                    pico_tctrl_str.split(), depth=pico_depth, node=pico_node
                )
                tc_init = self.state.time_control.get_parameters()
                text = self.state.dgttranslate.text("N00_oktime")
                await Observable.fire(Event.SET_TIME_CONTROL(tc_init=tc_init, time_text=text, show_ok=True))
                self.state.stop_fen_timer()

    async def det_pgn_guess_tctrl(self):
        self.state.max_guess_white = 0
        self.state.max_guess_black = 0

        logger.debug("molli pgn: determine pgn guess")

        uci_options = self.engine.get_pgn_options()

        logger.debug("molli pgn: uci_options %s", str(uci_options))

        if "max_guess" in uci_options:
            self.state.max_guess = int(uci_options["max_guess"])
        else:
            self.state.max_guess = 0

        if "think_time" in uci_options:
            self.state.think_time = int(uci_options["think_time"])
        else:
            self.state.think_time = 0

        if "pgn_game_file" in uci_options:
            logger.debug("molli pgn: pgn_game_file; %s", str(uci_options["pgn_game_file"]))
            if "book_test" in str(uci_options["pgn_game_file"]):
                self.state.pgn_book_test = True
                logger.debug("molli pgn: pgn_book_test set to True")
            else:
                self.state.pgn_book_test = False
                logger.debug("molli pgn: pgn_book_test set to False")
        else:
            logger.debug("molli pgn: pgn_book_test not found => False")
            self.state.pgn_book_test = False

        self.state.max_guess_white = self.state.max_guess
        self.state.max_guess_black = 0

        tc_init = self.state.time_control.get_parameters()
        tc_init["mode"] = TimeMode.FIXED
        tc_init["fixed"] = self.state.think_time
        tc_init["blitz"] = 0
        tc_init["fischer"] = 0

        tc_init["blitz2"] = 0
        tc_init["moves_to_go"] = 0
        tc_init["depth"] = 0
        tc_init["node"] = 0

        await self.state.stop_clock()
        text = self.state.dgttranslate.text("N00_oktime")
        self.state.time_control.reset()
        await Observable.fire(Event.SET_TIME_CONTROL(tc_init=tc_init, time_text=text, show_ok=True))
        await self.state.stop_clock()
        await DisplayMsg.show(Message.EXIT_MENU())

    async def engine_mode(self):
        """call when engine mode is changed"""
        tutor_analysis_enabled = self.tutor_analysis_enabled_for_current_mode()
        if self.state.picotutor is not None:
            await self.state.picotutor.set_analysis_enabled(tutor_analysis_enabled)
        if not tutor_analysis_enabled:
            await DisplayMsg.show(Message.WEB_ANALYSIS(analysis={"source": "tutor", "clear": True}))
        if self.state.interaction_mode in (Mode.NORMAL, Mode.BRAIN, Mode.TRAINING):
            # optimisation, dont ask for ponder unless needed
            ponder_mode = True if self.state.interaction_mode == Mode.BRAIN else False
            self.engine.set_mode(ponder=ponder_mode)
            # mode might have changed back to playing, activate tutor
            await self.state.picotutor.set_status(
                self.state.dgtmenu.get_picowatcher(),
                self.state.dgtmenu.get_picocoach(),
                self.state.dgtmenu.get_picoexplorer(),
                self.state.dgtmenu.get_picocomment(),
            )
        elif self.state.interaction_mode in (Mode.ANALYSIS, Mode.KIBITZ, Mode.OBSERVE, Mode.PONDER, Mode.PGNREPLAY):
            self.engine.set_mode()
            # Pico v4 allow picotutor to run also when watching
            await self.state.picotutor.set_status(
                self.state.dgtmenu.get_picowatcher(),
                self.state.dgtmenu.get_picocoach(),
                self.state.dgtmenu.get_picoexplorer(),
                self.state.dgtmenu.get_picocomment(),
            )
        if self.state.flag_picotutor:
            # always fix the picotutor if-to-analyse both sides and depth
            await self.state.picotutor.set_mode(self.pgn_mode() or not self.eng_plays())
        await self._start_or_stop_analysis_as_needed()  # engine mode changed

    def remote_engine_mode(self):
        if "remote" in self.state.engine_file:
            return True
        else:
            return False

    async def _pv_score_depth_analyser(self):
        """Analyse PV score depth in the background"""
        if self.state.game:
            if not self.state.game.is_game_over():
                await self.analyse(triggered_by_timer=True)

    def _can_run_user_clock_after_board_reconnect(self) -> bool:
        if self.board_type == dgt.util.EBoard.NOEBOARD or self.online_mode():
            return False
        if self.state.interaction_mode not in (Mode.NORMAL, Mode.BRAIN, Mode.REMOTE, Mode.TRAINING):
            return False
        if self.state.game_declared or ModeInfo.get_game_ending() != "*":
            return False
        return not self.state.is_not_user_turn()

    async def _board_connection_lost(self, last_board_message: float = 0.0) -> None:
        async with self._board_clock_transition_lock:
            if (
                self._can_run_user_clock_after_board_reconnect()
                and self.state.time_control.internal_running()
            ):
                self.state.clock_paused_by_board_loss = True
                silence = max(0.0, time.monotonic() - last_board_message) if last_board_message else 0.0
                await self.state.stop_clock(refund_seconds=silence)
                logger.info("paused user clock after e-board disconnect; board silent for %.1f secs", silence)

    async def _board_connection_restored(self) -> None:
        async with self._board_clock_transition_lock:
            if not self.state.clock_paused_by_board_loss:
                return
            self.state.clock_paused_by_board_loss = False
            if (
                self._can_run_user_clock_after_board_reconnect()
                and not self.state.position_mode
                and self.state.done_computer_fen is None
                and not self.state.dgtmenu.inside_main_menu()
                and not self.state.time_control.internal_running()
            ):
                await self.state.start_clock()
                logger.info("resumed user clock after e-board reconnect")

    async def event_consumer(self):
        """Event consumer for main"""
        logger.debug("evt_queue ready")
        try:
            while True:
                event = await evt_queue.get()
                if event is None:
                    # this is the signal to stop the main loop
                    logger.debug("evt_queue received None, stopping main loop")
                    evt_queue.task_done()
                    break
                # issue #45 still let main loop create tasks
                # @todo check if this should not do create_task either
                # create_task should make program more responsive to user tasks
                event_task = asyncio.create_task(
                    process_queued_event(event, self.process_main_events, evt_queue)
                )
                track_event_task(event_task, self.event_tasks)
                await asyncio.sleep(0.05)  # balancing message queues
        except asyncio.CancelledError:
            logger.debug("evt_queue cancelled")

    async def pre_exit_or_reboot_cleanups(self):
        """First immediate cleanups before exit or reboot"""
        logger.debug("pre exit_or_reboot_cleanups")
        self.shutdown_requested.set()
        if self.state.fen_timer_running:
            self.state.stop_fen_timer()
        # @todo are there other timers to stop here?
        # as we wait 5 secs before exiting we only want to prevent timer actions
        if self.engine is not None:
            await self.stop_search(timeout=ENGINE_SHUTDOWN_IDLE_TIMEOUT)
        await self.state.stop_clock()
        if self.engine is not None:
            await self.engine.quit()
        if self.state.picotutor:
            # close all the picotutor engines
            await self.state.picotutor.exit_or_reboot_cleanups()

    async def final_exit_or_reboot_cleanups(self):
        """Last cleanups before exit or reboot"""
        logger.debug("final exit_or_reboot_cleanups")
        if isinstance(self.dgtboard, DgtBoard):
            await self.dgtboard.stop()
        if self.state.pairing_bridge:
            await self.state.pairing_bridge.close()
        if self.pico_talker:
            # close the sound system (this is why final is a separate call)
            await self.pico_talker.exit_or_reboot_cleanups()
        # cancel all non-main tasks, this task will stop itself
        # and a None has been placed in the main event queue to stop it
        for task in self.non_main_tasks:
            task.cancel()
        # as the final step stop the main loop task
        # by putting None in the main event queue
        logger.debug("final exit_or_reboot_cleanups done - stopping main evt_queue")
        await Observable.fire(None)
        self.shutdown_complete.set()

    def can_do_next_pgn_replay_move(self) -> bool:
        """check if we can do the next pgn move"""
        if self.state.interaction_mode != Mode.PGNREPLAY or self.state.game.is_game_over():
            return False
        if self.state.picotutor.get_pgn_game_to_step() is None:
            return False  # No game to try to step through
        if self.board_type == dgt.util.EBoard.NOEBOARD:
            # on web display we can always autoplay the next pgn move
            return True
        # on a eboard we have to check if its waiting for
        # the previous move to be done by the user
        if self.state.done_computer_fen is None:
            # not waiting for a move, ok to do next move
            return True
        # the most tricky part, we are waiting for a move, has it been done?
        # Use get_board_fen() for variant-aware comparison (atomic explosions, etc.)
        if self.state.get_board_fen() == self.state.done_computer_fen:
            # yes, the move has been done, we can do the next move
            return True
        return False

    def _start_pgn_replay_autoplay(self) -> None:
        """Enable PGN replay autoplay without advancing immediately."""
        if self.can_do_next_pgn_replay_move():
            self._set_game_started(True)
            self._set_pgn_replay_autoplay(True)

    def _get_cached_pgn_next_move(self) -> chess.Move | None:
        """Return cached next PGN move for current FEN, computing when needed."""
        if not self.state.picotutor:
            return None
        current_fen = self.state.game.fen()
        if self.state.pgn_replay_next_move_fen == current_fen:
            return self.state.pgn_replay_next_move
        next_move = self.state.picotutor.get_next_pgn_move(self.state.game)
        self.state.pgn_replay_next_move_fen = current_fen
        self.state.pgn_replay_next_move = next_move
        return next_move

    def _get_cached_book_moves(self) -> set[chess.Move] | None:
        """Return cached opening book moves for current FEN."""
        if not self.bookreader:
            return None
        current_fen = self.state.game.fen()
        cached_moves = self.state.pgn_replay_book_cache.get(current_fen)
        if cached_moves is not None:
            return cached_moves
        moves = set()
        try:
            for entry in self.bookreader.find_all(self.state.game):
                moves.add(entry.move)
        except Exception as exc:
            logger.debug("opening book lookup failed: %s", exc)
            return moves
        if len(self.state.pgn_replay_book_cache) >= 64:
            self.state.pgn_replay_book_cache.pop(next(iter(self.state.pgn_replay_book_cache)))
        self.state.pgn_replay_book_cache[current_fen] = moves
        return moves

    def _pgn_next_move_in_book(self, next_move: chess.Move | None) -> bool:
        """Check whether the next PGN move is present in the current opening book."""
        if not next_move:
            return False
        book_moves = self._get_cached_book_moves()
        if not book_moves:
            return False
        return next_move in book_moves

    async def do_pgn_replay_move(self, next_move: chess.Move):
        """Used by autoplay to execute the next PGN replay move"""
        assert self.state.interaction_mode == Mode.PGNREPLAY
        if self.board_type == dgt.util.EBoard.NOEBOARD:
            await self.user_move(next_move, sliding=False)
        else:
            game_copy = self.state.game_copy()
            await DisplayMsg.show(
                Message.COMPUTER_MOVE(
                    move=next_move,
                    ponder=False,
                    game=game_copy,
                    wait=False,
                    is_user_move=True,
                )
            )
            # set state variables as waiting for the move to be done on the eboard
            game_copy.push(next_move)
            # For atomic variant, use atomic board to get FEN with explosions applied
            if self.state.variant == "atomic" and self.state._atomic_board is not None:
                atomic_copy = self.state._atomic_board.copy()
                atomic_copy.push(next_move)
                self.state.done_computer_fen = atomic_copy.board_fen()
            else:
                self.state.done_computer_fen = game_copy.board_fen()  # expected fen after move
            self.state.done_move = next_move  # expected move

    def game_end_event(self):
        #  @todo1 should have an EVENT message for game end, function for now
        #  @todo2 should be more state variables to reset here?
        self._set_game_started(False)
        self._set_pgn_replay_autoplay(False)  # prevent autoplay starting for next pgn read
        if self.state.interaction_mode != Mode.PONDER:
            self._clear_position_checkpoint()

    def _resume_game_after_takeback(self) -> None:
        """Restore active-game lifecycle after leaving a terminal position."""
        if not should_resume_game_after_takeback(
            game_over=self.state.game.is_game_over(),
            game_declared=self.state.game_declared,
            game_ending=ModeInfo.get_game_ending(),
        ):
            return
        logger.info("takeback reopened ended game")
        ModeInfo.set_game_ending(result="*")
        self.state.game_declared = False
        self.state.flag_pgn_game_over = False
        self._set_game_started(True)

    def _load_pgn_engine_games(self, pgn_file: str) -> None:
        self.state.pgn_engine_games = []
        self.state.pgn_engine_game_index = -1
        self.state.pgn_engine_total_halfmoves = None
        self.state.pgn_engine_result = "*"
        if not pgn_file:
            return
        try:
            with open(pgn_file, encoding="utf-8-sig") as f:
                while True:
                    pgn_game = chess.pgn.read_game(f)
                    if not pgn_game:
                        break
                    if getattr(pgn_game, "errors", []):
                        logger.error("Skipping remaining PGN games after parse error: %s", pgn_game.errors)
                        break
                    headers = dict(pgn_game.headers)
                    self.state.pgn_engine_games.append(
                        {
                            "headers": headers,
                            "total_halfmoves": sum(1 for _ in pgn_game.mainline_moves()),
                            "result": headers.get("Result", "*"),
                        }
                    )
        except (OSError, ValueError) as exc:
            logger.debug("Could not read pgn_engine file %s: %s", pgn_file, exc)

    def _apply_pgn_engine_game(self, game_info: dict[str, Any]) -> None:
        headers = dict(game_info.get("headers", {}))
        ensure_important_headers(headers)
        self.shared["headers"] = headers
        EventHandler.write_to_clients({"event": "Header", "headers": dict(headers)})
        self.state.pgn_engine_total_halfmoves = game_info.get("total_halfmoves")
        self.state.pgn_engine_result = game_info.get("result", "*")

    def _advance_pgn_engine_game(self) -> None:
        if not self.state.pgn_engine_games:
            return
        next_index = (self.state.pgn_engine_game_index + 1) % len(self.state.pgn_engine_games)
        self.state.pgn_engine_game_index = next_index
        self._apply_pgn_engine_game(self.state.pgn_engine_games[next_index])

    async def process_main_events(self, event):
        """Consume event from evt_queue"""
        if (
            not isinstance(event, Event.CLOCK_TIME)
            and not isinstance(event, Event.NEW_DEPTH)
            and not isinstance(event, Event.NEW_PV)
            and not isinstance(event, Event.NEW_SCORE)
        ):
            logger.debug("received event from evt_queue: %s", event)
        if (
            self.state.position_checkpoint_restore_pending
            and isinstance(event, Event.SET_INTERACTION_MODE)
            and event.mode != Mode.PONDER
        ):
            logger.info("ignoring mode change until the physical checkpoint restore is complete")
            await DisplayMsg.show(Message.WRONG_FEN())
            return
        if isinstance(event, (Event.NEW_DEPTH, Event.NEW_PV, Event.NEW_SCORE)):
            event_fen = getattr(event, "fen", None)
            current_fen = self.state.get_fen()
            if not analysis_event_matches_position(event_fen, current_fen):
                logger.debug(
                    "ignoring delayed analysis event %s for old fen: %s != %s",
                    event,
                    event_fen,
                    current_fen,
                )
                return
        if isinstance(event, Event.BOARD_CONNECTION_LOST):
            await self._board_connection_lost(getattr(event, "last_board_message", 0.0))

        elif isinstance(event, Event.BOARD_CONNECTION_RESTORED):
            await self._board_connection_restored()

        elif isinstance(event, Event.FEN):
            await self.process_fen(event.fen, self.state)

        elif isinstance(event, Event.KEYBOARD_MOVE):
            move = event.move
            logger.debug("keyboard move [%s]", move)
            if move.from_square == move.to_square:
                await self._handle_same_square_input(move.from_square)
            else:
                # Use variant board for legality check (atomic has different legal moves)
                _check_board = self.state.get_move_check_board()
                if move not in _check_board.legal_moves:
                    logger.warning("illegal move. fen: [%s]", self.state.game.fen())
                else:
                    # The move-check board also preserves variant-specific effects,
                    # including atomic capture explosions.
                    fen = board_fen_after_move(_check_board, move)
                    await DisplayMsg.show(Message.DGT_FEN(fen=fen, raw=False))

        elif isinstance(event, Event.LEVEL):
            if event.options:
                startup_ok = await self.engine.startup(event.options, self.state.rating)
                if not startup_ok:
                    logger.error("engine startup failed; invalid .uci options")
                    await DisplayMsg.show(Message.ENGINE_FAIL())
                    return
            self.state.new_engine_level = event.level_name
            await DisplayMsg.show(
                Message.LEVEL(
                    level_text=event.level_text,
                    level_name=event.level_name,
                    do_speak=bool(event.options),
                )
            )

        elif isinstance(event, Event.NEW_ENGINE):
            # Explicit engine selection is also an escape from pending Set Pos.
            self._clear_set_position_ack()
            # if we are waiting for an engine move, get rid of that first
            await self.get_rid_of_engine_move()
            self.state.best_sent_depth.reset()
            await DisplayMsg.show(Message.WEB_ANALYSIS(analysis={"source": "engine", "clear": True}))
            old_file = self.state.engine_file
            old_options = {}
            old_options = self.engine.get_pgn_options()
            engine_fallback = False
            # Stop the old engine cleanly
            if not self.emulation_mode():
                await self.stop_search()
            # Closeout the engine process and threads

            self.state.engine_file = event.eng["file"]
            self.state.artwork_in_use = False
            engine_file_to_load = self.state.engine_file  # assume not mame
            if "/mame/" in self.state.engine_file and self.state.dgtmenu.get_engine_rdisplay():
                engine_file_art = self.state.engine_file + "_art"
                my_file = Path(engine_file_art)
                if my_file.is_file():
                    self.state.artwork_in_use = True
                    engine_file_to_load = engine_file_art  # load mame
                else:
                    await DisplayMsg.show(Message.SHOW_TEXT(text_string="NO_ARTWORK"))

            await DisplayMsg.show(Message.ENGINE_SETUP())
            await self.engine.quit()
            # Load the new one and send self.args.
            uci_shell = self.uci_remote_shell if self.remote_engine_mode() and self.uci_remote_shell else self.uci_local_shell
            self.engine = UciEngine(
                file=engine_file_to_load,
                uci_shell=uci_shell,
                mame_par=self.calc_engine_mame_par(),
                loop=self.loop,
            )
            await self.engine.open_engine()
            if engine_file_to_load != self.state.engine_file:
                await asyncio.sleep(1)  # mame artwork wait
            if not self.engine.loaded_ok():
                # New engine failed to start, restart old engine
                logger.error("new engine failed to start, reverting to %s", old_file)
                engine_fallback = True
                event.options = old_options
                self.state.engine_file = old_file
                # restart old mame engine?
                self.state.artwork_in_use = False
                if "/mame/" in old_file and self.state.dgtmenu.get_engine_rdisplay():
                    old_file_art = old_file + "_art"
                    my_file = Path(old_file_art)
                    if my_file.is_file():
                        self.state.artwork_in_use = True
                        old_file = old_file_art

                uci_shell = self.uci_remote_shell if self.remote_engine_mode() and self.uci_remote_shell else self.uci_local_shell

                self.engine = UciEngine(
                    file=old_file,
                    uci_shell=uci_shell,
                    mame_par=self.calc_engine_mame_par(),
                    loop=self.loop,
                )
                await self.engine.open_engine()
                if not self.engine.loaded_ok():
                    # Help - old engine failed to restart. There is no engine
                    logger.error("no engines started")
                    await DisplayMsg.show(Message.ENGINE_FAIL())
                    await asyncio.sleep(3)
                    sys.exit(-1)
            # All done - rock'n'roll

            if (
                self.emulation_mode()
                and self.state.dgtmenu.get_engine_rdisplay()
                and self.state.artwork_in_use
                and not is_wayland_session()
                and not self.state.dgtmenu.get_engine_rwindow()
            ):
                # Preserve the old X11 fullscreen fallback. Wayland startup mode
                # is controlled by MAME -window/-nowindow parameters.
                cmd = get_window_command("toggle_fullscreen")
                if cmd:
                    process = await asyncio.create_subprocess_shell(
                        cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await process.communicate()
                    if process.returncode != 0:
                        logger.error(
                            "Command failed with return code %s: %s", process.returncode, stderr.decode()
                        )

            startup_ok = await self.engine.startup(event.options, self.state.rating)
            if startup_ok:
                # Initialize variant support from new engine settings
                self._init_variant_from_engine()
            if not startup_ok:
                logger.error("new engine options missing, reverting to %s", old_file)
                engine_fallback = True
                event.options = old_options
                self.state.engine_file = old_file
                self.state.artwork_in_use = False
                await self.engine.quit()
                if "/mame/" in old_file and self.state.dgtmenu.get_engine_rdisplay():
                    old_file_art = old_file + "_art"
                    my_file = Path(old_file_art)
                    if my_file.is_file():
                        self.state.artwork_in_use = True
                        old_file = old_file_art

                uci_shell = self.uci_remote_shell if self.remote_engine_mode() and self.uci_remote_shell else self.uci_local_shell

                self.engine = UciEngine(
                    file=old_file,
                    uci_shell=uci_shell,
                    mame_par=self.calc_engine_mame_par(),
                    loop=self.loop,
                )
                await self.engine.open_engine()
                if not self.engine.loaded_ok():
                    # Help - old engine failed to restart. There is no engine
                    logger.error("no engines started")
                    await DisplayMsg.show(Message.ENGINE_FAIL())
                    await asyncio.sleep(3)
                    sys.exit(-1)
                startup_ok = await self.engine.startup(event.options, self.state.rating)
                if not startup_ok:
                    logger.error("old engine options missing; no engines started")
                    await DisplayMsg.show(Message.ENGINE_FAIL())
                    await asyncio.sleep(3)
                    sys.exit(-1)

            ModeInfo.set_retro_features(self.engine.get_mame_capabilities().retro_info())

            if self.online_mode():
                await self.state.stop_clock()
                await DisplayMsg.show(Message.ONLINE_LOGIN())
                # check if login successful (correct server & correct user)
                (
                    self.login,
                    own_color,
                    self.self.own_user,
                    self.self.opp_user,
                    self.game_time,
                    self.fischer_inc,
                ) = read_online_user_info()
                logger.debug("molli online login: %s", self.login)

                if "ok" not in self.login:
                    # server connection failed: check settings!
                    await DisplayMsg.show(Message.ONLINE_FAILED())
                    await asyncio.sleep(3)
                    engine_fallback = True
                    event.options = dict()
                    old_file = "engines/aarch64/a-stockf"

                    uci_shell = self.uci_remote_shell if self.remote_engine_mode() and self.uci_remote_shell else self.uci_local_shell

                    self.engine = UciEngine(
                        file=old_file,
                        uci_shell=uci_shell,
                        mame_par=self.calc_engine_mame_par(),
                        loop=self.loop,
                    )
                    await self.engine.open_engine()
                    if not self.engine.loaded_ok():
                        # Help - old engine failed to restart. There is no engine
                        logger.error("no engines started")
                        await DisplayMsg.show(Message.ENGINE_FAIL())
                        await asyncio.sleep(3)
                        sys.exit(-1)
                    startup_ok = await self.engine.startup(event.options, self.state.rating)
                    if not startup_ok:
                        logger.error("engine options missing; no engines started")
                        await DisplayMsg.show(Message.ENGINE_FAIL())
                        await asyncio.sleep(3)
                        sys.exit(-1)
                else:
                    await asyncio.sleep(2)
            elif self.emulation_mode() or self.pgn_mode():
                # molli for emulation engines we have to reset to starting position
                await self.stop_search_and_clock()
                game_fen = self.state.game.board_fen()
                if self.state.variant == "racingkings":
                    self.state.game = chess.Board("8/8/8/8/8/8/krbnNBRK/qrbnNBRQ w - - 0 1")
                else:
                    self.state.game = chess.Board()
                self.state.game.turn = chess.WHITE
                self.state.reset_variant_board()
                self.state.play_mode = PlayMode.USER_WHITE
                if self.pgn_mode():
                    self.engine.option("game_sequence", "forward")
                    await self.engine.send()
                await self.engine.newgame(self.state.engine_board_copy())
                self.state.best_sent_depth.reset()
                self.state.done_computer_fen = None
                self.state.done_move = self.state.pb_move = chess.Move.null()
                self.state.searchmoves.reset()
                self.state.game_declared = False
                self.state.legal_fens = compute_legal_fens(self.state.game, self.state.get_variant_board())
                self.state.last_legal_fens = []
                self.state.legal_fens_after_cmove = []
                starting_fen = RK_STARTING_BOARD_FEN if self.state.variant == "racingkings" else chess.STARTING_BOARD_FEN
                real_new_game = game_fen != starting_fen
                msg = self.state.new_game_msg(newgame=real_new_game)
                await DisplayMsg.show(msg)
            else:
                # issue #72 - avoid problems by not sending newgame to new engine
                await self.engine.newgame(self.state.engine_board_copy(), send_ucinewgame=False)
                # Still notify the display layer about the new game (variant info etc.)
                await DisplayMsg.show(self.state.new_game_msg(newgame=False))

            await self.engine_mode()

            if engine_fallback:
                msg = Message.ENGINE_FAIL()
                # molli: in case of engine fail, set correct old engine display settings
                for index in range(0, len(EngineProvider.installed_engines)):
                    if EngineProvider.installed_engines[index]["file"] == old_file:
                        logger.debug("molli index:%s", str(index))
                        self.state.dgtmenu.set_engine_index(index)
                # in case engine fails, reset level as well
                if self.state.old_engine_level:
                    level_text = self.state.dgttranslate.text("B00_level", self.state.old_engine_level)
                    level_text.beep = False
                else:
                    level_text = None
                await DisplayMsg.show(
                    Message.LEVEL(
                        level_text=level_text,
                        level_name=self.state.old_engine_level,
                        do_speak=False,
                    )
                )
                self.state.new_engine_level = self.state.old_engine_level
            else:
                clear_preserved_mame_history(self.shared)
                self.state.searchmoves.reset()
                msg = Message.ENGINE_READY(
                    eng=event.eng,
                    eng_text=event.eng_text,
                    engine_name=self.engine.get_name(),
                    has_levels=self.engine.has_levels(),
                    has_960=self.engine.has_chess960(),
                    has_ponder=self.engine.has_ponder(),
                    show_ok=event.show_ok,
                    is_mame=self.engine.is_mame_engine(),
                    mame_capabilities=self.engine.get_mame_capabilities().as_dict(),
                )
            # Schedule cleanup of old objects
            gc.collect()

            await self.set_wait_state(msg, not engine_fallback)
            if not engine_fallback:
                await self.show_loaded_mame_capabilities()
            if self.state.interaction_mode in (
                Mode.NORMAL,
                Mode.BRAIN,
                Mode.TRAINING,
            ):  # engine isnt started/searching => stop the clock
                await self.state.stop_clock()
            self.state.engine_text = self.state.dgtmenu.get_current_engine_name()
            self.state.dgtmenu.exit_menu()

            self.state.old_engine_level = self.state.new_engine_level
            self.state.engine_level = self.state.new_engine_level
            self.state.dgtmenu.set_state_current_engine(self.state.engine_file)
            self.state.dgtmenu.exit_menu()
            # here dont care if engine supports pondering, cause Mode.NORMAL from startup
            if (
                not self.remote_engine_mode()
                and not self.online_mode()
                and not self.pgn_mode()
                and not engine_fallback
            ):
                # dont write engine(_level) if remote/online engine or engine failure
                write_picochess_ini("engine", event.eng["file"])
                write_picochess_ini("engine-level", self.state.engine_level)

            if self.pgn_mode():
                if not self.state.flag_last_engine_pgn:
                    self.state.tc_init_last = self.state.time_control.get_parameters()

                await self.det_pgn_guess_tctrl()

                self.state.flag_last_engine_pgn = True
            elif self.emulation_mode():
                if not self.state.flag_last_engine_emu:
                    self.state.tc_init_last = self.state.time_control.get_parameters()
                self.state.flag_last_engine_emu = True
            else:
                # molli restore last saved timecontrol
                if (
                    (self.state.flag_last_engine_pgn or self.state.flag_last_engine_emu)
                    and self.state.tc_init_last is not None
                    and not self.online_mode()
                    and not self.emulation_mode()
                    and not self.pgn_mode()
                ):
                    await self.state.stop_clock()
                    text = self.state.dgttranslate.text("N00_oktime")
                    await Observable.fire(
                        Event.SET_TIME_CONTROL(tc_init=self.state.tc_init_last, time_text=text, show_ok=True)
                    )
                    await self.state.stop_clock()
                    await DisplayMsg.show(Message.EXIT_MENU())
                self.state.flag_last_engine_pgn = False
                self.state.flag_last_engine_emu = False
                self.state.tc_init_last = None

            self.state.comment_file = self.get_comment_file()  # for picotutor game comments like Boris & Sargon
            self.state.picotutor.init_comments(self.state.comment_file)

            if self.emulation_mode():
                await self.set_emulation_tctrl()

            if self.pgn_mode():
                # read metadata directly from the PGN engine file (headers, move counts, end detection)
                pgn_options = self.engine.get_pgn_options() or {}
                pgn_file = pgn_options.get("pgn_game_file")
                self._load_pgn_engine_games(pgn_file)
                self._advance_pgn_engine_game()
                headers = self.shared.get("headers", {}) or {}
                pgn_problem = headers.get("Problem", "")
                pgn_fen = headers.get("FEN", "")

                if "mate in" in pgn_problem or "Mate in" in pgn_problem or pgn_fen != "":
                    await self.set_fen_from_pgn(pgn_fen)
                    self.state.play_mode = (
                        PlayMode.USER_WHITE if self.state.game.turn == chess.WHITE else PlayMode.USER_BLACK
                    )
                    msg = Message.PLAY_MODE(
                        play_mode=self.state.play_mode,
                        play_mode_text=self.state.dgttranslate.text(self.state.play_mode.value),
                    )
                    await DisplayMsg.show(msg)
                    await asyncio.sleep(1)

            if self.online_mode():
                ModeInfo.set_online_mode(mode=True)
                logger.debug("online game fen: %s", self.state.game.fen())
                _start_fen = RK_STARTING_BOARD_FEN if self.state.variant == "racingkings" else chess.STARTING_BOARD_FEN
                if (not self.state.flag_last_engine_online) or (
                    self.state.game.board_fen() == _start_fen
                ):
                    pos960 = 518
                    await Observable.fire(Event.NEW_GAME(pos960=pos960))
                self.state.flag_last_engine_online = True
            else:
                self.state.flag_last_engine_online = False
                ModeInfo.set_online_mode(mode=False)

            if self.pgn_mode():
                ModeInfo.set_pgn_mode(mode=True)
                pos960 = 518
                await Observable.fire(Event.NEW_GAME(pos960=pos960))
            else:
                ModeInfo.set_pgn_mode(mode=False)

            await self.update_elo_display()

            # new engine might change tutor usage - inform tutor
            await self.state.picotutor.set_mode(self.pgn_mode() or not self.eng_plays())
            # also state of main analyser might have changed
            await self._start_or_stop_analysis_as_needed()
            if not self.eng_plays():
                if self.need_engine_analyser():
                    await asyncio.sleep(0.2)
                await self.analyse(allow_autoplay=False)
            # end of NEW_ENGINE

        elif (
            isinstance(event, Event.SETUP_POSITION)
            and getattr(event, "side_only", False)
            and self.state.interaction_mode == Mode.PONDER
        ):
            try:
                ponder_turn = chess.Board(event.fen, chess960=event.uci960).turn
            except (TypeError, ValueError):
                logger.warning("invalid PONDER side-change fen: %s", event.fen)
            else:
                await self._set_ponder_turn(ponder_turn)

        elif isinstance(event, Event.SETUP_POSITION):
            new_game_code = set_position_new_game_code(
                event.fen,
                event.uci960,
                self.state.variant,
            )
            if not getattr(event, "from_scan", False) and new_game_code is not None:
                logger.info("Set Pos selected a starting position; routing to New Game")
                self._clear_set_position_ack()
                await Observable.fire(Event.NEW_GAME(pos960=new_game_code))
                return
            logger.debug("setting up custom fen: %s", event.fen)
            if self.state.interaction_mode != Mode.PONDER:
                self._clear_position_checkpoint()
            uci960 = event.uci960
            self.state.position_mode = False
            self.reset_setpieces_window_switch()
            event_game = getattr(event, "game", None)
            target_fen = None
            if event_game is not None and self.board_type != dgt.util.EBoard.NOEBOARD:
                target_fen = str(event.fen).split()[0]
                physical_fen = self.state.dgtmenu.get_dgt_fen() if self.state.dgtmenu is not None else ""
                self._begin_set_position_ack(
                    target_fen,
                    physical_fen,
                )
            else:
                self._clear_set_position_ack()

            if self.state.game.move_stack:
                if not (self.state.game.is_game_over() or self.state.game_declared):
                    result = GameResult.ABORT
                    self.game_end_event()
                    await DisplayMsg.show(
                        Message.GAME_ENDS(
                            tc_init=self.state.time_control.get_parameters(),
                            result=result,
                            play_mode=self.state.play_mode,
                            game=self.state.game.copy(),
                            mode=self.state.interaction_mode,
                        )
                    )
            if not self._owns_set_position_ack(target_fen):
                logger.info("Set Pos was cancelled before installing its target")
                return
            self._set_game_started(False)
            self._set_pgn_replay_autoplay(False)
            self._reset_loaded_pgn_lifecycle()
            ModeInfo.set_game_ending(result="*")
            mame_capabilities = self.engine.get_mame_capabilities()
            preserve_history = should_preserve_set_position_history(
                event_game,
                is_mame_engine=self.engine.is_mame_engine(),
                supports_position=mame_capabilities.position,
                supports_edit=mame_capabilities.edit,
            )
            if not preserve_history:
                logger.info("MAME Set Pos: edit unsupported; using selected FEN as a fresh game root")
            # Install presentation history only when the setup transaction
            # actually installs its board, never while the HTTP request is
            # merely queued. The validated event prefix is authoritative.
            if not preserve_history and event_game is not None and event_game.move_stack:
                self.preserve_mame_history_for_web(event_game, event.fen, "set_position")
            else:
                clear_preserved_mame_history(self.shared)
            self.state.game = setup_position_game(
                event.fen,
                uci960,
                event_game,
                preserve_history=preserve_history,
            )
            setup_fen = self.state.game.fen()
            if getattr(event, "from_scan", False):
                clear_preserved_mame_history(self.shared)

            # Reset variant boards if active (new position = new state)
            if self.state.variant == "3check" and self.state._threecheck_board is not None:
                self.state._threecheck_board.set_fen(setup_fen)
                self._update_variant_shared()
            elif self.state.variant == "atomic" and self.state._atomic_board is not None:
                self.state._atomic_board.set_fen(setup_fen)
            elif self.state.variant == "racingkings" and self.state._racingkings_board is not None:
                self.state._racingkings_board.set_fen(setup_fen)

            # see new_game
            await self.stop_search_and_clock()
            if not self._owns_set_position_ack(target_fen):
                logger.info("Set Pos was cancelled while stopping the current game")
                return
            if self.engine.has_chess960():
                self.engine.option("UCI_Chess960", uci960)
                await self.engine.send()

            await DisplayMsg.show(
                Message.SHOW_TEXT(
                    text_string=(
                        "POSITION_WAIT"
                        if event_game is not None or self.engine.is_mame_engine()
                        else "NEW_POSITION_SCAN"
                    )
                )
            )
            await self.engine.newgame(
                self.state.engine_board_copy(),
                send_position_to_mame=True,
            )
            if not self._owns_set_position_ack(target_fen):
                logger.info("Set Pos was cancelled during engine setup")
                return
            self.state.best_sent_depth.reset()
            self.state.done_computer_fen = None
            self.state.done_move = self.state.pb_move = chess.Move.null()
            self.state.legal_fens_after_cmove = []
            self.state.time_control.reset()
            self.state.searchmoves.reset()
            self.state.game_declared = False
            if self.state.picotutor is not None:
                await self.state.picotutor.set_analysis_enabled(self.tutor_analysis_enabled_for_current_mode())

            await self.set_picotutor_position(new_game=True)
            await self.set_wait_state(
                self.state.new_game_msg(newgame=True),
                preserve_play_mode=bool(getattr(event, "preserve_play_mode", False)),
            )
            if not self._owns_set_position_ack(target_fen):
                logger.info("Set Pos was cancelled while entering its wait state")
                return
            if self.emulation_mode():
                if self.state.dgtmenu.get_engine_rdisplay() and self.state.artwork_in_use:
                    # switch windows/tasks
                    cmd = get_window_command("switch_window")
                    if cmd:
                        process = await asyncio.create_subprocess_shell(
                            cmd,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        stdout, stderr = await process.communicate()
                        if process.returncode != 0:
                            logger.error(
                                "Command failed with return code %s: %s", process.returncode, stderr.decode()
                            )
                await DisplayMsg.show(Message.SHOW_TEXT(text_string="NEW_POSITION"))
                self.engine.is_ready()
            elif event_game is not None:
                await DisplayMsg.show(Message.SHOW_TEXT(text_string="NEW_POSITION"))
            self.state.position_mode = False
            if target_fen is not None:
                if not self._owns_set_position_ack(target_fen):
                    logger.info("Set Pos physical synchronization was superseded")
                    return
                self.state.set_position_ack_ready = True
                physical_fen = (
                    self.state.dgtmenu.get_dgt_fen()
                    if self.state.dgtmenu is not None
                    else ""
                )
                self.state.set_position_ack_pending = (
                    physical_fen != self.state.set_position_ack_target_fen
                )
                if self.state.set_position_ack_pending:
                    await DisplayMsg.show(Message.WRONG_FEN())
                else:
                    await self._finish_set_position_ack(target_fen)
            else:
                tutor_str = "POSOK"
                msg = Message.PICOTUTOR_MSG(eval_str=tutor_str)
                await DisplayMsg.show(msg)
                await asyncio.sleep(1)

        elif isinstance(event, Event.NEW_GAME):
            self._clear_set_position_ack()
            self._clear_position_checkpoint()
            clear_preserved_mame_history(self.shared)
            await self.get_rid_of_engine_move()
            self._set_game_started(False)
            self._set_pgn_replay_autoplay(False)  # stop auto replay of pgn file if new game started
            self._reset_loaded_pgn_lifecycle()
            last_move_no = self.state.game.fullmove_number
            self.state.takeback_active = False
            self.state.automatic_takeback = False
            self.state.reset_auto = False
            self.state.flag_startup = False
            self.state.flag_pgn_game_over = False

            # Check if game already ended BEFORE resetting the game ending status
            # This prevents duplicate PGN saves when user resets board after game ends
            game_already_ended = ModeInfo.get_game_ending() != "*"

            ModeInfo.set_game_ending(result="*")  # initialize game result for game saving status
            self.state.position_mode = False
            self.reset_setpieces_window_switch()
            self.state.fen_error_occured = False
            self.state.error_fen = None
            self.state.newgame_happened = True
            newgame = (
                self.state.game.move_stack
                or (self.state.game.chess960_pos() != event.pos960)
                or self.state.best_move_posted
                or self.state.done_computer_fen
            )
            if newgame:
                logger.debug("starting a new game with code: %s", event.pos960)
                uci960 = event.pos960 != 518

                if not (self.state.game.is_game_over() or self.state.game_declared) or self.pgn_mode():
                    if self.emulation_mode():  # force abortion for mame
                        if self.state.is_not_user_turn():
                            # clock must be stopped BEFORE the "book_move"
                            # event cause SetNRun resets the clock display
                            await self.state.stop_clock()
                            self.state.best_move_posted = True
                            # @todo 8/8/R6P/1R6/7k/2B2K1p/8/8 and sliding Ra6 over a5 to a4
                            # handle this in correct way!!
                            self.state.game_declared = True
                            self.state.stop_fen_timer()
                            self.state.legal_fens_after_cmove = []

                    # Only send ABORT message if game hasn't already ended
                    if not game_already_ended:
                        result = GameResult.ABORT
                        self.game_end_event()
                        await DisplayMsg.show(
                            Message.GAME_ENDS(
                                tc_init=self.state.time_control.get_parameters(),
                                result=result,
                                play_mode=self.state.play_mode,
                                game=self.state.game.copy(),
                                mode=self.state.interaction_mode,
                            )
                        )
                        await asyncio.sleep(0.3)

                if self.state.variant == "racingkings":
                    self.state.game = chess.Board("8/8/8/8/8/8/krbnNBRK/qrbnNBRQ w - - 0 1")
                else:
                    self.state.game = chess.Board()
                self.state.game.turn = chess.WHITE

                if uci960:
                    self.state.game.set_chess960_pos(event.pos960)

                self.state.reset_variant_board()
                self._update_variant_shared()

                if self.state.play_mode != PlayMode.USER_WHITE:
                    self.state.play_mode = PlayMode.USER_WHITE
                    msg = Message.PLAY_MODE(
                        play_mode=self.state.play_mode,
                        play_mode_text=self.state.dgttranslate.text(str(self.state.play_mode.value)),
                    )
                    await DisplayMsg.show(msg)
                await self.stop_search_and_clock()

                # see setup_position
                if self.engine.has_chess960():
                    self.engine.option("UCI_Chess960", uci960)
                    try:
                        await self.engine.send()
                    except Exception as exc:
                        logger.warning("engine.send() failed during new game setup: %s", exc)

                if self.online_mode():
                    await DisplayMsg.show(Message.SEEKING())
                    self.state.seeking_flag = True
                    self.state.stop_fen_timer()
                    ModeInfo.set_online_mode(mode=True)
                else:
                    ModeInfo.set_online_mode(mode=False)

                if self.pgn_mode():
                    self._advance_pgn_engine_game()
                await self.engine.newgame(self.state.engine_board_copy())

                self.state.best_sent_depth.reset()
                await DisplayMsg.show(Message.WEB_ANALYSIS(analysis={"source": "engine", "clear": True}))
                await DisplayMsg.show(Message.WEB_ANALYSIS(analysis={"source": "tutor", "clear": True}))
                self.state.done_computer_fen = None
                self.state.done_move = self.state.pb_move = chess.Move.null()
                self.state.time_control.reset()
                self.state.best_move_posted = False
                self.state.searchmoves.reset()
                self.state.game_declared = False
                if self.state.picotutor is not None:
                    await self.state.picotutor.set_analysis_enabled(self.tutor_analysis_enabled_for_current_mode())
                await self.update_elo_display()

                if self.online_mode():
                    await asyncio.sleep(0.5)
                    (
                        self.login,
                        own_color,
                        self.own_user,
                        self.opp_user,
                        self.game_time,
                        self.fischer_inc,
                    ) = read_online_user_info()
                    if "no_user" in self.own_user and not self.login == "ok":
                        # user login failed check login settings!!!
                        await DisplayMsg.show(Message.ONLINE_USER_FAILED())
                        await asyncio.sleep(3)
                    elif "no_player" in self.opp_user:
                        # no opponent found start new game or engine again!!!
                        await DisplayMsg.show(Message.ONLINE_NO_OPPONENT())
                        await asyncio.sleep(3)
                    else:
                        await DisplayMsg.show(Message.ONLINE_NAMES(own_user=self.own_user, opp_user=self.opp_user))
                        await asyncio.sleep(3)
                    self.state.seeking_flag = False
                    self.state.best_move_displayed = None

                self.state.legal_fens = compute_legal_fens(self.state.game, self.state.get_variant_board())
                self.state.last_legal_fens = []
                self.state.legal_fens_after_cmove = []
                if self.pgn_mode():
                    if self.state.max_guess > 0:
                        self.state.max_guess_white = self.state.max_guess
                        self.state.max_guess_black = 0
                    headers = self.shared.get("headers", {}) or {}
                    pgn_fen = headers.get("FEN", "")
                    pgn_problem = headers.get("Problem", "")
                    if "mate in" in pgn_problem or "Mate in" in pgn_problem or pgn_fen != "":
                        await self.set_fen_from_pgn(pgn_fen)
                if self.state.interaction_mode == Mode.PGNREPLAY:
                    # V4 built-in pgn replay done - no game to replay
                    self.state.interaction_mode = Mode.NORMAL  # switch to NORMAL plyaing mode
                    await self.engine_mode()  # see INTERACTION_MODE handling
                await self.set_wait_state(self.state.new_game_msg(newgame=newgame))
                if "no_player" not in self.opp_user and "no_user" not in self.own_user:
                    await self.switch_online()
                if self.picotutor_mode():
                    await self.state.picotutor.newgame()
                    if not self.state.flag_startup:
                        if self.state.play_mode == PlayMode.USER_BLACK:
                            await self.state.picotutor.set_user_color(
                                chess.BLACK, self.pgn_mode() or not self.eng_plays()
                            )
                        else:
                            await self.state.picotutor.set_user_color(
                                chess.WHITE, self.pgn_mode() or not self.eng_plays()
                            )
            else:
                if self.online_mode():
                    logger.debug("starting a new game with code: %s", event.pos960)
                    uci960 = event.pos960 != 518
                    await self.state.stop_clock()

                    self.state.game.turn = chess.WHITE

                    if uci960:
                        self.state.game.set_chess960_pos(event.pos960)

                    if self.state.play_mode != PlayMode.USER_WHITE:
                        self.state.play_mode = PlayMode.USER_WHITE
                        msg = Message.PLAY_MODE(
                            play_mode=self.state.play_mode,
                            play_mode_text=self.state.dgttranslate.text(str(self.state.play_mode.value)),
                        )
                        await DisplayMsg.show(msg)

                    # see setup_position
                    await self.stop_search_and_clock()
                    self.state.stop_fen_timer()

                    if self.engine.has_chess960():
                        self.engine.option("UCI_Chess960", uci960)
                        await self.engine.send()

                    self.state.time_control.reset()
                    self.state.searchmoves.reset()

                    await DisplayMsg.show(Message.SEEKING())
                    self.state.seeking_flag = True

                    await self.engine.newgame(self.state.engine_board_copy())

                    (
                        self.login,
                        own_color,
                        self.own_user,
                        self.opp_user,
                        self.game_time,
                        self.fischer_inc,
                    ) = read_online_user_info()
                    if "no_user" in self.own_user:
                        # user login failed check login settings!!!
                        await DisplayMsg.show(Message.ONLINE_USER_FAILED())
                        await asyncio.sleep(3)
                    elif "no_player" in self.opp_user:
                        # no opponent found start new game & search!!!
                        await DisplayMsg.show(Message.ONLINE_NO_OPPONENT())
                        await asyncio.sleep(3)
                    else:
                        await DisplayMsg.show(Message.ONLINE_NAMES(own_user=self.own_user, opp_user=self.opp_user))
                        await asyncio.sleep(1)
                    self.state.best_sent_depth.reset()
                    self.state.seeking_flag = False
                    self.state.best_move_displayed = None
                    self.state.takeback_active = False
                    self.state.automatic_takeback = False
                    self.state.done_computer_fen = None
                    self.state.done_move = self.state.pb_move = chess.Move.null()
                    self.state.legal_fens = compute_legal_fens(self.state.game, self.state.get_variant_board())
                    self.state.last_legal_fens = []
                    self.state.legal_fens_after_cmove = []
                    self.state.game_declared = False
                    if self.state.picotutor is not None:
                        await self.state.picotutor.set_analysis_enabled(self.tutor_analysis_enabled_for_current_mode())
                    await self.set_wait_state(
                        self.state.new_game_msg(newgame=newgame),
                    )
                    if "no_player" not in self.opp_user and "no_user" not in self.own_user:
                        await self.switch_online()
                else:
                    logger.debug("no need to start a new game")
                    if self.pgn_mode():
                        self.state.takeback_active = False
                        self.state.automatic_takeback = False
                        headers = self.shared.get("headers", {}) or {}
                        pgn_fen = headers.get("FEN", "")
                        pgn_problem = headers.get("Problem", "")
                        if "mate in" in pgn_problem or "Mate in" in pgn_problem or pgn_fen != "":
                            await self.set_fen_from_pgn(pgn_fen)
                            await self.set_wait_state(
                                self.state.new_game_msg(newgame=newgame),
                            )
                        else:
                            await DisplayMsg.show(
                                self.state.new_game_msg(newgame=newgame)
                            )
                    else:
                        await DisplayMsg.show(self.state.new_game_msg(newgame=newgame))

            if self.picotutor_mode():
                await self.state.picotutor.newgame()
                if not self.state.flag_startup:
                    if self.state.play_mode == PlayMode.USER_BLACK:
                        await self.state.picotutor.set_user_color(
                            chess.BLACK, self.pgn_mode() or not self.eng_plays()
                        )
                    else:
                        await self.state.picotutor.set_user_color(
                            chess.WHITE, self.pgn_mode() or not self.eng_plays()
                        )

            if self.state.interaction_mode != Mode.REMOTE and not self.online_mode():
                if self.state.dgtmenu.get_enginename():
                    await asyncio.sleep(0.7)  # give time for ABORT message
                    msg = Message.ENGINE_NAME(engine_name=self.state.engine_text)
                    await DisplayMsg.show(msg)
                if self.pgn_mode():
                    headers = self.shared.get("headers", {}) or {}
                    pgn_white = headers.get("White", "")
                    pgn_black = headers.get("Black", "")
                    pgn_game_name = headers.get("Event", "")
                    pgn_problem = headers.get("Problem", "")
                    pgn_result = headers.get("Result", "")
                    await asyncio.sleep(1)

                    update_speed = 1.0
                    if not pgn_white:
                        pgn_white = "????"
                    await DisplayMsg.show(Message.SHOW_TEXT(text_string=pgn_white))
                    await asyncio.sleep(update_speed)

                    await DisplayMsg.show(Message.SHOW_TEXT(text_string="versus"))
                    await asyncio.sleep(update_speed)

                    if not pgn_black:
                        pgn_black = "????"
                    await DisplayMsg.show(Message.SHOW_TEXT(text_string=pgn_black))
                    await asyncio.sleep(update_speed)

                    if pgn_result:
                        await DisplayMsg.show(Message.SHOW_TEXT(text_string=pgn_result))
                    await asyncio.sleep(update_speed)
                    if "mate in" in pgn_problem or "Mate in" in pgn_problem:
                        await DisplayMsg.show(Message.SHOW_TEXT(text_string=pgn_problem))
                    else:
                        await DisplayMsg.show(Message.SHOW_TEXT(text_string=pgn_game_name))
                    await asyncio.sleep(update_speed)

                    # reset pgn guess counters
                    if last_move_no > 1:
                        self.state.no_guess_black = 1
                        self.state.no_guess_white = 1
                    else:
                        log_pgn(self.state)
                        if self.state.max_guess_white > 0:
                            if self.state.no_guess_white > self.state.max_guess_white:
                                self.state.last_legal_fens = []
                                await self.get_next_pgn_move()

        elif isinstance(event, Event.PAUSE_RESUME):
            if self.pgn_mode():
                self.engine.pause_pgn_audio()
            else:
                if self.engine.is_thinking():
                    self.engine.force_move()
                elif (
                    self.eng_plays() and self.state.is_not_user_turn() and self.state.done_computer_fen is not None
                ):
                    # e-board: engine move still pending on the board; allow user to request another move
                    # (when go() sees searchlist=True it removes already-played moves from the root list)
                    if not self.state.check_game_state():
                        self._clear_pending_engine_move()
                        if self.picotutor_mode():
                            await rollback_picotutor_for_alternative(
                                self.state.picotutor,
                                self.state.game,
                                self.set_picotutor_position,
                            )
                            self.state.best_move_posted = False
                        await self.think(
                            Message.ALTERNATIVE_MOVE(game=self.state.game.copy(), play_mode=self.state.play_mode),
                            searchlist=True,
                        )
                elif self.eng_plays() and self.state.is_not_user_turn():
                    if self.state.time_control.internal_running():
                        await self.state.stop_clock()
                    elif not self.state.check_game_state():
                        text = self.state.play_mode.value
                        await self.think(
                            Message.PLAY_MODE(
                                play_mode=self.state.play_mode,
                                play_mode_text=self.state.dgttranslate.text(text),
                            )
                        )
                elif self.state.interaction_mode == Mode.PGNREPLAY:
                    # Built in PGN Replay mode - toggle autoplay on or off
                    if self.state.autoplay_pgn_file:
                        self._set_pgn_replay_autoplay(False)  # stop auto replay of pgn
                    else:
                        # if we are not already waiting for an autoplay move make the first move
                        if self.can_do_next_pgn_replay_move():
                            # avoid sending GAME_ENDS when autoplay is started
                            auto_move = await self.autoplay_pgnreplay_move(allow_game_ends=False)
                        else:
                            auto_move = None
                        if auto_move:
                            self._set_pgn_replay_autoplay(True)  # start auto replay of pgn
                        else:
                            msg = Message.SHOW_TEXT(text_string="no move")
                            await DisplayMsg.show(msg)
                elif not self.state.done_computer_fen:
                    if self.state.time_control.internal_running():
                        await self.state.stop_clock()
                    else:
                        self._set_game_started(True)
                        await self.state.start_clock()
                else:
                    logger.debug("best move displayed, dont start/stop clock")

        elif isinstance(event, Event.ALTERNATIVE_MOVE):
            if self.state.done_computer_fen and not self.emulation_mode():
                self._clear_pending_engine_move()
                if self.eng_plays():
                    # @todo handle Mode.REMOTE too
                    if self.state.time_control.mode == TimeMode.FIXED:
                        self.state.time_control.reset()
                    # set computer to move - in case the user just changed the engine
                    self.state.play_mode = (
                        PlayMode.USER_WHITE if self.state.game.turn == chess.BLACK else PlayMode.USER_BLACK
                    )
                    if not self.state.check_game_state():
                        if self.picotutor_mode():
                            await rollback_picotutor_for_alternative(
                                self.state.picotutor,
                                self.state.game,
                                self.set_picotutor_position,
                            )
                            self.state.best_move_posted = False
                        # Allow any late bestmove/info lines from the previous search to drain.
                        await asyncio.sleep(0.2)
                        await self.think(
                            Message.ALTERNATIVE_MOVE(game=self.state.game.copy(), play_mode=self.state.play_mode),
                            searchlist=True,
                        )
                else:
                    logger.warning("wrong function call [alternative]! mode: %s", self.state.interaction_mode)

        elif (
            isinstance(event, Event.SWITCH_SIDES)
            and self.state.interaction_mode == Mode.PONDER
        ):
            await self._set_ponder_turn(not self.state.game.turn)

        elif isinstance(event, Event.SWITCH_SIDES):
            self.state.best_sent_depth.reset()  # safest to drop optimisation when switching sides
            await self.get_rid_of_engine_move()
            self.state.flag_startup = False
            await DisplayMsg.show(Message.EXIT_MENU())

            if self.state.interaction_mode == Mode.PONDER:
                # molli: allow switching sides in flexble ponder mode
                fen = self.state.get_board_fen()

                if self.state.game.turn == chess.WHITE:
                    fen += " b KQkq - 0 1"
                else:
                    fen += " w KQkq - 0 1"
                # ask python-chess to correct the castling string
                bit_board = chess.Board(fen)
                bit_board.set_fen(bit_board.fen())
                if bit_board.is_valid():
                    self.state.game = chess.Board(bit_board.fen())
                    # Sync variant boards with new position
                    if self.state.variant == "3check" and self.state._threecheck_board is not None:
                        self.state._threecheck_board.set_fen(bit_board.fen())
                    elif self.state.variant == "atomic" and self.state._atomic_board is not None:
                        self.state._atomic_board.set_fen(bit_board.fen())
                    #  await self.stop_search_and_clock()
                    await self.engine.newgame(self.state.engine_board_copy())
                    self.state.best_sent_depth.reset()
                    self.state.done_computer_fen = None
                    self.state.done_move = self.state.pb_move = chess.Move.null()
                    self.state.time_control.reset()
                    self.state.searchmoves.reset()
                    self.state.game_declared = False
                    self.state.legal_fens = compute_legal_fens(self.state.game, self.state.get_variant_board())
                    self.state.legal_fens_after_cmove = []
                    self.state.last_legal_fens = []
                    # switching sides in PONDER (ANALYSIS in menu, not a playing mode)
                    self.state.play_mode = (
                        PlayMode.USER_WHITE if self.state.game.turn == chess.WHITE else PlayMode.USER_BLACK
                    )
                    msg = Message.PLAY_MODE(
                        play_mode=self.state.play_mode,
                        play_mode_text=self.state.dgttranslate.text(self.state.play_mode.value),
                    )
                    await DisplayMsg.show(msg)
                    await self.set_picotutor_position(new_game=True)  # issue #78 inform tutor
                    await self.analyse()  # #78 this should be last when all is done
                else:
                    logger.debug("illegal fen %s", fen)
                    await DisplayMsg.show(Message.WRONG_FEN())
                    await DisplayMsg.show(Message.EXIT_MENU())

            elif self.state.interaction_mode in (Mode.NORMAL, Mode.BRAIN, Mode.TRAINING):
                if not self.engine.is_waiting():
                    await self.stop_search_and_clock()
                self.state.automatic_takeback = False
                self.state.takeback_active = False
                self.state.reset_auto = False
                self.state.last_legal_fens = []
                self.state.legal_fens_after_cmove = []
                self.state.best_move_displayed = self.state.done_computer_fen
                if self.state.best_move_displayed:
                    move = self.state.done_move
                    self.state.done_computer_fen = None
                    self.state.done_move = self.state.pb_move = chess.Move.null()
                else:
                    move = chess.Move.null()  # not really needed
                # switching sides in engine plays modes
                self.state.play_mode = (
                    PlayMode.USER_WHITE if self.state.play_mode == PlayMode.USER_BLACK else PlayMode.USER_BLACK
                )
                msg = Message.PLAY_MODE(
                    play_mode=self.state.play_mode,
                    play_mode_text=self.state.dgttranslate.text(self.state.play_mode.value),
                )

                if self.state.time_control.mode == TimeMode.FIXED:
                    self.state.time_control.reset()

                if self.picotutor_mode():
                    if self.state.play_mode == PlayMode.USER_BLACK:
                        await self.state.picotutor.set_user_color(
                            chess.BLACK, self.pgn_mode() or not self.eng_plays()
                        )
                    else:
                        await self.state.picotutor.set_user_color(
                            chess.WHITE, self.pgn_mode() or not self.eng_plays()
                        )
                    if self.state.best_move_posted:
                        self.state.best_move_posted = False
                        await self.state.picotutor.pop_last_move(self.state.game)

                self.state.legal_fens = []

                if self.pgn_mode():  # molli change pgn guessing game sides
                    if self.state.max_guess_black > 0:
                        self.state.max_guess_white = self.state.max_guess_black
                        self.state.max_guess_black = 0
                    elif self.state.max_guess_white > 0:
                        self.state.max_guess_black = self.state.max_guess_white
                        self.state.max_guess_white = 0
                    self.state.no_guess_black = 1
                    self.state.no_guess_white = 1

                cond1 = self.state.game.turn == chess.WHITE and self.state.play_mode == PlayMode.USER_BLACK
                cond2 = self.state.game.turn == chess.BLACK and self.state.play_mode == PlayMode.USER_WHITE
                if cond1 or cond2:
                    # The side switch itself starts the new game when it hands
                    # the move to the engine from the initial position.  Without
                    # clearing this guard, the resulting BEST_MOVE is mistaken
                    # for a stale result from the pre-new-game search.
                    self.state.newgame_happened = False
                    self.state.time_control.reset_start_time()
                    await self.think(msg)  # PLAY_MODE
                else:
                    await DisplayMsg.show(msg)  # PLAY_MODE
                    self._set_game_started(True)
                    await self.state.start_clock()
                    self.state.legal_fens = compute_legal_fens(self.state.game, self.state.get_variant_board())

                if self.state.best_move_displayed:
                    await DisplayMsg.show(Message.SWITCH_SIDES(game=self.state.game.copy(), move=move))

            elif self.state.interaction_mode == Mode.REMOTE:
                if not self.engine.is_waiting():
                    await self.stop_search_and_clock()

                self.state.last_legal_fens = []
                self.state.legal_fens_after_cmove = []
                self.state.best_move_displayed = self.state.done_computer_fen
                if self.state.best_move_displayed:
                    move = self.state.done_move
                    self.state.done_computer_fen = None
                    self.state.done_move = self.state.pb_move = chess.Move.null()
                else:
                    move = chess.Move.null()  # not really needed

                self.state.play_mode = (
                    PlayMode.USER_WHITE if self.state.play_mode == PlayMode.USER_BLACK else PlayMode.USER_BLACK
                )
                msg = Message.PLAY_MODE(
                    play_mode=self.state.play_mode,
                    play_mode_text=self.state.dgttranslate.text(self.state.play_mode.value),
                )

                if self.state.time_control.mode == TimeMode.FIXED:
                    self.state.time_control.reset()

                self.state.legal_fens = []
                game_end = self.state.check_game_state()
                if game_end:
                    await DisplayMsg.show(msg)
                else:
                    cond1 = self.state.game.turn == chess.WHITE and self.state.play_mode == PlayMode.USER_BLACK
                    cond2 = self.state.game.turn == chess.BLACK and self.state.play_mode == PlayMode.USER_WHITE
                    if cond1 or cond2:
                        self.state.time_control.reset_start_time()
                        await self.think(msg)
                    else:
                        await DisplayMsg.show(msg)
                        self._set_game_started(True)
                        await self.state.start_clock()
                        self.state.legal_fens = compute_legal_fens(self.state.game, self.state.get_variant_board())

                if self.state.best_move_displayed:
                    await DisplayMsg.show(Message.SWITCH_SIDES(game=self.state.game.copy(), move=move))

        elif isinstance(event, Event.DRAWRESIGN):
            if not self.state.game_declared:  # in case user leaves kings in place while moving other pieces
                await self.stop_search_and_clock()
                l_result = ""
                if event.result == GameResult.DRAW:
                    l_result = "1/2-1/2"
                elif event.result in (GameResult.WIN_WHITE, GameResult.WIN_BLACK):
                    l_result = "1-0" if event.result == GameResult.WIN_WHITE else "0-1"
                elif event.result == GameResult.THREE_CHECK_WHITE:
                    l_result = "1-0"
                elif event.result == GameResult.THREE_CHECK_BLACK:
                    l_result = "0-1"
                elif event.result == GameResult.KOTH_WHITE:
                    l_result = "1-0"
                elif event.result == GameResult.KOTH_BLACK:
                    l_result = "0-1"
                elif event.result == GameResult.ATOMIC_WHITE:
                    l_result = "1-0"
                elif event.result == GameResult.ATOMIC_BLACK:
                    l_result = "0-1"
                elif event.result == GameResult.RK_WHITE:
                    l_result = "1-0"
                elif event.result == GameResult.RK_BLACK:
                    l_result = "0-1"
                elif event.result == GameResult.ANTICHESS_WHITE:
                    l_result = "1-0"
                elif event.result == GameResult.ANTICHESS_BLACK:
                    l_result = "0-1"
                ModeInfo.set_game_ending(result=l_result)
                self.game_end_event()
                await DisplayMsg.show(
                    Message.GAME_ENDS(
                        tc_init=self.state.time_control.get_parameters(),
                        result=event.result,
                        play_mode=self.state.play_mode,
                        game=self.state.game.copy(),
                        mode=self.state.interaction_mode,
                    )
                )
                await asyncio.sleep(1.5)
                self.state.game_declared = True
                self.state.stop_fen_timer()
                self.state.legal_fens_after_cmove = []
                await self.update_elo(event.result)

        elif isinstance(event, Event.REMOTE_MOVE):
            self.state.flag_startup = False
            if event.move.from_square == event.move.to_square:
                await self._handle_same_square_input(event.move.from_square)
            elif should_reject_user_move_after_game_end(
                self.state.interaction_mode,
                self.state.game_declared,
                ModeInfo.get_game_ending(),
            ):
                logger.info(
                    "ignoring remote move [%s] after game end: mode=%s declared=%s result=%s",
                    event.move,
                    self.state.interaction_mode,
                    self.state.game_declared,
                    ModeInfo.get_game_ending(),
                )
            elif self.board_type == dgt.util.EBoard.NOEBOARD:
                if not remote_move_matches_current_position(
                    event.move,
                    getattr(event, "fen", ""),
                    self.state.get_move_check_board(),
                ):
                    logger.info(
                        "ignoring stale web move [%s] for fen %s; live fen is %s",
                        event.move,
                        getattr(event, "fen", ""),
                        self.state.game.fen(),
                    )
                    return
                # Mirror process_fen(): once a real user move starts the new
                # game, the next BEST_MOVE belongs to this game, not the
                # previous-game stale-move guard.
                self.state.newgame_happened = False
                await self.user_move(event.move, sliding=False)
            else:
                if self.state.interaction_mode == Mode.REMOTE and self.state.is_not_user_turn():
                    if not remote_move_matches_current_position(
                        event.move,
                        getattr(event, "fen", ""),
                        self.state.get_move_check_board(),
                    ):
                        logger.info(
                            "ignoring stale remote web move [%s] for fen %s; live fen is %s",
                            event.move,
                            getattr(event, "fen", ""),
                            self.state.game.fen(),
                        )
                        return
                    await self.stop_search_and_clock()
                    await DisplayMsg.show(
                        Message.COMPUTER_MOVE(
                            move=event.move,
                            ponder=chess.Move.null(),
                            game=self.state.game_copy(),
                            wait=False,
                            is_user_move=False,
                        )
                    )
                    game_copy = self.state.game.copy()
                    game_copy.push(event.move)
                    self._prepare_engine_move(game_copy, event.move)
                else:
                    logger.warning(
                        "wrong function call [remote]! mode: %s turn: %s",
                        self.state.interaction_mode,
                        self.state.game.turn,
                    )

        elif isinstance(event, Event.BEST_MOVE):
            event_fen = getattr(event, "fen", None)
            event_search_revision = getattr(event, "search_revision", None)
            current_fen = self.state.get_fen()
            if not engine_move_event_matches_state(
                event_fen,
                current_fen,
                event_search_revision,
                self.state.engine_search_revision,
                self.state.done_computer_fen,
            ):
                logger.info(
                    "ignoring stale or duplicate engine move [%s] for fen %s; live fen is %s",
                    event.move,
                    event_fen,
                    current_fen,
                )
                return
            self.state.flag_startup = False
            self.state.take_back_locked = False
            self.state.best_move_posted = False
            self.state.takeback_active = False
            self.state.engine_move_was_book = bool(event.inbook) if self.eng_plays() else False

            if self.state.interaction_mode in (Mode.NORMAL, Mode.BRAIN, Mode.TRAINING):
                if self.state.is_not_user_turn():
                    # clock must be stopped BEFORE the "book_move" event cause SetNRun resets the clock display
                    clock_was_running = self.state.time_control.internal_running()
                    await self.state.stop_clock()
                    if not engine_move_event_matches_state(
                        event_fen,
                        self.state.get_fen(),
                        event_search_revision,
                        self.state.engine_search_revision,
                        self.state.done_computer_fen,
                    ):
                        logger.info("engine move [%s] became stale while stopping the clock", event.move)
                        if should_resume_clock_after_rejected_engine_move(
                            clock_was_running,
                            self.state.time_control.internal_running(),
                            self.state.done_computer_fen,
                        ):
                            await self.state.start_clock()
                        return
                    self.state.best_move_posted = True
                    # @todo 8/8/R6P/1R6/7k/2B2K1p/8/8 and sliding Ra6 over a5 to a4 - handle this in correct way!!
                    if self.state.game.is_game_over() and not self.online_mode():
                        logger.warning(
                            "illegal move on game_end - sliding? move: %s fen: %s",
                            event.move,
                            self.state.game.fen(),
                        )
                    elif event.move is None:  # online game aborted or pgn move wrong or end of pgn game
                        self.state.game_declared = True
                        self.state.stop_fen_timer()
                        self.state.legal_fens_after_cmove = []
                        game_msg = self.state.game.copy()
                        self.game_end_event()
                        if self.online_mode():
                            winner = ""
                            result_str = ""
                            await asyncio.sleep(0.5)
                            result_str, winner = read_online_result()
                            logger.debug("molli result_str:%s", result_str)
                            logger.debug("molli winner:%s", winner)
                            gameresult_tmp: GameResult | None = None
                            gameresult_tmp2: GameResult | None = None

                            if "Checkmate" in result_str or "checkmate" in result_str or "mate" in result_str:
                                gameresult_tmp = GameResult.MATE
                            elif "Game abort" in result_str or "timeout" in result_str:
                                if winner:
                                    if "white" in winner:
                                        gameresult_tmp = GameResult.ABORT
                                        gameresult_tmp2 = GameResult.WIN_WHITE
                                    else:
                                        gameresult_tmp = GameResult.ABORT
                                        gameresult_tmp2 = GameResult.WIN_BLACK
                                else:
                                    gameresult_tmp = GameResult.ABORT
                            elif result_str == "Draw" or result_str == "draw":
                                gameresult_tmp = GameResult.DRAW
                            elif "Out of time: White wins" in result_str:
                                gameresult_tmp = GameResult.OUT_OF_TIME
                                gameresult_tmp2 = GameResult.WIN_WHITE
                            elif "Out of time: Black wins" in result_str:
                                gameresult_tmp = GameResult.OUT_OF_TIME
                                gameresult_tmp2 = GameResult.WIN_BLACK
                            elif "Out of time" in result_str or "outoftime" in result_str:
                                if winner:
                                    if "white" in winner:
                                        gameresult_tmp = GameResult.OUT_OF_TIME
                                        gameresult_tmp2 = GameResult.WIN_WHITE
                                    else:
                                        gameresult_tmp = GameResult.OUT_OF_TIME
                                        gameresult_tmp2 = GameResult.WIN_BLACK
                                else:
                                    gameresult_tmp = GameResult.OUT_OF_TIME
                            elif "White wins" in result_str:
                                gameresult_tmp = GameResult.ABORT
                                gameresult_tmp2 = GameResult.WIN_WHITE
                            elif "Black wins" in result_str:
                                gameresult_tmp = GameResult.ABORT
                                gameresult_tmp2 = GameResult.WIN_BLACK
                            elif "OPP. resigns" in result_str or "resign" in result_str or "abort" in result_str:
                                gameresult_tmp = GameResult.ABORT
                                logger.debug("molli resign handling")
                                if winner == "":
                                    logger.debug("molli winner not set")
                                    if self.state.play_mode == PlayMode.USER_BLACK:
                                        gameresult_tmp2 = GameResult.WIN_BLACK
                                    else:
                                        gameresult_tmp2 = GameResult.WIN_WHITE
                                else:
                                    logger.debug("molli winner %s", winner)
                                    if "white" in winner:
                                        gameresult_tmp2 = GameResult.WIN_WHITE
                                    else:
                                        gameresult_tmp2 = GameResult.WIN_BLACK

                            else:
                                logger.debug("molli unknown result")
                                gameresult_tmp = GameResult.ABORT

                            logger.debug("molli result_tmp:%s", gameresult_tmp)
                            logger.debug("molli result_tmp2:%s", gameresult_tmp2)

                            if gameresult_tmp2 and not (
                                self.state.game.is_game_over() and gameresult_tmp == GameResult.ABORT
                            ):
                                if gameresult_tmp == GameResult.OUT_OF_TIME:
                                    await DisplayMsg.show(Message.LOST_ON_TIME())
                                    await asyncio.sleep(2)
                                    await DisplayMsg.show(
                                        Message.GAME_ENDS(
                                            tc_init=self.state.time_control.get_parameters(),
                                            result=gameresult_tmp2,
                                            play_mode=self.state.play_mode,
                                            game=game_msg,
                                            mode=self.state.interaction_mode,
                                        )
                                    )
                                else:
                                    await DisplayMsg.show(
                                        Message.GAME_ENDS(
                                            tc_init=self.state.time_control.get_parameters(),
                                            result=gameresult_tmp,
                                            play_mode=self.state.play_mode,
                                            game=game_msg,
                                            mode=self.state.interaction_mode,
                                        )
                                    )
                                    await asyncio.sleep(2)
                                    await DisplayMsg.show(
                                        Message.GAME_ENDS(
                                            tc_init=self.state.time_control.get_parameters(),
                                            result=gameresult_tmp2,
                                            play_mode=self.state.play_mode,
                                            game=game_msg,
                                            mode=self.state.interaction_mode,
                                        )
                                    )
                            else:
                                if gameresult_tmp == GameResult.ABORT and gameresult_tmp2:
                                    await DisplayMsg.show(
                                        Message.GAME_ENDS(
                                            tc_init=self.state.time_control.get_parameters(),
                                            result=gameresult_tmp2,
                                            play_mode=self.state.play_mode,
                                            game=game_msg,
                                            mode=self.state.interaction_mode,
                                        )
                                    )
                                else:
                                    await DisplayMsg.show(
                                        Message.GAME_ENDS(
                                            tc_init=self.state.time_control.get_parameters(),
                                            result=gameresult_tmp,
                                            play_mode=self.state.play_mode,
                                            game=game_msg,
                                            mode=self.state.interaction_mode,
                                        )
                                    )
                        else:
                            if self.pgn_mode():
                                # molli: check if last move of pgn game file
                                await self.stop_search_and_clock()
                                log_pgn(self.state)
                                # in Pico V4 we cannot detect end of pgn game by depth
                                # if max_guess uci option is zero - this must be end of game
                                if self.state.max_guess == 0 or (
                                    self.state.pgn_engine_total_halfmoves is not None
                                    and len(self.state.game.move_stack) >= self.state.pgn_engine_total_halfmoves
                                ):
                                    logger.debug("molli pgn: PGN END")
                                    pgn_result = self.state.pgn_engine_result or "*"
                                    await DisplayMsg.show(Message.PGN_GAME_END(result=pgn_result))
                                elif self.state.pgn_book_test:
                                    l_game_copy = self.state.game.copy()
                                    l_game_copy.pop()
                                    l_found = False
                                    if self.bookreader:
                                        l_found = self.state.searchmoves.check_book(self.bookreader, l_game_copy)

                                    if not l_found:
                                        await DisplayMsg.show(Message.PGN_GAME_END(result="*"))
                                    else:
                                        logger.debug("molli pgn: Wrong Move! Try Again!")
                                        # increase pgn guess counters
                                        if self.state.max_guess_black > 0 and self.state.game.turn == chess.WHITE:
                                            self.state.no_guess_black = self.state.no_guess_black + 1
                                            if self.state.no_guess_black > self.state.max_guess_black:
                                                await DisplayMsg.show(Message.MOVE_WRONG())
                                            else:
                                                await DisplayMsg.show(Message.MOVE_RETRY())
                                        elif self.state.max_guess_white > 0 and self.state.game.turn == chess.BLACK:
                                            self.state.no_guess_white = self.state.no_guess_white + 1
                                            if self.state.no_guess_white > self.state.max_guess_white:
                                                await DisplayMsg.show(Message.MOVE_WRONG())
                                            else:
                                                await DisplayMsg.show(Message.MOVE_RETRY())
                                        else:
                                            # user move wrong in pgn display mode only
                                            await DisplayMsg.show(Message.MOVE_RETRY())
                                        if self.board_type == dgt.util.EBoard.NOEBOARD:
                                            await Observable.fire(Event.TAKE_BACK(take_back="PGN_TAKEBACK"))
                                        else:
                                            self.state.takeback_active = True
                                            self.state.automatic_takeback = True
                                            await self.set_wait_state(
                                                Message.TAKE_BACK(game=self.state.game.copy()),
                                            )  # automatic takeback mode
                                else:
                                    logger.debug("molli pgn: Wrong Move! Try Again!")

                                    if self.state.max_guess_black > 0 and self.state.game.turn == chess.WHITE:
                                        self.state.no_guess_black = self.state.no_guess_black + 1
                                        if self.state.no_guess_black > self.state.max_guess_black:
                                            await DisplayMsg.show(Message.MOVE_WRONG())
                                        else:
                                            await DisplayMsg.show(Message.MOVE_RETRY())
                                    elif self.state.max_guess_white > 0 and self.state.game.turn == chess.BLACK:
                                        self.state.no_guess_white = self.state.no_guess_white + 1
                                        if self.state.no_guess_white > self.state.max_guess_white:
                                            await DisplayMsg.show(Message.MOVE_WRONG())
                                        else:
                                            await DisplayMsg.show(Message.MOVE_RETRY())
                                    else:
                                        # user move wrong in pgn display mode only
                                        await DisplayMsg.show(Message.MOVE_RETRY())

                                    if self.board_type == dgt.util.EBoard.NOEBOARD:
                                        await Observable.fire(Event.TAKE_BACK(take_back="PGN_TAKEBACK"))
                                    else:
                                        self.state.takeback_active = True
                                        self.state.automatic_takeback = True
                                        await self.set_wait_state(
                                            Message.TAKE_BACK(game=self.state.game.copy())
                                        )  # automatic takeback mode
                            else:
                                #  issue #14 0000 bestmove - not pgn replay - reload engine
                                result_str = self.state.pending_engine_result
                                self.state.pending_engine_result = None  # discard cached fallback once consumed
                                if not result_str:
                                    # Same logic as above: ping every engine after an illegal move
                                    # so we can distinguish a resignation from a crashed process.
                                    vb = self.state.get_variant_board()
                                    result_str = await self.engine.handle_bestmove_0000(
                                        self.state.game.copy(), variant_board=vb.copy() if vb else None
                                    )
                                result = game_result_from_header(result_str)  # "*" maps to ABORT
                                if result != GameResult.ABORT:
                                    await DisplayMsg.show(
                                        Message.GAME_ENDS(
                                            tc_init=self.state.time_control.get_parameters(),
                                            result=result,
                                            play_mode=self.state.play_mode,
                                            game=self.state.game.copy(),
                                            mode=self.state.interaction_mode,
                                        )
                                    )
                                else:
                                    logger.error("engine crashed - game has not ended")
                                    await DisplayMsg.show(Message.ENGINE_FAIL())
                                    await asyncio.sleep(0.5)
                                    # mimic the automatic-takeback logic used for mame blunders (see ~2360)
                                    # so the user can try a different move or pick another engine
                                    if self.board_type == dgt.util.EBoard.NOEBOARD:
                                        await Observable.fire(Event.TAKE_BACK(take_back="ENGINE_FAIL"))
                                    else:
                                        self.state.takeback_active = True
                                        self.state.automatic_takeback = True
                                        await self.set_wait_state(Message.TAKE_BACK(game=self.state.game.copy()))
                                    self.state.mame_recovery_rebase_pending = False
                                    loaded_ok = await self.engine.reopen_engine()
                                    if loaded_ok:
                                        capabilities = self.engine.get_mame_capabilities()
                                        if self.engine.is_mame_engine() and (
                                            capabilities.position or capabilities.edit
                                        ):
                                            recovery_board = self.state.engine_board_copy()
                                            self.state.mame_recovery_rebase_pending = (
                                                mame_requires_fresh_fen_root(
                                                    True,
                                                    capabilities.position,
                                                    capabilities.edit,
                                                )
                                                and bool(recovery_board.move_stack)
                                            )
                                            if self.state.mame_recovery_rebase_pending:
                                                recovery_board = recovery_board.copy(stack=False)
                                                logger.info(
                                                    "MAME recovery: synchronizing reopened engine from current FEN"
                                                )
                                            else:
                                                logger.info(
                                                    "MAME recovery: synchronizing reopened engine with move history"
                                                )
                                            await self.engine.newgame(
                                                recovery_board,
                                                send_ucinewgame=True,
                                                send_position_to_mame=True,
                                            )
                                        level_index = self.state.dgtmenu.get_engine_level_index()
                                        await DisplayMsg.show(
                                            Message.ENGINE_STARTUP(
                                                installed_engines=EngineProvider.installed_engines,
                                                file=self.state.engine_file,
                                                level_index=level_index,
                                                has_960=self.engine.has_chess960(),
                                                has_ponder=self.engine.has_ponder(),
                                            )
                                        )
                                        await asyncio.sleep(0.5)
                                        await DisplayMsg.show(Message.ENGINE_SETUP())
                                    else:
                                        logger.error("engine re-load failed")
                                        await DisplayMsg.show(Message.ENGINE_FAIL())
                        await asyncio.sleep(0.5)
                    elif self.state.newgame_happened:
                        # A new game was started while the engine was thinking.
                        # Discard the stale move – sending MSG_COMPUTER_MOVE now
                        # would display an illegal move on the new game's board.
                        logger.debug(
                            "EVT_BEST_MOVE: discarding stale engine move %s – new game started during think",
                            event.move,
                        )
                    else:
                        # normal computer move
                        if not engine_move_event_matches_state(
                            event_fen,
                            self.state.get_fen(),
                            event_search_revision,
                            self.state.engine_search_revision,
                            self.state.done_computer_fen,
                        ):
                            logger.info("engine move [%s] became stale before publication", event.move)
                            if should_resume_clock_after_rejected_engine_move(
                                clock_was_running,
                                self.state.time_control.internal_running(),
                                self.state.done_computer_fen,
                            ):
                                await self.state.start_clock()
                            return
                        if event.inbook:
                            await DisplayMsg.show(Message.BOOK_MOVE())
                        self.state.searchmoves.exclude(event.move)

                        if self.online_mode() or self.emulation_mode():
                            self.state.start_time_cmove_done = time.time()  # time should alraedy run for the player
                        await DisplayMsg.show(Message.EXIT_MENU())
                        await DisplayMsg.show(
                            Message.COMPUTER_MOVE(
                                move=event.move,
                                ponder=event.ponder,
                                game=self.state.game_copy(),
                                wait=event.inbook,
                                is_user_move=False,
                            )
                        )
                        game_copy = self.state.game.copy()
                        game_copy.push(event.move)

                        if self.picotutor_mode():
                            if self.pgn_mode():
                                t_color = self.state.picotutor.get_user_color()
                                if t_color == chess.BLACK:
                                    await self.state.picotutor.set_user_color(
                                        chess.WHITE, self.pgn_mode() or not self.eng_plays()
                                    )
                                else:
                                    await self.state.picotutor.set_user_color(
                                        chess.BLACK, self.pgn_mode() or not self.eng_plays()
                                    )

                            valid = await self.state.picotutor.push_move(event.move, game_copy)
                            if not valid:
                                await self.set_picotutor_position(position=game_copy)
                        self._prepare_engine_move(
                            game_copy,
                            event.move,
                            event.ponder if event.ponder and not event.inbook else chess.Move.null(),
                        )

                        if self.pgn_mode():
                            # molli pgn: reset pgn guess counters
                            if self.state.max_guess_black > 0 and not self.state.game.turn == chess.BLACK:
                                self.state.no_guess_black = 1
                            elif self.state.max_guess_white > 0 and not self.state.game.turn == chess.WHITE:
                                self.state.no_guess_white = 1

                        # molli: noeboard/WEB-Play
                        if self.board_type == dgt.util.EBoard.NOEBOARD:
                            logger.info("done move detected")
                            assert self.state.interaction_mode in (
                                Mode.NORMAL,
                                Mode.BRAIN,
                                Mode.REMOTE,
                                Mode.TRAINING,
                            ), (
                                "wrong mode: %s" % self.state.interaction_mode
                            )

                            await asyncio.sleep(0.5)
                            # Push the move and sync variant boards (e.g. 3check counter)
                            # BEFORE firing COMPUTER_MOVE_DONE so that the server-side
                            # _attach_variant_info re-stamp in COMPUTER_MOVE_DONE reads
                            # the freshly updated checks_remaining, not the pre-move value.
                            self.state.best_move_posted = False
                            self.state.push_move(self.state.done_move)  # computer move without human assistance
                            self._update_variant_shared()
                            await DisplayMsg.show(Message.COMPUTER_MOVE_DONE())
                            self.state.done_computer_fen = None
                            self.state.done_move = chess.Move.null()

                            if self.online_mode() or self.emulation_mode():
                                # for online or emulation engine the user time alraedy runs with move announcement
                                # => subtract time between announcement and execution
                                end_time_cmove_done = time.time()
                                cmove_time = math.floor(end_time_cmove_done - self.state.start_time_cmove_done)
                                if cmove_time > 0:
                                    self.state.time_control.sub_online_time(self.state.game.turn, cmove_time)
                                cmove_time = 0
                                self.state.start_time_cmove_done = 0

                            game_end = self.state.check_game_state()
                            if game_end:
                                await self.update_elo(game_end)
                                self.state.legal_fens = []
                                self.state.legal_fens_after_cmove = []
                                if self.online_mode():
                                    await self.stop_search_and_clock()
                                    self.state.stop_fen_timer()
                                await self.stop_search_and_clock()
                                if not self.pgn_mode():
                                    self.game_end_event()
                                    await DisplayMsg.show(game_end)
                            else:
                                self.state.searchmoves.reset()

                                self.state.time_control.add_time(not self.state.game.turn)

                                # molli new tournament time control
                                if (
                                    self.state.time_control.moves_to_go_orig > 0
                                    and (self.state.game.fullmove_number - 1)
                                    == self.state.time_control.moves_to_go_orig
                                ):
                                    self.state.time_control.add_game2(not self.state.game.turn)
                                    t_player = False
                                    msg = Message.TIMECONTROL_CHECK(
                                        player=t_player,
                                        movestogo=self.state.time_control.moves_to_go_orig,
                                        time1=self.state.time_control.game_time,
                                        time2=self.state.time_control.game_time2,
                                    )
                                    await DisplayMsg.show(msg)

                                if self.state.game.fullmove_number < 1:
                                    ModeInfo.reset_opening()
                                opening_message = self._current_opening_message()
                                if opening_message is not None:
                                    await DisplayMsg.show(opening_message)
                                    await asyncio.sleep(0.7)

                                if not self.online_mode() or self.state.game.fullmove_number > 1:
                                    await self.state.start_clock()
                                else:
                                    await DisplayMsg.show(Message.EXIT_MENU())  # show clock
                                    end_time_cmove_done = 0

                                self.state.legal_fens = compute_legal_fens(self.state.game, self.state.get_variant_board())
                                self.start_brain_hint_timer()

                                if self.pgn_mode():
                                    log_pgn(self.state)
                                    if self.state.game.turn == chess.WHITE:
                                        if self.state.max_guess_white > 0:
                                            if self.state.no_guess_white > self.state.max_guess_white:
                                                self.state.last_legal_fens = []
                                                await self.get_next_pgn_move()
                                        else:
                                            self.state.last_legal_fens = []
                                            await self.get_next_pgn_move()
                                    elif self.state.game.turn == chess.BLACK:
                                        if self.state.max_guess_black > 0:
                                            if self.state.no_guess_black > self.state.max_guess_black:
                                                self.state.last_legal_fens = []
                                                await self.get_next_pgn_move()
                                        else:
                                            self.state.last_legal_fens = []
                                            await self.get_next_pgn_move()

                            self.state.last_legal_fens = []
                            self.state.newgame_happened = False
                        # molli end noeboard/Web-Play
                else:
                    logger.warning(
                        "wrong function call [best]! mode: %s turn: %s",
                        self.state.interaction_mode,
                        self.state.game.turn,
                    )
            else:
                logger.warning(
                    "wrong function call [best]! mode: %s turn: %s",
                    self.state.interaction_mode,
                    self.state.game.turn,
                )

        elif isinstance(event, Event.NEW_PV):
            if event.pv[0]:
                # illegal moves can occur if a pv from the engine arrives
                # at the same time as an user move
                # Use variant board for legality check (atomic has different legal moves)
                pv_check_board = self.state.get_move_check_board()
                if pv_check_board.is_legal(event.pv[0]):
                    # only pv received from event
                    await DisplayMsg.show(
                        Message.NEW_PV(
                            pv=event.pv,
                            mode=self.state.interaction_mode,
                            game=self.state.game_copy(),
                        )
                    )
                else:
                    self.state.best_sent_depth.reset()
                    logger.info(
                        "illegal move can not be displayed. move: %s fen: %s",
                        event.pv[0],
                        self.state.get_fen(),
                    )
                    logger.info("engine status: t:%s p:%s", self.engine.is_thinking(), self.engine.is_pondering())

        elif isinstance(event, Event.NEW_SCORE):
            if event.score is not None:
                if event.score == 99999 or event.score == -99999:
                    self.state.flag_pgn_game_over = True  # molli pgn mode: signal that pgn is at end
                else:
                    self.state.flag_pgn_game_over = False

                # only score and mate received from event, turn is missing
                await DisplayMsg.show(
                    Message.NEW_SCORE(
                        score=event.score,
                        mate=event.mate,
                        mode=self.state.interaction_mode,
                        turn=self.state.game.turn,
                    )
                )

        elif isinstance(event, Event.NEW_DEPTH):
            if event.depth:
                if event.depth == 999:
                    self.state.flag_pgn_game_over = True
                else:
                    self.state.flag_pgn_game_over = False
                await DisplayMsg.show(Message.NEW_DEPTH(depth=event.depth))

        elif isinstance(event, Event.START_SEARCH):
            await DisplayMsg.show(Message.SEARCH_STARTED())

        elif isinstance(event, Event.STOP_SEARCH):
            await DisplayMsg.show(Message.SEARCH_STOPPED())

        elif isinstance(event, Event.SET_INTERACTION_MODE):
            self.state.best_sent_depth.reset()  # dont use optimisation when switching modes
            old_interaction_mode = self.state.interaction_mode
            entering_ponder = old_interaction_mode != Mode.PONDER and event.mode == Mode.PONDER
            leaving_ponder = old_interaction_mode == Mode.PONDER and event.mode != Mode.PONDER
            returning_restored_checkpoint = bool(
                leaving_ponder and self.state.can_preserve_position_checkpoint_play_mode()
            )
            preserve_checkpoint_play_mode = bool(
                returning_restored_checkpoint
                and event.mode in (Mode.NORMAL, Mode.BRAIN, Mode.TRAINING)
            )
            if self.eng_plays() and event.mode not in (Mode.NORMAL, Mode.BRAIN, Mode.TRAINING):
                # things to do when we change from a playing mode to non-playing
                await self.get_rid_of_engine_move()  # force/get-rid of engine move
            if self.state.interaction_mode == Mode.PGNREPLAY and event.mode != Mode.PGNREPLAY:
                self._set_pgn_replay_autoplay(False, mode=event.mode)
            elif not self.eng_plays() and event.mode in (Mode.NORMAL, Mode.BRAIN, Mode.TRAINING):
                # things to do i we change from a non-playing mode to a playing mode
                self._set_pgn_replay_autoplay(False, mode=event.mode)  # stop possible auto replay of pgn file
            if (
                event.mode not in (Mode.NORMAL, Mode.REMOTE, Mode.TRAINING) and self.state.done_computer_fen
            ):  # @todo check why still needed
                self.state.dgtmenu.set_mode(self.state.interaction_mode)  # undo the button4 stuff
                logger.warning("mode cant be changed to a pondering mode as long as a move is displayed")
                mode_text = self.state.dgttranslate.text("Y10_errormode")
                msg = Message.INTERACTION_MODE(mode=self.state.interaction_mode, mode_text=mode_text, show_ok=False)
                await DisplayMsg.show(msg)
            else:
                if event.mode == Mode.PONDER:
                    self.state.newgame_happened = False
                await self.stop_search_and_clock()
                if leaving_ponder:
                    # A normal mode selection commits the current PONDER
                    # position.  A restore has already put Tutor and the
                    # game back at the checkpoint.  In either case the
                    # temporary-analysis checkpoint ends with this mode
                    # transition.
                    if (
                        self.state.picotutor is not None
                        and not boards_match_position_and_history(self.state.picotutor.board, self.state.game)
                    ):
                        await self.state.picotutor.set_analysis_enabled(False)
                        await self.state.picotutor.set_position(self.state.game.copy(), new_game=False)
                    self._clear_position_checkpoint()
                if event.mode == Mode.PGNREPLAY and not returning_restored_checkpoint:
                    loaded_pgn_game = self.state.loaded_pgn_game
                    if loaded_pgn_game is not None:
                        file_name_only = self.state.loaded_pgn_filename or "loaded PGN"
                        await self.read_pgn_file(
                            file_name_only,
                            start_replay=True,
                            pgn_game=copy.deepcopy(loaded_pgn_game),
                        )
                    else:
                        file_name_only = "last_game.pgn"
                        await self.read_pgn_file(file_name_only, start_replay=True)
                    await self._start_or_stop_analysis_as_needed()
                else:
                    self.state.interaction_mode = event.mode
                    if entering_ponder:
                        await self._save_position_checkpoint(old_interaction_mode)
                    await self.engine_mode()
                    msg = Message.INTERACTION_MODE(
                        mode=event.mode, mode_text=event.mode_text, show_ok=event.show_ok
                    )
                    await self.set_wait_state(
                        msg,
                        preserve_play_mode=preserve_checkpoint_play_mode,
                    )  # dont clear searchmoves here

        elif isinstance(event, Event.SET_PGN_REPLAY_TUTOR_REGENERATION):
            self._set_pgn_replay_tutor_regeneration(event.enabled, override=True)
            if self.state.picotutor is not None:
                await self.state.picotutor.set_analysis_enabled(self.tutor_analysis_enabled_for_current_mode())
                await self.state.picotutor.set_mode(self.pgn_mode() or not self.eng_plays())
            await self._start_or_stop_analysis_as_needed()

        elif isinstance(event, Event.RESTORE_POSITION_CHECKPOINT):
            await self._restore_position_checkpoint()

        elif isinstance(event, Event.SET_OPENING_BOOK):
            book_file = event.book["file"]
            logger.debug("changing opening book [%s]", book_file)
            try:
                bookreader = chess.polyglot.open_reader(book_file)
            except OSError as exc:
                logger.warning("failed to open book '%s': %s", book_file, exc)
                return
            write_picochess_ini("book", book_file)
            self.bookreader = bookreader
            await DisplayMsg.show(Message.OPENING_BOOK(book_text=event.book_text, show_ok=event.show_ok))
            self.state.book_in_use = book_file
            self.state.stop_fen_timer()

        elif isinstance(event, Event.SHOW_ENGINENAME):
            self.state.dgtmenu.set_enginename(event.show_enginename)
            await DisplayMsg.show(Message.SHOW_ENGINENAME(show_enginename=event.show_enginename))

        elif isinstance(event, Event.SAVE_GAME):
            if event.pgn_filename:
                await self.state.stop_clock()
                await DisplayMsg.show(
                    Message.SAVE_GAME(
                        tc_init=self.state.time_control.get_parameters(),
                        play_mode=self.state.play_mode,
                        game=self.state.game.copy(),
                        pgn_filename=event.pgn_filename,
                        mode=self.state.interaction_mode,
                    )
                )

        elif isinstance(event, Event.READ_GAME):
            if event.pgn_filename:
                self._clear_position_checkpoint()
                show_headers = getattr(event, "show_headers", True)
                if show_headers:
                    await DisplayMsg.show(Message.READ_GAME(pgn_filename=event.pgn_filename))
                await self.read_pgn_file(event.pgn_filename, show_headers=show_headers)
                await self._start_or_stop_analysis_as_needed()

        elif isinstance(event, Event.CONTLAST):
            self.state.dgtmenu.set_continue_game(event.contlast)
            await DisplayMsg.show(Message.CONTLAST(contlast=event.contlast))

        elif isinstance(event, Event.ALTMOVES):
            self.state.dgtmenu.set_alt_move(event.altmoves)
            await DisplayMsg.show(Message.ALTMOVES(altmoves=event.altmoves))

        elif isinstance(event, Event.PICOWATCHER):
            self.state.dgtmenu.set_picowatcher(event.picowatcher)
            write_picochess_ini("tutor-watcher", event.picowatcher)
            self.state.best_sent_depth.reset()
            await self.state.picotutor.set_status(
                self.state.dgtmenu.get_picowatcher(),
                self.state.dgtmenu.get_picocoach(),
                self.state.dgtmenu.get_picoexplorer(),
                self.state.dgtmenu.get_picocomment(),
            )
            if event.picowatcher:
                self.state.flag_picotutor = True
                # @ todo - why do we need to re-set position in tutor?
                await self.set_picotutor_position()
            elif self.state.dgtmenu.get_picocoach() != PicoCoach.COACH_OFF:
                self.state.flag_picotutor = True
            elif self.state.dgtmenu.get_picoexplorer():
                self.state.flag_picotutor = True
            else:
                self.state.flag_picotutor = False

            if self.state.flag_picotutor:
                await self.state.picotutor.set_mode(self.pgn_mode() or not self.eng_plays())
            # Clear stale web analysis lines and restart the engine analyser so the
            # correct lines (engine / tutor) appear immediately after tutor state change.
            await DisplayMsg.show(Message.WEB_ANALYSIS(analysis=None))
            await self._start_or_stop_analysis_as_needed()
            await DisplayMsg.show(Message.PICOWATCHER(picowatcher=event.picowatcher))

        elif isinstance(event, Event.PICOCOACH):
            coach_request = event.picocoach
            if coach_request in (
                PicoCoach.COACH_OFF,
                PicoCoach.COACH_ON,
                PicoCoach.COACH_LIFT,
                PicoCoach.COACH_BRAIN,
                PicoCoach.COACH_HAND,
            ):
                self.state.coach_triggered_piece_type = None
                if coach_request == PicoCoach.COACH_OFF:
                    self.state.dgtmenu.set_picocoach(PicoCoach.COACH_OFF)
                    write_picochess_ini("tutor-coach", "off")
                    self.cancel_brain_hint_timer()
                elif coach_request == PicoCoach.COACH_ON:
                    self.state.dgtmenu.set_picocoach(PicoCoach.COACH_ON)
                    write_picochess_ini("tutor-coach", "on")
                elif coach_request == PicoCoach.COACH_LIFT:
                    self.state.dgtmenu.set_picocoach(PicoCoach.COACH_LIFT)
                    write_picochess_ini("tutor-coach", "lift")
                elif coach_request == PicoCoach.COACH_BRAIN:
                    self.state.dgtmenu.set_picocoach(PicoCoach.COACH_BRAIN)
                    write_picochess_ini("tutor-coach", "brain")
                else:
                    self.state.dgtmenu.set_picocoach(PicoCoach.COACH_HAND)
                    write_picochess_ini("tutor-coach", "hand")
            elif coach_request == 0:
                self.state.dgtmenu.set_picocoach(PicoCoach.COACH_OFF)
                write_picochess_ini("tutor-coach", "off")
                self.cancel_brain_hint_timer()
            elif coach_request == 1 and self.state.dgtmenu.get_picocoach() == PicoCoach.COACH_OFF:
                self.state.dgtmenu.set_picocoach(PicoCoach.COACH_ON)
                write_picochess_ini("tutor-coach", "on")
            self.state.best_sent_depth.reset()
            await self.state.picotutor.set_status(
                self.state.dgtmenu.get_picowatcher(),
                self.state.dgtmenu.get_picocoach(),
                self.state.dgtmenu.get_picoexplorer(),
                self.state.dgtmenu.get_picocomment(),
            )
            coach_mode = self.state.dgtmenu.get_picocoach()
            if coach_mode != PicoCoach.COACH_BRAIN:
                self.cancel_brain_hint_timer()
            if coach_mode != PicoCoach.COACH_HAND and self.state.hand_coach_task:
                if not self.state.hand_coach_task.done():
                    self.state.hand_coach_task.cancel()
                self.state.hand_coach_task = None
                self.state.last_hand_coach_move = None

            if coach_mode != PicoCoach.COACH_OFF:
                self.state.flag_picotutor = True
                # @ todo - why do we need to set tutor pos here?
                await self.set_picotutor_position()
            elif self.state.dgtmenu.get_picowatcher():
                self.state.flag_picotutor = True
            elif self.state.dgtmenu.get_picoexplorer():
                self.state.flag_picotutor = True
            else:
                self.state.flag_picotutor = False

            if self.state.flag_picotutor:
                await self.state.picotutor.set_mode(self.pgn_mode() or not self.eng_plays())
                if coach_mode == PicoCoach.COACH_BRAIN:
                    self.start_brain_hint_timer()
            # Clear stale web analysis lines and restart the engine analyser so the
            # correct lines (engine / tutor) appear immediately after tutor state change.
            await DisplayMsg.show(Message.WEB_ANALYSIS(analysis=None))
            await self._start_or_stop_analysis_as_needed()
            if coach_request != 2:
                coach_msg = 0
                if coach_mode == PicoCoach.COACH_ON:
                    coach_msg = 1
                elif coach_mode == PicoCoach.COACH_LIFT:
                    coach_msg = 2
                elif coach_mode == PicoCoach.COACH_BRAIN:
                    coach_msg = 3
                elif coach_mode == PicoCoach.COACH_HAND:
                    coach_msg = 4
                await DisplayMsg.show(Message.PICOCOACH(picocoach=coach_msg))
                if self.shared is not None:
                    if coach_mode != PicoCoach.COACH_OFF:
                        self.shared["tutor_watch_coach_pref"] = coach_mode
                    self.shared["tutor_watch_coach"] = coach_mode != PicoCoach.COACH_OFF
                    self.shared["tutor_watch_active"] = bool(
                        self.shared.get("tutor_watch_watcher") or self.shared.get("tutor_watch_coach")
                    )

            if self.state.dgtmenu.get_picocoach() != PicoCoach.COACH_OFF and coach_request == 2:
                # call pico coach in case it was already set to on
                if self.state.dgtmenu.get_picocoach() == PicoCoach.COACH_BRAIN:
                    self.start_brain_hint_timer()
                elif self.state.dgtmenu.get_picocoach() == PicoCoach.COACH_HAND:
                    self.state.last_hand_coach_move = None
                else:
                    await self.call_pico_coach()

        elif isinstance(event, Event.PICOEXPLORER):
            self.state.dgtmenu.set_picoexplorer(event.picoexplorer)
            write_picochess_ini("tutor-explorer", event.picoexplorer)
            self.state.best_sent_depth.reset()
            await self.state.picotutor.set_status(
                self.state.dgtmenu.get_picowatcher(),
                self.state.dgtmenu.get_picocoach(),
                self.state.dgtmenu.get_picoexplorer(),
                self.state.dgtmenu.get_picocomment(),
            )
            if event.picoexplorer:
                self.state.flag_picotutor = True
            else:
                if self.state.dgtmenu.get_picowatcher() or (
                    self.state.dgtmenu.get_picocoach() != PicoCoach.COACH_OFF
                ):
                    self.state.flag_picotutor = True
                else:
                    self.state.flag_picotutor = False

            if self.state.flag_picotutor:
                await self.state.picotutor.set_mode(self.pgn_mode() or not self.eng_plays())
            await DisplayMsg.show(Message.PICOEXPLORER(picoexplorer=event.picoexplorer))

        elif isinstance(event, Event.SET_RETRO_WINDOW):
            self.state.dgtmenu.set_retro_window(event.windowed)
            if self.emulation_mode() and self.state.dgtmenu.get_engine_rdisplay():
                cmd = get_window_command("switch_window_toggle_fullscreen")
                if cmd:
                    process = await asyncio.create_subprocess_shell(
                        cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _, stderr = await process.communicate()
                    if process.returncode != 0:
                        logger.error(
                            "Retro window command failed with return code %s: %s",
                            process.returncode,
                            stderr.decode(),
                        )

        elif isinstance(event, Event.RSPEED):
            self.state.dgtmenu.set_retro_speed(event.rspeed)
            if self.emulation_mode():
                # restart engine with new retro speed
                self.state.artwork_in_use = False
                engine_file_to_load = self.state.engine_file  # assume not mame
                if "/mame/" in self.state.engine_file and self.state.dgtmenu.get_engine_rdisplay():
                    engine_file_art = self.state.engine_file + "_art"
                    my_file = Path(engine_file_art)
                    if my_file.is_file():
                        self.state.artwork_in_use = True
                        engine_file_to_load = engine_file_art  # load mame
                old_options = self.engine.get_pgn_options()
                await DisplayMsg.show(Message.ENGINE_SETUP())
                await self.engine.quit()
                self.engine = UciEngine(
                    file=engine_file_to_load,
                    uci_shell=self.uci_local_shell,
                    mame_par=self.calc_engine_mame_par(),
                    loop=self.loop,
                )
                await self.engine.open_engine()
                if engine_file_to_load != self.state.engine_file:
                    await asyncio.sleep(1)  # mame artwork wait
                await self.engine.startup(old_options, self.state.rating)
                ModeInfo.set_retro_features(self.engine.get_mame_capabilities().retro_info())
                await self.stop_search_and_clock()

                if (
                    self.state.dgtmenu.get_engine_rdisplay()
                    and not is_wayland_session()
                    and not self.state.dgtmenu.get_engine_rwindow()
                    and self.state.artwork_in_use
                ):
                    # Preserve the old X11 fullscreen fallback. Wayland startup mode
                    # is controlled by MAME -window/-nowindow parameters.
                    cmd = get_window_command("toggle_fullscreen")
                    if cmd:
                        process = await asyncio.create_subprocess_shell(
                            cmd,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        stdout, stderr = await process.communicate()
                        if process.returncode != 0:
                            logger.error(
                                "Command failed with return code %s: %s", process.returncode, stderr.decode()
                            )
                game_fen = self.state.game.board_fen()
                if self.state.variant == "racingkings":
                    self.state.game = chess.Board("8/8/8/8/8/8/krbnNBRK/qrbnNBRQ w - - 0 1")
                else:
                    self.state.game = chess.Board()
                self.state.game.turn = chess.WHITE
                self.state.reset_variant_board()
                self.state.play_mode = PlayMode.USER_WHITE
                starting_fen = RK_STARTING_BOARD_FEN if self.state.variant == "racingkings" else chess.STARTING_BOARD_FEN
                if game_fen != starting_fen:
                    msg = self.state.new_game_msg(newgame=True)
                    await DisplayMsg.show(msg)
                await self.engine.newgame(self.state.engine_board_copy())
                self.state.best_sent_depth.reset()
                self.state.done_computer_fen = None
                self.state.done_move = self.state.pb_move = chess.Move.null()
                self.state.searchmoves.reset()
                self.state.game_declared = False
                self.state.legal_fens = compute_legal_fens(self.state.game, self.state.get_variant_board())
                self.state.last_legal_fens = []
                self.state.legal_fens_after_cmove = []
                await self.engine_mode()
                await DisplayMsg.show(Message.RSPEED(rspeed=event.rspeed))
                await self.update_elo_display()

        elif isinstance(event, Event.TAKE_BACK):
            self.state.best_sent_depth.reset()
            if self.state.game.move_stack and (
                event.take_back == "PGN_TAKEBACK"
                or not should_block_takeback(
                    take_back_locked=self.state.take_back_locked,
                    online_mode=self.online_mode(),
                    emulation_mode=self.emulation_mode(),
                    automatic_takeback=self.state.automatic_takeback,
                    ponder_mode=self.state.interaction_mode == Mode.PONDER,
                )
            ):
                await self.get_rid_of_engine_move()  # unnecessary engine move not yet done
                await self.takeback()

        elif isinstance(event, Event.PICOCOMMENT):
            if isinstance(event.picocomment, str) and event.picocomment.startswith("comment-factor"):
                if ":" in event.picocomment:
                    try:
                        comment_factor = max(0, min(100, int(event.picocomment.split(":", 1)[1])))
                    except (TypeError, ValueError):
                        comment_factor = self.state.dgtmenu.get_comment_factor()
                    self.state.dgtmenu.set_comment_factor(comment_factor)
                    write_picochess_ini("comment-factor", str(comment_factor))
                else:
                    comment_factor = self.state.dgtmenu.get_comment_factor()
                self.pico_talker.set_comment_factor(comment_factor=comment_factor)
                await DisplayMsg.show(Message.PICOCOMMENT(picocomment=f"comment-factor:{comment_factor}"))
            else:
                _comment_ini = {
                    PicoComment.COM_OFF:    "off",
                    PicoComment.COM_ON_ENG: "single",
                    PicoComment.COM_ON_ALL: "all",
                }
                if event.picocomment in _comment_ini:
                    self.state.dgtmenu.set_picocomment(event.picocomment)
                    write_picochess_ini("tutor-comment", _comment_ini[event.picocomment])
                await DisplayMsg.show(Message.PICOCOMMENT(picocomment=event.picocomment))

        elif isinstance(event, Event.SET_TIME_CONTROL):
            self.state.time_control.stop_internal(log=False)
            tc_init = event.tc_init
            self.state.dgtmenu.set_time_control(tc_init)

            self.state.time_control = TimeControl(**tc_init)

            if not self.pgn_mode() and not self.online_mode():
                if tc_init["moves_to_go"] > 0:
                    if self.state.time_control.mode == TimeMode.BLITZ:
                        write_picochess_ini(
                            "time",
                            "{:d} {:d} 0 {:d}".format(tc_init["moves_to_go"], tc_init["blitz"], tc_init["blitz2"]),
                        )
                    elif self.state.time_control.mode == TimeMode.FISCHER:
                        write_picochess_ini(
                            "time",
                            "{:d} {:d} {:d} {:d}".format(
                                tc_init["moves_to_go"],
                                tc_init["blitz"],
                                tc_init["fischer"],
                                tc_init["blitz2"],
                            ),
                        )
                elif self.state.time_control.mode == TimeMode.BLITZ:
                    write_picochess_ini("time", "{:d} 0".format(tc_init["blitz"]))
                elif self.state.time_control.mode == TimeMode.FISCHER:
                    write_picochess_ini("time", "{:d} {:d}".format(tc_init["blitz"], tc_init["fischer"]))
                elif self.state.time_control.mode == TimeMode.FIXED:
                    write_picochess_ini("time", "{:d}".format(tc_init["fixed"]))
                    # issue 87 - store user override depth/node if flag set
                    # New user choice overrides possibly loaded engine dummy uci options
                    # Node/Depth is a pair - drop both from uci and write both to ini
                    # this guarantees that we dont mix ini and uci file settings
                    # 671 (11 minutes 11 seconds) is the flag
                    if self.state.time_control.move_time == 671:
                        self.engine.drop_engine_uci_option("PicoDepth")  # user override
                        write_picochess_ini("depth", "{:d}".format(tc_init["depth"]))
                        self.engine.drop_engine_uci_option("PicoNode")  # user overrides
                        write_picochess_ini("node", "{:d}".format(tc_init["node"]))
            text = Message.TIME_CONTROL(time_text=event.time_text, show_ok=event.show_ok, tc_init=tc_init)
            await DisplayMsg.show(text)
            self.state.stop_fen_timer()

        elif isinstance(event, Event.CLOCK_TIME):
            if self.dgtdispatcher.is_prio_device(
                event.dev, event.connect
            ):  # transfer only the most prio clock's time
                # avoid debugs for every second
                #                    logger.debug(
                #                        "setting tc clock time - prio: %s w:%s b:%s",
                #                        event.dev,
                #                        hms_time(event.time_white),
                #                        hms_time(event.time_black),
                #                    )

                if self.state.time_control.mode != TimeMode.FIXED and (
                    event.time_white == self.state.time_control.game_time
                    and event.time_black == self.state.time_control.game_time
                ):
                    pass
                else:
                    moves_to_go = self.state.time_control.moves_to_go_orig - self.state.game.fullmove_number + 1
                    if moves_to_go < 0:
                        moves_to_go = 0
                    # logger.debug("setting tc clock times")
                    self.state.time_control.set_clock_times(
                        white_time=event.time_white,
                        black_time=event.time_black,
                        moves_to_go=moves_to_go,
                    )

                low_time = False  # molli allow the speech output even for less than 60 seconds
                self.dgtboard.low_time = low_time
                if self.state.interaction_mode == Mode.TRAINING or self.state.position_mode:
                    pass
                else:
                    await DisplayMsg.show(
                        Message.CLOCK_TIME(
                            time_white=event.time_white,
                            time_black=event.time_black,
                            low_time=low_time,
                        )
                    )
            else:
                logger.debug("ignore clock time - too low prio: %s", event.dev)
        elif isinstance(event, Event.OUT_OF_TIME):
            # Local timeout is a soft warning: Picochess historically allows
            # casual play to continue after the clock flag falls. A new clock
            # period may start after play resumes, so report every new flag fall.
            # Use the mode flag: this timer event can race with engine replacement.
            if should_report_local_timeout(ModeInfo.get_online_mode()):
                await self.state.stop_clock()
                await DisplayMsg.show(Message.LOST_ON_TIME())

        elif isinstance(event, Event.SHUTDOWN):
            await self.get_rid_of_engine_move()
            await self.pre_exit_or_reboot_cleanups()
            try:
                if self.uci_remote_shell:
                    if self.uci_remote_shell.get():
                        try:
                            self.uci_remote_shell.get().__exit__(
                                None, None, None
                            )  # force to call __exit__ (close shell connection)
                        except Exception:
                            pass
            except Exception:
                pass

            result = GameResult.ABORT
            self.game_end_event()
            await DisplayMsg.show(
                Message.GAME_ENDS(
                    tc_init=self.state.time_control.get_parameters(),
                    result=result,
                    play_mode=self.state.play_mode,
                    game=self.state.game.copy(),
                    mode=self.state.interaction_mode,
                )
            )
            await DisplayMsg.show(Message.SYSTEM_SHUTDOWN())
            # no messaging or events beyond this point
            await asyncio.sleep(3)  # molli allow more time (5) for commentary chat
            shutdown(self.args.dgtpi, dev=event.dev)  # @todo make independant of remote eng
            await self.final_exit_or_reboot_cleanups()

        elif isinstance(event, Event.REBOOT):
            await self.get_rid_of_engine_move()
            await self.pre_exit_or_reboot_cleanups()
            result = GameResult.ABORT
            self.game_end_event()
            await DisplayMsg.show(
                Message.GAME_ENDS(
                    tc_init=self.state.time_control.get_parameters(),
                    result=result,
                    play_mode=self.state.play_mode,
                    game=self.state.game.copy(),
                    mode=self.state.interaction_mode,
                )
            )
            await DisplayMsg.show(Message.SYSTEM_REBOOT())
            # no messaging or events beyond this point
            await asyncio.sleep(3)  # molli allow more time (5) for commentary chat
            reboot(
                self.args.dgtpi and self.uci_local_shell.get() is None, dev=event.dev
            )  # @todo make independant of remote eng
            await self.final_exit_or_reboot_cleanups()

        elif isinstance(event, Event.EXIT):
            await self.get_rid_of_engine_move()
            await self.pre_exit_or_reboot_cleanups()
            result = GameResult.ABORT
            self.game_end_event()
            await DisplayMsg.show(
                Message.GAME_ENDS(
                    tc_init=self.state.time_control.get_parameters(),
                    result=result,
                    play_mode=self.state.play_mode,
                    game=self.state.game.copy(),
                    mode=self.state.interaction_mode,
                )
            )
            # await DisplayMsg.show(Message.SYSTEM_EXIT())
            # no messaging or events beyond this point
            await asyncio.sleep(3)  # molli allow more time (5) for commentary chat
            exit_pico(self.args.dgtpi, dev=event.dev)  # @todo make independant of remote eng
            await self.final_exit_or_reboot_cleanups()

        elif isinstance(event, Event.EMAIL_LOG):
            email_logger = Emailer(email=self.args.email, mailgun_key=self.args.mailgun_key)
            email_logger.set_smtp(
                sserver=self.args.smtp_server,
                suser=self.args.smtp_user,
                spass=self.args.smtp_pass,
                sencryption=self.args.smtp_encryption,
                sstarttls=self.args.smtp_starttls,
                sport=self.args.smtp_port,
                sfrom=self.args.smtp_from,
            )
            body = "You probably want to forward this file to a picochess developer ;-)"
            email_logger.send("Picochess LOG", body, "/opt/picochess/logs/{}".format(self.args.log_file))

        elif isinstance(event, Event.SET_VOICE):
            await DisplayMsg.show(
                Message.SET_VOICE(type=event.type, lang=event.lang, speaker=event.speaker, speed=event.speed)
            )

        elif isinstance(event, Event.KEYBOARD_BUTTON):
            await DisplayMsg.show(Message.DGT_BUTTON(button=event.button, dev=event.dev))

        elif isinstance(event, Event.KEYBOARD_FEN):
            await DisplayMsg.show(Message.DGT_FEN(fen=event.fen, raw=False))

        elif isinstance(event, Event.EXIT_MENU):
            await DisplayMsg.show(Message.EXIT_MENU())

        elif isinstance(event, Event.UPDATE_PICO):
            await DisplayMsg.show(Message.UPDATE_PICO())
            if not event.tag or event.tag == "":
                # Full update on next boot through picochess-update.service.
                update_pico_v4()
            else:
                # only update code to a specific tag
                checkout_tag(event.tag)
            await DisplayMsg.show(Message.EXIT_MENU())

        elif isinstance(event, Event.UPDATE_ENGINES):
            await DisplayMsg.show(Message.UPDATE_PICO())
            update_pico_engines()  # in utilities for now
            await DisplayMsg.show(Message.EXIT_MENU())

        elif isinstance(event, Event.REMOTE_ROOM):
            await DisplayMsg.show(Message.REMOTE_ROOM(inside=event.inside))

        elif isinstance(event, Event.PROMOTION):
            await DisplayMsg.show(Message.PROMOTION_DONE(move=event.move))

        else:  # Default
            logger.info("event not handled : [%s]", event)
            await asyncio.sleep(0.05)  # balance message queues

    def exit_sigterm(self, signum, frame):
        """A handler function to register for systemctl stop signal"""
        if self.shutdown_requested.is_set():
            logger.debug("Shutdown already in progress; ignoring signal %s", signum)
            return
        logger.debug("Received kill signal, shutting down")
        # Queue all asyncio state changes through the loop's signal-safe
        # callback entry point.
        self.loop.call_soon_threadsafe(self._start_shutdown_task)

    def _start_shutdown_task(self) -> None:
        """Create the shutdown task from the event loop itself."""
        if self.shutdown_task is None:
            self.shutdown_requested.set()
            logger.debug("Starting shutdown task on event loop")
            self.shutdown_task = self.loop.create_task(self._exit_async())

    async def _exit_async(self):
        """Async function to handle systemctl stop signal"""
        logger.debug("Shutting down all async tasks")
        try:
            await self.pre_exit_or_reboot_cleanups()
            await self.final_exit_or_reboot_cleanups()
        except Exception:
            logger.exception("Error during shutdown")
            sys.exit(-1)  # force exit on error

    async def wait_for_board_connection(self):
        """Wait for the DGT eBoard connection without blocking other startup tasks."""
        # Wait for eBoard connection unless we are in no-eboards mode
        if self.board_type != dgt.util.EBoard.NOEBOARD:
            board_connected = getattr(self.dgtboard, "is_connected", None)
            if callable(board_connected):
                while not board_connected():
                    await asyncio.sleep(0.2)

        await self._start_or_stop_analysis_as_needed()  # start analysis if needed
        self.background_analyse_timer.start()  # always run background analyser
