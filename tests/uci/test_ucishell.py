import unittest

from uci.engine import UciShell


class TestUciShell(unittest.TestCase):
    def test_no_hostname(self):
        uci_shell = UciShell()
        self.assertIsNone(uci_shell.get())

    def test_password_authentication_settings(self):
        uci_shell = UciShell(hostname="test", username="user", password="pass")
        self.assertEqual(uci_shell.hostname, "test")
        self.assertEqual(uci_shell.username, "user")
        self.assertEqual(uci_shell.password, "pass")
        self.assertIsNone(uci_shell.key_file)
        self.assertIs(uci_shell, uci_shell.get())

    def test_private_key_authentication_settings(self):
        uci_shell = UciShell(hostname="test", username="user", key_file="key")
        self.assertEqual(uci_shell.hostname, "test")
        self.assertEqual(uci_shell.username, "user")
        self.assertEqual(uci_shell.key_file, "key")
        self.assertIsNone(uci_shell.password)
        self.assertIs(uci_shell, uci_shell.get())

    def test_remote_platform_settings(self):
        uci_shell = UciShell(hostname="test", windows=True, remote_home=r"C:\Engines")
        self.assertTrue(uci_shell.windows)
        self.assertEqual(uci_shell.remote_home, r"C:\Engines")
        self.assertIs(uci_shell, uci_shell.get())
