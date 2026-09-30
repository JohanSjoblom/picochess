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

from collections import OrderedDict
from typing import Dict, List, Optional

from uci.read import read_engine_ini


class EngineProvider(object):
    """
    EngineProvider is a data holder for defined engines in engines.ini, retro.ini and favorites.ini.
    """

    modern_engines: List[Dict[str, str]] = []
    retro_engines: List[Dict[str, str]] = []
    favorite_engines: List[Dict[str, str]] = []
    installed_engines: List[Dict[str, str]] = []
    engine_menu_sort = "file"

    @classmethod
    def init(cls, engine_menu_sort: str = "file"):
        cls.set_engine_menu_sort(engine_menu_sort)
        cls.modern_engines: List[Dict[str, str]] = read_engine_ini(filename="engines.ini")
        cls.retro_engines: List[Dict[str, str]] = read_engine_ini(filename="retro.ini")
        cls.favorite_engines: List[Dict[str, str]] = read_engine_ini(filename="favorites.ini")
        # set retro/favorite engines to the list of modern engines in case retro.ini or favorites.ini is empty
        if not cls.retro_engines:
            cls.retro_engines = cls.modern_engines
        if not cls.favorite_engines:
            cls.favorite_engines = cls.modern_engines
        cls.installed_engines: List[Dict[str, str]] = cls.modern_engines + cls.retro_engines + cls.favorite_engines

    @classmethod
    def set_engine_menu_sort(cls, sort_order: str) -> str:
        """Set presentation ordering without changing any engine-list indexes."""
        normalized = str(sort_order or "file").strip().lower()
        cls.engine_menu_sort = normalized if normalized in ("file", "engine", "manufacturer") else "file"
        return cls.engine_menu_sort

    @classmethod
    def get_retro_groups(cls) -> List[Dict]:
        """Return manufacturer groups containing stable indexes into retro_engines."""
        return cls.get_engine_groups(cls.retro_engines)

    @classmethod
    def get_engine_groups(cls, engines: List[Dict]) -> List[Dict]:
        """Return optional manufacturer groups for any engine catalog."""
        if not any(str(engine.get("manufacturer", "")).strip() for engine in engines):
            return []

        groups = OrderedDict()
        for index, engine in enumerate(engines):
            manufacturer = str(engine.get("manufacturer", "")).strip() or "Other"
            groups.setdefault(manufacturer, []).append(index)

        if cls.engine_menu_sort in ("engine", "manufacturer"):
            for indexes in groups.values():
                indexes.sort(key=lambda item: (str(engines[item].get("name", "")).casefold(), item))

        group_items = list(groups.items())
        if cls.engine_menu_sort == "manufacturer":
            group_items.sort(key=lambda item: item[0].casefold())
        return [{"manufacturer": manufacturer, "engine_indexes": indexes} for manufacturer, indexes in group_items]

    @classmethod
    def get_flat_retro_engine_indexes(cls) -> List[int]:
        """Return the presentation order used when retro.ini has no manufacturer metadata."""
        return cls.get_flat_engine_indexes(cls.retro_engines)

    @classmethod
    def get_flat_engine_indexes(cls, engines: List[Dict]) -> List[int]:
        """Return flat presentation indexes for an engine catalog."""
        indexes = list(range(len(engines)))
        if cls.engine_menu_sort in ("engine", "manufacturer"):
            indexes.sort(key=lambda item: (str(engines[item].get("name", "")).casefold(), item))
        return indexes

    @staticmethod
    def engine_matches(installed_file: str, requested_file: Optional[str]) -> bool:
        """Return True when a configured engine path resolves to an installed engine entry."""
        return bool(requested_file) and (
            installed_file == requested_file or installed_file.endswith(requested_file)
        )

    @classmethod
    def resolve_engine(cls, requested_file: Optional[str]) -> Optional[Dict[str, str]]:
        """Resolve a configured engine path to an installed engine, falling back to the first entry."""
        for eng in cls.installed_engines:
            if cls.engine_matches(eng["file"], requested_file):
                return eng
        if cls.installed_engines:
            return cls.installed_engines[0]
        return None

    @classmethod
    def has_engine(cls, requested_file: Optional[str]) -> bool:
        """Return True if the configured engine is present in the installed engine list."""
        return any(cls.engine_matches(eng["file"], requested_file) for eng in cls.installed_engines)
