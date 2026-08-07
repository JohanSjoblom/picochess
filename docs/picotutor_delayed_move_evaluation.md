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
describes a future position-pair evaluation mechanism and, in particular, the
special handling required for engines that do not provide analysis.

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
| Engine configured with `Analysis=false` | Final play information may contain a score, but continuous analysis is unavailable | Use it only when a compatible same-source before score exists; otherwise use a Tutor fallback |
| Retro/MAME engine | Usually no dependable score and no safe engine takeback | Resolve a possible `??` before sending the move to the engine |

Selection must be based on actual engine capabilities and available data, not
only on engine names.

## The retro-engine timing constraint

Retro/MAME engines have special existing behaviour. When PicoTutor immediately
assigns `??`, Picochess does not send the user move to the retro engine. It asks
the user to take back the move instead. This is necessary because these engines
cannot reliably take back a move after it has been submitted.

A delayed `??` that arrives after the retro engine has started thinking is too
late for this protection. It could still be written to WATCHER or the PGN, but
it could not safely trigger the existing automatic-takeback path.

Therefore, retro engines require a pre-send decision. When the deep top-three
Tutor search does not contain the selected move, Picochess must either obtain a
valid fallback evaluation before starting the retro engine or leave the move
unrated and allow play to continue. It must not send the move and later attempt
the retro automatic takeback.

## Proposed retro-safe Tutor fallback

The fallback should run when all of the following are true:

- Tutor/WATCHER evaluation is enabled.
- The selected user move is absent from the deep Tutor list, so immediate exact
  CPL is unavailable.
- The stored Tutor score for the position before the move reached the minimum
  depth.
- The playing engine cannot provide a compatible after-position score.
- Retro pre-send protection is required.

The proposed sequence is:

1. Preserve the before-position Tutor score, depth, FEN, and source as an
   immutable snapshot.
2. Push the user move on the Picochess and Tutor boards.
3. Do not start the retro engine yet.
4. Reuse the existing deep Tutor engine to analyse the resulting position with
   `MultiPV = 1`.
5. Do not start the shallow/obvious Tutor engine for this fallback.
6. Stop when the configured minimum depth is reached or a bounded timeout
   expires.
7. Compare the before and after position scores.
8. If the result is `??`, enter the existing automatic-takeback path without
   ever sending the move to the retro engine.
9. Otherwise stop the fallback analysis and start the retro engine normally.

The fallback should reuse `picotutor.best_engine`; it should not create another
engine process. The operation must be explicit and bounded rather than achieved
by weakening the normal PicoTutor lifecycle rules.

## CPU and clock rules

Picochess is designed around one deep analyser at a time. The deep Tutor must
not run concurrently with a playing engine merely to obtain a delayed score.

For retro play, the Tutor fallback and engine search must be sequential:

```text
user move
    -> optional Tutor MultiPV-1 validation
    -> retro engine search, if the move is accepted
```

The validation period should not consume the retro engine's clock time. A
temporary user-facing indication such as "checking move" may be considered if
the delay is noticeable.

Because MultiPV 1 to the minimum depth should be much faster than MultiPV 30 to
the same depth, this may still reduce total CPU consumption. It trades a short
post-move delay for a substantially narrower analysis while the user is
thinking. Timing must be measured on the target Raspberry Pi hardware.

The fallback requires:

- A bounded wall-clock timeout.
- Cancellation on takeback, new game, position reset, mode change, engine
  change, Tutor disable, and shutdown.
- FEN, ply, move, and generation checks before accepting the result.
- Logging of elapsed time, reached depth, source, and completion or rejection
  reason.
- Safe continuation without a rating if the minimum depth is not reached.

## Non-retro engines without analysis

Ordinary engines configured with `Analysis=false` do not have the same pre-send
takeback constraint. Their move can be started while the Tutor evaluation is
still unavailable, provided the one-deep-analyser rule is preserved.

Possible sequential fallback points include:

- After the playing engine finishes searching but before its move is
  announced.
- At another safe idle point, using the stored position after the user move.

The result may then be added to WATCHER and the stored PGN evaluation later.
It must not attempt the retro automatic-takeback action.

If the playing engine returns a valid top-line score, it is useful only when a
compatible before score from the same source exists. A score merely being
present is not sufficient reason to compare it with a Tutor score.

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
compatible before/after scores available
    -> derive the move evaluation from existing analysis

missing after score and retro pre-send protection required
    -> run a synchronous Tutor MultiPV-1 check before engine think()

missing after score but delayed feedback is safe
    -> schedule a sequential Tutor fallback at a safe idle point

no reliable pair before timeout
    -> leave the move unrated
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
5. Enable delayed position-pair evaluation as a fallback while deep MultiPV is
   still 30.
6. Test the retro pre-send Tutor fallback and confirm that a `??` move is never
   sent to the retro engine.
7. Reduce the deep Tutor MultiPV to 3 only after WATCHER, PGN persistence,
   takebacks, and retro protection have been validated.

Shadow-mode logging should include:

- Existing root-line CPL and proposed position-pair CPL.
- Absolute difference and threshold-crossing disagreements.
- Existing and proposed NAG.
- Before, after, and effective depths.
- Source identities and score types.
- Time taken to produce the after-position score.
- Rejection and timeout reasons.

Two retro strategies should be compared during testing:

- Deep MultiPV 3 with an occasional post-move MultiPV-1 validation.
- Retaining a wider deep MultiPV specifically for retro games.

The first strategy should save more analysis work but may introduce a short
response delay. The second avoids the validation delay but may retain the depth
and CPU problems that motivated the optimization.

## Conclusion

Position-pair evaluation can restore `?` and `??` coverage after reducing the
deep Tutor MultiPV, without separately analysing every possible root move. The
central requirement is source-consistent before and after scores.

Engines without usable analysis require a Tutor fallback. Retro/MAME engines
are the strictest case because `??` must be known before the user move is sent
to the engine. Their fallback must therefore be synchronous, bounded, and
sequential with engine thinking. Other engines may use delayed WATCHER and PGN
updates when immediate takeback protection is unnecessary.
