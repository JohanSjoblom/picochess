# Installing PicoChess on macOS

The macOS installer prepares a user-local PicoChess environment without
installing engines, launch agents, drivers, or Linux host integrations. It can
use the checkout containing the script or clone PicoChess into another
directory. Apple silicon and 64-bit Intel Macs are supported with a native
CPython 3.11 through 3.13 runtime.

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

> **Beta note:** Fresh clones currently check out the `471-port-to-windows`
> branch explicitly. This temporary branch pin must be removed before the port
> is merged into the default branch.

## Resource and recovery options

Books, opening data, and games database data are installed by default. A subset
can be selected, or downloads can be disabled:

```bash
bash ./install-picochess-mac.sh --resources Books,OpeningData
bash ./install-picochess-mac.sh --skip-resources
```

Existing complete resources are preserved. `--force-resources` first moves an
existing directory to a timestamped backup under
`~/Library/Application Support/PicoChess/backups`.

Use `--validate-only` to inspect an existing checkout without changing it,
`--recreate-venv` to back up and rebuild `venv`, or `--skip-smoke-tests` to
omit the final checks.

The games archive contains useful database data, but its bundled `tcscid`
binaries are for Linux. Installing a native macOS Scid/tcscid is outside the
scope of this installer. If you have one, the launcher can start it for the
Games tab (see below).

## Engines and startup

No engine is downloaded. Add a native macOS UCI engine and catalog under
`engines/arm64` on Apple silicon or `engines/mac_x86_64` on an Intel Mac.
The separate Intel folder prevents macOS binaries from being confused with
Linux binaries in `engines/x86_64`. Linux executables are not compatible with
macOS. See the
[engine setup guide](../engines/README.md#experimental-macos-setup).

After configuring `picochess.ini`, start PicoChess from the repository root:

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

The experimental macOS path is intended primarily for web-only play with a
native engine. PGN upload authentication, host updates, Wi-Fi/Bluetooth setup,
shutdown, and reboot integrations remain Linux-only.
