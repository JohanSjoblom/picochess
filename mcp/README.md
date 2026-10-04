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
| `get_engine` | Returns the engine PicoChess is using, for example `Stockfish 19`, and its Elo when known. Read-only. |
| `get_game` | Describes the current game: whose turn it is and what happens next, the last move and who played it, the moves so far, a text board diagram, FEN and PGN. Works with and without an e-board. Read-only. |
| `make_move` | Plays the user's move and waits for the engine's reply. Accepts `1. e4`, `e2-e4`, `e2e4`, `Nf3`, `O-O`, `e8=Q` and similar. Returns both moves in SAN, the new FEN, and the game so far as PGN. The first move starts the game. Without an e-board only; see below. |
| `pause_resume_clock` | On the user's turn, pauses or resumes the game clock (`action` is `pause` or `resume`), like the web client's play/pause button. Before the first move, `resume` starts the clock and the game. Confirms the new state from the clock. Only with a game clock (blitz, Fischer or tournament time); fixed move time, depth and nodes have none. |
| `force_engine_move` | While the engine is thinking, makes it play the best move found so far, like "Move now" in the web client. Without an e-board it returns the engine's move; with one, PicoChess shows the move on its displays. |
| `request_alternative_move` | With an e-board only: asks the engine to replace the move it has chosen but that is not yet made on the board, like the web client's play/pause button. The engine searches again without the moves it already proposed, and PicoChess shows the new move on its displays. |
| `new_game` | Starts a new standard chess game, discarding any game in progress. |
| `resign_game` | Resigns the current game, so the engine wins. Returns the final result and PGN. |

`new_game` and `resign_game` are marked destructive, so Claude Code asks before running them.

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
- The user plays the side to move after the engine's reply, the normal `Mode.NORMAL` case. Side
  switching is not supported yet.
- Losing on time does not end a local PicoChess game, so play can continue after the flag falls.
  After resignation, checkmate or a draw, `make_move` reports that the game is over.
- With an e-board, PicoChess publishes which move the engine chose only after it has been made on
  the board. Until then `get_game` reports that a move is pending, but not which move; PicoChess
  shows it on its own displays.

## How it works

| Purpose | Request |
|---|---|
| Engine name | `GET /info?action=get_system_info` |
| Current position, PGN and last move | `GET /dgt?action=get_last_move` |
| Play a move | `POST /channel` with `action=move`, `source`, `target`, `promotion` and `fen` |
| New game | `POST /channel` with `action=new_game` |
| Resign | `POST /channel` with `action=resign_game` |
| Clock state | `GET /info?action=get_clock_state` |
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
