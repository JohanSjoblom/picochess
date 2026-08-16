import unittest

from web.menu_translate import (
    ENGLISH,
    SUPPORTED_LANGUAGES,
    TRANSLATIONS,
    get_menu_catalog,
    get_menu_source_map,
    get_menu_text,
    validate_catalogs,
)


class TestWebMenuTranslate(unittest.TestCase):
    def test_every_non_english_language_has_every_key(self):
        reference_keys = set(ENGLISH)
        for language in SUPPORTED_LANGUAGES:
            if language == "en":
                continue
            with self.subTest(language=language):
                self.assertEqual(reference_keys, set(TRANSLATIONS[language]))

    def test_catalogs_have_matching_placeholders(self):
        self.assertEqual([], validate_catalogs())

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(ENGLISH, get_menu_catalog("unknown"))

    def test_named_placeholders_are_formatted(self):
        self.assertEqual("Zurück zu Analyse", get_menu_text("de", "mode.return_to", mode="Analyse"))
        self.assertEqual("Slot 3", get_menu_text("it", "game.slot", slot=3))

    def test_browser_labels_are_not_truncated(self):
        self.assertEqual("Zwei Spieler online", get_menu_text("de", "mode.remote"))

    def test_source_map_supports_legacy_english_fallback_strings(self):
        source_map = get_menu_source_map("es")
        self.assertEqual("Jugar", source_map["Play"])
        self.assertEqual("Motor", source_map["Engine"])


if __name__ == "__main__":
    unittest.main()
