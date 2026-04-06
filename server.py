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

import base64
import datetime
import time
import json
import logging
import os
import re
import ipaddress
import subprocess
from collections import OrderedDict
from typing import Set
import asyncio
import platform

import chess  # type: ignore
import chess.pgn as pgn  # type: ignore
import chess.polyglot  # type: ignore
import chess.variant  # type: ignore

import pam
import tornado.web  # type: ignore
import tornado.wsgi  # type: ignore
from tornado.websocket import WebSocketHandler  # type: ignore

from utilities import (
    Observable,
    DisplayMsg,
    hms_time,
    AsyncRepeatingTimer,
    keep_essential_headers,
    ensure_important_headers,
    get_opening_books,
    write_picochess_ini,
)
from upload_pgn import UploadHandler
from web.picoweb import picoweb as pw

from dgt.api import Event, Message
from dgt.util import PlayMode, Mode, ClockSide, GameResult, PicoCoach, PicoComment, TimeMode, Beep, flip_board_fen, Voice
from timecontrol import TimeControl
from dgt.iface import DgtIface
from eboard.eboard import EBoard
from pgn import ModeInfo

# This needs to be reworked to be session based (probably by token)
# Otherwise multiple clients behind a NAT can all play as the 'player'
client_ips = []


logger = logging.getLogger(__name__)
OBOOKSRV_BOOK_FILE = "obooksrv"
OBOOKSRV_BOOK_LABEL = "ObookSrv"
OBOOKSRV_DATA_FILE = os.path.join(os.path.dirname(__file__), "obooksrv", "opening.data")
INI_LINE_RE = re.compile(r'^\s*(#\s*)?([A-Za-z0-9_-]+)\s*=\s*(.*)$')
INI_COMMENT_RE = re.compile(r'^\s*#\s*(.+)$')


def _get_ini_path() -> str:
    return os.path.join(os.path.dirname(__file__), "picochess.ini")


def _get_remote_ip(request) -> str:
    return request.remote_ip or ""


def _is_local_request(request) -> bool:
    return _get_remote_ip(request) in ("127.0.0.1", "::1")

def _is_private_request(request) -> bool:
    try:
        addr = ipaddress.ip_address(_get_remote_ip(request))
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local


def _require_auth_if_remote(handler, realm: str) -> bool:
    if _is_local_request(handler.request):
        return True
    auth_header = handler.request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Basic "):
        handler.set_status(401)
        handler.set_header("WWW-Authenticate", f'Basic realm="{realm}"')
        handler.finish("Authentication required")
        return False
    try:
        auth_decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        username, password = auth_decoded.split(":", 1)
    except Exception:
        handler.set_status(401)
        handler.set_header("WWW-Authenticate", f'Basic realm="{realm}"')
        handler.finish("Authentication required")
        return False
    if not pam.pam().authenticate(username, password):
        handler.set_status(401)
        handler.set_header("WWW-Authenticate", f'Basic realm="{realm}"')
        handler.finish("Authentication required")
        return False
    handler.current_user = username
    return True


def _parse_ini_entries(lines):
    entries = {}
    pending_help = []
    for idx, line in enumerate(lines):
        if not line.strip():
            pending_help = []
            continue
        match = INI_LINE_RE.match(line)
        if not match:
            comment_match = INI_COMMENT_RE.match(line)
            if comment_match:
                pending_help.append(comment_match.group(1).strip())
            else:
                pending_help = []
            continue
        enabled = match.group(1) is None
        key = match.group(2)
        value = match.group(3).strip()
        help_text = " ".join(pending_help).strip() if pending_help else ""
        data = {
            "key": key,
            "value": value,
            "enabled": enabled,
            "line_index": idx,
            "help": help_text,
        }
        if key not in entries:
            entries[key] = data
        else:
            if enabled or not entries[key]["enabled"]:
                entries[key] = data
        pending_help = []
    return entries


def _load_ini_entries():
    ini_path = _get_ini_path()
    with open(ini_path, "r", encoding="utf-8") as ini_file:
        lines = ini_file.readlines()
    entries_map = _parse_ini_entries(lines)
    entries = sorted(entries_map.values(), key=lambda entry: entry["line_index"])
    return ini_path, lines, entries, entries_map


def _allow_onboard_without_auth() -> bool:
    try:
        _, _, _, entries_map = _load_ini_entries()
    except OSError:
        return True
    entry = entries_map.get("allow-onboard-without-auth")
    if not entry or not entry.get("enabled", True):
        return True
    value = str(entry.get("value", "")).strip().lower()
    return value in ("1", "true", "yes", "on")


class ServerRequestHandler(tornado.web.RequestHandler):
    def initialize(self, shared=None):
        self.shared = shared

    def data_received(self, chunk):
        pass


