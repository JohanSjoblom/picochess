General
=======
This folder is for the UCI-Engines. Place the engines in your corresponding plattform folder ("armv6l", armv7l" or "x86_64")

The engines must be named after "1char-restname" for example "x-stockfish". The first char decides the order
shown in the dgt display (the first 8 engines can also be activated with the queen).

If you update the engines list please run "./build/engines.py" after it to create a new engine cache file (engines.ini).
The program will build 3 names for the three types of clocks (XL, DGT3000, DGTPi) which have different maxlength they can show.
You might tweak this file cause the program cant be as clever as you in naming (see below). Please keep in mind the max display width of the three DGT-Clocks XL; 3000; PI (6,8,11 chars).

Personalities / Levels
======================
During the engine build (see above) the script will also build a level file for each engine (as long there isn't
such file already). These files are named after the engine with a ".uci" at the end like "x-stockfish.uci".

You can update them lateron by hand if you want but they should already be in good shape for standard engines (with level
support). If you do this please follow the standard level naming way with "Level@01" & "Elo@0123". The numbers must be
2chars or 4chars long and with this key-value-string (ending on "@") infront.
Actually, you can put any valid uci-command inside each section. The auto build just builds the old level support inside
this new system. So you can tweak each engine as you want (going towards personality engines).

If you have a personality engine (like rodent_III) please use something similar to the "rodent3" folder.
I uploaded some personality_* files already. Please move them to the plattform-engine folder, and name them similar to
the engine like "m-rodent.uci".
In case of rodent_III you must also make sure the engine is running in "SHOW_OPTIONS" mode.

The order of sections in yr_engine_name.uci or engines.ini decides the order for the menu. Also the first 8 sections are used for the queen fields for quick selection.
So please sort the sections as you want them to be. The "./build/*.py" files, trying to do the best they can to have a reasonable first configuration.

If you have problems please don't hassitate to contact me over eMail or gitter.

LocutusOfPenguin

Experimental Windows AMD64 setup
================================

64-bit Windows reports its architecture as ``AMD64``. PicoChess therefore
looks for the local engine catalog in ``engines/AMD64``. Windows users must
supply a native Windows UCI engine, such as a Windows Stockfish executable.

For a Stockfish test, create the following local, git-ignored files::

    engines/AMD64/stockfish.exe
    engines/AMD64/stockfish.exe.uci
    engines/AMD64/engines.ini

The section name in ``engines.ini`` must match the executable name. A minimal
catalog entry is::

    [stockfish.exe]
    name = Stockfish
    small = Stockf
    medium = Stockfis
    large = Stockfish
    elo = 3500

The sidecar name is the complete executable name plus ``.uci``. A minimal
level is::

    [Elo@2200]
    UCI_LimitStrength = true
    UCI_Elo = 2200

Use the engine for both normal play and PicoTutor in ``picochess.ini``::

    engine = engines\AMD64\stockfish.exe
    engine-level = Elo@2200
    tutor-engine = engines\AMD64\stockfish.exe
    board-type = noeboard
    web-server = 8080
    theme = dark

After installing Python, create the virtual environment, install the
dependencies, and start PicoChess from PowerShell in the repository root::

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    .\.venv\Scripts\python.exe picochess.py

Then open ``http://localhost:8080``. This experimental path targets web-only
play against a native engine. PGN upload authentication, host updates,
Wi-Fi/Bluetooth setup, shutdown, and reboot remain Linux-only integrations.

Experimental macOS arm64 setup
==============================

Apple-silicon Macs report their architecture as ``arm64``. PicoChess therefore
looks for the local engine catalog in ``engines/arm64``. macOS users must supply
a native macOS UCI engine; Linux ``aarch64`` executables are not compatible.

For a Stockfish test, create the following local, git-ignored files::

    engines/arm64/stockfish
    engines/arm64/stockfish.uci
    engines/arm64/engines.ini

The section name in ``engines.ini`` must match the executable name, for example
``[stockfish]``. A minimal catalog entry is::

    [stockfish]
    name = Stockfish
    small = Stockf
    medium = Stockfis
    large = Stockfish
    elo = 3500

The sidecar name is the executable name plus ``.uci``. A minimal level is::

    [Elo@2200]
    UCI_LimitStrength = true
    UCI_Elo = 2200

Make the engine executable with ``chmod +x engines/arm64/stockfish`` and select
that same path for both ``engine`` and ``tutor-engine`` in ``picochess.ini``.
Create the Python environment and start PicoChess from the repository root::

    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
    .venv/bin/python picochess.py

This experimental path targets web-only play against a native engine. PGN
upload authentication, host updates, Wi-Fi/Bluetooth setup, shutdown, and reboot
remain Linux-only integrations.
