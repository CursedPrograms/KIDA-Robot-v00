#!/usr/bin/env python3

"""
remote_client.py — network bridge between the remote controller and the
robot's Flask server (scripts/server.py):

  GET  /status          drive/mode/music/face state published by ui.py
  GET  /control/stats/  CPU, temp, RAM, latency, disk, boot (system_monitor.py)
  GET  /video_feed      MJPEG of the camera panel (320x240)
  GET  /qr.png          the dashboard QR shown in the left panel
  POST /command         {"command": "..."} — same strings ui.py's processor takes

This is the only controller module that touches the network — the drawing
is the robot's own render_helpers.py, fed from the fields kept here.
"""

import queue
import threading
import time

import requests

STATUS_INTERVAL = 0.25
STATS_INTERVAL  = 2.0

_DRIVE_WORDS = ("forward", "backward", "left", "right", "stop")


def _is_drive(command: str) -> bool:
    return command in _DRIVE_WORDS or command.startswith(("tank:", "drive:"))


class RemoteClient:
    def __init__(self, base_url: str):
        self.base_url  = base_url.rstrip("/")
        self.status    = {}
        self.stats     = {}
        self.jpeg      = None    # latest camera JPEG bytes (decoded on the main thread)
        self.jpeg_seq  = 0
        self.qr_png    = None
        self.connected = False
        self._running  = True
        self._session  = requests.Session()   # status polling
        self._cmd_sess = requests.Session()   # commands — sessions aren't thread-safe to share
        self._outbox   = queue.Queue()   # commands, sent one at a time in order

        for target in (self._poll_status, self._poll_stats, self._stream_cam,
                       self._fetch_qr, self._send_worker):
            threading.Thread(target=target, daemon=True).start()

    def stop(self) -> None:
        self._running = False
        self._outbox.put(None)           # wake the sender so it can exit

    # ── Polling ────────────────────────────────────────────────────────────────
    def _poll_status(self) -> None:
        while self._running:
            try:
                self.status    = self._session.get(f"{self.base_url}/status", timeout=1.5).json()
                self.connected = True
            except Exception:
                self.connected = False
            time.sleep(STATUS_INTERVAL)

    def _poll_stats(self) -> None:
        while self._running:
            try:
                r = requests.get(f"{self.base_url}/control/stats/", timeout=2)
                self.stats = r.json().get("stats", {}) or {}
            except Exception:
                pass
            time.sleep(STATS_INTERVAL)

    def _fetch_qr(self) -> None:
        while self._running and self.qr_png is None:
            try:
                r = requests.get(f"{self.base_url}/qr.png", timeout=3)
                if r.ok and r.content:
                    self.qr_png = r.content
                    return
            except Exception:
                pass
            time.sleep(2.0)

    # ── MJPEG reader ───────────────────────────────────────────────────────────
    def _stream_cam(self) -> None:
        while self._running:
            try:
                resp = requests.get(f"{self.base_url}/video_feed", stream=True, timeout=5)
                buf  = b""
                for chunk in resp.iter_content(chunk_size=4096):
                    if not self._running:
                        return
                    buf += chunk
                    # Take every complete JPEG in the buffer and keep the newest,
                    # so the picture never falls behind the live stream
                    latest = None
                    while True:
                        start = buf.find(b"\xff\xd8")
                        end   = buf.find(b"\xff\xd9", start + 2) if start != -1 else -1
                        if end == -1:
                            break
                        latest = buf[start:end + 2]
                        buf    = buf[end + 2:]
                    if latest:
                        self.jpeg = latest
                        self.jpeg_seq += 1
                    if len(buf) > 1_000_000:     # junk with no frame markers
                        buf = b""
            except Exception:
                time.sleep(1.0)

    # ── Outbound ───────────────────────────────────────────────────────────────
    def send(self, command: str) -> None:
        """Fire-and-forget, so a slow robot never stalls the HUD. Commands go
        out one at a time in order — with a thread each, a "stop" could
        overtake the "forward" before it and leave the robot driving."""
        self._outbox.put(command)

    def _send_worker(self) -> None:
        while self._running:
            batch = [self._outbox.get()]
            while not self._outbox.empty():           # everything queued up meanwhile
                batch.append(self._outbox.get_nowait())
            for i, command in enumerate(batch):
                if command is None:
                    return
                # A joystick sends a new drive value every frame — if the robot is
                # slow to answer, skip drive commands a newer one already replaces
                # instead of replaying a backlog (other commands all still go).
                if _is_drive(command) and any(_is_drive(c) for c in batch[i + 1:] if c):
                    continue
                self.send_now(command)

    def send_now(self, command: str) -> bool:
        try:
            r = self._cmd_sess.post(f"{self.base_url}/command", json={"command": command}, timeout=2)
            return r.ok
        except Exception:
            return False
