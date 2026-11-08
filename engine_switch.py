"""Policy helpers for safe logical engine-profile and chess-variant switches."""

import hashlib
import json

import chess
import chess.variant


def profile_variant(profile: dict) -> str:
    """Return the profile's logical variant; ordinary engines are chess."""
    return str(profile.get("variant") or "chess")


def game_context_fields(state) -> dict:
    """Return only stable fields whose change invalidates a destructive-switch confirmation."""
    game = state.game
    root_fen = game.root().fen() if game is not None else ""
    current_fen = game.fen() if game is not None else ""
    moves = [move.uci() for move in game.move_stack] if game is not None else []
    loaded_pgn = str(getattr(state, "loaded_pgn_filename", "") or "")
    return {
        "variant": str(getattr(state, "variant", "chess") or "chess"),
        "root_fen": root_fen,
        "current_fen": current_fen,
        "moves": moves,
        "pending_engine_fen": getattr(state, "done_computer_fen", None),
        "loaded_pgn": loaded_pgn,
        "game_started": bool(getattr(state, "game_started", False)),
    }


def game_context_fingerprint(state) -> str:
    payload = json.dumps(game_context_fields(state), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_start_fen(variant: str) -> str:
    # PicoChess keeps its authoritative move list in a plain chess.Board and
    # maintains variant-board state alongside it. Racing Kings alone has a
    # different physical/logical starting placement.
    if variant == "racingkings":
        return chess.variant.RacingKingsBoard().fen()
    return chess.Board().fen()


def has_protected_game_context(state) -> bool:
    fields = game_context_fields(state)
    return bool(
        fields["game_started"]
        or fields["moves"]
        or fields["pending_engine_fen"]
        or fields["loaded_pgn"]
        or fields["root_fen"] != _canonical_start_fen(fields["variant"])
        or fields["current_fen"] != fields["root_fen"]
    )


def variant_switch_requires_confirmation(state, target_variant: str) -> bool:
    current_variant = str(getattr(state, "variant", "chess") or "chess")
    return current_variant != (target_variant or "chess") and has_protected_game_context(state)


def variant_switch_forbidden(state, target_variant: str) -> bool:
    """Protect externally authoritative games from local variant replacement."""
    current_variant = str(getattr(state, "variant", "chess") or "chess")
    if current_variant == (target_variant or "chess"):
        return False
    mode = getattr(state, "interaction_mode", None)
    mode_name = getattr(mode, "name", str(mode or "")).upper()
    return mode_name in {"OBSERVE", "REMOTE", "ENGINE_MATCH"}


def confirmation_matches(state, game_generation, fingerprint) -> bool:
    return (
        game_generation == getattr(state, "game_generation", 0)
        and fingerprint == game_context_fingerprint(state)
    )
