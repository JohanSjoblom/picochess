import unittest

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


if __name__ == "__main__":
    unittest.main()
