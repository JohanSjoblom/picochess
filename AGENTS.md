# Picochess Agent Notes

## Purpose

This file captures repo-wide behavioral constraints that matter when changing
analysis routing and display behavior.

Start with this top-level file. Add more local `AGENTS.md` files only when a
subdirectory has rules that are specific to that subsystem.

## Wayland And Artwork

Preserve the current X11 and Wayland split for retro/MAME artwork handling.

- Keep X11 backward compatible. `xdotool` remains the X11 window-control path.
  Wayland work must not break the old X11 behavior.
- On Wayland, MAME startup window mode is controlled by `rwindow` passed as
  `-window` or `-nowindow`. This startup behavior must not depend on
  `ydotool`.
- `rdisplay = true` is the guard for artwork-related window switching.
  `rwindow` only controls whether MAME starts windowed or fullscreen.
- Runtime artwork window control uses `window-control-backend` with values
  `auto|xdotool|ydotool|swaymsg|none`. Prefer that override instead of trying
  to infer too much from the service environment.
- Do not assume `picochess.service` can reliably detect a desktop Wayland
  session from environment variables alone. Avoid service-level Wayland
  changes unless there is a clear deployment need.
- `install-ydotool.sh` is the preferred helper for Wayland users who need
  runtime window switching. It may add `trixie-backports`, add the install
  user to the `input` group, and enable `ydotool.service`.
- Honor `YDOTOOL_SOCKET` when using `ydotool`, so custom socket setups can
  work without changing the default-socket behavior.
- Raspberry Pi OS Trixie defaults to Wayland with `labwc`, not Sway. Do not
  assume `swaymsg` is the default backend on Raspberry Pi.
- Preserve the current artwork-switch UX unless intentionally redesigning it:
  quick non-king lift-and-return before `set pieces` switches windows, and
  post-`set pieces` non-king corrective lift-and-return also switches windows.
  King lift remains reserved for coach/evaluation behavior.

## Start Position And `NEW_GAME` Rules

Preserve the current distinction between physical eboard start-position scans
and explicit takeback handling.

- On a physical eboard, a return to the standard start position is still
  treated as `NEW_GAME`.
- This includes the case where a user takes back all moves one-by-one until the
  board reaches the start position on the eboard.
- Picochess deliberately does not use ply-counter logic to distinguish
  “last takeback back to start” from “user reset pieces for a new game” on the
  eboard path. Do not add that complexity unless the policy is intentionally
  changed.
- Explicit takeback from the web/menu path remains normal takeback even when
  the move stack becomes empty; it does not fire `NEW_GAME` just because the
  game returns to move 0.
- Takeback to a non-starting base position remains normal takeback and must not
  fall through to `NEW_GAME`.
- Start-position restore guards for lift-and-return and post-`set pieces`
  correction must continue to route through `Event.FEN` so same-position
  handling, including artwork/window switching, is preserved.

## Async Architecture

Picochess has been ported from a thread-based design to one shared `asyncio`
event loop used throughout the program. Preserve that architecture.

- Do not add new threads for normal Picochess work.
- Do not add blocking calls in the main flow, event handlers, analysis timers,
  engine routing, web handling, or display handling.
- Long-running or waiting work must run as async tasks and must yield with
  `await`, `asyncio.sleep()`, queues, events, or other non-blocking async
  primitives.
- Engine analysis and engine-thinking work should follow the existing pattern
  used by the two UCI analysis sisters: they run as background async tasks and
  expose cached state for the main loop to read.
- If a library API is blocking, isolate it behind an async boundary rather than
  leaking blocking behavior into `picochess.py`.

## Clock Timing Pitfalls

Clock drift regressions have occurred before. Preserve these timing-specific
rules when changing DGT board or web clock code.

- Do not reintroduce blocking delay on the `DGT_RETURN_SERIALNR` keepalive path
  in `dgt/board.py`; that previously caused web clock drift.
- The web clock in `server.py` intentionally keeps fractional elapsed-time
  carry between `_runclock()` ticks. Do not replace it with per-tick rounding
  or "subtract exactly 1 second per callback" logic.

## PicoTalker Web Audio Routing

Native/SoX PicoTalker audio has a special remote web-client path. Preserve this
routing when changing audio, server, or web-client code.

- `PicoTalkerDisplay` owns the sound queue and plays one clip at a time.
- `web-audio-backend-remote` is the persistent setting for using a remote web
  browser as the PicoTalker speaker.
- `web-audio-backend-remote` defaults to `False` for backward compatibility and
  to avoid enabling remote streaming implicitly.
