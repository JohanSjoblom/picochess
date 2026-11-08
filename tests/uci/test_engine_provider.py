import unittest
from unittest.mock import call, patch

from uci.engine_provider import EngineProvider


class TestEngineProvider(unittest.TestCase):
    def setUp(self):
        self.original_installed_engines = EngineProvider.installed_engines
        self.original_retro_engines = EngineProvider.retro_engines
        self.original_engine_menu_sort = EngineProvider.engine_menu_sort
        EngineProvider.installed_engines = [
            {"file": "/opt/picochess/engines/test/first"},
            {"file": "/opt/picochess/engines/test/second"},
        ]

    def tearDown(self):
        EngineProvider.installed_engines = self.original_installed_engines
        EngineProvider.retro_engines = self.original_retro_engines
        EngineProvider.engine_menu_sort = self.original_engine_menu_sort

    def test_resolve_engine_matches_absolute_path(self):
        engine = EngineProvider.resolve_engine("/opt/picochess/engines/test/second")
        self.assertEqual("/opt/picochess/engines/test/second", engine["file"])

    def test_resolve_engine_matches_relative_path_suffix(self):
        engine = EngineProvider.resolve_engine("engines/test/second")
        self.assertEqual("/opt/picochess/engines/test/second", engine["file"])

    def test_resolve_engine_falls_back_to_first_installed_engine(self):
        engine = EngineProvider.resolve_engine("/opt/picochess/engines/test/missing")
        self.assertEqual("/opt/picochess/engines/test/first", engine["file"])

    def test_resolve_engine_uses_first_installed_engine_when_unset(self):
        engine = EngineProvider.resolve_engine(None)
        self.assertEqual("/opt/picochess/engines/test/first", engine["file"])

    def test_has_engine_matches_relative_path_suffix(self):
        self.assertTrue(EngineProvider.has_engine("engines/test/second"))

    def test_has_engine_is_false_for_missing_engine(self):
        self.assertFalse(EngineProvider.has_engine("/opt/picochess/engines/test/missing"))

    def test_fallback_prefers_previous_installed_engine(self):
        fallback = EngineProvider.resolve_fallback_engine(
            failed_file="/opt/picochess/engines/test/second",
            preferred_file="engines/test/first",
        )
        self.assertEqual("/opt/picochess/engines/test/first", fallback["file"])

    def test_fallback_chooses_another_installed_engine_when_preferred_failed(self):
        fallback = EngineProvider.resolve_fallback_engine(
            failed_file="engines/test/second",
            preferred_file="/opt/picochess/engines/test/second",
        )
        self.assertEqual("/opt/picochess/engines/test/first", fallback["file"])

    def test_fallback_returns_none_when_no_alternative_is_installed(self):
        EngineProvider.installed_engines = [{"file": "/opt/picochess/engines/test/second"}]
        fallback = EngineProvider.resolve_fallback_engine(
            failed_file="engines/test/second",
            preferred_file="engines/test/second",
        )
        self.assertIsNone(fallback)

    def test_retro_groups_are_absent_without_metadata(self):
        EngineProvider.retro_engines = [{"name": "One"}, {"name": "Two"}]
        self.assertEqual([], EngineProvider.get_retro_groups())

    def test_generic_groups_are_absent_without_metadata(self):
        engines = [{"name": "One", "manufacturer": ""}, {"name": "Two"}]
        self.assertEqual([], EngineProvider.get_engine_groups(engines))

    def test_generic_groups_collect_missing_metadata_under_other(self):
        engines = [
            {"name": "Zulu", "manufacturer": ""},
            {"name": "Beta", "manufacturer": "Maker"},
        ]
        EngineProvider.set_engine_menu_sort("manufacturer")
        self.assertEqual(
            [
                {"manufacturer": "Maker", "engine_indexes": [1]},
                {"manufacturer": "Other", "engine_indexes": [0]},
            ],
            EngineProvider.get_engine_groups(engines),
        )

    def test_flat_retro_engine_sort_preserves_original_indexes(self):
        EngineProvider.retro_engines = [{"name": "Zulu"}, {"name": "Alpha"}, {"name": "Beta"}]
        EngineProvider.set_engine_menu_sort("engine")
        self.assertEqual([1, 2, 0], EngineProvider.get_flat_retro_engine_indexes())

    def test_retro_groups_keep_original_indexes_in_file_order(self):
        EngineProvider.retro_engines = [
            {"name": "Zulu", "manufacturer": ""},
            {"name": "Beta", "manufacturer": "Novag"},
            {"name": "Alpha", "manufacturer": "Novag"},
            {"name": "Academy", "manufacturer": "Mephisto"},
        ]
        EngineProvider.set_engine_menu_sort("file")
        self.assertEqual(
            [
                {"manufacturer": "Other", "engine_indexes": [0]},
                {"manufacturer": "Novag", "engine_indexes": [1, 2]},
                {"manufacturer": "Mephisto", "engine_indexes": [3]},
            ],
            EngineProvider.get_retro_groups(),
        )

    def test_engine_sort_only_sorts_engines_within_file_order_groups(self):
        EngineProvider.retro_engines = [
            {"name": "Zulu", "manufacturer": "Novag"},
            {"name": "Beta", "manufacturer": "Mephisto"},
            {"name": "Alpha", "manufacturer": "Novag"},
        ]
        EngineProvider.set_engine_menu_sort("engine")
        self.assertEqual(
            [
                {"manufacturer": "Novag", "engine_indexes": [2, 0]},
                {"manufacturer": "Mephisto", "engine_indexes": [1]},
            ],
            EngineProvider.get_retro_groups(),
        )

    def test_manufacturer_sort_sorts_groups_and_engines_without_mutating_catalog(self):
        engines = [
            {"name": "Zulu", "manufacturer": "Novag"},
            {"name": "Beta", "manufacturer": "Mephisto"},
            {"name": "Alpha", "manufacturer": "Novag"},
        ]
        EngineProvider.retro_engines = engines
        EngineProvider.set_engine_menu_sort("manufacturer")
        self.assertEqual(
            [
                {"manufacturer": "Mephisto", "engine_indexes": [1]},
                {"manufacturer": "Novag", "engine_indexes": [2, 0]},
            ],
            EngineProvider.get_retro_groups(),
        )
        self.assertIs(engines, EngineProvider.retro_engines)
        self.assertEqual(["Zulu", "Beta", "Alpha"], [engine["name"] for engine in engines])


