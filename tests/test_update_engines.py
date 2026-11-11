import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("update_engines", REPO / "update-engines.py")
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


def entry(name, label, ponder="n"):
    return f"[{name}]\nname = {label}\nlarge = {label}\nponder/brain = {ponder}\n\n"


@unittest.skipUnless(sys.platform == "linux", "Linux engine resource updater")
class TestUpdateEngines(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.engines = self.repo / "engines"
        self.engines.mkdir(parents=True)
        self.assets = self.root / "assets"
        self.assets.mkdir()
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        for name, body in {
            "uname": 'printf "%s\\n" "$TEST_ARCH"\n',
            "curl": 'name=${4##*/}\nprintf "%s\\n" "$name" >> "$DOWNLOAD_LOG"\n'
                    '[ "$name" != "$FAIL_DOWNLOAD" ] || exit 22\n'
                    'cp "$FIXTURE_ASSETS/$name" "$3"\n',
        }.items():
            target = self.fake_bin / name
            target.write_text("#!/bin/sh\n" + body)
            target.chmod(0o755)
        shutil.copy2(REPO / "install-engines.sh", self.repo)
        self.env = {
            **os.environ, "PATH": f"{self.fake_bin}:{os.environ['PATH']}",
            "HOME": str(self.root), "USER": "installer-test", "SUDO_USER": "installer-test",
            "FIXTURE_ASSETS": str(self.assets), "DOWNLOAD_LOG": str(self.root / "downloads"),
            "TEST_ARCH": "x86_64", "FAIL_DOWNLOAD": "", "FAIL_MAME": "",
        }
        self.backup = self.engines / ".update-backups" / "first"
        self.backup.mkdir(parents=True)

    def write(self, relative, contents):
        path = self.engines / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)

    def archive(self, name, contents):
        with tarfile.open(self.assets / name, "w:gz") as archive:
            for relative, value in contents.items():
                data = value.encode()
                info = tarfile.TarInfo(relative)
                info.size = len(data)
                info.mode = 0o755 if relative in ("mess", "mame/mm5", "a-stockf") else 0o644
                archive.addfile(info, io.BytesIO(data))

    def prepare(self, arch="x86_64"):
        self.env["TEST_ARCH"] = arch
        self.write(f"{arch}/retro.ini", entry("mame/borisa", "Old Boris", "y")
                   + entry("mame/mm5", "Old MM5") + entry("mame/custom", "My engine"))
        self.write(f"{arch}/favorites.ini", entry("mame/mm5", "Old favorite"))
        self.write(f"{arch}/mame/custom", "custom executable")
        self.write(f"{arch}/mame/mm5.uci", "old levels")
        self.write("mame_emulation/roms/classic.zip", "different classic ROM")
        self.write("mame_emulation/roms/saitek_schess/classic.zip", "Sensor Chess ROM")
        self.write("mame_emulation/roms/default.zip", "user ROM takes precedence")
        self.write("mame_emulation/mame.ini", "rompath roms;some-other-folder\n")
        self.write("mame_emulation/nvram/mm5/state", "old NVRAM")
        self.write("rodent3/personalities/custom.txt", "my personality")
        self.write("rodent4/old.txt", "old rodent")
        for name in updater.SHARED:
            self.write(f"{name}/keep", "existing shared resource")
        prefix = "engines-aarch64-large" if arch == "aarch64" else "x86_64_engines_large"
        self.archive(prefix + ".tar.gz", {
            "engines.ini": entry("a-stockf", "New Stockfish"),
            "a-stockf": "#!/bin/sh\nexit 0\n",
            "retro.ini": entry("mame/mm5", "Packaged default"),
            "engines_ini/all_retro.ini": "; Manufacturer: Chafitz\n" + entry("mame/borisa", "New Boris")
            + "; Manufacturer: Mephisto\n" + entry("mame/mm5", "New MM5"),
            "mame/mm5": "#!/bin/sh\nexit 0\n", "mame/mm5.uci": "updated levels",
        })
        mame = "engines-mame-large" if arch == "aarch64" else "x86_64_mame_large"
        self.archive(mame + ".tar.gz", {
            "mess": '#!/bin/sh\n[ -z "$FAIL_MAME" ] || { echo "missing libc" >&2; exit 127; }\n'
                    'echo "MAME test build"\n',
            "artwork/mm5/new.png": "new artwork", "mame.ini": "packaged settings",
            "roms/default.zip": "bundled ROM", "roms/new.zip": "new bundled ROM",
        })
        rodent3 = "engines-rodent3-large" if arch == "aarch64" else "x86_64_rodent3_large"
        rodent4 = "aarch64_rodent4_large" if arch == "aarch64" else "x86_64_rodent4_large"
        self.archive(rodent3 + ".tar.gz", {"new.txt": "new rodent3"})
        self.archive(rodent4 + ".tar.gz", {"new.txt": "new rodent4"})

    def update(self, arch="x86_64"):
        with patch.dict(os.environ, self.env), contextlib.redirect_stdout(io.StringIO()):
            updater.update(self.repo, arch, "large", self.backup)

    def snapshot(self):
        return {str(p.relative_to(self.engines)): p.read_bytes()
                for p in self.engines.rglob("*")
                if p.is_file() and ".update-backups" not in p.parts}

    def test_update_preserves_collection_selection_and_custom_files(self):
        self.prepare()
        self.update()
        menu, makers = updater.catalog(self.engines / "x86_64/retro.ini")
        self.assertEqual(["mame/borisa", "mame/mm5", "mame/custom"], menu.sections())
        self.assertEqual("New Boris", menu["mame/borisa"]["name"])
        self.assertEqual("n", menu["mame/borisa"]["ponder/brain"])
        self.assertEqual("Chafitz", makers["mame/borisa"])
        self.assertEqual("Other", makers["mame/custom"])
        favorites, _ = updater.catalog(self.engines / "x86_64/favorites.ini")
        self.assertEqual("New MM5", favorites["mame/mm5"]["name"])
        for name, expected in {
            "mame_emulation/roms/classic.zip": "different classic ROM",
            "mame_emulation/roms/saitek_schess/classic.zip": "Sensor Chess ROM",
            "mame_emulation/roms/default.zip": "user ROM takes precedence",
            "mame_emulation/roms/new.zip": "new bundled ROM",
            "mame_emulation/artwork/mm5/new.png": "new artwork",
            "mame_emulation/nvram/mm5/state": "old NVRAM",
            "x86_64/mame/mm5.uci": "updated levels",
            "x86_64/mame/custom": "custom executable",
            "rodent3/personalities/custom.txt": "my personality",
        }.items():
            self.assertEqual(expected, (self.engines / name).read_text(), name)
        self.assertEqual("rompath roms;some-other-folder\n",
                         (self.engines / "mame_emulation/mame.ini").read_text())
        self.assertEqual("old levels", (self.backup / "old/x86_64/mame/mm5.uci").read_text())
        self.assertEqual(4, len((self.root / "downloads").read_text().splitlines()))
        for name in updater.SHARED:
            self.assertEqual("existing shared resource", (self.engines / name / "keep").read_text())

    def test_aarch64_uses_matching_archives_and_retains_menu(self):
        self.prepare("aarch64")
        self.update("aarch64")
        menu, _ = updater.catalog(self.engines / "aarch64/retro.ini")
        self.assertEqual(3, len(menu.sections()))
        self.assertIn("engines-mame-large.tar.gz", (self.root / "downloads").read_text())

    def test_small_update_does_not_replace_existing_mame_or_rodent(self):
        self.prepare()
        self.archive("engines-x86_64-small.tar.gz", {
            "engines.ini": entry("a-stockf", "New Stockfish"), "a-stockf": "new engine",
        })
        before = self.snapshot()
        with patch.dict(os.environ, self.env), contextlib.redirect_stdout(io.StringIO()):
            updater.update(self.repo, "x86_64", "small", self.backup)
        after = self.snapshot()
        for name, data in before.items():
            if not name.startswith("x86_64/"):
                self.assertEqual(data, after[name], name)
        self.assertEqual(["engines-x86_64-small.tar.gz"],
                         (self.root / "downloads").read_text().splitlines())

    def test_dry_run_does_not_download_or_create_a_backup(self):
        self.prepare(updater.platform.machine())
        before = self.snapshot()
        result = subprocess.run(
            [sys.executable, str(REPO / "update-engines.py"), "large", "--dry-run"],
            env={**self.env, "REPO_DIR": str(self.repo)},
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Current retro menu: 3 entries", result.stdout)
        self.assertFalse((self.root / "downloads").exists())
        self.assertEqual([self.backup], list(self.backup.parent.iterdir()))
        self.assertEqual(before, self.snapshot())

    def test_late_download_failure_leaves_every_live_file_unchanged(self):
        self.prepare()
        before = self.snapshot()
        self.env["FAIL_DOWNLOAD"] = "x86_64_rodent3_large.tar.gz"
        with self.assertRaises(updater.subprocess.CalledProcessError):
            self.update()
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.backup / "old").exists())

    def test_incompatible_mame_leaves_every_live_file_unchanged(self):
        self.prepare()
        before = self.snapshot()
        self.env["FAIL_MAME"] = "yes"
        with self.assertRaisesRegex(RuntimeError, "missing libc"):
            self.update()
        self.assertEqual(before, self.snapshot())

    def test_replacement_failure_rolls_back_already_replaced_directories(self):
        self.prepare()
        before = self.snapshot()
        rename = Path.rename

        def fail_one(path, target):
            if path.name == "mame_emulation" and "staging-" in str(path):
                raise OSError("simulated replacement failure")
            return rename(path, target)

        with patch.object(Path, "rename", fail_one), self.assertRaisesRegex(OSError, "simulated"):
            self.update()
        self.assertEqual(before, self.snapshot())

    def test_restore_keeps_a_backup_of_the_replaced_installation(self):
        self.prepare()
        before = self.snapshot()
        self.update()
        self.write("mame_emulation/roms/collected-after-update.zip", "another ROM")
        restore_backup = self.engines / ".update-backups/second"
        restore_backup.mkdir()
        updater.restore(self.repo, "x86_64", self.backup, restore_backup)
        self.assertEqual(before, self.snapshot())
        collected = restore_backup / "old/mame_emulation/roms/collected-after-update.zip"
        self.assertEqual("another ROM", collected.read_text())

    def test_restore_removes_shared_pack_that_was_absent_before_update(self):
        self.prepare()
        shutil.rmtree(self.engines / "lc0_weights")
        self.archive("lc0_weights.tar.gz", {"new-weights": "downloaded weights"})
        self.update()
        self.assertTrue((self.engines / "lc0_weights/new-weights").is_file())
        restore_backup = self.engines / ".update-backups/second"
        restore_backup.mkdir()
        updater.restore(self.repo, "x86_64", self.backup, restore_backup)
        self.assertFalse((self.engines / "lc0_weights").exists())
        self.assertTrue((restore_backup / "old/lc0_weights/new-weights").is_file())

    def test_merge_does_not_write_through_destination_symlinks(self):
        outside = self.root / "external"
        outside.mkdir()
        (outside / "rom.zip").write_text("untouched")
        source = self.root / "source"
        source.mkdir()
        (source / "rom.zip").write_text("preserved")
        target = self.root / "target"
        target.symlink_to(outside, target_is_directory=True)
        updater.merge(source, target, overwrite=True)
        self.assertFalse(target.is_symlink())
        self.assertEqual("untouched", (outside / "rom.zip").read_text())
        self.assertEqual("preserved", (target / "rom.zip").read_text())