- Backend web audio is remote-only. Localhost web clients do not enable this
  path, and local Pi audio remains controlled by the normal voice, volume, and
  audio-backend settings.
- Audio routing scenarios in `PicoTalkerDisplay.sound_player()`:
  1) `web-audio-backend-remote` disabled: local native/SoX playback only.
  2) `web-audio-backend-remote` enabled, but no remote client connected:
     local native/SoX playback only.
  3) `web-audio-backend-remote` enabled and remote client connected:
     emit `WebAudio` and skip local playback for that clip.
- Scenario 3 emission is intentionally sequential (`await`), not fire-and-forget,
  to preserve clip order.
- Encoding audio files for the web and native/SoX playback may use
  `asyncio.to_thread()`, but the shared async loop must not be blocked.
- Backend web audio takes priority over browser speech synthesis; browser TTS is
  only a fallback when the backend stream is not active.
- SoX playback must not block the talker queue indefinitely. Calls to `play`
  should discard stdio, use a bounded timeout, and terminate the process or
  process group on timeout.
- Keep native and SoX backend behavior separate. SoX changes should not alter
  native playback except when native playback already falls back to SoX.

## Audio Debug Runbook (Trixie/PipeWire)

Use this short runbook before changing audio code:

- Verify runtime path first, then change code. Do not assume where sound is
  played from.
- Startup clips may play locally before a remote web client websocket is
  connected; this is expected.
- After a remote websocket is connected and
  `web-audio-backend-remote=true`, move clips should route to `WebAudio` only.
- CPU starvation can look like fading/clipping. Avoid max-load defaults for
  fresh installs by keeping explicit `engine-level` values in example ini files.
  For `a-stockf`, use a level that keeps startup `Threads=1` (for example
  `Elo@2200`).

When debugging routing, use these log markers:

- `audio routing clip=... target=web|local`
- `web audio emitted clip=...`
- `web audio broadcast websocket_clients=...`
- `websocket client state: has_remote=...`

Known test pitfall:

- Phone Bluetooth loopback can mislead tests. If the phone is paired to the Pi,
  web audio from the phone may be routed back to Pi speakers/jack, which can
  look like local backend playback even when routing is correct.

## Analysis Cycle CPU Rules

`analyse()` has two analysis outputs:

- Clock/DGT output through `send_analyse()`, depth-gated by
  `best_sent_depth`.
- Web client output through `send_web_analysis()`, tagged as engine or tutor
  analysis.

Analysis routing has four main cases:

- Engine is playing and tutor is on:
  - On the engine turn, use engine `PlayingContinuousAnalysis` for
    engine-thinking information.
  - On the user turn, keep clock hints and values engine-driven. Do not
    overwrite the clock output with tutor information, though tutor information
    may still be sent to the web client.
- Engine is playing and tutor is off:
  - On the user turn, use engine `ContinuousAnalysis` for clock updates.
  - On the engine turn, use engine `PlayingContinuousAnalysis`.
- Engine is not playing and tutor is on:
  - Tutor `best_engine` `ContinuousAnalysis` drives clock and web client
    output.
- Engine is not playing and tutor is off:
  - Engine `ContinuousAnalysis` drives clock and web client output.

CPU-saving invariant: the design is intentionally built around only one deep,
clock-driving analyser at a time. That analyser is either the selected main
engine or the tutor `best_engine`; do not let both run deep analysis for the
same cycle.

- `picotutor` `best_engine` `ContinuousAnalysis` for tutor-driven analysis paths
  when it is the user turn.
- Engine `ContinuousAnalysis` for tutor-off analysis paths, especially when the
  engine is not playing and Picochess analyses both sides.
- Engine `PlayingContinuousAnalysis` for the engine-thinking path when it is
  the engine turn, regardless of whether tutor is on or off.

Ignore `picotutor` `obvious_engine` for this invariant; it is shallow helper
analysis.

## Startup CPU Rules

Picochess normally starts in `Mode.NORMAL`. Preserve the startup CPU-saving
behavior for that default path:

- On initial startup in `Mode.NORMAL`, do not spend CPU on deep analysis while
  the board is the untouched standard starting position and `game_started` is
  still `False`.
- The startup-idle guard should be tied to the playing-mode lifecycle
  (`eng_plays()` and `game_started`), not to a broad "starting position is never
  worth analysing" rule.
- Starting analysis after the user clicks play/pause is intentional: the
  play/pause action marks the game as started, even if no move has been made.
