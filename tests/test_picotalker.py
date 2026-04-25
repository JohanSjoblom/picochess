#!/usr/bin/env python3

import subprocess
import unittest
from unittest.mock import Mock, patch

from picotalker import PicoTalkerDisplay


class TestPicoTalkerSoxBackend(unittest.TestCase):
    def _talker(self):
        talker = PicoTalkerDisplay.__new__(PicoTalkerDisplay)
        talker.speed_factor = 1.15
        return talker

    @patch("picotalker.subprocess.Popen")
    def test_sox_play_uses_timeout_and_devnull_output(self, popen_mock):
        process = Mock()
        process.wait.return_value = 0
        popen_mock.return_value = process

        played = self._talker().pico3_sound_player("checkmate.ogg")

        self.assertTrue(played)
        popen_mock.assert_called_once_with(
            ["play", "checkmate.ogg", "tempo", "1.15"],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        process.wait.assert_called_once()
        self.assertIn("timeout", process.wait.call_args.kwargs)

    @patch("picotalker.os.killpg")
    @patch("picotalker.subprocess.Popen")
    def test_sox_play_timeout_terminates_process_group(self, popen_mock, killpg_mock):
        process = Mock()
        process.pid = 1234
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("play", 12.0), None]
        popen_mock.return_value = process

        with self.assertLogs("picotalker", level="WARNING"):
            played = self._talker().pico3_sound_player("checkmate.ogg")

        self.assertFalse(played)
        killpg_mock.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)


if __name__ == "__main__":
    unittest.main()
