#!/usr/bin/env python3

"""
gamepad.py — game controller input for the robot's HUD (scripts/ui.py) and
the remote controller (controller/main.py). The web dashboard does the same
with the browser Gamepad API (static/js/main.js).

Uses SDL's GameController API, which maps Xbox, PlayStation, Switch Pro and
most generic pads to one layout, so the buttons below mean the same thing
whatever is plugged in. Hot-plug: a pad can be connected or swapped at any time,
also with none at boot, on the robot's own USB (ui.py) or on the PC (controller).

Sticks SDL has no layout for, like ARM's USB joystick (ARM-Robot-v01's
controller.py: stick axes 0/1, hat 0, trigger + buttons 1-3), are read raw:
the stick drives, the hat is the d-pad, and the trigger and buttons 1-3 are
A / B / X / Y. Their other axes (twist, throttle) are left alone, since a
throttle lever doesn't spring back to the middle.

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
  Right stick    pan the camera left / right (ui.py, controller/main.py); click it to centre

All of it is listed for people in keymap.py (the keys window, H / F1).
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
    "rstick": "CONTROLLER_BUTTON_RIGHTSTICK",
}
_DPAD = {
    "up":    "CONTROLLER_BUTTON_DPAD_UP",
    "down":  "CONTROLLER_BUTTON_DPAD_DOWN",
    "left":  "CONTROLLER_BUTTON_DPAD_LEFT",
    "right": "CONTROLLER_BUTTON_DPAD_RIGHT",
}
RESCAN_S = 2.0     # how often to look for a newly plugged-in pad
RAW_BUTTONS = {0: "a", 1: "b", 2: "x", 3: "y"}   # raw sticks: trigger, B1, B2, B3 (as KIDA-01's joystick_drive.py)


class _RawPad:
    """A joystick SDL has no controller layout for, read by axis / hat / button number."""

    def __init__(self, index: int):
        self.js = pygame.joystick.Joystick(index)
        self.js.init()
        self.name = self.js.get_name()
        self.instance_id = self.js.get_instance_id()
        self._count = pygame.joystick.get_count()

    def attached(self) -> bool:
        """Called every frame: only looks through the devices when their number changed."""
        count = pygame.joystick.get_count()
        if count != self._count:
            self._count = count
            self._here = any(pygame.joystick.Joystick(i).get_instance_id() == self.instance_id
                             for i in range(count))
        return getattr(self, "_here", True)

    def state(self):
        js = self.js
        ax = lambda i: js.get_axis(i) if js.get_numaxes() > i else 0.0
        hx, hy = js.get_hat(0) if js.get_numhats() else (0, 0)
        held = {n for i, n in RAW_BUTTONS.items() if i < js.get_numbuttons() and js.get_button(i)}
        return SimpleNamespace(lx=ax(0), ly=-ax(1), rx=0.0, ry=0.0,
                               up=hy > 0, down=hy < 0, left=hx < 0, right=hx > 0), held

# Button → the command string the robot's processor takes (ui.py), so a
# button does exactly what the matching key / web button does
_BUTTON_COMMANDS = {
    "a":     ["speed"],
    "b":     ["_mode_user", "stop"],
    "x":     ["photo"],
    "y":     ["arc_toggle"],
    "back":  ["face_save"],
    "start": ["music_toggle"],
    "rstick": ["cam_centre"],
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
        if not pygame.joystick.get_init():
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
        count = pygame.joystick.get_count()
        sdl_ok = _sdl is not None and _sdl.get_init()
        for i in range(count):                         # a pad SDL knows the layout of first
            if sdl_ok and _sdl.is_controller(i):
                self._pad = _sdl.Controller(i)
                logger.info("Gamepad connected: %s", self._pad.name)
                return True
        if count:                                      # else any joystick, read raw
            try:
                self._pad = _RawPad(0)
            except pygame.error as e:
                logger.debug("Joystick open failed: %s", e)
                return False
            logger.info("Joystick connected (raw layout): %s", self._pad.name)
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
        if isinstance(pad, _RawPad):
            try:
                state, held = pad.state()
            except pygame.error as e:        # unplugged mid-read
                logger.debug("Joystick read failed: %s", e)
                self._pad = None
                return None
            state.pressed = held - self._held
            self._held = held
            return state
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
