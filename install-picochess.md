# Picochess Installation Script — Variable Overview

This document explains the main variables used in the Picochess installation and update script.

## Engine package selection

Run `sudo ./install-picochess.sh small` for the minimum engine package (the default),
or `sudo ./install-picochess.sh large` for the larger package with MAME, Rodent
engines and PGN audio. This choice controls contents and download size,
independently of headless or desktop use. DGTPi clock support (`dgtpi`) and kiosk
setup (`kiosk`) are separate options and can be combined with either package.

`lite` remains a deprecated alias for `large` and prints a notice. The large
engine, MAME and Rodent downloads use `large` filenames from release
4.4.0. MAME resources now include Randy's MAME 0.289 build and updated artwork,
plugin, launch scripts and catalogs for aarch64 and x86_64. The installer also
installs the Qt 6 runtime required by the x86_64 build. See
[engine resource updates](install-engines.md#mame-0289-resources-for-both-architectures)
for existing-installation and ROM checks. Use `--help` for all options.

For an engine-only update that keeps collected ROMs and your retro menu
selection, stop PicoChess and run `./update-engines.py large` as your normal
install user. Use `--dry-run` to preview it. See
[preserving existing resources](install-engines.md#updating-without-losing-roms-or-retro-menu-selections).
On a fresh installation, `small` installs the minimum engine pack. On an existing
installation, the default, `pico` alone and explicit `small` leave engine resources
untouched. Only explicit `large` (or its legacy alias `lite`) uses the main
installer's clean backup/reinstall path; it does not perform this preservation
step. `noengines` skips engine installation even when `large` is supplied.

The Linux installer delegates LC0 network installation to `install-engines.sh`.
Both package sizes use the shared v4.4.0 weights archive, including
`tinygyal-8.pb.gz`. The full archive is downloaded only when the weights folder
is missing. To refresh an existing collection, move the whole folder to backup
first; no individual networks receive special treatment.

---

**REPO_DIR** - The full path where the Picochess repository is stored.  
Default: `/opt/picochess`

**BACKUP_DIR** - The directory where backups of the current Picochess installation are stored.  
Example: `/home/pi/pico_backups/current`

**TMPFILE** - Temporary file used during downloads, for example engine packages.  
Example: `/home/pi/pico_backups/current/tmp/engines-aarch64-small.tar.gz`

**ENGINE_URL** - The remote URL to download the default engine package from GitHub.

**ARCH** - The detected system architecture, such as `aarch64` or `x86_64`.  
Used to determine which engine package to install.

**BRANCH** - The current Git branch being tracked by the Picochess repository.  
Used to check if updates are available from GitHub.

**TAG_LIMIT** - The number of most recent tags to show when listing available versions.  
Default: `3`

**REMOTE_REPO** - The remote GitHub repository URL used for cloning or fetching updates.  
Default: `https://github.com/JohanSjoblom/picochess`

**GIT_USER** - The user account that performs git operations.  
Default: `pi`

**SERVICE_DIR** - Path to Picochess service files that integrate with `systemd`.  
Example: `/etc/systemd/system`

**PI_USER** - The primary user account on the Raspberry Pi used to run Picochess.  
Default: `pi`

---
