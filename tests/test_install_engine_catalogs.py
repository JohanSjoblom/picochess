import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class TestInstallEngineCatalogs(unittest.TestCase):
    script = Path(__file__).parents[1] / "install-engine-catalogs.sh"
    profile_source = Path(__file__).parents[1] / "engine-packages" / "fairy14"

    def _run(self, root: Path):
        environment = dict(os.environ)
        environment.update(
            {
                "REPO_DIR": str(root),
                "ENGINES_DIR": str(root / "engines"),
                "PROFILE_SOURCE": str(self.profile_source),
            }
        )
        return subprocess.run(
            ["sh", str(self.script), "aarch64"],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_small_or_lite_install_adds_metadata_only_after_binary_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "engines" / "aarch64"
            target.mkdir(parents=True)
            (target / "favorites.ini").write_text("[script/turing]\n", encoding="utf-8")

            self._run(root)

            self.assertEqual("[script/turing]\n", (target / "special.ini").read_text(encoding="utf-8"))
            self.assertFalse((target / "variants.ini").exists())

            (target / "fairy").write_bytes(b"binary")
            self._run(root)

            for filename in (
                "variants.ini",
                "fairy-3check.uci",
                "fairy-koth.uci",
                "fairy-atomic.uci",
                "fairy-racingkings.uci",
                "fairy-antichess.uci",
            ):
                self.assertEqual(
                    (self.profile_source / filename).read_bytes(),
                    (target / filename).read_bytes(),
                )

    def test_existing_catalogs_and_sidecars_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "engines" / "aarch64"
            target.mkdir(parents=True)
            (target / "fairy").write_bytes(b"binary")
            (target / "favorites.ini").write_text("legacy", encoding="utf-8")
            (target / "special.ini").write_text("custom special", encoding="utf-8")
            (target / "variants.ini").write_text("custom variants", encoding="utf-8")
            (target / "fairy-atomic.uci").write_text("custom atomic", encoding="utf-8")

            self._run(root)

            self.assertEqual("custom special", (target / "special.ini").read_text(encoding="utf-8"))
            self.assertEqual("custom variants", (target / "variants.ini").read_text(encoding="utf-8"))
            self.assertEqual("custom atomic", (target / "fairy-atomic.uci").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
