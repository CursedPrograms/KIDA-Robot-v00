from gpiozero import DistanceSensor
import time


class ObstacleAvoidance:
    def __init__(self, trigger_pin=27, echo_pin=22, motors=None, threshold=0.5):
        # Faster response (no smoothing delay)
        self.sensor = DistanceSensor(
            echo=echo_pin,
            trigger=trigger_pin,
            max_distance=2.0,
            queue_len=1
        )

        self.motors = motors
        self.threshold = threshold
        self.turn_left_next = True

        # More realistic speeds for a Pi 3 robot
        self.min_speed = 0.3
        self.max_speed = 0.6

    def get_distance(self):
        try:
            return self.sensor.distance
        except Exception:
            return None

    def _map_speed(self, distance):
        if distance >= self.threshold:
            return self.max_speed

        if distance <= 0:
            return self.min_speed

        ratio = distance / self.threshold
        speed = self.min_speed + (self.max_speed - self.min_speed) * ratio
        return max(self.min_speed, min(self.max_speed, speed))

    def check_and_avoid(self):
        if self.motors is None:
            return False

        distance = self.get_distance()
        if distance is None:
            return False

        # Debug (optional)
        # print(f"Distance: {distance:.2f} m")

        # 🚨 OBSTACLE DETECTED
        if distance < self.threshold:

            self.motors.stop()
            time.sleep(0.05)

            # Reverse briefly (shorter, faster reaction)
            self.motors.backward(self.min_speed)
            start_time = time.time()
            while time.time() - start_time < 0.3:
                pass

            self.motors.stop()
            time.sleep(0.05)

            # Turn (short controlled turn)
            if self.turn_left_next:
                self.motors.turn_left(self.min_speed)
            else:
                self.motors.turn_right(self.min_speed)

            self.turn_left_next = not self.turn_left_next

            start_time = time.time()
            while time.time() - start_time < 0.55:
                pass

            self.motors.stop()
            return True

        # ✅ PATH CLEAR
        else:
            speed = self._map_speed(distance)
            self.motors.forward(speed)
            return False

    def cleanup(self):
        if self.motors:
            self.motors.stop()
        self.sensor.close()
