import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from configobj import ConfigObj

from configuration import Configuration
from uci.engine_provider import EngineProvider


class TestEngineFavoritesConfiguration(unittest.TestCase):
    def _parse_ini(self, value: str):
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "picochess.ini"
            config_file.write_text(f"engine-favorites = {value}\n", encoding="utf-8")
            with patch.object(sys, "argv", ["picochess"]):
                args = Configuration(default_config_files=[str(config_file)])._args
        return EngineProvider.parse_starred_ids(args.engine_favorites)

    def test_one_favorite_is_parsed_from_real_ini_file(self):
        self.assertEqual(["b-texel"], self._parse_ini('["b-texel"]'))

    def test_multiple_favorites_and_slash_are_parsed_from_real_ini_file(self):
        self.assertEqual(
            ["b-texel", "script/turing"],
            self._parse_ini('["b-texel","script/turing"]'),
        )

    def test_empty_favorites_are_parsed_from_real_ini_file(self):
        self.assertEqual([], self._parse_ini("[]"))

    def test_configobj_persistence_round_trip_uses_the_same_parse_path(self):
        expected = ["b-texel", "script/turing", "engine name with spaces"]
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "picochess.ini"
            config = ConfigObj(str(config_file), default_encoding="utf8")
            config["engine-favorites"] = '["b-texel","script/turing","engine name with spaces"]'
            config.write()
            with patch.object(sys, "argv", ["picochess"]):
                args = Configuration(default_config_files=[str(config_file)])._args

        self.assertEqual(expected, EngineProvider.parse_starred_ids(args.engine_favorites))


if __name__ == "__main__":
    unittest.main()
