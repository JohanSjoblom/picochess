# PicoChess for macOS (control panel app)

`PicoChess.MacControlPanel` builds **PicoChess.app**, an experimental control panel for running
PicoChess on Apple-silicon and Intel Macs without a terminal. It is written in C# with
[Avalonia](https://avaloniaui.net/) on .NET 10. It is developed in parallel with the Windows
control panel in `win/` and shares no code with it.

## What the app does

When no PicoChess checkout is found, the app shows an **Install** section:

1. Choose a folder (default `~/PicoChess`) and whether to download books, opening data, and
   games data.
2. The app checks for Git and clones the `471-port-to-windows` branch. If Git is missing, macOS
   offers to install the Command Line Tools; accept, then click Install again.
3. It runs `install-picochess-mac.sh` and shows its output. The script needs a native CPython
   3.11-3.13 from [python.org](https://www.python.org/downloads/macos/) or Homebrew, and reports
   when none is found. The app does not install Python.

With a checkout, the app is a control panel:

- **Start** runs `start-picochess-mac.sh`, which starts `venv/bin/python picochess.py` and the
  optional Scid games helper.
- **Open in browser** opens `http://localhost:<port>/`, with the port read from `web-server` in
  `picochess.ini` (default 8080).
- **Stop** sends SIGINT to the PicoChess processes, like Ctrl+C in Terminal, so PicoChess runs
  its normal shutdown. Anything still running after 20 seconds is killed.
- **Upgrade** runs `install-picochess-mac.sh --update-repo` (a fast-forward-only `git pull` on a
  clean checkout). It is only enabled while PicoChess is stopped.

Closing the window or quitting with Cmd+Q while PicoChess runs offers to stop it first, because
PicoChess writes its output to the app.

The PicoChess folder is found from `--repo <folder>`, `PICOCHESS_HOME`, the folder last chosen
with **Change folder...** (saved in `~/Library/Application Support/PicoChess`), and finally
`~/PicoChess`.

No engine is installed. Add a native macOS engine and `picochess.ini` as described in
`docs/mac-install.md` before clicking Start.

An app started from Finder does not inherit your shell's `PATH`. The app adds `/opt/homebrew/bin`,
`/usr/local/bin`, and the python.org framework folders so the install script finds the same
Python as Terminal does.

## Building

Build on a Mac with the [.NET 10 SDK](https://dotnet.microsoft.com/download/dotnet/10.0):

```bash
bash mac/build-dist-mac.sh
```

This writes `PicoChess-mac-arm64.zip` and `PicoChess-mac-x64.zip`, each with a `.sha256` file,
to `sdist` at the repository root. `sdist` is ignored by Git; it only collects files to upload to
a GitHub release. Pass `--output-dir` to build somewhere else. The script must run on macOS
because the app bundle is signed with `codesign`.

For development, the project also builds and runs on Windows or Linux, which is useful for
checking the layout. Start, Stop, and Install only work on macOS.

```bash
dotnet run --project mac/PicoChess.MacControlPanel
```

## First launch (Gatekeeper)

The app is signed ad hoc but not notarized by Apple, so macOS blocks it the first time:

1. Unzip it and move `PicoChess.app` to Applications.
2. Open it. macOS reports that it cannot verify the app. Click **Done**.
3. Open **System Settings > Privacy & Security**, scroll down, and click **Open Anyway** next to
   the PicoChess message. Confirm with your password.

Alternatively, run `xattr -dr com.apple.quarantine /Applications/PicoChess.app` in Terminal.
Removing this step for everyone requires an Apple Developer account for notarization.

## Limitations

- Experimental and not yet tested on a Mac.
- There are separate downloads for Apple silicon (`arm64`) and Intel (`x64`).
- No app icon, notarization, or automatic start at login.