class ChannelHandler(ServerRequestHandler):

    async def process_board_scan(self):
        """Simulate exact DGT menu steps for position setup"""
        try:
            # Get parameters from web sliders
            side_to_play = self.get_argument("sideToPlay", "true").lower() == "true"
            board_reversed = self.get_argument("boardSide", "false").lower() == "true"
            uci960_enabled = self.get_argument("uci960", "false").lower() == "true"

            # Get castling rights from web sliders
            white_castle_king = self.get_argument("whiteCastleKing", "true").lower() == "true"
            white_castle_queen = self.get_argument("whiteCastleQueen", "true").lower() == "true"
            black_castle_king = self.get_argument("blackCastleKing", "true").lower() == "true"
            black_castle_queen = self.get_argument("blackCastleQueen", "true").lower() == "true"

            # Build castling rights string for FEN
            castling = ""
            if white_castle_king:
                castling += "K"
            if white_castle_queen:
                castling += "Q"
            if black_castle_king:
                castling += "k"
            if black_castle_queen:
                castling += "q"
            if not castling:
                castling = "-"

            fen = self.shared["dgt_fen"]

            if not fen or fen == "8/8/8/8/8/8/8/8":
                logger.error("No valid board position scanned")
                return None

            # Check if board needs flipping.
            if board_reversed:
                fen = flip_board_fen(fen)

            # Build complete FEN with position settings.
            fen += " {0} {1} - 0 1".format("w" if side_to_play else "b", castling)

            # Validate FEN using python-chess.
            try:
                bit_board = chess.Board(fen, chess960=uci960_enabled)
                is_valid = bit_board.is_valid()

                if not is_valid:
                    logger.warning(f"FEN validation failed: {fen}")
                    logger.warning(f"Status: {bit_board.status()}")
                    logger.warning("Accepting position anyway for setup")

                # Fire SETUP_POSITION even if invalid
                await Observable.fire(Event.SETUP_POSITION(fen=fen, uci960=uci960_enabled))
                return fen

            except Exception as fen_error:
                logger.error(f"FEN validation error: {fen_error}")
                return None

        except Exception as e:
            logger.error(f"Error in process_board_scan: {e}")
            return None

    async def process_console_command(self, raw):
        cmd = raw.lower()

        try:
            # Here starts the simulation of a dgt-board!
            # Let the user send events like the board would do
            if cmd.startswith("fen:"):
                fen = raw.split(":")[1].strip()
                # dgt board only sends the basic fen => be sure it's same no matter what fen the user entered
                fen = fen.split(" ")[0]
                bit_board = chess.Board()  # valid the fen
                bit_board.set_board_fen(fen)
                await Observable.fire(Event.KEYBOARD_FEN(fen=fen))
            # end simulation code
            elif cmd.startswith("go"):
                if "last_dgt_move_msg" in self.shared:
                    fen = self.shared["last_dgt_move_msg"]["fen"].split(" ")[0]
                    await Observable.fire(Event.KEYBOARD_FEN(fen=fen))
            else:
                # Event.KEYBOARD_MOVE tranfers "move" to "fen" and then continues with "Message.DGT_FEN"
                move = chess.Move.from_uci(cmd)
                await Observable.fire(Event.KEYBOARD_MOVE(move=move))
        except (ValueError, IndexError):
            logger.warning("Invalid user input [%s]", raw)

    async def post(self):
        action = self.get_argument("action")
        logger.info(f"POST recibido con action: {action}")

        if action == "broadcast":
            fen = self.get_argument("fen")
            pgn_str = self.get_argument("pgn")
            result = {
                "event": "Broadcast",
                "msg": "Position from Spectators!",
                "pgn": pgn_str,
                "fen": fen,
            }
            EventHandler.write_to_clients(result)
        elif action == "move":
            move = chess.Move.from_uci(
                self.get_argument("source") + self.get_argument("target") + self.get_argument("promotion")
            )
            await Observable.fire(Event.REMOTE_MOVE(move=move, fen=self.get_argument("fen")))
        elif action == "promotion":
            move = chess.Move.from_uci(
                self.get_argument("source") + self.get_argument("target") + self.get_argument("promotion")
            )
            await Observable.fire(Event.PROMOTION(move=move, fen=self.get_argument("fen")))
        elif action == "clockbutton":
            await Observable.fire(Event.KEYBOARD_BUTTON(button=self.get_argument("button"), dev="web"))
        elif action == "room":
            inside = self.get_argument("room") == "inside"
            await Observable.fire(Event.REMOTE_ROOM(inside=inside))
        elif action == "command":
            await self.process_console_command(self.get_argument("command"))
        elif action == "new_game":
            try:
                pos960 = int(self.get_argument("pos960", "518"))
            except (TypeError, ValueError):
                pos960 = 518
            await Observable.fire(Event.NEW_GAME(pos960=pos960))
        elif action == "tutor_watch":
            active = self.get_argument("active", "false").lower() == "true"
            await Observable.fire(Event.PICOWATCHER(picowatcher=active))
            if active:
                coach_pref = self.shared.get("tutor_watch_coach_pref", PicoCoach.COACH_ON)
                if coach_pref not in (PicoCoach.COACH_ON, PicoCoach.COACH_LIFT):
                    coach_pref = PicoCoach.COACH_ON
                await Observable.fire(Event.PICOCOACH(picocoach=coach_pref))
            else:
                await Observable.fire(Event.PICOCOACH(picocoach=0))
        elif action == "move_now":
            await Observable.fire(Event.PAUSE_RESUME())
        elif action == "resign_game":
            play_mode = (self.shared.get("game_info") or {}).get("play_mode")
            if play_mode == PlayMode.USER_BLACK:
                result = GameResult.WIN_WHITE
            else:
                result = GameResult.WIN_BLACK
            await Observable.fire(Event.DRAWRESIGN(result=result))
        elif action == "pgn_replay":
            await Observable.fire(
                Event.SET_INTERACTION_MODE(mode=Mode.PGNREPLAY, mode_text="PGN Replay", show_ok=False)
            )
        elif action == "save_game":
            try:
                slot = int(self.get_argument("slot", "1"))
                if slot not in (1, 2, 3):
                    slot = 1
            except (ValueError, TypeError):
                slot = 1
            await Observable.fire(Event.SAVE_GAME(pgn_filename=f"picochess_game_{slot}.pgn"))
        elif action == "load_game":
            try:
                slot = int(self.get_argument("slot", "1"))
                if slot not in (0, 1, 2, 3):
                    slot = 1
            except (ValueError, TypeError):
                slot = 1
            pgn_fn = "last_game.pgn" if slot == 0 else f"picochess_game_{slot}.pgn"
            await Observable.fire(Event.READ_GAME(pgn_filename=pgn_fn))
        elif action == "game_end":
            _result_map = {
                "white": GameResult.WIN_WHITE,
                "black": GameResult.WIN_BLACK,
                "draw":  GameResult.DRAW,
            }
            result = _result_map.get(self.get_argument("result", "").strip())
            if result is not None:
                await Observable.fire(Event.DRAWRESIGN(result=result))
        elif action == "new_engine":
            from uci.engine_provider import EngineProvider
            file  = self.get_argument("file")
            level = self.get_argument("level", "")
            eng   = EngineProvider.resolve_engine(file)
            if eng:
                options = eng.get("level_dict", {}).get(level, {}) if level else {}
                # Persist the selected level name now so _build_game_header uses
                # the correct Elo (e.g. "Elo@1600" → BlackElo 1600, not the engine
                # max).  The DGT-menu path fires Event.LEVEL first which does the
                # same; the web overlay fires only Event.NEW_ENGINE so we set it here.
                if level:
                    if "game_info" not in self.shared:
                        self.shared["game_info"] = {}
                    self.shared["game_info"]["level_name"] = level
                await Observable.fire(Event.NEW_ENGINE(
                    eng=eng,
                    eng_text=eng.get("text", ""),
                    options=options,
                    show_ok=True,
                ))
        elif action == "new_book":
            try:
                index = int(self.get_argument("index", "0"))
            except (TypeError, ValueError):
                index = 0
            library = get_opening_books()
            if index == 0:
                # Index 0 = online book server (obooksrv)
                book = {"file": OBOOKSRV_BOOK_FILE, "text": None}
                book_text = None
            elif 1 <= index <= len(library):
                book = library[index - 1]
                book_text = book.get("text")
            else:
                book = library[0] if library else {"file": "", "text": None}
                book_text = book.get("text")
            # Remember which book file was selected so get_book_list returns the right current_index
            self.shared["web_book_file"] = book.get("file", OBOOKSRV_BOOK_FILE)
            await Observable.fire(Event.SET_OPENING_BOOK(book=book, book_text=book_text, show_ok=True))
        elif action == "scan_board":
            result_fen = await self.process_board_scan()
            self.write({"success": result_fen is not None, "fen": result_fen})
            self.set_header("Content-Type", "application/json")
        elif action == "new_time":
            try:
                mode_id = int(self.get_argument("time_mode", "0"))
            except (TypeError, ValueError):
                mode_id = 0
            try:
                time_val = int(self.get_argument("time", "0") or "0")
            except (TypeError, ValueError):
                time_val = 0
            try:
                fischer_val = int(self.get_argument("fischer", "0") or "0")
            except (TypeError, ValueError):
                fischer_val = 0
            tournament_str = self.get_argument("tournament", "") or ""

            _mode_map = {
                0: TimeMode.FIXED,
                1: TimeMode.BLITZ,
                2: TimeMode.FISCHER,
                3: TimeMode.TOURN,
                4: TimeMode.DEPTH,
                5: TimeMode.NODE,
            }
            tc_mode = _mode_map.get(mode_id, TimeMode.FIXED)

            if mode_id == 3 and tournament_str:  # tournament: "moves_to_go blitz blitz2 fischer"
                parts = tournament_str.split()
                _mtg   = int(parts[0]) if len(parts) > 0 else 0
                _blitz = int(parts[1]) if len(parts) > 1 else 0
                _blitz2 = int(parts[2]) if len(parts) > 2 else 0
                _fisc  = int(parts[3]) if len(parts) > 3 else 0
                tc_init = {
                    "mode": TimeMode.TOURN, "fixed": 0, "blitz": _blitz,
                    "fischer": _fisc, "moves_to_go": _mtg, "blitz2": _blitz2,
                    "depth": 0, "node": 0, "internal_time": None,
                }
            elif mode_id == 4:  # depth
                tc_init = {
                    "mode": TimeMode.FIXED, "fixed": 0, "blitz": 0,
                    "fischer": 0, "moves_to_go": 0, "blitz2": 0,
                    "depth": time_val, "node": 0, "internal_time": None,
                }
            elif mode_id == 5:  # nodes
                tc_init = {
                    "mode": TimeMode.FIXED, "fixed": 0, "blitz": 0,
                    "fischer": 0, "moves_to_go": 0, "blitz2": 0,
                    "depth": 0, "node": time_val, "internal_time": None,
                }
            elif mode_id == 0:  # fixed seconds/move
                tc_init = {
                    "mode": TimeMode.FIXED, "fixed": time_val, "blitz": 0,
                    "fischer": 0, "moves_to_go": 0, "blitz2": 0,
                    "depth": 0, "node": 0, "internal_time": None,
                }
            elif mode_id == 1:  # blitz
                tc_init = {
                    "mode": TimeMode.BLITZ, "fixed": 0, "blitz": time_val,
                    "fischer": 0, "moves_to_go": 0, "blitz2": 0,
                    "depth": 0, "node": 0, "internal_time": None,
                }
            else:  # fischer (mode_id == 2)
                tc_init = {
                    "mode": TimeMode.FISCHER, "fixed": 0, "blitz": time_val,
                    "fischer": fischer_val, "moves_to_go": 0, "blitz2": 0,
                    "depth": 0, "node": 0, "internal_time": None,
                }

            tc = TimeControl(**{k: v for k, v in tc_init.items() if k != "internal_time"})
            time_text = tc.get_list_text()
            logger.info("web new_time: mode_id=%d tc_init=%s time_text=%r", mode_id, tc_init, time_text)
            await Observable.fire(Event.SET_TIME_CONTROL(tc_init=tc_init, time_text=time_text, show_ok=True))
        elif action == "picotutor":
            tutor = self.get_argument("tutor", "")
            val   = self.get_argument("val", "0")
            if tutor == "watcher":
                active = val not in ("0", "false", "off")
                await Observable.fire(Event.PICOWATCHER(picowatcher=active))
                if active:
                    coach_pref = self.shared.get("tutor_watch_coach_pref", PicoCoach.COACH_ON)
                    if coach_pref not in (PicoCoach.COACH_ON, PicoCoach.COACH_LIFT):
                        coach_pref = PicoCoach.COACH_ON
                    await Observable.fire(Event.PICOCOACH(picocoach=coach_pref))
                else:
                    await Observable.fire(Event.PICOCOACH(picocoach=0))
            elif tutor == "coach":
                _coach_map = {
                    "on":   PicoCoach.COACH_ON,
                    "lift": PicoCoach.COACH_LIFT,
                    "off":  PicoCoach.COACH_OFF,
                }
                coach_val = _coach_map.get(val.lower(), PicoCoach.COACH_OFF)
                await Observable.fire(Event.PICOCOACH(picocoach=coach_val))
            elif tutor == "explorer":
                active = val not in ("0", "false", "off")
                await Observable.fire(Event.PICOEXPLORER(picoexplorer=active))
            elif tutor == "comment":
                _comment_map = {
                    "engine": PicoComment.COM_ON_ENG,
                    "all":    PicoComment.COM_ON_ALL,
                    "off":    PicoComment.COM_OFF,
                }
                comment_val = _comment_map.get(val.lower(), PicoComment.COM_OFF)
                await Observable.fire(Event.PICOCOMMENT(picocomment=comment_val))
            elif tutor == "prob":
                try:
                    self.shared["tutor_prob"] = max(0, min(100, int(val)))
                except (TypeError, ValueError):
                    pass
            else:
                logger.warning("web picotutor: unknown tutor=%r", tutor)
        elif action == "set_mode":
            _mode_map = {
                "normal":    (Mode.NORMAL,    "Normal"),
                "training":  (Mode.TRAINING,  "Training"),
                "brain":     (Mode.BRAIN,     "Brain"),
                "analysis":  (Mode.ANALYSIS,  "Analysis"),
                "kibitz":    (Mode.KIBITZ,    "Kibitz"),
                "observe":   (Mode.OBSERVE,   "Observe"),
                "remote":    (Mode.REMOTE,    "Remote"),
                "ponder":    (Mode.PONDER,    "Ponder"),
                "pgnreplay": (Mode.PGNREPLAY, "PGN Replay"),
            }
            mode_name = self.get_argument("mode", "normal").lower()
            mode_val, mode_text = _mode_map.get(mode_name, (Mode.NORMAL, "Normal"))
            await Observable.fire(Event.SET_INTERACTION_MODE(mode=mode_val, mode_text=mode_text, show_ok=True))
        elif action == "lang":
            _valid_langs = {"en", "de", "nl", "fr", "es", "it"}
            lang_code = self.get_argument("val", "en").lower()
            if lang_code not in _valid_langs:
                logger.warning("web lang: unknown language code %r", lang_code)
            else:
                dgttranslate = self.shared.get("dgttranslate")
                if dgttranslate:
                    dgttranslate.set_language(lang_code)
                    write_picochess_ini("language", lang_code)
                    logger.info("web lang: language set to %r", lang_code)
                else:
                    logger.warning("web lang: dgttranslate not available in shared")
        elif action == "beep":
            _beep_map = {
                "off":    Beep.OFF,
                "some":   Beep.SOME,
                "on":     Beep.ON,
                "sample": Beep.SAMPLE,
            }
            beep_val_str = self.get_argument("val", "some").lower()
            beep_val = _beep_map.get(beep_val_str)
            if beep_val is None:
                logger.warning("web beep: unknown beep value %r", beep_val_str)
            else:
                dgttranslate = self.shared.get("dgttranslate")
                if dgttranslate:
                    dgttranslate.set_beep(beep_val)
                    write_picochess_ini("beep-config", dgttranslate.beep_to_config(beep_val))
                    logger.info("web beep: beep set to %r", beep_val_str)
                else:
                    logger.warning("web beep: dgttranslate not available in shared")
        elif action == "set_voice":
            speaker = self.get_argument("speaker", "").strip()
            voice_type = self.get_argument("type", "comp").strip()  # "user" or "comp"
            dgttranslate = self.shared.get("dgttranslate")
            lang = getattr(dgttranslate, "language", "en") if dgttranslate else "en"
            if speaker:
                voice_str = lang + ":" + speaker
                ini_key = "user-voice" if voice_type == "user" else "comp-voice"
                write_picochess_ini(ini_key, voice_str)
                await Observable.fire(
                    Event.SET_VOICE(type=voice_type, lang=lang, speaker=speaker, speed=1)
                )
                logger.info("web set_voice: type=%r lang=%r speaker=%r", voice_type, lang, speaker)
        elif action == "set_player":
            name = self.get_argument("name", "").strip()
            elo  = self.get_argument("elo",  "").strip()
            if name:
                if "system_info" not in self.shared:
                    self.shared["system_info"] = {}
                self.shared["system_info"]["user_name"] = name
                write_picochess_ini("pgn-user", name)
                logger.info("web set_player: name=%r", name)
            if elo:
                try:
                    elo_int = int(elo)
                    if not (0 <= elo_int <= 3000):
                        elo_int = 1500
                except (TypeError, ValueError):
                    elo_int = 1500
                if "system_info" not in self.shared:
                    self.shared["system_info"] = {}
                self.shared["system_info"]["user_elo"] = str(elo_int)
                write_picochess_ini("pgn-elo", str(elo_int))
                logger.info("web set_player: elo=%r", elo_int)
        elif action == "take_back":
            await Observable.fire(Event.TAKE_BACK(take_back="TAKEBACK"))
        elif action == "altmove":
            await Observable.fire(Event.ALTERNATIVE_MOVE())
        elif action == "contlast":
            await Observable.fire(Event.CONTLAST(contlast=True))
        elif action == "sys_shutdown":
            await Observable.fire(Event.SHUTDOWN(dev="web"))
        elif action == "sys_reboot":
            await Observable.fire(Event.REBOOT(dev="web"))
        elif action == "sys_exit":
            await Observable.fire(Event.EXIT(dev="web"))
        elif action == "sys_update":
            await Observable.fire(Event.UPDATE_PICO(tag=""))
        elif action == "sys_update_engines":
            await Observable.fire(Event.UPDATE_ENGINES())
            await asyncio.sleep(1)
            await Observable.fire(Event.REBOOT(dev="web"))
        elif action == "display":
            side = self.get_argument("side", "")
            notation = self.get_argument("notation", "")
            ponder = self.get_argument("ponder", "")
            confirm = self.get_argument("confirm", "")
            capital = self.get_argument("capital", "")
            enginename = self.get_argument("enginename", "")
            if side in ("left", "right"):
                ModeInfo.set_clock_side(side)
                write_picochess_ini("clockside", side)
            if notation == "short":
                write_picochess_ini("disable-short-notation", False)
            elif notation == "long":
                write_picochess_ini("disable-short-notation", True)
            if ponder == "on":
                write_picochess_ini("ponder-interval", 1)
            elif ponder == "off":
                write_picochess_ini("ponder-interval", 0)
            if confirm == "on":
                # "disable-confirm-message=False" means confirm messages ARE shown
                write_picochess_ini("disable-confirm-message", False)
                logger.info("web display: confirm messages enabled")
            elif confirm == "off":
                write_picochess_ini("disable-confirm-message", True)
                logger.info("web display: confirm messages disabled")
            if capital == "on":
                write_picochess_ini("enable-capital-letters", True)
                await Observable.fire(Event.PICOCOMMENT(picocomment="ok"))
                logger.info("web display: capital letters enabled")
            elif capital == "off":
                write_picochess_ini("enable-capital-letters", False)
                await Observable.fire(Event.PICOCOMMENT(picocomment="ok"))
                logger.info("web display: capital letters disabled")
            if enginename == "on":
                write_picochess_ini("show-engine", True)
                await Observable.fire(Event.SHOW_ENGINENAME(show_enginename=True))
                logger.info("web display: engine name shown")
            elif enginename == "off":
                write_picochess_ini("show-engine", False)
                await Observable.fire(Event.SHOW_ENGINENAME(show_enginename=False))
                logger.info("web display: engine name hidden")
        elif action == "eboard":
            eboard_type = self.get_argument("type", "").strip()
            _valid_eboards = {"dgt", "certabo", "chesslink", "chessnut", "ichessone", "none"}
            if eboard_type in _valid_eboards:
                # "none" means no board; write "noeboard" so EBoard['NOEBOARD'] resolves correctly
                # on next startup (EBoard has no 'NONE' member).
                ini_value = "noeboard" if eboard_type == "none" else eboard_type
                write_picochess_ini("board-type", ini_value)
                # Only reboot when the board type actually changes (mirrors DGT menu behaviour).
                current = ModeInfo.get_eboard_type()
                if current is None or current.name.lower() != ini_value:
                    await Observable.fire(Event.REBOOT(dev="web"))
        elif action == "wifi_hotspot":
            try:
                subprocess.Popen(
                    ["sudo", "-n", "/opt/picochess/wifi-hotspot-connect"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as exc:
                logger.warning("wifi-hotspot-connect failed: %s", exc)
        elif action == "bt_toggle":
            try:
                subprocess.Popen(
                    ["sudo", "-n", "/opt/picochess/pair-phone"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as exc:
                logger.warning("pair-phone failed: %s", exc)
        elif action == "bt_fix":
            try:
                subprocess.Popen(
                    ["sudo", "-n", "/opt/picochess/Fix_bluetooth.sh"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as exc:
                logger.warning("Fix_bluetooth.sh failed: %s", exc)
        elif action == "voice_speed":
            try:
                speed_factor = max(1, min(9, int(self.get_argument("val", "2"))))
            except (TypeError, ValueError):
                speed_factor = 2
            dgttranslate = self.shared.get("dgttranslate")
            lang = getattr(dgttranslate, "language", "en") if dgttranslate else "en"
            write_picochess_ini("speed-voice", speed_factor)
            await Observable.fire(
                Event.SET_VOICE(type=Voice.SPEED, lang=lang, speaker="mute", speed=speed_factor)
            )
            logger.info("web voice_speed: factor=%d", speed_factor)
        elif action == "voice_volume":
            try:
                vol_factor = max(1, min(20, int(self.get_argument("val", "10"))))
            except (TypeError, ValueError):
                vol_factor = 10
            write_picochess_ini("volume-voice", str(vol_factor))
            # Set system volume: each factor unit = 5 % (same as _set_volume_voice in menu.py)
            pct = str(vol_factor * 5)
            for channel in ("Headphone", "Master", "HDMI", "PCM"):
                try:
                    subprocess.run(
                        ["amixer", "-M", "sset", channel, f"{pct}%"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass
            dgttranslate = self.shared.get("dgttranslate")
            lang = getattr(dgttranslate, "language", "en") if dgttranslate else "en"
            await Observable.fire(
                Event.SET_VOICE(type=Voice.VOLUME, lang=lang, speaker="mute", speed=1)
            )
            logger.info("web voice_volume: factor=%d (%s%%)", vol_factor, pct)
        elif action == "rspeed":
            val_str = self.get_argument("val", "100").strip()
            try:
                rspeed_factor = 0.0 if val_str == "max" else round(float(val_str) / 100, 2)
            except (TypeError, ValueError):
                rspeed_factor = 1.0
            write_picochess_ini("rspeed", rspeed_factor)
            await Observable.fire(Event.RSPEED(rspeed=rspeed_factor))
            logger.info("web rspeed: factor=%s (%s%%)", rspeed_factor, val_str)


class EventHandler(WebSocketHandler):
    """Started by /event HTTP call - Clients are WebDisplay and WebVr classes"""

    clients: Set[WebSocketHandler] = set()

    def initialize(self, shared=None):
        self.shared = shared

    def on_message(self, message):
        logger.debug("WebSocket message " + message)

    def data_received(self, chunk):
        pass

    def real_ip(self):
        return self.request.remote_ip or ""

    @classmethod
    def has_remote_clients(cls) -> bool:
        for client in cls.clients:
            if (client.request.remote_ip or "") not in ("127.0.0.1", "::1"):
                return True
        return False

    def open(self, *args: str, **kwargs: str):
        EventHandler.clients.add(self)
        client_ips.append(self.real_ip())
        # Sync newly connected client with last known board state, if available.
        if self.shared and "last_dgt_move_msg" in self.shared:
            try:
                self.write_message(self.shared["last_dgt_move_msg"])
            except Exception as exc:  # pragma: no cover - websocket errors
                logger.warning("failed to sync board state to client: %s", exc)
        # If the engine has suggested a move not yet confirmed on the board, send the
        # arrow so this new client shows the same hint as already-connected clients.
        if self.shared and "pending_computer_move" in self.shared:
            pending = self.shared["pending_computer_move"]
            if "move" in pending:
                try:
                    self.write_message({"event": "Light", "move": pending["move"]})
                except Exception as exc:  # pragma: no cover - websocket errors
                    logger.warning("failed to sync pending engine move to client: %s", exc)
        for key in ("analysis_state_engine", "analysis_state_tutor", "analysis_state"):
            if self.shared and key in self.shared:
                try:
                    self.write_message({"event": "Analysis", "analysis": self.shared[key]})
                except Exception as exc:  # pragma: no cover - websocket errors
                    logger.warning("failed to sync analysis to client: %s", exc)
        # Push the current system_info so the overlay tile subtitles are correct
        # immediately, even if the HTTP get_system_info fetch hasn't completed.
        # Filter to only JSON-safe scalar values (plain str/int/float/bool/None).
        if self.shared and "system_info" in self.shared:
            try:
                _si = {k: v for k, v in self.shared["system_info"].items()
                       if isinstance(v, (str, int, float, bool, type(None)))}
                if _si:
                    self.write_message({"event": "SystemInfo", "msg": _si})
            except Exception as exc:  # pragma: no cover - websocket errors
                logger.warning("failed to sync system_info to client: %s", exc)

    def on_close(self):
        EventHandler.clients.remove(self)
        client_ips.remove(self.real_ip())

    @classmethod
    def write_to_clients(cls, msg):
        """This is the main event loop message producer for WebDisplay and WebVR"""
        for client in cls.clients:
            client.write_message(msg)


class DGTHandler(ServerRequestHandler):

    async def get(self, *args, **kwargs):
        action = self.get_argument("action")
        if action == "get_last_move":
            if "last_dgt_move_msg" in self.shared:
                result = dict(self.shared["last_dgt_move_msg"])
                picotutor = self.shared.get("picotutor")
                if picotutor:
                    try:
                        result["mistakes"] = picotutor.get_eval_mistakes()
                    except Exception as exc:  # pragma: no cover - defensive for UI
                        logger.debug("failed to collect tutor mistakes: %s", exc)
                self.write(result)


class InfoHandler(ServerRequestHandler):
    async def get(self, *args, **kwargs):
        action = self.get_argument("action")
        if action == "get_system_info":
            if "system_info" in self.shared:
                self.write(self.shared["system_info"])
        if action == "get_ip_info":
            if "ip_info" in self.shared:
                self.write(self.shared["ip_info"])
        if action == "get_headers":
            if "headers" in self.shared:
                self.write(dict(self.shared["headers"]))
        if action == "get_clock_text":
            if "clock_text" in self.shared:
                self.write(self.shared["clock_text"])
        if action == "get_engines":
            from uci.engine_provider import EngineProvider
            engines = []
            def _add(eng_list, category):
                for eng in eng_list:
                    engines.append({
                        "name":     eng.get("name", ""),
                        "file":     eng.get("file", ""),
                        "elo":      eng.get("elo",  ""),
                        "levels":   list(eng.get("level_dict", {}).keys()),
                        "category": category,
                    })
            _add(EngineProvider.modern_engines,   "modern")
            _add(EngineProvider.retro_engines,    "retro")
            _add(EngineProvider.favorite_engines, "favorites")
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"engines": engines}))
        if action == "get_voices":
            # Return available speakers for the current language.
            # Speakers are sub-directories of talker/voices/{lang}/.
            voices_base = os.path.join(os.path.dirname(__file__), "talker", "voices")
            dgttranslate = self.shared.get("dgttranslate")
            lang = getattr(dgttranslate, "language", "en") if dgttranslate else "en"
            lang_dir = os.path.join(voices_base, lang)
            speakers = []
            if os.path.isdir(lang_dir):
                for entry in sorted(os.listdir(lang_dir)):
                    if os.path.isdir(os.path.join(lang_dir, entry)) and not entry.startswith("."):
                        speakers.append(entry)
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"lang": lang, "speakers": speakers}))
        if action == "get_current_settings":
            # Return current picker values so the overlay can pre-mark selections.
            from configobj import ConfigObj as _ConfigObj
            settings = {}
            try:
                config = _ConfigObj("picochess.ini", default_encoding="utf8")
                dgttranslate = self.shared.get("dgttranslate")
                # Language (live from dgttranslate, fallback to ini)
                settings["language"] = (
                    getattr(dgttranslate, "language", None)
                    or str(config.get("language", "en")).lower()
                )
                # Beep (live from dgttranslate)
                beep = getattr(dgttranslate, "beep", None)
                _bmap = {Beep.OFF: "off", Beep.SOME: "some", Beep.ON: "on", Beep.SAMPLE: "sample"}
                settings["beep"] = _bmap.get(beep, "some") if beep is not None else "some"
                # Board type
                settings["board_type"] = str(config.get("board-type", "dgt")).lower()
                # Display settings
                settings["clockside"] = str(config.get("clockside", "left")).lower()
                dsn = config.get("disable-short-notation")
                settings["notation"] = "long" if dsn in (True, "True", "true") else "short"
                pi = config.get("ponder-interval", "1")
                settings["ponder"] = "off" if str(pi) == "0" else "on"
                dcm = config.get("disable-confirm-message")
                settings["confirm"] = "off" if dcm in (True, "True", "true") else "on"
                ecl = config.get("enable-capital-letters")
                settings["capital"] = "on" if ecl in (True, "True", "true") else "off"
                se = config.get("show-engine")
                settings["show_engine"] = "on" if se in (True, "True", "true") else "off"
                # Retro speed (stored as float 0.0–10.0; UI shows as % strings)
                try:
                    rspeed_f = float(config.get("rspeed", 1.0))
                    settings["rspeed"] = "max" if rspeed_f == 0.0 else str(int(round(rspeed_f * 100)))
                except (TypeError, ValueError):
                    settings["rspeed"] = "100"
                # Voice speed (1–9)
                settings["speed_voice"] = str(config.get("speed-voice", "2"))
                # Voice volume (1–20)
                settings["volume_voice"] = str(config.get("volume-voice", "10"))
                # Current voice speakers (stored as "lang:speaker")
                for key in ("comp-voice", "user-voice"):
                    raw = str(config.get(key, ""))
                    settings[key.replace("-", "_")] = raw.split(":")[-1] if ":" in raw else raw
            except Exception as exc:
                logger.warning("get_current_settings error: %s", exc)
            # Engine name and level come from shared (live state, not ini)
            si = self.shared.get("system_info", {})
            settings["engine_name"] = si.get("engine_name", "")
            settings["engine_level"] = self.shared.get("game_info", {}).get("level_name", "")
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps(settings))


class BookHandler(ServerRequestHandler):

    async def _get_obooksrv_moves(self, fen: str):
        # Opening books contain standard chess positions only
        variant = self.shared.get("variant", "chess")
        if variant not in ("chess", "3check", "kingofthehill"):
            return []
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_obooksrv_moves_sync, fen)

    def _get_obooksrv_moves_sync(self, fen: str):
        moves_data = []
        try:
            board = chess.Board(fen)
            with chess.polyglot.open_reader(OBOOKSRV_DATA_FILE) as reader:
                for entry in reader.find_all(board):
                    move_uci = entry.move.uci()
                    weight = entry.weight  # uint16
                    learn = entry.learn  # uint32
                    whitewins = (weight >> 8) & 0xFF
                    draws = weight & 0xFF
                    n_games = learn
                    blackwins = max(0, 100 - whitewins - draws)
                    moves_data.append(
                        {
                            "move": move_uci,
                            "count": n_games,
                            "whitewins": whitewins,
                            "draws": draws,
                            "blackwins": blackwins,
                        }
                    )
            moves_data.sort(key=lambda m: m["count"], reverse=True)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("obooksrv read failed: %s", exc)
            return None
        return moves_data

    @staticmethod
    def _strip_3check_fen(fen: str) -> str:
        """Strip check counting field from 3check FEN for standard book lookup."""
        parts = fen.split()
        if len(parts) == 7:  # 3check extended format
            return f"{parts[0]} {parts[1]} {parts[2]} {parts[3]} {parts[5]} {parts[6]}"
        return fen

    def _get_polyglot_moves(self, book_file: str, fen: str):
        # Opening books contain standard chess positions only
        variant = self.shared.get("variant", "chess")
        if variant not in ("chess", "3check", "kingofthehill"):
            return []
        moves_data = []
        try:
            # Strip 3check extension if present for standard book lookup
            fen = self._strip_3check_fen(fen)
            board = chess.Board(fen)
            aggregated = {}
            total_weight = 0

            with chess.polyglot.open_reader(book_file) as reader:
                for entry in reader.find_all(board):
                    move_uci = entry.move.uci()
                    weight = getattr(entry, "weight", 1)
                    total_weight += weight
                    if move_uci not in aggregated:
                        aggregated[move_uci] = {"move": move_uci, "count": 0}
                    aggregated[move_uci]["count"] += weight

            sorted_moves = sorted(aggregated.values(), key=lambda item: item["count"], reverse=True)

            for item in sorted_moves:
                count = item["count"]
                if total_weight > 0:
                    white_pct = int(round(100.0 * count / total_weight))
                else:
                    white_pct = 0
                draws_pct = 0
                black_pct = max(0, 100 - white_pct - draws_pct)
                moves_data.append(
                    {
                        "move": item["move"],
                        "count": count,
                        "whitewins": white_pct,
                        "draws": draws_pct,
                        "blackwins": black_pct,
                    }
                )
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Error reading opening book '%s': %s", book_file, exc)
        return moves_data

    async def get(self, *args, **kwargs):
        """Web-facing API for opening book explorer (independent from engine book)."""
        action = self.get_argument("action", "get_book_moves")

        # Build full opening book library from books.ini
        library = get_opening_books()
        books = [{"index": 0, "file": OBOOKSRV_BOOK_FILE, "label": OBOOKSRV_BOOK_LABEL}]
        for offset, book in enumerate(library, start=1):
            text_obj = book.get("text")
            label = ""
            if hasattr(text_obj, "web_text") and text_obj.web_text:
                label = text_obj.web_text
            elif hasattr(text_obj, "large_text") and text_obj.large_text:
                label = text_obj.large_text
            books.append({"index": offset, "file": book.get("file"), "label": label})

        if action == "get_book_list":
            # current selection: prefer web_book_file (updated on each new_book POST),
            # fall back to PicoOpeningBook PGN header, default to index 0 (Obooksrv).
            current_index = 0
            if books:
                active_file = self.shared.get("web_book_file") or (self.shared.get("headers") or {}).get("PicoOpeningBook")
                if active_file:
                    for entry in books:
                        if entry["file"] == active_file:
                            current_index = entry["index"]
                            break

            self.set_header("Content-Type", "application/json")
            self.write({"current_index": current_index, "books": books})
            return

        if action == "set_book_index":
            try:
                index = int(self.get_argument("index"))
            except (TypeError, ValueError):
                index = 0
            if not books:
                current = {"file": "", "label": ""}
            else:
                index = max(0, min(index, len(books) - 1))
                current = books[index]

            self.set_header("Content-Type", "application/json")
            self.write({"book": current})
            return

        # Default: get_book_moves
        fen = self.get_argument("fen", None)
        if not fen:
            last = self.shared.get("last_dgt_move_msg")
            if last and "fen" in last:
                fen = last["fen"]
        if not fen:
            fen = chess.STARTING_BOARD_FEN

        if not books:
            self.set_header("Content-Type", "application/json")
            self.write({"book": {"file": "", "label": ""}, "data": []})
            return

        # Determine which book index to use for the web explorer
        try:
            param_index = int(self.get_argument("book_index", ""))
        except (TypeError, ValueError):
            param_index = None

        if param_index is not None:
            index = max(0, min(param_index, len(books) - 1))
        else:
            index = 0
            headers = self.shared.get("headers") or {}
            active_file = headers.get("PicoOpeningBook")
            if active_file:
                for entry in books:
                    if entry["file"] == active_file:
                        index = entry["index"]
                        break

        current_book = books[index]
        book_file = current_book["file"]
        book_label = current_book["label"] or os.path.basename(book_file)

        if book_file == OBOOKSRV_BOOK_FILE:
            moves_data = await self._get_obooksrv_moves(fen)
            if moves_data is None:
                moves_data = []
        else:
            loop = asyncio.get_event_loop()
            moves_data = await loop.run_in_executor(None, self._get_polyglot_moves, book_file, fen)

        self.set_header("Content-Type", "application/json")
        self.write({"book": {"file": book_file or "", "label": book_label or ""}, "data": moves_data})

    async def post(self, *args, **kwargs):
        """Allow POST calls (used by jQuery.post) by delegating to GET logic."""
        await self.get(*args, **kwargs)


