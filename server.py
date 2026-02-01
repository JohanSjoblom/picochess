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
import json
import logging
import os
import re
from collections import OrderedDict
from typing import Set
import asyncio
import platform

import chess  # type: ignore
import chess.pgn as pgn  # type: ignore
import chess.polyglot  # type: ignore

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
)
from upload_pgn import UploadHandler
from web.picoweb import picoweb as pw

from dgt.api import Event, Message
from dgt.util import PlayMode, Mode, ClockSide, GameResult, PicoCoach, flip_board_fen
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
            await Observable.fire(Event.SAVE_GAME(pgn_filename="last_game.pgn"))
        elif action == "scan_board":
            result_fen = await self.process_board_scan()
            self.write({"success": result_fen is not None, "fen": result_fen})
            self.set_header("Content-Type", "application/json")


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
        x_real_ip = self.request.headers.get("X-Real-IP")
        real_ip = x_real_ip if x_real_ip else self.request.remote_ip
        return real_ip

    def open(self, *args: str, **kwargs: str):
        EventHandler.clients.add(self)
        client_ips.append(self.real_ip())
        # sync newly connected client with last known board state, if available
        if self.shared and "last_dgt_move_msg" in self.shared:
            try:
                self.write_message(self.shared["last_dgt_move_msg"])
            except Exception as exc:  # pragma: no cover - websocket errors
                logger.warning("failed to sync board state to client: %s", exc)
        for key in ("analysis_state_engine", "analysis_state_tutor", "analysis_state"):
            if self.shared and key in self.shared:
                try:
                    self.write_message({"event": "Analysis", "analysis": self.shared[key]})
                except Exception as exc:  # pragma: no cover - websocket errors
                    logger.warning("failed to sync analysis to client: %s", exc)

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


class BookHandler(ServerRequestHandler):

    async def _get_obooksrv_moves(self, fen: str):
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
            # initial selection: try to match engine/book header once, otherwise index 0
            current_index = 0
            if books:
                headers = self.shared.get("headers") or {}
                active_file = headers.get("PicoOpeningBook")
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
            moves_data = self._get_polyglot_moves(book_file, fen)

        self.set_header("Content-Type", "application/json")
        self.write({"book": {"file": book_file or "", "label": book_label or ""}, "data": moves_data})

    async def post(self, *args, **kwargs):
        """Allow POST calls (used by jQuery.post) by delegating to GET logic."""
        await self.get(*args, **kwargs)


class ChessBoardHandler(ServerRequestHandler):
    def initialize(self, theme="dark", shared=None):
        self.theme = theme
        self.shared = shared

    def get(self):
        web_speech = True
        tutor_watch_active = False
        if self.shared is not None:
            web_speech = self._get_web_speech_setting()
            tutor_watch_active = bool(self.shared.get("tutor_watch_active", False))
        self.render(
            "web/picoweb/templates/clock.html",
            theme=self.theme,
            web_speech=web_speech,
            tutor_watch_active=tutor_watch_active,
        )

    def _get_web_speech_setting(self) -> bool:
        web_speech_local = self.shared.get("web_speech_local", True)
        web_speech_remote = self.shared.get("web_speech_remote", False)
        remote_ip = self.request.headers.get("X-Real-IP") or self.request.remote_ip
        if remote_ip in ("127.0.0.1", "::1"):
            return web_speech_local
        return web_speech_remote


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
        self.set_header("Content-Type", "application/json")
        self.write({"status": "ok"})


