# PicoChess 4.2.2 – Complete Move Processing Cycle
### Current active development repository: https://github.com/JohanSjoblom/picochess
### February 2026

This document explains the full move cycle inside PicoChess, including:

- support for multiple electronic boards  
- GUI/keyboard move input  
- python‑chess legality checks  
- classic + variant endings  
- engine cycle  
- clock management  
- background time‑loss detection  
- and the correct sequence for engine‑move output  

---

## ASCII Flowchart

```
===============================================================================
           PICOCHESS – COMPLETE MOVE PROCESSING CYCLE (ASCII DIAGRAM)
===============================================================================

┌────────────────────────────────────────────────────────────────────────────┐
│ A. USER MAKES A MOVE (via ANY supported input source)                      │
└────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
      ┌────────────────────────────────────────────────────────────┐
      │  INPUT SOURCES (unified by PicoChess)                      │
      └────────────────────────────────────────────────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────────┬─────────────────┬───────────────┐
         │                       │                           │                 │               │
         ▼                       ▼                           ▼                 ▼               ▼
   [DGT e-board]         [Certabo e-board]       [Chessnut / ChessLink]   [iChessOne]      [NoEBoard]
         │                       │                           │                 │               │
         │                       │                           │                 │               ▼
         │                       │                           │                 │      [GUI / Web Browser]
         │                       │                           │                 │   (drag & drop or typed moves)
         │                       │                           │                 │               │
         └───────────────────────┴───────────────────────────┴─────────────────┘               │
                                 │                                                             │
                    Board drivers fire Event.FEN                              Web/GUI fires Event.REMOTE_MOVE
                   (board position changed)                                      (explicit move)
                                 └──────────────────────┬──────────────────────────────────────┘
                                 │
                                 ▼
         PicoChess matches FEN against pre-computed legal_fens
                  → candidate_move (abstracted input)

===============================================================================

┌────────────────────────────────────────────────────────────────────────────┐
│ B. LEGALITY CHECK (python-chess, variant-aware)                            │
└────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
    process_fen() checks candidate FEN in this order:
                                 │
         ┌───────────────────────┼──────────────────────────────┐
         │                       │                              │
    In legal_fens?         In game history?                Neither?
      (legal move)            (TAKEBACK)                 (illegal position)
         │                       │                              │
         ▼                       ▼                              │
   board.push(move)     Stop engine + clock.                    │
   (turn switches       Pop moves from game until            Board input:
    inside push)        board matches target FEN.              start 4-sec FEN timer;
         │              Set takeback_active = True.             if still wrong after
         │              Display "TAKEBACK" on DGT               timeout → display
         │                + show undone move (long              "set pieces" + beep.
         │                  notation) + light LEDs.           Training mode:
         │              Blocked when: online mode,              "wrong move" / "try
         │                take_back_locked, or                  again" + beep.
         │                emulation w/o auto-takeback.        Keyboard/Web:
         │              Web/NoEBoard: takeback via              silent reject (log only).
         │                menu button or Event.TAKE_BACK.
         │              Supports multi-move takeback
         │                (FEN can match any earlier
         │                 position in game history).
         │                       │
         │              Back to A (wait for next move)
         │
         ▼

===============================================================================

┌────────────────────────────────────────────────────────────────────────────┐
│ C. GAME-OVER CHECK (classic + variant rules via python-chess)              │
└────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
               check_game_state() → returns False or Message.GAME_ENDS(result)
                                 │
         Classic endings (GameResult values):
           • MATE               (checkmate)
           • STALEMATE           (stalemate)
           • INSUFFICIENT_MATERIAL
           • FIVEFOLD_REPETITION
           • SEVENTYFIVE_MOVES

         Variant endings (GameResult values):
           • ATOMIC_WHITE / ATOMIC_BLACK      (opponent king explodes)
           • KOTH_WHITE / KOTH_BLACK          (king reaches d4/e4/d5/e5)
           • THREE_CHECK_WHITE / THREE_CHECK_BLACK  (deliver 3 checks)
           • ANTICHESS_WHITE / ANTICHESS_BLACK  (lose all pieces to win)
           • RK_WHITE / RK_BLACK              (king reaches 8th rank)
           • DRAW                             (variant-specific draw)

         Other GameResult values (set elsewhere):
           • OUT_OF_TIME         (flag fall — set by background timer)
           • ABORT               (game aborted by user)
           • WIN_WHITE / WIN_BLACK  (resignation)
                                 │
              ┌──────────────────┴──────────────────┐
              │                                      │
         GAME_ENDS                                 False
              │                                      │
   [Stop clock, show result, stop engine]      Continue to D

===============================================================================

┌────────────────────────────────────────────────────────────────────────────┐
│ D. CLOCK MANAGEMENT (after USER move)                                      │
└────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
         stop_search_and_clock()
            └→ stop_internal(): elapsed = time.time() − start_time
               internal_time[color] −= elapsed
                                 │
                                 ▼
         add_time(color) → adds Fischer increment (if Fischer mode)
                                 │
                                 ▼
         Build UCI time dict from internal_time → wtime/btime/winc/binc

===============================================================================

┌────────────────────────────────────────────────────────────────────────────┐
│ E. UCI ENGINE COMMUNICATION                                                │
└────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
   python-chess engine.play() sends position via UCI protocol.
   Format chosen automatically by python-chess:
      • “position startpos moves <…>”
            when root position == standard starting FEN
      • “position fen <FEN> moves <…>”
            for any other position (setup, variant, or 960)
   Move history always appended from board.move_stack.
   For variants the variant board (e.g. AtomicBoard, ThreeCheckBoard)
   is passed to the engine — its own move_stack is kept in sync with
   the main game board via push_move()/pop_move().
                                 │
                                 ▼
        Send engine search command:  “go wtime … btime …”

===============================================================================

┌────────────────────────────────────────────────────────────────────────────┐
│ F. ENGINE THINKS                                                           │
└────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
                    Engine → “info depth ... score ...”
                                 │
                                 ▼
                     Engine → “bestmove X”
                                 │
                                 ▼
             engine_move = chess.Move.from_uci(X)

===============================================================================

┌────────────────────────────────────────────────────────────────────────────┐
│ G. ANNOUNCE ENGINE MOVE TO USER (BEFORE push)                              │
└────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
    DisplayMsg.show() broadcasts Message.COMPUTER_MOVE to ALL registered
    display handlers. Each handler checks the message's "devs" set
    (e.g. {"ser","i2c","web"}) against its own name; handlers whose
    name is not in "devs" silently skip the message. Only devices that
    were instantiated at startup are registered (no wasted queuing).

    Output devices (when registered):
       • DGT3000 / DGT XL / DGTPi (text display, devs="ser"/"i2c")
       • LEDs on board (FROM→TO squares)
       • Web GUI board + move list (devs="web")
       • Speech output (picotalker), if enabled
                                 │
                                 ▼
    Set done_computer_fen + done_move (expected board state after move)

===============================================================================

┌────────────────────────────────────────────────────────────────────────────┐
│ H. EXECUTE engine_move INTERNALLY (python-chess)                           │
└────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
       ┌─────────────────────────┴──────────────────────────┐
       │                                                     │
   Physical board                                      Web / NoeBoard
       │                                                     │
   Wait for user to physically                     board.push(engine_move)
   execute engine_move on board                    happens immediately
   (sensor must confirm FEN ==                           │
    done_computer_fen)                                   │
       │                                                     │
   board.push(engine_move)                                   │
   (turn switches inside push)                               │
       └─────────────────────────┬──────────────────────────┘
                                 │
                                 ▼

===============================================================================

┌────────────────────────────────────────────────────────────────────────────┐
│ I. GAME-OVER CHECK (after engine move is pushed)                           │
└────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
                     check_game_state() ?
               ┌──────────────────┴──────────────────┐
               │                                      │
             Yes                                     No
               │                                      │
  [Stop clock, show result, stop engine]        Continue to J

===============================================================================

┌────────────────────────────────────────────────────────────────────────────┐
│ J. CLOCK MANAGEMENT (after engine move is executed)                        │
└────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
                   add_time(color) → adds Fischer increment (if Fischer mode)
                   Start clock for user's turn (start_internal)
             (NO time-loss check — handled by background process)

===============================================================================

┌────────────────────────────────────────────────────────────────────────────┐
│ K. LOOP BACK (next user move)                                              │
└────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
                               Back to A

===============================================================================

BACKGROUND PROCESSES — ALWAYS RUNNING
─────────────────────────────────────
Timers (all use AsyncRepeatingTimer from utilities.py):

   1) Flag-Fall Timer (timecontrol.py, one-shot)
      Started when a player's clock begins.
      Interval = internal_time[color] (i.e. remaining seconds).
      On expiry → fire Event.OUT_OF_TIME → GAME OVER (flag fall).

   2) DGT Board Watchdog (dgt/board.py, 1 s repeating)
      Monitors DGT serial connection; resends clock commands
      (max 3 attempts); periodically requests board serial number.

   3) DGT Version/Handshake Retry (dgt/board.py, 2 s repeating)
      Retries board/clock version handshake during initialisation.
      Stops after successful handshake.

   4) Field Timer (dgt/board.py, 0.25–1.0 s one-shot)
      Debounces rapid piece movements on DGT serial boards before
      requesting the full board position.

   5) FEN Timer (picochess.py, 4 s one-shot)
      After an unrecognised board position, waits 4 s before showing
      "set pieces" error on the DGT display.

   6) Background Analysis Timer (picochess.py, 1 s repeating)
      Periodically triggers engine analysis (PicoTutor / PicoCoach)
      while a game is in progress.

   7) DGT Display Timer (dgt/display.py, 1 s repeating)
      Rotates ponder info, depth/score readouts on the DGT clock.

   8) Virtual Web Clock (server.py, 1 s repeating)
      Decrements the web-browser clock display each second;
      detects flag-fall for the web clock.

   9) Display Message Timeout (dispatcher.py, variable one-shot)
      Auto-clears a DGT display message after its maxtime expires.

Message consumers (long-running async queue loops):

  10) Event Consumer (picochess.py) — main game event loop
  11) DGT Display Consumer (dgt/display.py)
  12) Web Display Consumer (server.py)
  13) PicoTalker Consumer (picotalker.py) — speech output
  14) PGN Display Consumer (pgn.py) — game recording
  15) Dispatcher Consumer (dispatcher.py) — DGT message routing
  16) WebVr DGT Consumer (server.py) — web clock API
  17) DGT Hardware Consumer (dgt/iface.py) — DgtPi / DgtHw

Hardware / board polling (blocking reads wrapped in async tasks):

  18) DGT Board serial reader (dgt/board.py) — USB/Bluetooth
  19) DGT Pi I2C clock poller (dgt/pi.py)
  20) Certabo board poller (eboard/certabo/)
  21) ChessLink board poller + reconnect task (eboard/chesslink/)
  22) Chessnut board poller (eboard/chessnut/)
  23) iChessOne board poller (eboard/ichessone/)

Other:

  24) Engine Force Watchdog (uci/engine.py) — cancels hung engine
  25) Continuous Analysis loop (uci/engine.py) — infinite analysis stream
  26) Board Connection Waiter (picochess.py) — startup synchronisation
  27) Pairing Bridge IPC server (pairing_ipc.py) — Unix socket server
===============================================================================
```

---

# End of Markdown Document