class TestEngineProviderCatalogNames(unittest.TestCase):
    def setUp(self):
        self.original_modern = EngineProvider.modern_engines
        self.original_retro = EngineProvider.retro_engines
        self.original_special = EngineProvider.special_engines
        self.original_installed = EngineProvider.installed_engines
        self.original_sort = EngineProvider.engine_menu_sort

    def tearDown(self):
        EngineProvider.modern_engines = self.original_modern
        EngineProvider.retro_engines = self.original_retro
        EngineProvider.special_engines = self.original_special
        EngineProvider.installed_engines = self.original_installed
        EngineProvider.engine_menu_sort = self.original_sort

    @patch("uci.engine_provider.Path.is_file", return_value=True)
    @patch("uci.engine_provider.read_engine_ini")
    def test_special_ini_is_preferred(self, read_ini, _is_file):
        modern = [{"file": "modern"}]
        retro = [{"file": "retro"}]
        special = [{"file": "special"}]
        read_ini.side_effect = [modern, retro, special]

        EngineProvider.init()

        self.assertEqual(
            [call(filename="engines.ini"), call(filename="retro.ini"), call(filename="special.ini")],
            read_ini.call_args_list,
        )
        self.assertIs(special, EngineProvider.special_engines)
        self.assertEqual(modern + retro + special, EngineProvider.installed_engines)

    @patch("uci.engine_provider.Path.is_file", return_value=False)
    @patch("uci.engine_provider.read_engine_ini")
    def test_legacy_favorites_ini_is_special_fallback(self, read_ini, _is_file):
        modern = [{"file": "modern"}]
        retro = [{"file": "retro"}]
        legacy_special = [{"file": "script/turing"}]
        read_ini.side_effect = [modern, retro, legacy_special]

        with self.assertLogs("uci.engine_provider", level="WARNING") as logs:
            EngineProvider.init()

        self.assertEqual(call(filename="favorites.ini"), read_ini.call_args_list[-1])
        self.assertIs(legacy_special, EngineProvider.special_engines)
        self.assertIn("favorites.ini is deprecated", logs.output[0])

    @patch("uci.engine_provider.Path.is_file", return_value=True)
    @patch("uci.engine_provider.read_engine_ini")
    def test_empty_special_ini_does_not_read_legacy_file(self, read_ini, _is_file):
        modern = [{"file": "modern"}]
        retro = [{"file": "retro"}]
        read_ini.side_effect = [modern, retro, []]

        EngineProvider.init()

        self.assertEqual(call(filename="special.ini"), read_ini.call_args_list[-1])
        self.assertNotIn(call(filename="favorites.ini"), read_ini.call_args_list)
        # The old empty-catalog fallback is intentionally preserved in this
        # behavior-neutral rename commit and removed by the catalog feature.
        self.assertIs(modern, EngineProvider.special_engines)


if __name__ == "__main__":
    unittest.main()
