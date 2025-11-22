PicoChess
=========
Picochess transforms your Raspberry Pi or any Debian-based computer into a chess computer. It is not a chess engine program, you can use many different chess engines with picochess. Picochess connects an electronic board with the chess engines you chose to play against.
Installation includes Stockfish 17 and Leela Chess Zero (LCZero) as examples. If you want to add more engines you should have a look in the picochess google group. The retro and mame engines like Mephisto works. All special and historical engines might not work.

Features
========
- Play via Web Browser. Enjoy chess directly from your browser.
- Electronic Chess Board support, compatible with DGT e-board, Certabo, Chesslink, Chessnut, and Ichessone for an authentic playing experience. Note that no guarantees can be given that it will work with all of these boards, but the community has worked hard to maintain this possibility. I currently use a DGT e-board and a DGT Pi 3000 myself.
- DGT Clock Compatibility. Runs on the DGT Pi 3000 electronic clock which becomes an all-in one chess computer.

About This Fork
===============
This fork of Picochess focuses on:
- Upgrading dependencies – Uses the latest Python with the latest chess and Tornado libraries.
- Asynchronous Architecture – Replaces threads with an async-based architecture for improved performance and scalability.
- Keep the main program picochess.py as it was, rewrites are mainly focusing on engine.py and picoTutor.py to use the latest python chess library, but as the new library is quite different some changes are visible in picochess.py as well.

Requirements
------------

- Raspberry Pi 3, Pi 4, Pi 5 (aarch64) or a Debian computer (x86_64)
- RaspiOS Bookworm 64bit or the new Trixie. The goal is that you can always take the latest stock Pi image that is available. Trixie became available early October 2025. It should work out of the box as long as you remember to switch the audio to PulseAudio. You might also need to make sure that the pulse-audio packages are installed like pulseaudio, pulseaudio-utils, libpulse0, or even libasound2-plugins.

Quick Installation
------------------
Get the installations script, give it execution rights, and run it as sudo. It will clone the repository to /opt/picochess and install the needed services.
It will also download a basic set of engines like Stockfish 17.1 and LC0 0.32. It will also download a set of LC0 weights files that you could use to setup your own LC0 personalities by editing the LC0 uci file. Note: downloading these resources takes a while, especially the LC0 personalities.
- wget -L https://raw.github.com/JohanSjoblom/Picochess/master/install-picochess.sh
- chmod +x install-picochess.sh
- sudo ./install-picochess.sh
- reboot and if everything went well Picochess should start as a service
The script installs the following services in /etc/systemd/system/
- picochess, main service
- picochess-update, the service to stay updated
- obooksrv, opening books window on web page
- gamesdb, games window on web page
The first time the script runs it will download 

How to stay updated
-------------------
You can manually update to latest version from within the program. Go to the System, Power menu and select Restart and Update Picochess. If you really want to stay updated you can edit your picochess.ini file and uncomment the line enable-update = True. In this case it will update the code every time you reboot. It will not run a system update at boot, as that takes quite some time. It will only update the picochess code.

How to open the web page and play?
----------------------------------
Use localhost in your browser to open the web page. If you are running on another machine replace localhost with the ip address of your Pi4.

How to analyse a PGN game using Picotutor?
------------------------------------------
You can upload a PGN game. Go to localhost/upload and chose a PGN file to upload to Picochess. It will ask you for your pi user password. It will load the PGN game into the starting position. Now you can step through the PGN game in Picochess by using the play-pause button. Finally save the game from the menu if you want to store the evaluations. Uploads are written to /opt/picochess/games/upload. Games are saved in /opt/picochess/games.
To upload a game from your mobile phone to Picochess you need to know the ip address of your Pi computer and replace localhost above with the ip address. You also need to be on the same network as your pi computer.
If you want to load the last game chose "PGN Replay" mode. For more analysis modes, continue reading below.

