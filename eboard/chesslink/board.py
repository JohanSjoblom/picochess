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

import logging
import queue
import asyncio
from typing import Dict, Optional

from eboard.eboard import EBoard
from utilities import DisplayMsg
from dgt.api import Message, Dgt
from dgt.util import ClockIcons

from eboard.chesslink.chess_link_agent import ChessLinkAgent


logger = logging.getLogger(__name__)


class ChessLinkBoard(EBoard):
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.agent = None
        self.appque: queue.Queue[Dict[str, Optional[str]]] = queue.Queue()
        self.connected = False
        self.loop = loop
        self.waitchars = ["/", "-", "\\", "|"]
        self.wait_counter = 0
        self.reconnect_task: asyncio.Task | None = None
        self.reconnect_delay = 1.0
        self.process_task: asyncio.Task | None = None

    def light_squares_on_revelation(self, uci_move: str):
        logger.debug("turn LEDs on - move: %s", uci_move)
        dpos = [[0 for x in range(8)] for y in range(8)]
        dpos[int(uci_move[1]) - 1][ord(uci_move[0]) - ord("a")] = 1  # from
        dpos[int(uci_move[3]) - 1][ord(uci_move[2]) - ord("a")] = 1  # to
        if self.agent is not None:
            self.agent.set_led(dpos)

    def light_square_on_revelation(self, square: str):
        logger.debug("turn on LEDs - square: %s", square)
        dpos = [[0 for x in range(8)] for y in range(8)]
        dpos[int(square[1]) - 1][ord(square[0]) - ord("a")] = 1
        if self.agent is not None:
            self.agent.set_led(dpos)

    def clear_light_on_revelation(self):
        logger.debug("turn LEDs off")
        if self.agent is not None:
            self.agent.set_led_off()

    async def _process_incoming_board_forever(self):
        result = {}
        bwait = self.waitchars[self.wait_counter]
        while "cmd" not in result or (result["cmd"] == "agent_state" and result["state"] == "offline"):
            try:
                result = self.appque.get(block=False)
            except queue.Empty:
                pass
            bwait = self.waitchars[self.wait_counter]
            text = self._display_text("no ChessLink e-Board" + bwait, "ChessLink" + bwait, "ChesLnk" + bwait, bwait)
            await DisplayMsg.show(Message.DGT_NO_EBOARD_ERROR(text=text))
            self.wait_counter = (self.wait_counter + 1) % len(self.waitchars)
            await asyncio.sleep(1.0)

        if result["state"] != "offline":
            logger.info("incoming_board ready")
            self.connected = True

        while True:
            if self.agent is not None:
                try:
                    result = self.appque.get(block=False)
                    if "cmd" in result and result["cmd"] == "agent_state" and "state" in result and "message" in result:
                        if result["state"] == "offline":
                            self.connected = False
                            text = self._display_text(result["message"], result["message"], "no/", bwait)
                            if self.reconnect_task is None or self.reconnect_task.done():
                                self.reconnect_task = self.loop.create_task(self._reconnect())
                        else:
                            self.connected = True
                            text = Dgt.DISPLAY_TIME(force=True, wait=True, devs={"ser", "i2c", "web"})
                            # successful online state cancels any reconnect backoff
                            self.reconnect_delay = 1.0
                        await DisplayMsg.show(Message.DGT_NO_EBOARD_ERROR(text=text))
                    elif "cmd" in result and result["cmd"] == "raw_board_position" and "fen" in result:
                        fen = result["fen"].split(" ")[0]
                        await DisplayMsg.show(Message.DGT_FEN(fen=fen, raw=True))
                except queue.Empty:
                    pass
            await asyncio.sleep(0.05)

    async def _connect(self):
        logger.info("connecting to board")
        try:
            self.agent = await asyncio.to_thread(ChessLinkAgent, self.appque)
        except Exception as exc:
            logger.warning("ChessLink connect failed: %s", exc)
            self.agent = None
            self.connected = False
            return
        # mark connected if agent reports success
        if getattr(self.agent, "cl_brd", None) is not None and getattr(self.agent.cl_brd, "connected", False):
            self.connected = True

    def set_text_rp(self, text: bytes, beep: int):
        return True

    def _display_text(self, web, large, medium, small):
        return Dgt.DISPLAY_TEXT(
            web_text=web,
            large_text=large,
            medium_text=medium,
            small_text=small,
            wait=True,
            beep=False,
            maxtime=0.1,
            devs={"i2c", "web"},
        )

    def run(self):
        if self.process_task is None or self.process_task.done():
            self.process_task = self.loop.create_task(self._process_incoming_board_forever())
        self.loop.create_task(self._initial_connect())

    async def _initial_connect(self):
        await self._connect()
        if not self.connected:
            if self.reconnect_task is None or self.reconnect_task.done():
                self.reconnect_task = self.loop.create_task(self._reconnect())

    async def _reconnect(self):
        """Attempt to reconnect with simple backoff and emit spinner while offline."""
        self.connected = False
        while not self.connected:
            if self.agent is not None:
                try:
                    self.agent.quit()
                except Exception:
                    logger.debug("error while quitting ChessLink agent during reconnect", exc_info=True)
                self.agent = None

            # drain stale queue messages
            try:
                while True:
                    self.appque.get_nowait()
            except queue.Empty:
                pass

            # show spinner while attempting
            bwait = self.waitchars[self.wait_counter]
            self.wait_counter = (self.wait_counter + 1) % len(self.waitchars)
            text = self._display_text("no ChessLink e-Board" + bwait, "ChessLink" + bwait, "ChesLnk" + bwait, bwait)
            await DisplayMsg.show(Message.DGT_NO_EBOARD_ERROR(text=text))

            try:
                await self._connect()
            except Exception as exc:
                logger.warning("ChessLink reconnect attempt failed: %s", exc)

            if self.connected:
                self.reconnect_delay = 1.0
                await DisplayMsg.show(Dgt.DISPLAY_TIME(force=True, wait=True, devs={"ser", "i2c", "web"}))
                return

            await asyncio.sleep(self.reconnect_delay)
            self.reconnect_delay = min(self.reconnect_delay * 2, 10.0)

    def set_text_xl(self, text: str, beep: int, left_icons=ClockIcons.NONE, right_icons=ClockIcons.NONE):
        pass

    def set_text_3k(self, text: bytes, beep: int):
        pass

    def set_and_run(self, lr: int, lh: int, lm: int, ls: int, rr: int, rh: int, rm: int, rs: int):
        pass

    def end_text(self):
        pass

    def promotion_done(self, uci_move: str):
        pass

    def is_connected(self) -> bool:
        return self.connected
