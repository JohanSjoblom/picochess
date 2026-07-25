import unittest

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

    def test_retro_groups_are_absent_without_metadata(self):
        EngineProvider.retro_engines = [{"name": "One"}, {"name": "Two"}]
        self.assertEqual([], EngineProvider.get_retro_groups())

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
