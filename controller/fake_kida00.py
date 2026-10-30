#!/usr/bin/env python3

"""
fake_kida00.py — a pretend KIDA-00 for the controller's EMULATE (fleet TODO section 13).

Answers her Flask server's routes (scripts/server.py) the way she does, on 127.0.0.1:5003,
with a pretend room for her to drive round, so every key, button and pad input of
controller/main.py can be tried with no robot:

  GET  /status            what ui.py publishes, plus mind_drive.py's fields (?ctl=1 checks in)
  GET  /control/stats/    CPU, temp, RAM, ... (pretend numbers)
  GET  /video_feed        MJPEG: the room from above, her in it, her sonar's ray
  GET  /qr.png            a stand-in for her dashboard's QR code
  POST /command           {"command": ...}: the same strings as ui.py's command processor
  GET  /unlock /mind /look, POST /speak   her MIND mode (mind_drive.py)

Run it alone (python fake_kida00.py) and point the controller at 127.0.0.1, or press
EMULATE in the controller: it starts one of these inside itself.
"""

import io
import math
import os
import random
import sys
import time
from collections import deque

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "scripts"))   # drive_mix, hud_layout

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

import controller_kit as kit
from drive_mix import wheels_label
from hud_layout import SPEED_LEVELS

ROOM_W, ROOM_H = 400.0, 300.0          # cm
BOXES = [(110, 60, 60, 40), (250, 170, 50, 70), (60, 210, 40, 40)]   # x, y, w, h (cm)
TOP_CM_S = 45.0                         # full speed, both wheels forward
TRACK_CM = 40.0                         # her wheels, as a skid-steer turns (slower than their 14 cm say)
REMOTE_HOLD_S = 0.8                     # ui.py: a remote drive not heard of for this long stops
WALL_STOP_CM = 25.0                     # motor_control's wall guard: no forward past this
AUTO_TURN_CM = 35.0                     # her obstacle avoidance turns away below this
MIND_STEP_S, MIND_MAX_STEPS = 0.4, 4    # mind_drive.py
HOST_TTL_S = 5.0
MODES = ["USER", "AUTONOMOUS", "LINE", "FACE", "MIND"]
CAM_W, CAM_H = 320, 240


