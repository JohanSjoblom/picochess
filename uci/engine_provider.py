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
import json
import logging
from pathlib import Path
import re
from typing import Dict, List, Optional

from uci.architecture import local_engine_directory
from uci.read import read_engine_ini


logger = logging.getLogger(__name__)


class EngineProvider(object):
    """
    Hold the Modern, Retro and Special engine catalogs.

    New engine packages call the static Special catalog ``special.ini``.  The
    old name ``favorites.ini`` remains a read-only compatibility fallback; it
    must never be confused with the user's dynamic list of favorite engines.
    """

    modern_engines: List[Dict[str, str]] = []
    nnue_engines: List[Dict[str, str]] = []
    retro_engines: List[Dict[str, str]] = []
    special_engines: List[Dict[str, str]] = []
    variant_engines: List[Dict[str, str]] = []
    hidden_profiles: List[Dict[str, str]] = []
    unavailable_profiles: List[Dict[str, str]] = []
    installed_engines: List[Dict[str, str]] = []
    visible_profiles: List[Dict[str, str]] = []
    all_profiles: List[Dict[str, str]] = []
    profiles_by_id: Dict[str, Dict[str, str]] = {}
    favorite_profile_ids: List[str] = []
    favorite_profiles: List[Dict[str, str]] = []
    engine_menu_sort = "file"

    @classmethod
    def init(cls, engine_menu_sort: str = "file", engine_favorites: str = "[]"):
        cls.set_engine_menu_sort(engine_menu_sort)
        cls.modern_engines = read_engine_ini(filename="engines.ini")
        cls.retro_engines = read_engine_ini(filename="retro.ini")
        special_ini = Path(local_engine_directory(), "special.ini")
        if special_ini.is_file():
            cls.special_engines = read_engine_ini(filename="special.ini")
        else:
            cls.special_engines = read_engine_ini(filename="favorites.ini")
            if cls.special_engines:
                logger.warning("favorites.ini is deprecated; rename the Special catalog to special.ini")
        cls.nnue_engines = read_engine_ini(filename="nnue.ini")
        cls.variant_engines = read_engine_ini(filename="variants.ini")
        cls.unavailable_profiles = []
        for category, attribute in (
            ("modern", "modern_engines"),
            ("nnue", "nnue_engines"),
            ("retro", "retro_engines"),
            ("special", "special_engines"),
            ("variants", "variant_engines"),
        ):
            available = []
            for profile in getattr(cls, attribute):
                profile["source_category"] = category
                if profile.get("available", True):
                    available.append(profile)
                else:
                    cls.unavailable_profiles.append(profile)
            setattr(cls, attribute, available)
        cls.hidden_profiles = []
        if cls.variant_engines:
            visible_modern = []
            for profile in cls.modern_engines:
                if profile.get("profile_id") == "fairy":
                    cls.hidden_profiles.append(profile)
                else:
                    visible_modern.append(profile)
            cls.modern_engines = visible_modern
        # Keep the historical installed order stable; new catalogs are appended.
        cls.installed_engines = (
            cls.modern_engines
            + cls.retro_engines
            + cls.special_engines
            + cls.nnue_engines
            + cls.variant_engines
        )
        cls._rebuild_profile_index()
        cls.set_favorite_ids(engine_favorites)

    @classmethod
    def _rebuild_profile_index(cls):
        """Index logical profiles globally while retaining deterministic first-wins behavior."""
        catalogs = (
            ("modern", cls.modern_engines),
            ("nnue", cls.nnue_engines),
            ("retro", cls.retro_engines),
            ("special", cls.special_engines),
            ("variants", cls.variant_engines),
        )
        cls.visible_profiles = []
        cls.profiles_by_id = {}
        for category, catalog in catalogs:
            for profile in catalog:
                profile.setdefault("source_category", category)
                profile_id = str(profile.get("profile_id", profile.get("file", "")))
                profile["profile_id"] = profile_id
                cls.visible_profiles.append(profile)
                if profile_id in cls.profiles_by_id:
                    if cls.profiles_by_id[profile_id] is profile:
                        # Historical empty-catalog fallback aliases Modern into
                        # another category; it is not a second definition.
                        continue
                    logger.warning(
                        "duplicate engine profile id '%s' in %s; keeping first definition",
                        profile_id,
                        category,
                    )
                    continue
                cls.profiles_by_id[profile_id] = profile
        cls.all_profiles = list(cls.visible_profiles)
        for profile in cls.hidden_profiles:
            profile_id = str(profile.get("profile_id", profile.get("file", "")))
            profile["profile_id"] = profile_id
            profile["hidden"] = True
            cls.all_profiles.append(profile)
            if profile_id in cls.profiles_by_id:
                logger.warning("hidden engine profile id '%s' duplicates a visible profile; keeping visible", profile_id)
            else:
                cls.profiles_by_id[profile_id] = profile
        for profile in cls.unavailable_profiles:
            profile_id = str(profile.get("profile_id", profile.get("file", "")))
            profile["profile_id"] = profile_id
            cls.all_profiles.append(profile)
            if profile_id in cls.profiles_by_id:
                logger.warning("unavailable engine profile id '%s' duplicates another profile; keeping first", profile_id)
            else:
                cls.profiles_by_id[profile_id] = profile

    @classmethod
    def resolve_profile(cls, profile_id: Optional[str]) -> Optional[Dict[str, str]]:
        """Resolve an exact logical profile ID without falling back to another engine."""
        if not profile_id:
            return None
        return cls.profiles_by_id.get(profile_id)

    @staticmethod
    def parse_favorite_ids(value) -> List[str]:
        """Parse the persisted ordered JSON list, ignoring malformed and duplicate IDs."""
        if isinstance(value, (list, tuple)):
            parsed = value
        else:
            try:
                parsed = json.loads(str(value or "[]"))
            except (TypeError, ValueError, json.JSONDecodeError):
                logger.warning("invalid engine-favorites value; ignoring it")
                return []
        if not isinstance(parsed, list):
            logger.warning("engine-favorites must be a JSON list; ignoring it")
            return []
        result = []
        for item in parsed:
            profile_id = str(item)
            if profile_id and profile_id not in result:
                result.append(profile_id)
        return result

    @classmethod
    def set_favorite_ids(cls, value) -> List[str]:
        """Load favorites, silently dropping profile IDs no longer in the catalog."""
        requested = cls.parse_favorite_ids(value)
        cls.favorite_profile_ids = [
            profile_id
            for profile_id in requested
            if profile_id in cls.profiles_by_id and not cls.profiles_by_id[profile_id].get("hidden")
        ]
        cls._refresh_favorite_profiles()
        return list(cls.favorite_profile_ids)

    @classmethod
    def migrate_legacy_fairy_profile(cls, profile: Optional[Dict[str, str]], level_name: Optional[str]):
        """Resolve an old combined Fairy level to its new visible variant profile."""
        if not profile or profile.get("profile_id") != "fairy" or not level_name:
            return profile
        level_prefix = str(level_name).partition("@")[0].strip().casefold()
        legacy_variants = {
            "3check": "3check",
            "koth": "kingofthehill",
            "atomic": "atomic",
            "rk": "racingkings",
            "racingkings": "racingkings",
            "anti": "antichess",
            "antichess": "antichess",
        }
        target_variant = legacy_variants.get(level_prefix)
        if target_variant is None:
            return profile
        for candidate in cls.variant_engines:
            if candidate.get("file") == profile.get("file") and candidate.get("variant") == target_variant:
                return candidate
        return profile

    @staticmethod
    def level_names(profile: Dict) -> List[str]:
        """Return level names in numeric order without renaming stable section keys."""
        def sort_key(name: str):
            prefix, separator, suffix = str(name).rpartition("@")
            if separator and re.fullmatch(r"-?\d+", suffix):
                return prefix.casefold(), 0, int(suffix), str(name).casefold()
            return str(name).casefold(), 1, 0, str(name).casefold()

        return sorted(profile.get("level_dict", {}), key=sort_key)

    @classmethod
    def _refresh_favorite_profiles(cls):
        cls.favorite_profiles = [cls.profiles_by_id[profile_id] for profile_id in cls.favorite_profile_ids]

    @classmethod
    def set_favorite(cls, profile_id: str, favorite: bool) -> bool:
        """Set the desired favorite state; return False for an invalid request."""
        profile = cls.resolve_profile(profile_id)
        if profile is None or profile.get("hidden"):
            return False
        if favorite:
            if profile not in cls.visible_profiles:
                return False
            if profile_id not in cls.favorite_profile_ids:
                cls.favorite_profile_ids.append(profile_id)
        elif profile_id in cls.favorite_profile_ids:
            cls.favorite_profile_ids.remove(profile_id)
        cls._refresh_favorite_profiles()
        return True

    @classmethod
    def serialized_favorite_ids(cls) -> str:
        return json.dumps(cls.favorite_profile_ids, separators=(",", ":"))

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

        groups: OrderedDict[str, List[int]] = OrderedDict()
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
        if not requested_file:
            return False
        return installed_file == requested_file or installed_file.endswith(requested_file)

    @classmethod
    def resolve_engine(cls, requested_file: Optional[str]) -> Optional[Dict[str, str]]:
        """Resolve a configured engine path to an installed engine, falling back to the first entry."""
        for eng in cls.installed_engines + cls.hidden_profiles:
            if cls.engine_matches(eng["file"], requested_file):
                return eng
        if cls.installed_engines:
            return cls.installed_engines[0]
        return None

    @classmethod
    def resolve_fallback_engine(
        cls, failed_file: Optional[str], preferred_file: Optional[str] = None
    ) -> Optional[Dict[str, str]]:
        """Choose an installed fallback without selecting the failed engine again."""
        if preferred_file and preferred_file != failed_file:
            for eng in cls.installed_engines:
                if cls.engine_matches(eng["file"], preferred_file) and not cls.engine_matches(
                    eng["file"], failed_file
                ):
                    return eng
        for eng in cls.installed_engines:
            if not cls.engine_matches(eng["file"], failed_file):
                return eng
        return None

    @classmethod
    def has_engine(cls, requested_file: Optional[str]) -> bool:
        """Return True if the configured engine is present in the installed engine list."""
        return any(
            cls.engine_matches(eng["file"], requested_file)
            for eng in cls.installed_engines + cls.hidden_profiles
        )
