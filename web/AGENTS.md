# Picochess Web Client Agent Notes

## Purpose

This file captures design intent for the modernized PicoChess web client.
It applies to code under `web/`, and to nearby server glue when changing web
client behavior.

The modernized web client is a UX layer around the existing PicoChess backend.
Do not change chess playing logic, engine move selection, DGT board move
handling, or `UciEngine` behavior as part of web-menu work unless the task
explicitly requires it.

## Main Touch Points

- `web/picoweb/templates/clock.html`
  - modern overlay menu layout and inline menu state helpers
  - clock action buttons
  - system/audio menu labels and local UI state
- `web/picoweb/static/js/app.js`
  - board controls, websocket handling, audio routing, PGN upload/download
  - per-client audio mute state
- `server.py`
  - `/channel` actions for web menu commands
  - `/info?action=get_current_settings`
  - shared `system_info` and `TutorSettings` websocket updates
- `picochess.py`
  - only for web-visible lifecycle state or backend events that already exist
  - avoid adding web-specific rules to core game flow unless necessary
- `dgt/display.py`
  - only for DGT board FEN-to-event mapping and clock display behavior

## Menu Model

- The new overlay menu replaces the old web clock menu.
- The old tab area still exists and still has important behavior, especially
  `ANALYSES`, `WATCHER`, `BOOK`, and `GAMES`.
- Avoid duplicating old-tab behavior unless there is a clear UX reason.
- Prefer small `/channel` actions that send one backend setting change at a
  time. This avoids flooding audio announcements and makes settings easier to
  reason about.
- When the web menu changes a setting that is also owned or displayed by the
  DGT menu, keep the live DGT menu state synchronized before firing backend
  events. Many backend paths read `state.dgtmenu` rather than re-reading
  `picochess.ini`, and users may mix DGT clock menu changes with mobile web
  menu changes during one PicoChess run.
- For those shared settings, update all applicable layers together:
  `picochess.ini` for persistence, the live runtime value read by backend
  logic, and the DGT menu's cached/current selection fields used for clock menu
  display.

## Playing Mode Naming

- `playing-modes.txt` is the reference for user-facing mode names versus code
  mode names.
- The user-facing `MOVE HINT` mode is `Mode.ANALYSIS` in the backend.
- The user-facing `ANALYSIS` mode is `Mode.PONDER` in the backend.
- Do not infer analysis routing from the visible label alone. Web menu actions,
  `interaction_mode`, and analysis display logic must use the backend mode name.
- In particular, top-level `AGENTS.md` rules for `Mode.PONDER` apply to the
  web-visible `ANALYSIS` mode, not to web-visible `MOVE HINT`.

## Books

- There are two distinct book concepts.
- The new overlay engine book setting changes the engine opening book. It maps
  to the `book` setting in `picochess.ini`, persists, and must not expose the
  special `obooksrv` index 0 entry.
- The old `BOOK` tab changes only the opening information shown to the human in
  the web client. It must keep the special `ObookSrv` index 0 entry.
- Do not let the old `BOOK` tab change the playing engine book.

## Game Lifecycle State

- `game_started` is a lifecycle flag for the web client and CPU-saving analysis
  decisions. It is not just `len(move_stack) > 0`.
- `game_started` may be true even when the move stack is empty, for example
  after the user started a clock, switched sides before move 1, or took back to
  move 0.
- `Event.NEW_GAME` resets `game_started` to false.
- Do not use `game_started` to decide physical eboard start-position routing.

## Start Position And Takeback Rules

- Physical eboard state is authoritative when an eboard is being used.
- A normal DGT/eboard scan of a start position means `Event.NEW_GAME`.
- Do not add ply-counting state to distinguish "last physical takeback" from
  "user reset pieces for a new game"; this complexity was intentionally
  rejected.
- Explicit web/menu takeback back to move 0 remains a takeback sequence and
  must not fire `Event.NEW_GAME`.
- Mixed control, such as using web takeback while physically playing on an
  eboard, is not a supported UX path and does not need safeguards.
- Two eboard start-position restore exceptions must stay:
  - Set-pieces restore uses `Event.FEN`, not `Event.NEW_GAME`.
  - Quick mode-command restore from a start position, such as placing a queen on
    D5 to select `Mode.PGNREPLAY` and then removing it, uses `Event.FEN`.

## Clock Controls

