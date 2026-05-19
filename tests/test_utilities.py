import unittest
from unittest.mock import patch

from utilities import get_engine_mame_par, get_window_command


class TestUtilities(unittest.TestCase):

    def test_engine_mame_par(self):
        self.assertEqual("-speed 1.0 -sound none", get_engine_mame_par(1.0))
        self.assertEqual("-speed 2.01", get_engine_mame_par(2.01, True))
        self.assertEqual("-nothrottle -sound none", get_engine_mame_par(0.009))
        self.assertEqual("-nothrottle", get_engine_mame_par(0.009, True))

    @patch("utilities.is_wayland_session", return_value=False)
    def test_get_window_command_x11(self, _):
        self.assertEqual(
            "xdotool keydown alt key Tab; sleep 0.2; xdotool keyup alt",
            get_window_command("switch_window"),
        )

    @patch("utilities.is_wayland_session", return_value=True)
    def test_get_window_command_wayland_no_backend(self, _):
        self.assertIsNone(get_window_command("switch_window"))


if __name__ == "__main__":
    unittest.main()
