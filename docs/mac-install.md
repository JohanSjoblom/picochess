# Installing PicoChess on macOS

The macOS installer prepares a user-local PicoChess environment without
installing engines, launch agents, drivers, or Linux host integrations. It can
use the checkout containing the script or clone PicoChess into another
directory. The current macOS target is Apple silicon (`arm64`) with a native
CPython 3.11 through 3.13 runtime.

## Prerequisites

- macOS on Apple silicon. Intel Macs and Python running through Rosetta are not
  currently supported by this installer.
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
binaries are for Linux. A native macOS Scid/tcscid setup is outside the scope
of this installer.

## Engines and startup

No engine is downloaded. Add a native Apple-silicon macOS UCI engine and
catalog under `engines/arm64`. Linux `aarch64` executables are not compatible
with macOS. See the
[engine setup guide](../engines/README.md#experimental-macos-arm64-setup).

After configuring `picochess.ini`, start PicoChess from the repository root:

```bash
./venv/bin/python picochess.py
```

The experimental macOS path is intended primarily for web-only play with a
native engine. PGN upload authentication, host updates, Wi-Fi/Bluetooth setup,
shutdown, and reboot integrations remain Linux-only.
