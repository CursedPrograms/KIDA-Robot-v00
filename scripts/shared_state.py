"""
shared_state.py — Global queues, locks, and state dicts shared across modules.
Import from here; never re-declare these elsewhere.
"""

import queue
import threading

# ── Command queue (Flask → main loop) ─────────────────────────────────────────
command_queue: queue.Queue = queue.Queue()

# ── Robot telemetry ────────────────────────────────────────────────────────────
_robot_state: dict = {
    "direction": "STOPPED", "speed": 0.6, "mode": "USER",
    "video_rec": False, "music_playing": False,
    "led": [0, 0, 0], "face_count": 0,
}
_robot_state_lock = threading.Lock()

# ── System stats ───────────────────────────────────────────────────────────────
_system_stats: dict = {}
_stats_lock = threading.Lock()

# ── Face detection ─────────────────────────────────────────────────────────────
_face_results: list = []
_face_lock:     threading.Lock  = threading.Lock()
_face_frame_q:  queue.Queue     = queue.Queue(maxsize=1)
_face_enabled:  threading.Event = threading.Event()
_deepface_ok:   threading.Event = threading.Event()
