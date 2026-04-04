# mode_control.py
"""
Mode definitions for KIDA.

Used by ui.py as follows:
  - Mode(i)       — create from tab index (0-3)
  - int(mode)     — compare against tab index for highlight
  - len(Mode)     — total number of modes for TAB key cycling
  - mode.name     — string shown in status bar / Flask /status
  - Mode.USER     — manual drive via keyboard / d-pad
  - Mode.AUTONOMOUS — obstacle-avoidance loop
  - Mode.LINE     — line-follower loop
  - Mode.FACE     — DeepFace scan; motors stopped, purple LED pulse

Each mode has an on_enter / on_exit hook that ui.py calls whenever
the active mode changes.  The hooks receive the shared robot context
so mode_control owns all the side-effects of switching rather than
scattering them across the main loop.
"""

from __future__ import annotations

import logging
import math
from enum import IntEnum

logger = logging.getLogger("kida.mode")


# ── Enum ──────────────────────────────────────────────────────────────────────

class Mode(IntEnum):
    USER       = 0   # manual keyboard / d-pad control
    AUTONOMOUS = 1   # obstacle-avoidance loop
    LINE       = 2   # line-follower loop
    FACE       = 3   # face / age / gender scan


# ── Context ───────────────────────────────────────────────────────────────────

class ModeContext:
    """
    Bag of hardware references passed into every hook.

    ui.py builds one instance after hardware is initialised:

        ctx = ModeContext(
            motors            = motors,
            led               = led,
            set_led_fn        = set_led,          # your existing set_led() closure
            face_enabled_event= _face_enabled,    # threading.Event
            face_results      = _face_results,    # shared list
            face_lock         = _face_lock,
            robot_state       = _robot_state,
            robot_state_lock  = _robot_state_lock,
        )

    Then every mode change becomes:

        mode = switch_mode(mode, Mode.FACE, ctx)
    """

    def __init__(
        self,
        motors,
        led,
        set_led_fn,
        face_enabled_event,
        face_results,
        face_lock,
        robot_state,
        robot_state_lock,
    ):
        self.motors           = motors
        self.led              = led
        self.set_led          = set_led_fn
        self.face_enabled     = face_enabled_event   # threading.Event
        self.face_results     = face_results
        self.face_lock        = face_lock
        self.robot_state      = robot_state
        self.robot_state_lock = robot_state_lock


# ── Hook implementations ──────────────────────────────────────────────────────

def _on_enter_user(ctx: ModeContext) -> None:
    ctx.motors.stop()
    ctx.set_led((0, 0, 0))
    logger.info("Mode -> USER")


def _on_exit_user(ctx: ModeContext) -> None:
    ctx.motors.stop()
    ctx.set_led((0, 0, 0))


def _on_enter_autonomous(ctx: ModeContext) -> None:
    ctx.set_led((0, 180, 160))   # teal = avoidance live
    logger.info("Mode -> AUTONOMOUS")


def _on_exit_autonomous(ctx: ModeContext) -> None:
    ctx.motors.stop()
    ctx.set_led((0, 0, 0))


def _on_enter_line(ctx: ModeContext) -> None:
    ctx.set_led((0, 80, 200))    # blue = line-follow live
    logger.info("Mode -> LINE")


def _on_exit_line(ctx: ModeContext) -> None:
    ctx.motors.stop()
    ctx.set_led((0, 0, 0))


def _on_enter_face(ctx: ModeContext) -> None:
    """Stop motors, arm the DeepFace worker thread, set purple LED."""
    ctx.motors.stop()
    ctx.set_led((80, 0, 80))
    ctx.face_enabled.set()       # wakes _face_worker in ui.py
    logger.info("Mode -> FACE  (DeepFace worker enabled)")


def _on_exit_face(ctx: ModeContext) -> None:
    """Disarm worker, wipe stale results, reset face counter."""
    ctx.face_enabled.clear()
    with ctx.face_lock:
        ctx.face_results.clear()
    with ctx.robot_state_lock:
        ctx.robot_state["face_count"] = 0
    ctx.motors.stop()
    ctx.set_led((0, 0, 0))
    logger.info("Mode <- FACE  (DeepFace worker disabled, results cleared)")


# ── Dispatch tables ───────────────────────────────────────────────────────────

_ON_ENTER: dict = {
    Mode.USER:       _on_enter_user,
    Mode.AUTONOMOUS: _on_enter_autonomous,
    Mode.LINE:       _on_enter_line,
    Mode.FACE:       _on_enter_face,
}

_ON_EXIT: dict = {
    Mode.USER:       _on_exit_user,
    Mode.AUTONOMOUS: _on_exit_autonomous,
    Mode.LINE:       _on_exit_line,
    Mode.FACE:       _on_exit_face,
}


# ── Public API ────────────────────────────────────────────────────────────────

def switch_mode(current: Mode, target: Mode, ctx: ModeContext) -> Mode:
    """
    Cleanly transition from *current* to *target*.

    Fires on_exit for the old mode then on_enter for the new one.
    Returns *target* so callers can write:

        mode = switch_mode(mode, Mode.FACE, ctx)

    No-ops (hooks not called) when current == target.
    """
    if current == target:
        return current

    for hook_table, mode_ref, label in (
        (_ON_EXIT,  current, "exit"),
        (_ON_ENTER, target,  "enter"),
    ):
        hook = hook_table.get(mode_ref)
        if hook:
            try:
                hook(ctx)
            except Exception as exc:
                logger.warning(
                    "Mode %s hook for %s raised: %s",
                    label, mode_ref.name, exc,
                )

    return target


def face_pulse_color(frame: int) -> tuple:
    """
    Purple LED colour for the FACE-mode animation frame.

    Replace the inline calculation in ui.py's render loop with:

        set_led(face_pulse_color(frame))
    """
    pulse = int((math.sin(frame * 0.2) * 0.5 + 0.5) * 128)
    return (pulse, 0, pulse)