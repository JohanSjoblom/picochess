"""Selected-engine analysis limits shared by the main loop and its tests."""

from __future__ import annotations

import platform

from dgt.util import Mode


FLOAT_ENGINE_MAX_ANALYSIS_DEPTH = 40  # fallback cap for selected main-engine ContinuousAnalysis
AARCH64_NON_PLAYING_ENGINE_MAX_ANALYSIS_DEPTH = 30  # lower cap when no engine moves are being played
WEB_ANALYSIS_MULTIPV = 3  # maximum backend analysis lines shown by the web client


def selected_engine_analysis_depth(engine_plays: bool) -> int:
    """Return the selected main-engine ContinuousAnalysis depth limit."""
    if platform.machine().lower() == "aarch64" and not engine_plays:
        return AARCH64_NON_PLAYING_ENGINE_MAX_ANALYSIS_DEPTH
    return FLOAT_ENGINE_MAX_ANALYSIS_DEPTH


def selected_engine_analysis_multipv(interaction_mode: Mode, engine_options) -> int | None:
    """Return the supported MultiPV width for selected-engine analysis modes."""
    multipv_modes = (Mode.PONDER, Mode.ANALYSIS, Mode.KIBITZ, Mode.PGNREPLAY)
    if interaction_mode not in multipv_modes or not engine_options:
        return None
    multipv_option = engine_options.get("MultiPV")
    if multipv_option is None:
        return None
    minimum = getattr(multipv_option, "min", None)
    maximum = getattr(multipv_option, "max", None)
    if minimum is not None and minimum > WEB_ANALYSIS_MULTIPV:
        return None
    requested = WEB_ANALYSIS_MULTIPV if maximum is None else min(WEB_ANALYSIS_MULTIPV, maximum)
    return requested if requested > 1 else None
