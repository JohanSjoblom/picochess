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

If the folder already exists, the script skips installation to avoid overwriting
existing engines. Use `update-engines.py` below to update an existing installation
while retaining ROMs and menu selections. The older `move-engines-to-backup.sh`
followed by `install-engines.sh` is a clean reinstall and requires manual
restoration of ROMs and custom menus.

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

Package choice controls contents and download size, independently of headless or desktop use. `lite` remains a deprecated alias for `large` and prints a notice. The large engine, MAME and Rodent archives now use `large` filenames on release 4.4.0. Older release assets remain available for older installers.

Run the engine scripts as your normal install user, without sudo. The standalone
engine installer assumes the target directories do not already exist.

---

## Updating without losing ROMs or retro menu selections

Use the standalone, standard-library Python script `update-engines.py` for an
existing Linux aarch64 or x86_64 installation. For a Pi 4, the new MAME builds
require a 64-bit OS with Trixie-compatible runtime libraries. On x86_64, also
install `libqt6gui6` and `libqt6widgets6` if they are not already installed.

```bash
cd /opt/picochess
./update-engines.py large --dry-run
sudo systemctl stop picochess
./update-engines.py large
# Only restart after the update reports success:
sudo systemctl start picochess
```

Stop manually started PicoChess instances too. The updater refuses to proceed
when `picochess.service` is active. It does not start or stop services itself.

The update downloads and extracts into a staging directory first. It retains:

- The complete existing MAME ROM collection, including software-list subfolders
  and symlinks. Existing ROM files take precedence over bundled files with the
  same name; bundled ROMs with new names are also kept.
- Your `retro.ini` and `favorites.ini` selections and order. Their entries use
  updated catalog metadata when available. A 185-entry retro menu stays at 185
  entries, rather than being replaced with the packaged six-entry starter menu
  or expanded to all 431 engines. Custom entries are retained.
- MAME `mame.ini`, `ini/`, `cfg/` and `nvram/` settings/data.
- Unbundled engine files and personalities. Files provided by the new packs,
  including `.uci` level files, use the new versions; previous customizations
  of those files remain in the backup for selective reapplication.

Installed LC0 weights, script engines and PGN audio are reused. The updater
checks that the new MAME executable starts before replacing live resources.
Download, extraction or compatibility failures leave the live resources in
place. A failure during replacement rolls back directories already replaced.

Old resource directories are kept in a unique dated backup under
`engines/.update-backups/`. Earlier backups are never overwritten. Allow disk
space for the staged packs and a second copy of your ROM collection. Once you
have verified an update, older backups can be removed manually to reclaim space.

The script prints the exact rollback command:

```bash
./update-engines.py --restore /opt/picochess/engines/.update-backups/<backup-name>
```

Stop PicoChess before restoring. Restore also backs up the current resource
directories, including any ROMs collected after the update. ROMs are retained,
but compatibility with a newer MAME version must still be checked using
`./mess -verifyroms` and the software-list checker described below. The updater
does not rename ROMs, remove menu entries, or add every catalog entry.

`small` updates the architecture engine pack without replacing MAME or Rodent
resources already installed. To update the MAME resources, choose `large`.

## Updating an existing aarch64 large installation to 4.4.0

The 4.4.0 release supplies DJ Dekker's updated aarch64 large engine pack and
Rodent III/IV resources for [issue #468](https://github.com/JohanSjoblom/picochess/issues/468).
The updated aarch64 engine and Rodent archives use these names:

- `engines-aarch64-large.tar.gz`
- `engines-rodent3-large.tar.gz`
- `aarch64_rodent4_large.tar.gz`

Updating the PicoChess source alone does not replace existing engine directories.
After updating the source, stop PicoChess before updating the engine resources.
For a standard Linux service installation:

```bash
sudo systemctl stop picochess
cd /opt/picochess
./update-engines.py large
# Only restart after a successful update:
sudo systemctl start picochess
```

Run the updater as your normal install user. ROMs and menu selections are
preserved as described above. Reapply any customizations of packaged engine
settings selectively from the dated backup after checking the updated files.
If updating fails, keep PicoChess stopped while checking the reported error.

The Rodent configuration updates cover aarch64 only. The x86_64 Rodent contents
are unchanged and are republished under `large` filenames. The small engine packs
are unchanged.

## MAME 0.289 resources for both architectures

Release 4.4.0 also supplies Randy's updated MAME executable, artwork and
`chessengine` plugin, together with updated launch scripts and retro catalogs:

| Architecture | Engine pack | MAME resources |
| --- | --- | --- |
| aarch64 | `engines-aarch64-large.tar.gz` | `engines-mame-large.tar.gz` |
| x86_64 | `x86_64_engines_large.tar.gz` | `x86_64_mame_large.tar.gz` |

Both engine packs include the replacement `mame/`, `engines_ini/all_retro.ini`
and `retro.ini` from Randy's `x86_64_aarch64_mame_files.zip`. Other engine files
retain their previous contents. The MAME resource archives are Randy's original
archives with new filenames. The x86_64 build requires Qt 6; `install-picochess.sh`
installs `libqt6gui6` and `libqt6widgets6`, including their dependencies. For a
manual x86_64 resource update, install them with
`sudo apt install libqt6gui6 libqt6widgets6`.

Both new MAME executables require glibc 2.38 or newer and libstdc++ providing
`GLIBCXX_3.4.32`. Debian/Raspberry Pi OS Trixie supplies these versions;
the stock Bookworm libraries are too old.

Use the stop, backup, reinstall and start sequence above on either architecture.
Updating source alone does not replace the installed resources. The engine
installer downloads both the engine pack and MAME resources for `large`.

The installed `.uci` files have longer level labels for the web interface.
For DGTPi labels of at most 11 characters, unzip `mame_uci_dgtpi_en.zip` inside
`engines/<architecture>/mame/` over the installed `.uci` files.

Use ROMs compatible with MAME 0.289. From `engines/mame_emulation`, run
`./mess -verifyroms`, or `./mess -verifyroms mm5` for one machine. Cartridge and
module engines also need software-list ROMs. Randy's
[ROM checker](https://github.com/RandyR99/mame_for_picochess/blob/main/tools/check_softlist_roms.sh)
reports missing software-list ROMs and looks for matching files under older
archive names. A copy is included with the 4.4.0 release assets:

```bash
bash check_softlist_roms.sh
# Or check another ROM folder:
ROMPATH=/path/to/roms bash check_softlist_roms.sh
```

See Randy's [software-list documentation](https://github.com/RandyR99/mame_for_picochess#software-lists)
for details. The release `SHA256SUMS` covers the new archives as well as the
original 4.4.0 resources.

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
