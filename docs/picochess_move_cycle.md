# PicoChess 4.2.2 -- Complete Move Processing Cycle
### Current active development repository: https://github.com/JohanSjoblom/picochess
### February 2026

===============================================================================
           TABLE OF CONTENTS
===============================================================================

A. Startup and Initialization
A+. Interaction Modes (how modes affect the cycle)
B. User Makes a Move
C. FEN Classification + Legality Check
D. Game-Over Check
E. Tutor Engine -- Analyse User Move
F. Clock Management After User Move
G. UCI Engine Communication
H. Engine Thinks
I. Announce Engine Move to User Before Push
J. Execute Engine Move Internally
K. Game-Over Check After Engine Move
L. Tutor Engine -- Analyse Engine Move
M. Clock Management After Engine Move is Executed
N. Loop Back (Next User Move)
O. Game-End Processing
P. Background Processes - Always Running

===============================================================================

This document explains the full move cycle inside PicoChess, including:

- support for multiple electronic boards
- GUI/keyboard move input
- python-chess legality checks
- special FEN positions for settings (DGT board)
- classic + variant endings
- engine cycle
- clock management
- background time-loss detection
- the tutor engine (PicoCoach / PicoWatcher / PicoExplorer)
- alternative-move override
- king-lift hint (PicoCoach COACH_LIFT)
- interaction modes (NORMAL, BRAIN, ANALYSIS, KIBITZ, OBSERVE,
  REMOTE, PONDER, TRAINING, PGNREPLAY)
- game-end processing (PGN writing, email, Elo update)
- startup and initialisation sequence
- and the correct sequence for engine-move output

---

## ASCII Flowchart

