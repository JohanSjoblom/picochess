# Copyright (C) 2013-2018 Jean-Francois Romang (jromang@posteo.de)
#                         Shivkumar Shivaji ()
#                         Jürgen Précour (LocutusOfPenguin@posteo.de)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

# Issue #60. This version uses pygame instead of sox

import logging
from pathlib import Path
import io
from random import randint
import os
import asyncio

# import sys  # type: ignore - needed for redirecting stdout/stderr
import contextlib  # type: ignore - needed for redirecting stdout/stderr
import subprocess

# Suppress pygame's hardcoded output to stdout/stderr
with contextlib.redirect_stdout(io.StringIO()):
    import pygame

from pydub import AudioSegment  # type: ignore
import chess  # type: ignore
from utilities import DisplayMsg
from dgt.api import Message
from dgt.util import GameResult, PlayMode, Voice, EBoard

logger = logging.getLogger(__name__)
# base directory for picochess - needed for pydub AudioSegment file loading
# @todo: make one global constant for this basedir, its used in many places
# here its used only when audio speed is not 1.0, so pydub can load the sound file
BASE_DIR = "/opt/picochess/"


class PicoTalker(object):
    """Handle the human speaking of events."""

    def __init__(self, localisation_id_voice, speed_factor: float, common_queue: asyncio.Queue):
        self.voice_path = None
        self.speed_factor = 1.0
        self.set_speed_factor(speed_factor)
        logger.debug("molli voice pfad calc.")
        try:
            (localisation_id, voice_name) = localisation_id_voice.split(":")
            voice_path = "talker/voices/" + localisation_id + "/" + voice_name
            if Path(voice_path).exists():
                self.voice_path = voice_path
            else:
                logger.warning("voice path [%s] doesnt exist", voice_path)
        except ValueError:
            logger.warning("not valid voice parameter: %s", localisation_id_voice)
        logger.debug("voice pfad: [%s]", self.voice_path)
        self.sound_queue = common_queue  # queue to play one sound at a time

    def set_speed_factor(self, speed_factor: float):
        """Set the speed voice factor."""
        self.speed_factor = speed_factor

    async def talk(self, sounds) -> bool:
        """Speak out the sound part - return True if at least one voice file found"""
        if not self.voice_path:
            logger.debug("picotalker turned off")
            return False

        result = False
        for part in sounds:
            voice_file = self.voice_path + "/" + part
            if Path(voice_file).is_file():
                # put in common queue in PicoTalkerDisplay to play one sound at a time
                await self.sound_queue.put(voice_file)
                result = True
            else:
                logger.warning("voice file not found %s", voice_file)
        return result