class ChessBoardHandler(ServerRequestHandler):
    def initialize(self, theme="dark", pieces="merida", board="natural_wood", shared=None):
        self.theme = theme
        self.pieces = pieces
        self.board = board
        self.shared = shared

    def get(self):
        web_speech = True
        web_audio_backend = False
        tutor_watch_active = False
        if self.shared is not None:
            web_audio_backend = self._get_web_audio_backend_setting()
            web_speech = self._get_web_speech_setting()
            if web_audio_backend:
                # Backend audio takes priority over browser speech synthesis.
                web_speech = False
            tutor_watch_active = bool(self.shared.get("tutor_watch_active", False))
        pieces = self.shared.get("pieces", self.pieces) if self.shared else self.pieces
        board = self.shared.get("web-board-theme", self.board) if self.shared else self.board
        from utilities import version as pico_version
        from pgn import ModeInfo
        import dgt.util as _dgt_util
        _eboard_labels = {
            _dgt_util.EBoard.DGT:       "DGT",
            _dgt_util.EBoard.CERTABO:   "Certabo",
            _dgt_util.EBoard.CHESSLINK: "ChessLink",
            _dgt_util.EBoard.CHESSNUT:  "Chessnut",
            _dgt_util.EBoard.ICHESSONE: "iChessOne",
            _dgt_util.EBoard.NOEBOARD:  "No e-board",
        }
        eboard_name = _eboard_labels.get(ModeInfo.get_eboard_type(), "DGT")
        variant = self.shared.get("variant", "chess") if self.shared else "chess"
        self.render(
            "web/picoweb/templates/clock.html",
            theme=self.theme,
            pieces=pieces,
            board=board,
            web_speech=web_speech,
            web_audio_backend=web_audio_backend,
            tutor_watch_active=tutor_watch_active,
            pico_version=pico_version,
            eboard_name=eboard_name,
            variant=variant,
        )

    def _get_web_speech_setting(self) -> bool:
        web_speech_local = self.shared.get("web_speech_local", False)
        web_speech_remote = self.shared.get("web_speech_remote", True)
        if _is_local_request(self.request):
            return web_speech_local
        return web_speech_remote

    def _get_web_audio_backend_setting(self) -> bool:
        if _is_local_request(self.request):
            return False
        return bool(self.shared.get("web_audio_backend_remote", False))


