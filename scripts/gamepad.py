#!/usr/bin/env python3

"""
gamepad.py — game controller input for the robot's HUD (scripts/ui.py) and
the remote controller (controller/main.py). The web dashboard does the same
with the browser Gamepad API (static/js/main.js).

Uses SDL's GameController API, which maps Xbox, PlayStation, Switch Pro and
most generic pads to one layout, so the buttons below mean the same thing
whatever is plugged in. Hot-plug: a pad can be connected or swapped at any time.

  Left stick     drive (WASD scheme) — analog, already smooth
  Both sticks    left / right track (QA/WS tank scheme)
  D-pad          drive like WASD — arc turns follow the ARC toggle
  A              cycle speed
  B              stop: back to USER mode, motors off
  X              photo
  Y              toggle ARC turns
  LB / RB        previous / next mode
  Back / Select  save faces
  Start          play / pause music
"""

import logging
import time
from types import SimpleNamespace

import pygame

try:
    from pygame._sdl2 import controller as _sdl
except ImportError:          # very old pygame — no gamepad support, everything else works
    _sdl = None

logger = logging.getLogger("kida.gamepad")

_BUTTONS = {
    "a":     "CONTROLLER_BUTTON_A",
    "b":     "CONTROLLER_BUTTON_B",
    "x":     "CONTROLLER_BUTTON_X",
    "y":     "CONTROLLER_BUTTON_Y",
    "lb":    "CONTROLLER_BUTTON_LEFTSHOULDER",
    "rb":    "CONTROLLER_BUTTON_RIGHTSHOULDER",
    "back":  "CONTROLLER_BUTTON_BACK",
    "start": "CONTROLLER_BUTTON_START",
}
_DPAD = {
    "up":    "CONTROLLER_BUTTON_DPAD_UP",
    "down":  "CONTROLLER_BUTTON_DPAD_DOWN",
    "left":  "CONTROLLER_BUTTON_DPAD_LEFT",
    "right": "CONTROLLER_BUTTON_DPAD_RIGHT",
}
RESCAN_S = 2.0     # how often to look for a newly plugged-in pad

# Button → the command string the robot's processor takes (ui.py), so a
# button does exactly what the matching key / web button does
_BUTTON_COMMANDS = {
    "a":     ["speed"],
    "b":     ["_mode_user", "stop"],
    "x":     ["photo"],
    "y":     ["arc_toggle"],
    "back":  ["face_save"],
    "start": ["music_toggle"],
}
_MODES = ["user", "autonomous", "line"]     # LB / RB order, same as the tabs


def button_commands(pressed, mode_name: str) -> list:
    """Commands for the buttons that just went down. mode_name is the current
    mode (e.g. "USER"), needed for LB / RB."""
    cmds = []
    for b in sorted(pressed):
        cmds += _BUTTON_COMMANDS.get(b, [])
        if b in ("lb", "rb"):
            i = _MODES.index(mode_name.lower()) if mode_name.lower() in _MODES else 0
            cmds.append(f"_mode_{_MODES[(i + (1 if b == 'rb' else -1)) % len(_MODES)]}")
    return cmds


class Gamepad:
    """Call poll() once per frame (after pygame.event.get(), which pumps SDL)."""

    def __init__(self):
        self._pad       = None
        self._held      = set()
        self._next_scan = 0.0
        if _sdl is not None:
            try:
                _sdl.init()
            except Exception as e:
                logger.warning("Gamepad support unavailable: %s", e)

    @property
    def name(self) -> str:
        return self._pad.name if self._pad is not None else ""

    def _ensure_pad(self) -> bool:
        if _sdl is None or not _sdl.get_init():
            return False
        if self._pad is not None:
            try:
                if self._pad.attached():
                    return True
            except Exception:
                pass
            logger.info("Gamepad disconnected: %s", self._pad.name)
            self._pad, self._held = None, set()
        now = time.monotonic()
        if now < self._next_scan:
            return False
        self._next_scan = now + RESCAN_S
        for i in range(_sdl.get_count()):
            if _sdl.is_controller(i):
                self._pad = _sdl.Controller(i)
                logger.info("Gamepad connected: %s", self._pad.name)
                return True
        return False

    def poll(self):
        """Current state, or None with no pad connected:
        lx, ly, rx, ry   sticks, -1..1, y up = +1 (forward)
        up/down/left/right  d-pad held
        pressed          set of button names that went down since the last poll"""
        if not self._ensure_pad():
            return None
        pad = self._pad
        try:
            axis = lambda name: pad.get_axis(getattr(pygame, name)) / 32767.0
            held = {b for b, c in _BUTTONS.items() if pad.get_button(getattr(pygame, c))}
            dpad = {d: bool(pad.get_button(getattr(pygame, c))) for d, c in _DPAD.items()}
            state = SimpleNamespace(
                lx=axis("CONTROLLER_AXIS_LEFTX"),  ly=-axis("CONTROLLER_AXIS_LEFTY"),
                rx=axis("CONTROLLER_AXIS_RIGHTX"), ry=-axis("CONTROLLER_AXIS_RIGHTY"),
                pressed=held - self._held, **dpad,
            )
        except Exception as e:           # unplugged mid-read
            logger.debug("Gamepad read failed: %s", e)
            self._pad = None
            return None
        self._held = held
        return state
