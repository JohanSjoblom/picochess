"""Analysis source-selection policy shared by the main loop and tests."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from dgt.util import Mode


WEB_ANALYSIS_MULTIPV = 3  # maximum backend analysis lines shown by the web client


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


@dataclass(frozen=True)
class GameEndAnalysisContext:
    """Inputs that determine whether a completed game stops deep analysis."""

    interaction_mode: Mode
    game_over: bool
    game_declared: bool
    game_ending: str | None


def decide_game_end_analysis_stop(context: GameEndAnalysisContext) -> bool:
    """Return whether this game-end state must stop playing-mode analysis."""
    if context.interaction_mode not in (Mode.NORMAL, Mode.BRAIN, Mode.TRAINING):
        return False
    return (
        bool(context.game_over)
        or bool(context.game_declared)
        or (context.game_ending or "*") != "*"
    )


class AnalysisCycleAction(Enum):
    """Control action taken before an analysis cycle reads engine output."""

    CONTINUE = "continue"
    RECONCILE_CHECKPOINT_RESTORE = "reconcile_checkpoint_restore"
    STOP_AFTER_GAME_END = "stop_after_game_end"


@dataclass(frozen=True)
class AnalysisCycleContext:
    """Inputs for the early-exit policy of an analysis cycle."""

    checkpoint_restore_pending: bool
    game_end_analysis_stopped: bool


def decide_analysis_cycle_action(context: AnalysisCycleContext) -> AnalysisCycleAction:
    """Select an early analysis action while preserving checkpoint precedence."""
    if context.checkpoint_restore_pending:
        return AnalysisCycleAction.RECONCILE_CHECKPOINT_RESTORE
    if context.game_end_analysis_stopped:
        return AnalysisCycleAction.STOP_AFTER_GAME_END
    return AnalysisCycleAction.CONTINUE


class AnalysisSourceAction(Enum):
    """Select which cached analyser output an analysis cycle should read."""

    TUTOR_PRIMARY = "tutor_primary"
    ENGINE_NON_PLAYING = "engine_non_playing"
    ENGINE_THINKING = "engine_thinking"
    TUTOR_WEB_ONLY = "tutor_web_only"
    ENGINE_CURRENT = "engine_current"
    NONE = "none"


@dataclass(frozen=True)
class AnalysisSourceContext:
    """Inputs for selecting an analysis source without performing side effects."""

    tutor_is_primary: bool
    engine_plays: bool
    pgn_mode: bool
    is_user_turn: bool
    engine_thinking: bool
    tutor_analyser_available: bool


def decide_analysis_source(context: AnalysisSourceContext) -> AnalysisSourceAction:
    """Mirror the existing analysis-source precedence used by ``analyse()``."""
    if context.tutor_is_primary:
        return AnalysisSourceAction.TUTOR_PRIMARY
    if not context.engine_plays and not context.pgn_mode:
        return AnalysisSourceAction.ENGINE_NON_PLAYING
    if context.pgn_mode:
        return AnalysisSourceAction.NONE
    if not context.is_user_turn and context.engine_thinking:
        return AnalysisSourceAction.ENGINE_THINKING
    if context.tutor_analyser_available:
        return AnalysisSourceAction.TUTOR_WEB_ONLY
    return AnalysisSourceAction.ENGINE_CURRENT


def should_stop_analysis_after_game_end(
    interaction_mode: Mode, game_over: bool, game_declared: bool, game_ending: str | None
) -> bool:
    """Compatibility wrapper for the explicit game-end analysis context."""
    return decide_game_end_analysis_stop(
        GameEndAnalysisContext(
            interaction_mode=interaction_mode,
            game_over=game_over,
            game_declared=game_declared,
            game_ending=game_ending,
        )
    )


def tutor_analysis_allowed_in_mode(interaction_mode: Mode) -> bool:
    """PONDER must always show analysis from the selected engine, never from tutor."""
    return interaction_mode != Mode.PONDER


@dataclass(frozen=True)
class TutorAnalysisContext:
    """Inputs that determine whether Tutor replaces selected-engine analysis."""

    interaction_mode: Mode
    pgn_mode: bool
    engine_should_skip_analyser: bool
    engine_is_playing: bool
    is_user_turn: bool


def decide_tutor_analysis(context: TutorAnalysisContext) -> bool:
    """Return whether Tutor should own deep analysis for this cycle."""
    if not tutor_analysis_allowed_in_mode(context.interaction_mode):
        return False
    if context.pgn_mode or context.engine_should_skip_analyser:
        return True
    # While an engine is playing, its PlayingContinuousAnalysis owns the engine
    # turn. On the user turn PicoTutor replaces selected-engine analysis.
    return not context.engine_is_playing or context.is_user_turn
