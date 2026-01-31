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
ThreeCheckBoard wrapper for 3check chess variant.

This module provides a wrapper around chess.Board that tracks check counts
for the 3check variant. In 3check, a player wins by giving check three times.

The wrapper maintains:
- Remaining checks needed for each side (starts at 3)
- History of checks for proper takeback support
- Both standard FEN (for opening books) and extended FEN (for Fairy-Stockfish)
"""

from __future__ import annotations

import chess
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ThreeCheckBoard:
    """
    Wrapper for chess.Board that tracks 3check variant state.

    This class wraps a standard chess.Board and adds:
    - Check counting for both sides
    - Check history for takeback support
    - Extended FEN format for Fairy-Stockfish communication
    - Standard FEN for opening book lookups
    """

    def __init__(self, fen: Optional[str] = None):
        """
        Initialize a ThreeCheckBoard.

        Args:
            fen: Optional FEN string. Can be standard FEN or extended 3check FEN.
                 Extended format: "pieces turn castling ep checks halfmove fullmove"
                 where checks is "white_remaining+black_remaining" (e.g., "3+3")
        """
        self._board = chess.Board()
        # Remaining checks needed to win: 3 = need 3 more checks, 0 = won
        self.checks_remaining = {chess.WHITE: 3, chess.BLACK: 3}
        # History stack for takebacks: [(move, was_check, side_that_was_checked), ...]
        self._check_history: list[tuple[chess.Move, bool, Optional[chess.Color]]] = []

        if fen:
            self.set_fen(fen)

    def set_fen(self, fen: str) -> None:
        """
        Set position from FEN string.

        Accepts both standard FEN and extended 3check FEN format.

        Args:
            fen: FEN string (standard 6-field or extended 7-field 3check format)
        """
        parts = fen.split()

        if len(parts) == 7:
            # Extended 3check FEN: pieces turn castling ep checks halfmove fullmove
            standard_fen = f"{parts[0]} {parts[1]} {parts[2]} {parts[3]} {parts[5]} {parts[6]}"
            check_field = parts[4]  # e.g., "3+3" or "2+3"
            self._parse_check_field(check_field)
            self._board.set_fen(standard_fen)
        elif len(parts) == 6:
            # Standard FEN
            self._board.set_fen(fen)
            self.checks_remaining = {chess.WHITE: 3, chess.BLACK: 3}
        else:
            # Try to parse anyway
            self._board.set_fen(fen)
            self.checks_remaining = {chess.WHITE: 3, chess.BLACK: 3}

        # Clear history when setting new position
        self._check_history = []

    def _parse_check_field(self, check_field: str) -> None:
        """
        Parse the check counting field from 3check FEN.

        Format: "white_remaining+black_remaining" (e.g., "3+3", "2+3", "1+0")
        """
        try:
            parts = check_field.split("+")
            if len(parts) == 2:
                self.checks_remaining[chess.WHITE] = int(parts[0])
                self.checks_remaining[chess.BLACK] = int(parts[1])
            else:
                logger.warning("Invalid check field format: %s, using defaults", check_field)
                self.checks_remaining = {chess.WHITE: 3, chess.BLACK: 3}
        except ValueError:
            logger.warning("Could not parse check field: %s, using defaults", check_field)
            self.checks_remaining = {chess.WHITE: 3, chess.BLACK: 3}

    def standard_fen(self) -> str:
        """
        Return standard FEN without check counts.

        Use this for opening book lookups, which expect standard chess FEN.

        Returns:
            Standard 6-field FEN string
        """
        return self._board.fen()

    def extended_fen(self) -> str:
        """
        Return 3check extended FEN with check counts.

        Use this for communication with Fairy-Stockfish engine.

        Format: "pieces turn castling ep checks halfmove fullmove"
        where checks is "white_remaining+black_remaining"

        Returns:
            Extended 7-field FEN string
        """
        parts = self._board.fen().split()
        check_field = f"{self.checks_remaining[chess.WHITE]}+{self.checks_remaining[chess.BLACK]}"
        return f"{parts[0]} {parts[1]} {parts[2]} {parts[3]} {check_field} {parts[4]} {parts[5]}"

    def fen(self) -> str:
        """
        Return FEN string.

        For compatibility, returns extended FEN. Use standard_fen() for book lookups.

        Returns:
            Extended 7-field FEN string
        """
        return self.extended_fen()

    def board_fen(self) -> str:
        """
        Return only the piece placement part of FEN.

        Used for e-board comparison (e-boards only report piece positions).

        Returns:
            Piece placement string (first field of FEN)
        """
        return self._board.board_fen()

    def push(self, move: chess.Move) -> None:
        """
        Push a move and update check counts.

        Records whether the move gave check and which side was checked,
        for proper restoration during takeback.

        Args:
            move: The move to push
        """
        self._board.push(move)

        was_check = self._board.is_check()
        side_checked: Optional[chess.Color] = None

        if was_check:
            # The side now to move is the side that was checked
            side_checked = self._board.turn
            self.checks_remaining[side_checked] = max(0, self.checks_remaining[side_checked] - 1)
            logger.debug(
                "Check given to %s, remaining: %d",
                "white" if side_checked == chess.WHITE else "black",
                self.checks_remaining[side_checked],
            )

        self._check_history.append((move, was_check, side_checked))

    def pop(self) -> chess.Move:
        """
        Pop a move and restore check counts.

        Automatically restores the check count that was decremented when
        the move was pushed.

        Returns:
            The popped move

        Raises:
            IndexError: If there are no moves to pop
        """
        if not self._check_history:
            raise IndexError("pop from empty move stack")

        move, was_check, side_checked = self._check_history.pop()

        if was_check and side_checked is not None:
            self.checks_remaining[side_checked] = min(3, self.checks_remaining[side_checked] + 1)
            logger.debug(
                "Takeback restored check for %s, remaining: %d",
                "white" if side_checked == chess.WHITE else "black",
                self.checks_remaining[side_checked],
            )

        return self._board.pop()

    def is_variant_end(self) -> bool:
        """
        Check if the game ended due to 3check rule.

        Returns:
            True if either side has received 3 checks
        """
        return self.checks_remaining[chess.WHITE] == 0 or self.checks_remaining[chess.BLACK] == 0

    def variant_winner(self) -> Optional[chess.Color]:
        """
        Return the winner by 3check rule.

        Returns:
            chess.WHITE if white gave 3 checks to black,
            chess.BLACK if black gave 3 checks to white,
            None if game not ended by 3check
        """
        if self.checks_remaining[chess.WHITE] == 0:
            return chess.BLACK  # Black gave 3 checks to white
        if self.checks_remaining[chess.BLACK] == 0:
            return chess.WHITE  # White gave 3 checks to black
        return None

    def is_game_over(self) -> bool:
        """
        Check if game is over (including 3check condition).

        Returns:
            True if game ended by checkmate, stalemate, draw rules, or 3check
        """
        return self.is_variant_end() or self._board.is_game_over()

    def copy(self) -> "ThreeCheckBoard":
        """
        Create a copy of this board.

        Returns:
            A new ThreeCheckBoard with the same state
        """
        new_board = ThreeCheckBoard()
        new_board._board = self._board.copy()
        new_board.checks_remaining = self.checks_remaining.copy()
        new_board._check_history = self._check_history.copy()
        return new_board

    def reset(self) -> None:
        """Reset to starting position with fresh check counts."""
        self._board.reset()
        self.checks_remaining = {chess.WHITE: 3, chess.BLACK: 3}
        self._check_history = []

    def __getattr__(self, name: str):
        """
        Delegate unknown attributes to the underlying chess.Board.

        This allows ThreeCheckBoard to be used as a drop-in replacement
        for chess.Board in most contexts.

        Args:
            name: Attribute name

        Returns:
            The attribute from the underlying chess.Board
        """
        return getattr(self._board, name)

    def __repr__(self) -> str:
        """Return string representation."""
        return f"ThreeCheckBoard('{self.extended_fen()}')"
