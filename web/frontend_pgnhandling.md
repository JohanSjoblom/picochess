## DGT Position and PGN Update Flow in the Picochess Web Interface

### Overview
The web interface maintains a live connection with the Picochess backend to display the current chess position, move history (PGN), and game status.  
This flow describes how the frontend receives updates, refreshes the board, and synchronizes the PGN data.

---

### 1. Backend Update Source
The backend provides the current chess state through:
```
/dgt?action=get_last_move
```
This endpoint returns a JSON structure containing:
- **fen** — the Forsyth–Edwards Notation of the current position  
- **pgn** — the full Portable Game Notation text of the ongoing game  
- **move** — the latest move in algebraic notation  
- **play** — the side to play or context indicator (“user”, “review”, “reload”, etc.)

Example:
```json
{
  "fen": "rnbqkbnr/ppp2ppp/8/3pp3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq e6 0 3",
  "pgn": "[Event \"picochess\"]\n1. e4 e5 2. Nf3 Nc6",
  "move": "e2e4",
  "play": "user"
}
```

---

### 2. The Polling Function — `goToDGTFen()`
The frontend periodically calls the backend using:
```js
$.get('/dgt', { action: 'get_last_move' }, function (data) { ... });
```

When a valid response is received, it calls:
```js
updateDGTPosition(data);
highlightBoard(data.move, data.play);
addArrow(data.move, data.play);
```

This ensures that both the **board** and **visual indicators** reflect the current backend state.

---

### 3. Updating the Position — `updateDGTPosition(data)`
```js
function updateDGTPosition(data) {
    if (!goToPosition(data.fen) || data.play === 'reload') {
        loadGame(data['pgn'].split("\n"));
        goToPosition(data.fen);
    }
}
```

This function ensures that:
- The displayed position (`fen`) matches the backend.
- If the current board cannot reach the backend position (`goToPosition()` fails) or a reload is requested, the full game is reloaded from the **PGN text** sent by the backend.

---

### 4. Rebuilding the Game — `loadGame()`
When called, `loadGame()` parses the PGN lines into a global data structure:
```js
gameHistory
```
This structure stores:
- Game headers (Event, Site, Date, etc.)
- Move list and variations
- Result

Once the PGN is parsed, the board and move list are redrawn to reflect the current game state.

---

### 5. Local Game Export — `getFullGame()`
The function `getFullGame()` retrieves the PGN text from the already-loaded `gameHistory` object.  
It **does not** contact the backend; it simply exports the game state currently known by the frontend.

Thus, the frontend always mirrors whatever full PGN the backend most recently sent during a `loadGame()` update.

---

### 6. Data Flow Summary

```
Backend (picochess) → /dgt?action=get_last_move
         ↓
goToDGTFen()  ← periodic or event trigger
         ↓
updateDGTPosition(data)
         ↓
(loads PGN) → loadGame()
         ↓
Stores moves in → gameHistory
         ↓
Frontend PGN export → getFullGame()
```

---

### 7. Key Points

- The **backend** is the single source of truth for PGN and FEN.  
- The **frontend** does not build PGN incrementally — it reloads it entirely when necessary.  
- The **board** and **move list** are refreshed each time `updateDGTPosition()` is triggered.  
- `getFullGame()` simply exports the current in-memory `gameHistory`, reflecting the last PGN update received from the backend.

