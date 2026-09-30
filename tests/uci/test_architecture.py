import unittest
from unittest.mock import patch

from uci.architecture import engine_platform_name, local_default_engine_path, local_engine_directory


class TestEngineArchitecture(unittest.TestCase):
    def test_intel_macos_has_separate_engine_folder(self):
        self.assertEqual("mac_x86_64", engine_platform_name("Darwin", "x86_64"))

    def test_apple_silicon_keeps_native_machine_name(self):
        self.assertEqual("arm64", engine_platform_name("Darwin", "arm64"))

    def test_linux_engine_folder_names_are_unchanged(self):
        self.assertEqual("x86_64", engine_platform_name("Linux", "x86_64"))
        self.assertEqual("aarch64", engine_platform_name("Linux", "aarch64"))

    def test_windows_engine_folder_name_is_unchanged(self):
        self.assertEqual("AMD64", engine_platform_name("Windows", "AMD64"))

    @patch("uci.architecture.platform.machine", return_value="x86_64")
    @patch("uci.architecture.platform.system", return_value="Darwin")
    def test_local_engine_directory_uses_platform_mapping(self, _system, _machine):
        self.assertEqual("mac_x86_64", local_engine_directory().name)

    def test_windows_default_engine_uses_exe_suffix(self):
        path = local_default_engine_path("Windows", "AMD64")
        self.assertEqual(("engines", "AMD64", "a-stockf.exe"), path.parts[-3:])

    def test_linux_default_engine_has_no_exe_suffix(self):
        path = local_default_engine_path("Linux", "x86_64")
        self.assertEqual(("engines", "x86_64", "a-stockf"), path.parts[-3:])

    def test_intel_macos_default_engine_uses_mapped_directory(self):
        path = local_default_engine_path("Darwin", "x86_64")
        self.assertEqual(("engines", "mac_x86_64", "a-stockf"), path.parts[-3:])


if __name__ == "__main__":
    unittest.main()
