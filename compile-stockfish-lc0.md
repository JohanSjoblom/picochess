# Compile current Stockfish and Lc0 for PicoChess

This is an AI-assisted update procedure for [issue #580](https://github.com/JohanSjoblom/picochess/issues/580). Give the prompt below to an AI assistant that can use a terminal on the **machine that runs PicoChess**. It should build from the latest stable upstream releases and install the selected engine executables. It may add missing shared Lc0 weights and create or update the Stockfish, Lc0, and Maia `.uci` level files as described below. Preserve `engines.ini`, `picochess.ini`, existing weights, and unrelated engine files.

Before giving the prompt to the assistant, save any game you want to keep and stop PicoChess. For a Linux service installation, run `sudo systemctl stop picochess`. Stop any manually started PicoChess instance too. On macOS or Windows, close PicoChess. Keep it stopped until the assistant reports that both installed executables passed their checks.

> **Prompt for the assistant:** Read this whole file and the repository's `AGENTS.md`. On this machine, update the installed NNUE Stockfish and Lc0 executables from their latest stable official source releases. First inspect the OS, CPU, current engine paths, catalog entries, level files, available disk space, and running PicoChess processes. Verify PicoChess is stopped before replacing either executable; if it is running, tell me to stop it and wait. Do not stop or start PicoChess yourself. Ask me one question before changing Lc0/Maia levels: should `PicoNode` use (1) low limits of about 2 nodes, (2) 5000 nodes, or (3) no node limit? Apply my answer consistently to every installed Lc0-backed `.uci` file listed below. Clone or update the official source repositories under `~/pico-engine-compiles/stockfish` and `~/pico-engine-compiles/lc0`. Use the release tags shown on each upstream `/releases/latest` page, not a hard-coded version or the development branch. Build natively for this machine, verify UCI startup and a short search, and verify that Stockfish runs without external `.nnue` files. Add any missing shared Lc0 weights from the PicoChess release archive, preserving existing files. Back up each existing executable and any `.uci` file you change, then install the verified executables at their exact installed paths. Create or update the matching NNUE Stockfish `.uci` file with supported `UCI_Elo` levels, and the matching Lc0/Maia `.uci` files with the chosen node policy. Preserve installed executable names, catalog entries, unrelated settings, and other engines. Do not stop after compiling: the task is complete only when both installed executables and their selected Stockfish Elo and Lc0/Maia levels pass checks from the installed paths. Do not install a failed build; restore backups if an installed check fails. Report the source tags and commits, build options, installed paths, weight files, selected node policy, checks, and any limitations.

## Sources and release selection

| Engine | Official source | Latest stable release | Upstream build instructions |
| --- | --- | --- | --- |
| Stockfish | [official-stockfish/Stockfish](https://github.com/official-stockfish/Stockfish) | [Stockfish releases/latest](https://github.com/official-stockfish/Stockfish/releases/latest) | [Compiling from source](https://github.com/official-stockfish/Stockfish/wiki/Compiling-from-source) |
| Lc0 | [LeelaChessZero/lc0](https://github.com/LeelaChessZero/lc0) | [Lc0 releases/latest](https://github.com/LeelaChessZero/lc0/releases/latest) | [Lc0 README](https://github.com/LeelaChessZero/lc0#building-and-running-lc0) |

Check the release pages **when running the update**. Record each tag and commit. Clone into the user's home directory, outside the PicoChess checkout:

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

Do not infer an engine's version or NNUE behavior from its filename on another OS. The macOS starter installer, for example, uses the name `a-stockf` for an official modern Stockfish binary. macOS and Windows do not need a separate Stockfish 16 Tutor engine. Identify their actual NNUE executable and matching `.uci` file from the installed catalog before replacing anything. Users with more CPU may also choose that NNUE engine for `tutor-engine`, but this workflow must not change `picochess.ini` automatically.

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

The archive has no enclosing parent folder. Use the local PicoChess checkout path in each `WeightsFile` value; do not copy `/opt/picochess` paths blindly to a Mac or Windows installation.

## Native build: Raspberry Pi aarch64 and Debian x86_64

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

Stockfish uses its embedded NNUE networks at every strength. Users select a playing strength with `UCI_LimitStrength = true` and a supported `UCI_Elo` value. It does **not** need Lc0-style `WeightsFile` entries. For current Linux packs, work only on `engines/<arch>/NNUE/StockfishNN.uci`; use that file itself as the level-layout example. On macOS or Windows, use the sidecar matching the actual installed NNUE executable. Never copy the Pi's `Use NNUE = false` setting into an NNUE engine's sidecar.

Ask the new Stockfish executable for its `UCI_Elo` minimum and maximum with `uci` before writing levels; those bounds can change between releases. The Stockfish 19 build tested here reports 1320–3190. Back up an existing sidecar, keep its level names and unrelated settings, and retain useful Elo choices within the engine's supported range. A new file can start like this:

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

Use the installed files under `engines/x86_64/` or `engines/aarch64/` as examples when available. Each level file must have the **same full filename as its executable plus `.uci`**: for example `lc0v0321.uci`, `maia3.uci`, and `maiav0321.uci`; on Windows an executable ending in `.exe` needs a sidecar ending in `.exe.uci`. These entries may use one Lc0 binary under several names. On Linux and macOS the aliases can be symlinks to the Lc0 executable, as in the current Linux packs; on Windows use a native executable copy if symlinks are unavailable. Keep any existing `engines.ini` entry and its executable name. If a desired alias has no catalog entry, adding it to the catalog is a separate setup step; do not create an orphan `.uci` file and claim it is selectable.

Back up an existing `.uci` file before editing it. Keep its level section names, `WeightsFile` choices, and unrelated options. For a missing file, create the levels from these mappings, substituting the **absolute path on this machine** for `<weights>`:

| Sidecar | Default `WeightsFile` | Level sections and `WeightsFile` overrides |
| --- | --- | --- |
| `lc0v0321.uci` | `<weights>/792013-192x15.txt` | Gyal levels use `meangirl-8.pb.gz`, `badgyal-8.pb.gz`, `goodgyal-7.pb.gz`, `evilgyal-6.pb.gz`, and `tinygyal-8.pb.gz`. Standard one to four core levels use the default weight. |
| `classic.uci` | `<weights>/classic1.pb.gz` | Classic 1 uses `classic1.pb.gz`; Classic 2 levels use `classic2.pb.gz`. |
| `elitev2.uci` | `<weights>/elite_v2.pb.gz` | Existing levels use this same weight with different thread counts. |
| `maia3.uci` | `<weights>/maia3.pb.gz` | One or more Maia 3 levels may vary `Threads`; they use the same weight. |
| `maiav0321.uci` | `<weights>/maia-1100.pb.gz` | `Elo@1100` through `Elo@1900` in steps of 100, plus `Elo@2200` and `Elo@2500`, each point to their matching `maia-<elo>.pb.gz`. These labels select networks; they are not the Lc0 `UCI_LimitStrength` option. |

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

Before writing any of these files, ask **one question**: “For Lc0 and Maia, do you want low `PicoNode` limits (2 nodes), a medium limit (5000 nodes), or no `PicoNode` limit?” Apply the answer to every installed sidecar in the table consistently:

| Choice | `.uci` action |
| --- | --- |
| Low | Put `PicoNode = 2` in `[DEFAULT]` and remove per-level `PicoNode` overrides, so every level uses 2. |
| Medium | Put `PicoNode = 5000` in `[DEFAULT]` and remove per-level `PicoNode` overrides, so every level uses 5000. |
| No limit | Remove `PicoNode` from `[DEFAULT]` **and every level section**. Do not write `PicoNode = 0`. |

`PicoNode` is a PicoChess search limit, not an Lc0 UCI option. A positive value in a level overrides the normal node setting for that search. With the key absent, normal PicoChess time controls apply; a separate positive `node` setting in `picochess.ini` can still impose a node limit. Do not change that global setting without asking. Keep existing section names even if an old name mentions a tiny node count, so saved level selections continue to work; mention any misleading label in the report. Strength labels tied to tiny search limits may no longer describe the engine's actual strength when those limits are raised or removed.

## Verify, back up, and install

1. Test each **new** binary before installing it. Check that `uci` returns `uciok`, `isready` returns `readyok`, and `position startpos` plus `go depth 2` returns `bestmove`. Copy the Stockfish binary into a clean temporary directory without `.nnue` files and run that copy there. For Lc0, pass an existing configured weight file using `setoption name WeightsFile value <path>` before `isready`, and check that its selected CPU backend initializes and searches.
2. Compare the new UCI options with the installed `.uci` files. A removed or renamed option can make existing levels fail; resolve that before installing. Verify Stockfish's `UCI_Elo` range and `UCI_LimitStrength` option. `PicoNode` and `Analysis` are PicoChess control values, not Lc0 UCI options. Check dynamic library dependencies on Linux with `ldd`, especially for Lc0's OpenBLAS library.
3. Verify that PicoChess is stopped, including any manually started instance. The user stops it before giving the prompt; if it is still running, ask the user to stop it and wait. Back up each old binary under `~/pico-engine-compiles/backups/` with a timestamp and its original relative path recorded. Do not overwrite an earlier backup.
4. Copy the verified binary to a temporary filename **in the same target directory**, preserve executable permission, then rename it to the exact existing filename. Do this for **both** Stockfish and Lc0, one engine at a time. Add missing weights, then write the NNUE Stockfish Elo levels and chosen Lc0/Maia `PicoNode` policy. If an installed check fails, restore that engine's binary and sidecar backups.
5. Check **both installed paths** with the same UCI smoke tests and report their version strings. Test at least one configured Stockfish Elo level, checking that it enables `UCI_LimitStrength` with the requested `UCI_Elo`. Test at least one configured level from each installed Lc0/Maia sidecar with its `WeightsFile`, and confirm the requested `PicoNode` policy in every relevant section. Compare the installed binaries with the verified builds, for example with SHA-256 hashes. Leave `engines.ini`, `picochess.ini`, existing weights, unrelated `.uci` files, and other engines unchanged.

After the assistant reports success, the user starts PicoChess again (`sudo systemctl start picochess` for a Linux service, or the usual manual startup command on macOS or Windows) and confirms each engine can be selected and make a move.

Do not run `build/engines.py` for an executable-only update: it regenerates menu files. A later `update-engines.py` package update can replace same-name local builds, so retain the source tag/commit and backup for rebuilding.

## macOS and Windows follow-up

The source selection, isolated home-directory clones, existing-name replacement, backups, and UCI checks apply on all platforms. Build commands and runtime dependencies differ:

- On macOS, use the native compiler and the upstream Stockfish Makefile. Lc0's build requires Meson/Ninja and a suitable backend; review its current macOS instructions and test the resulting `lc0` on the target Mac. Use `engines/arm64` or `engines/mac_x86_64` as above. Linux binaries cannot be copied to a Mac.
- On Windows AMD64, use the upstream Windows build instructions and a native C++ toolchain (for example MSYS2/MinGW for Stockfish and the supported Visual Studio/Meson setup for Lc0). Install native `.exe` files under `engines/AMD64` using the **existing** catalog filenames, test their runtime DLL dependencies, and preserve the matching `.exe.uci` files. Linux binaries cannot be copied to Windows.

These platform paths are documented here, but the exact macOS and Windows build commands still need testing on those systems. Do not claim a platform is verified until its native binaries pass the same UCI and PicoChess checks.
