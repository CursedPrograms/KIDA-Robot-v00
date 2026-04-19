#!/usr/bin/env python3

import time
import logging
from gpiozero import LineSensor

logger = logging.getLogger(__name__)


class LineFollower:
    """
    Three-sensor line follower with recovery mode.

    Sensor logic (active-low IR — line detected = sensor value 1):
      all 3 on         → on track       → drive forward
      left only        → drifted right  → correct left
      right only       → drifted left   → correct right
      centre only      → minor drift    → drive forward
      none detected    → line lost      → enter recovery
    """

    def __init__(self, left_pin: int = 16, centre_pin: int = 26, right_pin: int = 21, motors=None):
        self.IR01 = LineSensor(left_pin)    # left
        self.IR02 = LineSensor(centre_pin)  # centre
        self.IR03 = LineSensor(right_pin)   # right
        self.motors = motors

        self.base_speed  = 0.45
        self.turn_speed  = 0.35
        self.max_speed   = 0.60

        self._last_direction         = "forward"
        self._lost_count             = 0
        self._lost_threshold         = 5        # frames before recovery kicks in

        self._recovery_mode          = False
        self._recovery_direction: str | None = None
        self._recovery_start         = 0.0
        self._recovery_timeout       = 1.5     # seconds

        logger.info(
            "LineFollower ready — left_pin=%d centre_pin=%d right_pin=%d",
            left_pin, centre_pin, right_pin
        )

    # ── Public API ────────────────────────────────────────────

    def read_sensors(self) -> tuple[int, int, int]:
        return int(self.IR01.value), int(self.IR02.value), int(self.IR03.value)

    def follow_line(self) -> bool:
        """
        Call each frame. Returns True if correcting / recovering
        (caller can use this to indicate non-straight travel).
        """
        if self.motors is None:
            return False

        if self._recovery_mode:
            return self._do_recovery()

        left, centre, right = self.read_sensors()

        if not left and not centre and not right:
            # Line lost
            self._lost_count += 1
            self.motors.stop()
            if self._lost_count > self._lost_threshold:
                self._start_recovery()
            return True

        elif left and not right:
            # Drifted right → steer left
            self.motors.turn_left(self.turn_speed)
            self._last_direction = "left"
            self._lost_count     = 0
            return True

        elif right and not left:
            # Drifted left → steer right
            self.motors.turn_right(self.turn_speed)
            self._last_direction = "right"
            self._lost_count     = 0
            return True

        else:
            # Centre or all sensors — on track
            self.motors.forward(self.max_speed)
            self._last_direction = "forward"
            self._lost_count     = 0
            return False

    def cleanup(self) -> None:
        if self.motors:
            self.motors.stop()
        self.IR01.close()
        self.IR02.close()
        self.IR03.close()
        logger.info("LineFollower cleaned up")

    # ── Internal ──────────────────────────────────────────────

    def _start_recovery(self) -> None:
        self._recovery_mode      = True
        self._recovery_start     = time.time()
        self._recovery_direction = (
            self._last_direction if self._last_direction in ("left", "right") else "left"
        )
        logger.info("Line lost — recovering %s", self._recovery_direction)

    def _do_recovery(self) -> bool:
        if time.time() - self._recovery_start > self._recovery_timeout:
            self._recovery_mode = False
            self._lost_count    = 0
            logger.info("Recovery timeout — resuming normal follow")
            return False

        left, centre, right = self.read_sensors()
        if left or centre or right:
            self._recovery_mode = False
            self._lost_count    = 0
            logger.info("Line reacquired during recovery")
            return False

        if self._recovery_direction == "left":
            self.motors.turn_left(self.turn_speed)
        else:
            self.motors.turn_right(self.turn_speed)
        return True
