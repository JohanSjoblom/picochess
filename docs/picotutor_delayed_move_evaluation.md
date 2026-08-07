# PicoTutor delayed move evaluation and engines without analysis

## Purpose

The planned PicoTutor optimization reduces the deep Tutor MultiPV from 30
lines to approximately 3 while retaining a wider shallow/obvious search, such
as MultiPV 10 at depth 5. The first priority is to preserve the Cambridge-style
`!` and `!!` evaluations while allowing the deep search to reach a useful depth
more quickly.

Reducing the deep list creates a separate problem for `?` and `??`. A bad user
move will commonly be outside the deep top three, so its score and exact
centipawn loss will not be available when the move is played. This document
describes a future position-pair evaluation mechanism and the retained-wide-
search policy for engines that cannot support delayed evaluation safely.

The accepted scope deliberately excludes synchronous post-move Tutor analysis
for retro engines. Retro/MAME engines, engines configured with
`Analysis=false`, and other engines for which Picochess skips continuous
analysis retain the current wide deep Tutor search and immediate evaluation.

This design complements
[`picotutor_cambridge_analysis.md`](picotutor_cambridge_analysis.md).

## Position-pair move evaluation

Instead of running a wide root-move analysis merely to find the move that was
played, Picochess can derive its value from engine evaluations of the positions
before and after the move.

For every analysed position, store the `MultiPV == 1` score and its depth. The
score must be normalized with `PovScore` to White's point of view:

- Positive scores favour White.
- Negative scores favour Black.
- The meaning of the score is independent of whose turn it is.

For ordinary centipawn scores, calculate the loss as follows:

```python
if mover == chess.WHITE:
    raw_cpl = score_before - score_after
else:
    raw_cpl = score_after - score_before

cpl = max(0, raw_cpl)
evaluation_depth = min(depth_before, depth_after)
```

The unclamped `raw_cpl` should be retained in debug logging. A negative value
can occur when the later search discovers something that the earlier search
missed.

Only a pair whose two evaluations reach the configured minimum depth should be
used. The resulting depth is the lower of the before and after depths, providing
a simple indication of the reliability of the comparison.

Mate scores must be stored and compared separately. They must not be converted
to a large artificial centipawn value for the position-pair calculation.

## Required source consistency

The before and after evaluations must come from the same engine and a
compatible configuration. A Tutor score before the move must not be compared
with a playing-engine score after the move.

Each stored position evaluation should identify at least:

- Exact analysed FEN.
- Engine or analysis-source identity.
- Relevant engine configuration identity.
- Search depth.
- Centipawn score or mate score.
- MultiPV line number.
- Whether the score is exact, a lower bound, or an upper bound.

Bounded UCI scores, stale-position results, and mixed score types must not be
used for an ordinary CPL calculation.

The resulting move evaluation should also retain:

- Ply number and played move.
- Side that moved.
- Before FEN and after FEN.
- Effective evaluation depth.
- Evaluation source and whether the result was immediate or delayed.

This prevents repetitions, transpositions, takebacks, and stale asynchronous
results from attaching an evaluation to the wrong move.

## Engine capability cases

Different playing engines provide different opportunities for obtaining the
after-position score.

| Playing engine | Possible score after the user move | Intended handling |
| --- | --- | --- |
| Analysis-capable UCI engine | Playing-engine `MultiPV == 1` analysis | Reuse it when a compatible before-position score exists from the same engine |
| LC0 or an engine with incomplete PV sequences | A top-line score and depth may still be available | A complete PV is unnecessary; score, depth, source, and correct FEN are sufficient |
| Engine configured with `Analysis=false` | Continuous analysis is deliberately unavailable | Retain deep Tutor MultiPV 30 and immediate evaluation |
| Retro/MAME engine | Usually no dependable score and no safe engine takeback | Retain deep Tutor MultiPV 30 and immediate pre-send `??` evaluation |
| Script or other engine for which Picochess skips its analyser | A compatible before-position score is not assured | Retain deep Tutor MultiPV 30 and immediate evaluation |

Selection must be based on existing engine capability policy and available
data, not only on engine names.

## The retro-engine timing constraint

Retro/MAME engines have special existing behaviour. When PicoTutor immediately
assigns `??`, Picochess does not send the user move to the retro engine. It asks
the user to take back the move instead. This is necessary because these engines
cannot reliably take back a move after it has been submitted.

A delayed `??` that arrives after the retro engine has started thinking is too
late for this protection. It could still be written to WATCHER or the PGN, but
it could not safely trigger the existing automatic-takeback path.

Therefore, retro engines require a pre-send decision. When the deep top-three
Tutor search would often omit the selected move. The chosen policy avoids that
problem by not applying the narrow deep search to retro play. Retro engines
retain deep MultiPV 30, so their existing immediate evaluation and automatic-
takeback control flow remain unchanged.

## Retained-wide-search policy

The optimization applies only when the selected playing engine can support the
analysis data needed for delayed position-pair evaluation. Picochess, rather
than PicoTutor, owns that engine capability decision.

