import RPi.GPIO as GPIO
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
