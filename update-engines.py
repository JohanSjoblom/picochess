#!/usr/bin/env python3
"""Stage an engine-pack update while preserving ROMs and menu selections."""

import argparse
import configparser
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time


SHARED = ("lc0_weights", "script_engines", "pgn_engine/pgn_audio")
MAME_USER_DATA = ("roms", "cfg", "nvram", "ini", "mame.ini")


def exists(path):
    return path.exists() or path.is_symlink()


def remove(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif exists(path):
        path.unlink()


def merge(source, target, *, overwrite):
    """Copy user files without following symlinks in the destination tree."""
    if source.is_dir() and not source.is_symlink():
        if exists(target) and (target.is_symlink() or not target.is_dir()):
            if not overwrite:
                return
            remove(target)
        target.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            merge(child, target / child.name, overwrite=overwrite)
    else:
        if exists(target):
            if not overwrite:
                return
            remove(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            target.symlink_to(os.readlink(source))
        else:
            shutil.copy2(source, target)


def catalog(path):
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    manufacturers = {}
    if path.is_file():
        text = path.read_text(encoding="utf-8-sig")
        parser.read_string(text)
        manufacturer = ""
        for line in text.splitlines():
            directive = re.fullmatch(r"; Manufacturer: (.+?)\s*", line)
            section = re.fullmatch(r"\s*\[([^\]]+)\]\s*", line)
            if directive:
                manufacturer = directive[1].strip()
            elif section:
                manufacturers[section[1]] = manufacturer
    return parser, manufacturers


def preserve_menu(old_path, new_arch):
    """Keep selection/order, refreshing metadata from the downloaded catalogs."""
    if not old_path.is_file():
        return
    old, old_makers = catalog(old_path)
    available, makers = {}, {}
    for name in ("engines.ini", "retro.ini", "engines_ini/all_retro.ini"):
        current, current_makers = catalog(new_arch / name)
        for section in current.sections():
            available[section] = dict(current[section])
            makers[section] = current_makers.get(section, "")
    rows = []
    for section in old.sections():
        if section not in available:
            print(f"Keeping custom/older menu entry: {section}", flush=True)
        rows.append((section, available.get(section, dict(old[section])),
                     makers.get(section) or old_makers.get(section, "")))
    grouped = any(maker for _, _, maker in rows)
    text = "# Selection retained by update-engines.py; packaged metadata refreshed.\n\n"
    for section, values, maker in rows:
        if grouped:
            text += f"; Manufacturer: {maker or 'Other'}\n"
        single = configparser.ConfigParser(interpolation=None)
        single.optionxform = str
        single[section] = values
        output = io.StringIO()
        single.write(output)
        text += output.getvalue()
    (new_arch / old_path.name).write_text(text, encoding="utf-8")
    print(f"Preserved {old_path.name}: {len(rows)} entries in their original order", flush=True)


def swap(engines, staged, backup, resources):
    """Move old directories aside, rolling back if any replacement fails."""
    saved, installed = [], []
    originals = [name for name in resources if exists(engines / name)]
    manifest = {"resources": resources, "originals": originals, "status": "replacing"}
    manifest_path = backup / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    try:
        for name in resources:
            live, old, new = engines / name, backup / "old" / name, staged / name
            if exists(live):
                old.parent.mkdir(parents=True, exist_ok=True)
                live.rename(old)
                saved.append(name)
            if exists(new):
                live.parent.mkdir(parents=True, exist_ok=True)
                new.rename(live)
                installed.append(name)
        manifest["status"] = "complete"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except BaseException:
        for name in reversed(installed):
            remove(engines / name)
        for name in reversed(saved):
            (backup / "old" / name).rename(engines / name)
        manifest["status"] = "rolled back"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        raise


def validate_mame(path):
    result = subprocess.run(
        [str(path / "mess"), "-help"], cwd=path, capture_output=True, text=True,
        timeout=30, env={**os.environ, "SDL_VIDEODRIVER": "dummy"}, check=False,
    )
    if result.returncode:
        raise RuntimeError(
            "The downloaded MAME executable cannot run on this system. "
            "The v4.4.0 builds need Trixie-compatible libraries; x86_64 also needs "
            "libqt6gui6 and libqt6widgets6.\n" + result.stdout + result.stderr
        )
    print(result.stdout.splitlines()[0], flush=True)


def update(repo, arch, variant, backup):
    engines = repo / "engines"
    with tempfile.TemporaryDirectory(prefix="staging-", dir=backup) as directory:
        staged_repo = Path(directory)
        staged = staged_repo / "engines"
        staged.mkdir()
        # These packs have not changed; retain installed resources without another download.
        for name in SHARED:
            if exists(engines / name) and (variant == "large" or name != "pgn_engine/pgn_audio"):
                link = staged / name
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(engines / name, target_is_directory=True)
        subprocess.run(
            ["sh", str(repo / "install-engines.sh"), variant],
            env={**os.environ, "REPO_DIR": str(staged_repo)}, check=True,
        )
        resources = [arch]
        if variant == "large":
            resources += ["mame_emulation", "rodent3", "rodent4"]
        resources += [name for name in SHARED if (staged / name).is_dir()
                      and not (staged / name).is_symlink()]
        for name in resources:
            if not (staged / name).is_dir() or not any((staged / name).iterdir()):
                raise RuntimeError(f"Downloaded resource is missing or empty: {name}")
        if not (staged / arch / "engines.ini").is_file():
            raise RuntimeError("Downloaded engine pack has no engines.ini")
        # Refresh menus before adding any older, unbundled files to the new tree.
        for menu in ("retro.ini", "favorites.ini"):
            preserve_menu(engines / arch / menu, staged / arch)
        for name in resources:
            source, target = engines / name, staged / name
            if source.is_dir():
                merge(source, target, overwrite=False)
        if variant == "large":
            for name in MAME_USER_DATA:
                source = engines / "mame_emulation" / name
                if exists(source):
                    merge(source, staged / "mame_emulation" / name, overwrite=True)
            validate_mame(staged / "mame_emulation")
        swap(engines, staged, backup, resources)


def restore(repo, arch, source, backup):
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    resources = manifest["resources"]
    originals = manifest["originals"]
    allowed = {arch, "mame_emulation", "rodent3", "rodent4", *SHARED}
    if manifest["status"] != "complete" or not set(originals) <= set(resources) <= allowed:
        raise RuntimeError("Not a completed update backup for this architecture")
    with tempfile.TemporaryDirectory(prefix="restoring-", dir=backup) as directory:
        staged = Path(directory)
        for name in originals:
            old = source / "old" / name
            if not exists(old):
                raise RuntimeError(f"Backup is missing {name}; no resources restored")
            merge(old, staged / name, overwrite=True)
        swap(repo / "engines", staged, backup, resources)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variant", nargs="?", choices=("small", "large"))
    parser.add_argument("--dry-run", action="store_true", help="Show the plan without downloads or changes")
    parser.add_argument("--restore", type=Path, metavar="BACKUP", help="Restore an update backup")
    args = parser.parse_args()
    if bool(args.variant) == bool(args.restore):
        parser.error("Specify small/large, or --restore BACKUP")
    if sys.platform != "linux":
        parser.error("This updater installs Linux resource packs only")
    import fcntl

    repo = Path(os.environ.get("REPO_DIR", Path(__file__).resolve().parent)).resolve()
    arch = platform.machine()
    if arch not in ("aarch64", "x86_64"):
        parser.error(f"Unsupported architecture: {arch}")
    if not (repo / "install-engines.sh").is_file():
        parser.error(f"No install-engines.sh in {repo}")
    print(f"Repository: {repo}\nArchitecture: {arch}", flush=True)
    if args.restore:
        print(f"Restore from: {args.restore.resolve()}", flush=True)
    else:
        print(f"Update: {args.variant}; preserve ROMs, MAME settings, retro/favorites selections "
              "and unbundled files. Packaged engine settings are refreshed.", flush=True)
        old_menu, _ = catalog(repo / "engines" / arch / "retro.ini")
        print(f"Current retro menu: {len(old_menu.sections())} entries", flush=True)
    print("PicoChess must be stopped, including any manually started instance.", flush=True)
    if args.dry_run:
        return 0
    if os.geteuid() == 0:
        parser.error("Run as your normal install user, without sudo")
    if shutil.which("systemctl") and subprocess.run(
        ["systemctl", "is-active", "--quiet", "picochess"], capture_output=True, check=False,
    ).returncode == 0:
        parser.error("PicoChess is running. Stop it with sudo systemctl stop picochess")
    backup_root = repo / "engines" / ".update-backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    with (backup_root / ".lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("Another engine update is in progress")
        backup = Path(tempfile.mkdtemp(prefix=time.strftime("%Y%m%d-%H%M%S-"), dir=backup_root))
        print(f"Backup: {backup}", flush=True)
        try:
            if args.restore:
                restore(repo, arch, args.restore.resolve(), backup)
            else:
                update(repo, arch, args.variant, backup)
        except (OSError, RuntimeError, ValueError, configparser.Error, subprocess.SubprocessError) as error:
            print(f"Update failed: {error}\nCheck the live resources and {backup} "
                  "before restarting PicoChess.", file=sys.stderr)
            return 1
    print(f"Complete. Backup retained at {backup}\n"
          f"To undo: ./update-engines.py --restore '{backup}'\n"
          "You can now start PicoChess. ROM compatibility still needs MAME verification.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