Conceptually, the runtime policy is:

```python
use_wide_tutor = (
    emulation_mode
    or engine.should_skip_engine_analyser()
)

if use_wide_tutor:
    deep_root_moves = 30
else:
    deep_root_moves = 3

shallow_root_moves = 10
```

`should_skip_engine_analyser()` currently includes MAME engines, script
wrappers, and engines whose configuration specifies `Analysis=false`. The
explicit emulation check also preserves the existing broader MAME/MESS
detection used by Picochess.

Keeping script engines on the wide policy is conservative. Picochess already
avoids using their continuous analyser, so a compatible same-source before
score is not assured even if their playing search later emits information.

The shallow MultiPV may still be reduced to 10 for both policies. Immediate
`?` and `??` use the exact deep user-line CPL, not the shallow score. The
shallow-boundary design separately preserves `!` and `!!` when the selected
deep move is outside the shallow top ten.

This policy intentionally does not attempt to optimize engines that cannot
support delayed evaluation. They retain current coverage and behaviour at the
cost of the existing wider Tutor workload.

## Out-of-scope retro fallback

A synchronous post-move Tutor MultiPV-1 check could theoretically preserve
retro automatic takeback while using a narrow pre-move search. It would,
however, add a new pre-engine control phase, clock and timeout policy,
asynchronous cancellation, and engine/Tutor lifecycle transitions.

That fallback is explicitly out of scope. This feature must not:

- Delay a retro engine while running new post-move deep Tutor analysis.
- Start Tutor deep analysis concurrently with the playing engine.
- Send a move to a retro engine and later attempt automatic takeback because a
  delayed `??` arrived.
- Change the existing retro engine move-submission or clock sequence.

## Mate transitions

Mate cases should be supported before reducing the deep MultiPV, because they
include some of the most important `??` moves. At minimum, the future policy
must distinguish:

- A move that allows the opponent a forced mate.
- A move that changes a winning or drawable position into a forced loss.
- A move that loses a forced mate for the mover.
- Two evaluations that both contain mate scores but differ in mate ownership
  or distance.

Mate ownership and distance must be compared directly. Mate values must not be
mixed into the ordinary CPL threshold calculation.

## Capability-based routing rule

The intended high-level routing is:

```text
engine is retro/MAME or Picochess skips its analyser
    -> retain deep MultiPV 30 and immediate evaluation

engine supports compatible before/after analysis scores
    -> use deep MultiPV 3 and derive delayed move evaluation when needed

compatible position pair reaches the minimum depth
    -> update WATCHER and stored PGN evaluation

no reliable compatible pair
    -> leave the delayed move unrated
```

## Testing and implementation order

The deep MultiPV should remain at 30 until the fallback mechanism has been
validated. This keeps the existing WATCHER list useful while the new mechanism
is developed.

Recommended order:

1. Preserve and test `!` and `!!` handling, including the intended shallow
   MultiPV 10 boundary logic, without reducing the deep MultiPV.
2. Collect position-pair evaluations in shadow mode while the current exact
   root-line CPL remains authoritative.
3. Compare the proposed CPL and NAG with the current result, including cases
   around the `?` and `??` thresholds.
4. Implement and test mate-transition handling.
5. Enable delayed position-pair evaluation for analysis-capable engines while
   deep MultiPV is still 30.
6. Add the runtime wide-versus-optimized policy and verify that retro/MAME,
   `Analysis=false`, and analyser-skipped script engines remain on deep
   MultiPV 30.
7. Reduce the deep Tutor MultiPV to 3 only for analysis-capable engines after
   WATCHER, PGN persistence, takebacks, stale-result rejection, and source
   matching have been validated.

Shadow-mode logging should include:

- Existing root-line CPL and proposed position-pair CPL.
- Absolute difference and threshold-crossing disagreements.
- Existing and proposed NAG.
- Before, after, and effective depths.
- Source identities and score types.
- Time taken to produce the after-position score.
- Rejection reasons.

Regression testing for the retained-wide policy must confirm:

- A retro `??` is still known before the move would be sent to the engine.
- Retro automatic takeback is unchanged.
- `Analysis=false` and analyser-skipped script engines still receive immediate
  wide-list evaluation.
- No delayed result can trigger retro automatic takeback.
- Switching between optimized and retained-wide engines updates the Tutor
  policy before analysis starts for the new engine.

## Conclusion

Position-pair evaluation can restore `?` and `??` coverage after reducing the
deep Tutor MultiPV, without separately analysing every possible root move. The
central requirement is source-consistent before and after scores.

The optimization is limited to engines that can provide the compatible analysis
needed for delayed evaluation. Retro/MAME, `Analysis=false`, and other
analyser-skipped engines retain deep MultiPV 30 and the existing immediate
evaluation path. No synchronous retro fallback is planned. This keeps delayed
evaluation in the annotation path and prevents the optimization from changing
retro engine control flow.
