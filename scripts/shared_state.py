#!/usr/bin/env python3

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
    "led": [0, 0, 0], "face_count": 0, "track_name": "",
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

# ── Web camera feed (latest JPEG frame for /video_feed) ────────────────────────
_cam_jpeg:      list            = [b""]   # mutable single-element container
_cam_jpeg_lock: threading.Lock  = threading.Lock()

# ── Camera mutual exclusion (held during long-exposure light painting) ──────────
_cam_lock: threading.Lock = threading.Lock()

# ── Light painting ──────────────────────────────────────────────────────────────
_light_paint_state: dict = {
    "pending": False, "active": False,
    "progress": 0.0, "last_file": "", "duration": 10,
}
_light_paint_lock: threading.Lock = threading.Lock()

# ── Media — tracks latest captured photo/video for client auto-download ─────────
_media_state: dict         = {"last_photo": "", "last_video": ""}
_media_lock:  threading.Lock = threading.Lock()

# ── QR code drive mode ─────────────────────────────────────────────────────────
_qr_state: dict = {"action": ""}   # current visible KIDA QR action, "" if none
_qr_lock:    threading.Lock  = threading.Lock()
_qr_frame_q: queue.Queue     = queue.Queue(maxsize=1)
_qr_enabled: threading.Event = threading.Event()

# ── Dance mode ─────────────────────────────────────────────────────────────────
_dance_active: threading.Event = threading.Event()  # set while dance is running

# ── Sleep / low-power idle ─────────────────────────────────────────────────────
_sleep_active: threading.Event = threading.Event()  # set while robot is sleeping

# ── Live audio amplitudes (for web waveform visualiser) ────────────────────────
_audio_amps: list        = []          # list[float] 0.0-1.0, length = num_bars
_audio_amps_lock: threading.Lock = threading.Lock()
