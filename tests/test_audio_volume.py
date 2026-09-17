#!/usr/bin/env python3

import subprocess
import threading
import time
import unittest
from unittest.mock import Mock, call, patch

import audio_volume
from audio_volume import ALSA_VOLUME_CHANNELS, set_system_volume


class TestAudioVolume(unittest.TestCase):
    @patch("audio_volume.subprocess.run")
    @patch("audio_volume.shutil.which", return_value="/usr/bin/wpctl")
    def test_pipewire_default_sink_is_preferred(self, _which, run):
        run.return_value = Mock(returncode=0, stdout="", stderr="")

        applied = set_system_volume(10, "native")

        self.assertTrue(applied)
        run.assert_called_once_with(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "50%"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3.0,
            check=False,
        )

    @patch("audio_volume.subprocess.run")
    @patch("audio_volume.shutil.which", return_value="/usr/bin/wpctl")
    def test_native_alsa_fallback_does_not_hide_pipewire_failure(self, _which, run):
        run.side_effect = [
            Mock(returncode=1, stdout="", stderr="PipeWire unavailable"),
            *[Mock(returncode=0, stdout="", stderr="") for _ in ALSA_VOLUME_CHANNELS],
        ]

        applied = set_system_volume(7, "native")

        self.assertFalse(applied)
        self.assertEqual(
            [
                call(
                    ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "35%"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=3.0,
                    check=False,
                ),
                *[
                    call(
                        ["amixer", "-M", "sset", channel, "35%"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=3.0,
                        check=False,
                    )
                    for channel in ALSA_VOLUME_CHANNELS
                ],
            ],
            run.call_args_list,
        )

    @patch("audio_volume.subprocess.run")
    @patch("audio_volume.shutil.which", return_value=None)
    def test_volume_factor_is_bounded_for_alsa(self, _which, run):
        run.return_value = Mock(returncode=0, stdout="", stderr="")

        set_system_volume(99)

        self.assertTrue(all(command.args[0][-1] == "100%" for command in run.call_args_list))

    @patch("audio_volume.subprocess.run")
    @patch("audio_volume.shutil.which", return_value="/usr/bin/wpctl")
    def test_sox_preserves_alsa_controls_with_running_pipewire(self, _which, run):
        run.return_value = Mock(returncode=0, stdout="", stderr="")

        self.assertTrue(set_system_volume(10, "sox"))

        commands = [entry.args[0] for entry in run.call_args_list]
        self.assertEqual(commands[:-1], [["amixer", "-M", "sset", ch, "50%"] for ch in ALSA_VOLUME_CHANNELS])
        self.assertEqual(commands[-1], ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "50%"])

    @patch("audio_volume.subprocess.run")
    @patch("audio_volume.shutil.which", return_value="/usr/bin/wpctl")
    def test_sox_alsa_success_does_not_hide_pipewire_failure(self, _which, run):
        run.side_effect = [
            *[Mock(returncode=0, stdout="", stderr="") for _ in ALSA_VOLUME_CHANNELS],
            Mock(returncode=1, stdout="", stderr="PipeWire unavailable"),
        ]

        self.assertFalse(set_system_volume(10, "sox"))

    @patch("audio_volume.subprocess.run", side_effect=subprocess.TimeoutExpired("volume", 3))
    @patch("audio_volume.shutil.which", return_value="/usr/bin/wpctl")
    def test_timeouts_report_failure_for_retry(self, _which, run):
        self.assertFalse(set_system_volume(10, "native"))
        self.assertEqual(run.call_count, 5)

    @patch("audio_volume._apply_system_volume")
    def test_concurrent_requests_finish_with_newest_volume(self, apply_volume):
        older_started = threading.Event()
        release_older = threading.Event()
        applied_percents = []

        def apply(percent, _backend):
            if percent == 100 and not older_started.is_set():
                older_started.set()
                self.assertTrue(release_older.wait(2))
            applied_percents.append(percent)
            return True

        apply_volume.side_effect = apply
        older = threading.Thread(target=set_system_volume, args=(20, "native"))
        newer = threading.Thread(target=set_system_volume, args=(10, "native"))
        older.start()
        self.assertTrue(older_started.wait(2))
        newer.start()

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with audio_volume._volume_request_lock:
                if audio_volume._latest_volume_request[1] == 10:
                    break
            time.sleep(0.001)
        else:
            self.fail("newer volume request was not registered")

        release_older.set()
        older.join(2)
        newer.join(2)
        self.assertFalse(older.is_alive())
        self.assertFalse(newer.is_alive())
        self.assertEqual(applied_percents[-1], 50)
        self.assertNotIn(100, applied_percents[1:])

    @patch("audio_volume._apply_system_volume", return_value=True)
    def test_committed_getter_overrides_stale_playback_value(self, apply_volume):
        committed_factor = 10

        self.assertTrue(set_system_volume(20, "native", lambda: committed_factor))

        apply_volume.assert_called_once_with(50, "native")


if __name__ == "__main__":
    unittest.main()
