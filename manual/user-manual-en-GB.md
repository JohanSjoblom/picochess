# PicoChess Web Client User Manual

First draft, UK English

This manual describes the modern PicoChess web client and its menu items. It is
intended as source text for later translations.

## 1. What PicoChess Does

PicoChess lets you play chess against a chess engine, analyse positions, replay
games, use a physical electronic chess board, and control the game from a web
browser.

The web client is useful on a Raspberry Pi touch screen, a tablet, a phone, or a
computer on the same network. Some functions are mainly for physical e-boards,
and some are mainly for web-only use. The menu descriptions below mention these
differences where they matter.

## 2. The Main Parts Of The Web Client

### Chess Board

The chess board shows the current game position. In web-only mode you can move
pieces on the web board. When a physical e-board is connected, the e-board is
normally the source of real moves, and the web board mirrors the game.

### Clock Area

The clock area shows time, engine messages, analysis messages, and short status
messages. During a game it normally shows both players' remaining time. In some
analysis modes it can show the engine's best move, score, or depth instead.

### Quick Controls

The quick controls near the clock give fast access to common actions such as
pause or resume, hint, evaluation, and switching sides. The pause/play control
is context-sensitive:

- during your clock time it pauses the clock;
- when paused it resumes play;
- while the engine is thinking it asks the engine to move now;
- when an engine move is waiting on the board it can request an alternative
  move;
- during PGN replay it pauses or resumes replay.

### PGN Move List

The PGN move list shows the move history. Clicking a move in the list selects
that position on the web board. This is useful for review, analysis, and the
Position > Set Pos function.

### Analysis Area

The analysis area can show PicoChess backend analysis and, when enabled, browser
Stockfish analysis. Backend analysis comes from PicoChess or PicoTutor. Browser
analysis runs in the web browser and can use extra CPU on the device showing the
web page.

### Opening Book And Games Tabs

The older tab area still contains useful information such as opening-book moves,
analysis rows, watcher information, and game search or PGN tools.

### Main Menu

Open the main menu with the menu button in the web client. The modern menu is
organised into tiles:

- Mode
- Engine
- Time
- Engine Book
- Tutor
- Position
- Game
- System
- Display

Each tile opens a group of related settings or actions.

## 3. Starting A Normal Game

### With A Physical E-Board

1. Connect and power on the e-board.
2. Place the pieces in the normal starting position.
3. Choose the engine, time control, and playing mode if you want to change them.
4. Start by making a move on the physical board, or use the clock/web controls
   to let PicoChess move first.

If the board is physically reset to the normal starting position, PicoChess
treats that as a new game.

### Without A Physical E-Board

1. Set the e-board type to None if needed.
2. Use the web board to make moves.
3. Choose mode, engine, and time settings from the web menu.

### Choosing Who Moves First

In Normal mode, if it is your turn, make a move. If you want the engine to move
first, use Switch Sides or the pause/play control depending on the current game
state.

## 4. Basic Playing Advice

- Wait for PicoChess to finish messages before making the next physical move.
- If an engine move is shown, play that move on the e-board unless you request
  an alternative move.
- If the web board and physical board get out of sync, use the Position menu to
  resynchronise.
- For a physical e-board, the real piece placement matters. The web board is a
  display and control surface, not the source of physical truth.

## 5. Mode Menu

The Mode menu decides what PicoChess is doing with the current position.

### Normal

Normal is the usual play-against-the-engine mode. You play one side and the
engine plays the other side. The clock and move flow behave like a normal game.

Use this when you want a standard game against the selected engine.

### Training

Training is a playing mode intended for guided practice. It is still a
user-versus-engine mode, but PicoChess may apply training behaviour depending on
the selected engine and tutor settings.

Use this when you want to practise rather than only play a rated-style game.

### Move Hint

Move Hint is a non-playing mode where PicoChess watches the position and can
show suggested moves. The engine does not play automatically as your opponent.

Use this when you want help finding moves while you remain in control of both
sides.

### Eval.Score

Eval.Score shows the engine's evaluation of the current position. The score is
normally shown from White's point of view: a positive score favours White and a
negative score favours Black.

Use this when you mainly want to know who is better and by how much.

### Analysis

