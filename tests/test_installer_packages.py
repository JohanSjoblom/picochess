import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestInstallerPackages(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        fake_bin = root / "bin"
        fake_bin.mkdir()
        self.sudo_log = root / "sudo-called"
        stubs = {
            "getent": (
                '#!/bin/sh\n[ "$1" = passwd ] && [ "$2" = installer-test ] || exit 2\n'
                'printf "installer-test:x:1000:1000:Test:%s:/bin/sh\\n" "$HOME"\n'
            ),
            "sudo": '#!/bin/sh\nprintf "unexpected sudo call\\n" > "$SUDO_LOG"\nexit 1\n',
        }
        for name, contents in stubs.items():
            path = fake_bin / name
            path.write_text(contents)
            path.chmod(0o755)
        self.env = {
            **os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "USER": "installer-test", "SUDO_USER": "installer-test", "HOME": str(root),
            "SUDO_LOG": str(self.sudo_log),
        }

    def tearDown(self):
        self.assertFalse(self.sudo_log.exists(), "Installer tests must not invoke sudo")

    def test_help_is_safe_without_an_install_user(self):
        for script in ("install-picochess.sh", "install-engines.sh"):
            with self.subTest(script=script):
                result = subprocess.run(
                    ["sh", str(REPO_ROOT / script), "--help"],
                    env={**self.env, "USER": "root", "SUDO_USER": "root"},
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
                    env=self.env,
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(expected, result.stdout.splitlines()[-1])
                self.assertEqual("lite" in args, "deprecated" in result.stderr)

    def test_main_installer_only_replaces_existing_engines_for_large(self):
        source = (REPO_ROOT / "install-picochess.sh").read_text()
        parser = source.split("set_ini_setting()", 1)[0]
        engine_step = source.split("# install engines as install user if needed\n", 1)[1]
        engine_step = engine_step.split("# Remove empty gamesdb placeholder", 1)[0]
        cases = [
            (True, [], []),
            (True, ["pico"], []),
            (True, ["small"], []),
            (True, ["pico", "small"], []),
            (True, ["large"], ["backup", "install large"]),
            (True, ["lite"], ["backup", "install large"]),
            (True, ["large", "noengines"], []),
            (False, [], ["install small"]),
            (False, ["pico"], ["install small"]),
            (False, ["small"], ["install small"]),
            (False, ["large"], ["install large"]),
            (False, ["small", "noengines"], []),
        ]
        for arch in ("aarch64", "x86_64"):
            for existing, args, expected in cases:
                with self.subTest(arch=arch, existing=existing, args=args), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    fake_bin = root / "bin"
                    fake_bin.mkdir()
                    calls = root / "calls"
                    for relative, text in {
                        "bin/uname": 'printf "%s\\n" "$TEST_ARCH"\n',
                        "bin/sudo": '[ "$1" = -u ] || exit 99\nshift 2\n'
                                    '[ "$PWD" = "$TEST_REPO_DIR" ] || exit 99\n'
                                    'case "$1" in\n'
                                    './install-engines.sh) printf "install %s\\n" "$2" >> "$CALL_LOG" ;;\n'
                                    './move-engines-to-backup.sh) printf "backup\\n" >> "$CALL_LOG" ;;\n'
                                    '*) exit 99 ;; esac\n',
                        "install-engines.sh": 'printf "install %s\\n" "$1" >> "$CALL_LOG"\n',
                        "move-engines-to-backup.sh": 'printf "backup\\n" >> "$CALL_LOG"\n',
                    }.items():
                        path = root / relative
                        path.write_text("#!/bin/sh\n" + text)
                        path.chmod(0o755)
                    sentinel = root / "engines" / arch / "my-engine"
                    weights = root / "engines/lc0_weights/my-network"
                    if existing:
                        for path in (sentinel, weights):
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_bytes(b"existing resource")
                    result = subprocess.run(
                        ["sh", "-c", parser + '\nREPO_DIR="$TEST_REPO_DIR"\n' + engine_step,
                         "installer-test", *args],
                        cwd=root, env={**self.env, "PATH": f"{fake_bin}:{self.env['PATH']}",
                                       "TEST_REPO_DIR": str(root), "TEST_ARCH": arch, "CALL_LOG": str(calls)},
                        capture_output=True, text=True, check=False,
                    )
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(expected, calls.read_text().splitlines() if calls.exists() else [])
                    if existing and not expected:
                        self.assertEqual(b"existing resource", sentinel.read_bytes())
                        self.assertEqual(b"existing resource", weights.read_bytes())

    def install_engines(self, arch, variant, *, existing_weights=False):
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
            if existing_weights:
                weights = root / "engines/lc0_weights"
                weights.mkdir(parents=True)
                (weights / "custom.pb.gz").write_bytes(b"user network")
            log = root / "downloads"
            result = subprocess.run(
                ["sh", str(REPO_ROOT / "install-engines.sh"), variant],
                env={
                    **self.env, "PATH": f"{fake_bin}:{self.env['PATH']}",
                    "REPO_DIR": str(root), "HOME": str(root),
                    "TEST_ARCH": arch, "DOWNLOAD_LOG": str(log),
                },
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            if existing_weights:
                self.assertEqual(b"user network", (weights / "custom.pb.gz").read_bytes())
                self.assertFalse((weights / "tinygyal-8.pb.gz").exists())
            return log.read_text().splitlines(), result

    def test_large_and_legacy_alias_select_identical_bundles_on_both_architectures(self):
        for arch in ("aarch64", "x86_64"):
            with self.subTest(arch=arch):
                large, result = self.install_engines(arch, "large")
                legacy, alias_result = self.install_engines(arch, "lite")
                self.assertEqual(large, legacy)
                self.assertEqual(7, len(large))
                for component in ("large.tar.gz", "mame", "rodent3", "rodent4", "pgn_audio"):
                    self.assertTrue(any(component in url for url in large), component)
                for url in large[:4]:
                    self.assertIn("/v4.4.0/", url)
                    self.assertIn("large.tar.gz", url)
                    self.assertNotIn("lite", url)
                self.assertIn(
                    "https://github.com/JohanSjoblom/picochess/releases/download/v4.4.0/lc0_weights.tar.gz",
                    large,
                )
                self.assertIn("variant: large", result.stdout)
                self.assertNotIn("deprecated", result.stderr)
                self.assertIn('use "large" instead', alias_result.stderr)

    def test_small_excludes_large_addons_on_both_architectures(self):
        for arch in ("aarch64", "x86_64"):
            with self.subTest(arch=arch):
                urls, _ = self.install_engines(arch, "small")
                self.assertEqual(3, len(urls))
                self.assertIn("small.tar.gz", urls[0])
                self.assertIn(
                    "https://github.com/JohanSjoblom/picochess/releases/download/v4.4.0/lc0_weights.tar.gz",
                    urls,
                )
                self.assertTrue(any("script_engines" in url for url in urls))

    def test_engine_installer_requires_a_valid_package(self):
        for args in ([], ["medium"], ["invalid"]):
            with self.subTest(args=args):
                result = subprocess.run(
                    ["sh", str(REPO_ROOT / "install-engines.sh"), *args],
                    env=self.env,
                    capture_output=True, text=True, check=False,
                )
                self.assertNotEqual(0, result.returncode)
                self.assertIn("small|large", result.stdout)

    def test_existing_weights_folder_is_reused_without_checking_individual_networks(self):
        for arch in ("aarch64", "x86_64"):
            for variant in ("small", "large"):
                with self.subTest(arch=arch, variant=variant):
                    urls, _ = self.install_engines(arch, variant, existing_weights=True)
                    self.assertFalse(any("lc0_weights" in url for url in urls))
