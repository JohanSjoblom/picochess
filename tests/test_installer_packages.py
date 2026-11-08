import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestInstallerPackages(unittest.TestCase):
    def test_help_is_safe_without_an_install_user(self):
        for script in ("install-picochess.sh", "install-engines.sh"):
            with self.subTest(script=script):
                result = subprocess.run(
                    ["sh", str(REPO_ROOT / script), "--help"],
                    env={**os.environ, "USER": "root", "SUDO_USER": "root"},
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("small|large", result.stdout)
                self.assertIn("headless or desktop", result.stdout)

    def test_main_installer_keeps_package_and_hardware_options_independent(self):
        # Stop before installation: exercise the real parser without system changes.
        source = (REPO_ROOT / "install-picochess.sh").read_text()
        parser = source.split("set_ini_setting()", 1)[0]
        parser += '\nprintf "%s %s %s %s\\n" "$ENGINE_VARIANT" "$EXPLICIT_ENGINE_VARIANT" '
        parser += '"$INSTALL_DGTPI" "$INSTALL_KIOSK"\n'
        cases = [
            ([], "small false false false"),
            (["small"], "small true false false"),
            (["large"], "large true false false"),
            (["lite"], "large true false false"),
            (["large", "dgtpi", "kiosk"], "large true true true"),
            (["pico", "lite", "dgtpi"], "large true true false"),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                result = subprocess.run(
                    ["sh", "-c", parser, "installer-test", *args],
                    env={**os.environ, "SUDO_USER": "pi"},
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(expected, result.stdout.strip())
                self.assertEqual("lite" in args, "deprecated" in result.stderr)

    def install_engines(self, arch, variant):
        # Real script, isolated filesystem; replace downloads/extraction with logs.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            stubs = {
                "uname": '#!/bin/sh\nprintf "%s\\n" "$TEST_ARCH"\n',
                "curl": '#!/bin/sh\nprintf "%s\\n" "$4" >> "$DOWNLOAD_LOG"\n',
                "tar": "#!/bin/sh\nexit 0\n",
            }
            for name, contents in stubs.items():
                path = fake_bin / name
                path.write_text(contents)
                path.chmod(0o755)
            log = root / "downloads"
            result = subprocess.run(
                ["sh", str(REPO_ROOT / "install-engines.sh"), variant],
                env={
                    **os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "REPO_DIR": str(root), "HOME": str(root), "SUDO_USER": "pi",
                    "TEST_ARCH": arch, "DOWNLOAD_LOG": str(log),
                },
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            return log.read_text().splitlines(), result

    def test_large_and_legacy_alias_select_identical_bundles_on_both_architectures(self):
        for arch in ("aarch64", "x86_64"):
            with self.subTest(arch=arch):
                large, result = self.install_engines(arch, "large")
                legacy, alias_result = self.install_engines(arch, "lite")
                self.assertEqual(large, legacy)
                self.assertEqual(7, len(large))
                for component in ("lite.tar.gz", "mame", "rodent3", "rodent4", "pgn_audio"):
                    self.assertTrue(any(component in url for url in large), component)
                self.assertIn("variant: large", result.stdout)
                self.assertNotIn("deprecated", result.stderr)
                self.assertIn('use "large" instead', alias_result.stderr)

    def test_small_excludes_large_addons_on_both_architectures(self):
        for arch in ("aarch64", "x86_64"):
            with self.subTest(arch=arch):
                urls, _ = self.install_engines(arch, "small")
                self.assertEqual(3, len(urls))
                self.assertIn("small.tar.gz", urls[0])
                self.assertTrue(any("lc0_weights" in url for url in urls))
                self.assertTrue(any("script_engines" in url for url in urls))

    def test_engine_installer_requires_a_valid_package(self):
        for args in ([], ["medium"], ["invalid"]):
            with self.subTest(args=args):
                result = subprocess.run(
                    ["sh", str(REPO_ROOT / "install-engines.sh"), *args],
                    capture_output=True, text=True, check=False,
                )
                self.assertNotEqual(0, result.returncode)
                self.assertIn("small|large", result.stdout)
