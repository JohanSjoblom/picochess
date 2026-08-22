import ast
import unittest
from pathlib import Path

from dgt.translate import DgtTranslate


class TestItalianTutorMoveTranslation(unittest.TestCase):
    def setUp(self):
        self.translate = DgtTranslate("none", 0, "it", "version")

    def test_tutor_move_piece_notation(self):
        expected_moves = {
            "Ke2": "Re2",
            "Kxe2": "Rxe2",
            "Re2": "Te2",
            "Be2": "Ae2",
        }

        for message_type in ("BEST", "HINT", "THREAT"):
            for english_move, italian_move in expected_moves.items():
                with self.subTest(message_type=message_type, move=english_move):
                    text = self.translate.text("C10_picotutor_msg", message_type + english_move)
                    self.assertIn(italian_move, text.web_text)
                    self.assertNotIn(english_move, text.web_text)


class TestDisplayTextLengths(unittest.TestCase):
    LIMITS = {
        "small_text": 6,
        "medium_text": 8,
        "large_text": 11,
        "web_text": 38,
    }

    def assert_text_fits(self, text):
        for field, limit in self.LIMITS.items():
            value = getattr(text, field)
            self.assertLessEqual(len(value), limit, f"{field}: {value!r}")

    def test_fixed_translation_literals_fit_their_displays(self):
        source_path = Path(__file__).parents[1] / "dgt" / "translate.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))

        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "DISPLAY_TEXT"
            ):
                continue
            for keyword in node.keywords:
                if keyword.arg not in self.LIMITS or not isinstance(keyword.value, ast.Constant):
                    continue
                if not isinstance(keyword.value.value, str):
                    continue
                with self.subTest(line=keyword.value.lineno, field=keyword.arg, text=keyword.value.value):
                    self.assertLessEqual(len(keyword.value.value), self.LIMITS[keyword.arg])

    def test_generated_text_is_bounded_for_every_language(self):
        cases = (
            ("N00_default", "x" * 100),
            ("C10_position_fail", "clear e4"),
            ("C10_position_fail", "put Qe4"),
            ("B00_level", "A very long engine level name"),
            ("B00_retrospeed", "1000%"),
            ("B00_tc_node", "500"),
            ("B00_updt_version", "v123.456"),
            ("B00_bat_percent", "100%"),
        )

        for language in ("en", "de", "nl", "fr", "es", "it"):
            translate = DgtTranslate("none", 0, language, "v123.456")
            translate.set_last_updated_info("upd: 999d ago and more")
            translate.set_git_info("git: a very long branch status")
            language_cases = cases + (
                ("B10_picochess", ""),
                ("B10_pico_updated_status", ""),
                ("B10_pico_git_status", ""),
            )
            for code, message in language_cases:
                with self.subTest(language=language, code=code, message=message):
                    self.assert_text_fits(translate.text(code, message))

    def test_web_text_allows_38_characters(self):
        text = DgtTranslate("none", 0, "en", "0.9m").text("N00_default", "x" * 100)
        self.assertEqual(38, len(text.web_text))

    def test_position_wait_text_is_not_reboot_specific(self):
        text = DgtTranslate("none", 0, "en", "0.9m").text("Y15_positionwait")

        self.assertEqual("Please wait", text.web_text)
        self.assertNotIn("reboot", text.web_text.lower())

    def test_retro_speed_keeps_the_selected_value(self):
        for language in ("en", "it"):
            text = DgtTranslate("none", 0, language, "0.9m").text("B00_retrospeed", "1000%")
            self.assertTrue(text.medium_text.endswith("1000%"))
            self.assertTrue(text.small_text.endswith("1000%"))


if __name__ == "__main__":
    unittest.main()
