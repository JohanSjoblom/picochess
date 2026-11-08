#!/usr/bin/env python3
"""Build nnue.ini from profiles present in an installed engines.ini."""

import configparser
from pathlib import Path
import sys


def build_catalog(source: Path, names_file: Path, target: Path) -> tuple[list[str], list[str]]:
    parser = configparser.RawConfigParser()
    parser.optionxform = str  # type: ignore
    with source.open(encoding="utf-8") as source_file:
        parser.read_file(source_file)

    requested_names = [
        line.strip()
        for line in names_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    sections_by_name = {
        parser[section].get("name", "").strip().casefold(): section
        for section in parser.sections()
    }
    selected = []
    missing = []
    for name in requested_names:
        section = sections_by_name.get(name.casefold())
        if section is None:
            missing.append(name)
        else:
            selected.append(section)

    if not selected:
        return [], missing

    output = configparser.RawConfigParser()
    output.optionxform = str  # type: ignore
    for section in selected:
        output.add_section(section)
        for key, value in parser.items(section, raw=True):
            output.set(section, key, value)

    temporary = target.with_name(f".{target.name}.tmp")
    with temporary.open("w", encoding="utf-8") as target_file:
        target_file.write("; Generated from the installed engine package by install-engine-catalogs.sh.\n")
        output.write(target_file, space_around_delimiters=True)
    temporary.replace(target)
    return selected, missing


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: build-nnue-catalog.py ENGINES.INI ENGINE-NAMES.TXT NNUE.INI", file=sys.stderr)
        return 2
    source, names_file, target = map(Path, sys.argv[1:])
    selected, missing = build_catalog(source, names_file, target)
    if selected:
        print(f"Installed nnue.ini with {len(selected)} engine profiles.")
    else:
        print("No configured NNUE profiles were found; nnue.ini was not installed.")
    if missing:
        print("NNUE profiles absent from this engine package: " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