class FakeKida(kit.FakeRobot):
    NAME = "KIDA00"
    PORTS = (5003,)

    def __init__(self, host="127.0.0.1"):
        self.x, self.y, self.heading = 40.0, 40.0, 0.0     # cm, radians (0 = along +x)
        self.wheels = (0.0, 0.0)
        self.state = {"direction": "STOPPED", "speed": SPEED_LEVELS[0], "speed_idx": 0, "ctrl_scheme": 1,
                      "arc_turn": True, "mode": "USER", "video_rec": False, "music_playing": False,
                      "track": "", "face_scan": True, "faces": [], "deepface_ok": True, "frame": 0,
                      "led": [0, 0, 0], "gamepad": None}
        self.remote = None            # ("dir", "forward") | ("tank", (l, r)) | ("mix", (l, r)) | ("mind", dir)
        self.remote_until = 0.0
        self.host_seen = -1e9
        self.mind = {"steps": 0, "blocked": False, "dir": None, "until": 0.0}
        self.cam_pan = 0.0
        self.started = time.time()
        self.tracks = ["Fake Song.mp3", "Another Fake Song.mp3"]
        self._track = 0
        self.drop = 0                 # session_test.py: lose this many commands, as a busy robot can
        self.heard = deque(maxlen=200)   # the commands she took, in order (session_test.py)
        super().__init__(host)

    # ── her world ──────────────────────────────────────────────────────────
    def distance(self, heading=None):
        """Her front sonar: cm to the nearest wall or box straight ahead (max 400)."""
        h = self.heading if heading is None else heading
        dx, dy = math.cos(h), math.sin(h)
        for d in range(0, 400, 2):
            px, py = self.x + dx * d, self.y + dy * d
            if not (0 < px < ROOM_W and 0 < py < ROOM_H) or any(
                    bx <= px <= bx + bw and by <= py <= by + bh for bx, by, bw, bh in BOXES):
                return float(d)
        return 400.0

    def _wanted_wheels(self, now):
        mode = self.state["mode"]
        if mode == "AUTONOMOUS":
            return (0.6, -0.6) if self.distance() < AUTO_TURN_CM else (1.0, 1.0)
        if mode == "LINE":
            return (0.55, 0.42)              # round and round a pretend line
        if self.remote is None or now > self.remote_until:
            return (0.0, 0.0)
        kind, v = self.remote
        if kind == "mind":
            return {"forward": (1, 1), "backward": (-1, -1), "left": (-1, 1), "right": (1, -1)}.get(v, (0, 0)) \
                if mode == "MIND" else (0.0, 0.0)
        if mode != "USER":
            return (0.0, 0.0)                 # remote drives only count in USER mode (ui.py)
        if kind == "dir":
            return {"forward": (1, 1), "backward": (-1, -1), "left": (-1, 1), "right": (1, -1)}[v]
        return v

    def step(self, dt):
        now = time.monotonic()
        st = self.state
        if st["mode"] == "MIND" and now - self.host_seen > HOST_TTL_S:
            st["mode"] = "USER"
            self.log("MIND host gone quiet: back to USER")
        # MIND steps (mind_drive._drive)
        m = self.mind
        if m["steps"] > 0 and st["mode"] == "MIND":
            if m["dir"] == "forward" and self.distance() < WALL_STOP_CM:
                m.update(steps=0, blocked=True)
            else:
                self.remote, self.remote_until = ("mind", m["dir"]), now + 0.2
                if now >= m["until"]:
                    m["steps"] -= 1
                    m["until"] = now + MIND_STEP_S
        l, r = self._wanted_wheels(now)
        if l > 0 and r > 0 and self.distance() < WALL_STOP_CM:
            l, r = 0.0, 0.0                   # the wall guard
        self.wheels = (l, r)
        speed = st["speed"] * TOP_CM_S
        v = (l + r) / 2 * speed
        self.heading -= (l - r) * speed / TRACK_CM * dt   # left wheel faster: she turns right (clockwise)
        nx = self.x + math.cos(self.heading) * v * dt
        ny = self.y + math.sin(self.heading) * v * dt
        if 8 < nx < ROOM_W - 8 and 8 < ny < ROOM_H - 8 and not any(
                bx - 8 <= nx <= bx + bw + 8 and by - 8 <= ny <= by + bh + 8 for bx, by, bw, bh in BOXES):
            self.x, self.y = nx, ny
        st["direction"] = "THINKING" if st["mode"] == "MIND" and not (l or r) else wheels_label(l, r)
        st["frame"] += 1
        face = st["mode"] == "FACE" or st["face_scan"]
        st["faces"] = [{"region": {"x": 120, "y": 70, "w": 70, "h": 80}, "gender": "Woman", "age": 27, "conf": 0.91}] \
            if face and int(time.time() / 4) % 2 else []
        st["face_count"] = len(st["faces"])
        st["led"] = {"USER": [200, 74, 137], "AUTONOMOUS": [20, 200, 170], "LINE": [55, 138, 221],
                     "FACE": [160, 80, 240], "MIND": [255, 160, 40]}[st["mode"]]

    # ── her command processor (ui.py's process()) ───────────────────────────
    def command(self, cmd):
        cmd = str(cmd).strip().lower()
        st, now = self.state, time.monotonic()
        if self.drop > 0 and not cmd.startswith(("tank:", "drive:", "forward", "backward", "left", "right", "stop")):
            self.drop -= 1
            self.log(f"(lost {cmd}, on purpose)")
            return
        self.heard.append(cmd)

        def drive(kind, v):
            self.remote, self.remote_until = (kind, v), now + REMOTE_HOLD_S

        if cmd in ("up", "forward"):          drive("dir", "forward")
        elif cmd in ("down", "backward"):     drive("dir", "backward")
        elif cmd in ("left", "right"):        drive("dir", cmd)
        elif cmd.startswith(("tank:", "drive:")):
            try:
                vals = [float(v) for v in cmd.split(":", 1)[1].split(":")]
                drive("mix", tuple(max(-1.0, min(1.0, v)) for v in vals[:2]))
            except ValueError:
                pass
        elif cmd == "stop":                   self.remote_until = 0.0
        elif cmd == "arc_toggle":             st["arc_turn"] = not st["arc_turn"]
        elif cmd in ("arc_on", "arc_off"):    st["arc_turn"] = cmd == "arc_on"
        elif cmd == "photo":                  self.log("photo taken")
        elif cmd in ("video", "video_start"): st["video_rec"] = True
        elif cmd == "video_stop":             st["video_rec"] = False
        elif cmd == "video_toggle":           st["video_rec"] = not st["video_rec"]
        elif cmd in ("music", "play_music", "start_music"):
            if not st["music_playing"]:
                self._play()
        elif cmd in ("stop_music", "pause_music"):
            st["music_playing"] = False
        elif cmd == "music_toggle":
            if st["music_playing"]:
                st["music_playing"] = False
            else:
                self._play()
        elif cmd in ("skip", "next_music", "skip_music"):
            if st["music_playing"]:
                self._play()
        elif cmd == "speed":
            self._speed((st["speed_idx"] + 1) % len(SPEED_LEVELS))
        elif cmd.startswith("speed_"):
            try:
                i = int(cmd[6:]) - 1
                if 0 <= i < len(SPEED_LEVELS):
                    self._speed(i)
            except ValueError:
                pass
        elif cmd in ("scheme_1", "scheme_wasd"): st["ctrl_scheme"] = 1
        elif cmd in ("scheme_2", "scheme_tank"): st["ctrl_scheme"] = 2
        elif cmd in ("face_save", "face_snapshot"): self.log("faces saved")
        elif cmd == "face_scan_toggle":       st["face_scan"] = not st["face_scan"]
        elif cmd.startswith("_mode_"):
            want = cmd[6:].upper()
            if want == "MIND" and time.monotonic() - self.host_seen > HOST_TTL_S:
                self.log("MIND needs a PC controller that can think, checking in")
            elif want in MODES:
                st["mode"] = want
                self.remote_until = 0.0
                self.mind["steps"] = 0
        elif cmd.startswith("cam_"):
            if cmd == "cam_left":     self.cam_pan = min(60.0, self.cam_pan + 15)
            elif cmd == "cam_right":  self.cam_pan = max(-60.0, self.cam_pan - 15)
            elif cmd == "cam_centre": self.cam_pan = 0.0
            elif cmd.startswith("cam_pan:"):
                try:
                    self.cam_pan = max(-60.0, min(60.0, self.cam_pan + float(cmd[8:])))
                except ValueError:
                    pass
        else:
            return
        if not cmd.startswith(("tank:", "drive:", "forward", "backward", "left", "right", "stop", "cam_pan")):
            self.log(f"{cmd}  ->  mode {st['mode']}, speed {st['speed_idx'] + 1}, scheme {st['ctrl_scheme']}")

    def _speed(self, i):
        self.state["speed_idx"], self.state["speed"] = i, SPEED_LEVELS[i]

    def _play(self):
        self._track = (self._track + 1) % len(self.tracks)
        self.state.update(music_playing=True, track=self.tracks[self._track])

    # ── routes ─────────────────────────────────────────────────────────────
    def status(self):
        st = dict(self.state)
        d = self.distance()
        st.update(motor_lock=False, moving=st["direction"] not in ("STOPPED", "THINKING"),
                  music="playing" if st["music_playing"] else "stopped",
                  uptime_s=int(time.time() - self.started), ladder=None,
                  camera_servo={"angle": 90 + self.cam_pan, "mode": "manual"},
                  mindHost=int(time.monotonic() - self.host_seen < HOST_TTL_S),
                  mindSteps=self.mind["steps"], blocked=self.mind["blocked"], distance_cm=round(d, 1),
                  distances_cm={"front": round(d, 1)}, emulated=True)
        return st

    def route(self, port, path, q):
        if path == "/status":
            if q.get("ctl") == "1":
                self.host_seen = time.monotonic()
            return 200, self.status()
        if path in ("/control/stats/", "/control/stats"):
            up = int(time.time() - self.started)
            return 200, {"stats": {"cpu": round(18 + 10 * random.random(), 1), "temp": round(48 + 3 * random.random(), 1),
                                   "ram_used": 1210, "ram_total": 3796, "ip": "127.0.0.1", "latency": "1 ms",
                                   "threads": 14, "disk_read": 0.2, "disk_write": 0.1,
                                   "boot_time": time.strftime("%H:%M", time.localtime(self.started)),
                                   "uptime": f"{up // 60}m"}}
        if path == "/command" and "_body" in q:
            self.command(q.get("_json", {}).get("command", ""))
            return 200, {"received": q.get("_json", {}).get("command", ""), "status": "queued"}
        if path == "/video_feed":
            return 200, self._mjpeg(), "multipart/x-mixed-replace; boundary=frame"
        if path == "/qr.png":
            return 200, self._qr(), "image/png"
        if path == "/ping":
            return 200, {"ok": True, "name": self.NAME}
        if path == "/unlock":
            if q.get("ctl") == "1":
                self.host_seen = time.monotonic()
                self.log("a mind host signed in")
                return 200, {"ok": True, "mindHost": 1, "motor_lock": False}
            return 200, {"ok": True, "motor_lock": False}
        if path == "/mind":
            return self._mind_act(q.get("act", ""), q.get("steps", 1))
        if path == "/look":
            if self.state["mode"] != "MIND":
                return 409, {"ok": False, "error": "she's not in MIND mode"}
            self.cam_pan = {"left": 45.0, "right": -45.0}.get(q.get("at", "centre"), 0.0)
            return 200, self._frame_jpeg(), "image/jpeg"
        if path == "/chirp":
            self.log(f"chirps line {q.get('u')}")
            return 200, {"ok": True}
        if path == "/speak":
            self.log(f"speaks a WAV of {len(q.get('_body', b''))} bytes")
            return 200, {"ok": True}
        return 404, {"error": f"KIDA00 (pretend) has no {path}"}

    def _mind_act(self, move, steps):
        move = str(move).strip().lower()
        moves = {"fwd": "forward", "bwd": "backward", "left": "left", "right": "right"}
        if move == "stop":
            self.mind["steps"] = 0
            return 200, {"ok": True, "move": "stop"}
        if move not in moves:
            return 400, {"ok": False, "error": f"unknown move {move or '(none)'}", "moves": [*moves, "stop"]}
        if self.state["mode"] != "MIND":
            return 409, {"ok": False, "error": "she's not in MIND mode"}
        if self.mind["steps"] > 0:
            return 409, {"ok": False, "error": "busy: still on the last move"}
        if move == "fwd" and self.distance() < WALL_STOP_CM:
            self.mind["blocked"] = True
            return 409, {"ok": False, "blocked": True, "distance_cm": round(self.distance(), 1)}
        try:
            steps = max(1, min(MIND_MAX_STEPS, int(steps)))
        except (TypeError, ValueError):
            steps = 1
        self.mind.update(steps=steps, blocked=False, dir=moves[move], until=time.monotonic() + MIND_STEP_S)
        self.log(f"MIND: {move} x{steps}")
        return 200, {"ok": True, "move": move, "steps": steps}

    # ── pictures ───────────────────────────────────────────────────────────
    def _frame_jpeg(self):
        """The room from above as her 'camera': boxes, her, her sonar's ray, which way the camera looks."""
        s = pygame.Surface((CAM_W, CAM_H))
        s.fill((24, 20, 30))
        k = min(CAM_W / ROOM_W, CAM_H / ROOM_H)
        ox, oy = (CAM_W - ROOM_W * k) / 2, (CAM_H - ROOM_H * k) / 2

        def p(x, y):
            return int(ox + x * k), int(oy + (ROOM_H - y) * k)   # y up in the room, down on screen

        pygame.draw.rect(s, (60, 48, 72), (*p(0, ROOM_H), int(ROOM_W * k), int(ROOM_H * k)), 2)
        for bx, by, bw, bh in BOXES:
            pygame.draw.rect(s, (120, 90, 70), (*p(bx, by + bh), int(bw * k), int(bh * k)))
        if self.state["mode"] == "LINE":
            pygame.draw.circle(s, (230, 230, 230), p(ROOM_W / 2, ROOM_H / 2), int(90 * k), 2)
        d = self.distance()
        hx, hy = math.cos(self.heading), math.sin(self.heading)
        pygame.draw.line(s, (255, 160, 40), p(self.x, self.y), p(self.x + hx * d, self.y + hy * d), 1)
        cam = self.heading + math.radians(self.cam_pan)
        pygame.draw.line(s, (55, 138, 221), p(self.x, self.y),
                         p(self.x + math.cos(cam) * 40, self.y + math.sin(cam) * 40), 2)
        pts = [(self.x + hx * 12, self.y + hy * 12),
               (self.x - hx * 8 - hy * 8, self.y - hy * 8 + hx * 8),
               (self.x - hx * 8 + hy * 8, self.y - hy * 8 - hx * 8)]
        pygame.draw.polygon(s, (200, 74, 137), [p(*q) for q in pts])
        buf = io.BytesIO()
        pygame.image.save(s, buf, "frame.jpg")
        return buf.getvalue()

    def _mjpeg(self):
        while not self._stop.is_set():
            jpg = self._frame_jpeg()
            yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"
            time.sleep(0.1)

    def _qr(self):
        s = pygame.Surface((130, 130))
        s.fill((255, 255, 255))
        rnd = random.Random(5003)
        for i in range(13):
            for j in range(13):
                if rnd.random() < 0.45 or (i < 3 and j < 3) or (i > 9 and j < 3) or (i < 3 and j > 9):
                    pygame.draw.rect(s, (0, 0, 0), (i * 10, j * 10, 10, 10))
        buf = io.BytesIO()
        pygame.image.save(s, buf, "qr.png")
        return buf.getvalue()


if __name__ == "__main__":
    robot = FakeKida()
    print("Pretend KIDA-00 on http://127.0.0.1:5003  (Ctrl+C stops it)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        robot.stop()
