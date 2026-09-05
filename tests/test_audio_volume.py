#!/usr/bin/env python3

import subprocess
import unittest
from unittest.mock import Mock, call, patch

from audio_volume import ALSA_VOLUME_CHANNELS, set_system_volume


class TestAudioVolume(unittest.TestCase):
    @patch("audio_volume.subprocess.run")
    @patch("audio_volume.shutil.which", return_value="/usr/bin/wpctl")
    def test_pipewire_default_sink_is_preferred(self, _which, run):
        run.return_value = Mock(returncode=0, stdout="", stderr="")

        applied = set_system_volume(10)

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
    def test_alsa_channels_are_fallback_when_pipewire_is_not_ready(self, _which, run):
        run.side_effect = [
            Mock(returncode=1, stdout="", stderr="PipeWire unavailable"),
            *[Mock(returncode=0, stdout="", stderr="") for _ in ALSA_VOLUME_CHANNELS],
        ]

        applied = set_system_volume(7)

        self.assertTrue(applied)
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


if __name__ == "__main__":
    unittest.main()
