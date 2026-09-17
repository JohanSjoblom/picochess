import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGED_FILES_SCRIPT = REPO_ROOT / "install-managed-files.sh"


class TestInstallManagedFiles(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "source"
        self.target = self.root / "target"
        self.backup = self.root / "target.backup"

    def replace(self, *, respect_marker=True, executable=False):
        command = (
            '. "$1"; replace_managed_file "$2" "$3" "$4" '
            '"$5" "$6" ""'
        )
        return subprocess.run(
            [
                "sh",
                "-c",
                command,
                "managed-files-test",
                str(MANAGED_FILES_SCRIPT),
                str(self.source),
                str(self.target),
                str(self.backup),
                str(respect_marker).lower(),
                str(executable).lower(),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def ini_setting_is_true(self, contents, key="dgtpi"):
        ini_file = self.root / "settings.ini"
        ini_file.write_text(contents, encoding="utf-8")
        command = '. "$1"; ini_setting_is_true "$2" "$3"'
        return subprocess.run(
            [
                "sh",
                "-c",
                command,
                "managed-files-test",
                str(MANAGED_FILES_SCRIPT),
                str(ini_file),
                key,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_changed_file_is_backed_up_and_replaced(self):
        self.source.write_text("current\n", encoding="utf-8")
        self.target.write_text("customized\n", encoding="utf-8")

        result = self.replace()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("current\n", self.target.read_text(encoding="utf-8"))
        self.assertEqual("customized\n", self.backup.read_text(encoding="utf-8"))

    def test_second_update_does_not_overwrite_meaningful_backup(self):
        self.source.write_text("current\n", encoding="utf-8")
        self.target.write_text("customized\n", encoding="utf-8")

        self.assertEqual(0, self.replace().returncode)
        self.assertEqual(0, self.replace().returncode)

        self.assertEqual("customized\n", self.backup.read_text(encoding="utf-8"))

    def test_no_update_comment_skips_normal_refresh(self):
        self.source.write_text("current\n", encoding="utf-8")
        original = "#!/bin/sh\n  # no update  \necho custom\n"
        self.target.write_text(original, encoding="utf-8")

        result = self.replace(respect_marker=True)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(original, self.target.read_text(encoding="utf-8"))
        self.assertFalse(self.backup.exists())

    def test_reset_override_ignores_no_update_comment(self):
        self.source.write_text("current\n", encoding="utf-8")
        original = "# no update\ncustom\n"
        self.target.write_text(original, encoding="utf-8")

        result = self.replace(respect_marker=False)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("current\n", self.target.read_text(encoding="utf-8"))
        self.assertEqual(original, self.backup.read_text(encoding="utf-8"))

    def test_marker_words_inside_another_comment_do_not_opt_out(self):
        self.source.write_text("current\n", encoding="utf-8")
        self.target.write_text("# This is not the no update marker\n", encoding="utf-8")

        result = self.replace(respect_marker=True)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("current\n", self.target.read_text(encoding="utf-8"))

    def test_missing_target_is_created_without_backup(self):
        self.source.write_text("current\n", encoding="utf-8")

        result = self.replace(executable=True)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("current\n", self.target.read_text(encoding="utf-8"))
        self.assertTrue(os.access(self.target, os.X_OK))
        self.assertFalse(self.backup.exists())

    def test_missing_source_leaves_existing_target_unchanged(self):
        self.target.write_text("customized\n", encoding="utf-8")

        result = self.replace()

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("customized\n", self.target.read_text(encoding="utf-8"))
        self.assertFalse(self.backup.exists())

    def test_active_dgtpi_setting_selects_dgtpi_defaults(self):
        result = self.ini_setting_is_true("# dgtpi = False\n dgtpi = True # clock\n")

        self.assertEqual(0, result.returncode, result.stderr)

    def test_last_active_dgtpi_setting_wins(self):
        result = self.ini_setting_is_true("dgtpi = True\ndgtpi = False\n")

        self.assertNotEqual(0, result.returncode)


if __name__ == "__main__":
    unittest.main()
