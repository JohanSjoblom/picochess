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

# Install the larger bundle
./install-engines.sh large
```

- `small` keeps the download size lean (used by `install-picochess.sh` and the regular update path).
- `large` installs the larger engine package plus add-ons such as MAME emulation and Rodent engines.

Package choice controls contents and download size, independently of headless or desktop use. `lite` remains a deprecated alias for `large` and prints a notice. Existing release archives retain `lite` in their filenames so download URLs continue to work.

> ℹ️ The script only runs as the `pi` user and assumes the target directories do **not** already exist. Run `move-engines-to-backup.sh` first if you need to reinstall over an existing setup.

---

## Updating an existing aarch64 large installation to 4.4.0

The 4.4.0 release supplies DJ Dekker's updated aarch64 large engine pack and
Rodent III/IV resources for [issue #468](https://github.com/JohanSjoblom/picochess/issues/468).
All three archives are needed:

- `engines-aarch64-lite.tar.gz`
- `engines-rodent3-lite.tar.gz`
- `aarch64_rodent4_lite.tar.gz`

Updating the PicoChess source alone does not replace existing engine directories.
After updating to 4.4.0, stop PicoChess before reinstalling the engine resources.
For a standard Linux service installation:

```bash
sudo systemctl stop picochess
cd /opt/picochess
./move-engines-to-backup.sh
./install-engines.sh large
sudo systemctl start picochess
```

Run the two engine scripts as your normal install user. The backup script moves
the current architecture's engines and the shared resource directories to
`~/pico_backups/current/engines_backup`. It replaces previous backups of those
directories, so preserve any older backup you need before running it. The
reinstall also downloads the other large resources moved by the backup script.
Keep your custom engine settings and personalities in the backup and reapply
them selectively after checking the updated files.

If installation fails, keep PicoChess stopped while investigating. To restore
the previous resources, run `./restore-engines-from-backup.sh all` as the same
user before starting PicoChess again. The restore script reports any resource
that had no backup; check those messages before restarting.

These updated archives cover aarch64 large only. The x86_64 Rodent configurations
remain to be updated and tested; the small engine packs are unchanged.

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
