import time
from picamera2 import Picamera2

# Initialize camera
picam2 = Picamera2()
config = picam2.create_still_configuration()
picam2.configure(config)
picam2.start()

def take_long_exposure(duration_seconds=10, filename="long_exposure.jpg"):
    print(f"📸 Preparing {duration_seconds}s exposure...")
    
    # Convert seconds to microseconds
    exposure_time_us = int(duration_seconds * 1_000_000)
    
    # Set manual controls
    # Note: We set these BEFORE capturing
    picam2.set_controls({
        "ExposureTime": exposure_time_us,
        "AeEnable": False,      # Disable Auto Exposure
        "AnalogueGain": 1.0,    # Keep gain low to reduce 'noise' (graininess)
        "AwbEnable": False,     # Disable Auto White Balance for consistency
        "ColourGains": (1.5, 1.5) 
    })
    
    # Wait for settings to settle
    time.sleep(2) 
    
    print("🚀 Shutter OPEN...")
    picam2.capture_file(filename)
    print(f"✅ Shutter CLOSED. Saved as {filename}")

try:
    take_long_exposure(10) # 10-second exposure
finally:
    picam2.stop()