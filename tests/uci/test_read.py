import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from uci.read import read_engine_ini


ENGINE_SECTION = """\
[{section}]
name = {name}
small = small
medium = medium
large = large
elo = 1500
"""


class TestReadEngineIniManufacturer(unittest.TestCase):
    def _read(self, filename, content):
        with tempfile.TemporaryDirectory() as engine_path:
            with open(os.path.join(engine_path, filename), "w", encoding="utf-8") as ini_file:
                ini_file.write(content)
            return read_engine_ini(engine_path=engine_path, filename=filename)

    def test_strict_manufacturer_applies_until_next_directive(self):
        engines = self._read(
            "retro.ini",
            "; Manufacturer: Mephisto\n"
            + ENGINE_SECTION.format(section="mame/one", name="One")
            + ENGINE_SECTION.format(section="mame/two", name="Two")
            + "; Manufacturer: Novag\n"
            + ENGINE_SECTION.format(section="mame/three", name="Three"),
        )
        self.assertEqual(["Mephisto", "Mephisto", "Novag"], [engine["manufacturer"] for engine in engines])

    def test_ordinary_and_malformed_comments_are_ignored(self):
        engines = self._read(
            "retro.ini",
            "; Manufacturer: Mephisto\n"
            + ENGINE_SECTION.format(section="mame/one", name="One")
            + "; ordinary comment\n;Manufacturer: Novag\n; manufacturer: Novag\n; Manufacturer:   \n"
            + ENGINE_SECTION.format(section="mame/two", name="Two"),
        )
        self.assertEqual(["Mephisto", "Mephisto"], [engine["manufacturer"] for engine in engines])

    def test_ungrouped_entries_have_empty_manufacturer(self):
        engines = self._read(
            "retro.ini",
            ENGINE_SECTION.format(section="mame/one", name="One")
            + "; Manufacturer: Novag\n"
            + ENGINE_SECTION.format(section="mame/two", name="Two"),
        )
        self.assertEqual(["", "Novag"], [engine["manufacturer"] for engine in engines])

    def test_manufacturer_directive_applies_to_every_engine_ini(self):
        engines = self._read(
            "engines.ini",
            "; Manufacturer: Mephisto\n" + ENGINE_SECTION.format(section="one", name="One"),
        )
        self.assertEqual("Mephisto", engines[0]["manufacturer"])

    def test_future_engine_ini_without_directives_keeps_empty_metadata(self):
        engines = self._read(
            "community.ini",
            ENGINE_SECTION.format(section="one", name="One"),
        )
        self.assertEqual("", engines[0]["manufacturer"])

    @patch("builtins.open", side_effect=PermissionError("catalog is not readable"))
    def test_unreadable_engine_ini_keeps_previous_empty_catalog_fallback(self, _open):
        self.assertEqual([], read_engine_ini(engine_path="/engines", filename="retro.ini"))

    def test_default_catalog_uses_mapped_local_engine_directory(self):
        with tempfile.TemporaryDirectory() as engine_path:
            with open(os.path.join(engine_path, "engines.ini"), "w", encoding="utf-8") as ini_file:
                ini_file.write(ENGINE_SECTION.format(section="stockfish", name="Stockfish"))
            with patch("uci.read.local_engine_directory", return_value=Path(engine_path)):
                engines = read_engine_ini(filename="engines.ini")

        self.assertEqual("Stockfish", engines[0]["name"])
        self.assertEqual("stockfish", engines[0]["profile_id"])
        self.assertEqual(os.path.join(engine_path, "stockfish"), engines[0]["file"])
        self.assertEqual(os.path.join(engine_path, "stockfish.uci"), engines[0]["uci_file"])

    def test_profile_can_share_binary_and_use_its_own_uci_file(self):
        content = ENGINE_SECTION.format(section="fairy-atomic", name="Atomic") + (
            "file = fairy\nuci = fairy-atomic.uci\n"
        )
        with tempfile.TemporaryDirectory() as engine_path:
            Path(engine_path, "variants.ini").write_text(content, encoding="utf-8")
            Path(engine_path, "fairy-atomic.uci").write_text(
                "[Atomic@1500]\nVariant = atomic\nUCI_Variant = atomic\n",
                encoding="utf-8",
            )

            engines = read_engine_ini(engine_path=engine_path, filename="variants.ini")

        self.assertEqual("fairy-atomic", engines[0]["profile_id"])
        self.assertEqual(os.path.join(engine_path, "fairy"), engines[0]["file"])
        self.assertEqual(os.path.join(engine_path, "fairy-atomic.uci"), engines[0]["uci_file"])
        self.assertEqual("atomic", engines[0]["level_dict"]["Atomic@1500"]["Variant"])

    def test_profile_id_preserves_catalog_slashes(self):
        engines = self._read(
            "special.ini",
            ENGINE_SECTION.format(section="script/turing", name="Turing"),
        )

        self.assertEqual("script/turing", engines[0]["profile_id"])

    def test_managed_fairy_profiles_cover_five_variants_and_full_strength_range(self):
        profile_path = Path(__file__).parents[2] / "engine-packages" / "fairy14"

        engines = read_engine_ini(engine_path=str(profile_path), filename="variants.ini")

        self.assertEqual(
            ["3check", "kingofthehill", "atomic", "racingkings", "antichess"],
            [engine["variant"] for engine in engines],
        )
        self.assertEqual(5, len({engine["profile_id"] for engine in engines}))
        for engine in engines:
            levels = list(engine["level_dict"].values())
            self.assertEqual(10, len(levels))
            self.assertEqual(
                [1000, 1250, 1500, 1750, 2000, 2250, 2500, 2750, 2850, 3000],
                [int(level["UCI_Elo"]) for level in levels],
            )
            self.assertTrue(all(level["UCI_LimitStrength"] == "true" for level in levels))
