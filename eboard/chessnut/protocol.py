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
#
# Some code copied from https://github.com/domschl/python-mchess/blob/master/mchess/chess_link.py


import time
import logging
import threading
import queue
import json

from eboard.move_debouncer import MoveDebouncer
from eboard.ble_transport import Transport
from eboard.chessnut.parser import Parser, ParserCallback, Battery, BoardType
from eboard.chessnut import command

logger = logging.getLogger(__name__)
READ_CHARACTERISTIC = "1b7e8262-2877-41c3-b46e-cf057c562023"
WRITE_CHARACTERISTIC = "1b7e8272-2877-41c3-b46e-cf057c562023"


class Protocol(ParserCallback):
    """
    This implements the 'Chessnut' protocol for Chessnut e-boards.

    Communcation with the board is asynchronous. Replies from the board are written
    to the python queue (`appqueue`) that is provided during instantiation.

    Every message in `appqueue` is a short json string.
    """

    def __init__(self, appque, name):
        """
        :param appque: a Queue that receive chess board events
        :param name: identifies this protocol
        """
        super().__init__()
        self.name = name
        logger.debug("Chessnut starting")
        self.error_condition = False
        self.appque = appque
        self.board_mutex = threading.Lock()
        self.trque = queue.Queue()
        self.trans = None
        self.config = None
        self.connected = False
        self.last_fen = None
        self.parser = Parser(self)
        self.brd_reversed = False
        self.brd_type = None
        self.device_in_config = False
        self.debouncer = MoveDebouncer(
            350, lambda fen: self.appque.put({"cmd": "raw_board_position", "fen": fen, "actor": self.name})
        )

        self.thread_active = True
        self.event_thread = threading.Thread(target=self._event_worker_thread)
        self.event_thread.setDaemon(True)
        self.event_thread.start()

        self.config = None
        try:
            self._read_config()
        except Exception as e:
            logger.debug(f"No valid default configuration, starting board-scan: {e}")
        while True:
            if not self.device_in_config:
                self._search_board()

            if self.config is None or self.trans is None or "address" not in self.config:
                logger.error("Cannot connect.")
                if self.config is None:
                    self.config = {}
                    self.write_configuration()
                self.error_condition = True
            else:
                self._connect()

            if not self.error_condition:
                break
            self.device_in_config = False
            time.sleep(3)

    def _read_config(self):
        with open("chessnut_config.json", "r") as f:
            self.config = json.load(f)
            if "btle_iface" not in self.config:
                self.config["btle_iface"] = 0
                self.write_configuration()
            if "address" in self.config:
                logger.debug(f"Checking default configuration for board at {self.config['address']}")
                trans = self._open_transport()
                if trans is not None:
                    self.device_in_config = True
                    self.trans = trans

    def _search_board(self):
        try:
            tr = Transport(self.trque, READ_CHARACTERISTIC, WRITE_CHARACTERISTIC)
            logger.debug("created obj")
            if tr.is_init():
                logger.debug("Transport loaded.")
                if self.config is not None:
                    btle = self.config["btle_iface"]
                else:
                    btle = 0
                address = tr.search_board("Chessnut", btle)
                if address is not None:
                    logger.debug(f"Found board at address {address}")
                    self.config = {"address": address}
                    self.trans = tr
                    self.write_configuration()
            else:
                logger.warning("Bluetooth failed to initialize")
        except Exception as e:
            logger.warning(f"Internal error, import of Bluetooth failed: {e}")

    def _connect(self):
        address = self.config["address"]
        logger.debug(f"Valid board available at {address}")
        logger.debug(f"Connecting to Chessnut at {address}")
        self.connected = self.trans.open_mt(address)
        if self.connected:
            logger.info(f"Connected to Chessnut at {address}")
        else:
            self.trans.quit()
            logger.error(f"Connection to Chessnut at {address} FAILED.")
            self.config = {}
            self.write_configuration()
            self.error_condition = True

    def quit(self):
        """
        Quit Chessnut connection.
        Try to terminate transport threads gracefully.
        """
        if self.trans is not None:
            self.trans.quit()
        self.thread_active = False

    def position_initialized(self):
        """
        Check, if a board position has been received and the Chessnut board is online.

        :return: True, if board position has been received
        """
        if self.connected:
            with self.board_mutex:
                fen = self.last_fen
            if fen is not None:
                return True
        return False

    def write_configuration(self):
        """
        Write the configuration for Bluetooth LE to 'chessnut_config.json'.

        :return: True on success, False on error
        """
        if "btle_iface" not in self.config:
            self.config["btle_iface"] = 0
        try:
            with open("chessnut_config.json", "w") as f:
                json.dump(self.config, f, indent=4)
                return True
        except Exception as e:
            logger.error(f"Failed to save default configuration {self.config} to chessnut_config.json: {e}")
        return False

    def _event_worker_thread(self):
        """
        The event worker thread is automatically started during __init__.
        """
        logger.debug("Chessnut worker thread started.")
        while self.thread_active:
            if not self.trque.empty():
                msg = self.trque.get()
                token = "agent-state: "
                if msg[: len(token)] == token:
                    toks = msg[len(token):]
                    i = toks.find(" ")
                    if i != -1:
                        state = toks[:i]
                        emsg = toks[i + 1:]
                    else:
                        state = toks
                        emsg = ""
                    logger.info(f"Agent state of {self.name} changed to {state}, {emsg}")
                    if state == "offline":
                        self.error_condition = True
                    else:
                        self.error_condition = False
                    self.appque.put({"cmd": "agent_state", "state": state, "message": emsg})
                    continue

                self.parser.parse(msg)
            else:
                time.sleep(0.01)

    def board_update(self, short_fen: str):
        self.debouncer.update(short_fen)
        with self.board_mutex:
            self.last_fen = short_fen

    def battery(self, percent: int, status: Battery):
        msg = f"{status.name} {percent}"
        self.appque.put({"cmd": "battery", "message": msg})

    def reversed(self, value: bool):
        self.brd_reversed = value

    def board_type(self, btype: BoardType):
        if self.brd_type is None:
            self.brd_type = btype

    def set_led(self, pos):
        """
        Set LEDs according to `position`.

        :param pos: `position` array, field != 0 indicates a led that should be on
        """
        if self.connected:
            if self.brd_type == BoardType.CHESSNUT_REGULAR:
                cmd = command.set_led_regular_chessnut(pos, self.brd_reversed)
                self.trans.write_mt(cmd)
            elif self.brd_type == BoardType.CHESSNUT_MOVE:
                cmd = command.set_led_chessnut_move(pos, self.brd_reversed)
                self.trans.write_mt(cmd)

    def set_led_off(self):
        if self.connected:
            if self.brd_type == BoardType.CHESSNUT_REGULAR:
                self.trans.write_mt(command.set_led_off_regular_chessnut())
            elif self.brd_type == BoardType.CHESSNUT_MOVE:
                self.trans.write_mt(command.set_led_off_chessnut_move())

    def request_battery_status(self):
        if self.connected:
            if self.brd_type is None or self.brd_type == BoardType.CHESSNUT_REGULAR:
                self.trans.write_mt(command.request_battery_status())
            if self.brd_type is None or self.brd_type == BoardType.CHESSNUT_MOVE:
                self.trans.write_mt(command.request_battery_status_chessnut_move())

    def realtime_mode(self):
        if self.connected:
            self.trans.write_mt(command.request_realtime_mode())

    def _open_transport(self):
        tr = Transport(self.trque, READ_CHARACTERISTIC, WRITE_CHARACTERISTIC)
        if tr.is_init():
            return tr
        else:
            logger.warning("Bluetooth transport failed to initialize")
        return None

    def auto_move(self, uci_move: str):
        """
        Send a command to the Chessnut Move to move the pieces to the given position.
        """
        with self.board_mutex:
            fen = self.last_fen
        if fen is not None and self.connected and self.brd_type == BoardType.CHESSNUT_MOVE:
            self.trans.write_mt(command.send_auto_move_fen(fen, uci_move))
