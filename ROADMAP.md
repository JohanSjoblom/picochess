## About the next version of PicoChess.

July 29, 2020
Marcel Vanthoor <mail@marcelvanthoor.nl>

## Introduction:

At the moment, PicoChess 0.9n is the latest official, free version, with
Jürgen Précour as the last person to actively work on the code. This
version is over two years old now, and has only been updated sporadically,
by Shivkumar Shivaji. The latest image, created using this version and
available from Jürgen Précour's site, is also about two years old. It is
becoming outdated, as it will not run on a Raspberry Pi 4.

## Goals

- Create a new image, on the basis of Raspberry Pi OS Buster, which is the
  latest latest version at the time of writing.
- Integrate PicoChess community efforts into this image, and after testing,
  also into PicoChess. These community efforts include:
    - Updated requirements.txt with the latest working dependencies that do
      NOT require code changes in PicoChess, created by Alan (Al, Scally).
    - Install the latest version of dgtpicom and dgtpicom.so, created by
      Lucas van der Ploeg from DGT Netherlands.
    - Install Eric's Bluetooth Fix script, to make Bluetooth connections
      more robust.
	
## Next version number: 10

Wilhelm and Dirk from the PicoChess Google group have collaborated on
several seperate forks of PicoChess. These are personal versions, with
changes that have never been pushed into the main repositories. These
versions are called PicoChess 1.0, 2.0, and 2.01.

Also there's an SD-card image, created by Alan, that is called PicoChess
2.01+ (2.01 Plus), which contains both PicoChess 2.01 and 0.9n, allowing
the user to switch between these versions. This image also contains a lot
more software such as additional engines, ande the MAME/MESS emulator which
is able to run retro/legacy engines from the 80's and 90's, if one has the
correct ROM-files. Some of those engine ROMs have been made freely
available by their authors.

Dirk has asked to not develop new versions on top of his own (open source)
code, as he feels that his code quality is not good enough to be in the
main repository. (Which, by the way, is entirely his own opinion: at the
time of writing this, I haven't yet inspected any PicoChess code from any
version.)

So, version numbers 1.0, 2.0, and 2.01 have already been taken. Even though
they are personal versions, they are well known within the community. The
image called PicoChess version 2.01+ by Alan is also used extensively.
Therefore, a new version of PicoChess developed on top of the last offical
open source 0.9n version should have a version number that clearly sets it
apart from all the other well known versions.

The next version would be PicoChess 10. This is basically "1.0" with the
dot removed.

Version 10 will not contain any changes to the code. It will contain
updates to external files and dependencies. A dependency will be updated to
the highest version number possible that does NOT require code changes in
PicoChess.

## Beyond version 10

After version 10 is established and the new main image is created, it is
the intent to upgrade dependencies further. To keep the number of fixes in
the code manageable, dependencies will be upgraded one by one, and one
version at a time.

For example: upgrade Tornado Webserver from 4.5.1 => 4.5.2 => 4.5.3.

If necessary, PicoChess' code will be changed to accomodate each update.

Each time a dependency is updated and then requires a code change,
PicoChess' version number will be raised by 0.1. After a dependency reaches
the latest available version (in this example, that would be Tornado 6.0.4)
and it is  is confirmed working after testing, PicoChess' version number
will be raised by 1.

So, the in-between updates of Tornado will see PicoChess 10.1, 10.2, and so
on; and after Tornado reaches its current latest version (6.0.4) and
PicoChess is updated to match, the PicoChess version will be 11.

Then, the next dependency will be updated, eventually resulting in
PicoChess 12... and so on.

## Even further into the future

After all the dependencies are updated and PicoChess has been adapted to
match, there would be room for the development of new features. This
development can commence earlier, to some extent, especially if those
developments do not depend on the existing dependencies.

It would not be advised to create new functionality which heavily depends
an external (Python) module that has not yet been updated to the latest
version. Doing so would possibly mean that this new functionality would
need to be changed as soon as the dependency is updated. While this does
not have to be a problem, it does create more work for the person creating
this functionality. Still, if the functionality is highly desired and the
update of the dependency is a long way off, it could be worthwhile to
implement the functionality ahead of time.
