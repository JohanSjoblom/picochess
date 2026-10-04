import unittest
import builtins
import runpy
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from legacy_kiosk import configured_kiosk_port, has_legacy_windowed_launcher, is_legacy_kiosk_command, stop_legacy_kiosk


class TestLegacyKiosk(unittest.TestCase):
    def test_old_wayland_launcher_without_kiosk_flag_is_recognized(self):
        with TemporaryDirectory() as directory:
            home = Path(directory)
            launcher = home / "kiosk.sh"
            self.assertFalse(has_legacy_windowed_launcher(home, 80))
            launcher.write_text(
                '#!/bin/bash\n/usr/bin/chromium \\\n'
                '    --password-store=basic \\\n'
                '    http://127.0.0.1 &\n'
            )
            self.assertTrue(has_legacy_windowed_launcher(home, 80))
            self.assertFalse(has_legacy_windowed_launcher(home, 8080))
            launcher.write_text('# /usr/bin/chromium --password-store=basic http://127.0.0.1 &\n')
            self.assertFalse(has_legacy_windowed_launcher(home, 80))
            launcher.write_text('/usr/bin/chromium --user-data-dir=/tmp/pico --password-store=basic http://127.0.0.1 &\n')
            self.assertFalse(has_legacy_windowed_launcher(home, 80))

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process cleanup")
    def test_windowed_browser_cleanup_requires_matching_installed_launcher(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            process = root / "101"
            process.mkdir()
            command = ["chromium", "--password-store=basic", "http://127.0.0.1"]
            (process / "cmdline").write_bytes("\0".join(command).encode() + b"\0")
            with patch("legacy_kiosk.os.getuid", return_value=root.stat().st_uid), patch.dict(
                "os.environ", {"SUDO_USER": "root"}
            ), patch("pwd.getpwuid", return_value=SimpleNamespace(pw_dir=str(home))), patch(
                "legacy_kiosk.os.kill"
            ) as kill:
                stop_legacy_kiosk(root, web_port=80)
                kill.assert_not_called()
                (home / "kiosk.sh").write_text(
                    "/usr/bin/chromium --password-store=basic http://127.0.0.1 &\n"
                )
                stop_legacy_kiosk(root, web_port=80)
                kill.assert_called_once()
                self.assertEqual(kill.call_args.args[0], 101)

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
            ), patch("sys.argv", [str(helper)]):
                runpy.run_path(str(helper), run_name="__main__")

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process cleanup")
    def test_unavailable_process_directory_does_not_interrupt_shutdown(self):
        with patch("legacy_kiosk.os.getuid", return_value=1000), patch(
            "pathlib.Path.iterdir", side_effect=PermissionError("proc unavailable")
        ), patch("legacy_kiosk.os.kill") as kill:
            stop_legacy_kiosk(web_port=80)
        kill.assert_not_called()

    def test_only_old_local_kiosk_matches(self):
        old = ["/usr/bin/chromium", "--password-store=basic", "--kiosk", "http://127.0.0.1:8080"]
        self.assertTrue(is_legacy_kiosk_command(old, 8080))
        self.assertFalse(is_legacy_kiosk_command(old, 80))
        self.assertTrue(is_legacy_kiosk_command(
            ["chromium-browser", "--password-store=basic", "--kiosk", "http://localhost/"], 80
        ))
        self.assertFalse(is_legacy_kiosk_command(old + ["--user-data-dir=/tmp/picochess-kiosk"], 8080))
        self.assertFalse(is_legacy_kiosk_command(["chromium", "http://127.0.0.1:8080"], 8080))
        self.assertFalse(is_legacy_kiosk_command(["chromium", "--kiosk", "http://localhost:8080"], 8080))
        self.assertFalse(is_legacy_kiosk_command(old + ["http://localhost:9090/dashboard"], 8080))

    def test_other_local_services_and_paths_are_excluded(self):
        for url in (
            "http://localhost:9090/dashboard", "http://localhost:9090/",
            "http://localhost:8080/dashboard", "http://localhost:8080/?app=other",
            "http://localhost:8080/#dashboard", "https://localhost:8080/",
            "http://127.0.0.1.example.com:8080", "http://localhost:invalid/",
            "http://user@localhost:8080/",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_legacy_kiosk_command(
                    ["chromium", "--password-store=basic", "--kiosk", url], 8080
                ))

    def test_configured_port_is_explicit_and_valid(self):
        with TemporaryDirectory() as directory:
            config = Path(directory) / "picochess.ini"
            self.assertIsNone(configured_kiosk_port(config))
            for setting, expected in (
                ("# web-server = 9090\nweb-server = 8080 # local web\n", 8080),
                ("web-server = 80\nweb-server = 1234\n", 1234),
                ("", None), ("web-server = 0", None),
                ("web-server = bad", None), ("web-server = 65536", None),
            ):
                with self.subTest(setting=setting):
                    config.write_text(setting)
                    self.assertEqual(expected, configured_kiosk_port(config))

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process cleanup")
    def test_unknown_endpoint_skips_process_scan(self):
        with patch("legacy_kiosk.configured_kiosk_port", return_value=None), patch(
            "pathlib.Path.iterdir", side_effect=AssertionError("Unknown endpoint must not scan")
        ):
            stop_legacy_kiosk()

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process cleanup")
    def test_only_legacy_kiosk_process_is_terminated(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = ["chromium", "--password-store=basic", "--kiosk"]
            for pid, command in (
                (101, prefix + ["http://localhost:8080"]),
                (102, prefix + ["http://localhost:8080", "--user-data-dir=/tmp/picochess"]),
                (103, ["chromium", "https://example.com"]),
                (104, prefix + ["http://localhost:9090/dashboard"]),
                (105, prefix + ["http://localhost:8080/dashboard"]),
            ):
                process = root / str(pid)
                process.mkdir()
                (process / "cmdline").write_bytes("\0".join(command).encode() + b"\0")
            with patch("legacy_kiosk.os.kill") as kill, patch(
                "legacy_kiosk.os.getuid", return_value=root.stat().st_uid
            ), patch.dict("os.environ", {"SUDO_USER": "root"}):
                stop_legacy_kiosk(root, web_port=8080)
            self.assertEqual(101, kill.call_args.args[0])
            self.assertEqual(1, kill.call_count)
