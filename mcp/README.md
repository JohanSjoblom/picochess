# PicoChess MCP server (experimental)

This folder contains a small [Model Context Protocol](https://modelcontextprotocol.io/) server
that lets Claude Code, or another MCP client, play chess against a running PicoChess. It talks to
the PicoChess web server through the same HTTP endpoints as the browser client, so PicoChess itself
needs no changes.

The server runs on the same machine as the MCP client and reaches PicoChess at
`http://localhost:8080` by default.

## Tools

| Tool | What it does |
|---|---|
| `get_engine` | Returns the engine PicoChess is using, for example `Stockfish 19`, its Elo when known, and its level, for example `Elo@2200`. Read-only. |
| `list_engines` | Lists the installed engines with their Elo, menu category (modern or retro) and levels. Read-only. |
| `set_engine` | Changes the engine, its level, or both, like the web client's Engine menu. A level can be given as `Elo@1800` or `1800`. A game in progress continues, except that a retro engine starts a new game. Returns once the engine has restarted. |
| `get_game` | Describes the current game: whose turn it is and what happens next, the last move and who played it, the moves so far, a text board diagram, FEN and PGN. Also the opening, and PicoTutor's feedback: the moves its Watcher marked or found inaccurate, with the better move, and its verdict on the user's latest move. Works with and without an e-board. Read-only. |
| `get_hint` | Suggests the best move in the current position, like the clock's + button (button 3): the move in SAN, the expected continuation, up to two other candidates, the search depth and the source (Tutor or engine). Read-only. |
| `get_top_moves` | Lists the best moves from PicoChess's analysis of the current position, as in the web client: for each, the move, an evaluation, the depth and the continuation. Three lines in analysis mode and in play mode on the user's turn with the Tutor on; one line otherwise, including while the engine is thinking. Read-only. |
| `get_evaluation` | Evaluates the current position, like the clock's - button (button 1): an assessment in words, centipawns from White's point of view or a mate count, the score from the user's point of view, the depth and the source. Does not reveal the best move. Read-only. |
| `make_move` | Plays the user's move. In play mode it waits for the engine's reply; in analysis mode the user enters moves for both sides and there is no reply. Accepts `1. e4`, `e2-e4`, `e2e4`, `Nf3`, `O-O`, `e8=Q` and similar. Returns the moves in SAN, the new FEN, and the game so far as PGN. The first move starts the game. Without an e-board only; see below. |
| `set_mode` | Switches between `play` (Normal mode: play against the engine) and `analysis` (the menu's Analysis mode: enter moves for both sides while the engine analyses). Entering analysis mode saves the game; switching back to play returns to it, like the menu's "Return to" tile. With an e-board, PicoChess first asks the user to set the pieces back. `keep_analysis_position` continues playing from the analysed position instead. |
| `get_tutor` | Returns PicoTutor's Watcher, Coach and Explorer settings, as in the web client's Tutor menu. Read-only. |
| `set_tutor` | Turns Watcher, Coach or Explorer on or off; only the settings given change. Watcher rates each of the user's moves and points out blunders. Coach is `off`, `on`, `lift`, `brain` or `hand`; `lift` and `hand` respond to lifting pieces on an e-board. Explorer names the opening. PicoChess saves the settings, and shows the Tutor's feedback on its own displays. |
| `pause_resume_clock` | On the user's turn, pauses or resumes the game clock (`action` is `pause` or `resume`), like the web client's play/pause button. Before the first move, `resume` starts the clock and the game. Confirms the new state from the clock. Only with a game clock (blitz, Fischer or tournament time); fixed move time, depth and nodes have none. |
| `force_engine_move` | While the engine is thinking, makes it play the best move found so far, like "Move now" in the web client. Without an e-board it returns the engine's move; with one, PicoChess shows the move on its displays. |
| `request_alternative_move` | With an e-board only: asks the engine to replace the move it has chosen but that is not yet made on the board, like the web client's play/pause button. The engine searches again without the moves it already proposed, and PicoChess shows the new move on its displays. |
| `set_position` | Replaces the current game with the position in a FEN, like Position > Set Pos in the web client. With an e-board, PicoChess then guides the user by voice to set up the pieces. |
| `scan_board` | With an e-board only: replaces the current game with the position on the board, like Position > Scan. Options: side to move, a reversed board, and the castling rights still allowed. |
| `play_as` | Chooses the colour the user plays, like the web client's Switch sides button. If it becomes the engine's turn, the engine moves, so choosing `black` before the first move lets the engine open. Play mode only. |
| `take_back` | Takes back the user's latest move: after the engine's reply both moves, so it is the user's turn again, or a given number of half-moves. With an e-board, the user takes the moves back on the board too. |
| `new_game` | Starts a new standard chess game, discarding any game in progress. |
| `resign_game` | Resigns the current game, so the engine wins. Returns the final result and PGN. |

`new_game`, `resign_game`, `set_position` and `scan_board` replace or end the game. They are marked destructive, so Claude Code asks before running them.

## Requirements

- PicoChess running on the same machine.
- To play moves through the MCP, `board-type = noeboard` in `picochess.ini`. With an e-board
  connected, moves are made on the board, as with the web client: `make_move` refuses, and the
  other tools work as a remote front end for information and game actions.
- A 64-bit CPython 3.10 or newer. PicoChess uses 3.13.
- [Claude Code](https://code.claude.com/), or another MCP client that can start a local stdio
  server.

The server uses its own virtual environment, `mcp/.venv`, which is ignored by Git. It does not
change PicoChess's `venv`.

## Setup on Windows

From the PicoChess folder:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\mcp\setup-mcp-windows.ps1 -Register
```

The script creates or reuses `mcp\.venv`, installs `mcp\requirements.txt`, checks the imports,
and registers the server with Claude Code as `picochess`. Leave out `-Register` to only prepare
the environment; the script then prints the registration command. Other options:

- `-PicoChessUrl http://host:port` registers the server for a PicoChess at another address.
- `-RecreateVenv` deletes `mcp\.venv` and creates it again.

## Setup on Linux and macOS

From the PicoChess folder:

```bash
python3 -m venv mcp/.venv
mcp/.venv/bin/python -m pip install -r mcp/requirements.txt
claude mcp add picochess -- "$PWD/mcp/.venv/bin/python" "$PWD/mcp/server.py"
```

## Registration

`claude mcp add` uses local scope by default: the server is available to you when Claude Code
runs in this PicoChess folder. Add `-s user` to make it available everywhere. Check it with
`claude mcp get picochess`, and remove it with `claude mcp remove picochess -s local`.

To reach PicoChess at another address, register it with `-e PICOCHESS_URL=http://host:port`.

## Claude Desktop

Claude Desktop can use the same server, but it does not read Claude Code's registration. Prepare
`mcp/.venv` first, with the Windows setup script (without `-Register`) or the Linux and macOS
commands above. Then add the server to Claude Desktop's configuration:

1. In Claude Desktop, open **Settings > Developer > Edit Config**. This opens
   `claude_desktop_config.json`: `%APPDATA%\Claude\` on Windows, or
   `~/Library/Application Support/Claude/` on macOS.
2. Add a `picochess` entry under `mcpServers`, with your PicoChess folder in both paths. JSON
   needs doubled backslashes in Windows paths:

   ```json
   {
     "mcpServers": {
       "picochess": {
         "command": "C:\\Users\\you\\PicoChess\\mcp\\.venv\\Scripts\\python.exe",
         "args": ["C:\\Users\\you\\PicoChess\\mcp\\server.py"]
       }
     }
   }
   ```

   If the file already has an `mcpServers` section, add only the `picochess` entry to it. To reach
   PicoChess at another address, add `"env": {"PICOCHESS_URL": "http://host:port"}` to the entry.
   On macOS, use `.../mcp/.venv/bin/python` as the command.
3. Quit Claude Desktop completely, from the system tray on Windows or the menu bar on macOS, and
   start it again. The PicoChess tools then appear in the tools menu of a new chat.

## Using it

1. Start PicoChess.
2. Start a new Claude Code session in the PicoChess folder, and check with `/mcp` that
   `picochess` is connected. In Claude Desktop, start a new chat.
3. Ask, for example, "What engine is loaded?" or "Let's play, 1. e4".

Claude Code starts the server when the session begins. After changing `server.py`, reconnect
`picochess` with `/mcp` or start a new session.

## Limitations

- Standard chess only. Variants are refused.
- Losing on time does not end a local PicoChess game, so play can continue after the flag falls.
  After resignation, checkmate or a draw, `make_move` reports that the game is over.
- With an e-board, PicoChess publishes which move the engine chose only after it has been made on
  the board. Until then `get_game` reports that a move is pending, but not which move; PicoChess
  shows it on its own displays.

## How it works

| Purpose | Request |
|---|---|
| Engine name | `GET /info?action=get_system_info` |
| Current position, PGN, last move and the Tutor's move ratings | `GET /dgt?action=get_last_move` |
| Play a move | `POST /channel` with `action=move`, `source`, `target`, `promotion` and `fen` |
| New game | `POST /channel` with `action=new_game` |
| Switch sides | `POST /channel` with `action=clockbutton` and `button=64` (the clock lever) |
| Take back a move | `POST /channel` with `action=take_back`, once per half-move |
| Installed engines and levels | `GET /info?action=get_engines` |
| Change engine or level | `POST /channel` with `action=new_engine`, `file` and `level` |
| Resign | `POST /channel` with `action=resign_game` |
| Set a position | `POST /channel` with `action=set_position` and `fen` |
| Switch mode | `POST /channel` with `action=set_mode` and `mode=normal` or `mode=ponder`. PicoChess's internal `Mode.PONDER` is the menu's Analysis mode; its `analysis` value is the menu's Move Hint mode. |
| Return from analysis mode to the saved game | `POST /channel` with `action=restore_position_checkpoint`, when `get_system_info` reports `position_checkpoint_available` |
| Scan the e-board | `POST /channel` with `action=scan_board`, `sideToPlay`, `boardSide` and the four castling flags |
| Clock state | `GET /info?action=get_clock_state` |
| Tutor settings | `GET /info?action=get_current_settings` |
| Change a Tutor setting | `POST /channel` with `action=picotutor`, `tutor=watcher`, `coach` or `explorer`, and `val` |
| Analysis for hints and evaluations | WebSocket `/event`: the snapshot PicoChess sends every new client |
| Pause or resume the clock | `POST /channel` with `action=pause_resume`, only on the user's turn |
| Move now | `POST /channel` with `action=pause_resume`, only while the engine is thinking |
| Alternative move | `POST /channel` with `action=pause_resume`, only while an engine move is pending on the e-board |

`pause_resume` is the web client's play/pause button. Its meaning depends on the game state: it
forces a move while the engine thinks, requests an alternative while an engine move is pending on
the e-board, and otherwise starts or stops the clock. The tools send it only in their own state.
If the engine finishes at the very moment the request arrives, PicoChess applies the meaning for
the new state.

The `fen` posted with a move is the position after the move, as the web client sends it.
PicoChess accepts the move only when it is legal and produces that position.

After posting a move, `make_move` polls `get_last_move` for the engine's reply. Until PicoChess
handles the new move, that endpoint still returns the previous engine reply, so a reply is
accepted only if it is legal after the user's move and produces the reported position.

`get_hint`, `get_evaluation` and `get_top_moves` read the analysis PicoChess already runs rather than pressing the
clock buttons, so nothing flashes on the clock. They connect to the web client's WebSocket, read
the messages PicoChess sends a new client (latest position, analysis and system information),
and disconnect. Each analysis carries the position it was computed for. The tools use only
analysis of the current position: after the engine moves, PicoChess keeps showing the engine's
analysis of the previous position, which would otherwise give a hint for the wrong side.

`get_game` names the opening itself, from the two lists PicoTutor's Explorer uses, `chess-eco_pos.txt` and
`opening_name_fen.txt` in the PicoChess folder: PicoChess shows the opening name only on its clock and in
saved PGN headers. Explorer names an opening only while the game is in the book; `get_game` keeps the
name of the latest known position.
