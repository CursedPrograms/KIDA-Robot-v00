import RPi.GPIO as GPIO
import time

TRIGGER_PIN = 27
ECHO_PIN = 22

GPIO.setmode(GPIO.BCM)
GPIO.setup(TRIGGER_PIN, GPIO.OUT)
GPIO.setup(ECHO_PIN, GPIO.IN)

def get_distance():
    # Send trigger pulse
    GPIO.output(TRIGGER_PIN, True)
    time.sleep(0.00001)
    GPIO.output(TRIGGER_PIN, False)

    # Wait for echo to go high (with timeout)
    start_time = time.time()
    timeout = start_time + 0.04  # 40 ms timeout
    while GPIO.input(ECHO_PIN) == 0 and time.time() < timeout:
        start_time = time.time()
    if time.time() >= timeout:
        return None  # Timeout waiting for echo high

    # Wait for echo to go low (with timeout)
    end_time = time.time()
    timeout = end_time + 0.04
    while GPIO.input(ECHO_PIN) == 1 and time.time() < timeout:
        end_time = time.time()
    if time.time() >= timeout:
        return None  # Timeout waiting for echo low

    duration = end_time - start_time
    distance = (duration * 34300) / 2
    return distance

try:
    while True:
        distance = get_distance()
        if distance is None:
            print("Timeout: No echo received")
        else:
            print(f"Distance: {distance:.2f} cm")
        time.sleep(0.5)

except KeyboardInterrupt:
    print("Exiting...")

finally:
    GPIO.cleanup()
