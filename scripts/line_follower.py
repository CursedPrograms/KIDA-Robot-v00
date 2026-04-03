from gpiozero import LineSensor
import time

# Define pin numbers
IR01 = 16
IR02 = 26
IR03 = 21

# Setup
GPIO.setmode(GPIO.BCM)
GPIO.setup(IR01, GPIO.IN)
GPIO.setup(IR02, GPIO.IN)
GPIO.setup(IR03, GPIO.IN)

print("Starting Line Sensor Test (Ctrl+C to exit)")

try:
    while True:
        left = GPIO.input(IR01)
        center = GPIO.input(IR02)
        right = GPIO.input(IR03)

        print(f"Left: {'LINE' if not left else 'NO LINE'} | "
              f"Center: {'LINE' if not center else 'NO LINE'} | "
              f"Right: {'LINE' if not right else 'NO LINE'}")

        time.sleep(0.2)

except KeyboardInterrupt:
    print("\nExiting Line Sensor Test")

finally:
    GPIO.cleanup()

class LineFollower:
    def __init__(self, left_pin=17, right_pin=27, motors=None):
        self.left_sensor  = LineSensor(left_pin)
        self.right_sensor = LineSensor(right_pin)
        self.motors = motors

        # Speed tuning
        self.base_speed = 0.45
        self.turn_speed = 0.35
        self.max_speed  = 0.6

        # State
        self.last_direction = "forward"
        self.lost_count = 0

        # Recovery system (like your obstacle avoider)
        self.recovery_mode = False
        self.recovery_direction = None
        self.recovery_start = 0
        self.recovery_time = 1.5

    def read_sensors(self):
        return self.left_sensor.value, self.right_sensor.value

    def _start_recovery(self):
        self.recovery_mode = True
        self.recovery_start = time.time()

        # Commit to last known direction
        if self.last_direction == "left":
            self.recovery_direction = "left"
        elif self.last_direction == "right":
            self.recovery_direction = "right"
        else:
            self.recovery_direction = "left"

        print(f"🔄 LINE LOST — recovering {self.recovery_direction.upper()}")

    def _handle_recovery(self):
        if time.time() - self.recovery_start > self.recovery_time:
            self.recovery_mode = False
            self.lost_count = 0
            print("✅ Line reacquire timeout")
            return False

        if self.recovery_direction == "left":
            self.motors.turn_left(self.turn_speed)
        else:
            self.motors.turn_right(self.turn_speed)

        return True

    def follow_line(self):
        if self.motors is None:
            return False

        left, right = self.read_sensors()

        # 🧠 RECOVERY MODE
        if self.recovery_mode:
            return self._handle_recovery()

        # 🟢 ON TRACK
        if left and right:
            self.motors.forward(self.max_speed)
            self.last_direction = "forward"
            self.lost_count = 0
            return False

        # ↩️ DRIFT RIGHT → correct LEFT
        elif not left and right:
            self.motors.turn_left(self.turn_speed)
            self.last_direction = "left"
            self.lost_count = 0
            return True

        # ↪️ DRIFT LEFT → correct RIGHT
        elif left and not right:
            self.motors.turn_right(self.turn_speed)
            self.last_direction = "right"
            self.lost_count = 0
            return True

        # ❌ LINE LOST
        else:
            self.lost_count += 1

            if self.lost_count > 5:
                self._start_recovery()

            self.motors.stop()
            return True

    def cleanup(self):
        if self.motors:
            self.motors.stop()
        self.left_sensor.close()
        self.right_sensor.close()