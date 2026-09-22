"""Board-position comparisons and stack-preserving move previews."""

from __future__ import annotations

import chess


def compare_fen(fen_board_external="", fen_board_internal="", board_type: type = None) -> str:
    # <Piece Placement> ::= <rank8>'/'<rank7>'/'<rank6>'/'<rank5>'/'<rank4>'/'<rank3>'/'<rank2>'/'<rank1>
    # <ranki>       ::= [<digit17>]<piece> {[<digit17>]<piece>} [<digit17>] | '8'
    # <piece>       ::= <white Piece> | <black Piece>
    # <digit17>     ::= '1' | '2' | '3' | '4' | '5' | '6' | '7'
    # <white Piece> ::= 'P' | 'N' | 'B' | 'R' | 'Q' | 'K'
    # <black Piece> ::= 'p' | 'n' | 'b' | 'r' | 'q' | 'k'
    # eg. starting position 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR'
    #                       'a8 b8 c8 d8... / a7 b7... / a1 b1 c1 ... h1'
    #
    # board_type: Optional board class (e.g., chess.Board, chess.variant.AtomicBoard).
    #             If None, defaults to chess.Board.

    if fen_board_external == fen_board_internal or fen_board_external == "" or fen_board_internal == "":
        return ""

    if board_type is None:
        board_type = chess.Board

    internal_board = board_type()
    internal_board.set_board_fen(fen_board_internal)

    external_board = board_type()
    external_board.set_board_fen(fen_board_external)

    # now compare each square and return first difference
    # and return first all fields to be cleared and then
    # all fields where to put new/different pieces on
    # start first with all squares to be cleared
    put_field = ""
    for square_no in range(0, 64):
        if internal_board.piece_at(square_no) != external_board.piece_at(square_no):
            if internal_board.piece_at(square_no) is None:
                return str("clear " + chess.square_name(square_no))
            else:
                put_field = str("put " + str(internal_board.piece_at(square_no)) + " " + chess.square_name(square_no))
    return put_field


def compute_legal_fens(game: chess.Board, variant_board=None):
    """
    Compute a list of legal FENs for the given game.

    :param game: The game (standard chess.Board)
    :param variant_board: Optional variant-specific board (e.g., AtomicBoard) for legal move generation
    :return: A list of legal FENs
    """
    # Legal FEN generation needs only the current position. Work on a stackless
    # snapshot so callers retain both their board state and complete move history.
    source_board = variant_board if variant_board is not None else game
    board = source_board.copy(stack=False)
    fens = []
    for move in board.legal_moves:
        board.push(move)
        fens.append(board.board_fen())
        board.pop()
    return fens


def board_fen_after_move(board: chess.Board, move: chess.Move) -> str:
    """Return the piece placement after a move without copying move history."""
    preview = board.copy(stack=False)
    preview.push(move)
    return preview.board_fen()


def previous_position_matching_board_fen(
    game: chess.Board, board_fen: str
) -> chess.Board | None:
    """Return the nearest earlier game position with the requested piece placement."""
    previous = game.copy(stack=True)
    while previous.move_stack:
        previous.pop()
        if previous.board_fen() == board_fen:
            return previous
    return None


def boards_match_position_and_history(first: chess.Board, second: chess.Board) -> bool:
    """Return whether two boards have the same position and recorded move stack."""
    return first.fen() == second.fen() and tuple(first.move_stack) == tuple(second.move_stack)