class HelpHandler(ServerRequestHandler):
    def initialize(self, theme="dark"):
        self.theme = theme

    def get(self):
        self.render("web/picoweb/templates/help.html", theme=self.theme)


class UploadPageHandler(tornado.web.RequestHandler):
    def get(self):
        self.render("web/picoweb/templates/upload.html")


class SettingsPageHandler(tornado.web.RequestHandler):
    def get(self):
        if not _require_auth_if_remote(self, "Settings"):
            return
        self.render("web/picoweb/templates/settings.html")


class SettingsDataHandler(ServerRequestHandler):
    def get(self):
        if not _require_auth_if_remote(self, "Settings"):
            return
        _, _, entries, _ = _load_ini_entries()
        payload = [
            {
                "key": item["key"],
                "value": item["value"],
                "enabled": item["enabled"],
                "help": item.get("help", ""),
            }
            for item in entries
        ]
        self.set_header("Content-Type", "application/json")
        self.write({"entries": payload})


class SettingsSaveHandler(ServerRequestHandler):
    def initialize(self, shared=None):
        self.shared = shared

    def post(self):
        if not _require_auth_if_remote(self, "Settings"):
            return
        try:
            payload = json.loads(self.request.body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            self.set_status(400)
            self.write({"error": "Invalid JSON payload"})
            return
        entries = payload.get("entries")
        if not isinstance(entries, list):
            self.set_status(400)
            self.write({"error": "Invalid entries payload"})
            return

        ini_path, lines, _, _ = _load_ini_entries()
        entries_by_key = {}
        keys_in_order = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key", "")).strip()
            if not key:
                continue
            if not INI_LINE_RE.match(f"{key} = "):
                continue
            if key not in entries_by_key:
                keys_in_order.append(key)
            value = str(entry.get("value", ""))
            if "\n" in value or "\r" in value:
                continue
            entries_by_key[key] = {
                "value": value,
                "enabled": bool(entry.get("enabled", False)),
            }

        def _line_for_entry(entry_key, entry_value, enabled):
            prefix = "" if enabled else "#"
            return f"{prefix}{entry_key} = {entry_value}\n"

        new_lines = []
        written_keys = set()
        for line in lines:
            match = INI_LINE_RE.match(line)
            if not match:
                new_lines.append(line)
                continue
            key = match.group(2)
            entry = entries_by_key.get(key)
            if not entry:
                new_lines.append(line)
                continue
            if key in written_keys:
                continue
            current_value = match.group(3).strip()
            is_commented = match.group(1) is not None
            if entry["enabled"]:
                if is_commented and current_value == entry["value"]:
                    new_lines.append(_line_for_entry(key, current_value, True))
                else:
                    new_lines.append(_line_for_entry(key, entry["value"], True))
            else:
                if is_commented and current_value == entry["value"]:
                    new_lines.append(line)
                else:
                    new_lines.append(_line_for_entry(key, entry["value"], False))
            written_keys.add(key)

        for key in keys_in_order:
            entry = entries_by_key[key]
            if not entry["enabled"] or key in written_keys:
                continue
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines[-1] += "\n"
            new_lines.append(_line_for_entry(key, entry["value"], True))

        with open(ini_path, "w", encoding="utf-8") as ini_file:
            ini_file.writelines(new_lines)

        # Update shared state for settings that take effect without restart
        if self.shared is not None:
            pieces_entry = entries_by_key.get("pieces")
            if pieces_entry and pieces_entry["enabled"]:
                self.shared["pieces"] = pieces_entry["value"]

            web_board_theme_entry = entries_by_key.get("web-board-theme")
            if web_board_theme_entry and web_board_theme_entry["enabled"]:
                self.shared["web-board-theme"] = web_board_theme_entry["value"]

            theme_entry = entries_by_key.get("theme")
            if theme_entry and theme_entry["enabled"]:
                self.shared["theme"] = theme_entry["value"]

        self.set_header("Content-Type", "application/json")
        self.write({"status": "ok"})


class WifiSetupPageHandler(tornado.web.RequestHandler):
    def get(self):
        allow_unauth = _allow_onboard_without_auth()
        if not allow_unauth or not _is_private_request(self.request):
            if not _require_auth_if_remote(self, "WiFi Setup"):
                return
        self.render("web/picoweb/templates/onboard.html")


class WifiSetupHandler(ServerRequestHandler):
    async def post(self):
        allow_unauth = _allow_onboard_without_auth()
        if not allow_unauth or not _is_private_request(self.request):
            if not _require_auth_if_remote(self, "WiFi Setup"):
                return
        try:
            payload = json.loads(self.request.body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            self.set_status(400)
            self.write({"error": "Invalid JSON payload"})
            return
        ssid = str(payload.get("ssid", "")).strip()
        password = str(payload.get("password", ""))
        hidden = bool(payload.get("hidden", False))
        if not ssid or len(ssid) > 32:
            self.set_status(400)
            self.write({"error": "Invalid SSID"})
            return
        if password and len(password) < 8:
            self.set_status(400)
            self.write({"error": "Password must be at least 8 characters"})
            return
        nmcli = "/usr/bin/nmcli"
        if not os.path.exists(nmcli):
            self.set_status(500)
            self.write({"error": "NetworkManager (nmcli) not available"})
            return
        cmd = ["sudo", "-n", nmcli, "dev", "wifi", "connect", ssid]
        if password:
            cmd += ["password", password]
        if hidden:
            cmd += ["hidden", "yes"]
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            )
        except subprocess.TimeoutExpired:
            self.set_status(504)
            self.write({"error": "Wi-Fi connect timed out"})
            return
        if result.returncode != 0:
            self.set_status(500)
            self.write({"error": (result.stderr or result.stdout or "Wi-Fi connect failed").strip()})
            return
        try:
            ip_result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["sudo", "-n", nmcli, "-g", "IP4.ADDRESS", "dev", "show", "wlan0"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                ),
            )
        except subprocess.TimeoutExpired:
            ip_result = subprocess.CompletedProcess([], 124, stdout="", stderr="timeout")
        ip_addr = ""
        if ip_result.returncode == 0:
            ip_addr = ip_result.stdout.strip().split("\n")[0].split("/")[0]
        self.set_header("Content-Type", "application/json")
        self.write({"status": "ok", "ip": ip_addr})


