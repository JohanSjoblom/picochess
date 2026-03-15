import unittest
from unittest.mock import patch

from utilities import _choose_wayland_backend, get_engine_mame_par, get_window_command


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

    @patch("utilities._choose_wayland_backend", return_value="ydotool")
    @patch("utilities.is_wayland_session", return_value=True)
    def test_get_window_command_wayland_ydotool(self, _, __):
        self.assertEqual(
            "ydotool key 56:1 15:1 15:0 56:0",
            get_window_command("switch_window"),
        )

    @patch("utilities._choose_wayland_backend", return_value="ydotool")
    @patch("utilities.is_wayland_session", return_value=True)
    @patch.dict("utilities.os.environ", {"YDOTOOL_SOCKET": "/home/pi/.ydotool_socket"}, clear=False)
    def test_get_window_command_wayland_ydotool_with_socket(self, _, __):
        self.assertEqual(
            "YDOTOOL_SOCKET=/home/pi/.ydotool_socket ydotool key 56:1 15:1 15:0 56:0",
            get_window_command("switch_window"),
        )

    @patch("utilities._choose_wayland_backend", return_value=None)
    @patch("utilities.is_wayland_session", return_value=True)
    def test_get_window_command_wayland_no_backend(self, _, __):
        self.assertIsNone(get_window_command("switch_window"))

    @patch("utilities.shutil.which", return_value="/usr/bin/swaymsg")
    @patch.dict("utilities.os.environ", {"PICOCHESS_WAYLAND_WINDOW_BACKEND": "swaymsg"}, clear=False)
    def test_choose_wayland_backend_override_sway(self, _):
        self.assertEqual("swaymsg", _choose_wayland_backend())

    @patch("utilities.shutil.which", return_value=None)
    @patch.dict("utilities.os.environ", {"PICOCHESS_WAYLAND_WINDOW_BACKEND": "ydotool"}, clear=False)
    def test_choose_wayland_backend_override_missing_tool(self, _):
        self.assertIsNone(_choose_wayland_backend())


if __name__ == "__main__":
    unittest.main()
