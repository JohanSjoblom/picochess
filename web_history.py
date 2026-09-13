"""Server-owned presentation history; never replaces an engine or Tutor board."""

import copy
import io
import uuid

import chess
import chess.pgn


def history_scope(shared):
    if "web_history_scope" not in shared:
        shared["web_history_scope"] = {"gameid": uuid.uuid4().hex, "revision": 0}
    return shared["web_history_scope"]


def reset_history(shared):
    shared.pop("preserved_mame_history", None)
    shared["web_history_scope"] = {"gameid": uuid.uuid4().hex, "revision": 0}


def read_game(text):
    if not text or len(text) > 200000:
        raise ValueError("Missing or oversized history")
    game = chess.pgn.read_game(io.StringIO(text))
    if game is None or game.errors:
        raise ValueError("Invalid history")
    return game


def same_position(first, second):
    return type(first) is type(second) and first.chess960 == second.chess960 and first.fen() == second.fen()


def compose(shared, live):
    """Return a fresh PGN tree, keeping all input trees and headers untouched."""
    snapshot = shared.get("preserved_mame_history")
    if not snapshot or snapshot.get("scope") != history_scope(shared):
        return live
    prefix = read_game(snapshot["pgn"])
    anchor = prefix.end()
    if not same_position(anchor.board(), live.board()):
        return live
    # The prefix is already truncated at the selected node. Attach the entire
    # live tree (including Tutor sidelines) once, rather than appending updates.
    combined = prefix
    target = combined.end()
    target.comment = live.comment or target.comment
    # Copy the live tree once: deepcopy of each child separately also follows
    # its parent links and would copy the whole tree for every variation.
    for child in copy.deepcopy(live).variations:
        child.parent = target
        target.variations.append(child)
    root_headers = {key: combined.headers[key] for key in ("FEN", "SetUp", "Variant") if key in combined.headers}
    combined.headers.update(live.headers)
    for key in ("FEN", "SetUp", "Variant"):
        combined.headers.pop(key, None)
    combined.headers.update(root_headers)
    if not same_position(combined.end().board(), live.end().board()):
        raise ValueError("Combined history does not reach the live position")
    return combined


def preserve(shared, text, selected_fen, reason):
    source = read_game(text)
    # Read Game can include moves beyond PicoStop. Keep only the selected prefix.
    selected = None
    selected_board = chess.Board(selected_fen)
    for node in [source, *source.mainline()]:
        if node.board().fen() == selected_board.fen():
            selected = node
            break
    if selected is None:
        raise ValueError("History does not contain the selected root")
    selected.variations = []
    if reason == "engine_recovery":
        source = compose(shared, source)
    scope = dict(history_scope(shared))
    scope["revision"] += 1
    shared["web_history_scope"] = scope
    snapshot = {
        "pgn": str(source), "fen": selected_fen, "reason": reason, "scope": dict(scope),
    }
    shared["preserved_mame_history"] = snapshot
    return snapshot


def project_message(shared, message):
    """Build browser output from a raw cached backend message, never mutate it."""
    info = shared.get("system_info") or {}
    caps = info.get("mame_capabilities") or {}
    if (message.get("event") not in ("Game", "Fen") or not message.get("pgn")
            or not info.get("is_mame") or not caps.get("position") or caps.get("edit")
            or not shared.get("preserved_mame_history")
            or message.get("history_scope") != history_scope(shared)):
        return message
    try:
        live = read_game(message["pgn"])
        if live.end().board().fen() != chess.Board(message["fen"]).fen():
            return message
        combined = compose(shared, live)
        if combined is live:
            return message
        result = dict(message)
        result["pgn"] = str(combined)
        result["history_merged"] = True
        # Tutor halfmoves are board.ply(), whereas browser nodes are relative
        # to their root. Carry an explicit target to avoid guessing an offset.
        root_ply = combined.board().ply()
        result["mistakes"] = []
        last_index = combined.end().ply() - root_ply
        for item in message.get("mistakes", []):
            item = dict(item)
            if item.get("halfmove"):
                target = item.get("target_halfmove", item["halfmove"] - 1 if item["halfmove"] > 2 else item["halfmove"])
                # Read Game review points already use the original PGN's
                # relative indexes. Only Tutor's absolute plies need rebasing.
                if item.get("reason") != "variation":
                    target -= root_ply
                if target < 1 or target > last_index:
                    continue
                item["target_halfmove"] = target
            result["mistakes"].append(item)
        return result
    except (ValueError, TypeError, KeyError, IndexError):
        return message
