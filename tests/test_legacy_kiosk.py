import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from legacy_kiosk import is_legacy_kiosk_command, stop_legacy_kiosk


class TestLegacyKiosk(unittest.TestCase):
    def test_only_old_local_kiosk_matches(self):
        old = ["/usr/bin/chromium", "--password-store=basic", "--kiosk", "http://127.0.0.1:8080"]
        self.assertTrue(is_legacy_kiosk_command(old))
        self.assertTrue(is_legacy_kiosk_command(["chromium-browser", "--kiosk", "http://localhost"]))
        self.assertFalse(is_legacy_kiosk_command(old + ["--user-data-dir=/tmp/picochess-kiosk"]))
        self.assertFalse(is_legacy_kiosk_command(["chromium", "http://127.0.0.1:8080"]))
        self.assertFalse(is_legacy_kiosk_command(["chromium", "--kiosk", "https://example.com"]))
        self.assertFalse(is_legacy_kiosk_command(["chromium", "--kiosk", "http://127.0.0.1.example.com"]))

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
