# Picochess Agent Notes

## Purpose

This file captures repo-wide behavioral constraints that matter when changing
analysis routing and display behavior.

Start with this top-level file. Add more local `AGENTS.md` files only when a
subdirectory has rules that are specific to that subsystem.

## Mode.PONDER Analysis Rules

- `Mode.PONDER` is analysis-only. It does not save a PGN move stack.
- In `Mode.PONDER`, analysis must always come from the currently selected main
  engine.
- Tutor analysis must never be used in `Mode.PONDER`, even if watcher/coach is
  enabled.
- Entering `Mode.PONDER` must prevent tutor analysis from starting and must
  clear any stale tutor analysis shown in the web client.
- Web client and clock analysis shown in `Mode.PONDER` must reflect the
  selected engine, not tutor.

## Non-Playing Mode Engine Switch Rules

- `eng_plays()` is false outside `NORMAL`, `BRAIN`, and `TRAINING`.
- When `NEW_ENGINE` happens in a mode where `eng_plays()` is false, analysis
  should continue after the engine switch.
- In `Mode.PONDER`, that means the newly selected engine must restart analysis
  and become the visible analysis source.
- Stale engine analysis from the previous engine should be cleared for the web
  client and clock display before fresh analysis arrives.
- The `best_sent_depth` optimization must be reset on engine switch so the new
  engine can send fresh depth updates immediately.

## Tutor Behavior Outside PONDER

- Non-`PONDER` modes keep the existing tutor behavior.
- If tutor is active in other non-playing modes such as `ANALYSIS`, `KIBITZ`,
  `OBSERVE`, or `PGNREPLAY`, tutor may remain the active analysis source.
- A selected-engine change in those tutor-driven modes should not be treated as
  a tutor policy change.
- A brief display reset is acceptable there; avoid adding complex branching just
  to preserve the previous display continuously.

## PGN Replay Guard

- Forced analysis refresh after `NEW_ENGINE` also applies to non-playing modes
  such as `PGNREPLAY`.
- Do not let that forced refresh trigger PGN autoplay side effects.
- Calls to `analyse()` made only to refresh analysis after `NEW_ENGINE` should
  use `allow_autoplay=False`.

## Touch Points

- `picochess.py`
  - tutor/engine routing policy
  - `engine_mode()`
  - `analyse()`
  - `NEW_ENGINE` handling
- `picotutor.py`
  - tutor analysis enable/disable gate
- `server.py`
  - web analysis clear/reset handling
- `dgt/display.py`
  - clock-side cached analysis reset
- `web/picoweb/static/js/app.js`
  - frontend handling for cleared analysis sources

## Regression Checks

- In `PONDER`, verify analysis comes from the selected engine and never tutor.
- In `PONDER`, switch engines mid-analysis and verify web and clock restart from
  the new engine cleanly.
- In tutor-active non-`PONDER` modes, verify existing tutor behavior still
  works.
- Good coverage modes for that regression are `KIBITZ` and `PGNREPLAY`.