- Starting analysis after a user move is intentional.
- Switching from startup `Mode.NORMAL` into a non-playing analysis mode is also
  an explicit user action. `Mode.PONDER`, `Mode.ANALYSIS`, and `Mode.KIBITZ`
  may start analysis immediately after such a switch, including from the
  standard starting position.
- Do not add a blanket start-position suppression for non-playing modes just to
  save CPU. In `Mode.PONDER`, the starting position may be a deliberate analysis
  position or a base for flexible setup. In `Mode.ANALYSIS` and `Mode.KIBITZ`,
  positions are entered move-by-move, but entering those modes is still
  user-initiated rather than startup-automatic.

## `picochess.py` Analysis Driver

`analyse()` in `picochess.py` is the main Picochess policy layer around
`UciEngine` analysis. It is called periodically by the background analysis
timer and decides which already-running analysis buffer should be read, where
that information should be displayed, and whether the engine analyser should be
started or stopped for the next cycle.

Keep this boundary intact when changing analysis behavior:

- `UciEngine` owns engine communication, `ContinuousAnalysis`, and
  `PlayingContinuousAnalysis`.
- `picochess.py` owns mode policy, tutor-versus-engine routing, clock/web
  output decisions, PGN replay side effects, and `best_sent_depth` filtering.
- `analyse()` should usually call `get_analysis()` or `get_thinking_analysis()`
  to read buffered data. Those calls are not the place to start another deep
  analyser.
- `UciEngine` exposes cached analysis snapshots to callers. See
  `uci/AGENTS.md` before changing `uci/engine.py` analysis internals.
- `_start_or_stop_analysis_as_needed()` is the reconciliation point for the
  selected engine analyser. It uses `need_engine_analyser()` and
  `state.get_move_check_board()` to start engine `ContinuousAnalysis` with
  `FLOAT_ENGINE_MAX_ANALYSIS_DEPTH`, or to stop it when tutor, PGN mode,
  engine-thinking, startup-idle, or stale-position rules say it is not needed.
- Tutor analysis is managed by `picotutor`; `_start_or_stop_analysis_as_needed()`
  only starts or stops the selected main engine analyser.
- Do not start engine `ContinuousAnalysis` while the playing engine is thinking
  about its move. Use `get_thinking_analysis()` / `PlayingContinuousAnalysis`
  for that path.
- In the normal user-turn path, `analyse()` may read tutor output for the web
  Tutor line and engine `ContinuousAnalysis` for the web Engine line. Clock/DGT
  output must still follow the CPU-saving routing rules above.
- `best_sent_depth` suppresses repeated or worse clock/DGT updates. Web output
  can still be sent separately with the correct source tag.
- PGN replay autoplay currently piggybacks on this once-per-second analysis
  cycle. Analysis refresh calls that are only for engine switching must pass
  `allow_autoplay=False`.

## `picotutor.py` Analysis Driver

`PicoTutor` also uses `UciEngine`, so it has its own analyser lifecycle guard:
`_start_or_stop_as_needed()`. Treat it as the tutor-side equivalent of
`picochess.py`'s `_start_or_stop_analysis_as_needed()`.

The tutor-side rule is:

- `set_mode()` and `set_analysis_enabled()` must reconcile tutor analysis by
  calling `_start_or_stop_as_needed()`.
- `_start_or_stop_as_needed()` must be the common path that starts tutor
  analysis when `_should_run_tutor()` is true and stops it otherwise.
- `_should_run_tutor()` should stay cheap and policy-focused: tutor analysis
  runs only when analysis is enabled, coach or watcher is on, and PicoTutor is
  either analysing both sides or it is the user's turn on the tutor board.
- `PicoTutor.start()` may start `best_engine` deep analysis and the shallow
  `obvious_engine` helper when tutor is active. The architecture rule is that
  tutor `best_engine` replaces the selected engine's deep `ContinuousAnalysis`
  in tutor-driven paths.
- `PicoTutor.get_analysis()` should read the tutor `best_engine` buffer only if
  tutor analysis is enabled and the analyser is already running. It should not
  be used as a back door to start tutor analysis.

If `UciEngine` analysis internals are updated again, preserve both lifecycle
guards: `picochess.py` decides whether the selected main engine analyser should
run, and `picotutor.py` decides whether the tutor analyser should run. The CPU
saving behavior depends on those two decisions staying coordinated.

## `picotutor.py` Color-Side State

PicoTutor is designed to understand both sides of the board. Important tutor
analysis state is keyed by chess color (`chess.WHITE` / `chess.BLACK`) rather
than being stored as one global "user" value.

Preserve this color-side design:

- Keep important analysis snapshots, move lists, histories, PVs, hints, and
  alternative-best-move state separated by color.
