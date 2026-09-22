"""Convert cached analysis into localized web payloads."""

from __future__ import annotations

from dataclasses import dataclass

import chess
from chess.engine import InfoDict

from analysis_policy import WEB_ANALYSIS_MULTIPV
from picotutor import PicoTutor


@dataclass(frozen=True)
class WebAnalysisSnapshot:
    """Keep cached web analysis together with the position it describes."""

    info: list[InfoDict] | None
    fen: str


WEB_SAN_PIECE_TRANSLATIONS = {
    "de": str.maketrans({"R": "T", "N": "S", "B": "L", "Q": "D"}),
    "nl": str.maketrans({"R": "T", "N": "P", "B": "L", "Q": "D"}),
    "fr": str.maketrans({"R": "T", "N": "C", "B": "F", "Q": "D", "K": "R"}),
    "es": str.maketrans({"R": "T", "N": "C", "B": "A", "Q": "D", "K": "R"}),
    "it": str.maketrans({"R": "T", "N": "C", "B": "A", "Q": "D", "K": "R"}),
}


def localize_web_san(san: str, language: str) -> str:
    """Translate SAN piece letters using the existing DGT language conventions."""
    translation = WEB_SAN_PIECE_TRANSLATIONS.get((language or "en").lower())
    return san.translate(translation) if translation is not None else san


def _web_analysis_pv(
    info: InfoDict,
    analysed_fen: str,
    move: chess.Move | None,
    language: str = "en",
) -> list[str]:
    """Convert one cached engine PV to SAN, with UCI as a defensive fallback."""
    pv_moves = list(info.get("pv") or [])
    pv_to_send = []
    if pv_moves and analysed_fen:
        try:
            san_board = chess.Board(analysed_fen)
            for pv_move in pv_moves:
                if not pv_move or pv_move == chess.Move.null():
                    break
                try:
                    pv_to_send.append(localize_web_san(san_board.san(pv_move), language))
                    san_board.push(pv_move)
                except (ValueError, AssertionError):
                    break
        except Exception:
            pass
    if not pv_to_send:
        pv_to_send = [pv_move.uci() for pv_move in pv_moves if pv_move and pv_move != chess.Move.null()]
    if not pv_to_send and move and move != chess.Move.null():
        try:
            pv_to_send = [localize_web_san(chess.Board(analysed_fen).san(move), language)]
        except Exception:
            pv_to_send = [move.uci()]
    return pv_to_send


def web_analysis_payload(
    info_list: list[InfoDict],
    analysed_fen: str,
    source: str,
    suppress_engine_line: bool = False,
    language: str = "en",
) -> dict | None:
    """Build up to three web lines while retaining PV1 compatibility fields."""
    limited_info = (info_list or [])[:WEB_ANALYSIS_MULTIPV]
    if not limited_info:
        return None
    lines = []
    for index, info in enumerate(limited_info, start=1):
        if not info:
            if index == 1:
                return None
            continue
        move, score, mate = PicoTutor.get_score(info)
        if score is None and not mate:
            if index == 1:
                return None
            continue
        lines.append(
            {
                "multipv": info.get("multipv", index),
                "depth": info.get("depth"),
                "score": score,
                "mate": mate,
                "pv": _web_analysis_pv(info, analysed_fen, move, language),
            }
        )
    if not lines:
        return None
    first_line = lines[0]
    return {
        "depth": first_line["depth"],
        "score": first_line["score"],
        "mate": first_line["mate"],
        "pv": first_line["pv"],
        "fen": analysed_fen,
        "source": source,
        "suppress_engine_line": suppress_engine_line,
        "lines": lines,
    }
