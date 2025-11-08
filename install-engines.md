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
      └── lc0
```

---

## ⚙️ Script behavior

- Detects current CPU architecture using `uname -m`
- Creates the `engines/<arch>` directory if missing
- Downloads the matching `.tar.gz` archive from GitHub
- Extracts it into place
- Cleans up temporary files afterward

If the folder already exists, the script skips installation to avoid overwriting existing engines. To force an update you must first run `move-engines-to-backup.sh`, which empties the `engines/` folder and allows the installer to download everything again.

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