class SettingsActionHandler(ServerRequestHandler):
    async def post(self, action: str):
        allow_unauth = _allow_onboard_without_auth()
        if action == "wifi-hotspot":
            if not allow_unauth or not _is_private_request(self.request):
                if not _require_auth_if_remote(self, "Settings"):
                    return
        else:
            if not _require_auth_if_remote(self, "Settings"):
                return
        if action not in ("wifi-hotspot", "bt-pair", "bt-fix", "bt-reconnect"):
            self.set_status(404)
            self.write({"error": "Unknown action"})
            return
        if action == "wifi-hotspot":
            cmd = ["sudo", "-n", "/opt/picochess/wifi-hotspot-connect"]
            timeout = 30
        elif action == "bt-pair":
            cmd = ["sudo", "-n", "/opt/picochess/pair-phone"]
            timeout = 50
        elif action == "bt-fix":
            cmd = ["sudo", "-n", "/opt/picochess/Fix_bluetooth.sh"]
            timeout = 60
        else:  # bt-reconnect
            cmd = ["sudo", "-n", "/opt/picochess/reconnect-dgt-bt.sh"]
            timeout = 30
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            )
        except subprocess.TimeoutExpired:
            self.set_status(504)
            self.write({"error": f"{action} timed out"})
            return
        if result.returncode != 0:
            self.set_status(500)
            self.write({"error": (result.stderr or result.stdout or "Action failed").strip()})
            return
        self.set_header("Content-Type", "application/json")
        self.write({"status": "ok"})


class WebServer:
    def __init__(self):
        pass

    def make_app(self, theme: str, pieces: str, board: str, shared: dict) -> tornado.web.Application:
        """define web pages and their handlers"""
        wsgi_app = tornado.wsgi.WSGIContainer(pw)
        return tornado.web.Application(
            [
                (r"/", ChessBoardHandler, dict(theme=theme, pieces=pieces, board=board, shared=shared)),
                (r"/event", EventHandler, dict(shared=shared)),
                (r"/dgt", DGTHandler, dict(shared=shared)),
                (r"/info", InfoHandler, dict(shared=shared)),
                (r"/book", BookHandler, dict(shared=shared)),
                (r"/help", HelpHandler, dict(theme=theme)),
                (r"/channel", ChannelHandler, dict(shared=shared)),
                (r"/upload-pgn", UploadHandler),
                (r"/upload", UploadPageHandler),
                (r"/settings", SettingsPageHandler),
                (r"/settings/data", SettingsDataHandler),
                (r"/settings/save", SettingsSaveHandler, dict(shared=shared)),
                (r"/settings/action/(wifi-hotspot|bt-pair|bt-fix|bt-reconnect)", SettingsActionHandler),
                (r"/onboard", WifiSetupPageHandler),
                (r"/onboard/wifi", WifiSetupHandler),
                (r".*", tornado.web.FallbackHandler, {"fallback": wsgi_app}),
            ]
        )


class WebVr(DgtIface):
    """Handle the web (clock) communication."""

    def __init__(self, shared, dgtboard: EBoard, loop: asyncio.AbstractEventLoop):
        super(WebVr, self).__init__(dgtboard, loop)
        self.shared = shared
        # virtual_timer is a web clock updater, loop is started in parent
        self.virtual_timer = AsyncRepeatingTimer(1, self._runclock, self.loop)
        self.enable_dgtpi = dgtboard.is_pi
        self.clock_show_time = True
        self._last_runclock_time = 0.0  # wall-clock time of last _runclock tick
        self._runclock_elapsed_carry = 0.0  # keep sub-second drift until it adds up to a full second

        # keep the last time to find out errorous DGT_MSG_BWTIME messages (error: current time > last time)
        self.r_time = 3600 * 10  # max value cause 10h cant be reached by clock
        self.l_time = 3600 * 10  # max value cause 10h cant be reached by clock

    async def initialize(self):
        """async inits moved here"""
        sub = 2 if self.dgtboard.is_pi else 0
        await DisplayMsg.show(Message.DGT_CLOCK_VERSION(main=2, sub=sub, dev="web", text=None))

    def _create_clock_text(self):
        if "clock_text" not in self.shared:
            self.shared["clock_text"] = {}

    async def _runclock(self):
        """callback from AsyncRepeatingTimer once every second"""
        # this is probably only to show a running web clock
        # the clock time is handled by TimeControl class
        now = time.time()
        if self._last_runclock_time:
            self._runclock_elapsed_carry += max(0.0, now - self._last_runclock_time)
        else:
            self._runclock_elapsed_carry += 1.0
        self._last_runclock_time = now
        elapsed = int(self._runclock_elapsed_carry)
        self._runclock_elapsed_carry -= elapsed
        if self.side_running == ClockSide.LEFT:
            time_left = max(0, self.l_time - elapsed)
            if time_left <= 0:
                logger.info("negative/zero time left: %s", time_left)
                self.virtual_timer.stop()
                time_left = 0
            self.l_time = time_left
        if self.side_running == ClockSide.RIGHT:
            time_right = max(0, self.r_time - elapsed)
            if time_right <= 0:
                logger.info("negative/zero time right: %s", time_right)
                self.virtual_timer.stop()
                time_right = 0
            self.r_time = time_right
        # logger.debug(
        #    "(web) clock new time received l:%s r:%s", hms_time(self.l_time), hms_time(self.r_time)
        # )
        await DisplayMsg.show(
            Message.DGT_CLOCK_TIME(time_left=self.l_time, time_right=self.r_time, connect=True, dev="web")
        )
        self._display_time(self.l_time, self.r_time)

    def _display_time(self, time_left: int, time_right: int):
        if time_left >= 3600 * 10 or time_right >= 3600 * 10:
            logger.debug("time values not set - abort function")
        elif self.clock_show_time:
            l_hms = hms_time(time_left)
            r_hms = hms_time(time_right)
            if ModeInfo.get_clock_side() == "left":
                text_l = "{}:{:02d}.{:02d}".format(l_hms[0], l_hms[1], l_hms[2])
                text_r = "{}:{:02d}.{:02d}".format(r_hms[0], r_hms[1], r_hms[2])
                icon_d = "fa-caret-right" if self.side_running == ClockSide.RIGHT else "fa-caret-left"
                left_running = self.side_running == ClockSide.LEFT
            else:
                text_r = "{}:{:02d}.{:02d}".format(l_hms[0], l_hms[1], l_hms[2])
                text_l = "{}:{:02d}.{:02d}".format(r_hms[0], r_hms[1], r_hms[2])
                icon_d = "fa-caret-right" if self.side_running == ClockSide.LEFT else "fa-caret-left"
                left_running = self.side_running == ClockSide.RIGHT
            if self.side_running == ClockSide.NONE:
                icon_d = "fa-sort"
                l_cls, r_cls = "ctime-l", "ctime-r"
            else:
                l_cls = "ctime-l ctime-active" if left_running else "ctime-l ctime-inactive"
                r_cls = "ctime-r ctime-active" if not left_running else "ctime-r ctime-inactive"
            text = (f'<span class="{l_cls}">{text_l}</span>'
                    f'<i class="fa {icon_d}"></i>'
                    f'<span class="{r_cls}">{text_r}</span>')
            self._create_clock_text()
            self.shared["clock_text"] = text
            result = {"event": "Clock", "msg": text}
            EventHandler.write_to_clients(result)

    def display_move_on_clock(self, message):
        """Display a move on the web clock."""
        is_new_rev2 = self.dgtboard.is_revelation and self.dgtboard.enable_revelation_pi
        if self.enable_dgt3000 or is_new_rev2 or self.enable_dgtpi:
            bit_board, text = self.get_san(message, not self.enable_dgtpi)
            points = "..." if message.side == ClockSide.RIGHT else "."
            if self.enable_dgtpi:
                text = "{:3d}{:s}{:s}".format(bit_board.fullmove_number, points, text)
            else:
                text = "{:2d}{:s}{:s}".format(bit_board.fullmove_number % 100, points, text)
        else:
            text = message.move.uci()
            if message.side == ClockSide.RIGHT:
                text = text[:2].rjust(3) + text[2:].rjust(3)
            else:
                text = text[:2].ljust(3) + text[:2].ljust(3)
        if self.get_name() not in message.devs:
            logger.debug("ignored %s - devs: %s", text, message.devs)
            return True
        self.clock_show_time = False
        self._create_clock_text()
        logger.debug("[%s]", text)
        self.shared["clock_text"] = text
        result = {"event": "Clock", "msg": text}
        EventHandler.write_to_clients(result)
        return True

    def display_text_on_clock(self, message):
        """Display a text on the web clock."""
        if message.web_text != "":
            text = message.web_text
        else:
            text = message.large_text
        if self.get_name() not in message.devs:
            logger.debug("ignored %s - devs: %s", text, message.devs)
            return True
        self.clock_show_time = False
        self._create_clock_text()
        logger.debug("[%s]", text)
        self.shared["clock_text"] = text
        result = {"event": "Clock", "msg": text}
        EventHandler.write_to_clients(result)
        return True

    def display_time_on_clock(self, message):
        """Display the time on the web clock."""
        if self.get_name() not in message.devs:
            logger.debug("ignored endText - devs: %s", message.devs)
            return True
        if self.side_running != ClockSide.NONE or message.force:
            self.clock_show_time = True
            self._display_time(self.l_time, self.r_time)
        else:
            logger.debug("(web) clock isnt running - no need for endText")
        return True

    async def stop_clock(self, devs: set):
        """Stop the time on the web clock."""
        if self.get_name() not in devs:
            logger.debug("ignored stopClock - devs: %s", devs)
            return True
        if self.virtual_timer.is_running():
            self.virtual_timer.stop()
        return self._resume_clock(ClockSide.NONE)

    def _resume_clock(self, side: ClockSide):
        self.side_running = side
        return True

    async def start_clock(self, side: ClockSide, devs: set):
        """Start the time on the web clock."""
        if self.get_name() not in devs:
            logger.debug("ignored startClock - devs: %s", devs)
            return True
        if self.virtual_timer.is_running():
            self.virtual_timer.stop()
        if side != ClockSide.NONE:
            self._last_runclock_time = time.time()
            self._runclock_elapsed_carry = 0.0
            self.virtual_timer.start()
        self._resume_clock(side)
        self.clock_show_time = True
        self._display_time(self.l_time, self.r_time)
        return True

    def set_clock(self, time_left: int, time_right: int, devs: set):
        """Start the time on the web clock."""
        if self.get_name() not in devs:
            logger.debug("ignored setClock - devs: %s", devs)
            return True
        self.l_time = time_left
        self.r_time = time_right
        return True

    def light_squares_on_revelation(self, uci_move):
        """Light the rev2 squares."""
        result = {"event": "Light", "move": uci_move}
        EventHandler.write_to_clients(result)
        return True

    def light_square_on_revelation(self, square):
        """Light the rev2 square."""
        uci_move = square + square
        result = {"event": "Light", "move": uci_move}
        EventHandler.write_to_clients(result)
        return True

    def clear_light_on_revelation(self):
        """Clear all leds from rev2."""
        result = {"event": "Clear"}
        EventHandler.write_to_clients(result)
        return True

    def promotion_done(self, uci_move):
        pass

    def get_name(self):
        """Return name."""
        return "web"

    def _create_task(self, msg):
        # put callback to be executed by Tornado main event loop
        self.loop.create_task(self._process_message(msg))


