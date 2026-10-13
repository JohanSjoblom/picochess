import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGED_FILES_SCRIPT = REPO_ROOT / "install-managed-files.sh"
INSTALLER_SCRIPT = REPO_ROOT / "install-picochess.sh"


class TestInstallManagedFiles(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "source"
        self.target = self.root / "target"
        self.backup = self.root / "target.backup"

    def replace(self, *, respect_marker=True, executable=False, owner="", env=None):
        command = (
            '. "$1"; replace_managed_file "$2" "$3" "$4" '
            '"$5" "$6" "$7"'
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
                owner,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def remove_managed_block(self, contents, begin, end):
        block_file = self.root / "config.txt"
        block_backup = self.root / "config.txt.backup"
        block_file.write_text(contents, encoding="utf-8")
        command = '. "$1"; remove_managed_block "$2" "$3" "$4" "$5"'
        result = subprocess.run(
            [
                "sh",
                "-c",
                command,
                "managed-files-test",
                str(MANAGED_FILES_SCRIPT),
                str(block_file),
                begin,
                end,
                str(block_backup),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        return result, block_file, block_backup

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

    def select_ini_profile(
        self,
        contents="",
        *,
        install_dgtpi=False,
        install_dgt3000=False,
        reset=True,
    ):
        ini_file = self.root / "profile.ini"
        ini_file.write_text(contents, encoding="utf-8")
        command = '. "$1"; select_ini_profile "$2" "$3" "$4" "$5"'
        return subprocess.run(
            [
                "sh",
                "-c",
                command,
                "managed-files-test",
                str(MANAGED_FILES_SCRIPT),
                str(install_dgtpi).lower(),
                str(install_dgt3000).lower(),
                str(reset).lower(),
                str(ini_file),
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

    def test_unchanged_executable_has_execute_permission_repaired(self):
        self.source.write_text("current\n", encoding="utf-8")
        self.target.write_text("current\n", encoding="utf-8")
        self.target.chmod(0o600)

        result = self.replace(executable=True)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(os.access(self.target, os.X_OK))
        self.assertFalse(self.backup.exists())

    def test_unchanged_file_has_owner_reapplied(self):
        self.source.write_text("current\n", encoding="utf-8")
        self.target.write_text("current\n", encoding="utf-8")
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        chown_log = self.root / "chown.log"
        fake_chown = fake_bin / "chown"
        fake_chown.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" > "$CHOWN_LOG"\n',
            encoding="utf-8",
        )
        fake_chown.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
        env["CHOWN_LOG"] = str(chown_log)

        result = self.replace(owner="pico", env=env)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"pico:pico {self.target}\n", chown_log.read_text(encoding="utf-8"))
        self.assertFalse(self.backup.exists())

    def test_complete_managed_block_is_removed_with_backup(self):
        begin = "# BEGIN PicoChess DGTPi clock timing"
        end = "# END PicoChess DGTPi clock timing"
        original = f"before\n{begin}\ncore_freq=300\n{end}\nafter\n"

        result, block_file, block_backup = self.remove_managed_block(original, begin, end)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("before\nafter\n", block_file.read_text(encoding="utf-8"))
        self.assertEqual(original, block_backup.read_text(encoding="utf-8"))

    def test_incomplete_managed_block_is_left_unchanged(self):
        begin = "# BEGIN PicoChess DGTPi clock timing"
        end = "# END PicoChess DGTPi clock timing"
        original = f"before\n{begin}\ncore_freq=300\n"

        result, block_file, block_backup = self.remove_managed_block(original, begin, end)

        self.assertNotEqual(0, result.returncode)
        self.assertEqual(original, block_file.read_text(encoding="utf-8"))
        self.assertFalse(block_backup.exists())

    def test_missing_managed_block_is_idempotent_without_backup(self):
        begin = "# BEGIN PicoChess DGTPi clock timing"
        end = "# END PicoChess DGTPi clock timing"
        original = "before\nafter\n"

        result, block_file, block_backup = self.remove_managed_block(original, begin, end)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(original, block_file.read_text(encoding="utf-8"))
        self.assertFalse(block_backup.exists())

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

    def test_explicit_dgtpi_selects_dgtpi_profile(self):
        result = self.select_ini_profile(install_dgtpi=True)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("dgtpi", result.stdout.strip())

    def test_explicit_dgt3000_selects_web_profile_even_if_old_ini_says_dgtpi(self):
        result = self.select_ini_profile(
            "dgtpi = True\n",
            install_dgt3000=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("web", result.stdout.strip())

    def test_reset_without_hardware_flag_preserves_existing_dgtpi_profile(self):
        result = self.select_ini_profile("dgtpi = True\n")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("dgtpi", result.stdout.strip())

    def test_reset_without_hardware_flag_uses_web_profile_for_dgt3000_ini(self):
        result = self.select_ini_profile("dgtpi = False\n")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("web", result.stdout.strip())


class TestInstallerHardwareProfiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.installer = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    def test_dgt3000_and_dgtpi_arguments_are_parsed_separately(self):
        self.assertIn(
            "dgt3000|DGT3000)\n            INSTALL_DGT3000=true",
            self.installer,
        )
        self.assertIn(
            "dgtpi|DGTPi|DGTPI)\n            INSTALL_DGTPI=true",
            self.installer,
        )
        self.assertNotIn("dgt3000|DGT3000|dgtpi", self.installer)

    def test_dgtpi_installs_and_dgt3000_removes_gpio_clock_support(self):
        clock_install = self.installer.index("# Install DGTPi clock support, or remove legacy GPIO support")
        bluetooth_install = self.installer.index("# Install Bluetooth unblock service", clock_install)
        section = self.installer[clock_install:bluetooth_install]

        self.assertIn('if [ "$INSTALL_DGTPI" = true ]; then', section)
        self.assertIn("./install-dgtpi-clock.sh", section)
        self.assertIn('elif [ "$INSTALL_DGT3000" = true ]; then', section)
        self.assertIn("remove_dgtpi_clock_support || exit 1", section)

    def test_dgt3000_cleanup_disables_service_and_removes_timing_block(self):
        cleanup = self.installer[
            self.installer.index("remove_dgtpi_clock_timing()"):
            self.installer.index('if [ "$SKIP_UPDATE" = false ]')
        ]

        self.assertIn("systemctl disable dgtpi.service", cleanup)
        self.assertIn("/etc/systemd/system/dgtpi.service", cleanup)
        self.assertIn('rm -f "$dgtpi_service"', cleanup)
        self.assertIn("# BEGIN PicoChess DGTPi clock timing", cleanup)
        self.assertIn("remove_managed_block", cleanup)

    def test_conflicting_clock_hardware_flags_are_rejected(self):
        self.assertIn(
            'if [ "$INSTALL_DGTPI" = true ] && [ "$INSTALL_DGT3000" = true ]; then',
            self.installer,
        )
        self.assertIn("choose either dgtpi or dgt3000, not both", self.installer)


if __name__ == "__main__":
    unittest.main()
