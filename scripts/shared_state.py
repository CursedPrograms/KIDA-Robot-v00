#!/usr/bin/env python3

"""
shared_state.py — Global queues, locks, and state dicts shared across modules.
Import from here; never re-declare these elsewhere.
"""

import io
import queue
import threading
import time

# ── Command queue (Flask → main loop) ─────────────────────────────────────────
command_queue: queue.Queue = queue.Queue()

# ── Wheel lock (like NORA's) ───────────────────────────────────────────────────
# Set = the wheels won't turn: motor_control.py makes every forward/backward a stop,
# whatever asked (keys, web, gamepad, autonomous, line, /do). Stop always works.
# Boots locked, like NORA. Locking is free (/motorlockOn, /do lock_wheels, K on
# her keyboard); unlocking needs MotorPassword (/motorlockOff?pw=) or a person
# at the robot (K).
motor_lock = threading.Event()
motor_lock.set()
_lock_listeners: list = []          # MotorController.stop of each motor set


def lock_wheels() -> None:
    motor_lock.set()
    for stop in list(_lock_listeners):
        try:
            stop()
        except Exception:
            pass


def unlock_wheels() -> None:
    motor_lock.clear()


STARTED = time.time()               # for /status uptime_s
music_ref: dict = {"player": None}  # ui.py's MusicPlayer, for fleet_music.py (/music)

# ── Robot telemetry ────────────────────────────────────────────────────────────
_robot_state: dict = {
    "direction": "STOPPED", "speed": 0.4, "speed_idx": 0, "ctrl_scheme": 1,
    "mode": "USER", "video_rec": False, "music_playing": False, "track": "",
    "led": [0, 0, 0], "face_count": 0, "faces": [], "face_scan": True,
    "deepface_ok": False, "frame": 0,
}
_robot_state_lock = threading.Lock()

# ── Camera frame for /video_feed (ui.py → Flask) ──────────────────────────────
# ui.py only JPEG-encodes frames while someone has asked for one recently,
# so the Pi doesn't pay for encoding when no controller/browser is watching.
_jpeg_frame: bytes = b""
_jpeg_cond = threading.Condition()
_last_viewer = 0.0
VIEWER_TIMEOUT = 5.0


def frame_wanted() -> bool:
    return time.monotonic() - _last_viewer < VIEWER_TIMEOUT


def publish_frame(pil_img, size=(320, 240)) -> None:
    """Encode a PIL frame (as shown on the HUD) for streaming."""
    global _jpeg_frame
    buf = io.BytesIO()
    pil_img.resize(size).save(buf, "JPEG", quality=70)
    with _jpeg_cond:
        _jpeg_frame = buf.getvalue()
        _jpeg_cond.notify_all()


def wait_frame(timeout: float = 1.0) -> bytes:
    """Block until a new frame is published (or timeout); marks a viewer."""
    global _last_viewer
    _last_viewer = time.monotonic()
    with _jpeg_cond:
        _jpeg_cond.wait(timeout)
        return _jpeg_frame

# ── System stats ───────────────────────────────────────────────────────────────
_system_stats: dict = {}
_stats_lock = threading.Lock()

# ── Face detection ─────────────────────────────────────────────────────────────
_face_results: list = []
_face_lock:     threading.Lock  = threading.Lock()
_face_frame_q:  queue.Queue     = queue.Queue(maxsize=1)
_face_enabled:  threading.Event = threading.Event()
_deepface_ok:   threading.Event = threading.Event()