- The web client needs quick clock-like controls outside the overlay menu.
- Keep switch-sides and pause/resume controls visually attached to the clock,
  not buried only inside the menu.
- The four quick clock controls, switch sides, evaluation, pause/play, and hint,
  should remain large enough for touch use on local and remote clients.
- The web action is `pause_resume`; avoid reintroducing the misleading
  `move_now` naming for this control.
- The same button intentionally has context-dependent meaning:
  - user clock running: pause
  - paused: resume/play
  - engine thinking: stop thinking and produce a move
  - engine move announced but waiting on physical board: request alternative
    move
  - PGN replay running: pause replay
- The web clock should show usable clock time on startup, not a persistent
  engine name.
- Timed DGT text messages shown on the web clock, such as Engine Setup, must
  restore the clock display after `maxtime`.

## Touch Layout

- Primary touch targets should be at least 44px where practical.
- The settings gear target must remain visibly framed, not just invisibly
  enlarged.
- Picker/menu rows should remain finger-sized and scrollable.
- Overlay submenu tiles should preserve the main 3x3 tile size where practical.
- Prefer a single one-step Back control in the overlay header over per-submenu
  titles or multiple nested Back buttons when vertical space is tight.
- Do not reintroduce secondary metadata in picker rows, such as engine Elo,
  when it makes touch selection harder and the same choice is confirmed later.
- PGN move-list text should keep a readable minimum size in landscape layouts,
  especially around 7" 1024x600 screens.
- Keep the chessboard control row compact for touchscreen use.
- Avoid layout moves that improve desktop landscape but regress mobile
  landscape or portrait.

## Tutor Menu

- The new Tutor menu should send only the changed setting.
- Tutor state is controlled from the overlay Tutor menu. Do not reintroduce the
  old quick combined Tutor toggle in the `ANALYSES` tab; that toolbar should
  stay focused on analysis visibility, variation visibility, Web Stockfish, and
  Explore controls.
- Coach is one mutually exclusive setting: `off`, `on`, `lift`, `brain`, or
  `hand`. Do not model Brain and Hand as independent toggles.
- Brain/Hand are tutor coach modes for normal play, not web-only modes.
  Selecting them from the web menu must post `action=picotutor&tutor=coach`
  with `val=brain` or `val=hand`.
- In the `ANALYSES` tab, the Pico backend analysis row should stay visually
  distinct from the web-client Stockfish row. Preserve the Pico source badge:
  `E` for selected-engine backend analysis and `T` for Tutor backend analysis.
- Read and display backend tutor state when the web client opens, and keep it in
  sync via websocket updates.
- When a PGN is loaded from disk, the WATCHER list may show lightweight review
  points derived from mainline side variations. Do not recreate or persist
  `PicoTutor.evaluated_moves` from PGN comments or old evaluation details.

## ANALYSES Tab CPU

- The web-client Stockfish row is browser-side analysis and is separate from
  Picochess backend analysis.
- On localhost, only one web-client Stockfish analysis line may run, and hiding
  the Web row must stop the browser Stockfish worker/module so it does not
  compete with the Picochess service for CPU.
- Remote web clients may expose multiple Web Stockfish MultiPV rows, but hiding
  Web analysis should still stop browser Stockfish rather than only hiding its
  output.
- Do not start or restart browser Stockfish from position updates unless the Web
  analysis toggle is active.

## ANALYSES Tab SHOW/HIDE State

- Treat the ANALYSES tab row visibility as shared UI state, not as independent
  CSS tweaks. The Pico backend row, Web Stockfish row, separator, and
  `#right-panel` sizing classes must stay synchronized.
- Use the existing row helpers in `web/picoweb/static/js/app.js`:
  `setAnalysisRowVisible()`, `updateAnalysisRowSeparator()`,
  `setEngineLinePlaceholder()`, and `setSF18Placeholder()`.
- Do not hide or show `#engineRow`, `#sf18Row`, or `#analysisRowSeparator`
  directly with ad hoc jQuery/CSS unless those helpers are also updated.
- When a row is hidden, also clear its stale content and reset its button text
  to `SHOW`. When a row is shown by fresh data or by an explicit user click, set
  the corresponding button text to `HIDE`.
- Keep `analysis-rows-none`, `analysis-rows-one`, and `analysis-rows-two` on
  `#right-panel` as the single source for letting the PGN move list reclaim
  space when analysis rows are collapsed.
