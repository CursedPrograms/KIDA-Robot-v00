#!/usr/bin/env python3

"""
drive_mix.py — turns keys / sticks into left & right wheel speeds.

Shared by the robot (scripts/ui.py) and the remote controller
(controller/main.py); static/js/main.js has the same maths for the web
dashboard. Wheel speeds are -1..1 (fraction of the selected speed, + is
forward) — the robot multiplies them by its speed setting.

Pure Python — no pygame / hardware imports.
"""

# Arc turns: the inside wheel keeps turning at this fraction instead of
# stopping or reversing, so W+A curves left rather than spinning on the spot.
ARC_INNER = 0.4

# Stick deadzone — centred sticks drift a little
DEADZONE = 0.15


def keys_to_wheels(fwd: bool, back: bool, left: bool, right: bool, arc: bool):
    """(left, right) wheel speeds for WASD / d-pad style input, or None if nothing pressed.

      W / S alone        → straight forward / back
      A / D alone        → spin on the spot
      W+A, W+D, S+A, S+D → arc turn (arc=True): the inside wheel slows to
                           ARC_INNER instead of stopping
                           (arc=False: drives straight, the turn key is ignored)
    """
    throttle = int(fwd) - int(back)
    steer    = int(right) - int(left)
    if throttle == 0 and steer == 0:
        return None
    if throttle == 0:
        return (float(steer), float(-steer))          # pivot
    if steer == 0 or not arc:
        return (float(throttle), float(throttle))
    inner = ARC_INNER * throttle
    return (inner, float(throttle)) if steer < 0 else (float(throttle), inner)


def _deadzone(v: float) -> float:
    if abs(v) < DEADZONE:
        return 0.0
    # rescale so output still starts at 0 just past the deadzone
    return (abs(v) - DEADZONE) / (1 - DEADZONE) * (1 if v > 0 else -1)


def stick_to_wheels(x: float, y: float):
    """(left, right) for an analog stick, or None when centred.
    x: -1 left … 1 right, y: -1 back … 1 forward (screen/gamepad Y already flipped)."""
    x, y = _deadzone(max(-1.0, min(1.0, x))), _deadzone(max(-1.0, min(1.0, y)))
    if x == 0 and y == 0:
        return None
    l, r = y + x, y - x
    m = max(1.0, abs(l), abs(r))
    return (l / m, r / m)


def tank_sticks_to_wheels(left_y: float, right_y: float):
    """(left, right) for tank driving with two sticks (each -1 back … 1 forward)."""
    l, r = _deadzone(left_y), _deadzone(right_y)
    return None if l == 0 and r == 0 else (l, r)


def wheels_to_command(l: float, r: float) -> str:
    """Command string the robot's processor takes. The four plain moves keep
    their old names; anything in between is drive:<left>:<right>."""
    named = {(1.0, 1.0): "forward", (-1.0, -1.0): "backward",
             (-1.0, 1.0): "left",   (1.0, -1.0): "right"}
    # 0.05 steps: plenty of resolution, and a stick that's barely moving
    # doesn't produce a new command every frame
    l, r = round(l * 20) / 20 + 0.0, round(r * 20) / 20 + 0.0     # + 0.0: no "-0.00"
    return named.get((l, r), f"drive:{l:.2f}:{r:.2f}")


def wheels_label(l: float, r: float) -> str:
    """What the HUD's DIR readout says for these wheel speeds."""
    if abs(l) < 0.01 and abs(r) < 0.01:
        return "STOPPED"
    if abs(l - r) < 0.05:
        return "FORWARD" if l > 0 else "BACKWARD"
    if l * r < 0 or abs(l) < 0.01 or abs(r) < 0.01:
        return "RIGHT" if l > r else "LEFT"            # spin / one wheel only
    going = "FWD" if l + r > 0 else "BACK"
    turning = "RIGHT" if abs(l) > abs(r) else "LEFT"
    return f"ARC {going} {turning}"