Analysis is free analysis with the selected main engine. PicoChess analyses the
current position without playing moves for either side.

Use this for studying a position, checking a PGN position, or analysing both
sides without starting a normal game.

### PGN Replay

PGN Replay is for stepping through or replaying a loaded PGN game. It is
separate from playing a new game against an engine.

Use this when you want to review an existing game move by move.

### Hand & Brain

Hand & Brain opens a choice between Brain and Hand coach modes.

- Brain: PicoChess gives automatic help about the kind of move or idea to look
  for.
- Hand: PicoChess lets you lift a piece to ask whether that piece is part of a
  good move.

These modes are connected to PicoTutor coach behaviour and are mainly useful for
training.

### Observe

Observe lets PicoChess watch a game without playing either side. The clock can
still be used and the engine can think silently in the background.

Use this for human-versus-human games where PicoChess should observe.

### Remote

Remote is for remote-player use through the web client. One side may play via
the web interface while the other uses the board.

Use this only when you intend to play with a remote web player.

## 6. Engine Menu

The Engine menu selects the chess engine and, when available, its level.

### Modern

Modern engines are current engines intended for normal play and analysis.

### Retro

Retro engines emulate older chess computers or older playing styles. Some retro
engines have special speed, sound, display, and artwork settings in the System
menu.

### Favourites

Favourites contains engines marked as preferred in the PicoChess engine
configuration.

### Engine Levels

After selecting an engine, PicoChess may show a list of levels. These can be Elo
levels, skill levels, personalities, or other engine-specific options.

Changing the engine or level affects future engine moves and analysis. It does
not change moves already played.

## 7. Time Menu

The Time menu controls how much time the engine and players use.

### Blitz: Minutes Per Game

Each side receives a fixed number of minutes for the whole game.

Use this for normal timed games such as 5 minutes or 15 minutes.

### Fischer: Game Plus Increment

Each side receives an initial amount of time plus an increment added after each
move.

For example, 5+3 means 5 minutes for the game and 3 seconds added after every
move.

### Tournament

Tournament controls use a more structured format with a number of moves, a main
time, and increments or secondary periods.

Use this for longer games that should resemble tournament time controls.

### Fixed: Seconds Per Move

The engine receives a fixed number of seconds for each move.

Use this when you want predictable engine response times instead of a full game
clock.

### Depth

The engine searches to a fixed depth in plies. A ply is one half-move.

Use this for testing or analysis where you want the engine to stop at a known
search depth.

### Nodes

The engine searches a fixed number of nodes. A node is a searched position in
the engine's search tree.

Use this mostly for testing, comparison, or special engine setups.

## 8. Engine Book Menu

The Engine Book menu selects the opening book used by the playing engine.

An opening book can make the engine play known opening moves instantly instead
of calculating from the first move. Choosing Off or no book makes the engine
calculate from the start.

This setting is for the playing engine's book. It is separate from any web tab
that only displays opening information to the user.

## 9. Tutor Menu

The Tutor menu controls PicoTutor features. PicoTutor can watch games, evaluate
moves, give hints, and produce comments.

### Watcher

Watcher turns PicoTutor's watching behaviour on or off. When enabled, PicoTutor
tracks the game and can report mistakes or useful information.

Use this if you want feedback while playing or reviewing.

### Coach

Coach controls how actively PicoTutor helps.

- Off: no coach help.
- On: normal coach feedback.
- Lift: ask for help by lifting a piece.
- Brain: automatic brain-style hints.
- Hand: ask whether a lifted piece is a good candidate.

Coach settings can affect gameplay because they change when and how hints or
training feedback appear.

### Explorer

Explorer enables opening or position exploration information where available.

Use this to get extra guidance about known positions or opening choices.

### Comment

Comment controls whether PicoTutor stores comments for the PGN.

- Off: no tutor comments.
- Engine: comment on engine-relevant evaluations.
- All: include broader tutor comments.

These comments can later appear in saved PGN files.

### Probability

Probability controls how often some tutor comments or feedback are given. A
higher value means PicoTutor is more likely to comment.

### Hint

Hint asks PicoChess for a hint in the current position.

## 10. Position Menu

