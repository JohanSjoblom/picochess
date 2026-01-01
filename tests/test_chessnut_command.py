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

import binascii
import unittest

import eboard.chessnut.command as cmd


class TestCommand(unittest.TestCase):

    def test_set_led_off_regular_chessnut(self):
        arr = cmd.set_led_off_regular_chessnut()
        self.assertEqual(b"0a080000000000000000", binascii.hexlify(arr))

    def test_set_led_regular_chessnut(self):
        position = [[0 for _ in range(8)] for _ in range(8)]
        position[2][2] = 1
        arr = cmd.set_led_regular_chessnut(position, False)
        self.assertEqual(b"0a080000000000200000", binascii.hexlify(arr))

    def test_set_leds_e2_e4_regular_chessnut(self):
        position = [[0 for _ in range(8)] for _ in range(8)]
        position[1][4] = 1  # e2
        position[3][4] = 1  # e4
        arr = cmd.set_led_regular_chessnut(position, False)
        self.assertEqual(b"0a080000000008000800", binascii.hexlify(arr))

    def test_set_led_initial_position_reversed_regular_chessnut(self):
        position = [[0 for _ in range(8)] for _ in range(8)]
        position[2][2] = 1
        arr = cmd.set_led_regular_chessnut(position, True)
        self.assertEqual(b"0a080000040000000000", binascii.hexlify(arr))

    def test_set_led_off_chessnut_move(self):
        arr = cmd.set_led_off_chessnut_move()
        self.assertEqual(b"43200000000000000000000000000000000000000000000000000000000000000000",
                         binascii.hexlify(arr))

    def test_set_led_chessnut_move(self):
        position = [[0 for _ in range(8)] for _ in range(8)]
        position[2][2] = 1
        arr = cmd.set_led_chessnut_move(position, False)
        self.assertEqual(b"43200000000000000000000000000000000000000000000030000000000000000000",
                         binascii.hexlify(arr))

    def test_set_leds_e2_e4_chessnut_move(self):
        position = [[0 for _ in range(8)] for _ in range(8)]
        position[1][4] = 1  # e2
        position[3][4] = 1  # e4
        arr = cmd.set_led_chessnut_move(position, False)
        self.assertEqual(b"43200000000000000000000000000000000000300000000000000030000000000000",
                         binascii.hexlify(arr))

    def test_set_led_initial_position_reversed_chessnut_move(self):
        position = [[0 for _ in range(8)] for _ in range(8)]
        position[2][2] = 1
        arr = cmd.set_led_chessnut_move(position, True)
        self.assertEqual(b"43200000000000000000000300000000000000000000000000000000000000000000",
                         binascii.hexlify(arr))

    def test_send_auto_move_fen(self):
        arr = cmd.send_auto_move_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR", "e2e4")
        self.assertEqual(b"422158233185444444440000000000000000007000000000000077077777a6c99b6a00",
                         binascii.hexlify(arr))


if __name__ == "__main__":
    unittest.main()
