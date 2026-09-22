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
import os
import copy
import logging
from logging.handlers import RotatingFileHandler
from typing import Any
import asyncio

from tornado.platform.asyncio import AsyncIOMainLoop
import dgt.util

from picostate import PicochessState

from configuration import Configuration
from uci.engine_provider import EngineProvider

from theme import ThemeResolver
from utilities import update_pico_v4
from utilities import DisplayMsg, version, set_window_control_backend_preference
from pgn import Emailer, PgnDisplay, ModeInfo
from server import WebDisplay, WebServer, WebVr, EventHandler
from picotalker import PicoTalkerDisplay
from dispatcher import Dispatcher

from dgt.api import Message
from dgt.util import PicoComment, PicoCoach
from dgt.hw import DgtHw
from dgt.pi import DgtPi
from dgt.display import DgtDisplay
from dgt.board import DgtBoard, Rev2Info
from dgt.translate import DgtTranslate
from dgt.menu import DgtMenu
from eboard.eboard import EBoard
from eboard.chesslink.board import ChessLinkBoard
from eboard.chessnut.board import ChessnutBoard
from eboard.ichessone.board import IChessOneBoard
from eboard.certabo.board import CertaboBoard
import pairing_ipc
from mainloop import MainLoop

logger = logging.getLogger(__name__)

WEB_SERVER_DEFAULT_PORT = 80
WEB_SERVER_PERMISSION_FALLBACK_PORT = 8080
WEB_SERVER_SETCAP_HINT = "sudo setcap 'cap_net_bind_service=+ep' $(readlink -f $(which python3))"


async def gather_main_tasks(tasks, shutdown_requested: asyncio.Event) -> None:
    """Wait for application tasks, suppressing cancellation only during an intentional shutdown."""
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        if not shutdown_requested.is_set():
            raise


async def wait_for_shutdown_cleanup(shutdown_requested: asyncio.Event, shutdown_complete: asyncio.Event) -> None:
    """Keep the event loop alive until an intentional shutdown has released its resources."""
    if shutdown_requested.is_set():
        await shutdown_complete.wait()


class WebServerListenError(RuntimeError):
    """Capture the port and reason when Tornado cannot bind the web server."""

    def __init__(self, port: int, reason: str, original_error: OSError):
        super().__init__(str(original_error))
        self.port = port
        self.reason = reason
        self.original_error = original_error


def _listen_web_app(web_app: Any, requested_port: int) -> int:
    try:
        web_app.listen(requested_port)
        return requested_port
    except PermissionError as exc:
        if requested_port != WEB_SERVER_DEFAULT_PORT:
            raise WebServerListenError(requested_port, "permission", exc) from exc

        fallback_port = WEB_SERVER_PERMISSION_FALLBACK_PORT
        logger.warning("Could not start web server - port %d not allowed by operating system", requested_port)
        logger.warning("Falling back to web server port %d", fallback_port)
        logger.warning("To restore port %d, try: %s", requested_port, WEB_SERVER_SETCAP_HINT)
        try:
            web_app.listen(fallback_port)
        except PermissionError as fallback_exc:
            raise WebServerListenError(fallback_port, "permission", fallback_exc) from fallback_exc
        except OSError as fallback_exc:
            raise WebServerListenError(fallback_port, "unavailable", fallback_exc) from fallback_exc
        return fallback_port
    except OSError as exc:
        raise WebServerListenError(requested_port, "unavailable", exc) from exc


