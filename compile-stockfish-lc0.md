# Update Stockfish and Lc0 for PicoChess

This is an AI-assisted update procedure for [issue #580](https://github.com/JohanSjoblom/picochess/issues/580). On Linux, first update the standard **large** engine resource pack. On both Debian x86_64 and Raspberry Pi aarch64, ask whether to compile current Stockfish NNUE and Lc0 from their stable upstream releases or keep the binaries from the refreshed pack. Apply the chosen Lc0/Maia node policy after the resource update either way, because packaged `.uci` files replace local edits. On Windows and macOS, update Stockfish from the official universal binary download used by the current installers; compiling it there is unnecessary. Lc0 installation on Windows and macOS still needs investigation in [issue #572](https://github.com/JohanSjoblom/picochess/issues/572). The shared Lc0 weights work on all platforms, but this guide's complete Lc0 build-and-install workflow is for Linux.

Before giving either prompt to the assistant, save any game you want to keep and stop PicoChess. For a Linux service installation, run `sudo systemctl stop picochess`. Stop any manually started PicoChess instance too. On macOS or Windows, close PicoChess. Keep it stopped until the assistant reports that the installed executables passed their checks.

> **Linux prompt for the assistant:** Read this whole file and the repository's `AGENTS.md`. On this Linux machine, refresh the standard **large** PicoChess engine resource pack. On Debian x86_64 or Raspberry Pi aarch64, ask me before the update whether to compile the latest stable Stockfish NNUE and Lc0 afterward or keep the packaged binaries. Apply my Lc0/Maia node policy either way. Inspect the OS, CPU, installed engine paths and catalog, available disk space, and running PicoChess processes first. Verify PicoChess is stopped; if it is running, tell me to stop it and wait. Do not stop or start PicoChess yourself. Run `./update-engines.py large --dry-run` and then `./update-engines.py large` as the normal install user, without `sudo`. Stop and report any updater failure; retain its rollback backup. Do not select `small` unless I explicitly ask for a quick test installation. Inspect the refreshed engine catalog and `.uci` files before any build.
>
> Ask me one question before changing Lc0/Maia levels: should `PicoNode` use (1) low limits of about 2 nodes, (2) 5000 nodes, or (3) no node limit? Apply my answer consistently to installed Lc0-backed `.uci` files, including locally added profiles, while preserving their other settings. If building, clone or update the official source repositories under `~/pico-engine-compiles/stockfish` and `~/pico-engine-compiles/lc0`. Use the release tags shown on each upstream `/releases/latest` page when building, not a hard-coded version or the development branch. If building, compile natively and back up and replace only the verified binaries. If keeping the packaged binaries, skip the clones, build dependencies, compilation, and binary replacement. In either case, verify both installed engines with UCI startup and a short search, and verify that Stockfish runs without external `.nnue` files. Add any missing shared Lc0 weights from the PicoChess release archive, preserving existing files. Back up any `.uci` file you change and each executable you replace. Check the matching NNUE Stockfish `.uci` file for supported `UCI_Elo` levels, updating it if needed, and update the matching Lc0/Maia `.uci` files with the chosen node policy. Preserve installed executable names, catalog entries, unrelated settings, and other engines. Do not stop after the resource update or compilation: the task is complete only when both installed executables and their selected Stockfish Elo and Lc0/Maia levels pass checks from the installed paths. Do not install a failed build; restore backups if an installed check fails. Report the updater backup, installed paths and versions, weight files, selected node policy, checks, and any limitations. If built, also report source tags and commits and build options.

## Linux update order

Run the [engine updater](install-engines.md#updating-without-losing-roms-or-retro-menu-selections) **before** compiling. The normal choice is `large`, which refreshes the x86_64 or aarch64 engine pack and the MAME and Rodent resources. `small` is only for an explicitly requested quick test installation. The updater requires an explicit `large` or `small` argument, so use `large` rather than omitting it. Allow disk space for the downloads, staged resources, and dated backup. Run it without `sudo` after stopping PicoChess:

```sh
cd /opt/picochess                 # or the actual PicoChess checkout
./update-engines.py large --dry-run
./update-engines.py large
```

Only continue if the updater reports success. Keep the rollback backup path it prints. The resource pack may replace `NNUE/StockfishNN`, `lc0v0321`, and their packaged `.uci` files. After the update, build and replace those two executables only if the user chose to compile. In either case, inspect the installed Stockfish Elo levels and apply the chosen `PicoNode` policy to the refreshed Lc0 sidecars. Existing local engine profiles and resources remain governed by the updater's preservation rules; inspect them before editing their level files.

On Debian or Raspberry Pi, ask **before running the updater**: “After the large resource update, should I compile the latest Stockfish NNUE and Lc0 on this machine, or keep the binaries supplied by the pack?” Both choices run the same large updater and apply the selected Lc0/Maia node policy. The refreshed x86_64 pack currently includes Stockfish 19 and Lc0 0.32.1; check the installed versions on each machine because packaged versions may lag behind later upstream releases. If the user keeps them, skip source clones, build dependencies, compilation, and binary replacement; still check UCI startup, a short search, the embedded Stockfish NNUE networks, the installed Elo levels, weights, and the node policy. Report the packaged versions. Do not guess the user's choice from the available disk space or silently choose one if they have not answered.

## Sources and release selection

| Engine | Official source | Latest stable release | Upstream build instructions |
| --- | --- | --- | --- |
| Stockfish | [official-stockfish/Stockfish](https://github.com/official-stockfish/Stockfish) | [Stockfish releases/latest](https://github.com/official-stockfish/Stockfish/releases/latest) | [Compiling from source](https://github.com/official-stockfish/Stockfish/wiki/Compiling-from-source) |
| Lc0 | [LeelaChessZero/lc0](https://github.com/LeelaChessZero/lc0) | [Lc0 releases/latest](https://github.com/LeelaChessZero/lc0/releases/latest) | [Lc0 README](https://github.com/LeelaChessZero/lc0#building-and-running-lc0) |

For the **Linux source-build workflow**, check the release pages when running the update and record each tag and commit. Clone into the user's home directory, outside the PicoChess checkout:

```sh
mkdir -p "$HOME/pico-engine-compiles"
git clone https://github.com/official-stockfish/Stockfish.git "$HOME/pico-engine-compiles/stockfish"
git clone https://github.com/LeelaChessZero/lc0.git "$HOME/pico-engine-compiles/lc0"
```

If a clone already exists, use `git -C <directory> fetch --tags --prune` instead of cloning again. Verify its `origin` points to the official repository. Check out the selected release tag in detached state; do not merge it into a local branch. For Lc0, run `git submodule update --init --recursive` after checkout. Inspect the checked-out release's build instructions because upstream flags and dependencies can change.

## Choose the installed executables

Find the PicoChess checkout on the local machine. The examples below assume `/opt/picochess`; substitute the real path if different. The engine directory is OS-specific:

| Machine | Engine directory |
| --- | --- |
| Raspberry Pi OS / Debian Linux aarch64 | `engines/aarch64/` |
| Debian Linux x86_64 | `engines/x86_64/` |
| macOS Apple Silicon | `engines/arm64/` |
| macOS Intel | `engines/mac_x86_64/` |
| Windows AMD64 | `engines/AMD64/` |

Use the actual catalog and `picochess.ini` to identify the installed executable names. In the current Linux engine packs, the playing Stockfish NNUE entry is `NNUE/StockfishNN` and the Lc0 entry is `lc0v0321`. Keep those filenames when replacing the binaries.

If this installation has no entry for one of the engines, report that instead of guessing a new destination. Adding an engine requires a separate catalog and level-file setup; this guide covers existing entries only.

On Raspberry Pi/Linux engine packs, `a-stockf` is deliberately kept at Stockfish 16 with NNUE disabled. It is a lighter PicoTutor engine for a small Pi. **Do not rebuild, replace, or edit `a-stockf` or `a-stockf.uci` in this workflow.** The new compiled Stockfish belongs at `NNUE/StockfishNN`, with Elo levels in `NNUE/StockfishNN.uci`. Leave the Pi's `tutor-engine` setting alone.

Do not infer an engine's version or NNUE behavior from its filename on another OS. The **current Windows installer** uses the [v4.3.5 AMD64 engine ZIP](https://github.com/JohanSjoblom/picochess/releases/download/v4.3.5/picochess-amd64-engines-small-v4.3.5.zip). It contains one executable, `a-stockf.exe`, plus `engines.ini` and `a-stockf.exe.uci`. The executable is byte-for-byte identical to the [official Stockfish 19 x86-64 universal build](https://github.com/official-stockfish/Stockfish/releases/download/sf_19/stockfish-windows-x86-64-universal.zip). It is the NNUE Stockfish playing and Tutor engine in the Windows starter setup; there is no separate Stockfish 16 there. Keep `a-stockf.exe` as the installed name when refreshing it from a newer official universal download.

The **current macOS installer** downloads the [official Stockfish macOS universal build](https://github.com/official-stockfish/Stockfish/releases/download/sf_19/stockfish-macos-universal.tar.gz) directly and installs it as `a-stockf`. Its [v4.3.5 engine metadata archive](https://github.com/JohanSjoblom/picochess/releases/download/v4.3.5/picochess-mac-engines-small-v4.3.5.tar.gz) contains only `engines.ini` and `a-stockf.uci`, not an engine binary. Here too, `a-stockf` is the modern NNUE playing and Tutor engine, not the Pi's classic Stockfish 16. Identify the installed executable and matching sidecar before replacing them. Windows and macOS do not need a separate Stockfish 16 Tutor engine. The installed NNUE binary can also serve as Tutor; this workflow must not change `picochess.ini` automatically.

Lc0 is different from Stockfish: its neural network weights are **not** embedded in the executable. The shared weight files live in `engines/lc0_weights/`, outside the architecture-specific engine folder. Confirm the files selected by the `.uci` levels exist before testing Lc0.

## Shared Lc0 weights

The [PicoChess v4.4.1 `lc0_weights.tar.gz` release asset](https://github.com/JohanSjoblom/picochess/releases/download/v4.4.1/lc0_weights.tar.gz) contains the Lc0 and Maia networks used by the current engine packs. The same archive works on Linux, macOS, and Windows; the weights are independent of CPU architecture. It includes `792013-192x15.txt`, the Gyal networks, `maia3.pb.gz`, Maia 1100–1900 in steps of 100, Maia 2200, and Maia 2500. These are Lc0 weights, separate from Stockfish's embedded NNUE networks.

First inspect `engines/lc0_weights/` and the `WeightsFile` entries in the installed `.uci` files. If a needed file is missing, download the archive into `~/pico-engine-compiles/`, inspect its contents, and extract into a staging directory there. Copy **only missing** network files into `engines/lc0_weights/`; do not replace existing networks or extract the archive over that live directory. Check that every chosen `WeightsFile` points to a real file. Allow room for the roughly 620 MB download plus extraction. On Windows, use PowerShell's download command and `tar` or another archive tool; use the same archive and preserve the same filenames.

On Linux or macOS, a download and staging example is:

```sh
mkdir -p "$HOME/pico-engine-compiles/lc0-weights-stage"
curl -fL --retry 3 -o "$HOME/pico-engine-compiles/lc0_weights.tar.gz" \
  https://github.com/JohanSjoblom/picochess/releases/download/v4.4.1/lc0_weights.tar.gz
tar -tzf "$HOME/pico-engine-compiles/lc0_weights.tar.gz"
tar -xzf "$HOME/pico-engine-compiles/lc0_weights.tar.gz" \
  -C "$HOME/pico-engine-compiles/lc0-weights-stage"
```

The archive has no enclosing parent folder. Use the local PicoChess checkout path in each `WeightsFile` value; do not copy `/opt/picochess` paths blindly to a Mac or Windows installation. Downloading these weights alone does not make Lc0 available on Windows or macOS; those platforms still need a validated executable and backend setup.

## Native build: Raspberry Pi aarch64 and Debian x86_64

Use this section on Debian or Raspberry Pi only when the user chose to compile after the resource update.

On Debian or Raspberry Pi OS, install missing build dependencies using the system package manager. At minimum check for Git, a C++20 compiler, Make, Python, Meson, Ninja, OpenBLAS development files, Protobuf development files/compiler, and zlib development files. On Debian these normally come from `git build-essential python3 meson ninja-build libopenblas-dev libprotobuf-dev protobuf-compiler zlib1g-dev`. Lc0's Meson build may fetch additional pinned subprojects. Check available disk space and RAM before building on a Pi, and use modest parallelism there.

For Stockfish, run `make help` in the checked-out `src/` directory and choose an `ARCH` supported by that release and CPU. `ARCH=armv8` is a safe baseline for 64-bit Raspberry Pi; use `armv8-dotprod` only if the target CPU supports it. For local Debian x86_64, `ARCH=x86-64` is portable, while a supported newer architecture can be faster on the same CPU. Example:

```sh
cd "$HOME/pico-engine-compiles/stockfish/src"
make -j2 build ARCH=armv8          # aarch64 Pi; use ARCH=x86-64 on Debian x86_64
```

The Stockfish `build` target obtains its release's default NNUE network files and embeds them in `src/stockfish`. A source checkout needs the networks during compilation; the **installed executable** must work without sidecar `.nnue` files. Check the build log for successful network validation. Do not copy `.nnue` files into PicoChess as a workaround for a failed or unembedded build.

For a Linux CPU-only Lc0 build, use the release's `build.sh` with OpenBLAS. Keep the build local; do not set `INSTALL_PREFIX`, which would also install outside the source tree:

```sh
cd "$HOME/pico-engine-compiles/lc0"
git submodule update --init --recursive
./build.sh -Dblas=true -Dopenblas=true -Dcudnn=false -Dplain_cuda=false -Donnx=false -Dgtest=false
```

The expected output is `build/release/lc0`. An accelerator build needs the matching hardware, libraries, backend selection, and a separate test; do not silently replace the CPU build with an untested GPU configuration. On a memory-limited Pi, use `meson setup build/release --buildtype release` with the same `-D` options, then `meson compile -C build/release -j2` to limit parallel compilation. Check the release's `build.sh` for any additional setup options first.

## Stockfish `.uci` Elo levels

Stockfish uses its embedded NNUE networks at every strength. Users select a playing strength with `UCI_LimitStrength = true` and a supported `UCI_Elo` value. It does **not** need Lc0-style `WeightsFile` entries. For current Linux packs, work only on `engines/<arch>/NNUE/StockfishNN.uci`; use that file itself as the level-layout example. In the current Windows and macOS starter setups, the resource metadata supplies `engines/AMD64/a-stockf.exe.uci` or `engines/<mac-arch>/a-stockf.uci` respectively. Keep these files and `engines.ini` when refreshing the executable. The present Windows ZIP has an obsolete `Use NNUE = false` line; Stockfish 19 has no such UCI option, and PicoChess filters unsupported options. The line does not disable its NNUE evaluation. It can be cleaned up in a future resource-metadata update, rather than requiring users to edit it when downloading a new binary.

Ask the new Stockfish executable for its `UCI_Elo` minimum and maximum with `uci` before writing or relying on levels; those bounds can change between releases. The Stockfish 19 build tested here reports 1320–3190. On Linux, back up an existing sidecar, keep its level names and unrelated settings, and retain useful Elo choices within the engine's supported range. A new Linux file can start like this:

```ini
[DEFAULT]
Threads = 1

[Elo@1600]
UCI_LimitStrength = true
UCI_Elo = 1600

[Elo@2200]
UCI_LimitStrength = true
UCI_Elo = 2200

[Full]
UCI_LimitStrength = false
```

Add the levels users want to choose, such as the current pack's 100-point steps from 1400 to 3100. A `Full` level disables the Elo cap; its `UCI_Elo` value has no effect. The existing `StockfishNN.uci` calls its full-strength level `Elo@3190` while setting `UCI_LimitStrength = false`. Keep that name if an existing selection depends on it, but report that it means full strength rather than an Elo-capped 3190. Do not add an unsupported Elo value or change the user's selected `engine-level` in `picochess.ini`.

## Lc0 and Maia `.uci` levels

For the Linux update, use the installed files under `engines/x86_64/` or `engines/aarch64/` as examples when available. Each level file must have the **same full filename as its executable plus `.uci`**: for example `lc0v0321.uci`, `maia3.uci`, and `maiav0321.uci`. These entries may use one Lc0 binary under several names, with aliases symlinked to it in the current Linux packs. Keep any existing `engines.ini` entry and its executable name. If a desired alias has no catalog entry, adding it to the catalog is a separate setup step; do not create an orphan `.uci` file and claim it is selectable.

Back up an existing `.uci` file before editing it. Keep its level section names, `WeightsFile` choices, and unrelated options. For a missing file, create the levels from these mappings, substituting the **absolute path on this machine** for `<weights>`:

| Sidecar | Default `WeightsFile` | Level sections and `WeightsFile` overrides |
| --- | --- | --- |
| `lc0v0321.uci` | `<weights>/792013-192x15.txt` | Gyal levels use `meangirl-8.pb.gz`, `badgyal-8.pb.gz`, `goodgyal-7.pb.gz`, `evilgyal-6.pb.gz`, and `tinygyal-8.pb.gz`. Standard one to four core levels use the default weight. |
| `classic.uci` | `<weights>/classic1.pb.gz` | Classic 1 uses `classic1.pb.gz`; Classic 2 levels use `classic2.pb.gz`. |
| `elitev2.uci` | `<weights>/elite_v2.pb.gz` | Existing levels use this same weight with different thread counts. |
| `maia3.uci` | `<weights>/maia3.pb.gz` | One or more Maia 3 levels may vary `Threads`; they use the same weight. |
| `maiav0321.uci` | `<weights>/maia-1100.pb.gz` | `Elo@1100` through `Elo@1900` in steps of 100, plus `Elo@2200` and `Elo@2500`, each point to their matching `maia-<elo>.pb.gz`. These labels select networks; they are not the Lc0 `UCI_LimitStrength` option. |

Inspect the installed catalog for locally added Lc0-backed profiles too. For example, a local `b-lc0` entry may have its own `b-lc0.uci` with `PicoNode` limits. Apply the chosen policy to that sidecar if present, without replacing its separate executable or changing its other options.

A minimal level looks like this; add the other sections following the table and the installed examples:

```ini
[DEFAULT]
WeightsFile = <weights>/maia-1100.pb.gz
Threads = 1
UCI_ShowWDL = false
Analysis = false

[Elo@1100]
WeightsFile = <weights>/maia-1100.pb.gz

[Elo@1200]
WeightsFile = <weights>/maia-1200.pb.gz
```

Before writing any of these files, ask **one question**: “For Lc0 and Maia, do you want low `PicoNode` limits (2 nodes), a medium limit (5000 nodes), or no `PicoNode` limit?” Apply the answer consistently to every installed Lc0-backed sidecar, including locally added profiles:

| Choice | `.uci` action |
| --- | --- |
| Low | Put `PicoNode = 2` in `[DEFAULT]` and remove per-level `PicoNode` overrides, so every level uses 2. |
| Medium | Put `PicoNode = 5000` in `[DEFAULT]` and remove per-level `PicoNode` overrides, so every level uses 5000. |
| No limit | Remove `PicoNode` from `[DEFAULT]` **and every level section**. Do not write `PicoNode = 0`. |

`PicoNode` is a PicoChess search limit, not an Lc0 UCI option. A positive value in a level overrides the normal node setting for that search. With the key absent, normal PicoChess time controls apply; a separate positive `node` setting in `picochess.ini` can still impose a node limit. Do not change that global setting without asking. Keep existing section names even if an old name mentions a tiny node count, so saved level selections continue to work; mention any misleading label in the report. Strength labels tied to tiny search limits may no longer describe the engine's actual strength when those limits are raised or removed.

## Linux: verify, back up, and install

The steps below apply when building. If the user keeps the packaged binaries, skip steps 1–4. Instead, verify both installed engines with the UCI startup and short-search checks in step 5, confirm Stockfish uses embedded NNUE, check its installed Elo levels and every Lc0 weight path, then apply and verify the chosen `PicoNode` policy. There is no source-build hash comparison in that case.

1. Test each **new** binary before installing it. Check that `uci` returns `uciok`, `isready` returns `readyok`, and `position startpos` plus `go depth 2` returns `bestmove`. Copy the Stockfish binary into a clean temporary directory without `.nnue` files and run that copy there. For Lc0, pass an existing configured weight file using `setoption name WeightsFile value <path>` before `isready`, and check that its selected CPU backend initializes and searches.
2. Compare the new UCI options with the installed `.uci` files. A removed or renamed option can make existing levels fail; resolve that before installing. Verify Stockfish's `UCI_Elo` range and `UCI_LimitStrength` option. `PicoNode` and `Analysis` are PicoChess control values, not Lc0 UCI options. Check dynamic library dependencies on Linux with `ldd`, especially for Lc0's OpenBLAS library.
3. Verify that PicoChess is stopped, including any manually started instance. The user stops it before giving the prompt; if it is still running, ask the user to stop it and wait. Back up each old binary under `~/pico-engine-compiles/backups/` with a timestamp and its original relative path recorded. Do not overwrite an earlier backup.
4. Copy the verified binary to a temporary filename **in the same target directory**, preserve executable permission, then rename it to the exact existing filename. Do this for **both** Stockfish and Lc0, one engine at a time. Add missing weights, then write the NNUE Stockfish Elo levels and chosen Lc0/Maia `PicoNode` policy. If an installed check fails, restore that engine's binary and sidecar backups.
5. Check **both installed paths** with the same UCI smoke tests and report their version strings. Test at least one configured Stockfish Elo level, checking that it enables `UCI_LimitStrength` with the requested `UCI_Elo`. Test at least one configured level from each installed Lc0/Maia sidecar with its `WeightsFile`, and confirm the requested `PicoNode` policy in every relevant section. Compare the installed binaries with the verified builds, for example with SHA-256 hashes. Leave `engines.ini`, `picochess.ini`, existing weights, unrelated `.uci` files, and other engines unchanged.

After the assistant reports success, the user starts PicoChess again (`sudo systemctl start picochess` for a Linux service) and confirms each engine can be selected and make a move.

Do not run `build/engines.py` for an executable-only update: it regenerates menu files. A later `update-engines.py` package update can replace same-name local builds, so retain the source tag/commit and backup for rebuilding.

## Windows and macOS: refresh official Stockfish

The current Windows and macOS installers supply one NNUE Stockfish with Elo levels in resource-provided metadata. For an existing installation, use the [latest official Stockfish release](https://github.com/official-stockfish/Stockfish/releases/latest) rather than compiling. The release tag and asset names must be checked each time:

| Platform | Look for the official universal asset | Replace only this installed executable |
| --- | --- | --- |
| Windows AMD64 | `stockfish-windows-x86-64-universal.zip` | `engines/AMD64/a-stockf.exe` |
| macOS Apple Silicon | `stockfish-macos-universal.tar.gz` | `engines/arm64/a-stockf` |
| macOS Intel | `stockfish-macos-universal.tar.gz` | `engines/mac_x86_64/a-stockf` |

> **Windows/macOS prompt for the assistant:** Read this section and the repository's `AGENTS.md`. Update only the installed Stockfish executable from the latest stable official universal release for this OS and CPU. Check the actual catalog, `picochess.ini`, and installed file before proceeding. Verify that I have closed PicoChess; do not stop or start it yourself. Download and extract the official archive under my home directory, record its release tag and source URL, and test the extracted executable with `uci`, `isready`, and a short search. Confirm it uses embedded NNUE without adjacent `.nnue` files and that its `UCI_Elo` range supports the installed level file. Back up the old executable and replace it under the same filename, then repeat the UCI check from the installed path. Preserve `engines.ini`, the installer-supplied `.uci` file, `picochess.ini`, and all other resources. If the new executable is incompatible with those levels, restore the backup and report the mismatch. Do not install Lc0 as part of this prompt.

Do not rerun the Windows resource installer to refresh Stockfish: its current engine ZIP still contains Stockfish 19 and may replace a newer local build if resources are forced. The current macOS installer skips an existing native engine directory. Keep their resource-provided Elo `.uci` files and catalog in place; update those metadata archives in a separate maintenance change if a future Stockfish release requires different options. After the assistant reports success, start PicoChess normally and check that Stockfish can be selected and make a move.

Lc0 on Windows and macOS remains an investigation for [issue #572](https://github.com/JohanSjoblom/picochess/issues/572): select a suitable executable and backend, confirm its dependencies and weights, and test a real search on both platforms before adding an installation workflow here. The Linux Lc0 build commands above are not instructions for those systems.
