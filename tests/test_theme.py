import datetime
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import theme


@contextmanager
def freeze_time(value):
    if isinstance(value, str):
        value = datetime.datetime.fromisoformat(value)

    class FixedDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return value
            if value.tzinfo is None:
                return value.replace(tzinfo=tz)
            return value.astimezone(tz)

    with patch("theme.datetime.datetime", FixedDatetime):
        yield


@patch("utilities.get_location")
class TestTheme(unittest.TestCase):
    def test_calc_theme_for_known_astral_location(self, mocked_get_location):
        with freeze_time("2022-12-21 22:00:00"):
            self.assertEqual("dark", theme.calc_theme("auto", "auto"))
        with freeze_time("2022-12-21 13:00:00"):
            self.assertEqual("light", theme.calc_theme("auto", "auto"))

    def test_calc_theme_for_known_astral_location_from_settings(self, _):
        with freeze_time("2022-12-21 22:00:00"):
            self.assertEqual("dark", theme.calc_theme("auto", "Vienna"))
        with freeze_time("2022-12-21 13:00:00"):
            self.assertEqual("light", theme.calc_theme("auto", "Vienna"))

    @patch("theme._location_info_from_location")
    def test_calc_theme_for_unknown_astral_but_known_geolocation(self, mocked_location_info, mocked_get_location):
        mocked_get_location.return_value = ("Woerdern, Austria AT", "127.0.0.1", "127.0.0.1")
        mocked_location_info.return_value = theme.LocationInfo(
            "Woerdern",
            "AT",
            "Europe/Vienna",
            48.3345,
            16.2374,
        )
        with freeze_time("2022-12-21 22:00:00"):
            self.assertEqual("dark", theme.calc_theme("auto", "auto"))
        with freeze_time("2022-12-21 13:00:00"):
            self.assertEqual("light", theme.calc_theme("auto", "auto"))

    @patch("theme._local_time")
    def test_auto_uses_pi_local_date_for_western_location(self, mocked_local_time, _):
        local_timezone = datetime.timezone(datetime.timedelta(hours=-4))
        mocked_local_time.return_value = datetime.datetime(2026, 8, 10, 12, 0, tzinfo=local_timezone)
        location_info = theme.LocationInfo(
            "New York",
            "US",
            "UTC",
            40.7128,
            -74.0060,
        )

        self.assertEqual("light", theme._theme_from_location_info(location_info))

    def test_calc_theme_according_to_current_time(self, mocked_get_location):
        mocked_get_location.return_value = ("?", None, None)
        with freeze_time("2022-12-21 16:59:00"):
            self.assertEqual("light", theme.calc_theme("auto", "auto"))
        with freeze_time("2022-12-21 17:00:00"):
            self.assertEqual("dark", theme.calc_theme("auto", "auto"))
        with freeze_time("2022-12-21 09:00:00"):
            self.assertEqual("dark", theme.calc_theme("auto", "auto"))
        with freeze_time("2022-12-21 09:01:00"):
            self.assertEqual("light", theme.calc_theme("auto", "auto"))

    def test_calc_theme_pass_through(self, _):
        self.assertEqual("light", theme.calc_theme("light", "auto"))
        self.assertEqual("dark", theme.calc_theme("dark", "auto"))

    def test_resolver_rechecks_time_without_repeating_location_lookup(self, mocked_get_location):
        mocked_get_location.return_value = ("?", None, None)
        resolver = theme.ThemeResolver("auto")

        with patch("theme._location_info_from_location", return_value=None):
            with freeze_time("2022-12-21 10:00:00"):
                self.assertEqual("light", resolver.resolve("auto"))
            with freeze_time("2022-12-21 18:00:00"):
                self.assertEqual("dark", resolver.resolve("auto"))

        mocked_get_location.assert_called_once_with()
        self.assertFalse(resolver.needs_location_lookup("auto"))

    def test_resolver_does_not_look_up_location_for_explicit_theme(self, mocked_get_location):
        resolver = theme.ThemeResolver("auto")

        self.assertEqual("light", resolver.resolve("light"))
        self.assertEqual("dark", resolver.resolve("dark"))

        mocked_get_location.assert_not_called()
        self.assertTrue(resolver.needs_location_lookup("auto"))
