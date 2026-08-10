# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import datetime
import threading
from geopy.geocoders import Nominatim  # type: ignore
from geopy.exc import GeopyError  # type: ignore
from astral import LocationInfo  # type: ignore
from astral.sun import sun  # type: ignore
import astral.geocoder  # type: ignore

import utilities


class ThemeResolver:
    """Resolve a theme while performing location discovery at most once."""

    def __init__(self, location_setting: str):
        self.location_setting = location_setting
        self._location_info = None
        self._location_checked = False
        self._location_lock = threading.Lock()

    def resolve(self, theme_in: str) -> str:
        if theme_in == "auto":
            location_info = self._get_location_info()
            if location_info is not None:
                try:
                    return _theme_from_location_info(location_info)
                except (KeyError, ValueError):
                    pass
            return _theme_according_to_current_time()
        if theme_in == "time":
            return _theme_according_to_current_time()
        return theme_in

    def needs_location_lookup(self, theme_in: str) -> bool:
        """Return whether resolving this preference may perform blocking I/O."""
        return theme_in == "auto" and not self._location_checked

    def _get_location_info(self):
        if self._location_checked:
            return self._location_info
        with self._location_lock:
            if not self._location_checked:
                location = (
                    utilities.get_location()[0] if self.location_setting == "auto" else self.location_setting
                )
                try:
                    self._location_info = astral.geocoder.lookup(location, astral.geocoder.database())
                except KeyError:
                    self._location_info = _location_info_from_location(location)
                self._location_checked = True
        return self._location_info


def calc_theme(theme_in: str, location_setting: str) -> str:
    return ThemeResolver(location_setting).resolve(theme_in)


def _theme_according_to_current_time() -> str:
    # check if before or after 9am/5pm
    now = datetime.datetime.now()
    year = now.year
    month = now.month
    day = now.day
    sunset = datetime.datetime(year, month, day, 17)
    sunrise = datetime.datetime(year, month, day, 9)
    return _theme_for_time(now, sunrise, sunset)


def _local_time() -> datetime.datetime:
    """Return the Pi's current local time with its UTC offset."""
    return datetime.datetime.now().astimezone()


def _theme_from_location_info(location_info) -> str:
    local_time = _local_time()
    local_timezone = local_time.tzinfo
    sun_info = sun(location_info.observer, date=local_time.date(), tzinfo=local_timezone)
    return _theme_for_time(local_time, sun_info["sunrise"], sun_info["sunset"])


def _theme_for_time(current_time: datetime.datetime, sunrise: datetime.datetime, sunset: datetime.datetime) -> str:
    if sunrise < current_time < sunset:
        theme = "light"
    else:
        theme = "dark"
    return theme


def _location_info_from_location(location: str):
    location_info = None
    geolocator = Nominatim(user_agent="Picochess")
    try:
        loc = geolocator.geocode(location)
    except GeopyError:
        loc = None
    if loc is not None:
        location_info = LocationInfo(
            location,
            "",
            # Theme calculation uses the Pi's live local tzinfo. This value is
            # only a valid placeholder required by Astral's LocationInfo.
            "UTC",
            loc.latitude,
            loc.longitude,
        )
    return location_info
