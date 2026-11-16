# Adding your own UCI engine on Windows or macOS

This guide is for [issue #572](https://github.com/JohanSjoblom/picochess/issues/572).
It explains how to use an engine you already have, for example a Fritz,
Komodo, HIARCS or other commercial engine, or a free engine you downloaded
yourself. PicoChess can then act as a front end for it. The guide is written
so that you can hand it to an AI coding assistant, but every step can also be
done by hand.

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
| Windows x64 | `engines\AMD64\` |
| macOS Apple silicon | `engines/arm64/` |
| macOS Intel | `engines/mac_x86_64/` |

Adding an engine follows the same rule as the main README's
"How to add more engines?" section. In the engine folder, add:

- the engine executable, for example `engineX.exe` on Windows or `engineX` on
  macOS;
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

Run the check with the Python environment PicoChess already uses, so it works
the same way on Windows and macOS. From the PicoChess folder:

```text
Windows:  venv\Scripts\python.exe
macOS:    venv/bin/python
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
    result = engine.play(chess.Board(), chess.engine.Limit(time=1.0))
    print("bestmove from start position:", result.move)
finally:
    engine.quit()
```

Save it outside the PicoChess folder, for example as `check_engine.py` in your
home folder, and run it with the engine path as its argument. The check passes
when it prints the engine's name and options and a legal best move. A UCI
handshake alone is not enough; the short search proves the engine can play.

On macOS, a downloaded binary may need `chmod +x`. If macOS blocks it because
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

On macOS, the same entry would start with `[Fritz]`.

| Key | Meaning |
| --- | --- |
| `name` | Name shown in menus and logs. |
| `small`, `medium`, `large` | Clock display names: at most 6, 8 and 11 characters for the DGT XL, DGT3000 and DGT Pi clocks. |
| `web` | Optional longer web menu name. Defaults to `large`. |
| `elo` | Approximate full-strength rating. Shown in the menu only; an estimate is fine. |

## Step 3: add a levels file

Create a levels file next to the executable, named after the executable with
`.uci` added. In the example that is `engines\AMD64\Fritz.exe.uci`.
Without this file the engine still works, at full strength and with no level
choice.

Each section is one level, and each line in it sets a UCI option. The
`[DEFAULT]` section applies to every level. Option names must match the names
printed by the check in step 1. **PicoChess silently drops options the engine
does not report**, so a misspelt option does nothing. Use the
`Elo@1234` or `Level@01` naming style for levels.

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

## Step 4: check the catalog and select the engine

Check that PicoChess reads the new entry and its levels. Run this from the
PicoChess folder:

```text
venv\Scripts\python.exe -c "from uci.read import read_engine_ini; [print(e['name'], '->', e['file'], list(e['level_dict'])) for e in read_engine_ini()]"
```

On macOS, use `venv/bin/python` instead. Every engine, including Stockfish,
should be listed with the expected file path and levels.

Then start PicoChess and select the engine from the engine menu in the web
client or on the clock. To make it the startup engine, edit `engine` and
`engine-level` in `picochess.ini` yourself. The level must be a section name
from the `.uci` file. Keep `tutor-engine` on Stockfish unless you have a
reason to change it.

## Keeping your engine

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
> PicoChess on this Windows or macOS computer: `<engine path or installation
> folder>`. Verify that I have closed PicoChess; do not stop or start it
> yourself. Work out this computer's engine folder. Inspect the engine's
> installation and tell me which files it needs, then copy the executable
> and those files directly into the engine folder, as described in the guide
> and the main README. If a file with the same name already exists there,
> stop and ask me. Do not modify the
> original installation, and do not try to bypass copy protection or
> activation. Run the UCI and short-search check from the guide against the
> copied executable. If it is not a UCI engine, or it does not run from the
> copy, stop and report this. Back up `engines.ini`, then append a section for
> the engine after the existing entries, leaving Stockfish first, named after
> the executable's file name. Create a levels file using only option names the engine reports, and
> use `PicoNode`/`PicoDepth` levels if it has no strength options. Use absolute
> paths for any data files it needs. Run the catalog check from the guide.
> Do not change Stockfish, its levels file, `picochess.ini` or any other
> resources. Do not add the engine or its files to git. Finish by telling me
> the engine and level names to select, and the `engine` and `engine-level`
> lines I could put in `picochess.ini` if I want it as the startup engine.
