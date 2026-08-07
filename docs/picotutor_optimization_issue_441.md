# Plan: Optimize PicoTutor MultiPV Analysis

Issue: [#441 - Optimize the speed of PicoTutor by reducing the number of
MultiPV analysis lines](https://github.com/JohanSjoblom/picochess/issues/441)

**Status:** Analysis completed; implementation deferred because validation and
calibration would require substantial testing. This document preserves the
proposed approach for possible future work.

## Context

PicoTutor currently requests 30 deep and 30 shallow MultiPV lines. A wide
depth-17 search can be interrupted before reaching the minimum trustworthy
evaluation depth, especially when the user moves quickly on Raspberry Pi
hardware.

The initial experimental candidates are:

- Deep/best Tutor analysis: values such as MultiPV 3, 5, 10, and 15, compared
  with the current 30 baseline.
- Shallow/obvious Tutor analysis: begin with MultiPV 10 at depth 5, then test
  wider values if their cost remains small.
- Minimum authoritative evaluation depth: 12 for the relevant deep lines.

MultiPV 3 is not the target by itself. The target is the smallest measured deep
width that materially improves depth attainment without an unacceptable loss
of move coverage or annotation agreement. The shallow width should favor exact
obvious-move coverage while remaining fast enough not to starve deep analysis.

The first priority is to preserve Cambridge-style `!` and `!!` evaluations.
Reducing the deep list makes immediate `?` and `??` less available because a
bad user move will commonly be outside the selected narrow list. When
compatible position scores exist, delayed position-pair evaluation should later
restore WATCHER and PGN blunder coverage. For non-retro engines without usable
analysis, a missing delayed blunder entry is an accepted limitation.

The design background is documented in:

- [`docs/picotutor_cambridge_analysis.md`](picotutor_cambridge_analysis.md)
- [`docs/picotutor_delayed_move_evaluation.md`](picotutor_delayed_move_evaluation.md)
- [`docs/picotutor_constants.xlsx`](picotutor_constants.xlsx)

## Scope and policy boundary

The narrow deep search applies to every non-retro engine. Delayed scoring is
used only when compatible position evaluations are available.

Retain deep MultiPV 30 and immediate evaluation when:

- Picochess is in retro/MAME emulation mode.

Conceptually:

```python
use_wide_tutor = emulation_mode

deep_root_moves = 30 if use_wide_tutor else selected_deep_root_moves
shallow_root_moves = selected_shallow_root_moves
```

`picochess.py` owns this policy. PicoTutor should receive the chosen runtime
width rather than infer the playing-engine type itself. Before an engine is
ready or its emulation state is known, default to the safe wide policy.

`should_skip_engine_analyser()` and actual score availability determine whether
delayed position-pair evaluation is possible; they do not determine Tutor
width. A non-retro `Analysis=false` or analyser-skipped script engine still uses
the selected narrow deep width. If its user move is outside that list and no
compatible score pair exists, WATCHER and PGN simply receive no delayed blunder
evaluation.

## Explicitly out of scope

- Synchronous post-user-move Tutor analysis before starting a retro engine.
- Delaying or changing retro engine move submission or clock handling.
- Allowing a delayed `??` to trigger retro automatic takeback.
- Optimizing retro/MAME emulation.
- Running the deep Tutor concurrently with a thinking engine.
- A full reimplementation of Cambridge Δ1, G1, G2, or curvature K.
- Redesigning the meanings of `!?` and `?!`.
- Showing unrated or low-quality entries in WATCHER.

## Architecture constraints

- Preserve the shared `asyncio` architecture; do not add threads or blocking
  waits.
- Preserve the one-deep-analyser-at-a-time CPU policy.
- Keep engine capability and analysis routing decisions in `picochess.py`.
- Keep Tutor analysis state, histories, and persisted move evaluations in
  `PicoTutor`.
- Preserve color-keyed Tutor state.
- Use immutable snapshots for delayed evaluation; never retain mutable
  references into an analyser's live cache.
- Reject stale results by FEN, ply, move, source, and analysis generation.
- Failure or insufficient depth must leave the move unrated and allow normal
  play to continue.

## Implementation steps

### 1. Establish baseline logging and tests

Before changing MultiPV widths, add or confirm logging for:

- Requested and returned deep and shallow line counts.
- Depth of each returned line.
- Whether the user move was found in each list and at which rank.
- Immediate evaluation result and rejection reason.
- Effective depth of the best and selected deep lines.

Add baseline tests around the current exact evaluation paths so later changes
can distinguish intended coverage changes from regressions.

Acceptance checks:

- Logging is diagnostic only and does not alter evaluation or engine routing.
- Existing focused and full unit tests pass with deep and shallow MultiPV still
  at 30.

### 2. Add a runtime Tutor width policy

Allow PicoTutor's requested deep and shallow root-move counts to be selected at
runtime rather than read only from global constants.

Requirements:

- `picochess.py` selects wide or optimized policy from current emulation mode.
- Retro/MAME emulation selects deep 30.
- Every non-retro engine may eventually select the measured compromise width.
- Shallow analysis initially selects 10 under both policies, with wider values
  retained as experimental candidates.
- Engine changes update the policy before Tutor analysis restarts.
- New games, mode changes, Tutor toggles, and position resets preserve the
  selected policy.
- The initial implementation may keep deep 30 for both branches until delayed
  evaluation has been validated.

Acceptance checks:

- A pure policy test proves that MAME/MESS emulation remains wide while normal,
  `Analysis=false`, and script engines select the narrow policy.
- Switching between wide and optimized engines cannot leave a previous
  MultiPV setting active.
- The policy change does not start a second deep analyser.

### 3. Preserve `!` and `!!` with a configurable shallow width

Keep the current exact calculation when the selected deep move is also present
in the shallow list:

```text
ΔS = selected deep score - selected shallow score
```

When the selected move is present in the deep list but absent from a complete
shallow list of the requested width, use the final shallow boundary score as an
upper bound on the selected move's shallow score:

```text
actual shallow score <= shallow boundary score

minimum ΔS = selected deep score - shallow boundary score
```

The boundary may prove the `!` or `!!` improvement threshold conservatively.
It must not be presented or stored as an exact ΔS.

Boundary evidence is valid only when:

- The requested shallow list is complete for the number of legal moves.
- The boundary line has a valid exact score.
- The boundary line reached `LOW_DEPTH`.
- The selected deep line and best deep line meet the minimum deep depth.

If those conditions are not satisfied, suppress the positive annotation.

Keep approximated `!?` and `?!` suppressed. Exact legacy classifications may
remain when all their required data is present, but redesigning them is outside
this issue.

Acceptance checks:

- Existing exact `!` and `!!` cases remain unchanged.
- A missing shallow user line can produce `!` or `!!` only when the conservative
  lower bound crosses the corresponding threshold.
- A partial or shallow boundary cannot produce a positive annotation.
- Stored/debug data distinguishes exact ΔS from a lower bound.
- Mate and only-legal-move guards remain effective.

Initially perform this work while the deep MultiPV remains 30.

### 4. Capture position scores in shadow mode

For each usable analysis snapshot, capture the `MultiPV == 1` score normalized
to White's point of view, together with:

- Analysed FEN.
- Source/engine identity and relevant configuration identity.
- Depth.
- Centipawn score or mate score.
- Exact, lower-bound, or upper-bound status.
- Analysis generation.

Only exact scores are candidates for ordinary position-pair CPL. Keep mate
scores separate.

Associate pending move evaluations with:

- Ply number and move.
- Moving color.
- Before and after FEN.
- Before and after source.

Shadow mode calculates and logs a proposed result but must not change WATCHER,
speech, PGN persistence, automatic takeback, or engine control.

Acceptance checks:

- Scores are correctly normalized to White regardless of side to move.
- Live analyser cache updates cannot mutate stored snapshots.
- Takeback, new game, engine switch, position reset, and Tutor disable cancel or
  invalidate pending pairs.
- Stale, mixed-source, bounded, or insufficient-depth pairs are rejected.

### 5. Compare shadow CPL with current root-line CPL

For positions where both methods are available, compare:

```python
if mover == chess.WHITE:
    raw_cpl = score_before - score_after
else:
    raw_cpl = score_after - score_before

cpl = max(0, raw_cpl)
evaluation_depth = min(depth_before, depth_after)
```

Log:

- Current exact root-line CPL.
- Proposed position-pair CPL and unclamped delta.
- Absolute difference.
- Current and proposed `?`/`??` result.
- Threshold-crossing disagreements around 150 and 250 CPL.
- Before, after, and effective depths.
- Source identities and rejection reasons.

Acceptance gate:

- Disagreements are understood and sufficiently rare/stable at the selected
  minimum depth.
- The result is not enabled merely because the formula works in unit tests;
  representative engine and hardware logs must support it.

### 6. Define and test mate transitions

Do not convert mate scores to artificial centipawn values for position-pair
subtraction.

At minimum distinguish:

- A move that allows the opponent a forced mate.
- A move that turns a winning or drawable position into a forced loss.
- A move that loses a forced mate for the mover.
- Mate-to-mate changes in owner or distance.

Acceptance checks:

- Ordinary CPL code never receives mate values.
- Mate ownership is evaluated from White-normalized scores and the moving
  color.
- Important forced-mate blunders are not silently lost when delayed evaluation
  is enabled.

### 7. Enable delayed WATCHER and PGN fallback

For any non-retro engine, use a valid position pair when one is available and
the existing immediate deep list did not contain the user move.

Rules:

- An existing authoritative immediate evaluation wins; do not duplicate or
  overwrite it with a delayed fallback.
- Require both positions to meet the minimum depth.
- Store the lower position depth as the move's evaluation depth.
- Add or update the correct move in WATCHER without creating a duplicate.
- Persist the result in `PicoTutor.evaluated_moves` so WATCHER and saved PGN
  consume the same evaluation.
- A delayed result is annotation only. It must not trigger retro automatic
  takeback or otherwise alter engine control.
- If no reliable pair becomes available, leave the move unrated.

Acceptance checks:

- Delayed `?` and `??` attach to the correct historical user move.
- Fast moves, engine completion, and later analysis cannot attach the result to
  a subsequent ply.
- Takeback removes or invalidates the applicable pending/stored result.
- WATCHER and PGN agree.
- Normal play and clocks continue when delayed evaluation fails.

Enable this while deep MultiPV is still 30 so it can be compared with the
existing immediate result before the optimization is activated.

### 8. Select and activate the compromise widths

After shadow comparison and delayed fallback pass their acceptance gates:

- Compare deep candidates such as 3, 5, 10, and 15 against the current 30
  baseline while initially holding shallow MultiPV at 10.
- Measure time and frequency to reach depths 12 and 17, user-move hit rate,
  effective line depths, annotation agreement, WATCHER coverage, CPU time, and
  interruption rate under realistic move timing.
- Select the non-retro deep compromise from those results rather than assuming
  that 3 is optimal.
- After narrowing the useful deep range, compare shallow candidates such as 10,
  20, and the current 30.
- Select the shallow width that improves exact ΔS coverage without materially
  delaying or starving the deep search.
- Keep deep MultiPV 30 only for retro/MAME emulation.
- Preserve the current minimum-depth gate for relevant deep lines.

Acceptance checks:

- `!` and `!!` remain available through exact or conservative shallow evidence.
- Immediate `?` and `??` remain available when the selected move happens to be
  in the selected deep list.
- Missing deep user moves may receive delayed `?`/`??` only through a validated
  compatible position pair.
- Retro/MAME engines retain immediate evaluation and existing automatic-
  takeback behaviour.
- A non-retro engine without compatible analysis may omit delayed blunder
  entries without affecting normal play.
- The optimized search reaches the minimum depth more often on target
  hardware.

## Regression matrix

Automated tests should cover:

- White and Black position-pair CPL orientation.
- Negative raw CPL clamping and logging.
- Effective depth selection.
- Exact versus bounded scores.
- Source mismatch and stale FEN/generation rejection.
- Deep and shallow user-move hit/miss combinations.
- Complete and incomplete shallow boundaries.
- `!`, `!!`, `?`, `??`, mate, and no-annotation cases.
- Takeback, repeated positions, new game, engine switch, and mode switch.
- Delayed WATCHER insertion without duplicates.
- PGN persistence consistency.
- Retro-wide/non-retro-selected-width policy transitions.
- Candidate-width measurements and selection logic.

Manual or integration testing should include:

- A normal analysis-capable UCI engine.
- LC0 or another engine whose PV output may be incomplete while a score is
  still available.
- An engine configured with `Analysis=false`.
- A script engine covered by `should_skip_engine_analyser()`.
- A retro/MAME engine with an immediate `??` automatic-takeback case.
- Fast user moves that interrupt deep analysis near the minimum depth.
- Engine book moves and very short engine searches.
- Physical e-board and web/no-e-board input where applicable.

Run focused tests during development and the full suite before each activation
step:

```text
venv/bin/python -m unittest tests.test_picotutor
venv/bin/python -m unittest tests.test_picochess_analysis_routing
venv/bin/tox -e unit
```

## Commit and activation strategy

Keep the work in reviewable, reversible commits:

1. Baseline logging and tests.
2. Runtime width policy, still selecting deep 30 everywhere.
3. Initial shallow MultiPV 10 and configurable conservative `!`/`!!` boundary
   support.
4. Passive position-score snapshots and shadow comparison.
5. Mate-transition support.
6. Delayed WATCHER/PGN fallback when compatible position pairs exist.
7. Measured selection and activation of the non-retro deep and shallow widths.

Do not combine the final width reduction with the initial state-tracking work.
The branch should always have a commit to which testing can return while deep
MultiPV 30 remains authoritative.

## Risk

Overall risk is **medium** under the accepted scope.

The `!`/`!!` and MultiPV-width work is primarily Tutor-evaluation behaviour.
Delayed WATCHER/PGN evaluation adds asynchronous state and therefore requires
careful stale-result and takeback handling. However, the branch explicitly
avoids the highest-risk change: delayed evaluation does not control whether a
move is sent to a retro engine.

Risk boundaries:

- A delayed-evaluation failure may omit or misclassify Tutor information, but
  must not stop normal play.
- Retro/MAME engine control flow must remain unchanged.
- Analysis-disabled and analyser-skipped non-retro engines may lose blunder
  annotations, but their normal play and clock flow must remain unchanged.
- No new concurrent deep analyser is permitted.
- Failure and timeout paths must degrade to an unrated move.

## Completion criteria

The feature is complete when:

- All non-retro engines use the experimentally selected deep and shallow
  compromise widths.
- Retro/MAME emulation retains deep MultiPV 30 and immediate evaluation.
- `!` and `!!` are preserved with exact or conservative shallow evidence.
- Delayed `?` and `??` restore WATCHER and PGN coverage when a validated
  position pair is available.
- Non-retro engines without compatible analysis fail safely with no delayed
  blunder entry.
- Mate transitions are handled without artificial CPL arithmetic.
- Retro automatic takeback and engine submission are unchanged.
- Target-hardware logs demonstrate improved deep-analysis depth or time and
  justify the selected widths against the tested alternatives.
- Focused and full unit suites pass.
