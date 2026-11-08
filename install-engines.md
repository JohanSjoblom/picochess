# Engine Installation for Picochess

The `install-engines.sh` script automatically downloads and installs prepackaged chess engine bundles for your system architecture. Despite its name it also deploys related resources (MAME emulation data, Rodent engines, opening books, etc.) whenever they are available for that architecture.

Each engine package is provided as a `.tar.gz` archive, hosted in the GitHub releases section.  
The script detects the current architecture (e.g. `aarch64`, `x86_64`, `armv7l`) and installs the correct set of engines into the `engines/` folder.

---

## 📦 Package format

Each `.tar.gz` archive is created from the architecture-specific subfolder, **without including parent directories**, e.g.:

```bash
cd engines
tar -czf engines-aarch64-small.tar.gz -C aarch64 .
```

This ensures the archive extracts directly into `engines/aarch64` when run by the installer:

```bash
tar -xzf engines-aarch64-small.tar.gz -C engines/aarch64
```

Correct structure after installation:
```
engines/
 └── aarch64/
      ├── stockfish
      ├── berserk
      ├── lc0
      ├── variants.ini
      ├── fairy-atomic.uci
      └── other managed Fairy profile sidecars
```

When the package contains the Fairy-Stockfish executable named `fairy`, include
`variants.ini` and all five `fairy-*.uci` files from `engine-packages/fairy14/` at the
archive root. The installer also adds these files to an existing installation
when they are missing. Existing user or package files are never overwritten.

Cloning the PicoChess repository does not activate any of these catalogs. The
source templates live outside `engines/<arch>` and are deployed only when the
user runs `./install-engines.sh small` or `./install-engines.sh lite`.

For compatibility, an existing static `favorites.ini` is copied to
`special.ini` when the latter is absent. The original file is retained.

The installer generates `nnue.ini` from matching profiles in the installed
`engines.ini`. A generated file starts with a managed-metadata marker and may
be refreshed by later installation runs. Remove that marker before making
manual changes that must be retained. An unmarked `nnue.ini` is never replaced.

---

## ⚙️ Script behavior

- Detects current CPU architecture using `uname -m`
- Creates the `engines/<arch>` directory if missing
- Downloads the matching `.tar.gz` archive from GitHub
- Extracts it into place
- Cleans up temporary files afterward

If the folder already exists, the script skips the binary archive to avoid
overwriting existing engines. It may still add missing, repository-managed
catalog metadata. To force a binary-package update you must first run
`move-engines-to-backup.sh`, which empties the `engines/` folder and allows the
installer to download everything again.

---

## ▶️ Usage

`install-engines.sh` now requires an explicit package selection:

```bash
# Install the smaller engine bundle (default in installers)
./install-engines.sh small

# Install the lite/DGT-focused bundle
./install-engines.sh lite
```

- `small` keeps the download size lean (used by `install-picochess.sh` and the regular update path).
- `lite` installs the full lite/DGT package plus add-ons such as MAME emulation and Rodent engines.

> ℹ️ The script only runs as the `pi` user and assumes the target directories do **not** already exist. Run `move-engines-to-backup.sh` first if you need to reinstall over an existing setup.

---

## 🧰 Adding new packages

To create and upload a new engine package:

1. Prepare your engine binaries inside `engines/<arch>/`
2. Create the `.tar.gz` archive:
   ```bash
   cd engines
   tar -czf engines-<arch>-small.tar.gz -C <arch> .
   ```
3. Upload the archive as a release asset on GitHub  
   (e.g. `https://github.com/<yourname>/picochess/releases`)

The script will automatically fetch it during the next installation.

---
