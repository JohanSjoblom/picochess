import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from configobj import ConfigObj

from configuration import Configuration
from uci.engine_provider import EngineProvider


class TestEngineProfileConfiguration(unittest.TestCase):
    def test_favorite_json_and_clock_prompt_round_trip_as_strings_and_bool(self):
        with patch.object(
            sys,
            "argv",
            [
                "picochess",
                "--engine-profile",
                "script/turing",
                "--engine-favorites",
                '["script/turing","fairy-atomic"]',
                "--engine-fav-prompt",
                "false",
            ],
        ):
            args = Configuration()._args

        self.assertEqual("script/turing", args.engine_profile)
        self.assertEqual(
            ["script/turing", "fairy-atomic"],
            EngineProvider.parse_favorite_ids(args.engine_favorites),
        )
        self.assertFalse(args.engine_fav_prompt)

    def test_favorite_json_from_picochess_ini_is_accepted_as_a_list(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "picochess.ini"
            config_file.write_text('engine-favorites = ["b-texel"]\n', encoding="utf-8")
            with patch.object(sys, "argv", ["picochess"]):
                args = Configuration(default_config_files=[str(config_file)])._args

        self.assertEqual(["b-texel"], args.engine_favorites)
        self.assertEqual(["b-texel"], EngineProvider.parse_favorite_ids(args.engine_favorites))

    def test_empty_favorite_json_from_picochess_ini_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "picochess.ini"
            config_file.write_text("engine-favorites = []\n", encoding="utf-8")
            with patch.object(sys, "argv", ["picochess"]):
                args = Configuration(default_config_files=[str(config_file)])._args

        self.assertEqual([], args.engine_favorites)
        self.assertEqual([], EngineProvider.parse_favorite_ids(args.engine_favorites))

    def test_multiple_favorites_written_by_configobj_round_trip(self):
        expected = ["b-texel", "script/turing", "engine name with spaces"]
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "picochess.ini"
            config = ConfigObj(str(config_file), default_encoding="utf8")
            config["engine-favorites"] = '["b-texel","script/turing","engine name with spaces"]'
            config.write()
            with patch.object(sys, "argv", ["picochess"]):
                args = Configuration(default_config_files=[str(config_file)])._args

        self.assertEqual(expected, EngineProvider.parse_favorite_ids(args.engine_favorites))


if __name__ == "__main__":
    unittest.main()
