import sys
import unittest
from unittest.mock import patch

from configuration import Configuration


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
        self.assertEqual('["script/turing","fairy-atomic"]', args.engine_favorites)
        self.assertFalse(args.engine_fav_prompt)


if __name__ == "__main__":
    unittest.main()
