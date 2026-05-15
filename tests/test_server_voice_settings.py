import unittest

import server
from dgt.util import Voice


class TestServerVoiceSettings(unittest.TestCase):

    def test_web_comp_voice_uses_runtime_computer_voice_key(self):
        voice_type, ini_key = server._voice_type_and_ini_key("comp")

        self.assertEqual(Voice.COMP, voice_type)
        self.assertEqual("computer-voice", ini_key)

    def test_web_user_voice_uses_user_voice_key(self):
        voice_type, ini_key = server._voice_type_and_ini_key("user")

        self.assertEqual(Voice.USER, voice_type)
        self.assertEqual("user-voice", ini_key)

    def test_muted_voice_config_is_reported_as_mute(self):
        self.assertEqual("mute", server._voice_speaker_from_config({"computer-voice": "None"}, "computer-voice"))
        self.assertEqual("mute", server._voice_speaker_from_config({}, "computer-voice"))

    def test_voice_bounds_keep_valid_mute_values(self):
        self.assertEqual(0, server._bounded_voice_volume("0"))
        self.assertEqual(0, server._bounded_voice_speed("0"))


if __name__ == "__main__":
    unittest.main()
