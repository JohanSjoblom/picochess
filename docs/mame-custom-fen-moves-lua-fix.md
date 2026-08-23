# MAME Lua fix for custom FEN positions with move history

## Summary

Picochess can send a UCI position containing both a custom starting FEN and a
move list:

```text
position fen <custom FEN> moves <move1> <move2> ...
```

The existing MAME `chessengine` Lua plugin changes this into a start-position
command. This discards the custom FEN and applies the moves to the standard
chess starting position.

The tested `init.lua` correction fixes that behavior. It sets up the emulated
board from the custom FEN first and then applies the supplied moves to that
position.

This is needed primarily for these Picochess actions:

- **Position -> Set Pos** after selecting a position from a game that started
  from a custom FEN.
- **Read Game** when the PGN contains both a `FEN` header and moves.

**Position -> Scan** is different: an eboard scan supplies only a position and
has no move history.

## File location

The installed plugin is normally located at:

```text
/opt/picochess/engines/mame_emulation/plugins/chessengine/init.lua
```

The Lua plugin is in the shared `mame_emulation` directory, not in an
architecture-specific engine directory. This correction has currently been
tested with the x86-64 MAME executable and Mephisto MM V. Testing on other
architectures and with other emulated chess computers is welcome.

The SHA-256 checksum of the `init.lua` version tested on 21 August 2026, after
Changes 1-3 below, is:

```text
16034358af0ef4a9a842834dd3a4c4db5181ee3a11fe9760ae0882507cc657c0
```

The MM V waiting-for-`go` proof of concept in Change 4 produces:

```text
1d04990a894e1b94d5c105bb1ea0e34150879dfef35cce5f29a97e949ebbf10b
```

This second checksum is pending the artwork tests described below. Keep the
first checksum as the tested rollback point while evaluating the proof of
concept.

Before replacing the installed file, keep a backup. If your `init.lua` is
newer or substantially different, apply the changes below to your version
instead of replacing the complete file.

## Change 1: preserve and set up the custom FEN

### Before

```lua
if cmd:match("^position fen ") ~= nil then
  if board == nil then
    board_reset()
  end
  m = cmd:find("moves ")
  if m ~= nil then
    --manager.machine:popmessage("position fen moves found")
    cmd = "position startpos " .. cmd:sub(m)
  else
    if interface.set_pos then
      editmode = 0
      if game_started == false then
        local throttle_state = manager.machine.video.throttled
        manager.machine.video.throttled = false
        emu.wait(1)
        local tag=interface.set_pos(0)
        if tag:sub(1,7) == "ERROR: " then
          manager.machine.video.throttled = throttle_state
          emu.print_error(tag)
          editmode = -1
          send_cmd("bestmove ----")
          return
        else
          sb_setup_board(tag, cmd:sub(14))
          if ply == "B" then
            interface.set_pos(-1)
          else
            interface.set_pos(1)
          end
          emu.wait(1)
          manager.machine.video.throttled = throttle_state
          game_started = true
          manager.machine:popmessage("Position setup is complete!")
        end
      end
      return
    else
      emu.print_error("ERROR: 'Setup' mode is not supported by '" .. module .. "'!")
      editmode = -1
      send_cmd("bestmove ----")
      return
    end
  end
end
```

### After

```lua
if cmd:match("^position fen ") ~= nil then
  if board == nil then
    board_reset()
  end
  m = cmd:find("moves ")
  if interface.set_pos then
    editmode = 0
    if game_started == false then
      local throttle_state = manager.machine.video.throttled
      manager.machine.video.throttled = false
      emu.wait(1)
      local tag=interface.set_pos(0)
      if tag:sub(1,7) == "ERROR: " then
        manager.machine.video.throttled = throttle_state
        emu.print_error(tag)
        editmode = -1
        send_cmd("bestmove ----")
        return
      else
        sb_setup_board(tag, cmd:sub(14))
        if ply == "B" then
          interface.set_pos(-1)
        else
          interface.set_pos(1)
        end
        emu.wait(1)
        manager.machine.video.throttled = throttle_state
        game_started = true
        if m ~= nil then
          lastpos = cmd:sub(1, m + 4)
        else
          lastpos = cmd .. " moves"
        end
        manager.machine:popmessage("Position setup is complete!")
      end
    end
    if m == nil then
      return
    end
  else
    emu.print_error("ERROR: 'Setup' mode is not supported by '" .. module .. "'!")
    editmode = -1
    send_cmd("bestmove ----")
    return
  end
end
```

The original code replaces a custom-FEN command containing moves with
`position startpos moves ...`. The corrected code instead sets up the custom
FEN and records the correct position prefix in `lastpos`.

For a FEN without moves, it initializes `lastpos` as the custom FEN followed by
the UCI `moves` separator. This prevents a subsequent move from being compared
with stale start-position state.

## Change 2: recognize custom-FEN commands containing moves

### Before

```lua
elseif cmd:match("^position startpos moves ") ~= nil then
```

### After

```lua
elseif cmd:match("^position startpos moves ") ~= nil or
       cmd:match("^position fen .+ moves ") ~= nil then
```

This allows the existing move-replay code to process moves following a custom
FEN.

