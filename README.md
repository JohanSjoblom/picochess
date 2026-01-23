PicoChess
=========
Picochess transforms a Raspberry Pi or a Linux based computer into a chess computer. You can use many different chess engines with Picochess. Picochess connects an electronic chess board with the chess engines you chose to play against.
Installation includes Stockfish and Leela Chess Zero (LC0) as examples. There are several LC0 personalities you can play against. If you want to add more engines you can have a look in the Picochess Google group. See the "How to add more engines" section below. Many retro and mame engines like Mephisto, TuroChamp etc work. The community is working hard to make it possible to run all old chess engines.

Features
========
- Play via Web Browser. Enjoy chess directly from your browser. You do need an electronic chess board.
- Electronic Chess Board support for an authentic playing experience. Compatible with DGT e-board, Certabo, Chesslink, Chessnut, and Ichessone. Note that no guarantees can be given that it will work with all of these boards, but the community has worked hard to maintain this possibility. I currently use a DGT e-board and a DGT Pi 3000 myself.
- DGT Clock Compatibility. Runs on the DGT Pi 3000 electronic clock which becomes an all-in one chess computer.
- Responsive web layout scales well on large desktop screens.

About This Fork
===============
This fork of Picochess focuses on:
- Upgrading dependencies – Uses the latest Python with the latest chess and Tornado libraries.
- Ability to run both on Raspberry Pi and Linux computers.
- Asynchronous Architecture – Replaces threads with an async-based architecture for improved performance and scalability.
- Keep the main program picochess.py as it was, rewrites are mainly focusing on engine.py and picotutor.py to use the latest python chess library, but as the new library is quite different some changes are visible in picochess.py as well.
- Wayland support with optional native audio backend (no X11/PulseAudio requirement).
- Engines, books, and games database are distributed as external resource packs.
- The obooksrv dataset is now read directly in `server.py` without an external service.
- Built-in replay mode, while preserving the original PGN Replay engine.
- Refreshed web client experience.

Requirements
------------

- Raspberry Pi 3, Pi 4, Pi 5 (aarch64) or a Linux computer (x86_64)
- RaspiOS Bookworm 64bit or the new Trixie 13, released in 2025. Wayland is supported. If you don't want to switch to PulseAudio, set `audio_backend = native` in `picochess.ini`. You might also need to make sure that the PulseAudio packages are installed like pulseaudio, pulseaudio-utils, libpulse0, or even libasound2-plugins.

Quick Installation
------------------
Get the installation script, give it execution rights, and run it as sudo. It will clone the repository to /opt/picochess and install the needed services. It also downloads a basic set of engines (Stockfish 17.1 and LC0 0.32) plus LC0 weights; downloading the weights can take a while.

- `wget -L https://raw.github.com/JohanSjoblom/Picochess/master/install-picochess.sh`
- `chmod +x install-picochess.sh`
- `sudo ./install-picochess.sh`
- Reboot; Picochess should start as a service.

The script installs the following services in `/etc/systemd/system/`:
- picochess (main service)
- picochess-update (stay updated)
- gamesdb (games window on web page)

`install-picochess.sh` flags:
- `pico` skips system update (useful on existing systems).
- `small` (default) or `lite` selects the engine pack to install. On reruns, an explicit `small`/`lite` triggers an engine backup + reinstall for the current architecture; otherwise engines are left untouched if already present.
- `noengines` skips installing engines (used internally during code-only updates).
- `dgt3000` or `DGT3000` installs the DGT Pi 3000 clock service; do not run `install-dgtpi-clock.sh` separately.

You can safely rerun `install-picochess.sh` any time. It can fix permissions, refresh services, and is a good first troubleshooting step if something isn’t working.

How to stay updated
-------------------
You can manually update to latest version from within the program. Go to the System, Power menu and select Restart and Update Picochess. If you really want to stay updated you can edit your picochess.ini file and uncomment the line enable-update = True. In this case it will update the code every time you reboot. It will not run a system update at boot, as that takes quite some time. It will only update the picochess code.

How to open the web page and play?
----------------------------------
Use `localhost` in your browser to open the web page. If you are running on another machine replace `localhost` with the IP address of your Pi. If you use a firewall, ensure the Picochess web port is allowed.

How to analyse a PGN game using Picotutor?
------------------------------------------
You can upload a PGN game. Go to `localhost/upload` and choose a PGN file to upload to Picochess. It will ask you for your pi user password. It will load the PGN game into the starting position. Now you can step through the PGN game in Picochess by using the play-pause button. Finally save the game from the menu if you want to store the evaluations. Uploads are written to `/opt/picochess/games/upload`. Games are saved in `/opt/picochess/games`.
To upload a game from your mobile phone to Picochess you need to know the IP address of your Pi computer and replace `localhost` above with the IP address. You also need to be on the same network as your Pi computer.
If you want to load the last game choose "PGN Replay" mode. For more analysis modes, continue reading below.