The Position menu is used to keep PicoChess, the web board, and a physical
e-board synchronised.

### Side To Move

Sets whether White or Black is to move when scanning a physical position.

This matters because the same piece placement can be a different legal position
depending on whose turn it is.

### Board Side

Sets whether the physical board is used with White at the normal bottom side or
with Black at the bottom.

Use this if you have turned the physical board around.

### Chess960

Enables Chess960 castling interpretation for position setup.

Use this only for Chess960/Fischer Random positions and make sure the selected
engine supports Chess960.

### Castling

Sets castling rights for the scanned position:

- White O-O
- White O-O-O
- Black O-O
- Black O-O-O

Castling rights are not visible from piece placement alone, so PicoChess needs
this information when setting up a custom position.

### Scan: Get Eboard Pos

Scan reads the current physical e-board position and makes PicoChess use that
position. It is useful when the pieces on the e-board are the position you want
to start from.

Typical use:

1. Put the pieces on the e-board.
2. Set side to move, board side, Chess960, and castling rights.
3. Choose Scan.
4. PicoChess starts from the scanned e-board position.

### Set Pos: Set Eboard Pos

Set Pos sends the currently selected web/PGN position to PicoChess. If a
physical e-board is connected, you then set up the pieces on the e-board to
match that position.

Typical use:

1. Click a move in the PGN move list to select the position after that move.
2. Open Position.
3. Choose Set Pos.
4. PicoChess forgets the later PGN moves and keeps the game history up to the
   selected point.
5. Arrange the e-board pieces to match the selected position.
6. Continue playing or choose an analysis mode.

The intended result is that the web client, backend game state, and physical
e-board all agree on the same position and move history.

## 11. Game Menu

The Game menu contains direct game actions.

### New Game

Starts a new game. This clears the current game state and returns to a fresh
game.

### Hint

Asks PicoChess for a hint in the current position.

### Takeback

Takes back the previous move. Repeating this can step back through the game.

On a physical e-board, keep the pieces in sync with the taken-back position.

### Save

Saves the current game to a slot.

### Read

Loads a saved game from a slot, or loads the last game.

### End Game

Sets the game result manually:

- White wins
- Black wins
- Draw

Use this when the result is known but was not detected automatically.

### Alt Move

Requests an alternative engine move when an engine move is available or waiting.

Use this if you do not want to play the first engine suggestion.

### Cont Last

Continues from the last game or last stored position where supported.

### Switch Sides

Switches which side the user plays. The board orientation in the web client may
also flip.

### Resign

Resigns the current game. This is only available when a game is active.

### Move Now

Stops the engine search and asks the engine to play immediately. This is only
available when the engine is thinking.

### Player

Sets the player's name and Elo. This information can be used in PGN headers.

### Download PGN

Downloads the current game as a PGN file from the browser.

### Upload PGN

Opens the PGN upload page so a PGN can be loaded into PicoChess.

## 12. System Menu

The System menu contains device, sound, language, voice, retro, and maintenance
settings.

### Power

Contains system actions:

- Shutdown
- Reboot
- Exit PicoChess
- Update PicoChess
- Update Engines

Use these carefully. Shutdown and reboot affect the Raspberry Pi or host
system.

### Info

Shows system information such as PicoChess version, git status, IP addresses,
location, and battery information where available.

### Picochess.ini

Opens the settings page for editing PicoChess configuration.

### Phone Speaker

Toggles remote web audio for PicoTalker. When enabled and a remote web client is
connected, PicoTalker audio can be sent to the remote browser instead of playing
locally for that clip.

Localhost web clients do not enable the remote speaker path.

### Audio Backend

Selects the local audio backend:

- Native: intended for Wayland/PipeWire systems.
- SoX: older X11 or legacy playback path.

This is a technical setting and may require a PicoChess restart.

### DGT Beep

Controls DGT clock beeps:

- Off
- Some
- On
- Sample

### Language

Sets the PicoChess language. Current menu choices include English, German,
Dutch, French, Spanish, and Italian.

### Comp Voice

Selects the computer/engine voice speaker for spoken move announcements and
PicoTalker output. Mute disables that voice.

### User Voice

Selects the user's voice speaker. Mute disables that voice.

### Voice Speed

