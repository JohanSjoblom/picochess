# Copyright (C) 2013-2014 Jean-Francois Romang (jromang@posteo.de)
#                         Shivkumar Shivaji ()
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

import logging
import chess
from dgtinterface import *
# from dgti2c import *
from dgtpiboard import *
from dgtpiclock import *
from utilities import *


class DGTPi(DGTInterface):
    def __init__(self, device, enable_board_leds, disable_dgt_clock_beep):
        super(DGTPi, self).__init__(enable_board_leds, disable_dgt_clock_beep)
        # self.dgti2c = DGTi2c(device)
        # self.dgti2c.run()
        self.dgtclock = DGTpiclock()
        self.dgtclock.run()
        self.dgtboard = DGTpiboard(device)
        self.dgtboard.run(self.dgtclock.lib)

    def _display_on_dgt_3000(self, text, beep=False, duration=0, force=False):
        if len(text) > 11:
            logging.warning('DGT 3000 clock message too long [%s]', text)
        logging.debug(text)
        text = bytes(text, 'utf-8')
        # self.dgti2c.write(text, beep, duration, force)
        self.dgtclock.write(text, beep, duration, force)

    def display_text_on_clock(self, text, dgt_xl_text=None, beep=BeepLevel.CONFIG, duration=0, force=False):
        beep = self.get_beep_level(beep)
        self._display_on_dgt_3000(text, beep, duration, force)

    def display_move_on_clock(self, move, fen, beep=BeepLevel.CONFIG, duration=0, force=False):
        beep = self.get_beep_level(beep)
        bit_board = chess.Board(fen)
        text = bit_board.san(move)
        self._display_on_dgt_3000(text, beep, duration, force)

    def light_squares_revelation_board(self, squares):
        pass

    def clear_light_revelation_board(self):
        pass

    def stop_clock(self):
        # self.dgti2c.write_stop_to_clock(self.time_left, self.time_right)
        self.dgtclock.write_stop_to_clock(self.time_left, self.time_right)

    def start_clock(self, time_left, time_right, side):
        l_hms = hours_minutes_seconds(time_left)
        r_hms = hours_minutes_seconds(time_right)
        self.time_left = l_hms
        self.time_right = r_hms
        # self.dgti2c.write_start_to_clock(l_hms, r_hms, side)
        self.dgtclock.write_start_to_clock(l_hms, r_hms, side)

    def serialnr_board(self):
        self.dgtboard.write_to_board([DgtCmd.DGT_RETURN_SERIALNR])