import unittest

from uci.engine_provider import EngineProvider


class TestEngineProvider(unittest.TestCase):
    def setUp(self):
        self.original_installed_engines = EngineProvider.installed_engines
        EngineProvider.installed_engines = [
            {"file": "/opt/picochess/engines/test/first"},
            {"file": "/opt/picochess/engines/test/second"},
        ]

    def tearDown(self):
        EngineProvider.installed_engines = self.original_installed_engines

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
