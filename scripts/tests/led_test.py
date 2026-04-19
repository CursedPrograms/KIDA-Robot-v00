#!/usr/bin/env python3

import time
from rpi_ws281x import PixelStrip, Color

# LED strip configuration:
LED_COUNT = 3        # Number of LED pixels on your HAT
LED_PIN = 10         # GPIO pin connected to the pixels
LED_FREQ_HZ = 800000 # LED signal frequency (800khz)
LED_DMA = 10         # DMA channel to use for generating signal
LED_BRIGHTNESS = 150 # Set to 0 for darkest and 255 for brightest
LED_INVERT = False   # True to invert the signal
LED_CHANNEL = 0      # set to '1' for GPIOs 13, 19, 41, 45 or 53

def color_wipe(strip, color, wait_ms=50):
    """Wipe color across display a pixel at a time."""
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, color)
        strip.show()
        time.sleep(wait_ms/1000.0)

if __name__ == "__main__":
    # Create PixelStrip object
    strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
    strip.begin()

    print("Starting LED Test... Press Ctrl+C to stop.")
    try:
        while True:
            print("Red")
            color_wipe(strip, Color(255, 0, 0))  # Red
            time.sleep(1)
            
            print("Green")
            color_wipe(strip, Color(0, 255, 0))  # Green
            time.sleep(1)
            
            print("Blue")
            color_wipe(strip, Color(0, 0, 255))  # Blue
            time.sleep(1)

            print("Rainbow Cycle")
            color_wipe(strip, Color(255, 255, 255)) # White
            time.sleep(1)

    except KeyboardInterrupt:
        color_wipe(strip, Color(0, 0, 0), 10)
        print("\nLEDs turned off.")