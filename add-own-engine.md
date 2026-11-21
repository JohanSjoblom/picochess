# Adding your own UCI engine

This guide is for [issue #572](https://github.com/JohanSjoblom/picochess/issues/572).
It explains how to use an engine you already have, for example a Fritz,
Komodo, HIARCS or other commercial engine, or a free engine you downloaded
yourself. PicoChess can then act as a front end for it. The guide is written
so that you can hand it to an AI coding assistant, but every step can also be
done by hand.

This guide covers Raspberry Pi, Linux, Windows, and macOS. Use an executable
that matches the OS and CPU architecture of the machine running PicoChess.
For a MAME retro engine on Linux or Raspberry Pi, use the
[retro engine guide and AI prompt](install-engines.md#adding-a-mame-retro-engine-with-ai-assistance).

The installers supply Stockfish as the default playing and PicoTutor engine.
Your engine is added **next to** Stockfish. It does not replace it.

## Before you start

- PicoChess talks to engines using the **UCI** protocol only. Many engines
  sold with ChessBase products are UCI engines, but some older ones use the
  ChessBase engine format (`.eng`) or WinBoard/XBoard. Those cannot be used
  directly. The UCI check below shows which kind you have.
- Use the engine on your own computer only. Do not add commercial engines,
  their files or their licence keys to the PicoChess repository, to resource
  packs or to bug reports.
- Some commercial engines are copy-protected or need activation and only run
  from their original installation. If an engine stops working after it has
  been copied, stop there. Do not try to get round its licence protection.
- Close PicoChess before changing engine files, and keep it closed until the
  checks below pass.

## Where engines go

PicoChess reads the engine catalog from one folder per platform:

| Platform | Engine folder |
| --- | --- |
| Linux x86_64 | `engines/x86_64/` |
| 64-bit Raspberry Pi or other Linux aarch64 | `engines/aarch64/` |
| Windows x64 | `engines\AMD64\` |
| macOS Apple silicon | `engines/arm64/` |
| macOS Intel | `engines/mac_x86_64/` |

Adding an engine follows the same rule as the main README's
"How to add more engines?" section. In the engine folder, add:

- the engine executable, for example `engineX.exe` on Windows or `engineX` on
  Linux and macOS;
- a text file with the engine's settings, named after the executable with
  `.uci` added: `engineX.exe.uci` or `engineX.uci`;
- an `[engineX.exe]` or `[engineX]` section in `engines.ini`.

```text
engines\AMD64\
    engines.ini                                   catalog: Stockfish + your engine
    stockfish-windows-x86-64-universal.exe        installed Stockfish (keep)
    stockfish-windows-x86-64-universal.exe.uci
    Fritz.exe                                     copied engine executable
    Fritz.exe.uci                                 settings and levels for it
```

PicoChess finds an engine by joining the engine folder and the section name, so
the executable must be copied into the folder. Engines cannot be run from where
they are installed, for example from `C:\Program Files`. If the engine needs
DLLs or other files from its own folder, copy those next to it as well. Do not
overwrite a file that is already there; stop and ask instead.

## Step 1: check that the engine speaks UCI

Run the check with the Python environment PicoChess already uses. From the
PicoChess folder:

```text
Windows:                   venv\Scripts\python.exe
Raspberry Pi, Linux, macOS: venv/bin/python
```

```python
import sys
import chess
import chess.engine

engine = chess.engine.SimpleEngine.popen_uci(sys.argv[1], timeout=30)
try:
    print("id:", engine.id)
    for name, option in engine.options.items():
        print(f"option {name!r}: type={option.type} default={option.default} "
              f"min={option.min} max={option.max} var={option.var}")
    engine.ping()
    board = chess.Board()
    result = engine.play(board, chess.engine.Limit(time=1.0))
    if result.move is None or result.move not in board.legal_moves:
        raise RuntimeError(f"Expected a legal move, got {result.move}")
    print("bestmove from start position:", result.move)
finally:
    engine.quit()
```

Save it outside the PicoChess folder, for example as `check_engine.py` in your
home folder, and run it with the engine path as its argument. The check passes
when it prints the engine's name and options and a legal best move. A UCI
handshake alone is not enough; the short search proves the engine can play.

The initial `uci` command reports the options supported by that exact
executable. Each `option` line gives its name and type, and may give a
default, minimum and maximum, or a list of allowed choices. The Python check
above prints the same information. Use it when creating a profile and when
checking an existing `.uci` file after an engine update.

On Linux and macOS, a downloaded binary may need `chmod +x`. If macOS blocks it because
it was downloaded from the internet, the user decides whether to allow it,
either in **System Settings > Privacy & Security** or with
`xattr -d com.apple.quarantine <file>`.

## Step 2: add a catalog entry

Add a section to `engines.ini` in the engine folder. **Append it after the
existing Stockfish section.** The first entry is the fallback engine and must
stay Stockfish. The section name is the executable's file name, including
`.exe` on Windows:

```ini
[Fritz.exe]
name = Fritz 19
small = Fritz
medium = Fritz 19
large = Fritz 19
elo = 3400
```

For an executable named `engineX` on Linux or macOS, use `[engineX]`.

| Key | Meaning |
| --- | --- |
| `name` | Name shown in menus and logs. |
| `small`, `medium`, `large` | Clock display names: at most 6, 8 and 11 characters for the DGT XL, DGT3000 and DGT Pi clocks. |
| `web` | Optional longer web menu name. Defaults to `large`. |
| `elo` | Approximate full-strength rating. Shown in the menu only; an estimate is fine. |

## Step 3: create or verify a levels file

Create a levels file next to the executable, named after the executable with
`.uci` added. In the example that is `engines\AMD64\Fritz.exe.uci`.
Without this file the engine still works, at full strength and with no level
choice.

Start a new profile with `[DEFAULT]` at the top. Put settings shared by all
levels there, such as a required weights path or a common thread limit. The
section can be empty when the engine needs no shared settings. Add at least
one named level below it, such as `[Elo@1500]` or `[Level@01]`. PicoChess lists
the named sections as levels. Each level inherits the defaults and can
override individual values. There is no universal set of required keys.

Check the effective settings for each level, including inherited values,
against the exact option names, types, ranges and choices reported in step 1.
Leave engine defaults in place unless the profile needs to override them.
When reviewing an existing profile, report stale or unsupported options and
keep working level names and settings. Merged levels may also contain
PicoChess settings such as `PicoNode`, `PicoDepth`, `Name`, `Variant`, and
`Analysis`. Keep those separate from options sent directly to the engine.
The Stockfish `[Auto]` level can use a PicoChess Elo expression. PicoChess
resolves that expression to a number before it configures the engine.

Use local profiles as examples of structure. `NNUE/StockfishNN.uci` uses
shared `Hash` and `Threads` settings followed by Elo levels. `lc0v0321.uci`
sets a shared `WeightsFile` and overrides it for levels that use a different
network. Option support and file paths can differ between builds.

Choose the levels from what the engine supports:

- **`UCI_LimitStrength` and `UCI_Elo`:** use Elo levels within the `min` and
  `max` the engine reports. Copy the layout of the installed Stockfish `.uci`
  file.

  ```ini
  [DEFAULT]
  Threads = 1
  Hash = 128

  [Elo@1500]
  UCI_LimitStrength = true
  UCI_Elo = 1500

  [Elo@2000]
  UCI_LimitStrength = true
  UCI_Elo = 2000
  ```

- **A skill option** (for example `Skill Level` or `Skill`): use one level per
  useful step, such as `Level@01` to `Level@20`, setting that option.

- **No strength options:** PicoChess can still weaken any engine by limiting
  its search. `PicoNode` (nodes) and `PicoDepth` (plies) are PicoChess
  settings, not engine options:

  ```ini
  [Level@01]
  PicoDepth = 1

  [Level@02]
  PicoNode = 5000
  ```

If the engine needs a network, book or other data file, set it with an
absolute path. PicoChess starts engines from the PicoChess folder, not the
engine's own folder, so relative paths may not be found. Leave out
`SyzygyPath` unless the tablebases exist on this computer.

After writing or changing a profile, check that PicoChess reads all its levels
as described in step 4. For each new or changed level, apply the effective
engine options, wait for `isready`, and run a bounded search with a legal
position. Use `PicoNode` or `PicoDepth` as search limits when present. For a
level that depends on PicoChess-specific handling, such as `[Auto]`, verify it
through PicoChess's option handling before running the search. A successful
handshake alone does not prove that a network loads or a level plays.

## Step 4: check the catalog and select the engine

Check that PicoChess reads the new entry and its levels. Run this from the
PicoChess folder:

```text
venv\Scripts\python.exe -c "from uci.read import read_engine_ini; [print(e['name'], '->', e['file'], list(e['level_dict'])) for e in read_engine_ini()]"
```

On Linux and macOS, use `venv/bin/python` instead. Every engine, including Stockfish,
should be listed with the expected file path and levels.

Then start PicoChess and select the engine from the engine menu in the web
client or on the clock. To make it the startup engine, edit `engine` and
`engine-level` in `picochess.ini` yourself. The level must be a section name
from the `.uci` file. Keep `tutor-engine` on Stockfish unless you have a
reason to change it.

## Keeping your engine

- **Linux and Raspberry Pi:** use the [preservation updater](install-engines.md#updating-without-losing-roms-or-retro-menu-selections).
  It keeps locally added engine files and their catalog entries. A clean
  `large` reinstall can move those files to a backup for manual restoration.
- **Windows:** rerunning the installer keeps an existing `engines\AMD64`.
  `-ForceResources` moves the whole folder, including your engine, to a backup
  under `%LOCALAPPDATA%\PicoChess\backups`. Copy your engine and its
  `engines.ini` section back from there afterwards.
- **macOS:** the installer never changes an existing engine folder.
- Updating Stockfish with
  [the Windows and macOS refresh workflow](update-engine-resources.md#windows-and-macos-refresh-official-stockfish)
  replaces only the Stockfish executable, so your engine is not affected.

## Prompt for the assistant

> **Add-engine prompt for the assistant:** Read `add-own-engine.md` and the
> repository's `AGENTS.md`. I want to add an engine I already have to
> PicoChess on this computer: `<engine path or installation folder>`. Verify
> that PicoChess is stopped, including the service if there is one. Let me
> handle stopping and restarting it. Check the OS and CPU architecture, locate
> the active engine folder, and confirm the executable matches the platform.
> Inspect the engine's installation and tell me which files it needs, then copy the executable
> and those files directly into the engine folder, as described in the guide
> and the main README. If a file with the same name already exists there,
> stop and ask me. Do not modify the
> original installation, and do not try to bypass copy protection or
> activation. Run the UCI and short-search check from the guide against the
> copied executable. If it is not a UCI engine, or it does not run from the
> copy, stop and report this. Back up `engines.ini`, then append a section for
> the engine after the existing entries, leaving Stockfish first, named after
> the executable's file name. Use the options reported by that executable to
> create a `.uci` file with `[DEFAULT]` and named levels. Validate the effective
> options after inheritance and use `PicoNode` or `PicoDepth` for levels if the
> engine has no strength options. Verify data paths. Run the catalog check and
> test each new or changed level as described in step 3.
> Do not change Stockfish, its levels file, `picochess.ini` or any other
> resources. Do not add the engine or its files to git. Finish by telling me
> the engine and level names to select, and the `engine` and `engine-level`
> lines I could put in `picochess.ini` if I want it as the startup engine.

> **Verify an existing `.uci` profile**
>
> Read steps 1, 3 and 4. Check `<engine executable or catalog key>` and its
> installed `.uci` file. Make sure PicoChess is stopped before testing. Query
> the executable and validate the effective settings of each level, including
> inherited defaults, PicoChess settings and data files. Test the levels with
> bounded searches. Report which levels pass and which settings need attention.
> If I ask you to make corrections, back up the profile and keep its existing
> level names, order and working settings. Repeat the checks after editing.