- `analyse_both_sides=True` allows the tutor to evaluate both White and Black.
  This is required for non-playing analysis modes such as `Mode.ANALYSIS`,
  `Mode.KIBITZ`, and similar modes where there is no normal user-versus-engine
  split.
- `user_color` still matters when the engine is playing. With
  `analyse_both_sides=False`, tutor evaluates the user side and keeps the
  engine side in history with a fake/dummy tuple so pop/history logic remains
  color-consistent.
- Do not collapse color-keyed tutor state back into user-only state. That would
  break tutor-driven analysis modes where the tutor must analyse both sides.
- When adding new tutor state that follows analysis, move history, PV, hint, or
  evaluation data, prefer the existing `{color: ... for color in
  [chess.WHITE, chess.BLACK]}` pattern unless the value is truly global.

## Tutor Evaluations And PGN Save

Tutor move evaluations are persisted in `PicoTutor`, not recomputed during PGN
save. `get_user_move_eval()` both produces live feedback and records
PGN-facing evaluation data in `evaluated_moves`.

Preserve this data flow:

- `evaluated_moves` is reset only for a new game and then accumulates evaluated
  move data during play or analysis.
- Its key is `(halfmove_nr, move, turn)`, where `turn` is the board turn after
  the move. PGN saving uses the move and turn as a checksum before annotating a
  node.
- Values may include NAG, CPL, score, mate, best move, user move,
  `deep_low_diff`, and `score_hist_diff`.
- `PgnDisplay.add_picotutor_evaluation()` consumes `picotutor.get_eval_moves()`
  at save time and writes tutor NAGs/comments into the PGN.
- Do not move this evaluation persistence into `PgnDisplay` or try to
  recompute tutor evaluations while saving. PGN saving should consume the tutor
  snapshot gathered during the actual game or analysis session.
- Keep `get_eval_mistakes()` based on the same stored data so the web UI and
  saved PGN stay consistent.

## PGN Replay Architectures

There are two PGN replay mechanisms. They serve a similar purpose but are not
the same code path.

- `Mode.PGNREPLAY` is the built-in replay mode added to step through a loaded
  PGN game. It uses PicoTutor's PGN game state to find the next move, supports
  autoplay, and may eventually replace the historical replay engine.
- The selected `"PGN Replay"` engine is the legacy replay engine. It behaves
  like a UCI engine from Picochess's point of view, but its purpose is to return
  moves from a PGN file rather than calculate chess moves.
- The legacy PGN replay engine does not provide normal analysis. Do not expect
  it to feed the analysis cycle like a real chess engine.
- When asking `UciEngine` for a new move from the legacy PGN replay engine, keep
  the special error/end-of-game handling. An engine error, `bestmove 0000`, or
  `ABORT`-like result may mean "the PGN game is ended", not necessarily "the
  engine crashed".
- Picochess reads PGN replay-engine metadata from the configured
  `pgn_game_file` so it can track headers, total halfmoves, and the PGN result.
  Preserve that metadata path when changing engine startup or level switching.
- Built-in `Mode.PGNREPLAY` end handling is separate from the legacy replay
  engine's `PGN_GAME_END` path. Do not merge those branches unless the legacy
  engine is intentionally removed.
- `Mode.PGNREPLAY` must not overwrite the normal `last_game.pgn`; it saves replay
  output separately as `last_replay.pgn`.
- Keep `allow_autoplay=False` on analysis refreshes that are only meant to
  restart analysis after engine changes. Those refreshes must not accidentally
  advance built-in PGN replay.

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

## Reference Branches

- `web-client-424` is a permanent side branch for accessibility reference
  material, especially older web-client behavior that may help users with poor
  eyesight on 7" 1024x600 touch screens.
- Do not merge `web-client-424` into `master` or feature branches. When it is
  useful, inspect it with `git diff` or copy only specific design ideas or files
  and adapt them to the current codebase.

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

- Run unit tests through the repository virtual environment. Use
  `venv/bin/tox -e unit` for the full unit suite, or `venv/bin/python -m
  unittest ...` for focused unittest runs. Do not start with the system
  `python`/`python3`, because it may miss Picochess test dependencies such as
  `chess`, `configobj`, `flask`, and `paramiko`.
- In `PONDER`, verify analysis comes from the selected engine and never tutor.
- In `PONDER`, switch engines mid-analysis and verify web and clock restart from
  the new engine cleanly.
- In tutor-active non-`PONDER` modes, verify existing tutor behavior still
  works.
- Good coverage modes for that regression are `KIBITZ` and `PGNREPLAY`.
