import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class TestInstallEngineCatalogs(unittest.TestCase):
    script = Path(__file__).parents[1] / "install-engine-catalogs.sh"
    profile_source = Path(__file__).parents[1] / "engine-packages" / "fairy14"
    nnue_names_source = Path(__file__).parents[1] / "engine-packages" / "nnue" / "engine-names.txt"
    nnue_builder = Path(__file__).parents[1] / "build-nnue-catalog.py"

    def _run(self, root: Path):
        environment = dict(os.environ)
        environment.update(
            {
                "REPO_DIR": str(root),
                "ENGINES_DIR": str(root / "engines"),
                "PROFILE_SOURCE": str(self.profile_source),
                "NNUE_NAMES_SOURCE": str(self.nnue_names_source),
                "NNUE_BUILDER": str(self.nnue_builder),
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
            (target / "engines.ini").write_text(
                "[NNUE/StockfishNN]\n"
                "name = StockfishNN 19\nweb = Stockfish NNUE 19\n"
                "small = SF19\nmedium = Stockf19\nlarge = Stockfish19\nelo = 3600\n"
                "\n[NNUE/ArasanNN]\n"
                "name = ArasanNN v26.0\nsmall = Arasan\nmedium = ArasanNN\nlarge = Arasan NN\nelo = 3500\n"
                "\n[classic]\n"
                "name = Classic Engine\nsmall = Classic\nmedium = Classic\nlarge = Classic\nelo = 2000\n",
                encoding="utf-8",
            )
            (target / "NNUE").mkdir()
            (target / "NNUE" / "StockfishNN").write_bytes(b"binary")
            (target / "NNUE" / "ArasanNN").write_bytes(b"binary")

            self._run(root)

            self.assertEqual("[script/turing]\n", (target / "special.ini").read_text(encoding="utf-8"))
            self.assertFalse((target / "variants.ini").exists())
            nnue = (target / "nnue.ini").read_text(encoding="utf-8")
            self.assertIn("[NNUE/StockfishNN]", nnue)
            self.assertIn("[NNUE/ArasanNN]", nnue)
            self.assertNotIn("[classic]", nnue)

            # A catalog created by this installer is managed metadata and may
            # be regenerated on upgrade to add newly classified profiles.
            (target / "engines.ini").write_text(
                (target / "engines.ini").read_text(encoding="utf-8")
                + "\n[NNUE/BlackDiamondNN]\n"
                "name = Black Diamond NNUE v13.1b\n"
                "small = BDiamond\nmedium = BlackDia\nlarge = BlackDiamond\nelo = 3500\n",
                encoding="utf-8",
            )
            (target / "NNUE" / "BlackDiamondNN").write_bytes(b"binary")
            self._run(root)
            self.assertIn(
                "[NNUE/BlackDiamondNN]",
                (target / "nnue.ini").read_text(encoding="utf-8"),
            )

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
            (target / "engines.ini").write_text("[engine]\n", encoding="utf-8")
            (target / "nnue.ini").write_text("custom nnue", encoding="utf-8")

            self._run(root)

            self.assertEqual("custom special", (target / "special.ini").read_text(encoding="utf-8"))
            self.assertEqual("custom variants", (target / "variants.ini").read_text(encoding="utf-8"))
            self.assertEqual("custom atomic", (target / "fairy-atomic.uci").read_text(encoding="utf-8"))
            self.assertEqual("custom nnue", (target / "nnue.ini").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
