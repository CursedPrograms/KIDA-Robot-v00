#!/usr/bin/env python3

# servo_control.py

from gpiozero import Servo
from time import sleep

# Hardware Configuration
# Updated to include the new GPIO 19
PINS = [12, 13, 19]
servos = []