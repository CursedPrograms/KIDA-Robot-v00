#!/usr/bin/env python3

"""
camera_servo.py — the servo KIDA's camera sits on (GPIO 13 on the Freenove V2 board).

  Manual   pan it from the dashboard / POST /camera_servo (left, right, an angle, centre)
  Follow   looks at a person: OpenCV's Haar face cascade on 320x240 grey frames (the lightest
           detector there is, no neural network), and turns a little towards the face each frame
  Sweep    to one end, record, sweep slowly to the other end (sweep time from the slider), stop
           recording, back to the centre. The video goes to videos/sweep_<time>.mp4

A normal 180° servo (the arm kit's gripper servo): 0-180°, 90 = straight ahead. Settings in
config.json under Config.CameraServo (Pin, Min, Max, Centre, Invert, FollowOnBoot). If it turns
away from faces instead of towards them, set "Invert": true.

Frames come from ui.py (the camera has one owner): it calls feed(pil) while wants_frames().
Standalone, it centres the servo: python3 scripts/camera_servo.py   (KIDA's service stopped first,
or the pin is busy; while she runs use the dashboard's CENTRE button or POST /camera_servo).
"""

import json
import logging
import os
import queue
import threading
import time

logger = logging.getLogger("kida.camservo")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULTS = {"Pin": 13, "Min": 0, "Max": 180, "Centre": 90, "Invert": False, "FollowOnBoot": False}

FRAME_W, FRAME_H = 320, 240
DEADZONE_PX  = 30        # a face this close to the middle counts as centred: no jitter
MAX_STEP_DEG = 6         # most it turns per frame while following
IDLE_DETACH_S = 0.8      # stop driving the pin this long after the last move: no buzzing at rest
SWEEP_MIN_S, SWEEP_MAX_S = 3.0, 60.0


def load_settings() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(os.path.join(_ROOT, "config.json"), encoding="utf-8") as f:
            cfg.update(json.load(f)["Config"].get("CameraServo", {}))
    except (OSError, ValueError, KeyError):
        pass
    return cfg


