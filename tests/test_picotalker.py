#!/usr/bin/env python3

import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from dgt.util import GameResult
from picotalker import BLACK_WIN_RESULTS, WHITE_WIN_RESULTS, PicoTalkerDisplay


class TestPicoTalkerVariantResults(unittest.TestCase):
    def test_all_variant_wins_use_the_existing_winner_announcements(self):
        self.assertTrue(
            {
                GameResult.THREE_CHECK_WHITE,
                GameResult.KOTH_WHITE,
                GameResult.ATOMIC_WHITE,
                GameResult.RK_WHITE,
                GameResult.ANTICHESS_WHITE,
            }.issubset(WHITE_WIN_RESULTS)
        )
        self.assertTrue(
            {
                GameResult.THREE_CHECK_BLACK,
                GameResult.KOTH_BLACK,
                GameResult.ATOMIC_BLACK,
                GameResult.RK_BLACK,
                GameResult.ANTICHESS_BLACK,
            }.issubset(BLACK_WIN_RESULTS)
        )


class TestPicoTalkerSoxBackend(unittest.TestCase):
    def _talker(self):
        talker = PicoTalkerDisplay.__new__(PicoTalkerDisplay)
        talker.speed_factor = 1.15
        talker._apply_playback_volume = Mock()
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


class TestPicoTalkerNativeVolume(unittest.TestCase):
    def _talker(self):
        talker = PicoTalkerDisplay.__new__(PicoTalkerDisplay)
        talker.native_stream = None
        talker.native_stream_samplerate = None
        talker.native_stream_channels = None
        talker.native_stream_lock = threading.RLock()
        talker.volume_factor_getter = lambda: 10
        talker.playback_volume_state = {}
        return talker

    @patch("picotalker.set_system_volume")
    @patch("picotalker.sd.OutputStream")
    def test_native_stream_reapplies_volume_after_start(self, output_stream, set_volume):
        stream = Mock(active=True)
        started = False

        def mark_started():
            nonlocal started
            started = True

        def require_started(_volume_factor, _backend, _volume_factor_getter):
            self.assertTrue(started)
            return True

        stream.start.side_effect = mark_started
        set_volume.side_effect = require_started
        output_stream.return_value = stream
        talker = self._talker()

        ready = talker._ensure_native_stream(16000, 1)

        self.assertTrue(ready)
        stream.start.assert_called_once_with()
        set_volume.assert_called_once_with(10, "native", talker.volume_factor_getter)

    @patch("picotalker.time.monotonic", return_value=0)
    @patch("picotalker.set_system_volume", side_effect=[False, True])
    @patch("picotalker.sd.OutputStream", return_value=Mock(active=True))
    def test_failed_volume_retries_without_reopening_stream(self, output_stream, set_volume, now):
        talker = self._talker()
        with self.assertLogs("picotalker", level="WARNING"):
            self.assertTrue(talker._ensure_native_stream(16000, 1))
        now.return_value = 0.5
        talker._ensure_native_stream(16000, 1)
        self.assertEqual(set_volume.call_count, 1)
        now.return_value = 1
        talker._ensure_native_stream(16000, 1)
        self.assertEqual(set_volume.call_count, 2)
        now.return_value = 100
        talker._ensure_native_stream(16000, 1)
        self.assertEqual(set_volume.call_count, 2)
        output_stream.assert_called_once()

    @patch("picotalker.set_system_volume", return_value=True)
    @patch("picotalker.sd.OutputStream", return_value=Mock(active=True))
    def test_format_change_reapplies_committed_volume(self, _output_stream, set_volume):
        from dgt.menu import DgtMenu

        menu = DgtMenu.__new__(DgtMenu)
        menu.set_voice_volume(10)
        talker = self._talker()
        talker.volume_factor_getter = menu.get_voice_volume
        talker._ensure_native_stream(16000, 1)
        menu.menu_system_voice_volumefactor = 11  # menu edit, not confirmed
        talker._ensure_native_stream(22050, 1)
        self.assertEqual(set_volume.call_count, 2)
        set_volume.assert_called_with(10, "native", talker.volume_factor_getter)

    @patch("picotalker.time.monotonic", return_value=0)
    @patch("picotalker.set_system_volume", side_effect=[False, True])
    @patch("picotalker.subprocess.Popen")
    def test_sox_retries_volume_before_later_playback(self, popen, set_volume, now):
        popen.return_value.wait.return_value = 0
        talker = self._talker()
        talker.speed_factor = 1.0
        with self.assertLogs("picotalker", level="WARNING"):
            self.assertTrue(talker.pico3_sound_player("check.ogg"))
        now.return_value = 1
        self.assertTrue(talker.pico3_sound_player("check.ogg"))
        self.assertEqual(set_volume.call_count, 2)
        set_volume.assert_called_with(10, "sox", talker.volume_factor_getter)


if __name__ == "__main__":
    unittest.main()
