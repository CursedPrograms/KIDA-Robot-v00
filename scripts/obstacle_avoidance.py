import time
import logging
from gpiozero import DistanceSensor

logger = logging.getLogger(__name__)


class ObstacleAvoidance:
    """
    Ultrasonic obstacle avoidance with graduated speed, alternating turns,
    and a stuck-detection system that commits to one direction when the robot
    is bouncing between obstacles.
    """

    def __init__(
        self,
        trigger_pin: int = 27,
        echo_pin: int = 22,
        motors=None,
        threshold: float = 0.5,
    ):
        self.sensor = DistanceSensor(
            echo=echo_pin,
            trigger=trigger_pin,
            max_distance=2.0,
            queue_len=1,          # fastest possible response
        )
        self.motors    = motors
        self.threshold = threshold

        self.min_speed = 0.3
        self.max_speed = 0.6

        # Alternating turn direction
        self._turn_left_next = True

        # Stuck detection
        self._obstacle_count      = 0
        self._last_obstacle_time  = 0.0
        self._stuck_threshold     = 3      # hits within the time window
        self._stuck_window        = 2.0    # seconds
        self._committed_dir: str | None = None
        self._commitment_start    = 0.0
        self._commitment_timeout  = 5.0    # seconds before re-evaluating

        logger.info(
            "ObstacleAvoidance ready — trigger=%d echo=%d threshold=%.2fm",
            trigger_pin, echo_pin, threshold,
        )

    # ── Public API ────────────────────────────────────────────

    def get_distance(self) -> float | None:
        try:
            return self.sensor.distance
        except Exception as e:
            logger.warning("Distance read error: %s", e)
            return None

    def check_and_avoid(self) -> bool:
        """
        Call each frame. Returns True if an obstacle was handled
        (caller should skip normal drive logic).
        """
        if self.motors is None:
            return False

        distance = self.get_distance()
        if distance is None:
            return False

        if distance < self.threshold:
            self._handle_obstacle()
            return True

        # Clear path — decay stuck counter and drive at graduated speed
        if distance > self.threshold * 1.5:
            self._obstacle_count = max(0, self._obstacle_count - 1)

        self.motors.forward(self._graduated_speed(distance))
        return False

    def cleanup(self) -> None:
        if self.motors:
            self.motors.stop()
        self.sensor.close()
        logger.info("ObstacleAvoidance cleaned up")

    # ── Internal ──────────────────────────────────────────────

    def _handle_obstacle(self) -> None:
        self._update_stuck()

        self.motors.stop()
        time.sleep(0.05)

        # Brief reverse
        self.motors.backward(self.min_speed)
        time.sleep(0.3)
        self.motors.stop()
        time.sleep(0.05)

        # Choose direction and duration
        if self._is_committed():
            turn_dir      = self._committed_dir
            turn_duration = 0.7
            logger.debug("Stuck mode — committing %s", turn_dir)
        else:
            turn_dir      = "left" if self._turn_left_next else "right"
            turn_duration = 0.55
            self._turn_left_next = not self._turn_left_next

        if turn_dir == "left":
            self.motors.turn_left(self.min_speed)
        else:
            self.motors.turn_right(self.min_speed)

        time.sleep(turn_duration)
        self.motors.stop()

    def _update_stuck(self) -> None:
        now = time.time()
        if now - self._last_obstacle_time < self._stuck_window:
            self._obstacle_count += 1
        else:
            self._obstacle_count = 1
        self._last_obstacle_time = now

        if self._obstacle_count >= self._stuck_threshold and self._committed_dir is None:
            self._committed_dir   = "left" if self._turn_left_next else "right"
            self._commitment_start = now
            logger.info("Stuck detected — committing to %s", self._committed_dir)

    def _is_committed(self) -> bool:
        if self._committed_dir is None:
            return False
        if time.time() - self._commitment_start > self._commitment_timeout:
            logger.info("Commitment timeout — resuming normal avoidance")
            self._committed_dir  = None
            self._obstacle_count = 0
            return False
        return True

    def _graduated_speed(self, distance: float) -> float:
        """Scale speed linearly between min and max based on proximity."""
        ratio = min(distance / self.threshold, 1.0)
        return self.min_speed + (self.max_speed - self.min_speed) * ratio