How to enter and analyse a game using Picotutor?
------------------------------------------------
You can use the menu to go to Mode and switch to "Hint On", "Eval.Score", "Observe" or "Analysis" mode. Now you make moves for both sides. Use the plus and minus button to check the depth-score and hit move. When you are done analysing: use the Game Setup from the menu and chose Declare game ending. Your game with picotutor evaluations are saved in /opt/picochess/games/last_game.pgn.

Additional scripts you might find useful:
-----------------------------------------
- install-dgtpi-clock.sh, run this on DGT3000 Dgt Pi clock hardware, it installs the dgtpi service
- connect-dgt-on-debian.sh, needed on Debian laptops to connect to a Bluetooth DGT e-board

How to add more engines?
------------------------
There are no engines in the git repo, but there are resource files with engines. The picochess installer will run the install-engines.sh after it has cloned the repo. By default it installs the small version. The small version should include at least Stockfish 17.1 and LC0 0.32. You can rerun the install-engines at any time but it will only install engines if there is no engines/arch folder for that architecture. arch can be aarch64 or x86_64. To see what options you have run install-engines without any parameters. And dont use sudo when running install-engines. Sudo is only needed for the install-picochess.
To add an engine manually you need:
- locate the /opt/picochess/engines folder - Pi uses aarch64 and Debian laptops x86_64 folder
- add an executable engine file like "engineX" and a text file "engineX.uci" with settings
- add an [engineX] section in engines.ini file
To get a lot of Pi engines copy the entire /opt/picoshess/engines/aarch64 folder from an image found in the picochess google group. At some point we can perhaps make every image release available as a resource file.

Installation with more detailed info
------------------------------------
1. You need a Raspberry PI 5, 4, or 3. You also need a 32G SD card.
2. Use Raspberry Pi Imager to crete a PI operating system on your SD card as follows:
3. Choose PI 4 and 64bit OS (I have not tested PI 3 yet, but feel free to test)
4. Username is assumed to be pi which should be standard on the imager. You can make sure by editing options in the imager.
5. If you don't not use a network cable on your PI remember to define your WiFi settings.
6. Add ssh support if you don't work locally on your Raspberry Pi with attached screen, keyboard and mouse.
7. Write the image to the SD.
8. Boot your PI with the SD card inserted. A standard image will reboot after first start, and the second time it starts you should be able to login as user pi.
9. Using sudo raspi-config make changes to advanced options: select PulseAudio and X11. Without PulseAudio there might be lags in the picochess spoken voice. A desktop stock image of Trixie will still have Pipewire as default,... change it to PulseAudio for better performance. X11 seems to be the default but check it anyway.
New Trixie might be missing audio libraries you need like pulseaudio, pulseaudio-utils, libpulse0, or even libasound2-plugins
10. Get this repo. First cd /opt then do sudo git clone. This should create your /opt/picochess folder. Alternative: Download the install-picochess.sh script and run it using sudo. See quick installation above.
11. Run the install-picochess.sh script. The script will first do a system update which may run for a while depending on how old your installation is. Then it will do git clone if you dont have the repo, and git pull if you already have the repo in /opt/picochess.
12. Reboot when install is done. When you login again the voice should say "picochess", "engine startup", "ok".
13. Open your web browser on localhost or from another computer using the IP address of your PI. You can change the web port in picochess.ini
14. Start playing !

Tailoring: edit the picochess.ini file.
Troubleshooting: check the log in /opt/picochess/logs/picochess.log
Google group for reporting and discussing: https://groups.google.com/g/picochess

**Note**

This repository does not contain all engines, books or voice samples the
community has built over the years. Unfortunately, a lot of those files cannot
be easily hosted in this repository. You can find additional content for your
picochess installation in the [Picochess Google Group](https://groups.google.com/g/picochess).
<img width="1284" height="767" alt="Captura de pantalla 2025-11-22 191548" src="https://github.com/user-attachments/assets/cc391e26-277a-4bca-84cf-eab26e7314f7" />