## Change 3: ignore an identical repeated position

### Before

```lua
elseif (last_move == prev_move) then
```

### After

```lua
-- Repeating an identical UCI position must be a no-op. This happens when
-- Picochess sets up a PGN position and python-chess sends the same position
-- again immediately before go.
elseif (cmd == lastpos or last_move == prev_move) then
```

Picochess sends a position immediately during MAME setup. Python-chess may send
the identical position again immediately before asking the engine to move.
Treating an identical command as a no-op prevents the final move from being
entered twice in the emulated chess computer.

## Change 4: keep MM V idle until UCI `go` (proof of concept)

Set Pos sends the position eagerly so that the MAME engine and artwork are
synchronized before the next user action. This sequence deliberately contains
no `go`:

```text
ucinewgame
position startpos moves ...
isready
```

The original `play_moves()` assumes that replaying a move stack is immediately
followed by `go`. It therefore calls `interface.start_play(false)` itself. For
MM V, `start_play()` presses `ENT`, causing the emulated computer to calculate
and display an extra move in the artwork even though Picochess has not asked it
to move.

The proof of concept adds this helper before `play_moves()`:

```lua
local function wait_for_go()
  -- Keep the emulated computer idle after synchronizing a position.  A UCI
  -- position command must not start a search; execute_uci_command("go") will
  -- assign the current ply to the emulated computer when Picochess asks it to
  -- move.
  if ply == "W" then
    my_color = "B"
  else
    my_color = "W"
  end
  piece_get = false
  piece_from = nil
  piece_to = nil
  sel_started = false
end
```

At the end of `play_moves()`, replace:

```lua
if interface.start_play then
  interface.start_play(false)
  my_color = ply
end
```

with:

```lua
if module == "mm5" then
  -- Proof of concept: Set Pos may replay a move stack without an immediate
  -- go.  Do not let MM V start playing merely because replay has finished.
  wait_for_go()
elseif interface.start_play then
  interface.start_play(false)
  my_color = ply
end
```

The identical-position branch from Change 3 must also wait instead of starting
MM V. Replace its body with:

```lua
if module == "mm5" then
  wait_for_go()
else
  my_color = ply
  sel_started = false
  if interface.start_play then
    interface.start_play(not game_started)
  end
end
```

`ply` remains the actual side to move. Setting `my_color` to the opposite side
does not alter the FEN, move stack, backend position, or artwork. It only keeps
the Lua move detector idle. When Picochess later requests a move after a user
move or Switch Sides, the existing `go` handler calls `start_play()` and sets
`my_color = ply`.

The `module == "mm5"` condition intentionally limits this first test to
Mephisto MM V. If the test succeeds, the waiting behavior can be evaluated as
the generic UCI rule for all interfaces: `position` synchronizes state, while
only `go` starts calculation. `mm4.lua` is not changed.

## Successful test

The corrected plugin was tested with Mephisto MM V using this sequence:

1. Scan a custom position from the physical eboard.
2. Continue playing from that position.
3. Select the historical position after `...Qxd1` in the web client.
4. Use **Position -> Set Pos**.
5. Arrange the physical board and receive the Picochess OK announcement.
6. Play `Rxd1`.
7. MM V continues normally and replies with `...Nxe4`.

The successful test contained no Lua errors, UCI protocol-state errors,
readiness failures, or engine crashes.

## MM V artwork proof-of-concept test

Change 4 still needs to be verified with `rdisplay = true`:

1. Play through `1.e4 c6 2.d4 d5 3.e5 Bf5 4.Nf3 e6 5.Be2 Nd7 6.O-O c5`.
2. Use **Position -> Set Pos** at the position after `6...c5`.
3. Wait longer than MM V normally needs to move. The artwork must remain at
   the requested position and must not add `7.Bb5` or another move.
4. Make a White move other than `Bb5`. MM V must then receive the real `go`,
   reply once, and remain synchronized with the backend, web client, and
   artwork.
5. Repeat Set Pos and use Switch Sides. MM V must remain idle before the switch
   and make exactly one legitimate move afterward.
6. Repeat from a position containing an odd number of half-moves to verify both
   sides to move.
7. Confirm that FEN-only Scan remains idle and continues normally after a user
   move or Switch Sides.

## Compatibility and rollback

Changes 1-3 affect MAME positions with custom FEN roots and move history.
Change 4 is currently limited to MM V and affects a replayed move stack with
either a standard or custom root. The relevant proof-of-concept case requires:

- Mephisto MM V through MAME;
- a non-empty move history; and
- an action such as Set Pos or Read Game that sends the history without an
  immediate `go`.

FEN-only Scan does not call `play_moves()` and is not changed by this proof of
concept.

Picochess will preserve and send the move stack for these operations once its
corresponding update is installed. Therefore, image builders should distribute
this Lua correction together with that Picochess update.

If Change 4 causes problems, restore the tested Changes 1-3 `init.lua` with
checksum `16034358af0ef4a9a842834dd3a4c4db5181ee3a11fe9760ae0882507cc657c0`.
If the custom-FEN move-history handling itself causes problems, restore the
original plugin and revert the matching Picochess move-history commit so that
MAME positions are again sent without a move suffix.
