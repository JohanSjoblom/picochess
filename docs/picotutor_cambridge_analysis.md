# Analysis of the PicoTutor implementation of the Cambridge annotation model

This document analyses how the PicoTutor V3 and V4 evaluation algorithms relate
to the Cambridge *Computers and Chess Annotation* model. The original Cambridge
text, parameter comparison, interpretation notes, and V3 code extract are
preserved in [`picotutor_constants.xlsx`](picotutor_constants.xlsx).

PicoTutor V3 and V4 are inspired by the Cambridge model, but they implement a
simplified heuristic rather than the complete mathematical model.

## Cambridge variables and their PicoTutor equivalents

| Cambridge variable | Meaning | PicoTutor implementation |
| --- | --- | --- |
| Δ1 | Difference between the best move and selected move at minimum ply | Not calculated |
| Δ2 | Difference between the best move and selected move at maximum ply | `best_score - current_score` |
| ΔS | Change in the selected move's value between minimum and maximum ply | `current_score - low_score` |
| G1 | Evaluation gradient at minimum ply | Not calculated |
| G2 | Evaluation gradient at maximum ply | Approximated by `current_score - before_score` |
| K | Curvature of the evaluation as ply increases | Not calculated |

In PicoTutor:

- `best_score` is the score of the best move from the deep analysis.
- `current_score` is the deep-analysis score of the move selected by the user.
- `low_score` is the shallow-analysis score of that same move.
- `before_score` is the stored deep score from the previous evaluated move for
  the same side.

The mappings of Δ2 and ΔS are direct implementations of the Cambridge
definitions.

The mapping of `score_hist_diff` to G2 is only a PicoTutor heuristic.
Cambridge's G1 and G2 describe how the evaluation of the same candidate move
changes as search ply increases. `score_hist_diff` instead compares evaluations
from different positions and different moves in the game history. It may be
useful as a practical signal, but it is not formally the Cambridge G2 gradient.

## Bad moves: `?` and `??`

Cambridge describes a bad move as one for which both the shallow and deep
analyses consider the move substantially worse than the best alternative:

```text
Δ1 > threshold and Δ2 > threshold
```

The original V3 code explicitly showed the Δ1 condition commented out. Both
V3 and V4 therefore classify bad moves using only Δ2:

```python
best_deep_diff = best_score - current_score

if best_deep_diff > VERY_BAD_MOVE_TH:
    evaluation = "??"
elif best_deep_diff > BAD_MOVE_TH:
    evaluation = "?"
```

Consequences:

- The selected move must be available in the deep analysis to calculate an
  exact centipawn loss.
- Whether the move already appeared bad at shallow depth is not considered.
- The `??` classification does not explicitly test whether the move changed
  the position from winning to drawing or losing, despite this being part of
  the Cambridge descriptive definition.

This is an intentional V3 simplification retained by V4.

## Exceptional moves: `!` and `!!`

Cambridge describes an exceptional move as:

- Objectively good at maximum ply: small Δ2.
- Improving substantially as the search becomes deeper: positive ΔS.
- Not obvious at minimum ply: sufficiently large Δ1.
- Not becoming obviously good too early: an appropriate curvature K.

PicoTutor implements only the first two conditions.

For `!!`:

```python
best_deep_diff <= VERY_GOOD_MOVE_TH
and deep_low_diff > VERY_GOOD_IMPROVE_TH
```

For `!`:

```python
best_deep_diff <= GOOD_MOVE_TH
and deep_low_diff > GOOD_IMPROVE_TH
```

Therefore:

- A `!!` move must be the best deep move, or numerically tied with it.
- A `!` move must be close to the best deep move.
- The move must improve substantially between shallow and deep analysis.
- Δ1 is not calculated.
- Curvature K is not calculated.
- PicoTutor does not directly measure whether the move is much better than all
  other alternatives.

A large positive ΔS often indicates that the move was not obvious at shallow
depth, but ΔS is not equivalent to Δ1. The best shallow move's evaluation can
also change between the shallow and deep searches.

## Unclear moves: `!?` and `?!`

The Cambridge text describes unclear moves using:

- The initial gradient G1.
- Curvature K acting against that gradient.
- A relatively small absolute ΔS.

The text says that if ΔS is large, the move is better described as exceptional
or bad rather than unclear.

PicoTutor instead uses:

- Δ2.
- A large absolute ΔS.
- `score_hist_diff`, based on the previous evaluated move.

