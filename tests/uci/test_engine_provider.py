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

    def test_single_manufacturer_does_not_add_redundant_menu_level(self):
        engines = [
            {"name": "King of the Hill", "manufacturer": "Fairy-Stockfish"},
            {"name": "Antichess", "manufacturer": "Fairy-Stockfish"},
        ]

        self.assertEqual(1, len(EngineProvider.get_engine_groups(engines)))
        self.assertEqual([], EngineProvider.get_engine_menu_groups(engines))

    def test_multiple_manufacturers_keep_menu_level(self):
        engines = [
            {"name": "One", "manufacturer": "Maker One"},
            {"name": "Two", "manufacturer": "Maker Two"},
        ]

        self.assertEqual(2, len(EngineProvider.get_engine_menu_groups(engines)))

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
        self.original_nnue = EngineProvider.nnue_engines
        self.original_retro = EngineProvider.retro_engines
        self.original_special = EngineProvider.special_engines
        self.original_variants = EngineProvider.variant_engines
        self.original_hidden = EngineProvider.hidden_profiles
        self.original_unavailable = EngineProvider.unavailable_profiles
        self.original_installed = EngineProvider.installed_engines
        self.original_visible = EngineProvider.visible_profiles
        self.original_all = EngineProvider.all_profiles
        self.original_profiles_by_id = EngineProvider.profiles_by_id
        self.original_favorite_ids = EngineProvider.favorite_profile_ids
        self.original_favorite_profiles = EngineProvider.favorite_profiles
        self.original_sort = EngineProvider.engine_menu_sort

    def tearDown(self):
        EngineProvider.modern_engines = self.original_modern
        EngineProvider.nnue_engines = self.original_nnue
        EngineProvider.retro_engines = self.original_retro
        EngineProvider.special_engines = self.original_special
        EngineProvider.variant_engines = self.original_variants
        EngineProvider.hidden_profiles = self.original_hidden
        EngineProvider.unavailable_profiles = self.original_unavailable
        EngineProvider.installed_engines = self.original_installed
        EngineProvider.visible_profiles = self.original_visible
        EngineProvider.all_profiles = self.original_all
        EngineProvider.profiles_by_id = self.original_profiles_by_id
        EngineProvider.favorite_profile_ids = self.original_favorite_ids
        EngineProvider.favorite_profiles = self.original_favorite_profiles
        EngineProvider.engine_menu_sort = self.original_sort

    def test_nnue_catalog_reclassifies_profiles_out_of_modern(self):
        stockfish_modern = {"profile_id": "a-stockf", "name": "Stockfish 19"}
        classic = {"profile_id": "classic", "name": "Classic"}
        stockfish_nnue = {"profile_id": "a-stockf", "name": "Stockfish 19"}
        EngineProvider.modern_engines = [stockfish_modern, classic]
        EngineProvider.nnue_engines = [stockfish_nnue]

        EngineProvider._apply_nnue_catalog_override()

        self.assertEqual([classic], EngineProvider.modern_engines)
        self.assertEqual([stockfish_nnue], EngineProvider.nnue_engines)

    def test_single_cli_json_argument_is_parsed_as_favorite_list(self):
        self.assertEqual(
            ["script/turing", "fairy-atomic"],
            EngineProvider.parse_favorite_ids(['["script/turing","fairy-atomic"]']),
        )

    @patch("uci.engine_provider.Path.is_file", return_value=True)
    @patch("uci.engine_provider.read_engine_ini")
    def test_special_ini_is_preferred(self, read_ini, _is_file):
        modern = [{"file": "modern"}]
        retro = [{"file": "retro"}]
        special = [{"file": "special"}]
        read_ini.side_effect = [modern, retro, special, [], []]

        EngineProvider.init()

        self.assertEqual(
            [call(filename="engines.ini"), call(filename="retro.ini"), call(filename="special.ini")],
            read_ini.call_args_list[:3],
        )
        self.assertEqual(special, EngineProvider.special_engines)
        self.assertEqual(modern + retro + special, EngineProvider.installed_engines)

    @patch("uci.engine_provider.Path.is_file", return_value=False)
    @patch("uci.engine_provider.read_engine_ini")
    def test_legacy_favorites_ini_is_special_fallback(self, read_ini, _is_file):
        modern = [{"file": "modern"}]
        retro = [{"file": "retro"}]
        legacy_special = [{"file": "script/turing"}]
        read_ini.side_effect = [modern, retro, legacy_special, [], []]

        with self.assertLogs("uci.engine_provider", level="WARNING") as logs:
            EngineProvider.init()

        self.assertEqual(call(filename="favorites.ini"), read_ini.call_args_list[2])
        self.assertEqual(legacy_special, EngineProvider.special_engines)
        self.assertIn("favorites.ini is deprecated", logs.output[0])

    @patch("uci.engine_provider.Path.is_file", return_value=True)
    @patch("uci.engine_provider.read_engine_ini")
    def test_empty_special_ini_does_not_read_legacy_file(self, read_ini, _is_file):
        modern = [{"file": "modern"}]
        retro = [{"file": "retro"}]
        read_ini.side_effect = [modern, retro, [], [], []]

        EngineProvider.init()

        self.assertEqual(call(filename="special.ini"), read_ini.call_args_list[2])
        self.assertNotIn(call(filename="favorites.ini"), read_ini.call_args_list)
        self.assertEqual([], EngineProvider.special_engines)

    @patch("uci.engine_provider.Path.is_file", return_value=True)
    @patch("uci.engine_provider.read_engine_ini", side_effect=[[], [], [], [], []])
    def test_empty_catalogs_do_not_copy_modern_or_crash_resolution(self, _read_ini, _is_file):
        EngineProvider.init()

        self.assertEqual([], EngineProvider.modern_engines)
        self.assertEqual([], EngineProvider.nnue_engines)
        self.assertEqual([], EngineProvider.retro_engines)
        self.assertEqual([], EngineProvider.special_engines)
        self.assertEqual([], EngineProvider.variant_engines)
        self.assertEqual([], EngineProvider.installed_engines)
        self.assertIsNone(EngineProvider.resolve_engine("missing"))

    def test_profile_lookup_is_exact_and_preserves_slashes(self):
        turing = {"profile_id": "script/turing", "file": "/engines/script/turing"}
        EngineProvider.modern_engines = []
        EngineProvider.nnue_engines = []
        EngineProvider.retro_engines = []
        EngineProvider.special_engines = [turing]
        EngineProvider.variant_engines = []
        EngineProvider.hidden_profiles = []

        EngineProvider._rebuild_profile_index()

        self.assertIs(turing, EngineProvider.resolve_profile("script/turing"))
        self.assertIsNone(EngineProvider.resolve_profile("turing"))
        self.assertIsNone(EngineProvider.resolve_profile("script\\turing"))

    def test_duplicate_profile_id_warns_and_first_catalog_wins(self):
        modern = {"profile_id": "shared", "file": "/engines/modern"}
        special = {"profile_id": "shared", "file": "/engines/special"}
        EngineProvider.modern_engines = [modern]
        EngineProvider.nnue_engines = []
        EngineProvider.retro_engines = []
        EngineProvider.special_engines = [special]
        EngineProvider.variant_engines = []
        EngineProvider.hidden_profiles = []

        with self.assertLogs("uci.engine_provider", level="WARNING") as logs:
            EngineProvider._rebuild_profile_index()

        self.assertIs(modern, EngineProvider.resolve_profile("shared"))
        self.assertIn("duplicate engine profile id 'shared'", logs.output[0])

    @patch("uci.engine_provider.Path.is_file", return_value=True)
    @patch("uci.engine_provider.read_engine_ini")
    def test_variant_catalog_hides_but_keeps_legacy_fairy_resolvable(self, read_ini, _is_file):
        fairy = {"profile_id": "fairy", "file": "/engines/fairy"}
        atomic = {"profile_id": "fairy-atomic", "file": "/engines/fairy"}
        read_ini.side_effect = [[fairy], [], [], [], [atomic]]

        EngineProvider.init()

        self.assertNotIn(fairy, EngineProvider.installed_engines)
        self.assertNotIn(fairy, EngineProvider.visible_profiles)
        self.assertIs(fairy, EngineProvider.resolve_profile("fairy"))
        self.assertIs(atomic, EngineProvider.resolve_profile("fairy-atomic"))

    def test_favorites_are_ordered_profile_references(self):
        turing = {"profile_id": "script/turing", "file": "/engines/script/turing"}
        atomic = {"profile_id": "fairy-atomic", "file": "/engines/fairy"}
        EngineProvider.profiles_by_id = {"script/turing": turing, "fairy-atomic": atomic}
        EngineProvider.visible_profiles = [turing, atomic]

        loaded = EngineProvider.set_favorite_ids('["fairy-atomic","missing","script/turing"]')

        self.assertEqual(["fairy-atomic", "script/turing"], loaded)
        self.assertEqual([atomic, turing], EngineProvider.favorite_profiles)
        self.assertEqual('["fairy-atomic","script/turing"]', EngineProvider.serialized_favorite_ids())

        self.assertTrue(EngineProvider.set_favorite("fairy-atomic", False))
        self.assertTrue(EngineProvider.set_favorite("fairy-atomic", True))
        self.assertEqual(["script/turing", "fairy-atomic"], EngineProvider.favorite_profile_ids)

    def test_hidden_legacy_profile_cannot_be_favorited(self):
        legacy = {"profile_id": "fairy", "file": "/engines/fairy", "hidden": True}
        EngineProvider.profiles_by_id = {"fairy": legacy}
        EngineProvider.visible_profiles = []
        EngineProvider.favorite_profile_ids = []

        self.assertFalse(EngineProvider.set_favorite("fairy", True))
        self.assertFalse(EngineProvider.set_favorite("missing", True))
        self.assertEqual([], EngineProvider.favorite_profile_ids)

        self.assertEqual([], EngineProvider.set_favorite_ids('["fairy"]'))

    def test_legacy_fairy_level_migrates_to_shared_binary_profile(self):
        legacy = {"profile_id": "fairy", "file": "/engines/fairy"}
        atomic = {
            "profile_id": "fairy-atomic",
            "file": "/engines/fairy",
            "variant": "atomic",
        }
        EngineProvider.variant_engines = [atomic]

        self.assertIs(atomic, EngineProvider.migrate_legacy_fairy_profile(legacy, "Atomic@1500"))
        self.assertIs(legacy, EngineProvider.migrate_legacy_fairy_profile(legacy, "Unknown@1500"))

        antichess = {
            "profile_id": "fairy-antichess",
            "file": "/engines/fairy",
            "variant": "antichess",
        }
        EngineProvider.variant_engines.append(antichess)
        self.assertIs(antichess, EngineProvider.migrate_legacy_fairy_profile(legacy, "Anti@1500"))

    def test_level_names_sort_numeric_suffixes_numerically(self):
        profile = {"level_dict": {"Atomic@2000": {}, "Atomic@900": {}, "Atomic@1000": {}}}

        self.assertEqual(
            ["Atomic@900", "Atomic@1000", "Atomic@2000"],
            EngineProvider.level_names(profile),
        )

    def test_known_unavailable_favorite_can_be_removed_but_not_added(self):
        unavailable = {
            "profile_id": "fairy-atomic",
            "file": "/engines/fairy",
            "available": False,
        }
        EngineProvider.profiles_by_id = {"fairy-atomic": unavailable}
        EngineProvider.visible_profiles = []
        EngineProvider.favorite_profile_ids = ["fairy-atomic"]
        EngineProvider._refresh_favorite_profiles()

        self.assertTrue(EngineProvider.set_favorite("fairy-atomic", False))
        self.assertFalse(EngineProvider.set_favorite("fairy-atomic", True))


if __name__ == "__main__":
    unittest.main()
