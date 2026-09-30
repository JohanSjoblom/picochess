import unittest

from picochess import (
    WEB_SERVER_PERMISSION_FALLBACK_PORT,
    WebServerListenError,
    _listen_web_app,
    _warn_unknown_parameters,
)


class FakeWebApp:
    def __init__(self, errors=None):
        self.errors = list(errors or [])
        self.ports = []

    def listen(self, port):
        self.ports.append(port)
        if self.errors:
            error = self.errors.pop(0)
            if error is not None:
                raise error


class TestPicochessWebStartup(unittest.TestCase):
    def test_unknown_startup_parameters_do_not_log_values(self):
        unknown = ["--hotspot-ssid=phone", "--hotspot-pass=secret-value", "--other-pass", "another-secret"]

        with self.assertLogs("picochess", level="WARNING") as captured:
            _warn_unknown_parameters(unknown)

        self.assertEqual(["WARNING:picochess:4 unrecognized startup parameter(s) ignored"], captured.output)
        self.assertNotIn("secret-value", captured.output[0])
        self.assertNotIn("another-secret", captured.output[0])

    def test_listen_uses_requested_port_when_available(self):
        web_app = FakeWebApp()

        port = _listen_web_app(web_app, 80)

        self.assertEqual(80, port)
        self.assertEqual([80], web_app.ports)

    def test_port_80_permission_error_falls_back_to_8080(self):
        web_app = FakeWebApp([PermissionError(), None])

        with self.assertLogs("picochess", level="WARNING"):
            port = _listen_web_app(web_app, 80)

        self.assertEqual(WEB_SERVER_PERMISSION_FALLBACK_PORT, port)
        self.assertEqual([80, WEB_SERVER_PERMISSION_FALLBACK_PORT], web_app.ports)

    def test_busy_port_80_does_not_fall_back(self):
        web_app = FakeWebApp([OSError()])

        with self.assertRaises(WebServerListenError) as raised:
            _listen_web_app(web_app, 80)

        self.assertEqual(80, raised.exception.port)
        self.assertEqual("unavailable", raised.exception.reason)
        self.assertEqual([80], web_app.ports)

    def test_custom_privileged_port_permission_error_does_not_fall_back(self):
        web_app = FakeWebApp([PermissionError()])

        with self.assertRaises(WebServerListenError) as raised:
            _listen_web_app(web_app, 81)

        self.assertEqual(81, raised.exception.port)
        self.assertEqual("permission", raised.exception.reason)
        self.assertEqual([81], web_app.ports)

    def test_fallback_port_busy_reports_fallback_port(self):
        web_app = FakeWebApp([PermissionError(), OSError()])

        with self.assertLogs("picochess", level="WARNING"):
            with self.assertRaises(WebServerListenError) as raised:
                _listen_web_app(web_app, 80)

        self.assertEqual(WEB_SERVER_PERMISSION_FALLBACK_PORT, raised.exception.port)
        self.assertEqual("unavailable", raised.exception.reason)
        self.assertEqual([80, WEB_SERVER_PERMISSION_FALLBACK_PORT], web_app.ports)
