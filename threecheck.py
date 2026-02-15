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

"""
ThreeCheckBoard compatibility wrapper for 3check chess variant.

This module provides a compatibility wrapper around chess.variant.ThreeCheckBoard
that maintains the same API as the original custom implementation.

The wrapper uses python-chess's built-in 3check support while providing the same
interface that PicoChess expects.
"""

from __future__ import annotations

import chess
import chess.variant
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ThreeCheckBoard:
    """
    Compatibility wrapper for chess.variant.ThreeCheckBoard.

    This class wraps chess.variant.ThreeCheckBoard and provides the same API
    as the original custom implementation for backward compatibility.
    """

    # Required by python-chess engine._position() which does type(board).uci_variant
    uci_variant = "3check"
    # Needed for python-chess engine._position() chess960 check
    chess960 = False

    def __init__(self, fen: Optional[str] = None):
        """
        Initialize a ThreeCheckBoard.

        Args:
            fen: Optional FEN string. Can be standard FEN or extended 3check FEN.
                 Extended format: "pieces turn castling ep checks halfmove fullmove"
                 where checks is "white_remaining+black_remaining" (e.g., "3+3")
        """
        if fen:
            self._board = chess.variant.ThreeCheckBoard(fen)
        else:
            self._board = chess.variant.ThreeCheckBoard()

    def set_fen(self, fen: str) -> None:
        """
        Set position from FEN string.

        Accepts both standard FEN and extended 3check FEN format.

        Args:
            fen: FEN string (standard 6-field or extended 7-field 3check format)
        """
        self._board.set_fen(fen)

    @property
    def checks_remaining(self):
        """Get remaining checks as dictionary for backward compatibility."""
        return {chess.WHITE: self._board.remaining_checks[0], chess.BLACK: self._board.remaining_checks[1]}

    @checks_remaining.setter
    def checks_remaining(self, value):
        """Set remaining checks from dictionary."""
        self._board.remaining_checks[0] = value.get(chess.WHITE, 3)
        self._board.remaining_checks[1] = value.get(chess.BLACK, 3)

    def standard_fen(self) -> str:
        """
        Return standard FEN without check counts.

        Use this for opening book lookups, which expect standard chess FEN.

        Returns:
            Standard 6-field FEN string
        """
        parts = self._board.fen().split()
        # Return standard 6-field FEN: pieces turn castling ep halfmove fullmove
        return f"{parts[0]} {parts[1]} {parts[2]} {parts[3]} {parts[5]} {parts[6]}"

    def extended_fen(self) -> str:
        """
        Return 3check extended FEN with check counts.

        Use this for communication with Fairy-Stockfish engine.

        Returns:
            Extended 7-field FEN string
        """
        return self._board.fen()

    def fen(self, *, shredder=False, en_passant='legal', promoted=None) -> str:
        """
        Return FEN string.

        For compatibility, returns extended FEN.

        Args:
            shredder: Use Shredder-FEN format for castling rights
            en_passant: How to handle en passant squares
            promoted: How to handle promoted pieces

        Returns:
            Extended 7-field FEN string
        """
        return self._board.fen(shredder=shredder, en_passant=en_passant, promoted=promoted)

    def board_fen(self, *, promoted=False) -> str:
        """
        Return only the piece placement part of FEN.

        Used for e-board comparison (e-boards only report piece positions).

        Args:
            promoted: Whether to include promoted piece information

        Returns:
            Piece placement string (first field of FEN)
        """
        return self._board.board_fen(promoted=promoted)

    def push(self, move: chess.Move) -> None:
        """
        Push a move and update check counts.

        Args:
            move: The move to push
        """
        self._board.push(move)

    def pop(self) -> chess.Move:
        """
        Pop a move and restore check counts.

        Returns:
            The popped move
        """
        return self._board.pop()

    def is_variant_end(self) -> bool:
        """
        Check if the game ended due to 3check rule.

        Returns:
            True if either side has received 3 checks
        """
        return self._board.is_variant_end()

    def variant_winner(self) -> Optional[chess.Color]:
        """
        Return the winner by 3check rule.

        Returns:
            chess.WHITE if white gave 3 checks to black,
            chess.BLACK if black gave 3 checks to white,
            None if game not ended by 3check
        """
        if self._board.remaining_checks[chess.WHITE] == 0:
            return chess.BLACK  # Black gave 3 checks to white
        if self._board.remaining_checks[chess.BLACK] == 0:
            return chess.WHITE  # White gave 3 checks to black
        return None

    def is_game_over(self) -> bool:
        """
        Check if game is over (including 3check condition).

        Returns:
            True if game ended by checkmate, stalemate, draw rules, or 3check
        """
        return self._board.is_game_over()

    def copy(self, *, stack=True) -> "ThreeCheckBoard":
        """
        Create a copy of this board.

        Args:
            stack: Whether to copy the move stack. Defaults to True.

        Returns:
            A new ThreeCheckBoard with the same state
        """
        new_wrapper = ThreeCheckBoard()
        new_wrapper._board = self._board.copy(stack=stack)
        return new_wrapper

    def reset(self) -> None:
        """Reset to starting position with fresh check counts."""
        self._board.reset()

    def __getattr__(self, name: str):
        """
        Delegate unknown attributes to the underlying chess.variant.ThreeCheckBoard.

        This allows ThreeCheckBoard to be used as a drop-in replacement
        for the original implementation.

        Args:
            name: Attribute name

        Returns:
            The attribute from the underlying board
        """
        return getattr(self._board, name)

    def __repr__(self) -> str:
        """Return string representation."""
        return f"ThreeCheckBoard('{self.extended_fen()}')"