The current formulas are effectively:

```python
# ?!
best_deep_diff > DUBIOUS_TH
and abs(deep_low_diff) > UNCLEAR_DIFF
and score_hist_diff > POS_INCREASE
```

```python
# !?
best_deep_diff < INTERESTING_TH
and abs(deep_low_diff) > UNCLEAR_DIFF
and score_hist_diff < POS_DECREASE
```

This differs materially from the Cambridge description:

- PicoTutor requires a large absolute ΔS, while the Cambridge text says ΔS
  should remain relatively small.
- G1 and K are not available.
- The previous-move history difference substitutes for the missing gradient
  information.

Consequently, PicoTutor's `!?` and `?!` should be understood as V3-specific
pragmatic heuristics inspired by Cambridge, rather than direct implementations
of the Cambridge unclear-move model.

## V4 quality safeguards

The current V4 implementation adds data-quality checks around the inherited
evaluation formulas:

- Both the best deep line and selected user line must reach the minimum
  evaluation depth.
- If the selected move is absent from the deep MultiPV list, the evaluation is
  rejected because exact Δ2 and CPL are unavailable.
- If the selected move is absent only from the shallow list, exact deep `?` and
  `??` evaluations remain possible, but `!`, `!!`, `!?`, and `?!` are
  suppressed.
- `!?` and `?!` require a valid previous history score whose deep analysis also
  reached the minimum depth.

These checks improve confidence in the data without changing the underlying V3
classification formulas.

## Relevance to reducing MultiPV

The optimization is not intended to apply uniformly to every playing engine.
Retro/MAME emulation retains deep MultiPV 30 because its automatic-takeback
feature requires an immediate `??` before the move is sent to the engine. Other
engines may use an experimentally selected narrower deep search. MultiPV 3 is
an initial candidate, not a predetermined final value. When a non-retro engine
cannot provide compatible analysis, a user move outside the deep list may
simply have no delayed WATCHER or PGN blunder evaluation. See
[`picotutor_delayed_move_evaluation.md`](picotutor_delayed_move_evaluation.md)
for the capability policy and implementation order.

Reducing the deep MultiPV has different effects on the annotations:

- `!!` should normally remain available because the move must be the best deep
  move.
- `!` should usually remain available because the move must be close to the
  best, although positions with many nearly equal moves can produce safe false
  negatives.
- `!?` also requires the move to be close to the best and will often be
  present, subject to the same crowded-position limitation.
- `?!`, `?`, and `??` are more likely to disappear from a small deep MultiPV
  because inferior user moves will often be outside the returned lines.

Using a larger shallow MultiPV remains useful even when the deep MultiPV is
small:

- It increases the probability of obtaining an exact shallow score for the
  selected move.
- This preserves the exact ΔS calculation needed by `!` and `!!`.
- If a deep top move is absent from a complete shallow list, the final shallow
  line can provide a conservative upper bound for its shallow score. This can
  potentially prove a minimum ΔS without pretending that the exact shallow
  score is known.

For example, when testing shallow MultiPV 10 and the selected deep move is
absent from the complete shallow list:

```text
actual shallow score <= score of shallow line 10

minimum ΔS = selected deep score - score of shallow line 10
```

If this minimum already exceeds the `!` or `!!` threshold, the improvement
condition is safely satisfied. This boundary-based method is not yet part of
the current V4 implementation.

The final deep and shallow widths should be selected from measurements rather
than assumed. Useful deep candidates include 3, 5, 10, 15, and the current 30.
The shallow search can initially remain at 10 while deep widths are compared,
then wider shallow values can be tested because depth 5 is relatively quick.
Selection should consider depth-12/depth-17 attainment, user-move coverage,
annotation agreement, WATCHER coverage, and analysis time on target hardware.

## Conclusion

The core V3/V4 PicoTutor model can be summarized as:

- `?` and `??`: deep centipawn loss only.
- `!` and `!!`: deep quality plus improvement from shallow to deep.
- `!?` and `?!`: deep quality, shallow/deep volatility, and previous-move
  history.
- Δ1, true depth gradients, and curvature are not implemented.

The V3 code preserved in the spreadsheet confirms that these simplifications
originated in V3 and are not accidental V4 regressions. For the MultiPV
optimization, it is advisable to preserve these existing semantics first and
treat any closer implementation of Δ1, G1/G2, or K as a separate feature.