- The Web Stockfish SHOW/HIDE button also controls browser CPU usage. Hiding Web
  analysis must call the path that stops the browser Stockfish worker/module; it
  must not merely hide the DOM row.

## System Audio Design

- There are two web audio sources:
  - backend PicoTalker audio streamed from the Pi to a remote browser
  - browser synthesized speech fallback
- The backend PicoTalker stream is the primary "phone as speaker" feature.
- Backend stream ownership is in `PicoTalkerDisplay`; the web client only
  receives `WebAudio` events and queues playback.
- The System menu `Phone Speaker` setting toggles
  `web-audio-backend-remote` globally and persistently. It may update live via
  shared state.
- Backend audio is remote-only. Localhost must not enable the backend stream.
- When backend audio is active, it takes priority over browser speech synthesis.
- Remote clients have one per-client mute button. It mutes whichever source is
  currently active: backend stream when available, otherwise browser speech.
- Do not add a localhost mute for the Pi's local PicoTalker voice. Local voice
  output should be controlled by the existing user/computer voice settings and
  volume settings.
- `audio-backend` is a technical restart-required setting:
  - `native` is intended for Wayland/PipeWire and requires `pipewire-alsa`.
  - `sox` is the older X11/legacy path.
  - Changing this setting from the web menu should save `picochess.ini` and
    clearly indicate that a PicoChess restart is required.

## PGN Controls

- Do not add PGN controls back to the board control row without checking mobile
  touch layout.
- PGN upload is available only on remote web clients, near the clock/mute
  controls.
- PGN download is currently not exposed as a quick touch control; if needed,
  prefer adding it to a menu rather than the board row.
- PGN replay must keep the smart clock control state in sync with replay
  autoplay.

## Web Explore State

- Keep the Explore ON state explicit. In NOEBOARD/web-only play, the Explore
  button must turn ON only when the user clicks it.
- When a physical eboard is in use, the web board is an open playground rather
  than the authoritative move source. In that case Explore may default ON so
  web-board moves do not affect the physical game unless the user explicitly
  leaves Explore.
- In normal physical-eboard play, the backend must not accept web-board moves
  as real game moves. The frontend should also default to the eboard-safe path
  when board authority is unknown or stale.
- With a physical eboard and Explore OFF, the web board should be read-only in
  normal play. Do not update the browser PGN or post a move to the backend from
  a board drag unless the client is explicitly in NOEBOARD or the `Mode.REMOTE`
  exception below applies.
- Track whether the loaded PGN tree is the live PicoChess game tree separately
  from the selected FEN. Database games, watcher/PGN review, and live gameplay
  can show the same board position while having different move-entry authority.
  Use that state to guard web-board move submission. Highlight Sync only during
  an active game when the user is away from live move entry; finished-game and
  loaded-PGN review should not show amber just because there is no active game
  to continue.
- `Mode.REMOTE` is the intentional exception: one player uses the physical
  eboard and the remote opponent uses the web board. With Explore OFF, the web
  client may submit real moves only for the remote side's turn; local-side moves
  still come from the eboard.
- Because `Mode.REMOTE` uses the web board as a real move-entry surface, it
  should behave like NOEBOARD for the remote side: do not auto-set Explore ON
  just because a physical eboard exists, and keep the board playable only for
  the remote side to move.
- PGN move-list navigation, watcher review links, finished-game review, loaded
  PGNs, result/header updates, and DGT sync/reload paths must not turn Explore
  ON implicitly. They may preserve Explore if it was already ON.
- Keep OFF automations narrow and defensive. Turning Explore OFF is acceptable
  when entering a playable live position, such as a new game or SET_POSITION,
  so the user is not blocked from making normal web-board moves.
- When the user explicitly turns Explore OFF, the web client must perform a
  full live-position sync, equivalent to the Sync button, including restoring
  the last real move highlight/arrow and discarding explorer-only highlights.
- Avoid rebuilding a complex Explore state machine. Prefer preserving current
  user intent, explicit user toggles, and the small set of defensive OFF resets.

## Merge And Risk Guidance

- Keep web-client commits small and separable from backend game-flow changes.
- Prefer frontend-only fixes when a problem is purely visual or UX state.
- If backend support is needed, add narrow `/channel` or `/info` support and
  avoid changing core move coordination.
- Before changing `picochess.py`, verify whether the same behavior can be
  achieved through existing events or shared `system_info`.
