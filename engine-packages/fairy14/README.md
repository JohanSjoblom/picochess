# Fairy-Stockfish 14 profiles

These managed files split the five supported chess variants into logical
profiles while sharing the executable named `fairy`.

The values from 1000 through 3000, normally in steps of 250, are practical
`UCI_Elo` strength settings. The legacy 2850 setting is retained so saved
levels continue to resolve. These are not calibrated ratings across chess
variants, because no common variant rating pool or opponent set exists.

The Git clone keeps these inert templates outside `engines/<arch>`.
`install-engines.sh small` and `install-engines.sh lite` call
`install-engine-catalogs.sh`, which copies missing files into an architecture
engine directory only when the Fairy executable is present. It never replaces
an existing catalog or sidecar. Engine release tarballs should include the same
six files at their archive root.
