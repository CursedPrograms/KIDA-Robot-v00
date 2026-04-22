#!/usr/bin/env python3

"""
light_painting.py — Long-exposure still-capture helper.

Standalone usage:
  python light_painting.py [duration_seconds] [output_path]

Integrated usage (via ui.py / shared_state):
  The main loop calls _do_light_paint() from ui.py when triggered by the web UI.
  This module is kept as a standalone fallback / test tool.
"""

import sys
import time


def take_long_exposure(cam=None, duration: int = 10, filename: str = "long_exposure.jpg") -> str:
    """
    Perform a long-exposure capture.

    If *cam* is provided (a running Picamera2 instance) the camera is
    temporarily reconfigured for still mode.  If omitted a new instance is
    created (standalone mode).

    Returns the output filename on success, raises on error.
    """
    from picamera2 import Picamera2

    standalone = cam is None
    if standalone:
        cam = Picamera2()

    try:
        cam.stop()
        cam.configure(cam.create_still_configuration())
        cam.start()

        cam.set_controls({
            "ExposureTime": int(duration * 1_000_000),
            "AeEnable":     False,
            "AnalogueGain": 1.0,
            "AwbEnable":    False,
            "ColourGains":  (1.5, 1.5),
        })

        print(f"Settling (2 s)…")
        time.sleep(2)
        print(f"Shutter open — {duration}s exposure…")
        cam.capture_file(filename)
        print(f"Done → {filename}")
        return filename

    finally:
        if standalone:
            cam.stop()
        else:
            # Restore preview stream
            try:
                import libcamera
                cam.stop()
                cam.configure(cam.create_preview_configuration(
                    main={"size": (320, 240)},
                    transform=libcamera.Transform(hflip=1, vflip=1),
                ))
                cam.start()
            except Exception as e:
                print(f"Warning: could not restore preview: {e}", file=sys.stderr)


if __name__ == "__main__":
    dur  = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    path = sys.argv[2]      if len(sys.argv) > 2 else "long_exposure.jpg"
    take_long_exposure(duration=dur, filename=path)