```
===============================================================================
           PICOCHESS -- COMPLETE MOVE PROCESSING CYCLE (ASCII DIAGRAM)
===============================================================================

+----------------------------------------------------------------------------+
| A. STARTUP AND INITIALISATION  (runs once before the first move)          |
+----------------------------------------------------------------------------+

   The startup sequence is executed by main() -> MainLoop.__init__() ->
   MainLoop.initialise() before the main event loop begins.

   A-1. CONFIGURATION
   ------------------
     * Parse picochess.ini + command-line args (configargparse).
     * Read engines.ini, retro.ini, favorites.ini via EngineProvider.init()
       -> builds the installed_engines list.
     * Each engine entry references a .uci file that stores its levels
       and UCI option defaults.
     * Read books.ini -> builds the all_books list of Polyglot books.

   A-2. E-BOARD DETECTION
   ----------------------
     Board type is selected via --board-type (default: DGT).
     Exactly one driver is instantiated:

       DGT        -> DgtBoard   (dgt/board.py)    -- serial / Bluetooth
       CERTABO    -> CertaboBoard (eboard/certabo/)
       CHESSNUT   -> ChessnutBoard (eboard/chessnut/)
       CHESSLINK  -> ChessLinkBoard (eboard/chesslink/)
       ICHESSONE  -> IChessOneBoard (eboard/ichessone/)
       NOEBOARD   -> no hardware (web / GUI only)

     The board driver starts its polling task (e.g. DgtBoard.run()).

   A-3. DISPLAY SYSTEM
   -------------------
     Display handlers are created and their async message_consumer()
     tasks are launched.  Each handler registers with DisplayMsg so
     that every Message.show() call fans out to all of them:

       * DgtDisplay      -- DGT clock text + LEDs (ser / i2c)
       * PicoTalkerDisplay -- speech output
       * WebDisplay       -- web browser GUI  (if --web-server-port)
       * PgnDisplay       -- PGN file recording
       * Dispatcher       -- DGT API message routing

     Supporting infrastructure:
       * DgtTranslate  -- translates display texts to chosen language
       * DgtMenu       -- manages the on-clock menu system
       * WebVr         -- web clock + virtual DGT bridge
       * PairingBridge -- IPC server for external pairing tools

   A-4. TIME CONTROL
   -----------------
     Parse --time string -> create initial TimeControl object.
     Mode is one of FIXED (per-move), BLITZ (game total), or
     FISCHER (game total + increment).

   A-5. PLAYING ENGINE
   -------------------
     a) Create UciEngine with the configured engine file path.
        If --engine-remote-server is set, connect via SSH (UciShell).
     b) engine.open_engine():
          * Spawn the UCI process (local: popen_uci; remote: SSH).
          * Engine responds to "uci" with its id + option list.
          * "isready" / "readyok" handshake.
     c) engine.startup(options):
          * Read the engine's .uci file (ConfigParser format).
            Extracts UCI options, PicoChess-specific flags
            (Variant, UCI_Variant, Analysis), and level settings.
          * Send "setoption name X value Y" for each option.
          * Send "isready" / "readyok" to confirm.
     d) Validate engine loaded successfully; exit on failure.

   A-6. TUTOR ENGINE
   -----------------
     a) Create PicoTutor instance with tutor engine path
        (--tutor-engine, typically Stockfish).
     b) picotutor.open_engine():
          * Spawns TWO independent UciEngine instances from the
            same binary:
              best_engine    (deep, DEEP_DEPTH ~ 17, more threads)
              obvious_engine (shallow, LOW_DEPTH ~ 5, fewer threads)
          * Each goes through the same uci -> isready -> setoption
            -> isready cycle.
     c) Load opening-book data files:
          chess-eco_pos.txt     (ECO positions)
          opening_name_fen.txt  (opening names by FEN)
     d) Load comment files for PicoComment (language-specific).

   A-7. INITIAL GAME STATE
   -----------------------
     * game = chess.Board()          (standard starting position)
     * legal_fens = compute_legal_fens(game)
         Pre-computes the board_fen() for every legal move from the
         starting position -- used by process_fen() in step C-2.
     * ModeInfo.set_game_ending("*")  (no result yet)

   A-8. OPENING BOOK
   -----------------
     The Polyglot .bin book selected by --book is opened via
     chess.polyglot.open_reader().  python-chess memory-maps the
     file for fast lookup during play.

   A-9. DISPLAY STARTUP MESSAGES
   -----------------------------
     Broadcast to all displays:
       * Message.SYSTEM_INFO   -- version, engine name, user name, Elo
       * Message.STARTUP_INFO  -- interaction mode, time control,
                                  book name, engine level
       * Message.ENGINE_STARTUP -- engine name + level text
     The DGT clock shows the engine name; the web GUI refreshes.

   A-10. BOARD CONNECTION + EVENT LOOP
   -----------------------------------
     * Launch event_consumer() -- the main game event loop (processes
       events from evt_queue).
     * Launch wait_for_board_connection() -- polls until the e-board
       is detected (or skips for NoEBoard).  Once connected:
         -- Display "ok" confirmation.
         -- Start the background analysis timer (1 s repeating).
     * All async tasks (display consumers, board pollers, event
       loop, board-wait) are gathered with asyncio.gather().
     * PicoChess is now ready for the first move -> section A+/B.

                                |
                                V

===============================================================================

+----------------------------------------------------------------------------+
| A+. INTERACTION MODES  (how modes affect the move cycle)                   |
+----------------------------------------------------------------------------+

   PicoChess supports nine interaction modes.  The mode determines WHO
   plays (engine vs. user), whether the engine searches or analyses,
   whether the clock runs, and which parts of the move cycle are active.
   The mode is set via the DGT menu, web GUI, or special FEN (section C-1).

   +------------+-----------------------------------------------------------+
   | Mode       | Description                                              |
   +------------+-----------------------------------------------------------+
   | NORMAL     | Standard play.  Engine is the opponent.  Clock runs.     |
   |            | Engine produces bestmove -> sections G--J apply.           |
   |            | Ponder is OFF.                                           |
   +------------+-----------------------------------------------------------+
   | BRAIN      | Like NORMAL, but with permanent pondering enabled.       |
   |            | After the engine's move, it starts pondering (speculative|
   |            | search on the expected reply).  If the user plays the    |
   |            | predicted move -> "ponderhit" (engine keeps searching     |
   |            | with confirmed time).  Otherwise -> "pondermiss" (engine  |
   |            | restarts from scratch).  Clock runs.                     |
   +------------+-----------------------------------------------------------+
   | ANALYSIS   | User plays BOTH sides.  Engine continuously analyses     |
   |            | the position (infinite search).  Displays best move +    |
   |            | principal variation on DGT clock and web GUI.            |
   |            | No bestmove is produced -- sections G--J are SKIPPED.     |
   |            | Clock does NOT run.                                      |
   +------------+-----------------------------------------------------------+
   | KIBITZ     | Like ANALYSIS, but shows eval score + depth instead of   |
   |            | best move.  User plays both sides.  Continuous analysis. |
   |            | No bestmove -- sections G--J SKIPPED.  No clock.          |
   +------------+-----------------------------------------------------------+
   | OBSERVE    | User plays both sides.  Engine analyses on demand (not   |
   |            | continuously).  Analysis results displayed when ready.   |
   |            | No bestmove -- sections G--J SKIPPED.  Clock does NOT run.|
   +------------+-----------------------------------------------------------+
   | REMOTE     | Two humans play against each other (via network or       |
   |            | shared board).  NO engine at all -- sections E--L are     |
   |            | largely skipped.  Clock runs.  PicoChess only validates  |
   |            | moves and manages the clock.                             |
   +------------+-----------------------------------------------------------+
   | PONDER     | Flexible analysis mode.  User can play moves for either  |
   |            | side, set up arbitrary positions, and explore lines.     |
   |            | Engine analyses continuously.  No clock.  PGN is NOT    |
   |            | saved at game end.                                       |
   +------------+-----------------------------------------------------------+
   | TRAINING   | Engine plays as opponent (like NORMAL), but with         |
   |            | automatic blunder detection + takeback.  If the user     |
   |            | plays a bad move (above blunder threshold), the move is  |
   |            | taken back automatically and the user must try again.    |
   |            | "Wrong move" / "try again" is displayed.  Clock runs.   |
   +------------+-----------------------------------------------------------+
   | PGNREPLAY  | Step through a loaded PGN file move by move.  Optional  |
   |            | autoplay at configurable speed.  No engine search.      |
   |            | Sections G--J are SKIPPED.  Saves to last_replay.pgn.   |
   +------------+-----------------------------------------------------------+

   Which modes use the engine as opponent?
     eng_plays() returns True for: NORMAL, BRAIN, TRAINING.
     Only these three modes execute the full G -> H -> I -> J cycle.

   Which modes run the clock?
     NORMAL, BRAIN, TRAINING, REMOTE.
     ANALYSIS, KIBITZ, OBSERVE, PONDER, PGNREPLAY do NOT run the clock.

   Simplified cycle per mode:

     NORMAL / BRAIN / TRAINING:
       B -> C -> D -> E -> F -> G -> H -> I -> J -> K -> L -> M -> N -> (back to B)

     ANALYSIS / KIBITZ / OBSERVE / PONDER:
       B -> C -> D -> [engine analyses, no bestmove] -> N -> (back to B)

     REMOTE:
       B -> C -> D -> [no engine] -> F -> N -> (back to B)

     PGNREPLAY:
       [step through PGN moves] -> B -> C -> D -> N -> (back to B)
                                 |
                                 V

===============================================================================

+----------------------------------------------------------------------------+
| B. USER MAKES A MOVE (via ANY supported input source)                      |
+----------------------------------------------------------------------------+
                                 |
                                 V
      +------------------------------------------------------------+
      |  INPUT SOURCES (unified by PicoChess)                      |
      +------------------------------------------------------------+
                                 |
         +-----------------------+---------------------------+-----------------+---------------+
         |                       |                           |                 |               |
         V                       V                           V                 V               V
   [DGT e-board]         [Certabo e-board]       [Chessnut / ChessLink]   [iChessOne]      [NoEBoard]
         |                       |                           |                 |               |
         |                       |                           |                 |               V
         |                       |                           |                 |      [GUI / Web Browser]
         |                       |                           |                 |   (drag & drop or typed moves)
         |                       |                           |                 |               |
         +-----------------------+---------------------------+-----------------+               |
                                 |                                                             |
                    Board drivers fire Event.FEN                              Web/GUI fires Event.REMOTE_MOVE
                   (board position changed)                                      (explicit move)
                                 +----------------------+--------------------------------------+
                                 |
                                 V
         PicoChess matches FEN against pre-computed legal_fens
                  -> candidate_move (abstracted input)

   Mode note: In NORMAL, BRAIN, TRAINING the user plays one side only.
   In ANALYSIS, KIBITZ, OBSERVE, PONDER the user plays BOTH sides.
   In REMOTE both players are human.  In PGNREPLAY moves come from the
   loaded PGN file (user steps forward/back or autoplay advances).

===============================================================================

+----------------------------------------------------------------------------+
| C. FEN CLASSIFICATION + LEGALITY CHECK                                     |
+----------------------------------------------------------------------------+
                                 |
                                 V
   C-1. SPECIAL FEN PRE-FILTER  (dgt/display.py -- DGT boards only)
   -----------------------------
   Before the FEN reaches the game logic, the DGT display layer checks
   it against predefined "settings FEN" maps.  These are ILLEGAL
   positions: standard starting position + one extra queen placed on a
   specific square.  The file (a--h) selects a slot; the rank selects
   which setting category.

   +--------------------+---------+------------------------------------+
   | Setting            | Piece   | Rank / squares                     |
   +--------------------+---------+------------------------------------+
   | Engine skill level | black q | rank 5 (a5--h5)  -> 8 levels        |
   | Opening book       | black q | ranks 3--4 (a3--h4) -> 16 books      |
   | Engine selection   | black q | rank 6 (a6--h6)  -> 8 engines       |
   | Playing mode       | White Q | rank 5 (A5--H5)  -> 8 modes         |
   | Time ctrl (fixed)  | White Q | dynamic map from menu              |
   | Time ctrl (blitz)  | White Q | dynamic map from menu              |
   | Time ctrl (Fischer)| White Q | dynamic map from menu              |
   | Shutdown           | 2 Q's   | d1+e1 (or d8+e8 variants)         |
   | Reboot             | 2 q's   | d8+e8 (or d1+e1 variants)         |
   | Draw / Resign      | 2 kings | adjacent kings, specific squares   |
   +--------------------+---------+------------------------------------+

   On match -> fire the appropriate event (Event.LEVEL,
   Event.SET_OPENING_BOOK, Event.NEW_ENGINE,
   Event.SET_INTERACTION_MODE, Event.SET_TIME_CONTROL, etc.),
   display confirmation on DGT clock, and return.
   The FEN is NOT forwarded to the game logic.

   No match -> continue to C-2.

   (Web/NoEBoard/non-DGT boards skip C-1; they send Event.REMOTE_MOVE
    or Event.FEN directly to picochess.py.)

   C-2. LEGALITY CHECK  (picochess.py, python-chess, variant-aware)
   ---------------------
   process_fen() checks candidate FEN in this order:
                                 |
         +-----------------------+------------------------------+
         |                       |                              |
    In legal_fens?         In game history?                Neither?
      (legal move)            (TAKEBACK)                 (illegal position)
         |                       |                              |
         V                       V                              |
   board.push(move)     Stop engine + clock.                    |
   (turn switches       Pop moves from game until            Board input:
    inside push)        board matches target FEN.              start 4-sec FEN timer;
         |              Set takeback_active = True.             if still wrong after
         |              Display "TAKEBACK" on DGT               timeout -> display
         |                + show undone move (long              "set pieces" + beep.
         |                  notation) + light LEDs.           Training mode:
         |              Blocked when: online mode,              "wrong move" / "try
         |                take_back_locked, or                  again" + beep.
         |                emulation w/o auto-takeback.        Keyboard/Web:
         |              Web/NoEBoard: takeback via              silent reject (log only).
         |                menu button or Event.TAKE_BACK.
         |              Supports multi-move takeback
         |                (FEN can match any earlier
         |                 position in game history).
         |                       |
         |              Back to B (wait for next move)
         |
   TRAINING mode note: if the user's move is legal but is judged a
   blunder by the tutor engine (score drop exceeds threshold), PicoChess
   automatically takes it back and displays "wrong move" / "try again".
   The user must play a different (better) move before the cycle
   continues.  This check happens after the move is pushed but before
   the engine searches.
         |
         V

===============================================================================

+----------------------------------------------------------------------------+
| D. GAME-OVER CHECK (classic + variant rules via python-chess)              |
+----------------------------------------------------------------------------+
                                 |
                                 V
               check_game_state() -> returns False or Message.GAME_ENDS(result)
                                 |
         Classic endings (GameResult values):
           * MATE               (checkmate)
           * STALEMATE           (stalemate)
           * INSUFFICIENT_MATERIAL
           * FIVEFOLD_REPETITION
           * SEVENTYFIVE_MOVES

         Variant endings (GameResult values):
           * ATOMIC_WHITE / ATOMIC_BLACK      (opponent king explodes)
           * KOTH_WHITE / KOTH_BLACK          (king reaches d4/e4/d5/e5)
           * THREE_CHECK_WHITE / THREE_CHECK_BLACK  (deliver 3 checks)
           * ANTICHESS_WHITE / ANTICHESS_BLACK  (lose all pieces to win)
           * RK_WHITE / RK_BLACK              (king reaches 8th rank)
           * DRAW                             (variant-specific draw)

         Other GameResult values (set elsewhere):
           * OUT_OF_TIME         (flag fall -- set by background timer)
           * ABORT               (game aborted by user)
           * WIN_WHITE / WIN_BLACK  (resignation)
                                 |
              +------------------+------------------+
              |                                      |
         GAME_ENDS                                 False
              |                                      |
   [Game-end processing -> section O]      Continue to E

===============================================================================

+----------------------------------------------------------------------------+
| E. TUTOR ENGINE -- ANALYSE USER MOVE                                       |
|    (PicoCoach * PicoWatcher * PicoExplorer)                               |
+----------------------------------------------------------------------------+
                                |
                                V
   PicoChess runs TWO independent UCI engines simultaneously:

     1) Playing engine  -- the opponent; produces bestmove (sections G--H).
     2) Tutor engine    -- a second engine (picotutor.py) devoted entirely
                          to position analysis and coaching.

   The tutor engine binary is configured separately (--tutor-engine).
   Internally it spawns two search instances from the same binary:
     * best_engine   (deep search, DEEP_DEPTH ~ 17 plies, more threads)
     * obvious_engine (shallow search, LOW_DEPTH ~ 5 plies, fewer threads)
   These run on separate UciEngine objects so they can search concurrently.

   Three independently toggleable features use the tutor engine:

   +--------------+--------------------------------------------------------+
   | PicoCoach    | Evaluates the user's move immediately after push.     |
   | (coach_on)   | Compares the move to the tutor engine's best line.    |
   |              | Assigns a NAG symbol: !! / ! / !? / ?! / ? / ??       |
   |              | On blunder/mistake: displays threat + hint move on    |
   |              | the DGT clock and web GUI.                            |
   |              | Three sub-modes: OFF, ON, LIFT.                        |
   |              | COACH_LIFT: "King-lift hint" -- see below.              |
   +--------------+--------------------------------------------------------+
   | PicoWatcher  | Continuously evaluates ALL legal moves in the         |
   | (watcher_on) | current position while the user is thinking.          |
   |              | Feeds eval/score/depth into the DGT display rotation  |
   |              | and the web GUI.                                      |
   |              | Binary on/off.                                        |
   +--------------+--------------------------------------------------------+
   | PicoExplorer | Looks up the current position in the opening book     |
   | (explorer_on)| (chess-eco_pos.txt, opening_name_fen.txt).            |
   |              | Displays ECO code, opening name, and book moves.      |
   |              | Also surfaces alternative best moves from the tutor   |
   |              | engine (within ALTERNATIVE_TH centipawns of best).    |
   |              | Binary on/off.                                        |
   +--------------+--------------------------------------------------------+

   These features are NOT mutually exclusive -- any combination can be
   active at the same time.  They are toggled from the DGT menu or web
   settings; set_status() activates/deactivates them on the PicoTutor
   instance.

   KING-LIFT HINT (PicoCoach COACH_LIFT mode, physical board only)
   ----------------
   During the user's turn, lifting the king off the board requests a
   position analysis -- a "hint" -- without making a move.

   Trigger sequence:
     1. User lifts king -> board FEN changes (king disappears).
     2. Board fires Event.FEN -> process_fen() starts the 4 s FEN timer
        (the position is not legal, so no move is matched).
     3. expired_fen_timer() fires after 4 s -> compare_fen() detects
        that exactly one king is missing from its home square
        -> sets coach_triggered = True.
     4. User places king back -> board FEN matches the pre-lift position
        -> process_fen() sees a valid position AND coach_triggered is set.
     5. call_pico_coach() is invoked -> picotutor.get_pos_analysis():
          * Tutor engine analyses the current position (deep search).
          * Returns: best move, score (centipawns), and up to 3
            alternative moves within ALTERNATIVE_TH of best.
     6. Results are displayed on the DGT clock (scrolling text) and
        web GUI: "Hint: Nf3  Score: +0.42".
     7. coach_triggered is reset to False.

   Conditions:
     * PicoCoach sub-mode must be COACH_LIFT (not OFF or ON).
     * Physical DGT board only (king lift is not detected on web/GUI).
     * Must be the user's turn.
     * Only works when a game is in progress (not during setup).

   After the user move is pushed (step C):
     * PicoCoach: picotutor.push_move() -> get_user_move_eval()
       -> display PICOTUTOR_MSG with NAG + optional threat/hint.
     * PicoWatcher: eval_legal_moves() runs in the background,
       updating displayed scores each second.
     * PicoExplorer: opening book lookup + alt-move list updated.
                                |
                                V
                          Continue to F

===============================================================================

+----------------------------------------------------------------------------+
| F. CLOCK MANAGEMENT (after USER move)                                      |
+----------------------------------------------------------------------------+
                                 |
                                 V
         stop_search_and_clock()
            +-> stop_internal(): elapsed = time.time() - start_time
               internal_time[color] -= elapsed
                                 |
                                 V
         add_time(color) -> adds Fischer increment (if Fischer mode)
                                 |
                                 V
         Build UCI time dict from internal_time -> wtime/btime/winc/binc

   Mode note: Clock management (F) only applies to modes that run the
   clock: NORMAL, BRAIN, TRAINING, REMOTE.  In clockless modes
   (ANALYSIS, KIBITZ, OBSERVE, PONDER, PGNREPLAY) this step is skipped.

   -- MODE BRANCH POINT ----------------------------------------------
   After section F (or D if clock is skipped), the cycle diverges:

     * eng_plays() modes (NORMAL, BRAIN, TRAINING):
         -> Continue to G (UCI engine communication).
         -> Full cycle: G -> H -> I -> J -> K -> L -> M -> N.

     * Analysis modes (ANALYSIS, KIBITZ, OBSERVE, PONDER):
         -> Engine runs analyse() -- infinite search, displays eval/PV.
         -> No bestmove is produced.  Sections G--J are SKIPPED.
         -> Jump directly to N (wait for next user move).

     * REMOTE:
         -> No engine at all.  Sections G--L are SKIPPED.
         -> Jump directly to N (wait for next user move from opponent).

     * PGNREPLAY:
         -> No engine search.  Next move comes from the PGN file.
         -> Jump directly to N.
   --------------------------------------------------------------------

===============================================================================

+----------------------------------------------------------------------------+
| G. UCI ENGINE COMMUNICATION                                                |
+----------------------------------------------------------------------------+
                                 |
                                 V
   python-chess engine.play() sends position via UCI protocol.
   Format chosen automatically by python-chess:
      * "position startpos moves <...>"
            when root position == standard starting FEN
      * "position fen <FEN> moves <...>"
            for any other position (setup, variant, or 960)
   Move history always appended from board.move_stack.
   For variants the variant board (e.g. AtomicBoard, ThreeCheckBoard)
   is passed to the engine -- its own move_stack is kept in sync with
   the main game board via push_move()/pop_move().
                                 |
                                 V
        Send engine search command:  "go wtime ... btime ..."

===============================================================================

+----------------------------------------------------------------------------+
| H. ENGINE THINKS                                                           |
+----------------------------------------------------------------------------+
                                 |
                                 V
                    Engine -> "info depth ... score ..."
                                 |
                                 V
                     Engine -> "bestmove X"
                                 |
                                 V
             engine_move = chess.Move.from_uci(X)

   BRAIN mode: after producing bestmove, the engine also returns
   "bestmove X ponder Y".  PicoChess immediately starts a speculative
   search on move Y ("go ponder ...").  When the user's next move
   arrives (section B):
     * If user plays Y -> "ponderhit" -- engine continues its search
       with confirmed time parameters (very fast response).
     * If user plays anything else -> "pondermiss" -- engine stops the
       speculative search and restarts from the new position.

===============================================================================

+----------------------------------------------------------------------------+
| I. ANNOUNCE ENGINE MOVE TO USER (BEFORE push)                              |
+----------------------------------------------------------------------------+
                                 |
                                 V
    DisplayMsg.show() broadcasts Message.COMPUTER_MOVE to ALL registered
    display handlers. Each handler checks the message's "devs" set
    (e.g. {"ser","i2c","web"}) against its own name; handlers whose
    name is not in "devs" silently skip the message. Only devices that
    were instantiated at startup are registered (no wasted queuing).

    Output devices (when registered):
       * DGT3000 / DGT XL / DGTPi (text display, devs="ser"/"i2c")
       * LEDs on board (FROM->TO squares)
       * Web GUI board + move list (devs="web")
       * Speech output (picotalker), if enabled
                                 |
                                 V
    Set done_computer_fen + done_move (expected board state after move)

===============================================================================

+----------------------------------------------------------------------------+
| J. EXECUTE engine_move INTERNALLY (python-chess)                           |
|    -- or user overrides with an ALTERNATIVE MOVE                            |
+----------------------------------------------------------------------------+
                                 |
                                 V
       +-------------------------+--------------------------+
       |                                                     |
   Physical board                                      Web / NoeBoard
       |                                                     |
   Wait for user to physically                     board.push(engine_move)
   execute engine_move on board                    happens immediately
   (sensor must confirm FEN ==                           |
    done_computer_fen)                                   |
       |                                                     |
   board.push(engine_move)                                   |
   (turn switches inside push)                               |
       +-------------------------+--------------------------+
                                 |
                                 V

   ALTERNATIVE MOVE (physical board only, when altmove is enabled):
   ----------------
   Instead of executing the announced engine_move, the user may play
   a DIFFERENT legal move on behalf of the engine (e.g. to explore a
   different continuation).

   Conditions (all must be true):
     * The resulting FEN is in legal_fens_pico (legal from engine's turn)
     * The FEN \!= done_computer_fen (it is not the announced move)
     * Mode is NORMAL or BRAIN  (not available in other modes)
     * altmove is enabled in the DGT menu / settings
     * Not in online, emulation, or PGN mode

   What happens:
     1. Display "ALTERNATIVE MOVE" on clock / web
     2. Pop the announced engine move from PicoTutor
        (keeps tutor board in sync)
     3. board.push(alternative_move) instead
     4. Check for game end
     5. If game continues -> engine searches again from
        the new position (back to G)

   The alternative-move button (DGT play/pause while engine move
   is pending, or web menu button) can also fire
   Event.ALTERNATIVE_MOVE explicitly.  This cancels the announced
   engine move and triggers a fresh engine search from the current
   position (back to G).
                                 |
                                 V

===============================================================================

+----------------------------------------------------------------------------+
| K. GAME-OVER CHECK (after engine move is pushed)                           |
+----------------------------------------------------------------------------+
                                 |
                                 V
                     check_game_state() ?
               +------------------+------------------+
               |                                      |
             Yes                                     No
               |                                      |
  [Game-end processing -> section O]        Continue to L

===============================================================================

+----------------------------------------------------------------------------+
| L. TUTOR ENGINE -- ANALYSE ENGINE MOVE                                     |
+----------------------------------------------------------------------------+
                                |
                                V
   Same tutor engine hooks as E, now for the engine's move:
     * PicoCoach:    picotutor.push_move() -> track engine's move in tutor history.
     * PicoWatcher:  eval_legal_moves() re-runs for the new position,
                     updating displayed scores for the user's upcoming turn.
     * PicoExplorer: opening book re-lookup for new position.
                                |
                                V
                          Continue to M

===============================================================================

+----------------------------------------------------------------------------+
| M. CLOCK MANAGEMENT (after engine move is executed)                        |
+----------------------------------------------------------------------------+
                                 |
                                 V
                   add_time(color) -> adds Fischer increment (if Fischer mode)
                   Start clock for user's turn (start_internal)
             (NO time-loss check -- handled by background process)

===============================================================================

+----------------------------------------------------------------------------+
| N. LOOP BACK (next user move)                                              |
+----------------------------------------------------------------------------+
                                 |
                                 V
                               Back to B

===============================================================================

+----------------------------------------------------------------------------+
| O. GAME-END PROCESSING (when check_game_state() returns GAME_ENDS,        |
|    Event.DRAWRESIGN fires, or Event.OUT_OF_TIME fires)                     |
+----------------------------------------------------------------------------+

   Steps D and K can end the game (checkmate, stalemate, variant win,
   insufficient material, repetition, 75-move rule).  Flag-fall
   (Event.OUT_OF_TIME) and user resignation/draw (Event.DRAWRESIGN)
   also land here.  The following happens in order:

   1. STOP ENGINE + CLOCK
   ----------------------
      stop_search_and_clock()  (picochess.py)
        -> stop_search():  send UCI "stop" to playing engine
        -> stop_clock():
            * time_control.stop_internal()
              (freezes the internal timer for that player)
            * Message.CLOCK_STOP broadcast to DGT clock + web

   2. MAP GameResult -> PGN RESULT STRING
   --------------------------------------
      GameResult enum is translated to one of "1-0", "0-1", "1/2-1/2":

        DRAW / STALEMATE / INSUFFICIENT_MATERIAL /
          FIVEFOLD_REPETITION / SEVENTYFIVE_MOVES        -> "1/2-1/2"
        WIN_WHITE / THREE_CHECK_WHITE / KOTH_WHITE /
          ATOMIC_WHITE / RK_WHITE / ANTICHESS_WHITE      -> "1-0"
        WIN_BLACK / THREE_CHECK_BLACK / KOTH_BLACK /
          ATOMIC_BLACK / RK_BLACK / ANTICHESS_BLACK      -> "0-1"
        MATE / OUT_OF_TIME                               -> depends on
                                                           game.turn
                                                           (loser's turn)

      Stored via ModeInfo.set_game_ending(result=<string>).

   3. BROADCAST Message.GAME_ENDS
   ------------------------------
      DisplayMsg.show(Message.GAME_ENDS(...)) delivers the result to
      every registered display consumer.  Each handles it:

      a) DGT Display (dgt/display.py):
         * Show translated result text on DGT clock (1 s).
         * Reset time counter and last-player tracking.

      b) Web Display (server.py):
         * Store result_sav, push updated PGN + result to web
           clients via EventHandler.write_to_clients().
         * Update shared["headers"]["Result"].

      c) PGN Display (pgn.py) -- THE MAIN FILE-WRITING STEP:
         Conditions: game has >= 1 move, not PGN-replay mode,
                     not PONDER mode.
         -> _save_and_email_pgn(message):

           i.   Build chess.pgn.Game from board + move_stack.
           ii.  Populate PGN headers (see header table below).
           iii. add_picotutor_evaluation():
                  Annotate moves with PicoTutor NAGs and comments
                  (e.g. "! Best: Nf3  Score: +0.5  CPL: 12").
           iv.  Merge with shared["headers"] + ensure_important_headers().
           v.   Write games/last_game.pgn   (overwrite -- always the
                                              most recent game).
           vi.  Append to games/games.pgn   (cumulative log of all
                                              games played).
           vii. emailer.send():
                  If configured, email the PGN via Mailgun API or
                  SMTP with the PGN file attached.

         Special case: in PGNREPLAY mode, saves to
         games/last_replay.pgn instead.
         In PONDER mode, PGN is NOT saved at all (analysis only).

      d) PicoTalker (picotalker.py):
         * Speak the result (if speech enabled).

   4. PGN HEADER TABLE
   -------------------
      Header              Source
      ----------------- ------------------------------------------
      Event               "PicoChess Game" (or + engine for online)
      Site                 geo-IP location string
      Date / Time          date & clock at game start
      Result               ModeInfo.get_game_ending()
      White / Black        user_name vs. engine_name (+/- level)
      WhiteElo / BlackElo  user Elo & engine Elo (adaptive if applicable)
      PicoTimeControl      time control string (e.g. "300 5")
      PicoRemTimeW/B       remaining seconds per side at game end
      PicoDepth            fixed depth (if depth mode)
      PicoNode             node limit (if node mode)
      PicoRSpeed           emulation speed (if emulation mode)
      PicoOpeningBook      book filename
      Opening              opening name from PicoExplorer
      ECO                  ECO code from PicoExplorer
      Variant              set for non-standard variants:
                             "Atomic", "Three-Check", "Crazyhouse",
                             "King of the Hill", "Antichess", "Horde",
                             "Racing Kings"
      (move comments)      PicoTutor NAGs + eval text per move

   5. POST-GAME CLEANUP
   --------------------
      * game_declared = True       (prevents duplicate end processing)
      * stop_fen_timer()           (cancel any pending 4 s FEN timer)
      * legal_fens_after_cmove = [] (clear stale legal-FEN lists)
      * update_elo(result):
          If the engine is adaptive, recalculate the user's
          rating via engine.update_rating() (Elo adjustment).

===============================================================================

+----------------------------------------------------------------------------+
| P. BACKGROUND PROCESSES (always running)                                   |
+----------------------------------------------------------------------------+

Timers (all use AsyncRepeatingTimer from utilities.py):

   1) Flag-Fall Timer (timecontrol.py, one-shot)
      Started when a player's clock begins.
      Interval = internal_time[color] (i.e. remaining seconds).
      On expiry -> fire Event.OUT_OF_TIME -> GAME OVER (flag fall).

   2) DGT Board Watchdog (dgt/board.py, 1 s repeating)
      Monitors DGT serial connection; resends clock commands
      (max 3 attempts); periodically requests board serial number.

   3) DGT Version/Handshake Retry (dgt/board.py, 2 s repeating)
      Retries board/clock version handshake during initialisation.
      Stops after successful handshake.

   4) Field Timer (dgt/board.py, 0.25--1.0 s one-shot)
      Debounces rapid piece movements on DGT serial boards before
      requesting the full board position.

   5) FEN Timer (picochess.py, 4 s one-shot)
      After an unrecognised board position, waits 4 s before showing
      "set pieces" error on the DGT display.

   6) Background Analysis Timer (picochess.py, 1 s repeating)
      Periodically triggers the TUTOR ENGINE analysis
      (PicoCoach / PicoWatcher / PicoExplorer) while a game is
      in progress.  This is NOT the playing engine -- it is the
      second engine managed by picotutor.py (see E / L above).

   7) DGT Display Timer (dgt/display.py, 1 s repeating)
      Rotates ponder info, depth/score readouts on the DGT clock.

   8) Virtual Web Clock (server.py, 1 s repeating)
      Decrements the web-browser clock display each second;
      detects flag-fall for the web clock.

   9) Display Message Timeout (dispatcher.py, variable one-shot)
      Auto-clears a DGT display message after its maxtime expires.

Message consumers (long-running async queue loops):

  10) Event Consumer (picochess.py) -- main game event loop
  11) DGT Display Consumer (dgt/display.py)
      Also processes clock button presses (Message.DGT_BUTTON):
      _process_button() routes to _process_button0()--_process_button4()
      for menu navigation, confirm/select, pause/resume, switch sides.
  12) Web Display Consumer (server.py)
  13) PicoTalker Consumer (picotalker.py) -- speech output
  14) PGN Display Consumer (pgn.py) -- game recording
  15) Dispatcher Consumer (dispatcher.py) -- DGT message routing
  16) WebVr DGT Consumer (server.py) -- web clock API
  17) DGT Hardware Consumer (dgt/iface.py) -- DgtPi / DgtHw

Hardware / board polling (blocking reads wrapped in async tasks):

  18) DGT Board serial reader (dgt/board.py) -- USB/Bluetooth
      Also detects clock button presses: _process_board_message()
      recognises DgtAck.DGT_ACK_CLOCK_BUTTON, parses a 3-byte ACK
      to identify buttons 0--4 + lever, and queues
      Message.DGT_BUTTON(button=N, dev="ser").
  19) DGT Pi I2C clock poller (dgt/pi.py)
      process_incoming_clock_forever() polls dgtpicom_get_button_message()
      and maps bitmask values (0x01--0x20) to buttons 0--4 + on/off +
      lever.  Fires Message.DGT_BUTTON(button=N, dev="i2c").
  20) Certabo board poller (eboard/certabo/)
  21) ChessLink board poller + reconnect task (eboard/chesslink/)
  22) Chessnut board poller (eboard/chessnut/)
  23) iChessOne board poller (eboard/ichessone/)

Other:

  24) Engine Force Watchdog (uci/engine.py) -- cancels hung engine
  25) Continuous Analysis loop (uci/engine.py) -- infinite analysis stream
  26) Board Connection Waiter (picochess.py) -- startup synchronisation
  27) Pairing Bridge IPC server (pairing_ipc.py) -- Unix socket server

Tutor engine (picotutor.py) -- second UCI engine:

  28) best_engine (UciEngine)    -- deep search (~ 17 plies, more threads)
  29) obvious_engine (UciEngine) -- shallow search (~ 5 plies, fewer threads)
      Both run the same tutor engine binary (--tutor-engine) but as
      independent UciEngine instances so they can search concurrently.
      They serve PicoCoach, PicoWatcher, and PicoExplorer (see E/L).
===============================================================================
```

---

# End of Markdown Document
