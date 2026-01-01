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

import chess

FEN_TO_CHESSNUT = {
    "p": 4, "r": 8, "n": 5, "b": 3, "q": 1, "k": 2,
    "P": 7, "R": 6, "N": 10, "B": 9, "Q": 11, "K": 12,
}


def set_led_regular_chessnut(pos, is_reversed: bool) -> bytes:
    """
    Set LEDs according to `position` on a regular Chessnut e-board.
    :param pos: `position` array, field != 0 indicates an LED that should be on
    :param is_reversed: whether the colors on the board are reversed
    """
    leds = bytearray(8)
    for y in range(8):
        for x in range(8):
            if pos[y][x] != 0:
                square = (7 - y) * 8 + x
                if is_reversed:
                    square = 63 - square
                _set_bit(leds, square, 1)

    prefix = bytearray(2)
    prefix[0] = 0x0A
    prefix[1] = 0x08
    return prefix + leds


def _set_bit(data: bytearray, pos: int, val: int):
    posByte = int(pos / 8)
    posBit = pos % 8
    oldByte = data[posByte]
    oldByte = ((0xFF7F >> posBit) & oldByte) & 0x00FF
    newByte = (val << (8 - (posBit + 1))) | oldByte
    data[posByte] = newByte


def set_led_off_regular_chessnut():
    return b"\x0a\x08\x00\x00\x00\x00\x00\x00\x00\x00"


def set_led_chessnut_move(pos, is_reversed: bool) -> bytes:
    """
    Set LEDs according to `position` on a Chessnut Move e-board.
    :param pos: `position` array, field != 0 indicates an LED that should be on
    :param is_reversed: whether the colors on the board are reversed
    """
    leds = bytearray(32)
    for y in range(8):
        for x in range(8):
            if pos[y][x] != 0:
                internal = y * 8 + x
                fen_index = internal if is_reversed else (63 - internal)
                _set_led_color(leds, fen_index, 3)  # 3 = blue LED

    prefix = bytearray(2)
    prefix[0] = 0x43
    prefix[1] = 0x20
    return prefix + leds


def set_led_off_chessnut_move() -> bytes:
    cmd = bytearray(34)
    cmd[0] = 0x43
    cmd[1] = 0x20
    return cmd


def _set_led_color(data: bytearray, fen_index: int, color_nibble: int):
    """
    Packs a 4‑bit color value into the correct nibble.
    """
    byte_index = fen_index // 2
    lower = (fen_index % 2 == 0)
    existing = data[byte_index]
    if lower:
        existing = (existing & 0xF0) | (color_nibble & 0x0F)
    else:
        existing = (existing & 0x0F) | ((color_nibble & 0x0F) << 4)
    data[byte_index] = existing


def request_realtime_mode() -> bytes:
    return b"\x21\x01\x00"


def request_battery_status() -> bytes:
    return b"\x29\x01\x00"


def request_battery_status_chessnut_move() -> bytes:
    return b"\x41\x01\x0c"


def _fen_to_board64(fen: str):
    """Convert piece-placement FEN to 64 nibbles in a1=0 order."""
    board = [0] * 64
    rows = fen.split("/")
    for fen_row_idx, row in enumerate(rows):
        rank = 8 - fen_row_idx
        base = (rank - 1) * 8
        file = 0
        for ch in row:
            if ch.isdigit():
                file += int(ch)
            else:
                board[base + file] = FEN_TO_CHESSNUT[ch]
                file += 1
    return board


def _encode_board(board64) -> bytes:
    out = bytearray(32)
    idx = 0
    for row in range(7, -1, -1):
        for col in range(3, -1, -1):
            hi = board64[idx]
            lo = board64[idx + 1]
            out[row * 4 + col] = (hi << 4) | lo
            idx += 2
    return out


def send_auto_move_fen(fen: str, uci_move: str) -> bytes:
    board = chess.Board(fen + " w KQkq - 0 1")
    move = chess.Move.from_uci(uci_move)
    if not board.is_legal(move):
        board = chess.Board(fen + " b KQkq - 0 1")
        if not board.is_legal(move):
            return bytearray(0)
    board.push(move)

    new_fen = board.board_fen()
    board64 = _fen_to_board64(new_fen)
    encoded = _encode_board(board64)

    cmd = bytearray(35)
    cmd[0] = 0x42
    cmd[1] = 0x21
    cmd[2:34] = encoded
    cmd[34] = 0  # force = true
    return cmd
