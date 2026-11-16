"""Check staged Lc0 catalog entries with a real search before installation.

Used by the Windows and macOS installers. Every ``<engine>.uci`` file in the
given folder is paired with its executable, started with the network from its
``[DEFAULT]`` section and asked for a short search. A UCI handshake alone does
not prove that the backend can evaluate the network.
"""

import configparser
import pathlib
import subprocess
import sys

import chess
import chess.engine


def check(folder: pathlib.Path) -> bool:
    ok = True
    level_files = sorted(folder.glob("*.uci"))
    if not level_files:
        print(f"No .uci files found in {folder}")
        return False
    for level_file in level_files:
        executable = folder / level_file.stem
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str  # type: ignore[assignment]
        parser.read(level_file, encoding="utf-8")
        defaults = parser["DEFAULT"]
        options = {"WeightsFile": defaults["WeightsFile"], "Threads": 1}
        if "Backend" in defaults:
            options["Backend"] = defaults["Backend"]
        engine = None
        try:
            engine = chess.engine.SimpleEngine.popen_uci(str(executable), timeout=120, stderr=subprocess.DEVNULL)
            engine.configure(options)
            result = engine.play(chess.Board(), chess.engine.Limit(nodes=10))
            print(f"{executable.name}: {pathlib.Path(options['WeightsFile']).name} -> {result.move}")
        except Exception as error:  # report every entry, then fail once
            print(f"{executable.name}: FAILED with {pathlib.Path(options['WeightsFile']).name}: {error!r}")
            ok = False
        finally:
            if engine is not None:
                engine.quit()
    return ok


if __name__ == "__main__":
    sys.exit(0 if check(pathlib.Path(sys.argv[1])) else 1)