class CameraServo:
    def __init__(self, settings: dict = None, servo=None, cascade=None, videos_dir=None):
        self.cfg = settings or load_settings()
        self.lo, self.hi = float(self.cfg["Min"]), float(self.cfg["Max"])
        self.centre_deg = float(self.cfg["Centre"])
        self.invert = bool(self.cfg["Invert"])
        self.videos_dir = videos_dir or os.path.join(_ROOT, "videos")
        self._servo = servo
        self._cascade = cascade
        self._lock = threading.Lock()
        self._frames: queue.Queue = queue.Queue(maxsize=1)
        self.angle = self.centre_deg
        self.mode = "manual"              # manual / follow / sweep
        self.face = None                  # the face it's looking at: {x, y, w, h} in 320x240
        self.sweep = {"seconds": 10.0, "file": None, "progress": 0.0}
        self.error = None
        self._last_move = 0.0
        self._stop = threading.Event()

    # ── the servo ──────────────────────────────────────────────────────────────
    def _hw(self):
        if self._servo is None:
            from gpiozero import AngularServo
            self._servo = AngularServo(int(self.cfg["Pin"]), min_angle=0, max_angle=180,
                                       min_pulse_width=0.0005, max_pulse_width=0.0025)
        return self._servo

    def set_angle(self, deg: float) -> float:
        deg = max(self.lo, min(self.hi, float(deg)))
        with self._lock:
            try:
                self._hw().angle = deg
                self.error = None
            except Exception as e:          # no servo / no GPIO (a PC): remember why, keep going
                self.error = str(e)
            self.angle = deg
            self._last_move = time.monotonic()
        return deg

    def nudge(self, delta: float) -> float:
        return self.set_angle(self.angle + delta)

    def centre(self) -> float:
        return self.set_angle(self.centre_deg)

    def _release_when_idle(self) -> None:
        with self._lock:
            if self._servo is not None and self._last_move and time.monotonic() - self._last_move > IDLE_DETACH_S:
                try:
                    self._servo.detach()
                except Exception:
                    pass
                self._last_move = 0.0

    # ── modes ──────────────────────────────────────────────────────────────────
    def set_follow(self, on: bool) -> None:
        if self.mode == "sweep":
            return
        self.mode = "follow" if on else "manual"
        self.face = None

    def start_sweep(self, seconds: float) -> bool:
        if self.mode == "sweep":
            return False
        self.sweep = {"seconds": max(SWEEP_MIN_S, min(SWEEP_MAX_S, float(seconds))), "file": None, "progress": 0.0}
        self._after_sweep = self.mode
        self.mode = "sweep"
        threading.Thread(target=self._sweep_run, daemon=True, name="camservo-sweep").start()
        return True

    def stop_sweep(self) -> None:
        if self.mode == "sweep":
            self.sweep["cancel"] = True

    def wants_frames(self) -> bool:
        return self.mode in ("follow", "sweep")

    def feed(self, pil_img) -> None:
        """ui.py hands over each camera frame while wants_frames(); only the newest is kept."""
        try:
            self._frames.get_nowait()
        except queue.Empty:
            pass
        try:
            self._frames.put_nowait(pil_img)
        except queue.Full:
            pass

    def _next_frame(self, timeout=0.5):
        try:
            return self._frames.get(timeout=timeout)
        except queue.Empty:
            return None

    def status(self) -> dict:
        return {"angle": round(self.angle, 1), "mode": self.mode, "face": self.face,
                "min": self.lo, "max": self.hi, "centre": self.centre_deg,
                "sweep": {k: v for k, v in self.sweep.items() if k != "cancel"}, "error": self.error}

    # ── follow: look at the person ─────────────────────────────────────────────
    def _detector(self):
        if self._cascade is None:
            import cv2
            self._cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        return self._cascade

    def follow_step(self, pil_img):
        """One frame of following: find the biggest face, turn a bit towards it. Returns the face or None."""
        import numpy as np
        import cv2
        grey = cv2.cvtColor(np.array(pil_img.convert("RGB").resize((FRAME_W, FRAME_H))), cv2.COLOR_RGB2GRAY)
        faces = self._detector().detectMultiScale(grey, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        if len(faces) == 0:
            self.face = None
            return None
        x, y, w, h = (int(v) for v in max(faces, key=lambda f: f[2] * f[3]))
        self.face = {"x": x, "y": y, "w": w, "h": h}
        error = (x + w / 2) - FRAME_W / 2          # + = the face is right of the middle
        if abs(error) > DEADZONE_PX:
            step = max(1.0, min(MAX_STEP_DEG, abs(error) / (FRAME_W / 2) * MAX_STEP_DEG * 1.5))
            turn = -step if error > 0 else step     # a higher angle looks left on most mounts
            self.nudge(-turn if self.invert else turn)
        return self.face

    # ── sweep: record one end to the other ─────────────────────────────────────
    def _sweep_run(self) -> None:
        writer = None
        try:
            start, end = self.lo, self.hi
            self.set_angle(start)
            time.sleep(0.8)                          # get there before recording
            import numpy as np
            import cv2
            os.makedirs(self.videos_dir, exist_ok=True)
            path = os.path.join(self.videos_dir, time.strftime("sweep_%Y%m%d_%H%M%S.mp4"))
            seconds = self.sweep["seconds"]
            t0 = time.monotonic()
            while not self.sweep.get("cancel"):
                p = min(1.0, (time.monotonic() - t0) / seconds)
                self.sweep["progress"] = round(p, 3)
                self.set_angle(start + (end - start) * p)
                frame = self._next_frame(0.2)
                if frame is not None:
                    bgr = cv2.cvtColor(np.array(frame.convert("RGB")), cv2.COLOR_RGB2BGR)
                    if writer is None:
                        h, w = bgr.shape[:2]
                        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (w, h))
                        self.sweep["file"] = os.path.basename(path)
                    writer.write(bgr)
                if p >= 1.0:
                    break
            logger.info("Sweep recorded: %s", self.sweep["file"])
        except Exception as e:
            self.error = f"sweep: {e}"
            logger.warning("Sweep failed: %s", e)
        finally:
            if writer is not None:
                writer.release()
            self.centre()
            self.mode = getattr(self, "_after_sweep", "manual")
            self.sweep.pop("cancel", None)

    # ── the worker ─────────────────────────────────────────────────────────────
    def _run(self) -> None:
        while not self._stop.is_set():
            if self.mode == "follow":
                frame = self._next_frame(0.5)
                if frame is not None:
                    try:
                        self.follow_step(frame)
                    except Exception as e:
                        self.error = f"follow: {e}"
                        time.sleep(1.0)
            else:
                time.sleep(0.2)
            if self.mode == "manual":
                self._release_when_idle()

    def start(self) -> "CameraServo":
        self.centre()
        if self.cfg.get("FollowOnBoot"):
            self.mode = "follow"
        threading.Thread(target=self._run, daemon=True, name="camservo").start()
        return self

    def close(self) -> None:
        self._stop.set()
        if self._servo is not None:
            try:
                self._servo.detach()
            except Exception:
                pass


camera_servo = CameraServo()      # the one KIDA uses: ui.py feeds it, server.py drives it


def command(body: dict) -> tuple:
    """POST /camera_servo: {"action": "centre" | "left" | "right" | "angle" | "follow" | "sweep" | "stop_sweep",
    "angle": 0-180, "step": degrees, "on": true/false, "seconds": sweep time}."""
    cs = camera_servo
    action = str(body.get("action", "")).strip().lower()
    try:
        if action in ("centre", "center"):
            cs.set_follow(False)
            cs.centre()
        elif action in ("left", "right"):
            step = float(body.get("step", 10))
            cs.set_follow(False)
            cs.nudge(step if action == "left" else -step)
        elif action == "angle":
            cs.set_follow(False)
            cs.set_angle(float(body["angle"]))
        elif action == "follow":
            cs.set_follow(bool(body.get("on", True)))
        elif action == "sweep":
            if not cs.start_sweep(float(body.get("seconds", 10))):
                return {"ok": False, "error": "already sweeping", **cs.status()}, 409
        elif action == "stop_sweep":
            cs.stop_sweep()
        else:
            return {"ok": False, "error": f"unknown action {action or '(none)'}"}, 400
    except (KeyError, TypeError, ValueError) as e:
        return {"ok": False, "error": f"bad value: {e}"}, 400
    return {"ok": True, **cs.status()}, 200


if __name__ == "__main__":
    s = CameraServo()
    print(f"Centring the camera servo on GPIO {s.cfg['Pin']} ({s.centre_deg}°)...")
    s.centre()
    time.sleep(1.0)
    s.close()
    print(s.error or "Centred.")
