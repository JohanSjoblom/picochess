#!/usr/bin/env python3

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

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


class TestPicoTalkerReplayGain(unittest.TestCase):
    def test_read_replaygain_track_gain_from_ogg_comment_bytes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            voice_file = Path(tmpdir) / "voice.ogg"
            voice_file.write_bytes(b"OggS\x00REPLAYGAIN_TRACK_GAIN=+2.62 dB\x00Vorbis")

            gain = PicoTalkerDisplay._read_replaygain_track_gain(str(voice_file))

        self.assertEqual(gain, 2.62)

    def test_read_replaygain_track_gain_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            voice_file = Path(tmpdir) / "voice.ogg"
            voice_file.write_bytes(b"OggS\x00TITLE=check\x00Vorbis")

            gain = PicoTalkerDisplay._read_replaygain_track_gain(str(voice_file))

        self.assertIsNone(gain)

    def test_apply_replaygain_track_gain_scales_samples(self):
        samples = np.array([[0.25], [-0.25]], dtype=np.float32)

        adjusted = PicoTalkerDisplay._apply_replaygain_track_gain(samples, 6.0)

        self.assertAlmostEqual(float(adjusted[0, 0]), 0.25 * (10 ** (6.0 / 20)), places=6)
        self.assertAlmostEqual(float(adjusted[1, 0]), -0.25 * (10 ** (6.0 / 20)), places=6)

    def test_apply_replaygain_track_gain_limits_positive_gain_to_prevent_clipping(self):
        samples = np.array([[0.8], [-0.4]], dtype=np.float32)

        adjusted = PicoTalkerDisplay._apply_replaygain_track_gain(samples, 6.0)

        self.assertAlmostEqual(float(np.max(np.abs(adjusted))), 1.0, places=6)
        self.assertAlmostEqual(float(adjusted[1, 0]), -0.5, places=6)

    def test_apply_replaygain_track_gain_leaves_untagged_samples_unchanged(self):
        samples = np.array([[0.25], [-0.25]], dtype=np.float32)

        adjusted = PicoTalkerDisplay._apply_replaygain_track_gain(samples, None)

        self.assertIs(adjusted, samples)


if __name__ == "__main__":
    unittest.main()
