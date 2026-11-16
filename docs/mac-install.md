# Installing PicoChess on macOS

The macOS installer prepares a user-local PicoChess environment with a
Stockfish starter engine. It does not install launch agents, drivers, or Linux
host integrations. It can use the checkout containing the script or clone
PicoChess into another directory. Apple silicon and 64-bit Intel Macs are
supported with a native CPython 3.11 through 3.13 runtime.

## Prerequisites

- macOS on Apple silicon (`arm64`) or a 64-bit Intel Mac (`x86_64`).
- CPython 3.11, 3.12, or 3.13 from [python.org](https://www.python.org/downloads/macos/)
  or Homebrew.
- Git when PicoChess still needs to be cloned or when using `--update-repo`.
- Internet access for Python dependencies and selected resource packs.

The installer does not need `sudo`. Run it from an existing checkout with:

```bash
bash ./install-picochess-mac.sh
```

To use a downloaded copy of the script as a bootstrap installer:

```bash
bash ./install-picochess-mac.sh --install-dir "$HOME/PicoChess"
```

It creates or reuses `venv`, installs `requirements.txt`, initializes runtime
directories and the voice configuration, installs portable resources, and runs
dependency/import smoke tests. Existing Git changes are never reset. Updating
is opt-in and requires a clean branch:

```bash
bash ./install-picochess-mac.sh --update-repo
```

The update uses `git pull --ff-only`, so it never merges or overwrites local
work. It also configures older single-branch checkouts to fetch all branches,
without changing the checked-out branch.

Fresh clones check out the `master` branch.

## Resource and recovery options

The native engine directory is checked before any engine download. If
`engines/arm64` or `engines/mac_x86_64` already exists for this Mac, the
installer leaves it untouched, even with `--force-resources`. Otherwise it
downloads the official Stockfish 19 macOS universal release, verifies that the
binary answers UCI commands, then downloads the PicoChess macOS engine metadata
archive from release v4.3.5. It installs the executable as `a-stockf` alongside
the archive's `engines.ini`, `a-stockf.uci`, and any additional files. The
official Stockfish archive and the metadata archive serve both Mac architectures.
Both downloads have pinned SHA-256 checksums; a mismatch stops the installation
before anything is installed.

The `Lc0` resource then adds Lc0 to the same engine folder, even when the
folder already existed. Only a pre-release,
[Lc0 v0.33.0-rc0](https://github.com/LeelaChessZero/lc0/releases/tag/v0.33.0-rc0),
currently ships a macOS binary. It is universal, so it serves both Mac
architectures, and it is installed as `lc0` with `Backend = blas`, which uses
Apple's Accelerate. The installer adds the same catalog entries as Linux:
`lc0`, `classic`, `elitev2`, `maiav0321` and `maia3`, the last four as
symlinks to `lc0`, each with its levels file from a PicoChess v4.4.1 metadata
archive. When `engines/lc0_weights` is missing, it also downloads the shared
`lc0_weights.tar.gz` (about 620 MB) and points the levels files at it. All
downloads have pinned SHA-256 checksums, and each entry must complete a short
search before anything is installed. An existing `lc0` is kept. If the Lc0
step fails, the installer warns and continues; Stockfish remains usable. Retry
it with `--resources Lc0`.

The starter engine, Lc0, books, opening data, and games database data are
selected by default. A subset can be selected, or downloads can be disabled:

```bash
bash ./install-picochess-mac.sh --resources Engines,Books,OpeningData
bash ./install-picochess-mac.sh --skip-resources
```

Existing complete data resources are preserved. For data resources,
`--force-resources` first moves an existing directory to a timestamped backup
under
`~/Library/Application Support/PicoChess/backups`.

Use `--validate-only` to inspect an existing checkout without changing it,
`--recreate-venv` to back up and rebuild `venv`, or `--skip-smoke-tests` to
omit the final checks.

The games archive contains useful database data, but its bundled `tcscid`
binaries are for Linux. Installing a native macOS Scid/tcscid is outside the
scope of this installer. If you have one, the launcher can start it for the
Games tab (see below).

## Engines and startup

The starter engine is installed under `engines/arm64` on Apple silicon or
`engines/mac_x86_64` on an Intel Mac when that directory is absent. You can
also supply your own native UCI engine and catalog in that directory.
The separate Intel folder prevents macOS binaries from being confused with
Linux binaries in `engines/x86_64`. Linux executables are not compatible with
macOS. See the
[engine setup guide](../engines/README.md#experimental-macos-setup). To add an
engine you already have next to Stockfish, see
[Adding your own UCI engine](../add-own-engine.md), which includes a prompt for
an AI coding assistant.

After installation, start PicoChess from the repository root:

```bash
bash ./start-picochess-mac.sh
```

Arguments after `--` are passed to `picochess.py`:

```bash
bash ./start-picochess-mac.sh -- --board-type noeboard --web-server 8080
```

The launcher checks for the virtual environment and `picochess.ini`. It then
optionally starts the Scid games helper (`tcscid get_games.tcl --server 7778`)
when the games data and a native macOS `tcscid` are available. The `tcscid` is
taken from `--tcscid PATH`, then `PICOCHESS_TCSCID`, then `PATH`. The helper is
stopped when PicoChess exits. Use `--skip-games-server` to skip it. Without a
helper, PicoChess replaces the launcher process, so stopping it with Ctrl+C
behaves exactly like running `./venv/bin/python picochess.py`.

An experimental PicoChess.app control panel can install PicoChess and start,
stop, and upgrade it without a terminal. See `mac/README.md`.

The experimental macOS path is intended primarily for web-only play with a
native engine. PGN upload authentication, host updates, Wi-Fi/Bluetooth setup,
shutdown, and reboot integrations remain Linux-only.