class WebServer:
    def __init__(self):
        pass

    def make_app(self, theme: str, shared: dict) -> tornado.web.Application:
        """define web pages and their handlers"""
        wsgi_app = tornado.wsgi.WSGIContainer(pw)
        return tornado.web.Application(
            [
                (r"/", ChessBoardHandler, dict(theme=theme, shared=shared)),
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
                (r"/settings/save", SettingsSaveHandler),
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
        if self.side_running == ClockSide.LEFT:
            time_left = self.l_time - 1
            if time_left <= 0:
                logger.info("negative/zero time left: %s", time_left)
                self.virtual_timer.stop()
                time_left = 0
            self.l_time = time_left
        if self.side_running == ClockSide.RIGHT:
            time_right = self.r_time - 1
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
            else:
                text_r = "{}:{:02d}.{:02d}".format(l_hms[0], l_hms[1], l_hms[2])
                text_l = "{}:{:02d}.{:02d}".format(r_hms[0], r_hms[1], r_hms[2])
                icon_d = "fa-caret-right" if self.side_running == ClockSide.LEFT else "fa-caret-left"
            if self.side_running == ClockSide.NONE:
                icon_d = "fa-sort"
            text = text_l + '&nbsp;<i class="fa ' + icon_d + '"></i>&nbsp;' + text_r
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

        def _oldstyle_fen(game: chess.Board):
            builder = []
            builder.append(game.board_fen())
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
            if variant != "chess":
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
            }
            self.shared["analysis_state"] = analysis_payload
            self.shared["analysis_state_engine"] = analysis_payload
            EventHandler.write_to_clients({"event": "Analysis", "analysis": analysis_payload})

        def _transfer(game: chess.Board, keep_these_headers: dict = None):
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
            fen = message.game.fen()
            result = {
                "pgn": pgn_str,
                "fen": fen,
                "event": "Game",
                "move": "0000",
                "play": "newgame",
            }
            # Add variant info for 3check
            variant = self.shared.get("variant", "chess")
            if variant != "chess":
                result["variant"] = variant
            if variant == "3check":
                result["checks"] = self.shared.get("checks_remaining", {"white": 3, "black": 3})
            _attach_mistakes(result)
            self.shared["last_dgt_move_msg"] = result
            EventHandler.write_to_clients(result)
            if message.newgame:
                # issue #55 - dont reset headers if its not a real new game
                _build_headers()
                _send_headers()
                _send_title()

        elif isinstance(message, Message.IP_INFO):
            self.shared["ip_info"] = message.info

        elif isinstance(message, Message.SYSTEM_INFO):
            self._create_system_info()
            self.shared["system_info"].update(message.info)
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

        elif isinstance(message, Message.STARTUP_INFO):
            self.shared["game_info"] = message.info.copy()
            # change book_index to book_text
            books = message.info["books"]
            book_index = message.info["book_index"]
            if books and book_index is not None and 0 <= book_index < len(books):
                self.shared["game_info"]["book_text"] = books[book_index]["text"]
            else:
                self.shared["game_info"]["book_text"] = ""
            self.shared["game_info"].pop("book_index", None)  # safer to pop not del, but never used

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

        elif isinstance(message, Message.INTERACTION_MODE):
            self._create_game_info()
            self.shared["game_info"]["interaction_mode"] = message.mode
            _set_normal_pgn()

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
                _build_headers()
                _send_headers()

        elif isinstance(message, Message.TIME_CONTROL):
            self._create_game_info()
            self.shared["game_info"]["time_text"] = message.time_text
            self.shared["game_info"]["tc_init"] = message.tc_init

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

        elif isinstance(message, Message.DGT_NO_CLOCK_ERROR):
            # result = {'event': 'Status', 'msg': 'Error clock'}
            # EventHandler.write_to_clients(result)
            pass

        elif isinstance(message, Message.DGT_CLOCK_VERSION):
            if message.dev == "ser":
                attached = "serial"
            elif message.dev == "i2c":
                attached = "i2c-pi"
            else:
                attached = "server"
            result = {"event": "Status", "msg": "Ok clock " + attached}
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
                self.shared["last_dgt_move_msg"] = result  # not send => keep it for COMPUTER_MOVE_DONE

        elif isinstance(message, Message.COMPUTER_MOVE_DONE):
            WebDisplay.result_sav = ""
            result = self.shared["last_dgt_move_msg"]
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
            # dont rebuild headers here, use existing one

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
                await self.task(message)
                self.msg_queue.task_done()
                await asyncio.sleep(0.05)  # balancing message queues
        except asyncio.CancelledError:
            logger.debug("WebDisplay msg_queue cancelled")
