#!/usr/bin/env python3

import logging
from gpiozero import Motor
import pygame

from shared_state import motor_lock, _lock_listeners

logger = logging.getLogger(__name__)

# The wall guard (like MILA's and IDA's guardDist, NORA's MANUAL_STOP_CM): she won't drive forward,
# whatever drives her (keys, tank, gamepad, web, line following), while the front sensor sees
# something closer than this. Turning and reversing still work, so she can always get away.
# Obstacle mode stops long before this (its threshold is 0.5 m), so the two never fight.
WALL_GUARD_M = 0.15


class _LockedMotor:
    """A gpiozero Motor that won't turn while the wheel lock is on (shared_state.motor_lock):
    forward/backward become stop. Every drive path ends at a Motor (this class's methods,
    ui.py's drive_tank, obstacle_avoidance, line_follower), so this one check covers them all."""

    def __init__(self, motor):
        self._motor = motor

    def forward(self, speed: float = 1.0) -> None:
        self._motor.stop() if motor_lock.is_set() else self._motor.forward(speed)

    def backward(self, speed: float = 1.0) -> None:
        self._motor.stop() if motor_lock.is_set() else self._motor.backward(speed)

    def __getattr__(self, name):          # stop, close, value... as the Motor has them
        return getattr(self._motor, name)


class MotorController:
    """Controls the left and right drive motors."""

    def __init__(self, left_pins: tuple = (24, 23), right_pins: tuple = (5, 6)):
        try:
            self.left  = _LockedMotor(Motor(forward=left_pins[0],  backward=left_pins[1]))
            self.right = _LockedMotor(Motor(forward=right_pins[0], backward=right_pins[1]))
            logger.info("Motors initialised on pins L=%s R=%s", left_pins, right_pins)
        except Exception as e:
            logger.error("Motor init failed: %s", e)
            raise
        _lock_listeners.append(self.stop)   # locking stops her at once
        self.distance = None   # () -> metres ahead or None; ui.py hands over the ultrasonic's

    def wall_ahead(self) -> bool:
        """Something within WALL_GUARD_M in front (False with no sensor or no reading)."""
        if not self.distance:
            return False
        try:
            d = self.distance()
        except Exception:
            return False
        return d is not None and 0 < d < WALL_GUARD_M

    # ── Primitives ────────────────────────────────────────────

    def stop(self) -> None:
        self.left.stop()
        self.right.stop()

    def forward(self, speed: float = 1.0) -> None:
        if self.wall_ahead():
            self.stop()
            return
        speed = self._clamp(speed)
        self.left.forward(speed)
        self.right.forward(speed)

    def backward(self, speed: float = 1.0) -> None:
        speed = self._clamp(speed)
        self.left.backward(speed)
        self.right.backward(speed)

    def turn_left(self, speed: float = 1.0) -> None:
        speed = self._clamp(speed)
        self.left.backward(speed)
        self.right.forward(speed)

    def turn_right(self, speed: float = 1.0) -> None:
        speed = self._clamp(speed)
        self.left.forward(speed)
        self.right.backward(speed)

    def drive(self, left: float, right: float) -> None:
        """Each wheel at its own signed speed (-1 back … 1 forward) — arc
        turns, joystick and gamepad driving (see drive_mix.py)."""
        if left > 0 and right > 0 and self.wall_ahead():   # going forward into a wall
            self.stop()
            return
        for wheel, v in ((self.left, left), (self.right, right)):
            v = max(-1.0, min(1.0, v))
            if   v > 0: wheel.forward(v)
            elif v < 0: wheel.backward(-v)
            else:       wheel.stop()

    # ── Tank / independent-wheel scheme ───────────────────────

    def control_tank(self, keys, speed: float) -> tuple[bool, bool]:
        """
        QA = left wheel forward/backward
        WS = right wheel forward/backward
        Returns (left_active, right_active).
        """
        speed = self._clamp(speed)
        left_active = right_active = False
        if keys[pygame.K_q] and keys[pygame.K_w] and self.wall_ahead():   # both tracks forward, into a wall
            self.stop()
            return False, False

        if keys[pygame.K_q]:
            self.left.forward(speed);  left_active = True
        elif keys[pygame.K_a]:
            self.left.backward(speed); left_active = True
        else:
            self.left.stop()

        if keys[pygame.K_w]:
            self.right.forward(speed);  right_active = True
        elif keys[pygame.K_s]:
            self.right.backward(speed); right_active = True
        else:
            self.right.stop()

        return left_active, right_active

    # ── Cleanup ───────────────────────────────────────────────

    def cleanup(self) -> None:
        self.stop()
        self.left.close()
        self.right.close()
        logger.info("Motors closed")

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _clamp(speed: float) -> float:
        return max(0.0, min(1.0, speed))
