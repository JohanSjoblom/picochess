"""Selected-engine depth caps and clock/DGT depth handover."""

from __future__ import annotations

import logging
import platform

import chess
from chess.engine import InfoDict

logger = logging.getLogger("picochess")


FLOAT_ENGINE_MAX_ANALYSIS_DEPTH = 40  # fallback cap for selected main-engine ContinuousAnalysis
AARCH64_NON_PLAYING_ENGINE_MAX_ANALYSIS_DEPTH = 30  # lower cap when no engine moves are being played



def selected_engine_analysis_depth(engine_plays: bool) -> int:
    """Return the selected main-engine ContinuousAnalysis depth limit."""
    if platform.machine().lower() == "aarch64" and not engine_plays:
        return AARCH64_NON_PLAYING_ENGINE_MAX_ANALYSIS_DEPTH
    return FLOAT_ENGINE_MAX_ANALYSIS_DEPTH


class BestSeenDepth:
    """a small utility class to help picochess remember last sent depth, bestmove info
    can at the moment only be used when getting analysis from playing engine
    it remembers the _last_seen_depth for _last_half_move_nr"""

    def __init__(self):
        self.last_seen_depth = 0  # last seen depth - info sent
        self.last_half_move_nr = 0  # nr of halfmoves done at depth
        self.ponder_move: chess.Move = chess.Move.null()

    def reset(self):
        """forget seen depth"""
        self.last_seen_depth = 0
        self.last_half_move_nr = 0
        self.ponder_move = chess.Move.null()

    def is_better(self, info: InfoDict | None, analysed_fen: str, game: chess.Board) -> bool:
        """Return True if a deeper depth was found for the analysed FEN (no state updates here).
        info         - InfoDict from engine analysis
        analysed_fen - the fen from which the info comes
        game         - current game board"""
        if not self.ponder_move:
            return True  # special case - without ponder_move we accept any info
        is_better = False
        curr_half_move_nr = len(game.move_stack)  # half_move dont work in library
        if info and analysed_fen == game.fen():
            if "depth" in info:
                # calc how much depth has been lost by comparing half-moves
                depth_diff = curr_half_move_nr - self.last_half_move_nr
                if depth_diff < 0:
                    logger.debug("best depth out of sync - resetting it")
                    self.reset()  # throw away the worthless values
                    is_better = True  # whatever caller sent is better than "future" depth values
                elif info.get("depth") > self.last_seen_depth - depth_diff:
                    is_better = True  # caller has a better depth than our old
        return is_better

    def set_best(self, info: InfoDict | None, analysed_fen: str, game: chess.Board, ponder_move: chess.Move) -> None:
        """Use this when you send the latest info - being sent means it's the latest seen.
        if ponder_move is None or chess.Move.null() it's ok to call, but it will never be is_better"""
        curr_half_move_nr = len(game.move_stack)  # half_move dont work in library
        if info and analysed_fen == game.fen():
            if "depth" in info:
                self.last_seen_depth = info.get("depth")
                self.last_half_move_nr = curr_half_move_nr
                # best sent ponder_move - sama as plus-button
                # if this ponder_move is missing is_better has to return True otherwise we
                # would not get a ponder move until new depth has reached old depth
                self.ponder_move = ponder_move if ponder_move else chess.Move.null()


def depth_gated_analysis_info(
    best_seen_depth: BestSeenDepth,
    info_list: list[InfoDict] | None,
    analysed_fen: str,
    game: chess.Board,
) -> list[InfoDict] | None:
    """Return clock analysis only when it passes the existing depth gate."""
    info_candidate = info_list[0] if info_list else None
    if best_seen_depth.is_better(info_candidate, analysed_fen, game):
        return info_list
    return None
