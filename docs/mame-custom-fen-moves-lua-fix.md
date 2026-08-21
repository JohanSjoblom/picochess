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

The SHA-256 checksum of the `init.lua` version tested on 21 August 2026 is:

```text
16034358af0ef4a9a842834dd3a4c4db5181ee3a11fe9760ae0882507cc657c0
```

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

## Compatibility and rollback

Normal play from the standard starting position is unaffected. The relevant
case requires all of the following:

- a MAME engine;
- a custom starting FEN;
- a non-empty move history; and
- an action such as Set Pos or Read Game that sends that history.

Picochess will preserve and send the move stack for these operations once its
corresponding update is installed. Therefore, image builders should distribute
this Lua correction together with that Picochess update.

If problems are found, restore the previous `init.lua` and revert the matching
Picochess move-history commit so that MAME positions are again sent without a
move suffix.
