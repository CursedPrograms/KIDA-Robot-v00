#!/usr/bin/env python3

import os
import re
import glob
import random
import logging
import pygame

logger = logging.getLogger(__name__)

# Force ALSA and the card that `speaker-test -D hw:0,0` plays through. SDL reads
# SDL_AUDIODRIVER when the mixer starts, not at import, so setting it here is enough.
# Both can be overridden from the environment without touching the code.
os.environ.setdefault("SDL_AUDIODRIVER", "alsa")
AUDIO_DEVICE = os.environ.get("KIDA_AUDIO_DEVICE", "hw:0,0")


def _init_mixer() -> bool:
    """True once the mixer is open. False with no audio device at all: then music is off,
    and everything else still runs."""
    try:
        pygame.mixer.init(devicename=AUDIO_DEVICE)
        logger.info("Audio on ALSA device %s", AUDIO_DEVICE)
        return True
    except pygame.error as e:
        logger.warning("Could not open %s (%s); falling back to default audio device", AUDIO_DEVICE, e)
    try:
        pygame.mixer.init()
        return True
    except pygame.error as e:
        logger.error("No audio device (%s) — music off", e)
        return False


class MusicPlayer:
    """
    Pygame-backed music player with shuffle, skip, and auto-advance.

    Attributes
    ----------
    current_track : str
        Basename of the currently loaded track, or empty string if none.
    playing : bool
        True while a track is actively playing.
    """

    def __init__(self, folder: str, shuffle: bool = False):
        self.current_track: str = ""
        self.current_path:  str = ""     # full path of current_track (for the waveform analyser)
        self.playing:       bool = False
        self.paused:        bool = False

        self._manual_stop = False
        self._index       = 0

        self.SONG_END = pygame.USEREVENT + 1
        self._playlist = []
        if not _init_mixer():
            return                                    # no audio: an empty playlist, so nothing plays
        pygame.mixer.music.set_endevent(self.SONG_END)

        pattern = os.path.join(folder, "*.mp3")
        self._playlist = sorted(glob.glob(pattern))   # glob order is arbitrary

        if not self._playlist:
            logger.warning("No .mp3 files found in %s", folder)
            return

        if shuffle:
            random.shuffle(self._playlist)

        logger.info("MusicPlayer loaded %d tracks from %s", len(self._playlist), folder)

    # ── Public API ────────────────────────────────────────────

    def play_next(self) -> None:
        if not self._playlist:
            logger.warning("Playlist is empty — nothing to play")
            return

        self._manual_stop = False
        path  = self._playlist[self._index]
        self._index = (self._index + 1) % len(self._playlist)

        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            self.current_track = os.path.basename(path)
            self.current_path  = path
            self.playing        = True
            self.paused         = False
            logger.info("Now playing: %s", self.current_track)
        except pygame.error as e:
            logger.error("Failed to play %s: %s", path, e)

    def load_number(self, number: int) -> bool:
        """Loads the track with this number in its file name (track07.mp3 -> 7), ready for
        start_loaded(): the fleet's music together (fleet_music.py). False if there's none."""
        for path in self._playlist:
            m = re.search(r"\d+", os.path.splitext(os.path.basename(path))[0])
            if m and int(m.group()) == number:
                try:
                    pygame.mixer.music.load(path)
                except pygame.error as e:
                    logger.error("Failed to load %s: %s", path, e)
                    return False
                self._loaded = path
                return True
        return False

    def start_loaded(self) -> None:
        """Starts what load_number() loaded, at once."""
        self._manual_stop = False
        try:
            pygame.mixer.music.play()
        except pygame.error as e:
            logger.error("Failed to start %s: %s", self._loaded, e)
            return
        self.current_track = os.path.basename(self._loaded)
        self.current_path  = self._loaded
        self.playing       = True
        self.paused        = False
        logger.info("Now playing (with the fleet): %s", self.current_track)

    def stop(self) -> None:
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
        self._manual_stop  = True
        self.playing        = False
        self.paused         = False
        self.current_track  = ""
        self.current_path   = ""
        logger.debug("Music stopped")

    def pause(self) -> None:
        if self.playing and not self.paused:
            pygame.mixer.music.pause()
            self.paused = True

    def resume(self) -> None:
        if self.paused:
            pygame.mixer.music.unpause()
            self.paused = False

    def handle_event(self, event: pygame.event.Event) -> None:
        """Pass pygame events here to handle auto-advance."""
        if event.type != self.SONG_END:
            return
        if self._manual_stop:
            self._manual_stop = False
            return
        if pygame.mixer.music.get_busy():
            # A skip already started the next track — this is the old one's end
            return
        logger.debug("Track ended — advancing")
        self.play_next()

    # ── Info ──────────────────────────────────────────────────

    @property
    def track_count(self) -> int:
        return len(self._playlist)

    def __repr__(self) -> str:
        return (
            f"MusicPlayer(tracks={self.track_count}, "
            f"playing={self.playing}, current='{self.current_track}')"
        )
