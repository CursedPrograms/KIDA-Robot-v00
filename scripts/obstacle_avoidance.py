#!/usr/bin/env python3

import time
import logging
from gpiozero import DistanceSensor, AngularServo

logger = logging.getLogger(__name__)


class ObstacleAvoidance:
    """
    Ultrasonic obstacle avoidance modelled on MILA's: cruise forward, and when
    something is closer than `threshold`, stop, swing the sensor servo left and
    right, then turn toward whichever side has more room.

    It's a non-blocking state machine — call check_and_avoid() once per frame
    and it advances one step, so the HUD, Flask commands and camera keep
    running while the sensor scans (no sleeps in the main loop).

    Speed follows the speed the user has selected (X / speed dots / web), the
    way MILA's obstacle mode uses its global speed: full selected speed when the
    path is clear, slowing down as an obstacle gets closer. Turns have a floor
    speed, since a pivot turn at low PWM barely moves.
    """

    # Servo angles (degrees, 0 = straight ahead). If the sensor looks right
    # when it should look left, swap the sign of SCAN_ANGLE.
    SCAN_ANGLE = 60

    # Timings (seconds)
    BRAKE_S        = 0.10   # pause after stopping before scanning
    SERVO_SCAN_S   = 0.40   # centre → one side
    SERVO_SWING_S  = 0.55   # one side → the other
    SERVO_CENTRE_S = 0.30   # side → centre
    REVERSE_S      = 0.30   # back off first if something is really close
    TURN_MIN_S     = 0.20   # always turn at least this long
    TURN_MAX_S     = 1.20   # give up waiting for a clear path after this
    TURN_AROUND_S  = 2.00   # max turn when both sides are blocked
    IDLE_RESET_S   = 0.50   # not called for this long → mode was left, start over

    TURN_MIN_SPEED    = 0.70  # pivot turns need torque
    REVERSE_MIN_SPEED = 0.50
    CRUISE_MIN_SPEED  = 0.30  # never slow below this while cruising

    def __init__(
        self,
        trigger_pin: int = 27,
        echo_pin: int = 22,
        servo_pin: int | None = 12,
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

        # Sensor servo is optional: without it the robot still avoids, it just
        # can't look, so it alternates turn direction instead.
        self.servo = None
        if servo_pin is not None:
            try:
                self.servo = AngularServo(
                    servo_pin, min_angle=-90, max_angle=90,
                    min_pulse_width=0.0005, max_pulse_width=0.0025,
                )
            except Exception as e:
                logger.warning("Sensor servo on GPIO %s unavailable (%s) — avoiding without scanning",
                               servo_pin, e)
        self._servo_release_at = 0.0
        self._look(0, settle=self.SERVO_CENTRE_S)

        self._turn_left_next = True   # fallback when there's no servo
        self._state      = "cruise"
        self._state_t    = 0.0
        self._last_step  = 0.0
        self._left_dist  = 0.0
        self._right_dist = 0.0
        self._turn_dir   = "left"
        self._turn_max   = self.TURN_MAX_S
        self._turn_speed = self.TURN_MIN_SPEED

        logger.info(
            "ObstacleAvoidance ready — trigger=%d echo=%d servo=%s threshold=%.2fm",
            trigger_pin, echo_pin, servo_pin if self.servo else "none", threshold,
        )

    # ── Public API ────────────────────────────────────────────

    def get_distance(self) -> float | None:
        try:
            return self.sensor.distance
        except Exception as e:
            logger.warning("Distance read error: %s", e)
            return None

    def check_and_avoid(self, speed: float = 0.6) -> bool:
        """
        Call each frame with the user's selected speed (0..1). Returns True
        while an obstacle is being handled (stopping, scanning or turning).
        """
        if self.motors is None:
            return False

        now = time.monotonic()
        if now - self._last_step > self.IDLE_RESET_S:
            self._enter("cruise", now)        # (re)entered autonomous mode
            self._look(0, settle=self.SERVO_CENTRE_S)
        self._last_step = now
        self._maybe_release_servo(now)

        distance = self.get_distance()
        if distance is None:
            self.motors.stop()
            return False

        elapsed = now - self._state_t
        st = self._state

        if st == "cruise":
            if distance >= self.threshold:
                self.motors.forward(self._cruise_speed(distance, speed))
                return False
            self.motors.stop()
            logger.debug("Obstacle at %.2fm — stopping", distance)
            self._enter("brake", now)

        elif st == "brake":
            if elapsed >= self.BRAKE_S:
                if distance < self.threshold * 0.4:   # too close to pivot safely
                    self.motors.backward(max(speed, self.REVERSE_MIN_SPEED))
                    self._enter("reverse", now)
                else:
                    self._start_scan(speed, now)

        elif st == "reverse":
            if elapsed >= self.REVERSE_S:
                self.motors.stop()
                self._start_scan(speed, now)

        elif st == "scan_left":
            if elapsed >= self.SERVO_SCAN_S:
                self._left_dist = distance
                self._look(-self.SCAN_ANGLE)
                self._enter("scan_right", now)

        elif st == "scan_right":
            if elapsed >= self.SERVO_SWING_S:
                self._right_dist = distance
                self._look(0, settle=self.SERVO_CENTRE_S)
                self._enter("centre", now)

        elif st == "centre":
            if elapsed >= self.SERVO_CENTRE_S:
                left, right = self._left_dist, self._right_dist
                self._turn_dir = "left" if left > right else "right"
                both_blocked   = max(left, right) < self.threshold
                self._turn_max = self.TURN_AROUND_S if both_blocked else self.TURN_MAX_S
                logger.debug("Scan L=%.2fm R=%.2fm — turning %s%s", left, right,
                             self._turn_dir, " (both blocked)" if both_blocked else "")
                self._start_turn(speed, now)

        elif st == "turn":
            # Sensor is centred again, so turn until it sees a clear path
            # (with some margin) rather than for a fixed time.
            clear = distance > self.threshold * 1.3
            if (elapsed >= self.TURN_MIN_S and clear) or elapsed >= self._turn_max:
                self.motors.stop()
                self._enter("cruise", now)

        return self._state != "cruise"

    def cleanup(self) -> None:
        if self.motors:
            self.motors.stop()
        self.sensor.close()
        if self.servo:
            self.servo.close()
        logger.info("ObstacleAvoidance cleaned up")

    # ── Internal ──────────────────────────────────────────────

    def _enter(self, state: str, now: float) -> None:
        self._state   = state
        self._state_t = now

    def _start_scan(self, speed: float, now: float) -> None:
        if self.servo is None:
            # Can't look — alternate, like the old behaviour
            self._turn_dir = "left" if self._turn_left_next else "right"
            self._turn_left_next = not self._turn_left_next
            self._turn_max = self.TURN_MAX_S
            self._start_turn(speed, now)
            return
        self._look(self.SCAN_ANGLE)
        self._enter("scan_left", now)

    def _start_turn(self, speed: float, now: float) -> None:
        self._turn_speed = max(speed, self.TURN_MIN_SPEED)
        if self._turn_dir == "left":
            self.motors.turn_left(self._turn_speed)
        else:
            self.motors.turn_right(self._turn_speed)
        self._enter("turn", now)

    def _look(self, angle: float, settle: float | None = None) -> None:
        """Point the sensor. With `settle`, stop driving the servo once it has
        had time to get there — gpiozero's software PWM makes an idle servo jitter."""
        if self.servo is None:
            return
        self.servo.angle = angle
        self._servo_release_at = time.monotonic() + settle if settle else 0.0

    def _maybe_release_servo(self, now: float) -> None:
        if self.servo and self._servo_release_at and now >= self._servo_release_at:
            self.servo.detach()
            self._servo_release_at = 0.0

    def _cruise_speed(self, distance: float, speed: float) -> float:
        """
        Full selected speed when the path is clear (≥ 1.5× threshold),
        easing down to half of it right at the threshold.
        """
        far = self.threshold * 1.5
        if distance >= far:
            scale = 1.0
        else:
            scale = 0.5 + 0.5 * (distance - self.threshold) / (far - self.threshold)
        return max(speed * scale, self.CRUISE_MIN_SPEED)