class PicoTalkerDisplay(DisplayMsg):
    """Listen on messages for talking."""

    USER = "user"
    COMPUTER = "computer"
    SYSTEM = "system"
    BEEPER = "beeper"

    c_taken = False
    c_castle = False
    c_knight = False
    c_rook = False
    c_king = False
    c_bishop = False
    c_pawn = False
    c_queen = False
    c_check = False
    c_mate = False
    c_stalemate = False
    c_draw = False

    # add voice comment-factor
    def __init__(
        self,
        user_voice: str,
        computer_voice: str,
        speed_factor: int,
        setpieces_voice: bool,
        comment_factor: int,
        sample_beeper: bool,
        sample_beeper_level: int,
        eboard_type: EBoard,
        loop: asyncio.AbstractEventLoop,
    ):
        """
        Initialize a PicoTalkerDisplay with voices for the user and/or computer players.

        :param user_voice: The voice to use for the user (eg. en:al).
        :param computer_voice: The voice to use for the computer (eg. en:christina).
        """
        super(PicoTalkerDisplay, self).__init__(loop)
        # init pygame sound stuff
        pygame.mixer.init()  # keep all pygame.mixer here in PicoTalkerDisplay, not in PicoTalkers
        self.sound_cache = {}  # cache for voice files
        self.common_queue = asyncio.Queue()  # queue for sound_player
        asyncio.create_task(self.sound_player())  # background sound player

        self.user_picotalker = None  # type: PicoTalker
        self.computer_picotalker = None  # type: PicoTalker
        self.beeper_picotalker = None  # type: PicoTalker
        self.eboard_type = eboard_type
        self.speed_factor = (90 + (speed_factor % 10) * 5) / 100
        self.play_mode = PlayMode.USER_WHITE
        self.low_time = False
        self.play_game = None
        self.setpieces_voice = setpieces_voice
        if computer_voice:
            self.pico_voice_active = True
        else:
            self.pico_voice_active = False
        self.c_no_beforecmove = 0
        self.c_no_beforeumove = 0
        self.c_no_cmove = 0
        self.c_no_umove = 0
        self.c_no_poem = 0
        self.c_no_chat = 0
        self.c_no_newgame = 0
        self.c_no_rmove = 0
        self.c_no_uwin = 0
        self.c_no_uloose = 0
        self.c_no_ublack = 0
        self.c_no_uwhite = 0
        self.c_no_start = 0
        self.c_no_name = 0
        self.c_no_shutdown = 0
        self.c_no_takeback = 0
        self.c_no_taken = 0
        self.c_no_check = 0
        self.c_no_mate = 0
        self.c_no_stalemate = 0
        self.c_no_draw = 0
        self.c_no_castle = 0
        self.c_no_king = 0
        self.c_no_queen = 0
        self.c_no_rook = 0
        self.c_no_bishop = 0
        self.c_no_knight = 0
        self.c_no_pawn = 0
        self.same_cnt = 0

        self.c_comment_factor = comment_factor
        self.sample_beeper = sample_beeper
        self.sample_beeper_level = sample_beeper_level

        if user_voice:
            logger.debug("creating user voice: [%s]", str(user_voice))
            self.set_user(PicoTalker(user_voice, self.speed_factor, self.common_queue))
        if computer_voice:
            logger.debug("creating computer voice: [%s]", str(computer_voice))
            self.set_computer(PicoTalker(computer_voice, self.speed_factor, self.common_queue))
        if self.sample_beeper and self.sample_beeper_level > 0:
            beeper_sound = "en:beeper"
            logger.debug("creating beeper sound: [%s]", str(beeper_sound))
            self.set_beeper(PicoTalker(beeper_sound, self.speed_factor, self.common_queue))

    async def exit_or_reboot_cleanups(self):
        """Clean up before exit or reboot."""
        logger.debug("picotalker cleaning up sound cache and queues")
        # First drain remaining unplayed sounds
        while not self.common_queue.empty():
            try:
                self.common_queue.get_nowait()
                self.common_queue.task_done()
            except asyncio.QueueEmpty:
                break
        await self.common_queue.put(None)  # signal stop sound player
        # calling main picochess is waiting after this, but...
        # cannot clear cache before it finds None in the sound queue
        await asyncio.sleep(0.1)  # give sound player time to process None
        self.sound_cache.clear()  # clear sound cache
        self.sound_cache = {}
        if pygame.mixer.get_init():  # prevent mixer not initialized error in shutdown
            pygame.mixer.stop()  # stop all sounds
            pygame.mixer.quit()  # clean up mixer subsystem
        # finally call quit that only exists in runtime - ignore linter error
        pygame.quit()  # pylint: disable=E1101

    async def sound_player(self):
        """Common sound player to play one sound at a time from the sound queue
        Both user, computer and beeper talker will use this queue to play sounds."""
        try:
            while True:
                voice_file = await self.common_queue.get()
                if voice_file is None:
                    # stop sound player
                    logger.debug("picotalker sound player stopping")
                    break  # exit the loop
                # self.pico3_sound_player(voice_file)  # blocking play
                await asyncio.to_thread(self.pico3_sound_player, voice_file)
                # issue #77 tmp commenting out Pico4 sound playing
                # sound = await self.get_or_load_sound(voice_file)
                # sound.play()  # returns immediately
                # await asyncio.sleep(sound.get_length() + 0.3)  # wait until it's done
        except asyncio.CancelledError:
            logger.debug("picotalker sound player cancelled")

    def pico3_sound_player(self, voice_file) -> bool:
        """Speak out the sound part by using sox play.
        return True if sound was played, False if not."""
        result = False
        command = ["play", voice_file, "tempo", str(self.speed_factor)]
        try:  # use blocking call
            subprocess.call(command, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            result = True
        except OSError as os_exc:
            logger.warning("OSError: %s => turn voice OFF", os_exc)
        return result

    async def get_or_load_sound(self, path):
        """Async function to load or get sound from cache"""
        key = (path, self.speed_factor)
        if key not in self.sound_cache:
            # loading sounds blocks, playing them does not, use thread here
            sound = await asyncio.to_thread(self.load_and_transform, path)
            self.sound_cache[key] = sound
        return self.sound_cache[key]

    def load_and_transform(self, path: str):
        """Load a sound file and change its playback speed if necessary."""
        if self.speed_factor == 1.0:
            # no speed change needed, load directly, dont use pydub, ffmpeg, io
            return pygame.mixer.Sound(path)  # only AudioSegment needs BASE_DIR
        # use pydub and ffmpeg to load the sound file and change playback speed
        seg = AudioSegment.from_file(BASE_DIR + path)
        seg = self.change_playback_speed(seg)
        return self.audiosegment_to_pygame_sound(seg)

    # the following two member functions are used to change the playback speed of a sound
    # it requires pydub and ffmpeg to be installed - only used if speed_factor != 1.0
    # they are called from load_and_transform above
    def change_playback_speed(self, sound: AudioSegment):
        """use pydub to change the playback speed of a sound"""
        new_frame_rate = int(sound.frame_rate * self.speed_factor)
        return sound._spawn(sound.raw_data, overrides={"frame_rate": new_frame_rate}).set_frame_rate(sound.frame_rate)

    def audiosegment_to_pygame_sound(self, seg: AudioSegment):
        """Convert an AudioSegment to a pygame Sound object.
        used to play pydub sounds in pygame, pydub is used to change playback speed."""
        raw = io.BytesIO()
        seg.export(raw, format="wav")
        raw.seek(0)
        return pygame.mixer.Sound(file=raw)

    def set_comment_factor(self, comment_factor: int):
        self.c_comment_factor = comment_factor

    def calc_no_group_comments(self, filestring: str):
        """
        molli: Calculate number of generic filestring files in voice folder
        """
        c_group_no = 0

        if self.computer_picotalker is not None:
            path = self.computer_picotalker.voice_path
            for file in os.listdir(path):
                if file.startswith(filestring):
                    c_group_no += 1

        return c_group_no

    def set_computer(self, picotalker: PicoTalker):
        """Set the computer talker.
        molli: set correct number and assign it to voice group comment variables"""
        self.computer_picotalker = picotalker
        self.c_no_beforecmove = self.calc_no_group_comments("f_beforecmove")
        self.c_no_beforeumove = self.calc_no_group_comments("f_beforeumove")
        self.c_no_cmove = self.calc_no_group_comments("f_cmove")
        self.c_no_umove = self.calc_no_group_comments("f_umove")
        self.c_no_poem = self.calc_no_group_comments("f_poem")
        self.c_no_chat = self.calc_no_group_comments("f_chat")
        self.c_no_newgame = self.calc_no_group_comments("f_newgame")
        self.c_no_rmove = self.calc_no_group_comments("f_rmove")
        self.c_no_uwin = self.calc_no_group_comments("f_uwin")
        self.c_no_uloose = self.calc_no_group_comments("f_uloose")
        self.c_no_ublack = self.calc_no_group_comments("f_ublack")
        self.c_no_uwhite = self.calc_no_group_comments("f_uwhite")
        self.c_no_start = self.calc_no_group_comments("f_start")
        self.c_no_name = self.calc_no_group_comments("f_name")
        self.c_no_shutdown = self.calc_no_group_comments("f_shutdown")
        self.c_no_takeback = self.calc_no_group_comments("f_takeback")
        self.c_no_taken = self.calc_no_group_comments("f_taken")
        self.c_no_check = self.calc_no_group_comments("f_check")
        self.c_no_mate = self.calc_no_group_comments("f_mate")
        self.c_no_stalemate = self.calc_no_group_comments("f_stalemate")
        self.c_no_draw = self.calc_no_group_comments("f_draw")
        self.c_no_castle = self.calc_no_group_comments("f_castle")
        self.c_no_king = self.calc_no_group_comments("f_king")
        self.c_no_queen = self.calc_no_group_comments("f_queen")
        self.c_no_rook = self.calc_no_group_comments("f_rook")
        self.c_no_bishop = self.calc_no_group_comments("f_bishop")
        self.c_no_knight = self.calc_no_group_comments("f_knight")
        self.c_no_pawn = self.calc_no_group_comments("f_pawn")

    def set_user(self, picotalker: PicoTalker):
        """Set the user talker."""
        self.user_picotalker = picotalker

    def set_beeper(self, picotalker: PicoTalker):
        """Set the beeper talker."""
        self.beeper_picotalker = picotalker

    def set_factor(self, speed_factor):
        """Set speech factor."""
        if self.computer_picotalker:
            self.computer_picotalker.set_speed_factor(speed_factor)
        if self.user_picotalker:
            self.user_picotalker.set_speed_factor(speed_factor)
        if self.beeper_picotalker:
            self.beeper_picotalker.set_speed_factor(speed_factor)

    async def talk(self, sounds, dev=SYSTEM):
        if self.low_time:
            return
        if dev == self.USER:  # switch-case
            if self.user_picotalker:
                await self.user_picotalker.talk(sounds)
        elif dev == self.COMPUTER:
            if self.computer_picotalker:
                await self.computer_picotalker.talk(sounds)
        elif dev == self.BEEPER:
            if self.beeper_picotalker:
                await self.beeper_picotalker.talk(sounds)
        elif dev == self.SYSTEM:
            if self.computer_picotalker:
                await self.computer_picotalker.talk(sounds)
                return
            if self.user_picotalker:
                await self.user_picotalker.talk(sounds)

    def get_total_cgroup(self, c_group: str):
        # molli: define number of possible comments in differrent event groups
        #        together with a probability factor one can control how
        #        often a group comment will be spoken
        c_number = 0
        c_prob = 0
        if c_group == "beforeumove":
            c_prob = 15
            c_number = self.c_no_beforeumove
        elif c_group == "beforecmove":
            c_prob = 15
            c_number = self.c_no_beforecmove
        elif c_group == "cmove":
            c_prob = 15
            c_number = self.c_no_cmove
        elif c_group == "umove":
            c_prob = 15
            c_number = self.c_no_umove
        elif c_group == "poem":
            c_prob = 15
            c_number = self.c_no_poem
        elif c_group == "chat":
            c_prob = 15
            c_number = self.c_no_chat
        elif c_group == "newgame":
            c_prob = 100
            c_number = self.c_no_newgame
        elif c_group == "rmove":
            c_prob = 15
            c_number = self.c_no_rmove
        elif c_group == "uwin":
            c_prob = 100
            c_number = self.c_no_uwin
        elif c_group == "uloose":
            c_prob = 100
            c_number = self.c_no_uloose
        elif c_group == "ublack":
            c_prob = 50
            c_number = self.c_no_ublack
        elif c_group == "uwhite":
            c_prob = 50
            c_number = self.c_no_uwhite
        elif c_group == "start":
            c_prob = 100
            c_number = self.c_no_start
        elif c_group == "name":
            c_prob = 100
            c_number = self.c_no_name
        elif c_group == "shutdown":
            c_prob = 100
            c_number = self.c_no_shutdown
        elif c_group == "takeback":
            c_prob = 50
            c_number = self.c_no_takeback
        elif c_group == "taken":
            c_prob = 50
            c_number = self.c_no_taken
        elif c_group == "check":
            c_prob = 50
            c_number = self.c_no_check
        elif c_group == "mate":
            c_prob = 100
            c_number = self.c_no_mate
        elif c_group == "stalemate":
            c_prob = 100
            c_number = self.c_no_stalemate
        elif c_group == "draw":
            c_prob = 100
            c_number = self.c_no_draw
        elif c_group == "castle":
            c_prob = 50
            c_number = self.c_no_castle
        elif c_group == "king":
            c_prob = 50
            c_number = self.c_no_king
        elif c_group == "queen":
            c_prob = 50
            c_number = self.c_no_queen
        elif c_group == "rook":
            c_prob = 50
            c_number = self.c_no_rook
        elif c_group == "bishop":
            c_prob = 50
            c_number = self.c_no_bishop
        elif c_group == "knight":
            c_prob = 50
            c_number = self.c_no_knight
        elif c_group == "pawn":
            c_prob = 50
            c_number = self.c_no_pawn
        else:
            c_prob = 0
            c_number = 0

        return c_number, c_prob

    def calc_comment(self, c_group):
        # molli: define number of possible comments in differrent event groups
        #        together with a probability factor one can control how
        #        often a group comment will be spoken
        talkfile = ""
        c_rand_str = ""
        c_rand = 0
        c_number = 0
        c_prob = 0
        c_total = 0

        # get total numbers of possible comments for this event group in dependence of
        # selected comment speech and lanuage

        c_total, c_prob = self.get_total_cgroup(c_group)

        if c_prob == 0 or self.c_comment_factor == 0:
            return talkfile

        # consider probability factor from picochess.ini
        if any(
            (
                c_group == "start",
                c_group == "name",
                c_group == "shutdown",
                c_group == "mate",
                c_group == "stalemate",
                c_group == "draw",
                c_group == "takeback",
                c_group == "check",
            )
        ):
            # don't use factor for these events
            pass
        else:
            c_prob = round(c_prob * (self.c_comment_factor / 100))

        c_number = round(c_total * (100 / c_prob))

        if c_number > 1:
            c_rand = randint(1, c_number)
        else:
            c_rand = c_number

        c_rand_str = str(c_rand)

        if c_rand == 0:
            talkfile = ""
        elif c_rand <= c_total:
            talkfile = "f_" + c_group + c_rand_str + ".ogg"
        else:
            talkfile = ""

        return talkfile

    async def comment(self, c_group):
        # molli: define number of possible comments in differrent event groups
        #        together with a probability factor one can control how
        #        often a group comment will be spoke
        talkfile = ""

        # get total numbers of possible comments for this event group in dependence of
        # selected comment speech and lanuage

        talkfile = self.calc_comment(c_group)

        if talkfile != "":
            await self.talk([talkfile])

    async def move_comment(self):
        talkfile = ""

        if PicoTalkerDisplay.c_taken:
            talkfile = self.calc_comment("taken")
        elif PicoTalkerDisplay.c_bishop:
            talkfile = self.calc_comment("bishop")
        elif PicoTalkerDisplay.c_queen:
            talkfile = self.calc_comment("queen")
        elif PicoTalkerDisplay.c_knight:
            talkfile = self.calc_comment("knight")
        elif PicoTalkerDisplay.c_rook:
            talkfile = self.calc_comment("rook")
        elif PicoTalkerDisplay.c_king:
            talkfile = self.calc_comment("king")
        elif PicoTalkerDisplay.c_castle:
            talkfile = self.calc_comment("castle")
        elif PicoTalkerDisplay.c_pawn:
            talkfile = self.calc_comment("pawn")
        else:
            # pawn piesces are not spoken
            # (no flag is set) => but we comment them!
            talkfile = self.calc_comment("pawn")

        if talkfile != "":
            await self.talk([talkfile])

        if PicoTalkerDisplay.c_mate:
            talkfile = ""
        elif PicoTalkerDisplay.c_stalemate:
            talkfile = ""
        elif PicoTalkerDisplay.c_draw:
            talkfile = ""
        elif PicoTalkerDisplay.c_check:
            talkfile = self.calc_comment("check")
        else:
            talkfile = ""

        if talkfile != "":
            await self.talk([talkfile])

    def say_squarepiece(self, fen_result):
        logger.debug("molli: talker fen_result = %s", fen_result)

        piece_parts = {
            "K": "t_king.ogg",
            "B": "t_bishop.ogg",
            "N": "t_knight.ogg",
            "R": "t_rook.ogg",
            "Q": "t_queen.ogg",
            "P": "t_pawn.ogg",
        }

        square_parts = {
            "a": "t_a.ogg",
            "b": "t_b.ogg",
            "c": "t_c.ogg",
            "d": "t_d.ogg",
            "e": "t_e.ogg",
            "f": "t_f.ogg",
            "g": "t_g.ogg",
            "h": "t_h.ogg",
            "1": "t_1.ogg",
            "2": "t_2.ogg",
            "3": "t_3.ogg",
            "4": "t_4.ogg",
            "5": "t_5.ogg",
            "6": "t_6.ogg",
            "7": "t_7.ogg",
            "8": "t_8.ogg",
        }

        sound_file = ""
        voice_parts = []
        rank = fen_result[-2]
        file = fen_result[-1]
        square_str = rank
        square_str = square_str + " " + file

        logger.debug("molli: talker square = %s", square_str)

        if len(fen_result) > 2:
            piece = fen_result[0]
            if piece.islower():
                voice_parts += ["black.ogg"]
                piece = piece.upper()
            else:
                voice_parts += ["white.ogg"]

            logger.debug("molli: talker piece = %s", piece)

            try:
                sound_file = piece_parts[piece]
            except KeyError:
                sound_file = ""
            if sound_file:
                voice_parts += [sound_file]

            voice_parts += ["on.ogg"]

            for part in square_str:
                try:
                    sound_file = square_parts[part]
                except KeyError:
                    sound_file = ""
                if sound_file:
                    voice_parts += [sound_file]
        else:
            for part in square_str:
                try:
                    sound_file = square_parts[part]
                except KeyError:
                    sound_file = ""
                if sound_file:
                    voice_parts += [sound_file]

        logger.debug("molli: talker voice_parts = %s", voice_parts)
        return voice_parts

    async def message_consumer(self):
        """consume Picotalker messages"""
        logger.debug("picotalker msg_queue ready")
        try:
            while True:
                # Check if we have something to say
                message = await self.msg_queue.get()
                if (
                    not isinstance(message, Message.DGT_SERIAL_NR)
                    and not isinstance(message, Message.DGT_CLOCK_TIME)
                    and not isinstance(message, Message.CLOCK_TIME)
                ):
                    logger.debug("received message from msg_queue: %s", message)
                # issue #45 just process one message at a time - dont spawn task
                # asyncio.create_task(self.process_picotalker_messages(message))
                await self.process_picotalker_messages(message)
                self.msg_queue.task_done()
                await asyncio.sleep(0.05)  # balancing message queues
        except asyncio.CancelledError:
            logger.debug("picotalker msg_queue cancelled")

    async def process_picotalker_messages(self, message):
        """process Picotalker messages"""
        previous_move = chess.Move.null()  # Ignore repeated broadcasts of a move
        last_pos_dir = ""
        if isinstance(message, Message.ENGINE_FAIL):
            logger.debug("announcing ENGINE_FAIL")
            await self.talk(["error.ogg"])

        elif isinstance(message, Message.START_NEW_GAME):
            last_pos_dir = ""
            if message.newgame:
                logger.debug("announcing START_NEW_GAME")
                await self.talk(["new_game.ogg"], self.BEEPER)
                await self.talk(["newgame.ogg"])
                self.play_game = None
                await self.comment("newgame")
                await self.comment("uwhite")
                previous_move = chess.Move.null()

        elif isinstance(message, Message.COMPUTER_MOVE):
            logger.debug("molli: before announcing COMPUTER_MOVE [%s]", message.move)
            if message.move and message.game:
                game_copy = message.game.copy()
                if game_copy.board_fen() == chess.STARTING_BOARD_FEN:
                    previous_move = chess.Move.null()
                if message.move != previous_move:
                    logger.debug("announcing COMPUTER_MOVE [%s]", message.move)
                    game_copy.push(message.move)
                    await self.talk(["computer_move.ogg"], self.BEEPER)
                    if self.eboard_type == EBoard.NOEBOARD:
                        await self.talk(["player_move.ogg"], self.BEEPER)
                    await self.comment("beforecmove")
                    await self.talk(self.say_last_move(game_copy), self.COMPUTER)
                    await self.move_comment()
                    await self.comment("cmove")
                    previous_move = message.move
                    self.play_game = game_copy

        elif isinstance(message, Message.COMPUTER_MOVE_DONE):
            self.play_game = None
            if self.eboard_type != EBoard.NOEBOARD:
                await self.talk(["player_move.ogg"], self.BEEPER)
            await self.comment("chat")

        elif isinstance(message, Message.USER_MOVE_DONE):
            if message.move and message.game and message.move != previous_move:
                logger.debug("announcing USER_MOVE_DONE [%s]", message.move)
                await self.talk(["player_move.ogg"], self.BEEPER)
                await self.comment("beforeumove")
                await self.talk(self.say_last_move(message.game), self.USER)
                previous_move = message.move
                self.play_game = None
                await self.comment("umove")
                await self.comment("poem")

        elif isinstance(message, Message.REVIEW_MOVE_DONE):
            if message.move and message.game and message.move != previous_move:
                logger.debug("announcing REVIEW_MOVE_DONE [%s]", message.move)
                await self.talk(["player_move.ogg"], self.BEEPER)
                await self.talk(self.say_last_move(message.game), self.USER)
                previous_move = message.move
                self.play_game = None  # @todo why thats not set in dgtdisplay?

        elif isinstance(message, Message.GAME_ENDS):
            previous_move = chess.Move.null()
            last_pos_dir = ""
            if message.result == GameResult.OUT_OF_TIME:
                logger.debug("announcing GAME_ENDS/TIME_CONTROL")
                wins = "whitewins.ogg" if message.game.turn == chess.BLACK else "blackwins.ogg"
                await self.talk(["timelost.ogg", wins])
                if wins == "whitewins.ogg":
                    if self.play_mode == PlayMode.USER_WHITE:
                        await self.comment("uwin")
                    else:
                        await self.comment("uloose")
                else:
                    if self.play_mode == PlayMode.USER_BLACK:
                        await self.comment("uwin")
                    else:
                        await self.comment("uloose")
            elif message.result == GameResult.INSUFFICIENT_MATERIAL:
                logger.debug("announcing GAME_ENDS/INSUFFICIENT_MATERIAL")
                await self.talk(["material.ogg", "draw.ogg"])
                await self.comment("draw")
            elif message.result == GameResult.MATE:
                logger.debug("announcing GAME_ENDS/MATE")
                await self.comment("mate")
                if message.game.turn == chess.BLACK:
                    # white wins
                    if self.play_mode == PlayMode.USER_WHITE:
                        await self.talk(["checkmate.ogg"])
                        await self.talk(["whitewins.ogg"])
                        await self.comment("uwin")
                    else:
                        await self.comment("uloose")
                else:
                    # black wins
                    if self.play_mode == PlayMode.USER_BLACK:
                        await self.talk(["checkmate.ogg"])
                        await self.talk(["blackwins.ogg"])
                        await self.comment("uwin")
                    else:
                        await self.comment("uloose")
            elif message.result == GameResult.STALEMATE:
                logger.debug("announcing GAME_ENDS/STALEMATE")
                await self.talk(["stalemate.ogg"])
                await self.comment("stalemate")
            elif message.result == GameResult.ABORT:
                logger.debug("announcing GAME_ENDS/ABORT")
                await self.talk(["abort.ogg"])
            elif message.result == GameResult.DRAW:
                logger.debug("announcing GAME_ENDS/DRAW")
                await self.talk(["draw.ogg"])
                await self.comment("draw")
            elif message.result == GameResult.WIN_WHITE:
                logger.debug("announcing GAME_ENDS/WHITE_WIN")
                await self.talk(["whitewins.ogg"])
                if self.play_mode == PlayMode.USER_WHITE:
                    await self.comment("uwin")
                else:
                    await self.comment("uloose")
            elif message.result == GameResult.WIN_BLACK:
                logger.debug("announcing GAME_ENDS/BLACK_WIN")
                await self.talk(["blackwins.ogg"])
                if self.play_mode == PlayMode.USER_BLACK:
                    await self.comment("uwin")
                else:
                    await self.comment("uloose")
            elif message.result == GameResult.FIVEFOLD_REPETITION:
                logger.debug("announcing GAME_ENDS/FIVEFOLD_REPETITION")
                await self.talk(["repetition.ogg", "draw.ogg"])
                await self.comment("draw")

        elif isinstance(message, Message.TAKE_BACK):
            logger.debug("announcing TAKE_BACK")
            await self.talk(["takeback.ogg"])
            self.play_game = None
            previous_move = chess.Move.null()
            await self.comment("takeback")

        elif isinstance(message, Message.TIME_CONTROL):
            logger.debug("announcing TIME_CONTROL")
            await self.talk(["confirm.ogg"], self.BEEPER)
            await self.talk(["oktime.ogg"])

        elif isinstance(message, Message.INTERACTION_MODE):
            logger.debug("announcing INTERACTION_MODE")
            await self.talk(["okmode.ogg"])

        elif isinstance(message, Message.LEVEL):
            if message.do_speak:
                logger.debug("announcing LEVEL")
                await self.talk(["oklevel.ogg"])
            else:
                logger.debug("dont announce LEVEL cause its also an engine message")

        elif isinstance(message, Message.OPENING_BOOK):
            logger.debug("announcing OPENING_BOOK")
            await self.talk(["okbook.ogg"])

        elif isinstance(message, Message.ENGINE_READY):
            logger.debug("announcing ENGINE_READY")
            await self.talk(["confirm.ogg"], self.BEEPER)
            await self.talk(["okengine.ogg"])

        elif isinstance(message, Message.PLAY_MODE):
            logger.debug("announcing PLAY_MODE")
            self.play_mode = message.play_mode
            userplay = "userblack.ogg" if message.play_mode == PlayMode.USER_BLACK else "userwhite.ogg"
            await self.talk([userplay])
            if message.play_mode == PlayMode.USER_BLACK:
                await self.comment("ublack")
            else:
                await self.comment("uwhite")

        elif isinstance(message, Message.STARTUP_INFO):
            self.play_mode = message.info["play_mode"]
            logger.debug("announcing PICOCHESS")
            await self.talk(["picoChess.ogg"], self.BEEPER)
            await self.talk(["picoChess.ogg"])
            previous_move = chess.Move.null()
            last_pos_dir = ""
            await self.comment("start")
            await self.comment("name")

        elif isinstance(message, Message.CLOCK_TIME):
            self.low_time = message.low_time
            if self.low_time:
                logger.debug(
                    "time too low, disable voice - w: %i, b: %i",
                    message.time_white,
                    message.time_black,
                )

        elif isinstance(message, Message.ALTERNATIVE_MOVE):
            self.play_mode = message.play_mode
            self.play_game = None
            await self.talk(["alternative_move.ogg"])

        elif isinstance(message, Message.SYSTEM_SHUTDOWN):
            logger.debug("announcing SHUTDOWN")
            await self.talk(["goodbye.ogg"])
            await self.comment("shutdown")

        elif isinstance(message, Message.SYSTEM_REBOOT):
            logger.debug("announcing REBOOT")
            await self.talk(["pleasewait.ogg"])
            await self.comment("shutdown")

        elif isinstance(message, Message.MOVE_RETRY):
            logger.debug("announcing MOVE_RETRY")
            await self.talk(["retry_move.ogg"])

        elif isinstance(message, Message.MOVE_WRONG):
            logger.debug("announcing MOVE_WRONG")
            await self.talk(["wrong_move.ogg"])

        elif isinstance(message, Message.ONLINE_LOGIN):
            logger.debug("announcing ONLINE_LOGIN")
            await self.talk(["online_login.ogg"])

        elif isinstance(message, Message.SEEKING):
            logger.debug("announcing SEEKING")
            await self.talk(["seeking.ogg"])

        elif isinstance(message, Message.ONLINE_NAMES):
            logger.debug("announcing ONLINE_NAMES")
            await self.talk(["opponent_found.ogg"])

        elif isinstance(message, Message.RESTORE_GAME):
            logger.debug("announcing RESTORE_GAME")
            await self.talk(["last_game_restored.ogg"])

        elif isinstance(message, Message.ENGINE_SETUP):
            logger.debug("announcing ENGINE_SETUP")
            await self.talk(["engine_setup.ogg"])

        elif isinstance(message, Message.ONLINE_FAILED):
            await self.talk(["server_error.ogg"])

        elif isinstance(message, Message.ONLINE_USER_FAILED):
            await self.talk(["login_error.ogg"])

        elif isinstance(message, Message.ONLINE_NO_OPPONENT):
            await self.talk(["no_opponent.ogg"])

        elif isinstance(message, Message.LOST_ON_TIME):
            await self.talk(["timelost.ogg"])

        elif isinstance(message, Message.POSITION_FAIL):
            logger.debug("molli: talker orig. fen_result = %s", message.fen_result)
            if last_pos_dir == message.fen_result:
                self.same_cnt = self.same_cnt + 1
            else:
                self.same_cnt = 0
            last_pos_dir = message.fen_result
            if self.same_cnt % 3 == 0:
                if "clear" in message.fen_result:
                    fen_str = message.fen_result[-2:]
                    await self.talk(["remove.ogg"])
                    await self.talk(self.say_squarepiece(fen_str))
                elif "put" in message.fen_result:
                    fen_str = message.fen_result[-4:]
                    await self.talk(["put.ogg"])
                    await self.talk(self.say_squarepiece(fen_str))
                else:
                    pass

        elif isinstance(message, Message.PICOTUTOR_MSG):
            if "??" == message.eval_str:
                if not self.pico_voice_active:
                    await self.talk(["picotutor.ogg"], self.BEEPER)
                await self.talk(["picotutor_notify.ogg"])
                await self.talk(["verybadmove.ogg"])
            elif "?" == message.eval_str:
                await self.talk(["picotutor_notify.ogg"])
                await self.talk(["badmove.ogg"])
            elif "!?" == message.eval_str:
                await self.talk(["picotutor_notify.ogg"])
                await self.talk(["interestingmove.ogg"])
            elif "!!" == message.eval_str:
                await self.talk(["picotutor_notify.ogg"])
                await self.talk(["verygoodmove.ogg"])
            elif "!" == message.eval_str:
                await self.talk(["picotutor_notify.ogg"])
                await self.talk(["goodmove.ogg"])
            elif "?!" == message.eval_str:
                await self.talk(["picotutor_notify.ogg"])
                await self.talk(["dubiousmove.ogg"])
            elif "ER" == message.eval_str:
                await self.talk(["picotutor_notify.ogg"])
                await self.talk(["error.ogg"])
            elif "ACTIVE" in message.eval_str:
                await self.talk(["picotutor_notify.ogg"])
                await self.talk(["picotutor_enabled.ogg"])
            elif "ANALYSIS" in message.eval_str:
                await self.talk(["picotutor_notify.ogg"])
                await self.talk(["picotutor_analysis.ogg"])
            elif "HINT" in message.eval_str:
                await self.talk(["picotutor_hintmove.ogg"])
                await self.talk(self.say_tutor_move(message.game))
            elif "THREAT" in message.eval_str:
                await self.talk(["picotutor_threatmove.ogg"])
                await self.talk(self.say_tutor_move(message.game))
            elif "POSOK" in message.eval_str:
                last_pos_dir = ""
                await self.talk(["confirm.ogg"], self.BEEPER)
                await self.talk(["ok.ogg"])
            elif "POS" in message.eval_str:
                score = message.score
                if abs(score) <= 1:
                    await self.talk(["picotutor_equal_position.ogg"])
                elif score > 3:
                    await self.talk(["picotutor_verygood_position.ogg"])
                elif score > 1 and score < 3:
                    await self.talk(["picotutor_good_position.ogg"])
                elif score < -3:
                    await self.talk(["picotutor_verybad_position.ogg"])
                elif score > -3 and score < -1:
                    await self.talk(["picotutor_bad_position.ogg"])
            elif "BEST" in message.eval_str:
                await self.talk(["picotutor_best_move.ogg"])
                await self.talk(self.say_tutor_move(message.game))
            elif "PICMATE" in message.eval_str:
                logger.debug("molli in picotutortalker: %s", message.eval_str)
                await self.talk(["picotutor_pico_mate.ogg"])
                list_str = message.eval_str
                list_mate = list_str.split("_")
                logger.debug("molli in picotutortalker: %s", list_mate[0])
                logger.debug("molli in picotutortalker: %s", list_mate[1])

                talk_mate = "t_" + list_mate[1] + ".ogg"
                logger.debug("talk_mate = %s", talk_mate)
                await self.talk([talk_mate])
            elif "USRMATE" in message.eval_str:
                logger.debug("molli in picotutortalker: %s", message.eval_str)
                await self.talk(["picotutor_player_mate.ogg"])
                list_str = message.eval_str
                list_mate = list_str.split("_")
                logger.debug("molli in picotutortalker: %s", list_mate[0])
                logger.debug("molli in picotutortalker: %s", list_mate[1])

                talk_mate = "t_" + list_mate[1] + ".ogg"
                logger.debug("talk_mate = %s", talk_mate)
                await self.talk([talk_mate])

        elif isinstance(message, Message.PGN_GAME_END):  # for pgn replay
            logger.debug("announcing PGN GAME END")
            previous_move = chess.Move.null()
            await self.talk(["pgn_game_end.ogg"])
            if "1-0" in message.result:
                await self.talk(["whitewins.ogg"])
            elif "0-1" in message.result:
                await self.talk(["blackwins.ogg"])
            elif "0.5-0.5" in message.result or "1/2-1/2" in message.result:
                await self.talk(["draw.ogg"])
            elif "*" in message.result:
                await self.talk(["game_result_unknown.ogg"])
            else:
                # default
                await self.talk(["game_result_unknown.ogg"])

        elif isinstance(message, Message.TIMECONTROL_CHECK):
            logger.debug("timecontrol check")
            await self.talk(["picotutor_notify.ogg"])
            if message.player:
                await self.talk(["timecontrol_check_player.ogg"])
            else:
                await self.talk(["timecontrol_check_opp.ogg"])

        elif isinstance(message, Message.SHOW_ENGINENAME):
            if message.show_enginename:
                await self.talk(["show_enginename_on.ogg"])
            else:
                await self.talk(["show_enginename_off.ogg"])

        elif isinstance(message, Message.SHOW_TEXT):
            if message.text_string == "NEW_POSITION_SCAN":
                await self.talk(["position_setup.ogg"])
            elif message.text_string == "NEW_POSITION":
                await self.talk(["set_pieces_sound.ogg"], self.BEEPER)
                if not self.sample_beeper or self.sample_beeper_level == 0:
                    await self.talk(["set_pieces_sound.ogg"])

        elif isinstance(message, Message.PICOWATCHER):
            if message.picowatcher:
                await self.talk(["picowatcher_enabled.ogg"])
            else:
                await self.talk(["picowatcher_disabled.ogg"])
            await self.talk(["picotutor_ok.ogg"])

        elif isinstance(message, Message.PICOCOACH):
            if message.picocoach:
                await self.talk(["picocoach_enabled.ogg"])
            else:
                await self.talk(["picocoach_disabled.ogg"])
            await self.talk(["picotutor_ok.ogg"])

        elif isinstance(message, Message.PICOEXPLORER):
            if message.picoexplorer:
                await self.talk(["picoexplorer_enabled.ogg"])
            else:
                await self.talk(["picoexplorer_disabled.ogg"])
            await self.talk(["picotutor_ok.ogg"])

        elif isinstance(message, Message.PICOCOMMENT):
            await self.talk(["ok.ogg"])

        elif isinstance(message, Message.SAVE_GAME):
            await self.talk(["save_game.ogg"])

        elif isinstance(message, Message.READ_GAME):
            await self.talk(["read_game.ogg"])

        elif isinstance(message, Message.CONTLAST):
            if message.contlast:
                await self.talk(["contlast_game_on.ogg"])
            else:
                await self.talk(["contlast_game_off.ogg"])

        elif isinstance(message, Message.ALTMOVES):
            if message.altmoves:
                await self.talk(["altmoves_on.ogg"])
            else:
                await self.talk(["altmoves_off.ogg"])

        elif isinstance(message, Message.SET_VOICE):
            self.speed_factor = (90 + (message.speed % 10) * 5) / 100
            localisation_id_voice = message.lang + ":" + message.speaker
            if message.type == Voice.USER:
                self.set_user(PicoTalker(localisation_id_voice, self.speed_factor, self.common_queue))
            if message.type == Voice.COMP:
                self.set_computer(PicoTalker(localisation_id_voice, self.speed_factor, self.common_queue))
            if message.type == Voice.SPEED:
                self.set_factor(self.speed_factor)
            if message.type == Voice.BEEPER:
                self.set_beeper(PicoTalker(localisation_id_voice, self.speed_factor, self.common_queue))
                if message.speaker == "mute":
                    self.sample_beeper = False
                else:
                    self.sample_beeper = True
            await self.talk(["confirm.ogg"], self.BEEPER)
            await self.talk(["ok.ogg"])

        elif isinstance(message, Message.WRONG_FEN):
            await self.talk(["set_pieces_sound.ogg"], self.BEEPER)
            if self.setpieces_voice:
                await self.talk(["setpieces.ogg"])
            else:
                if not self.sample_beeper or self.sample_beeper_level == 0:
                    await self.talk(["set_pieces_sound.ogg"])
            if self.play_game:
                await self.talk(self.say_last_move(self.play_game), self.COMPUTER)

        elif isinstance(message, Message.DGT_BUTTON):
            if self.sample_beeper and self.sample_beeper_level > 1:
                await self.talk(["button_click.ogg"], self.BEEPER)

    @staticmethod
    def say_last_move(game: chess.Board):
        """Take a chess.BitBoard instance and speaks the last move from it."""

        PicoTalkerDisplay.c_taken = False
        PicoTalkerDisplay.c_castle = False
        PicoTalkerDisplay.c_knight = False
        PicoTalkerDisplay.c_rook = False
        PicoTalkerDisplay.c_king = False
        PicoTalkerDisplay.c_bishop = False
        PicoTalkerDisplay.c_pawn = False
        PicoTalkerDisplay.c_queen = False
        PicoTalkerDisplay.c_check = False
        PicoTalkerDisplay.c_mate = False
        PicoTalkerDisplay.c_stalemate = False
        PicoTalkerDisplay.c_draw = False

        move_parts = {
            "K": "king.ogg",
            "B": "bishop.ogg",
            "N": "knight.ogg",
            "R": "rook.ogg",
            "Q": "queen.ogg",
            "P": "pawn.ogg",
            "+": "",
            "#": "",
            "x": "takes.ogg",
            "=": "promote.ogg",
            "a": "a.ogg",
            "b": "b.ogg",
            "c": "c.ogg",
            "d": "d.ogg",
            "e": "e.ogg",
            "f": "f.ogg",
            "g": "g.ogg",
            "h": "h.ogg",
            "1": "1.ogg",
            "2": "2.ogg",
            "3": "3.ogg",
            "4": "4.ogg",
            "5": "5.ogg",
            "6": "6.ogg",
            "7": "7.ogg",
            "8": "8.ogg",
        }

        bit_board = game.copy()
        move = bit_board.pop()
        san_move = bit_board.san(move)
        voice_parts = []
        if san_move.startswith("O-O-O"):
            voice_parts += ["castlequeenside.ogg"]
            PicoTalkerDisplay.c_castle = True
        elif san_move.startswith("O-O"):
            voice_parts += ["castlekingside.ogg"]
            PicoTalkerDisplay.c_castle = True
        else:
            for part in san_move:
                try:
                    sound_file = move_parts[part]
                except KeyError:
                    logger.warning("unknown char found in san: [%s : %s]", san_move, part)
                    sound_file = ""
                if sound_file:
                    voice_parts += [sound_file]
                    if sound_file == "takes.ogg":
                        PicoTalkerDisplay.c_taken = True
                    elif sound_file == "knight.ogg":
                        PicoTalkerDisplay.c_knight = True
                    elif sound_file == "king.ogg":
                        PicoTalkerDisplay.c_king = True
                    elif sound_file == "rook.ogg":
                        PicoTalkerDisplay.c_rook = True
                    elif sound_file == "pawn.ogg":
                        PicoTalkerDisplay.c_pawn = True
                    elif sound_file == "bishop.ogg":
                        PicoTalkerDisplay.c_bishop = True
                    elif sound_file == "queen.ogg":
                        PicoTalkerDisplay.c_queen = True

        if game.is_game_over():
            if game.is_checkmate():
                wins = "whitewins.ogg" if game.turn == chess.BLACK else "blackwins.ogg"
                voice_parts += ["checkmate.ogg", wins]
                PicoTalkerDisplay.c_mate = True
            elif game.is_stalemate():
                voice_parts += ["stalemate.ogg"]
                PicoTalkerDisplay.c_stalemate = True
            else:
                PicoTalkerDisplay.c_draw = True
                if game.is_seventyfive_moves():
                    voice_parts += ["75moves.ogg", "draw.ogg"]
                elif game.is_insufficient_material():
                    voice_parts += ["material.ogg", "draw.ogg"]
                elif game.is_fivefold_repetition():
                    voice_parts += ["repetition.ogg", "draw.ogg"]
                else:
                    voice_parts += ["draw.ogg"]
        elif game.is_check():
            voice_parts += ["check.ogg"]
            PicoTalkerDisplay.c_check = True

        if bit_board.is_en_passant(move):
            voice_parts += ["enpassant.ogg"]

        return voice_parts

    @staticmethod
    def say_tutor_move(game: chess.Board):
        """Take a chess.BitBoard instance and speaks the last move from it."""
        move_parts = {
            "K": "t_king.ogg",
            "B": "t_bishop.ogg",
            "N": "t_knight.ogg",
            "R": "t_rook.ogg",
            "Q": "t_queen.ogg",
            "P": "t_pawn.ogg",
            "+": "",
            "#": "",
            "x": "t_takes.ogg",
            "=": "t_promote.ogg",
            "a": "t_a.ogg",
            "b": "t_b.ogg",
            "c": "t_c.ogg",
            "d": "t_d.ogg",
            "e": "t_e.ogg",
            "f": "t_f.ogg",
            "g": "t_g.ogg",
            "h": "t_h.ogg",
            "1": "t_1.ogg",
            "2": "t_2.ogg",
            "3": "t_3.ogg",
            "4": "t_4.ogg",
            "5": "t_5.ogg",
            "6": "t_6.ogg",
            "7": "t_7.ogg",
            "8": "t_8.ogg",
        }

        bit_board = game.copy()
        move = bit_board.pop()
        san_move = bit_board.san(move)
        voice_parts = []

        if san_move.startswith("O-O-O"):
            voice_parts += ["t_castlequeenside.ogg"]
        elif san_move.startswith("O-O"):
            voice_parts += ["t_castlekingside.ogg"]
            PicoTalkerDisplay.c_castle = True
        else:
            for part in san_move:
                try:
                    sound_file = move_parts[part]
                except KeyError:
                    logger.warning("unknown char found in san: [%s : %s]", san_move, part)
                    sound_file = ""
                if sound_file:
                    voice_parts += [sound_file]

        if game.is_check():
            voice_parts += ["t_check.ogg"]

        if bit_board.is_en_passant(move):
            voice_parts += ["t_enpassant.ogg"]

        return voice_parts
