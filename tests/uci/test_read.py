import os
import tempfile
import unittest

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

    def test_ungrouped_retro_entries_have_empty_manufacturer(self):
        engines = self._read(
            "retro.ini",
            ENGINE_SECTION.format(section="mame/one", name="One")
            + "; Manufacturer: Novag\n"
            + ENGINE_SECTION.format(section="mame/two", name="Two"),
        )
        self.assertEqual(["", "Novag"], [engine["manufacturer"] for engine in engines])

    def test_manufacturer_directive_is_ignored_outside_retro_ini(self):
        engines = self._read(
            "engines.ini",
            "; Manufacturer: Mephisto\n" + ENGINE_SECTION.format(section="one", name="One"),
        )
        self.assertNotIn("manufacturer", engines[0])
