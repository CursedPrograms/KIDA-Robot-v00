#!/usr/bin/env python3

from gpiozero import Servo
from time import sleep

# Hardware Configuration
SERVO0_PIN = 12
SERVO1_PIN = 13

# Initialize Servos
# We use a standard pulse width range (min=1ms, max=2ms)
servo0 = Servo(SERVO0_PIN)
servo1 = Servo(SERVO1_PIN)

def test_sweep(servo_obj, name):
    print(f"--- Testing {name} ---")
    
    print("Moving to MIN position...")
    servo_obj.min()
    sleep(1)
    
    print("Moving to MID position...")
    servo_obj.mid()
    sleep(1)
    
    print("Moving to MAX position...")
    servo_obj.max()
    sleep(1)
    
    print("Returning to MID...")
    servo_obj.mid()
    sleep(0.5)

try:
    print("Starting Servo Test...")
    test_sweep(servo0, "Servo 0 (Pin 12)")
    test_sweep(servo1, "Servo 1 (Pin 13)")
    print("Test Complete!")

except KeyboardInterrupt:
    print("\nTest stopped by user.")

finally:
    # Cleanup
    servo0.value = None
    servo1.value = None