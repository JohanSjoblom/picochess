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


class TestEngineFavorites(unittest.TestCase):
    def setUp(self):
        self.original = {
            "modern": EngineProvider.modern_engines,
            "retro": EngineProvider.retro_engines,
            "special": EngineProvider.favorite_engines,
            "installed": EngineProvider.installed_engines,
            "profiles": EngineProvider.profiles_by_id,
            "ids": EngineProvider.starred_profile_ids,
            "starred": EngineProvider.starred_engines,
            "sort": EngineProvider.engine_menu_sort,
        }

    def tearDown(self):
        EngineProvider.modern_engines = self.original["modern"]
        EngineProvider.retro_engines = self.original["retro"]
        EngineProvider.favorite_engines = self.original["special"]
        EngineProvider.installed_engines = self.original["installed"]
        EngineProvider.profiles_by_id = self.original["profiles"]
        EngineProvider.starred_profile_ids = self.original["ids"]
        EngineProvider.starred_engines = self.original["starred"]
        EngineProvider.engine_menu_sort = self.original["sort"]

    @patch("uci.engine_provider.read_engine_ini")
    def test_existing_catalogs_and_empty_catalog_fallback_stay_unchanged(self, read_ini):
        modern = [{"profile_id": "modern", "file": "modern"}]
        read_ini.side_effect = [modern, [], []]

        EngineProvider.init(engine_favorites=[])

        self.assertEqual(
            [call(filename="engines.ini"), call(filename="retro.ini"), call(filename="favorites.ini")],
            read_ini.call_args_list,
        )
        self.assertIs(EngineProvider.retro_engines, modern)
        self.assertIs(EngineProvider.favorite_engines, modern)

    def test_duplicate_profile_id_uses_first_catalog_entry_once(self):
        modern = {"profile_id": "shared", "file": "/engines/modern"}
        special = {"profile_id": "shared", "file": "/engines/special"}
        EngineProvider.modern_engines = [modern]
        EngineProvider.retro_engines = []
        EngineProvider.favorite_engines = [special]

        EngineProvider._rebuild_profile_index()
        EngineProvider.set_starred_ids(["shared", "shared"])

        self.assertEqual(["shared"], EngineProvider.starred_profile_ids)
        self.assertEqual([modern], EngineProvider.starred_engines)

    def test_different_profile_ids_sharing_one_path_remain_distinct(self):
        first = {"profile_id": "first", "file": "/engines/shared"}
        second = {"profile_id": "second", "file": "/engines/shared"}
        EngineProvider.modern_engines = [first]
        EngineProvider.retro_engines = [second]
        EngineProvider.favorite_engines = []

        EngineProvider._rebuild_profile_index()
        EngineProvider.set_starred_ids(["second", "first"])

        self.assertEqual(["second", "first"], EngineProvider.starred_profile_ids)
        self.assertEqual([second, first], EngineProvider.starred_engines)

    def test_unknown_ids_are_ignored_and_last_favorite_can_be_removed(self):
        engine = {"profile_id": "script/turing", "file": "/engines/script/turing"}
        EngineProvider.modern_engines = [engine]
        EngineProvider.retro_engines = []
        EngineProvider.favorite_engines = []
        EngineProvider._rebuild_profile_index()

        EngineProvider.set_starred_ids(["missing", "script/turing"])
        self.assertEqual(["script/turing"], EngineProvider.starred_profile_ids)

        self.assertTrue(EngineProvider.set_starred("script/turing", False))
        self.assertEqual([], EngineProvider.starred_profile_ids)
        self.assertEqual([], EngineProvider.starred_engines)
