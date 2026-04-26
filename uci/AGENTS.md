# Picochess UCI Agent Notes

## UciEngine Boundary

`UciEngine` exists to isolate `picochess.py` and `picotutor.py` from direct
`python-chess` engine/protocol details. The main Picochess code should not need
to know how the underlying chess library starts analysis, stops analysis,
returns best moves, exposes info packets, handles protocol state, or requires
workarounds.

When updating `uci/engine.py`, preserve this boundary:

- Keep chess-library-specific mechanics inside `UciEngine`,
  `ContinuousAnalysis`, and `PlayingContinuousAnalysis`.
- Keep `picochess.py` focused on game mode policy, move flow, clock/web output,
  and tutor-versus-engine routing.
- Prefer adapting `UciEngine`'s API when the chess library changes instead of
  leaking new library behavior into Picochess main logic.

## Async Loop Rule

UCI engine work must preserve Picochess's single shared `asyncio` loop design.
Do not reintroduce threads or blocking waits in `uci/engine.py`.

- Engine searches, analysis streams, stop handling, force-move handling, and
  lease waiting must be async and must yield control to the shared event loop.
- Long-running UCI operations belong in background async tasks, as
  `ContinuousAnalysis` and `PlayingContinuousAnalysis` already do.
- Caller-facing methods should await async coordination or return cached state;
  they should not busy-wait or block the event loop while an engine thinks.
- Use `asyncio` primitives such as tasks, locks, events, queues, and sleeps for
  coordination with the rest of Picochess.

## Two Analysis Sisters

`uci/engine.py` intentionally has two sister classes for engine analysis:
`ContinuousAnalysis` and `PlayingContinuousAnalysis`. This is a deliberate
two-class design, not accidental duplication. Do not refactor them into one
class.

`ContinuousAnalysis` is the watching/analyser sister:

- It is the eternal analyser used when Picochess or PicoTutor wants analysis of
  a board position without asking the engine to play a move.
- It is started, updated, and stopped by the CPU-saving lifecycle logic in the
  root `AGENTS.md`: `picochess.py` controls the selected main engine analyser,
  and `picotutor.py` controls the tutor analyser.
- It caches the latest `InfoDict` list received from the chess engine so callers
  can poll the latest available analysis without triggering a new search.
- It supports position, depth, and multipv updates while preserving the idea of
  one long-running analysis worker.

`PlayingContinuousAnalysis` is the playing/thinking sister:

- It replaces the normal `python-chess` `play()` path for engines where
  Picochess needs live info while the engine is thinking about its move.
- The newer `python-chess` `play()` API does not provide the ongoing analysis
  stream Picochess needs for clock and web engine-thinking output.
- It therefore uses `engine.analysis()` as a timed, play-like search, keeps the
  latest thinking info cached, stops the analysis when time/force/cancel says
  the move should be chosen, then builds a `PlayResult` from the analysis
  `bestmove` result.
- From the rest of Picochess, this should behave like the engine is playing a
  move, while still exposing cached thinking analysis through
  `get_thinking_analysis()`.

The two sisters must not be collapsed into a plain `play()` call, one generic
helper, a shared base class, or a mode-flagged combined analyser. Keep the
separate classes unless the project owner explicitly asks for an architecture
change. Small shared utility functions are acceptable only when they do not hide
or weaken the separation between watching analysis and playing analysis.

## UciEngine Analysis Contract

`UciEngine` provides cached analysis results to its callers. From the caller's
point of view, `get_analysis()` and `get_thinking_analysis()` read the latest
analysis information already received from the chess engine; they do not start a
new deep search and should not be treated as synchronous analysis requests.

Keep these rules intact when changing `uci/engine.py`:

- `start_analysis()` owns the lifecycle of `ContinuousAnalysis`. If analysis is
  already running for the same position it keeps the existing analyser; if the
  position or depth changes, it updates the running analyser.
- `ContinuousAnalysis` stores the latest received `InfoDict` list in
  `_analysis_data` while its background task consumes engine analysis output.
- `ContinuousAnalysis.get_analysis()` returns a deep-copied snapshot of that
  cached data, together with the FEN and game id for the analysed position.
- `UciEngine.get_analysis(game)` should return cached analyser data only when
  analysis is allowed, the analyser is running, and the analyser FEN matches the
  caller's board. For stale or unavailable analysis it should return an empty
  result rather than starting a new search.
- `UciEngine.get_thinking_analysis(game)` reads cached information from
  `PlayingContinuousAnalysis` while the playing engine is thinking. It is the
  engine-turn counterpart to `get_analysis()`.
- `stop_analysis()` must wait for the background analyser to release the engine
  lease before returning. This prevents later UCI commands from racing an
  in-flight analysis stop or `bestmove` exchange.

The main Picochess and PicoTutor policy layers decide when analysis should run.
Do not move mode, tutor, clock, or web display routing policy into `UciEngine`.

## Engine `.uci` Options

Each chess engine has its own `.uci` config file. `UciEngine.startup()` reads
that config when no options dict is supplied, takes the selected section, and
stores a copy in `self.options`. Callers can also pass an options dict directly,
for example when changing levels or engines.

Keep these option rules intact:

- `self.options` is the stored Picochess view of the configured engine options.
  `get_pgn_options()` returns this stored dict for PGN/header and restart use.
- `send()` must not blindly send every key in `self.options` to the chess
  engine. It filters options against `self.engine.options` before calling
  `engine.configure()`.
- Some `.uci` entries are Picochess control values, not normal UCI engine
  options. Current examples include `Variant`, `Analysis`, `UCI_Variant`,
  `PicoDepth`, and `PicoNode`.
- `Variant` is stored in `self.variant` and is not sent through
  `engine.configure()`.
- `Analysis` controls legacy analysis handling and is removed from
  `self.options`.
- `UCI_Variant` is stored in `self.uci_variant` and sent directly with
  `send_line()` because `python-chess` blocks it in `configure()`.
- `PicoDepth` and `PicoNode` are deliberate pseudo-UCI settings. They may come
  from the engine `.uci` file and stay in `self.options`, but they are not real
  engine options. They are applied by `get_engine_uci_options()` to the
  `chess.engine.Limit` passed into the two analysis sisters / play-like search.
- `PicoDepth` and `PicoNode` have priority over time-control `depth` / `node`
  values, and they are treated as a pair so Picochess does not mix `.uci` and
  runtime sources.
- User menu overrides can remove these pseudo-options with
  `drop_engine_uci_option()`, allowing runtime depth/node values to take over.

## Legacy PGN Replay Engine

The `"PGN Replay"` engine is a special historical UCI engine. It is not a normal
analysing chess engine.

- It returns moves from a configured PGN file and may send `ABORT` /
  `bestmove 0000` when the PGN game is over.
- It does not provide normal analysis output. Do not make `UciEngine` analysis
  assumptions that require this engine to behave like Stockfish.
- `newgame()` has a special `"PGN Replay"` branch that pings before sending
  `ucinewgame`; the legacy engine expects that ordering while loading games.
- `handle_bestmove_0000()` must continue to distinguish real terminal positions,
  resignations, and dead/unresponsive engines. Picochess relies on this when a
  replay-like engine returns no move.
- Keep PGN replay-engine compatibility in mind when changing engine startup,
  `ucinewgame`, `isready`, stop, or bestmove handling.