class WebDisplay(DisplayMsg):
    level_text_sav = ""
    level_name_sav = ""
    engine_elo_sav = ""
    user_elo_sav = ""
    result_sav = ""
    engine_name = "Picochess"

    @staticmethod
    def _text_to_label(text_obj) -> str:
        """Extract a plain string from a DGT Text object or passthrough if already a str."""
        if text_obj is None:
            return ""
        if isinstance(text_obj, str):
            return text_obj.strip()
        for attr in ("web_text", "large_text", "medium_text"):
            val = getattr(text_obj, attr, None)
            if val and str(val).strip():
                return str(val).strip()
        return ""

    @staticmethod
    def _tc_to_label(tc_init: dict) -> str:
        """Derive a short human-readable time-control label from a tc_init dict."""
        if not tc_init:
            return ""
        from dgt.util import TimeMode
        mode   = tc_init.get("mode")
        depth  = tc_init.get("depth")  or 0
        node   = tc_init.get("node")   or 0
        moves  = tc_init.get("moves_to_go") or 0
        blitz  = tc_init.get("blitz")  or 0
        fixed  = tc_init.get("fixed")  or 0
        fisch  = tc_init.get("fischer") or 0
        blitz2 = tc_init.get("blitz2") or 0
        if depth:
            return f"{depth} ply"
        if node:
            return f"{node}k nodes"
        if moves:
            return f"{moves}/{blitz}+{fisch}/{blitz2}" if fisch else f"{moves}/{blitz}/{blitz2}"
        if mode == TimeMode.FISCHER:
            return f"{blitz}+{fisch}"
        if mode == TimeMode.BLITZ:
            return f"{blitz} min"
        if mode == TimeMode.FIXED:
            return f"{fixed} s"
        return ""

    def __init__(self, shared: dict, loop: asyncio.AbstractEventLoop):
        super(WebDisplay, self).__init__(loop)
        self.shared = shared
        self._task = None  # task for message consumer
        self.starttime = datetime.datetime.now().strftime("%H:%M:%S")
        self.analysis_state = {
            "depth": None,
            "score": None,
            "mate": None,
            "pv": None,
            "fen": None,
        }

    def _reset_analysis_state(self) -> None:
        self.analysis_state = {
            "depth": None,
            "score": None,
            "mate": None,
            "pv": None,
            "fen": None,
        }

    def _create_game_info(self):
        if "game_info" not in self.shared:
            self.shared["game_info"] = {}

    def _create_system_info(self):
        if "system_info" not in self.shared:
            self.shared["system_info"] = {}

    def _create_headers(self):
        if "headers" not in self.shared:
            self.shared["headers"] = OrderedDict()

    def _build_game_header(self, pgn_game: chess.pgn.Game, keep_these_headers: dict = None):
        """Build the game headers for the current game"""
        if ModeInfo.get_pgn_mode() and keep_these_headers:
            pgn_game.headers.update(keep_these_headers)
            return
        if WebDisplay.result_sav:
            pgn_game.headers["Result"] = WebDisplay.result_sav
        pgn_game.headers["Event"] = "PicoChess game"
        pgn_game.headers["Site"] = "picochess.org"
        pgn_game.headers["Date"] = datetime.datetime.today().strftime("%Y.%m.%d")
        pgn_game.headers["Round"] = "?"
        pgn_game.headers["White"] = "?"
        pgn_game.headers["Black"] = "?"

        user_name = "User"

        user_elo = "-"
        comp_elo = 2500
        rspeed = 1
        retro_speed = 100
        retro_speed_str = ""

        if "system_info" in self.shared:
            if "user_name" in self.shared["system_info"]:
                user_name = self.shared["system_info"]["user_name"]
            if "engine_name" in self.shared["system_info"]:
                WebDisplay.engine_name = self.shared["system_info"]["engine_name"]
            if "rspeed" in self.shared["system_info"]:
                rspeed = self.shared["system_info"]["rspeed"]
                retro_speed = int(100 * round(float(rspeed), 2))
                if ModeInfo.get_emulation_mode():
                    retro_speed_str = " (" + str(retro_speed) + "%" + ")"
                    if retro_speed < 20:
                        retro_speed_str = " (full speed)"
                else:
                    retro_speed_str = ""
            if "user_elo" in self.shared["system_info"]:
                user_elo = self.shared["system_info"]["user_elo"]
            if "engine_elo" in self.shared["system_info"]:
                comp_elo = self.shared["system_info"]["engine_elo"]

        if "game_info" in self.shared:
            if "level_text" in self.shared["game_info"]:
                text = self.shared["game_info"]["level_text"]
                engine_level = " ({0})".format(text.large_text)
                if text.large_text == "" or text.large_text == " ":
                    engine_level = ""
            else:
                engine_level = ""
            if "level_name" in self.shared["game_info"]:
                level_name = self.shared["game_info"]["level_name"]
                if level_name.startswith("Elo@"):
                    comp_elo = int(level_name[4:])
                    engine_level = ""
                elif level_name.startswith("Level@"):
                    try:
                        comp_elo = "Level {}".format(int(level_name[6:]))
                    except ValueError:
                        comp_elo = level_name[6:]
                    engine_level = ""
                elif "@" in level_name:
                    suffix = level_name.rsplit("@", 1)[-1]
                    if suffix.isdigit():
                        comp_elo = int(suffix)
                        engine_level = ""
            if "play_mode" in self.shared["game_info"]:
                if self.shared["game_info"]["play_mode"] == PlayMode.USER_WHITE:
                    pgn_game.headers["White"] = user_name
                    pgn_game.headers["Black"] = WebDisplay.engine_name + engine_level + retro_speed_str
                    pgn_game.headers["WhiteElo"] = str(user_elo)
                    pgn_game.headers["BlackElo"] = str(comp_elo)
                else:
                    pgn_game.headers["White"] = WebDisplay.engine_name + engine_level + retro_speed_str
                    pgn_game.headers["Black"] = user_name
                    pgn_game.headers["WhiteElo"] = str(comp_elo)
                    pgn_game.headers["BlackElo"] = str(user_elo)
            if "PGN Replay" in WebDisplay.engine_name:
                # keep headers from shared state; do not re-read transfer file
                pass

        if "ip_info" in self.shared:
            if "location" in self.shared["ip_info"]:
                pgn_game.headers["Site"] = self.shared["ip_info"]["location"]

        pgn_game.headers["Time"] = self.starttime
        # issue 55 - keep headers if existing valid header is given
        if keep_these_headers is not None:
            # issue #78 dont keep old FEN in headers to avoid webdisplay freeze
            cleaned = keep_essential_headers(keep_these_headers)
            ensure_important_headers(cleaned)  # #97 ensure "?" in important headers
            pgn_game.headers.update(cleaned)

    async def task(self, message):
        """Message task consumer for WebDisplay messages"""

        def _set_normal_pgn():
            if self.shared["system_info"]["old_engine"] != "":
                self.shared["system_info"]["engine_name"] = self.shared["system_info"]["old_engine"]
                self.shared["system_info"]["old_engine"] = ""

            if self.shared["system_info"]["user_name_orig"] != "":
                self.shared["system_info"]["user_name"] = self.shared["system_info"]["user_name_orig"]
                self.shared["system_info"]["user_name_orig"] = ""

            if WebDisplay.engine_elo_sav != "":
                self.shared["system_info"]["engine_elo"] = WebDisplay.engine_elo_sav
                WebDisplay.engine_elo_sav = ""

            if WebDisplay.user_elo_sav != "":
                self.shared["system_info"]["user_elo"] = WebDisplay.user_elo_sav
                WebDisplay.user_elo_sav = ""

            if WebDisplay.level_text_sav != "":
                self.shared["game_info"]["level_text"] = WebDisplay.level_text_sav
                WebDisplay.level_text_sav = ""

            if WebDisplay.level_name_sav != "":
                self.shared["game_info"]["level_name"] = WebDisplay.level_name_sav
                WebDisplay.level_name_sav = ""

            _build_headers()
            _send_headers()

        def _variant_board_fen(game: chess.Board) -> str:
            """Return board_fen with variant rules applied (e.g. atomic explosions).

            For atomic: replays the move stack on an AtomicBoard so captured
            pieces and their neighbours are removed.  For all other variants
            the standard board_fen is returned unchanged.
            """
            variant = self.shared.get("variant", "chess")
            if variant == "atomic":
                try:
                    atm = chess.variant.AtomicBoard()
                    for move in game.move_stack:
                        atm.push(move)
                    return atm.board_fen()
                except Exception:
                    pass  # fall through to standard
            return game.board_fen()

        def _oldstyle_fen(game: chess.Board):
            variant = self.shared.get("variant", "chess")
            if variant == "atomic" and game.move_stack:
                try:
                    atm = chess.variant.AtomicBoard()
                    for move in game.move_stack:
                        atm.push(move)
                    return atm.fen()
                except Exception:
                    pass  # fall through to standard
            elif variant == "racingkings":
                try:
                    rkb = chess.variant.RacingKingsBoard()
                    for move in game.move_stack:
                        rkb.push(move)
                    return rkb.fen()
                except Exception:
                    pass  # fall through to standard
            builder = []
            builder.append(_variant_board_fen(game))
            builder.append("w" if game.turn == chess.WHITE else "b")
            builder.append(game.castling_xfen())
            builder.append(chess.SQUARE_NAMES[game.ep_square] if game.ep_square else "-")
            builder.append(str(game.halfmove_clock))
            builder.append(str(game.fullmove_number))
            return " ".join(builder)

        def _build_headers():
            self._create_headers()
            if ModeInfo.get_pgn_mode() and self.shared.get("headers"):
                return
            pgn_game = pgn.Game()
            self._build_game_header(pgn_game)  # rebuilds game headers
            self.shared["headers"].update(pgn_game.headers)

        def _send_headers():
            EventHandler.write_to_clients({"event": "Header", "headers": dict(self.shared["headers"])})

        def _send_title():
            if "ip_info" in self.shared:
                EventHandler.write_to_clients({"event": "Title", "ip_info": self.shared["ip_info"]})

        def _attach_mistakes(result: dict) -> None:
            picotutor = self.shared.get("picotutor")
            if not picotutor:
                return
            try:
                result["mistakes"] = picotutor.get_eval_mistakes()
            except Exception as exc:  # pragma: no cover - defensive for UI
                logger.debug("failed to collect tutor mistakes: %s", exc)

        def _attach_variant_info(result: dict) -> None:
            """Attach 3check variant info to result dict for web clients."""
            variant = self.shared.get("variant", "chess")
            result["variant"] = variant
            if variant == "3check":
                result["checks"] = self.shared.get("checks_remaining", {"white": 3, "black": 3})

        def _maybe_send_analysis():
            state = self.analysis_state
            if self.shared.get("suppress_engine_analysis"):
                return
            if state.get("pv") is None:
                return
            if state.get("score") is None and not state.get("mate"):
                return
            pv_moves = state.get("pv") or []
            fen = None
            if "last_dgt_move_msg" in self.shared:
                fen = self.shared["last_dgt_move_msg"].get("fen")
            analysis_payload = {
                "depth": state.get("depth"),
                "score": state.get("score"),
                "mate": state.get("mate"),
                "pv": [move.uci() for move in pv_moves],
                "fen": fen,
                "source": "engine",
                "engine_name": self.shared.get("system_info", {}).get("engine_name", "Engine"),
            }
            self.shared["analysis_state"] = analysis_payload
            self.shared["analysis_state_engine"] = analysis_payload
            EventHandler.write_to_clients({"event": "Analysis", "analysis": analysis_payload})

        def _transfer(game: chess.Board, keep_these_headers: dict = None):
            variant = self.shared.get("variant", "chess")
            if variant == "atomic" and game.move_stack:
                try:
                    atm = chess.variant.AtomicBoard()
                    for move in game.move_stack:
                        atm.push(move)
                    pgn_game = pgn.Game.from_board(atm)
                except Exception:
                    pgn_game = pgn.Game().from_board(game)
            elif variant == "antichess" and game.move_stack:
                try:
                    acb = chess.variant.AntichessBoard()
                    for move in game.move_stack:
                        acb.push(move)
                    pgn_game = pgn.Game.from_board(acb)
                except Exception:
                    pgn_game = pgn.Game().from_board(game)
            elif variant == "racingkings":
                try:
                    rkb = chess.variant.RacingKingsBoard()
                    for move in game.move_stack:
                        rkb.push(move)
                    pgn_game = pgn.Game.from_board(rkb)
                except Exception:
                    pgn_game = pgn.Game().from_board(game)
            elif variant == "3check" and game.move_stack:
                try:
                    tcb = chess.variant.ThreeCheckBoard()
                    for move in game.move_stack:
                        tcb.push(move)
                    pgn_game = pgn.Game.from_board(tcb)
                except Exception:
                    pgn_game = pgn.Game().from_board(game)
            else:
                pgn_game = pgn.Game().from_board(game)
            self._build_game_header(pgn_game, keep_these_headers)
            self.shared["headers"] = pgn_game.headers
            return pgn_game.accept(pgn.StringExporter(headers=True, comments=False, variations=False))

        def peek_uci(game: chess.Board):
            """Return last move in uci format."""
            try:
                return game.peek().uci()
            except IndexError:
                return chess.Move.null().uci()

        # switch-case
        if isinstance(message, Message.START_NEW_GAME):
            # Clear stale analysis so clients don't keep showing the previous
            # position's engine lines while waiting for fresh analysis output.
            self.analysis_state = {"depth": None, "score": None, "mate": None, "pv": None, "fen": None}
            for key in ("analysis_state", "analysis_state_engine", "analysis_state_tutor"):
                self.shared.pop(key, None)
            EventHandler.write_to_clients({"event": "Analysis", "analysis": None})
            WebDisplay.result_sav = ""
            self.starttime = datetime.datetime.now().strftime("%H:%M:%S")
            if ModeInfo.get_pgn_mode():
                keep_these_headers = self.shared["headers"]
            elif message.newgame:
                keep_these_headers = None
            else:
                # #78 and #55 just a new position, keep headers
                keep_these_headers = self.shared["headers"]
            pgn_str = _transfer(message.game, keep_these_headers)
            fen = _oldstyle_fen(message.game) if message.game.move_stack else message.game.fen()
            result = {
                "pgn": pgn_str,
                "fen": fen,
                "event": "Game",
                "move": "0000",
                "play": "newgame",
            }
            _attach_variant_info(result)
            result["mistakes"] = []  # always empty for a new game
            self.shared.pop("pending_computer_move", None)  # discard any pending engine move
            self.shared["last_dgt_move_msg"] = result
            EventHandler.write_to_clients(result)
            if message.newgame:
                # issue #55 - dont reset headers if its not a real new game
                _build_headers()
                _send_headers()
                _send_title()

        elif isinstance(message, Message.IP_INFO):
            self.shared["ip_info"] = message.info
            # Expose network fields in system_info so the overlay Info
            # panel (which reads system_info) can display them.
            self._create_system_info()
            self.shared["system_info"]["ip"] = message.info.get("int_ip", "")
            self.shared["system_info"]["ext_ip"] = message.info.get("ext_ip", "")
            self.shared["system_info"]["location"] = message.info.get("location", "")

        elif isinstance(message, Message.BATTERY):
            self._create_system_info()
            pct = message.percent
            if pct == 0x7F:
                self.shared["system_info"]["battery"] = "N/A"
            else:
                self.shared["system_info"]["battery"] = "{}%".format(min(pct, 99))

        elif isinstance(message, Message.SYSTEM_INFO):
            self._create_system_info()
            self.shared["system_info"].update(message.info)
            # Let the web client know whether a physical board is connected so it
            # can make the diagram read-only when appropriate.
            self.shared["system_info"]["has_board"] = (
                ModeInfo.get_eboard_type() != EBoard.NOEBOARD
            )
            # store old/original values of everything from start
            if "engine_name" in self.shared["system_info"]:
                WebDisplay.engine_name = self.shared["system_info"]["engine_name"]
                self.shared["system_info"]["old_engine"] = self.shared["system_info"]["engine_name"]
            if "engine_elo" in self.shared["system_info"]:
                WebDisplay.engine_elo_sav = self.shared["system_info"]["engine_elo"]
            if "rspeed" in self.shared["system_info"]:
                self.shared["system_info"]["rspeed_orig"] = self.shared["system_info"]["rspeed"]
            if "user_name" in self.shared["system_info"]:
                self.shared["system_info"]["user_name_orig"] = self.shared["system_info"]["user_name"]
            if "user_elo" in self.shared["system_info"]:
                WebDisplay.user_elo_sav = self.shared["system_info"]["user_elo"]

        elif isinstance(message, Message.ENGINE_STARTUP):
            for index in range(0, len(message.installed_engines)):
                eng = message.installed_engines[index]
                if eng["file"] == message.file:
                    self.shared["system_info"]["engine_elo"] = eng["elo"]
                    #  @todo check if eng["name"] should be set here also
                    #  probably  not needed as its set in SYSTEM_INFO on startup
                    break
            _build_headers()
            _send_headers()

        elif isinstance(message, Message.ENGINE_READY):
            self._create_system_info()
            WebDisplay.engine_name = message.engine_name
            self.shared["system_info"]["old_engine"] = self.shared["system_info"]["engine_name"] = message.engine_name
            WebDisplay.engine_elo_sav = self.shared["system_info"]["engine_elo"] = message.eng["elo"]
            if not message.has_levels:
                if "level_text" in self.shared["game_info"]:
                    del self.shared["game_info"]["level_text"]
                if "level_name" in self.shared["game_info"]:
                    del self.shared["game_info"]["level_name"]
            _build_headers()
            _send_headers()
            # Push the new engine name to connected web clients so the overlay
            # tile subtitle stays current without requiring a page refresh.
            EventHandler.write_to_clients({"event": "SystemInfo", "msg": {"engine_name": message.engine_name}})

        elif isinstance(message, Message.STARTUP_INFO):
            self.shared["game_info"] = message.info.copy()
            # Mirror interaction_mode and play_mode into system_info so the
            # web client can determine diagram interactivity on page load.
            self._create_system_info()
            _im = message.info.get("interaction_mode")
            _pm = message.info.get("play_mode")
            if _im is not None:
                self.shared["system_info"]["interaction_mode"] = _im.name.lower()
            if _pm is not None:
                self.shared["system_info"]["play_mode"] = (
                    "user_white" if _pm == PlayMode.USER_WHITE else "user_black"
                )
            # change book_index to book_text
            books = message.info["books"]
            book_index = message.info["book_index"]
            if books and book_index is not None and 0 <= book_index < len(books):
                self.shared["game_info"]["book_text"] = books[book_index]["text"]
            else:
                self.shared["game_info"]["book_text"] = ""
            self.shared["game_info"].pop("book_index", None)  # safer to pop not del, but never used
            # Mirror plain-string labels into system_info for get_system_info.
            # game_info["book_text"] is a DGT Text object; extract readable text.
            _raw_book = self.shared["game_info"].get("book_text")
            self.shared["system_info"]["book_name"] = self._text_to_label(_raw_book) or "Off"
            # Derive time label from tc_init (TimeMode enums are not JSON-safe).
            _tc_init = message.info.get("tc_init")
            if _tc_init:
                _tc_label = self._tc_to_label(_tc_init)
                if _tc_label:
                    self.shared["system_info"]["time_label"] = _tc_label

            # remove if no level_text or level_name exist, else set old/original value from start
            if self.shared["game_info"].get("level_text") is None:
                self.shared["game_info"].pop("level_text", None)
                WebDisplay.level_text_sav = ""
            else:
                WebDisplay.level_text_sav = self.shared["game_info"]["level_text"]
            if self.shared["game_info"].get("level_name") is None:
                self.shared["game_info"].pop("level_name", None)
                WebDisplay.level_name_sav = ""
            else:
                WebDisplay.level_name_sav = self.shared["game_info"]["level_name"]

        elif isinstance(message, Message.OPENING_BOOK):
            self._create_game_info()
            self.shared["game_info"]["book_text"] = message.book_text
            # Mirror plain-string book label into system_info and push live
            # update so the overlay tile subtitle reflects the new selection.
            self._create_system_info()
            _book_name = self._text_to_label(message.book_text) or "Off"
            self.shared["system_info"]["book_name"] = _book_name
            EventHandler.write_to_clients({"event": "SystemInfo", "msg": {"book_name": _book_name}})

        elif isinstance(message, Message.INTERACTION_MODE):
            self._create_game_info()
            self.shared["game_info"]["interaction_mode"] = message.mode
            _set_normal_pgn()
            # Keep system_info in sync and push live update so connected
            # clients can immediately re-evaluate diagram interactivity.
            self._create_system_info()
            _im_str = message.mode.name.lower()
            self.shared["system_info"]["interaction_mode"] = _im_str
            EventHandler.write_to_clients({"event": "SystemInfo", "msg": {"interaction_mode": _im_str}})

            if self.shared["game_info"]["interaction_mode"] == Mode.REMOTE:
                if self.shared["system_info"]["engine_name"] != "" and self.shared["system_info"]["old_engine"] == "":
                    self.shared["system_info"]["old_engine"] = self.shared["system_info"]["engine_name"]
                self.shared["system_info"]["engine_name"] = "Remote Player"

                if self.shared["system_info"]["engine_elo"] != "" and WebDisplay.engine_elo_sav == "":
                    WebDisplay.engine_elo_sav = self.shared["system_info"]["engine_elo"]
                self.shared["system_info"]["engine_elo"] = "?"

                if "level_text" in self.shared["game_info"]:
                    if self.shared["game_info"]["level_text"] != "" and WebDisplay.level_text_sav == "":
                        WebDisplay.level_text_sav = self.shared["game_info"]["level_text"]
                    del self.shared["game_info"]["level_text"]

                if "level_name" in self.shared["game_info"]:
                    if self.shared["game_info"]["level_name"] != "" and WebDisplay.level_name_sav == "":
                        WebDisplay.level_name_sav = self.shared["game_info"]["level_name"]
                    del self.shared["game_info"]["level_name"]

            elif self.shared["game_info"]["interaction_mode"] == Mode.OBSERVE:
                if self.shared["system_info"]["engine_name"] != "" and self.shared["system_info"]["old_engine"] == "":
                    self.shared["system_info"]["old_engine"] = self.shared["system_info"]["engine_name"]
                self.shared["system_info"]["engine_name"] = "Player B"

                if self.shared["system_info"]["user_name"] != "" and self.shared["system_info"]["user_name_orig"] == "":
                    self.shared["system_info"]["user_name_orig"] = self.shared["system_info"]["user_name"]
                self.shared["system_info"]["user_name"] = "Player A"

                if self.shared["system_info"]["engine_elo"] != "" and WebDisplay.engine_elo_sav == "":
                    WebDisplay.engine_elo_sav = self.shared["system_info"]["engine_elo"]
                self.shared["system_info"]["engine_elo"] = "?"

                if self.shared["system_info"]["user_elo"] != "" and WebDisplay.user_elo_sav == "":
                    WebDisplay.user_elo_sav = self.shared["system_info"]["user_elo"]
                self.shared["system_info"]["user_elo"] = "?"

                if "level_text" in self.shared["game_info"]:
                    if self.shared["game_info"]["level_text"] != "" and WebDisplay.level_text_sav == "":
                        WebDisplay.level_text_sav = self.shared["game_info"]["level_text"]
                    del self.shared["game_info"]["level_text"]

                if "level_name" in self.shared["game_info"]:
                    if self.shared["game_info"]["level_name"] != "" and WebDisplay.level_name_sav == "":
                        WebDisplay.level_name_sav = self.shared["game_info"]["level_name"]
                    del self.shared["game_info"]["level_name"]

            _build_headers()
            _send_headers()

        elif isinstance(message, Message.PLAY_MODE):
            # issue 55 - dont reset headers when switching sides in PGN engine replay
            if "PGN Replay" not in WebDisplay.engine_name:
                self._create_game_info()
                self.shared["game_info"]["play_mode"] = message.play_mode
                # PLAY_MODE fires in set_wait_state() before START_NEW_GAME when the
                # user's colour changes at the start of a new game.  At that point
                # result_sav still holds the previous game's result ("0-1" etc.).
                # Clearing it here prevents _build_headers() from embedding the stale
                # result in the Header event that is sent to web clients.
                # START_NEW_GAME (which arrives next) clears it anyway; we just beat it.
                WebDisplay.result_sav = ""
                _build_headers()
                _send_headers()
            # Keep system_info in sync and push live update.
            self._create_system_info()
            _pm_str = "user_white" if message.play_mode == PlayMode.USER_WHITE else "user_black"
            self.shared["system_info"]["play_mode"] = _pm_str
            EventHandler.write_to_clients({"event": "SystemInfo", "msg": {"play_mode": _pm_str}})

        elif isinstance(message, Message.TIME_CONTROL):
            self._create_game_info()
            self.shared["game_info"]["time_text"] = message.time_text
            self.shared["game_info"]["tc_init"] = message.tc_init
            # Derive a plain-string time label from tc_init and push it.
            # tc_init contains TimeMode enums which are not JSON-safe, so we
            # never put tc_init itself into system_info — only the derived label.
            _time_label = self._tc_to_label(message.tc_init)
            if _time_label:
                self._create_system_info()
                self.shared["system_info"]["time_label"] = _time_label
                EventHandler.write_to_clients({"event": "SystemInfo", "msg": {"time_label": _time_label}})
            # Immediately push new clock times to web clients.
            # The normal dispatch chain (CLOCK_SET → CLOCK_START) can be silently
            # dropped when clock_connected["web"] is not yet set, or can be
            # queued behind a running maxtimer that never re-shows time when
            # side_running==NONE.  This guarantees the overlay change is visible.
            try:
                tc_init = message.tc_init
                _tc = TimeControl(**{k: v for k, v in tc_init.items() if k != "internal_time"})
                _tl, _tr = _tc.get_internal_time()
                if _tl < 3600 * 10 and _tr < 3600 * 10:
                    _l = hms_time(_tl)
                    _r = hms_time(_tr)
                    if ModeInfo.get_clock_side() == "left":
                        _tl_str = "{}:{:02d}.{:02d}".format(_l[0], _l[1], _l[2])
                        _tr_str = "{}:{:02d}.{:02d}".format(_r[0], _r[1], _r[2])
                    else:
                        _tr_str = "{}:{:02d}.{:02d}".format(_l[0], _l[1], _l[2])
                        _tl_str = "{}:{:02d}.{:02d}".format(_r[0], _r[1], _r[2])
                    _text = (f'<span class="ctime-l">{_tl_str}</span>'
                             f'<i class="fa fa-sort"></i>'
                             f'<span class="ctime-r">{_tr_str}</span>')
                    self._create_clock_text()
                    self.shared["clock_text"] = _text
                    EventHandler.write_to_clients({"event": "Clock", "msg": _text})
            except Exception:
                pass  # non-fatal; normal dispatch chain remains the fallback

        elif isinstance(message, Message.LEVEL):
            self._create_game_info()
            self.shared["game_info"]["level_text"] = message.level_text
            self.shared["game_info"]["level_name"] = message.level_name

        elif isinstance(message, Message.PICOWATCHER):
            self.shared["tutor_watch_watcher"] = bool(message.picowatcher)
            self.shared["tutor_watch_active"] = bool(
                self.shared.get("tutor_watch_watcher") or self.shared.get("tutor_watch_coach")
            )
            EventHandler.write_to_clients(
                {"event": "TutorWatch", "active": self.shared["tutor_watch_active"]}
            )

        elif isinstance(message, Message.PICOCOACH):
            coach_value = message.picocoach
            coach_is_off = coach_value == 0 or coach_value == PicoCoach.COACH_OFF or coach_value is False
            coach_is_lift = coach_value == 2 or coach_value == PicoCoach.COACH_LIFT
            coach_is_on = coach_value == 1 or coach_value == PicoCoach.COACH_ON or (
                coach_value and not coach_is_lift and not coach_is_off
            )
            self.shared["tutor_watch_coach"] = bool(coach_is_on or coach_is_lift)
            if coach_is_lift:
                self.shared["tutor_watch_coach_pref"] = PicoCoach.COACH_LIFT
            elif coach_is_on:
                self.shared["tutor_watch_coach_pref"] = PicoCoach.COACH_ON
            self.shared["tutor_watch_active"] = bool(
                self.shared.get("tutor_watch_watcher") or self.shared.get("tutor_watch_coach")
            )
            EventHandler.write_to_clients(
                {"event": "TutorWatch", "active": self.shared["tutor_watch_active"]}
            )

        elif isinstance(message, Message.WEB_ANALYSIS):
            analysis_payload = message.analysis or {}
            source = analysis_payload.get("source", "engine")
            self.shared["suppress_engine_analysis"] = bool(analysis_payload.get("suppress_engine_line"))
            if analysis_payload.get("clear"):
                if source == "tutor":
                    self.shared.pop("analysis_state_tutor", None)
                else:
                    self.shared.pop("analysis_state_engine", None)
                    self.shared.pop("analysis_state", None)
                    self._reset_analysis_state()
            else:
                if "fen" not in analysis_payload and "last_dgt_move_msg" in self.shared:
                    analysis_payload["fen"] = self.shared["last_dgt_move_msg"].get("fen")
                if source == "tutor":
                    self.shared["analysis_state_tutor"] = analysis_payload
                else:
                    self.shared["analysis_state_engine"] = analysis_payload
            self.shared["analysis_web_enabled"] = True
            EventHandler.write_to_clients({"event": "Analysis", "analysis": analysis_payload})

        elif isinstance(message, Message.NEW_PV):
            self.analysis_state["pv"] = message.pv
            _maybe_send_analysis()

        elif isinstance(message, Message.NEW_SCORE):
            self.analysis_state["score"] = message.score
            self.analysis_state["mate"] = message.mate
            _maybe_send_analysis()

        elif isinstance(message, Message.NEW_DEPTH):
            self.analysis_state["depth"] = message.depth
            _maybe_send_analysis()

        elif isinstance(message, Message.DGT_SERIAL_NR):
            # Serial number confirms the physical board is present on the bus.
            # Turn the footer dot green regardless of whether a clock is attached.
            if message.number:
                EventHandler.write_to_clients({"event": "Status", "eboard": "connected"})

        elif isinstance(message, Message.DGT_NO_CLOCK_ERROR):
            EventHandler.write_to_clients({"event": "Status", "eboard": "error"})

        elif isinstance(message, Message.DGT_CLOCK_VERSION):
            if message.dev == "ser":
                attached = "serial"
            elif message.dev == "i2c":
                attached = "i2c-pi"
            else:
                attached = "server"
            connected = attached != "server"   # physical board, not web-only
            result = {"event": "Status", "msg": "Ok clock " + attached, "eboard": "connected" if connected else "noeboard"}
            EventHandler.write_to_clients(result)

        elif isinstance(message, Message.COMPUTER_MOVE):
            # @todo issue 54 misuse this as USER_MOVE until we have such a message
            if not message.is_user_move:
                game_copy = message.game.copy()
                game_copy.push(message.move)
                if ModeInfo.get_pgn_mode():
                    pgn_str = _transfer(game_copy, self.shared["headers"])
                else:
                    pgn_str = _transfer(game_copy)
                fen = _oldstyle_fen(game_copy)
                mov = message.move.uci()
                result = {"pgn": pgn_str, "fen": fen, "event": "Fen", "move": mov, "play": "computer"}
                _attach_mistakes(result)
                _attach_variant_info(result)
                self.shared["pending_computer_move"] = result  # not sent => keep it for COMPUTER_MOVE_DONE

        elif isinstance(message, Message.COMPUTER_MOVE_DONE):
            WebDisplay.result_sav = ""
            result = self.shared.pop("pending_computer_move", None)
            # If START_NEW_GAME already ran it cleared pending_computer_move, so result is None –
            # skip this stale engine move so the new game's clean PGN isn't overwritten.
            if result is not None:
                # Re-stamp variant info: for 3check, process_fen has already pushed
                # the engine move onto the ThreeCheck board and updated checks_remaining,
                # so this overwrites the stale value captured at COMPUTER_MOVE time.
                _attach_variant_info(result)
                self.shared["last_dgt_move_msg"] = result
                EventHandler.write_to_clients(result)

        elif isinstance(message, Message.DGT_FEN):
            # Update dgt_fen for board scan functionality
            self.shared["dgt_fen"] = message.fen.split(" ")[0]

        elif isinstance(message, Message.USER_MOVE_DONE):
            WebDisplay.result_sav = ""
            pgn_str = _transfer(message.game, self.shared["headers"])  # dont remake headers every move
            fen = _oldstyle_fen(message.game)
            mov = message.move.uci()
            result = {"pgn": pgn_str, "fen": fen, "event": "Fen", "move": mov, "play": "user"}
            _attach_mistakes(result)
            _attach_variant_info(result)
            self.shared["last_dgt_move_msg"] = result
            EventHandler.write_to_clients(result)

        elif isinstance(message, Message.REVIEW_MOVE_DONE):
            pgn_str = _transfer(message.game, self.shared["headers"])  # dont remake headers every move
            fen = _oldstyle_fen(message.game)
            mov = message.move.uci()
            result = {"pgn": pgn_str, "fen": fen, "event": "Fen", "move": mov, "play": "review"}
            _attach_mistakes(result)
            _attach_variant_info(result)
            self.shared["last_dgt_move_msg"] = result
            EventHandler.write_to_clients(result)

        elif isinstance(message, Message.ALTERNATIVE_MOVE):
            pgn_str = _transfer(message.game, self.shared["headers"])  # dont remake headers every move
            fen = _oldstyle_fen(message.game)
            mov = peek_uci(message.game)
            result = {"pgn": pgn_str, "fen": fen, "event": "Fen", "move": mov, "play": "reload"}
            _attach_mistakes(result)
            _attach_variant_info(result)
            self.shared["last_dgt_move_msg"] = result
            EventHandler.write_to_clients(result)

        elif isinstance(message, Message.SWITCH_SIDES):
            pgn_str = _transfer(message.game)
            fen = _oldstyle_fen(message.game)
            mov = message.move.uci()
            result = {"pgn": pgn_str, "fen": fen, "event": "Fen", "move": mov, "play": "reload"}
            _attach_mistakes(result)
            _attach_variant_info(result)
            self.shared["last_dgt_move_msg"] = result
            EventHandler.write_to_clients(result)

        elif isinstance(message, Message.TAKE_BACK):
            pgn_str = _transfer(message.game)
            fen = _oldstyle_fen(message.game)
            mov = peek_uci(message.game)
            result = {"pgn": pgn_str, "fen": fen, "event": "Fen", "move": mov, "play": "reload"}
            _attach_mistakes(result)
            _attach_variant_info(result)
            self.shared["last_dgt_move_msg"] = result
            EventHandler.write_to_clients(result)

        elif isinstance(message, Message.PROMOTION_DIALOG):
            result = {"event": "PromotionDlg", "move": message.move}
            EventHandler.write_to_clients(result)

        elif isinstance(message, Message.GAME_ENDS):
            if message.result == GameResult.DRAW:
                WebDisplay.result_sav = "1/2-1/2"
            elif message.result in (GameResult.WIN_WHITE, GameResult.WIN_BLACK):
                WebDisplay.result_sav = "1-0" if message.result == GameResult.WIN_WHITE else "0-1"
            elif message.result == GameResult.THREE_CHECK_WHITE:
                WebDisplay.result_sav = "1-0"
            elif message.result == GameResult.THREE_CHECK_BLACK:
                WebDisplay.result_sav = "0-1"
            elif message.result == GameResult.KOTH_WHITE:
                WebDisplay.result_sav = "1-0"
            elif message.result == GameResult.KOTH_BLACK:
                WebDisplay.result_sav = "0-1"
            elif message.result == GameResult.ATOMIC_WHITE:
                WebDisplay.result_sav = "1-0"
            elif message.result == GameResult.ATOMIC_BLACK:
                WebDisplay.result_sav = "0-1"
            elif message.result == GameResult.RK_WHITE:
                WebDisplay.result_sav = "1-0"
            elif message.result == GameResult.RK_BLACK:
                WebDisplay.result_sav = "0-1"
            elif message.result == GameResult.ANTICHESS_WHITE:
                WebDisplay.result_sav = "1-0"
            elif message.result == GameResult.ANTICHESS_BLACK:
                WebDisplay.result_sav = "0-1"
            elif message.result == GameResult.OUT_OF_TIME or message.result == GameResult.MATE:
                # last moved won - same as in DgtDisplay
                if message.game.turn == chess.WHITE:
                    WebDisplay.result_sav = "0-1"
                else:
                    WebDisplay.result_sav = "1-0"
            else:
                WebDisplay.result_sav = ""
            if WebDisplay.result_sav:
                # in future cleanups everything should be in headers only
                # and its most logical that WebDisplay updates the shared header
                # now for issue #111 make sure also header has end game result
                self.shared["headers"]["Result"] = WebDisplay.result_sav
            # Rebuild PGN with result and push to all clients so the move list
            # immediately shows "1-0", "0-1" or "1/2-1/2" appended.
            # If an engine move was announced but not yet confirmed on the board,
            # include it in the final PGN so the move list is complete.
            game_for_end = message.game
            pending = self.shared.get("pending_computer_move")
            if pending and "move" in pending:
                try:
                    game_for_end = message.game.copy()
                    game_for_end.push(chess.Move.from_uci(pending["move"]))
                except Exception:
                    pass
            pgn_str = _transfer(game_for_end)
            fen = _oldstyle_fen(game_for_end)
            mov = peek_uci(game_for_end)
            end_msg = {"pgn": pgn_str, "fen": fen, "event": "Fen", "move": mov, "play": "reload"}
            _attach_mistakes(end_msg)
            _attach_variant_info(end_msg)
            self.shared["last_dgt_move_msg"] = end_msg
            EventHandler.write_to_clients(end_msg)

    async def message_consumer(self):
        """Message task consumer for WebDisplay messages"""
        logger.debug("WebDisplay msg_queue ready")
        try:
            while True:
                message = await self.msg_queue.get()
                if (
                    not isinstance(message, Message.DGT_SERIAL_NR)
                    and not isinstance(message, Message.DGT_CLOCK_TIME)
                    and not isinstance(message, Message.CLOCK_TIME)
                    and not isinstance(message, Message.NEW_DEPTH)
                    and not isinstance(message, Message.NEW_SCORE)
                    and not isinstance(message, Message.NEW_PV)
                    and not isinstance(message, Message.WEB_ANALYSIS)
                ):
                    logger.debug("received message from msg_queue: %s", message)
                # issue #45 just process one message at a time - dont spawn task
                # asyncio.create_task(self.task(message))
                try:
                    await self.task(message)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("WebDisplay: unhandled exception processing %s", message)
                self.msg_queue.task_done()
                await asyncio.sleep(0.05)  # balancing message queues
        except asyncio.CancelledError:
            logger.debug("WebDisplay msg_queue cancelled")
