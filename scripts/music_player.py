#!/usr/bin/env python3

import os
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


def _init_mixer() -> None:
    try:
        pygame.mixer.init(devicename=AUDIO_DEVICE)
        logger.info("Audio on ALSA device %s", AUDIO_DEVICE)
    except pygame.error as e:
        logger.warning("Could not open %s (%s); falling back to default audio device", AUDIO_DEVICE, e)
        pygame.mixer.init()


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
        _init_mixer()

        self.current_track: str = ""
        self.current_path:  str = ""     # full path of current_track (for the waveform analyser)
        self.playing:       bool = False
        self.paused:        bool = False

        self._manual_stop = False
        self._index       = 0

        self.SONG_END = pygame.USEREVENT + 1
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

    def stop(self) -> None:
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
