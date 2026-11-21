# Engine Installation for Picochess

To refresh the standard large engine pack and optionally build the latest upstream
Stockfish NNUE and Lc0 on Debian or Raspberry Pi, or refresh
Stockfish from official downloads on Windows and macOS, follow the
[AI-assisted engine update guide](update-engine-resources.md).
When following that guide, leave PicoChess stopped after the large resource
update until the rebuilt engines and their level files pass their checks.

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

Package choice controls contents and download size, independently of headless or desktop use. `lite` remains a deprecated alias for `large` and prints a notice. The v4.4.1 release gathers all archives used by this installer, with `large` filenames for the large engine, MAME and Rodent packages. Older release assets remain available for older installers.

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

- Existing MAME ROMs absent from the package, including software-list subfolders
  and symlinks. Packaged ROMs replace installed ROMs at the same path so they
  match the packaged MAME version. Previous copies remain in the dated backup.
  Packaged artwork also replaces artwork with the same path; personal artwork
  with other names remains.
- Your `retro.ini` and `favorites.ini` selections and order. Their entries use
  updated catalog metadata when available, while retaining entry comment lines
  (`;` or `#`) from the installed menu and adding packaged entry comments. A
  185-entry retro menu stays at 185 entries, rather than being replaced with
  the packaged six-entry starter menu or expanded to all 431 engines. Custom
  entries are retained.
- MAME `mame.ini`, `ini/`, `cfg/` and `nvram/` settings/data.
- Unbundled engine files, personalities, and locally added `engines.ini` entries,
  so extra engines remain selectable. Files provided by the new packs, including
  `.uci` level files, use the new versions; previous customizations of those
  files remain in the backup for selective reapplication.

The same-name replacement rule also applies to Stockfish and LC0. The updater
does not compare engine versions or protect local builds with the same filename.
Older retro entries absent from the package remain in `retro.ini`, with their
unbundled engine files retained. Compiling newer engines is a separate workflow.

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
directories, including any ROMs collected after the update. Extra ROMs are
retained, but compatibility with the new MAME version must still be checked
using `./mess -verifyroms` and the software-list checker described below. The updater
does not rename ROMs, remove menu entries, or add every catalog entry.

`small` updates the architecture engine pack without replacing MAME or Rodent
resources already installed. To update the MAME resources, choose `large`.

## Shared LC0 weights

Both Linux package sizes download the same architecture-independent
[`lc0_weights.tar.gz` from v4.4.1](https://github.com/JohanSjoblom/picochess/releases/download/v4.4.1/lc0_weights.tar.gz).
It contains the previous 21 networks plus `tinygyal-8.pb.gz`, fixing
[issue #385](https://github.com/JohanSjoblom/picochess/issues/385). The files extract
directly into `engines/lc0_weights/`, without a parent directory in the archive.
These network files can also be used by native LC0 on Windows and macOS; they
contain no architecture-specific executables.

`install-picochess.sh` uses `install-engines.sh` for this download. The complete
archive is installed only when `engines/lc0_weights/` is missing. Existing
folders are left untouched, regardless of which networks they contain.
`update-engines.py` also reuses an existing weights folder without inspecting
individual files.

To refresh only the weights on an existing installation, stop PicoChess and
move the entire collection to a unique backup before reinstalling:

```bash
cd /opt/picochess
sudo systemctl stop picochess
mkdir -p "$HOME/pico_backups"
WEIGHTS_BACKUP=$(mktemp -d "$HOME/pico_backups/lc0-weights.XXXXXX")
mv engines/lc0_weights "$WEIGHTS_BACKUP/"
./install-engines.sh large
# Only restart after a successful installation:
sudo systemctl start picochess
```

Run the backup and engine installer as your normal user. Other existing engine
resource directories are skipped. The older `move-engines-to-backup.sh` workflow
also moves the whole weights folder, together with the other engine resources.

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

## Adding a MAME retro engine with AI assistance

This workflow is for Linux and Raspberry Pi installations with the matching
`large` engine and MAME packs. For a separate native UCI executable on any platform,
see [Adding your own UCI engine](add-own-engine.md).

The full list of supported retro entries is in
`engines/<arch>/engines_ini/all_retro.ini`, where `<arch>` is `x86_64` or
`aarch64`. `engines/<arch>/retro.ini` is the selection shown in PicoChess.
The catalog key, for example `[mame/mm5_exp]`, identifies the launcher under
`engines/<arch>/mame/`. The matching `.uci` file defines the available levels.
Read the launcher to identify the MAME system and any extra module it loads.
For example, `mm5` and `mm5_exp` both launch the `mm5` system. `mm5_exp`
also loads the `hg550` opening module from the `mephisto_mm5` software list.

PicoChess cannot redistribute every ROM a catalog entry needs. An assistant can
identify the required ROM names, check files you already have, and install ROMs
you provide and are allowed to use. Give it the engine name and the local path
to any ROM archives you have. If you have none, it can report which files to
obtain and where they belong. Save your game and stop PicoChess before making
changes.

> **Retro engine prompt for the assistant**
>
> Read this section and `AGENTS.md`. Help me add `<retro engine name or catalog
> key>` to this Linux PicoChess installation. My ROM files are in `<local path,
> or none yet>`. Find the installed architecture and matching entry in
> `engines_ini/all_retro.ini`. Check whether it is already in the active
> `retro.ini`. Inspect the packaged launcher and `.uci` file to confirm the exact
> variant, MAME system, and any cartridge or opening module. If several variants
> match, show me the differences so I can choose.
>
> Check the ROM search paths used by the launcher and MAME configuration. From
> the MAME directory, use `./mess -verifyroms <system>` to audit the system ROM
> and `./mess -listroms <system>` to identify missing files. Check parent or BIOS
> sets if the audit reports them. For a module or cartridge, identify the list
> and item with `./mess -listsoftware <system>` or the installed `hash/*.xml`
> files, then check that specific item in the output of
> `./mess -verifysoftlist <list>`. Software archives typically go in
> `<rompath>/<list>/<item>.zip`. Report exact missing filenames and destinations.
> Use only ROMs I provide and am allowed to use. Keep existing ROMs and backups,
> and ask before replacing a conflicting file. Keep ROMs out of git and release
> assets.
>
> If the required files are available, verify that PicoChess is stopped before
> making changes. Install only the required ROMs and repeat the targeted audits.
> Before adding the menu entry, run the supplied headless launcher with a bounded
> UCI check (`uci`, `isready`, and a short search that returns `bestmove`). Use
> temporary MAME config and NVRAM directories for the test so it preserves saved
> machine state. If an audit or the search fails, report the error and leave the
> menu as it was. After
> the checks pass, back up `retro.ini` and add only the selected catalog section
> if it is missing. Preserve the other entries and their order, and keep the
> selected entry's manufacturer directive and comments from the full catalog.
> Tell me what was installed, which checks passed, where the backup is, and which
> engine to select in the Retro menu when I restart PicoChess.

See the [MAME command-line reference](https://docs.mamedev.org/commandline/commandline-all.html)
and [ROM search paths](https://docs.mamedev.org/usingmame/assetsearch.html) for more
detail on the audits and archive placement.

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
