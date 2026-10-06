#!/usr/bin/env python3
# voice.py - KIDA's spoken voice, the same idea as NORA's.
#
# NORA (an Uno + MP3 shield) plays track200+.mp3 off an SD card for each line.
# KIDA has no shield but already runs pygame, so she speaks the same way: the
# lines are pre-rendered to voice/track2NN.ogg by make_voice.ps1, and played
# here through a reserved pygame.mixer channel so a line can talk over music.
#
# Keep the indices below in step with scripts/make_voice.ps1.
#   USER / AUTONOMOUS / LINE / FACE mode, "blocked", and "hello" on startup.
#   say(n) plays line n directly (the equivalent of NORA's SAY:<n>).
#
# Everything is guarded: no mixer, no audio device, or no voice files -> the
# calls quietly do nothing, so importing or using this never breaks the robot.

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger("kida.voice")

try:
    import pygame
    _HAVE_PYGAME = True
except Exception:
    _HAVE_PYGAME = False

# ── Line numbers (match make_voice.ps1) ──────────────────────────────────────
FIRST_VOICE_TRACK = 200
VOICE_MODE_0   = 0    # 0-3: User / Autonomous / Line / Face mode
VOICE_BLOCKED  = 4
VOICE_HELLO    = 5

# Mode value (mode_control.Mode IntEnum: USER=0, AUTONOMOUS=1, LINE=2, FACE=3)
# maps straight onto voice lines 0-3.
_MODE_LINE = {0: 0, 1: 1, 2: 2, 3: 3}

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VOICE_DIR = os.path.join(_REPO, "voice")
_BLOCKED_COOLDOWN_S = 6.0     # don't repeat "something's in the way" too often


class _Voice:
    def __init__(self):
        self.enabled = False
        self._sounds = {}        # n -> pygame Sound
        self._channel = None
        self._last_blocked = 0.0
        self._init()

    def _track_path(self, n):
        base = os.path.join(_VOICE_DIR, "track%03d" % (FIRST_VOICE_TRACK + n))
        for ext in (".ogg", ".wav", ".mp3"):
            if os.path.exists(base + ext):
                return base + ext
        return None

    def _init(self):
        if not _HAVE_PYGAME:
            logger.info("voice: pygame not available — voice off")
            return
        try:
            if not pygame.mixer.get_init():
                # Reuse KIDA's own mixer settings if the music player set them.
                try:
                    from music_player import _init_mixer
                    _init_mixer()
                except Exception:
                    pygame.mixer.init()
            # A reserved channel so voice overlays music instead of cutting it.
            n = pygame.mixer.get_num_channels()
            pygame.mixer.set_num_channels(n + 1)
            self._channel = pygame.mixer.Channel(n)
        except Exception as e:
            logger.info("voice: mixer unavailable (%s) — voice off", e)
            return

        have = []
        for i in range(0, 32):
            p = self._track_path(i)
            if p:
                try:
                    self._sounds[i] = pygame.mixer.Sound(p)
                    have.append(i)
                except Exception as e:
                    logger.debug("voice: could not load line %d (%s)", i, e)
        self.enabled = bool(self._sounds)
        if self.enabled:
            logger.info("voice: %d lines loaded from %s", len(have), _VOICE_DIR)
        else:
            logger.info("voice: no voice files in %s — run make_voice.bat", _VOICE_DIR)

    # ── public API ────────────────────────────────────────────────────────────
    def say(self, n: int) -> bool:
        """Play voice line n. False if it isn't loaded or voice is off."""
        if not self.enabled:
            return False
        snd = self._sounds.get(n)
        if snd is None:
            return False
        try:
            if self._channel is not None:
                self._channel.stop()        # a new line interrupts the old one
                self._channel.play(snd)
            else:
                snd.play()
            return True
        except Exception as e:
            logger.debug("voice: play failed on line %d (%s)", n, e)
            return False

    def say_mode(self, mode_value: int) -> bool:
        line = _MODE_LINE.get(int(mode_value))
        return self.say(line) if line is not None else False

    def hello(self) -> bool:
        return self.say(VOICE_HELLO)

    def blocked(self) -> bool:
        now = time.time()
        if now - self._last_blocked < _BLOCKED_COOLDOWN_S:
            return False
        self._last_blocked = now
        return self.say(VOICE_BLOCKED)


# Module-level singleton, mirroring NORA's single voice on her board.
voice = _Voice()
