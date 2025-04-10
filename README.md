PicoChess
=========
Picochess transforms your Raspberry Pi or any Debian-based computer into a powerful chess computer. It is not a chess engine itself but a manager for the chess engines you choose to use.
This repository includes Stockfish 17 and Leela Chess Zero (LCZero) as examples. If you want to add more engines you should have a look in the picochess google group. The retro and mame engines like Mephisto works, but the special and historical engines do not work at the moment.

Features
========
- Play via Web Browser. Enjoy chess directly from your browser.
- Electronic Chess Board support, compatible with DGT e-board, Certabo, Chesslink, Chessnut, and Ichessone for an authentic playing experience. Note that no guarantees can be given that it will work with all of these boards, but the community has worked hard to maintain this possibility. I currently use a DGT e-board myself.
- DGT Clock Compatibility. Runs on the DGT Pi 3000 electronic clock which becomes an all-in one chess computer.

About This Fork
===============
This fork of Picochess focuses on:
- Upgrading dependencies – Uses the latest Python with the latest chess, and Tornado libraries.
- Asynchronous Architecture – Replaces threads with an async-based architecture for improved performance and scalability.

Requirements
------------

- Raspberry Pi 3, or Pi 4 (aarch64) or Debian (x86_64)
- RaspiOS Bookworm (latest) 64bit recommended

Quick Installation
------------------
Get the installations script, give it execution rights, and run it as sudo. It will clone the repository to /opt/picochess and install the needed services as listed below.
- wget -L https://raw.github.com/JohanSjoblom/Picochess/master/install-picochess.sh
- chmod a+x install-picochess.sh
- sudo ./install-picochess
- reboot and if everything went well Picochess should start as a service
The script installs the following services in /etc/systemd/system/
- picochess, main service
- obooksrv, opening books window on web page
- gamesdb, games window on web page

How to open the web page and play?
Use localhost:8080 in your browser to open the web page. If you are running on another machine replace localhost with the ip address of your Pi4. 

Additional scripts you might find useful:
- install-dgtpi-clock.sh, run this on DGT3000 Dgt Pi clock hardware, it installs the dgtpi service
- connect-dgt-on-debian.sh, needed on Debian laptops to connect to a Bluetooth DGT e-board

How to add more engines?
In the repo there are only Stockfish and LC0 examples. To add an engine you need:
- locate the /opt/picochess/engines folder - Pi uses aarch64 and Debian laptops x86_64 folder
- add an executable file like "engineX" and a text file "engineX.uci" with settings
- add an [engineX] section in engines.ini file
To get a lot of Pi engines copy the entire /opt/picoshess/engines/ folder from an image found in the picochess google group.

If you have a Pi4 image from the picochess group you can copy the entire /opt/picoshess/engines/aarch64 folder from the image to your Pi4.

Installation with more detailed info
------------------------------------
1. You need a Raspberry PI 4 (or 3) and a 32G SD card.
2. Use Raspberry Pi Imager to crete a PI operating system on your SD card as follows:
3. Choose PI 4 and 64bit OS (I have not tested PI 3 yet, but feel free to test)
4. Username is assumed to be pi which should be standard on the imager. You can make sure by editing options in the imager.
5. If you don't not use a network cable on your PI remember to define your WiFi settings.
6. Add ssh support if you don't work locally on your Raspberry Pi with attached screen, keyboard and mouse.
7. Write the image to the SD.
8. Boot your PI with the SD card inserted. A standard image will reboot after first start, and the second time it starts you should be able to login as user pi.
9. Using sudo raspi-config make changes to advanced options: select PulseAudio and X11. PulseAudio prevents lag in the picochess spoken voice.
10. Get this repo. First cd /opt then do sudo git clone. This should create your /opt/picochess folder. Alternative: Download the install-picochess.sh script and run it using sudo. See quick installation above.
11. Run the install-picochess.sh script. The script will first do a system update which may run for a while depending on how old your installation is. Then it will do git clone if you dont have the repo, and git pull if you already have the repo in /opt/picochess.
12. Reboot when install is done. When you login again the voice should say "picochess", "engine startup", "ok".
13. Open your web browser on localhost:8080 or from another computer using the IP address of your PI. You can change the web port in pocochess.ini
14. Start playing !

Tailoring: edit the picochess.ini file.
Troubleshooting: check the log in /opt/picochess/logs/picochess.log
Google group for reporting and discussing: https://groups.google.com/g/picochess

**Note**

This repository does not contain all engines, books or voice samples the
community has built over the years. Unfortunately, a lot of those files cannot
be easily hosted in this repository. You can find additional content for your
picochess installation in the [Picochess Google Group](https://groups.google.com/g/picochess).
