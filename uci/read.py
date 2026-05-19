# Copyright (C) 2013-2018 Jean-Francois Romang (jromang@posteo.de)
#                         Shivkumar Shivaji ()
#                         Jürgen Précour (LocutusOfPenguin@posteo.de)
#
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

import logging
import platform
import configparser
import os
from dgt.api import Dgt


logger = logging.getLogger(__name__)


def _retro_clock_text(text: str, max_len: int) -> str:
    """Return a single-token clock label so retro names do not wrap."""
    return "".join(str(text).split())[:max_len]


def resolve_engine_path(engine_path=None, filename: str | None = None) -> str:
    if engine_path:
        return engine_path

    program_path = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    engines_root = os.path.join(program_path, "engines")
    preferred_paths = []
    for candidate in (
        os.path.join(engines_root, platform.machine()),
        os.path.join(engines_root, "aarch64"),
    ):
        if candidate not in preferred_paths:
            preferred_paths.append(candidate)

    try:
        for entry in os.listdir(engines_root):
            candidate = os.path.join(engines_root, entry)
            if os.path.isdir(candidate) and candidate not in preferred_paths:
                preferred_paths.append(candidate)
    except OSError:
        pass

    standard_files = ("engines.ini", "retro.ini", "favorites.ini")

    def _score(candidate: str):
        if not os.path.isdir(candidate):
            return (-1, -1)
        matching_file = int(bool(filename) and os.path.isfile(os.path.join(candidate, filename)))
        available_files = sum(int(os.path.isfile(os.path.join(candidate, item))) for item in standard_files)
        return (matching_file, available_files)

    existing_candidates = [candidate for candidate in preferred_paths if os.path.isdir(candidate)]
    if existing_candidates:
        return max(existing_candidates, key=_score)

    return preferred_paths[0]


def read_engine_ini(engine_shell=None, engine_path=None, filename=None) -> list[dict[str, str]]:
    l_web_text = ""
    """Read engine.ini and create a library list out of it."""
    if filename is None:
        filename = "engines.ini"
    config = configparser.ConfigParser()
    config.optionxform = str  # type: ignore
    try:
        if engine_shell is None:
            engine_path = resolve_engine_path(engine_path, filename)
            logger.debug("complete path without shell: %s", str(engine_path + os.sep + filename))
            config.read(engine_path + os.sep + filename)
        else:
            logger.debug("complete path: %s", str(engine_path + os.sep + filename))
            with engine_shell.open(engine_path + os.sep + filename, "r") as file:
                config.read_file(file)
    except FileNotFoundError:
        pass

    library = []
    for section in config.sections():
        parser = configparser.ConfigParser()
        parser.optionxform = str  # type: ignore

        level_dict: dict[str, dict] = {}
        if engine_shell is None:
            success = bool(parser.read(engine_path + os.sep + section + ".uci"))
        else:
            try:
                with engine_shell.open(engine_path + os.sep + section + ".uci", "r") as file:
                    parser.read_file(file)
                success = True
            except FileNotFoundError:
                success = False
        if success:
            for p_section in parser.sections():
                level_dict[p_section] = {}
                for option in parser.options(p_section):
                    level_dict[p_section][option] = parser[p_section][option]

        confsect = config[section]
        l_web_text = confsect["web"] if "web" in confsect else confsect["large"]
        large_text = confsect["large"]
        medium_text = confsect["medium"]
        small_text = confsect["small"]
        if filename == "retro.ini" and section.startswith("mame/"):
            large_text = _retro_clock_text(large_text, 11)
            medium_text = _retro_clock_text(medium_text or large_text, 8)
            small_text = _retro_clock_text(small_text or medium_text or large_text, 6)
        text = Dgt.DISPLAY_TEXT(
            web_text=l_web_text,
            large_text=large_text,
            medium_text=medium_text,
            small_text=small_text,
            wait=True,
            beep=False,
            maxtime=0,
            devs={"ser", "i2c", "web"},
        )
        library.append(
            {
                "file": engine_path + os.sep + section,
                "level_dict": level_dict,
                "text": text,
                "name": confsect["name"],
                "elo": confsect["elo"],
            }
        )
    return library
