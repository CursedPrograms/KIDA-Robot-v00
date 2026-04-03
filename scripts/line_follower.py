import time
import logging
from gpiozero import LineSensor

logger = logging.getLogger(__name__)


class LineFollower:
    """
    Two-sensor line follower with recovery mode.

    Sensor logic (active-low IR — line detected = sensor value 1):
      left=1, right=1  → on track  → drive forward
      left=0, right=1  → drifted right → correct left
      left=1, right=0  → drifted left  → correct right
      left=0, right=0  → line lost     → enter recovery
    """

    def __init__(self, left_pin: int = 17, right_pin: int = 27, motors=None):
        self.left_sensor  = LineSensor(left_pin)
        self.right_sensor = LineSensor(right_pin)
        self.motors = motors

        self.base_speed  = 0.45
        self.turn_speed  = 0.35
        self.max_speed   = 0.60

        self._last_direction    = "forward"
        self._lost_count        = 0
        self._lost_threshold    = 5        # frames before recovery kicks in

        self._recovery_mode      = False
        self._recovery_direction: str | None = None
        self._recovery_start     = 0.0
        self._recovery_timeout   = 1.5     # seconds

        logger.info(
            "LineFollower ready — left_pin=%d right_pin=%d", left_pin, right_pin
        )

    # ── Public API ────────────────────────────────────────────

    def read_sensors(self) -> tuple[int, int]:
        return self.left_sensor.value, self.right_sensor.value

    def follow_line(self) -> bool:
        """
        Call each frame. Returns True if correcting / recovering
        (caller can use this to indicate non-straight travel).
        """
        if self.motors is None:
            return False

        if self._recovery_mode:
            return self._do_recovery()

        left, right = self.read_sensors()

        if left and right:
            # On track
            self.motors.forward(self.max_speed)
            self._last_direction = "forward"
            self._lost_count     = 0
            return False

        elif not left and right:
            # Drifted right → steer left
            self.motors.turn_left(self.turn_speed)
            self._last_direction = "left"
            self._lost_count     = 0
            return True

        elif left and not right:
            # Drifted left → steer right
            self.motors.turn_right(self.turn_speed)
            self._last_direction = "right"
            self._lost_count     = 0
            return True

        else:
            # Both sensors dark — line lost
            self._lost_count += 1
            self.motors.stop()
            if self._lost_count > self._lost_threshold:
                self._start_recovery()
            return True

    def cleanup(self) -> None:
        if self.motors:
            self.motors.stop()
        self.left_sensor.close()
        self.right_sensor.close()
        logger.info("LineFollower cleaned up")

    # ── Internal ──────────────────────────────────────────────

    def _start_recovery(self) -> None:
        self._recovery_mode      = True
        self._recovery_start     = time.time()
        # Spin toward the last known direction
        self._recovery_direction = (
            self._last_direction if self._last_direction in ("left", "right") else "left"
        )
        logger.info("Line lost — recovering %s", self._recovery_direction)

    def _do_recovery(self) -> bool:
        if time.time() - self._recovery_start > self._recovery_timeout:
            # Give up and reset
            self._recovery_mode = False
            self._lost_count    = 0
            logger.info("Recovery timeout — resuming normal follow")
            return False

        # Re-check sensors — exit recovery if line reacquired
        left, right = self.read_sensors()
        if left or right:
            self._recovery_mode = False
            self._lost_count    = 0
            logger.info("Line reacquired during recovery")
            return False

        if self._recovery_direction == "left":
            self.motors.turn_left(self.turn_speed)
        else:
            self.motors.turn_right(self.turn_speed)
        return True