Changes voice playback speed. Lower values are slower and higher values are
faster.

### Volume

Changes voice volume.

### Retro Speed

Controls retro engine playback speed. This affects retro/MAME-style engines and
can range from slow percentages to maximum speed.

### Retro Sound

Turns retro engine sound on or off where supported.

### Retro Display

Turns retro engine display or artwork support on or off where supported.

### Retro Window

Chooses whether retro artwork starts windowed or fullscreen where supported.

### Retro Info

Shows the current retro engine feature flags.

### Preferences

Contains display and notation preferences:

- Clock Side: choose whether the clock display is shown on the left or right.
- Notation: choose short or long move notation.
- Confirm: turn confirmation messages on or off.
- Capital: show clock text in capitals or normal case.
- Engine Name: show or hide the engine name.

### EBoard

Selects the physical board type:

- DGT
- Certabo
- ChessLink
- ChessNut
- iChessOne
- None

Choose None for web-only use.

### WiFi/BT

Contains network and Bluetooth helper actions:

- Toggle Hotspot
- Toggle BT
- Fix BT

Use these when setting up or repairing connectivity.

## 13. Display Menu

The Display menu changes the look of the web client.

### Board

Selects the board colour or board theme. Examples include Blue, Green, Metal,
Natural Wood, Newspaper, Soft, and Wood.

### Pieces

Selects the piece set. Examples include Alpha, Berlin, Leipzig, Merida, Neo,
and USCF.

### Theme

Selects the web user-interface theme:

- Dark
- Light
- Auto

## 14. Common Workflows

### Continue From A PGN Position On A Physical E-Board

1. Load or play a game so the PGN move list is visible.
2. Click the PGN move whose resulting position you want.
3. Open Position > Set Pos.
4. Set the physical pieces to match the selected position.
5. Wait for PicoChess to confirm the position.
6. Choose Normal, Analysis, or another mode.

### Start From A Position Already On The E-Board

1. Put the position on the physical board.
2. Open Position.
3. Set side to move, board side, Chess960, and castling rights.
4. Choose Scan.
5. Continue playing or analysing from the scanned position.

### Analyse A Finished Game

1. Open or finish a game.
2. Click moves in the PGN list to inspect positions.
3. Choose Mode > Analysis for engine analysis from the selected position.
4. Use the analysis area and PGN list to move through the game.

### Save Or Export A Game

1. Use Game > Save to save to a PicoChess slot.
2. Use Game > Download PGN to download the PGN through the browser.
3. Use Game > End Game first if you need to set the result manually.

## 15. Troubleshooting

### The Web Board And Physical Board Do Not Match

Use Position > Scan if the physical board is correct.

Use Position > Set Pos if the web/PGN position is correct and you want to set
the physical board to match it.

### The Engine Does Not Move

Check that you are in a playing mode such as Normal or Training. In Analysis,
Move Hint, Eval.Score, Observe, and PGN Replay, the engine may analyse or watch
without playing as your opponent.

### The PGN Move List Looks Wrong

Make a move only after PicoChess has synchronised the position. If you are using
Set Pos, wait for the position setup confirmation before continuing.

### There Is No Sound

Check System > Volume, Comp Voice, User Voice, Phone Speaker, and Audio Backend.
If using Native audio on Wayland/PipeWire, the system may need the required
PipeWire ALSA support and a PicoChess restart.

### A Remote Phone Seems To Play Audio On The Raspberry Pi

If the phone is connected to the Raspberry Pi by Bluetooth, the phone audio may
be routed back to the Pi speakers. Disconnect Bluetooth audio before testing
remote web audio.

## 16. Glossary

### Backend

The PicoChess program running on the Raspberry Pi or host computer.

### E-Board

An electronic chess board such as DGT, Certabo, ChessLink, ChessNut, or
iChessOne.

### Engine

The chess program that calculates moves or analysis.

### FEN

A text description of a chess position, including pieces, side to move,
castling rights, en-passant square, and move counters.

### PGN

A text format for recording a chess game and its move list.

### Ply

One half-move. White's move is one ply; Black's reply is another ply.

### PicoTutor

The PicoChess tutor component that can watch, coach, evaluate, and comment on
games.