async def main() -> None:
    """Main function."""
    # Use asyncio's event loop as the Tornado IOLoop
    AsyncIOMainLoop().install()
    main_loop = asyncio.get_event_loop()

    own_user = ""
    opp_user = ""
    game_time = 0
    fischer_inc = 0
    login = ""

    config = Configuration()
    args, unknown = config._args, config.unknown
    set_window_control_backend_preference(args.window_control_backend)

    # Enable logging
    if args.log_file:
        handler = RotatingFileHandler("logs" + os.sep + args.log_file, maxBytes=1 * 1024 * 1024, backupCount=5)
        logging.basicConfig(
            level=getattr(logging, args.log_level.upper()),
            format="%(asctime)s.%(msecs)03d %(levelname)7s %(module)10s - %(funcName)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            handlers=[handler],
        )
    logging.getLogger("chess.engine").setLevel(logging.INFO)  # don't want to get so many python-chess uci messages

    logger.debug("#" * 20 + " PicoChess v%s " + "#" * 20, version)
    # log the startup parameters but hide the password fields
    a_copy = copy.copy(vars(args))
    a_copy["mailgun_key"] = a_copy["smtp_pass"] = a_copy["engine_remote_key"] = a_copy["engine_remote_pass"] = "*****"
    logger.debug("startup parameters: %s", a_copy)
    if unknown:
        logger.warning("invalid parameter given %s", unknown)

    EngineProvider.init(args.engine_menu_sort)

    Rev2Info.set_dgtpi(args.dgtpi)
    try:
        board_type = dgt.util.EBoard[args.board_type.upper()]
    except KeyError:
        board_type = dgt.util.EBoard.DGT
    ModeInfo.set_eboard_type(board_type)

    # wire some dgt classes
    if board_type == dgt.util.EBoard.CHESSLINK:
        dgtboard: EBoard = ChessLinkBoard(main_loop)
    elif board_type == dgt.util.EBoard.CHESSNUT:
        dgtboard = ChessnutBoard(main_loop)
    elif board_type == dgt.util.EBoard.ICHESSONE:
        dgtboard = IChessOneBoard(main_loop)
    elif board_type == dgt.util.EBoard.CERTABO:
        dgtboard = CertaboBoard(main_loop)
    else:
        dgtboard = DgtBoard(
            args.dgt_port, args.disable_revelation_leds, args.dgtpi, args.disable_et, main_loop, args.slow_slide
        )
    dgttranslate = DgtTranslate(args.beep_config, args.beep_some_level, args.language, version)
    dgtmenu = DgtMenu(
        args.clockside,
        args.disable_confirm_message,
        args.ponder_interval,
        args.user_voice,
        args.computer_voice,
        args.speed_voice,
        args.enable_capital_letters,
        args.disable_short_notation,
        args.log_file,
        args.engine_remote_server,
        args.rolling_display_normal,
        max(0, min(20, args.volume_voice)),
        board_type,
        args.theme,
        round(float(args.rspeed), 2),
        args.rsound,
        args.rdisplay,
        args.rwindow,
        args.rolling_display_ponder,
        args.show_engine,
        PicoCoach.from_str(args.tutor_coach),
        args.tutor_watcher,
        args.tutor_explorer,
        PicoComment.from_str(args.tutor_comment),
        args.comment_factor,
        args.continue_game,
        args.alt_move,
        dgttranslate,
        brain_hint_display=args.tutor_brain_hint_display,
        brain_reveal_text=args.tutor_brain_reveal_text == "on",
        brain_hint_countdown=args.countdown_during_brain_display,
        audio_backend=args.audio_backend,
    )
    state = PicochessState(main_loop, dgttranslate, dgtmenu)
    state.flag_flexible_ponder = args.flexible_analysis
    state.flag_premove = args.premove
    state.set_location = args.location
    state.online_decrement = args.online_decrement
    await asyncio.to_thread(state.dgtmenu._set_volume_voice, state.dgtmenu.get_voice_volume())

    dgtdispatcher = Dispatcher(state.dgtmenu, main_loop)

    logger.debug("node %s", args.node)

    state.time_control, time_text = await state.transfer_time(args.time.split(), depth=args.depth, node=args.node)
    state.tc_init_last = state.time_control.get_parameters()
    time_text.beep = False

    # collect all tasks for later cancellation at exit, shutdown, or reboot
    # except the main_loop task which we terminate by sending a None into the async queue
    non_main_tasks: set[asyncio.Task] = set()
    shutdown_requested = asyncio.Event()
    shutdown_complete = asyncio.Event()

    # The class dgtDisplay fires Event (Observable) & DispatchDgt (Dispatcher)
    my_dgt_display = DgtDisplay(
        state.dgttranslate,
        state.dgtmenu,
        state.time_control,
        main_loop,
        board_connected=getattr(dgtboard, "is_connected", None),
    )
    non_main_tasks.add(asyncio.create_task(my_dgt_display.message_consumer()))
    my_dgt_display.start_once_per_second_timer()
    # @todo optimise to start this timer only when playmode is needing it?

    async def show_pairing_text(text: str) -> None:
        await DisplayMsg.show(Message.SHOW_TEXT(text_string=text))

    pairing_bridge = pairing_ipc.PairingBridge(main_loop, show_pairing_text)
    try:
        await pairing_bridge.start()
        pairing_ipc.set_bridge(pairing_bridge)
        state.pairing_bridge = pairing_bridge
        if pairing_bridge.server_task is not None:
            non_main_tasks.add(pairing_bridge.server_task)
    except Exception as exc:
        logger.warning("pairing IPC not available: %s", exc)

    ModeInfo.set_clock_side(args.clockside)

    sample_beeper = False
    sample_beeper_level = 0

    if args.beep_some_level > 1:
        # samples: confirmation and button press sounds
        sample_beeper_level = 2
    elif args.beep_some_level == 1:
        # samples: only confirmation sounds
        sample_beeper_level = 1
    else:
        sample_beeper_level = 0

    if args.beep_config == "sample":
        # sample sounds according to beeper_level
        sample_beeper = True
    else:
        # samples: no sounds
        sample_beeper = False

    shared: dict = {
        "web_speech_local": args.web_speech_local,
        "web_speech_remote": args.web_speech_remote,
        "web_audio_backend_remote": bool(args.web_audio_backend_remote),
        "system_info": {
            "web_audio_backend_remote": bool(args.web_audio_backend_remote),
            "brain_reveal_min_secs": args.tutor_brain_reveal_display,
        },
    }

    def _emit_web_audio(audio_data: dict):
        EventHandler.write_to_clients({"event": "WebAudio", "audio": audio_data})

    def _should_emit_web_audio() -> bool:
        return bool(shared.get("web_audio_backend_remote", False)) and EventHandler.has_remote_clients()

    def _voice_volume_factor() -> int:
        return state.dgtmenu.get_voice_volume()

    pico_talker = PicoTalkerDisplay(
        args.user_voice,
        args.computer_voice,
        args.speed_voice,
        args.audio_backend,
        _voice_volume_factor,
        bool(args.web_server_port),
        _emit_web_audio,
        _should_emit_web_audio,
        args.enable_setpieces_voice,
        args.comment_factor,
        sample_beeper,
        sample_beeper_level,
        board_type,
        main_loop,
    )

    non_main_tasks.add(asyncio.create_task(pico_talker.message_consumer()))

    # Launch web server
    if args.web_server_port:
        my_web_server = WebServer()
        shared["dgtmenu"] = state.dgtmenu
        shared["tutor_watch_active"] = bool(
            state.dgtmenu.get_picowatcher() or state.dgtmenu.get_picocoach() != PicoCoach.COACH_OFF
        )
        shared["tutor_watch_watcher"] = bool(state.dgtmenu.get_picowatcher())
        shared["tutor_watch_coach"] = bool(state.dgtmenu.get_picocoach() != PicoCoach.COACH_OFF)
        if state.dgtmenu.get_picocoach() == PicoCoach.COACH_BRAIN:
            shared["tutor_coach"] = "brain"
        elif state.dgtmenu.get_picocoach() == PicoCoach.COACH_HAND:
            shared["tutor_coach"] = "hand"
        elif state.dgtmenu.get_picocoach() == PicoCoach.COACH_LIFT:
            shared["tutor_coach"] = "lift"
        elif state.dgtmenu.get_picocoach() == PicoCoach.COACH_ON:
            shared["tutor_coach"] = "on"
        else:
            shared["tutor_coach"] = "off"
        shared["tutor_watch_coach_pref"] = (
            state.dgtmenu.get_picocoach()
            if state.dgtmenu.get_picocoach() != PicoCoach.COACH_OFF
            else PicoCoach.COACH_ON
        )
        shared["tutor_explorer"] = bool(state.dgtmenu.get_picoexplorer())
        if state.dgtmenu.get_picocomment() == PicoComment.COM_ON_ALL:
            shared["tutor_comment"] = "all"
        elif state.dgtmenu.get_picocomment() == PicoComment.COM_ON_ENG:
            shared["tutor_comment"] = "engine"
        else:
            shared["tutor_comment"] = "off"
        shared["tutor_prob"] = int(state.dgtmenu.get_comment_factor())
        # moved starting WebDisplayt and WebVr here so that they are in same main loop
        logger.info("initializing message queues")
        my_web_display = WebDisplay(shared, main_loop)
        non_main_tasks.add(asyncio.create_task(my_web_display.message_consumer()))
        my_web_vr = WebVr(shared, dgtboard, main_loop)
        await my_web_vr.initialize()
        non_main_tasks.add(asyncio.create_task(my_web_vr.dgt_consumer()))
        logger.info("message queues ready - starting web server")
        dgtdispatcher.register("web")
        theme_resolver = ThemeResolver(state.set_location)
        if theme_resolver.needs_location_lookup(args.theme):
            theme: str = await asyncio.to_thread(theme_resolver.resolve, args.theme)
        else:
            theme = theme_resolver.resolve(args.theme)
        shared["theme"] = args.theme
        shared["pieces"] = args.pieces
        shared["web-board-theme"] = args.web_board_theme
        shared["dgttranslate"] = state.dgttranslate
        web_app = my_web_server.make_app(
            theme, args.pieces, args.web_board_theme, shared, theme_resolver=theme_resolver
        )
        try:
            active_web_server_port = _listen_web_app(web_app, args.web_server_port)
        except WebServerListenError as exc:
            if exc.reason == "permission":
                logger.error("Could not start web server - port %d not allowed by operating system", exc.port)
                logger.error("try: %s", WEB_SERVER_SETCAP_HINT)
            else:
                logger.error("Could not start web server - port %d not available", exc.port)
                logger.error("is another Picochess, or other web application already running?")
            sys.exit(1)  # fatal, cannot continue without web server
        args.web_server_port = active_web_server_port
        shared["system_info"]["web_server_port"] = active_web_server_port

    if board_type == dgt.util.EBoard.NOEBOARD:
        logger.debug("starting PicoChess in no eboard mode")
    else:
        # Connect to DGT board
        logger.debug("starting PicoChess in board mode")
        if args.dgtpi:
            my_dgtpi = DgtPi(dgtboard, main_loop)
            dgtdispatcher.register("i2c")
            non_main_tasks.add(asyncio.create_task(my_dgtpi.dgt_consumer()))
            non_main_tasks.add(asyncio.create_task(my_dgtpi.process_incoming_clock_forever()))
        else:
            logger.debug("(ser) starting the board connection")
            dgtboard.run()  # a clock can only be online together with the board, so we must start it infront
        my_dgthw = DgtHw(dgtboard, main_loop)
        dgtdispatcher.register("ser")
        non_main_tasks.add(asyncio.create_task(my_dgthw.dgt_consumer()))

    # The class Dispatcher sends DgtApi messages at the correct (delayed) time out
    non_main_tasks.add(asyncio.create_task(dgtdispatcher.dispatch_consumer()))

    # Save to PGN
    emailer = Emailer(email=args.email, mailgun_key=args.mailgun_key)
    emailer.set_smtp(
        sserver=args.smtp_server,
        suser=args.smtp_user,
        spass=args.smtp_pass,
        sencryption=args.smtp_encryption,
        sstarttls=args.smtp_starttls,
        sport=args.smtp_port,
        sfrom=args.smtp_from,
    )

    my_pgn_display = PgnDisplay("games" + os.sep + args.pgn_file, emailer, shared, main_loop)
    non_main_tasks.add(asyncio.create_task(my_pgn_display.message_consumer()))

    # Update
    if args.enable_update:
        # picov3: await update_picochess(args.dgtpi, args.enable_update_reboot, state.dgttranslate)
        update_pico_v4()  # next boot will trigger picochess-update.service

    #################################################

    my_main = MainLoop(
        own_user,
        opp_user,
        game_time,
        fischer_inc,
        login,
        state,
        my_pgn_display,
        pico_talker,
        dgtdispatcher,
        dgtboard,
        board_type,
        main_loop,
        args,
        shared,
        non_main_tasks,
        shutdown_requested,
        shutdown_complete,
    )

    await my_main.initialise(time_text)
    main_task = main_loop.create_task(my_main.event_consumer())  # start main message loop
    board_wait_task = main_loop.create_task(my_main.wait_for_board_connection())
    non_main_tasks.add(board_wait_task)  # ensure it gets cancelled on shutdown if still waiting
    all_tasks = set(non_main_tasks)
    all_tasks.add(main_task)
    await gather_main_tasks(all_tasks, shutdown_requested)
    await wait_for_shutdown_cleanup(shutdown_requested, shutdown_complete)
    logger.debug("all tasks done, exiting main loop and picochess program")
    # await asyncio.Event().wait()  # wait forever


if __name__ == "__main__":
    asyncio.run(main())
