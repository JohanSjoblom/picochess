# Compile current Stockfish and Lc0 for PicoChess

This is an AI-assisted update procedure for [issue #580](https://github.com/JohanSjoblom/picochess/issues/580). Give the prompt below to an AI assistant that can use a terminal on the **machine that runs PicoChess**. It should build from the latest stable upstream releases and replace only the selected engine executables. It must leave `engines.ini`, `.uci` level files, `picochess.ini`, and `engines/lc0_weights/` alone.

Before giving the prompt to the assistant, save any game you want to keep and stop PicoChess. For a Linux service installation, run `sudo systemctl stop picochess`. Stop any manually started PicoChess instance too. On macOS or Windows, close PicoChess. Keep it stopped until the assistant reports that both installed executables passed their checks.

> **Prompt for the assistant:** Read this whole file and the repository's `AGENTS.md`. On this machine, update the installed NNUE Stockfish and Lc0 executables from their latest stable official source releases. First inspect the OS, CPU, current engine paths, catalog entries, level files, available disk space, and running PicoChess processes. Verify PicoChess is stopped before replacing either executable; if it is running, tell me to stop it and wait. Do not stop or start PicoChess yourself. Clone or update the official source repositories under `~/pico-engine-compiles/stockfish` and `~/pico-engine-compiles/lc0`. Use the release tags shown on each upstream `/releases/latest` page, not a hard-coded version or the development branch. Build natively for this machine, verify UCI startup and a short search, and verify that Stockfish runs without external `.nnue` files. Back up each existing executable, then replace it at its exact installed path. Preserve its installed filename and every other file in the engine folder. Do not stop after compiling: the task is complete only when both installed executables pass the UCI checks from their installed paths. Do not install a failed build; restore a backup if an installed check fails. Report the exact source tags and commits, build options, installed paths, checks, and any limitations.

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

Use the actual catalog and `picochess.ini` to identify the installed executable names. In the current Linux engine packs, the NNUE Stockfish entry is `NNUE/StockfishNN` and the Lc0 entry is `lc0v0321`. Keep those filenames when replacing the binaries.

If this installation has no entry for one of the engines, report that instead of guessing a new destination. Adding an engine requires a separate catalog and level-file setup; this guide covers existing entries only.

The `a-stockf` entry is the older **classic** Stockfish configuration and its `.uci` file disables NNUE. Do not replace it in this workflow. The NNUE entry has a separate `.uci` file and uses embedded networks by default. Do not change either `.uci` file merely to make a new binary start.

Lc0 is different from Stockfish: its neural network weights are **not** embedded in the executable. Keep the existing `WeightsFile` values and `engines/lc0_weights/` files. Confirm at least one configured weight exists, and test Lc0 using that weight. If there is no compatible weight, report that separately instead of changing settings as part of the executable update.

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

## Verify, back up, and install

1. Test each **new** binary before installing it. Check that `uci` returns `uciok`, `isready` returns `readyok`, and `position startpos` plus `go depth 2` returns `bestmove`. Copy the Stockfish binary into a clean temporary directory without `.nnue` files and run that copy there. For Lc0, pass an existing configured weight file using `setoption name WeightsFile value <path>` before `isready`, and check that its selected CPU backend initializes and searches.
2. Compare the new UCI options with the installed `.uci` file. A removed or renamed option can make existing levels fail; resolve that before installing. Check dynamic library dependencies on Linux with `ldd`, especially for Lc0's OpenBLAS library.
3. Verify that PicoChess is stopped, including any manually started instance. The user stops it before giving the prompt; if it is still running, ask the user to stop it and wait. Back up each old binary under `~/pico-engine-compiles/backups/` with a timestamp and its original relative path recorded. Do not overwrite an earlier backup.
4. Copy the verified binary to a temporary filename **in the same target directory**, preserve executable permission, then rename it to the exact existing filename. Do this for **both** Stockfish and Lc0, one engine at a time. If an installed check fails, restore that engine's backup.
5. Check **both installed paths** with the same UCI smoke tests and report their version strings. Compare the installed binaries with the verified builds, for example with SHA-256 hashes. Leave `engines.ini`, `.uci`, `picochess.ini`, network weights, and other engines unchanged. Record hashes of those files before and after if needed to verify this.

After the assistant reports success, the user starts PicoChess again (`sudo systemctl start picochess` for a Linux service, or the usual manual startup command on macOS or Windows) and confirms each engine can be selected and make a move.

Do not run `build/engines.py` for an executable-only update: it regenerates menu files. A later `update-engines.py` package update can replace same-name local builds, so retain the source tag/commit and backup for rebuilding.

## macOS and Windows follow-up

The source selection, isolated home-directory clones, existing-name replacement, backups, and UCI checks apply on all platforms. Build commands and runtime dependencies differ:

- On macOS, use the native compiler and the upstream Stockfish Makefile. Lc0's build requires Meson/Ninja and a suitable backend; review its current macOS instructions and test the resulting `lc0` on the target Mac. Use `engines/arm64` or `engines/mac_x86_64` as above. Linux binaries cannot be copied to a Mac.
- On Windows AMD64, use the upstream Windows build instructions and a native C++ toolchain (for example MSYS2/MinGW for Stockfish and the supported Visual Studio/Meson setup for Lc0). Install native `.exe` files under `engines/AMD64` using the **existing** catalog filenames, test their runtime DLL dependencies, and preserve the matching `.exe.uci` files. Linux binaries cannot be copied to Windows.

These platform paths are documented here, but the exact macOS and Windows build commands still need testing on those systems. Do not claim a platform is verified until its native binaries pass the same UCI and PicoChess checks.