How to enter and analyse a game using Picotutor?
------------------------------------------------
You can use the menu to go to Mode and switch to "Hint On", "Eval.Score", "Observe" or "Analysis" mode. Now you make moves for both sides. Use the plus and minus button to check the depth-score and hit move. When you are done analysing: use the Game Setup from the menu and chose Declare game ending. Your game with picotutor evaluations are saved in /opt/picochess/games/last_game.pgn.

Additional scripts you might find useful:
-----------------------------------------
- `connect-dgt-on-debian.sh`, use this on Linux laptops to be able to connect to a Bluetooth DGT e-board (edit the script to add your eboard MAC address).
- `Fix_bluetooth.sh`, BLE reset and compatibility setup for Raspberry Pi OS Trixie (run with sudo).
- `check-bluetooth.sh`, collect Bluetooth diagnostics into `bluetooth.txt` for troubleshooting.

How to add more engines?
------------------------
Picochess ships with engine resource packs. The installer runs install-engines.sh once after cloning and installs the default small pack (includes Stockfish and LC0). You can re-run install-engines.sh anytime; it only downloads folders that are missing.

Please note that you should choose either the small or the lite package, not both. To move from small to lite, command #1 below moves your current engines to backup. Command #2 then downloads the lite package. Alternatively, you can re-run `install-picochess.sh lite` and it will perform the backup and reinstall automatically for the current architecture.

To switch from small to the larger lite pack:
1) Run `./move-engines-to-backup.sh` to move your current engines out of `/opt/picochess/engines`. This prepares a clean install.
2) Run `./install-engines.sh lite`. The script detects your architecture (aarch64 on Raspberry Pi, x86_64 on Linux) and downloads the matching lite files.

If you prefer, you can delete the architecture folder under `/opt/picochess/engines` instead of using the backup script, then run `./install-engines.sh lite`. The script requires an argument: `small` or `lite`.

The lite download is larger and takes longer than small.
To add more engine manually yourself you need:
- locate the /opt/picochess/engines folder - Pi uses aarch64 and Linux x86_64 folder
- add an executable engine file like "engineX" and a text file "engineX.uci" with the settings for that engine
- add an [engineX] section in engines.ini file

Books and games database resources
----------------------------------
Opening books and the games database are downloaded as external resources via `install-picochess.sh` (or `install-books-games.sh`). Once downloaded, they are user-managed and won't be overwritten by normal code updates.
The `obooksrv/opening.data` file is also user-managed; if it is missing, `install-books-games.sh` will download it.
The book selector in the web client is independent from the engine opening book; the engine uses the book configured in `picochess.ini`.
The web book tab also includes an `obooksrv` entry; selecting it shows statistics from the local `opening.data` dataset, while other entries use the selected polyglot `.bin` book.
To add a custom book, place the `.bin` file in `books/` and add a matching entry in `books/books.ini`.

Installation with more detailed info
------------------------------------
1. You need a Raspberry PI 5, 4, or 3. You also need a 32G SD card.
2. Use Raspberry Pi Imager to create a PI operating system on your SD card as follows:
3. Choose PI 4 and 64bit OS (I have not tested PI 3 yet, but feel free to test)
4. Username is typically pi (default in Raspberry Pi Imager). The user you install with should be the same account that runs picochess as a service. Installing under a different user than you log in with may cause permission issues (for example, updates).
5. If you don't not use a network cable on your PI remember to define your WiFi settings.
6. Add ssh support if you don't work locally on your Raspberry Pi with attached screen, keyboard and mouse.
7. Write the image to the SD.
8. Boot your PI with the SD card inserted. A standard image will reboot after first start, and the second time it starts you should be able to login as user pi.
9. Using sudo raspi-config make changes to advanced options: select PulseAudio if you want the PulseAudio backend. If you prefer to stay on Pipewire, set `audio_backend = native` in `picochess.ini`. Wayland is supported; X11 is optional.
New Trixie might be missing audio libraries you need like pulseaudio, pulseaudio-utils, libpulse0, or even libasound2-plugins
10. Get this repo. First cd /opt then do sudo git clone. This should create your /opt/picochess folder. Alternative: Download the install-picochess.sh script and run it using sudo. See quick installation above.
11. Run the install-picochess.sh script. The script will first do a system update which may run for a while depending on how old your installation is. Then it will do git clone if you dont have the repo, and git pull if you already have the repo in /opt/picochess.
12. Reboot when install is done. When you login again the voice should say "picochess", "engine startup", "ok".
13. Open your web browser on localhost or from another computer using the IP address of your PI. You can change the web port in picochess.ini
14. Start playing !

Tailoring: edit the picochess.ini file.
Troubleshooting: check the log in `/opt/picochess/logs/picochess.log`
Google group for reporting and discussing: https://groups.google.com/g/picochess

Screenshots
-----------

**Note**

This repository does not contain all engines, books or voice samples the
community has built over the years. Unfortunately, a lot of those files cannot
be easily hosted in this repository. You can find additional content for your
picochess installation in the [Picochess Google Group](https://groups.google.com/g/picochess).
<img width="1284" height="767" alt="Captura de pantalla 2025-11-22 191548" src="https://github.com/user-attachments/assets/cc391e26-277a-4bca-84cf-eab26e7314f7" />
