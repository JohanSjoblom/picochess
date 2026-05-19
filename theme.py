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

def normalize_theme(theme_in: str, default: str = "dark") -> str:
    theme = (theme_in or "").strip().lower()
    if theme in ("light", "dark"):
        return theme
    return default if default in ("light", "dark") else "dark"


def calc_theme(theme_in: str, location_setting: str) -> str:
    return normalize_theme(theme_in)
