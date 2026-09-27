import unittest
import builtins
import runpy
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from legacy_kiosk import is_legacy_kiosk_command, stop_legacy_kiosk


class TestLegacyKiosk(unittest.TestCase):
    def test_unsupported_platform_needs_no_unix_modules_or_process_access(self):
        original_import = builtins.__import__

        def without_pwd(name, *args, **kwargs):
            if name == "pwd":
                raise ModuleNotFoundError("No module named 'pwd'")
            return original_import(name, *args, **kwargs)

        helper = Path(__file__).resolve().parents[1] / "legacy_kiosk.py"
        for platform in ("win32", "darwin"):
            with self.subTest(platform=platform), patch("sys.platform", platform), patch(
                "builtins.__import__", side_effect=without_pwd
            ), patch("os.getuid", create=True, side_effect=AssertionError("Unix API used")), patch(
                "pathlib.Path.iterdir", side_effect=AssertionError("Process scan attempted")
            ):
                runpy.run_path(str(helper), run_name="__main__")

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process cleanup")
    def test_unavailable_process_directory_does_not_interrupt_shutdown(self):
        with patch("legacy_kiosk.os.getuid", return_value=1000), patch(
            "pathlib.Path.iterdir", side_effect=PermissionError("proc unavailable")
        ), patch("legacy_kiosk.os.kill") as kill:
            stop_legacy_kiosk()
        kill.assert_not_called()

    def test_only_old_local_kiosk_matches(self):
        old = ["/usr/bin/chromium", "--password-store=basic", "--kiosk", "http://127.0.0.1:8080"]
        self.assertTrue(is_legacy_kiosk_command(old))
        self.assertTrue(is_legacy_kiosk_command(["chromium-browser", "--kiosk", "http://localhost"]))
        self.assertFalse(is_legacy_kiosk_command(old + ["--user-data-dir=/tmp/picochess-kiosk"]))
        self.assertFalse(is_legacy_kiosk_command(["chromium", "http://127.0.0.1:8080"]))
        self.assertFalse(is_legacy_kiosk_command(["chromium", "--kiosk", "https://example.com"]))
        self.assertFalse(is_legacy_kiosk_command(["chromium", "--kiosk", "http://127.0.0.1.example.com"]))

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process cleanup")
    def test_only_legacy_kiosk_process_is_terminated(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for pid, command in (
                (101, ["chromium", "--kiosk", "http://localhost"]),
                (102, ["chromium", "--kiosk", "http://localhost", "--user-data-dir=/tmp/picochess"]),
                (103, ["chromium", "https://example.com"]),
            ):
                process = root / str(pid)
                process.mkdir()
                (process / "cmdline").write_bytes("\0".join(command).encode() + b"\0")
            with patch("legacy_kiosk.os.kill") as kill:
                stop_legacy_kiosk(root)
            self.assertEqual(101, kill.call_args.args[0])
            self.assertEqual(1, kill.call_count)
