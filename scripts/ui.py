"""
KIDA — main UI  v2.4
Refactored: render helpers extracted, duplicate info-strip removed,
music-playing bug fixed, shutdown hook fires correctly.
"""

import os
import time
import math
import queue
import socket
import logging
import threading
import subprocess
import datetime
import warnings

warnings.filterwarnings("ignore", category=UserWarning)

import pygame
import psutil
import qrcode
from PIL import Image
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput
from flask import Flask, jsonify, request

from mode_control       import Mode, ModeContext, switch_mode, face_pulse_color
from music_player       import MusicPlayer
from motor_control      import MotorController
from obstacle_avoidance import ObstacleAvoidance
from line_follower      import LineFollower
from led_control        import SPI_WS2812_LEDStrip
from audio_analysis     import AudioAnalyzer
#from server import 

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("kida.ui")

# ── Palette ───────────────────────────────────────────────────────────────────
BG     = (8,   9,  13)
PANEL  = (14,  15,  22)
BORDER = (32,  35,  52)
ACCENT = (255,  30, 100)
GREEN  = (29,  200, 120)
BLUE   = (55,  138, 221)
AMBER  = (255, 160,  40)
RED    = (226,  75,  74)
TEAL   = (20,  200, 170)
PURPLE = (160,  80, 240)
PRI    = (230, 230, 225)
SEC    = (130, 132, 125)
DIM    = (60,   62,  75)

# ── Flask ─────────────────────────────────────────────────────────────────────
app           = Flask(__name__, static_folder="static", template_folder="templates")
command_queue: queue.Queue = queue.Queue()

_robot_state: dict = {
    "direction": "STOPPED", "speed": 0.6, "mode": "USER",
    "video_rec": False, "music_playing": False,
    "led": [0, 0, 0], "face_count": 0,
}
_robot_state_lock = threading.Lock()


@app.route("/")
def home():
    from flask import render_template
    return render_template("index.html")

@app.route("/status")
def status():
    with _robot_state_lock:
        return jsonify(_robot_state.copy())

@app.route("/command", methods=["POST"])
def receive_command():
    try:
        cmd = request.get_json(force=True).get("command", "")
        command_queue.put(cmd)
        return jsonify({"received": cmd, "status": "queued"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/control/send/", methods=["POST"])
def control_send():
    try:
        cmd = request.get_json(force=True).get("command", "")
        command_queue.put(cmd)
        return jsonify({"received": cmd, "status": "queued"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/control/stats/", methods=["GET"])
def control_stats():
    with _stats_lock:
        return jsonify({"stats": _system_stats.copy()})

@app.route("/speed", methods=["POST"])
def set_speed_route():
    try:
        spd = float(request.get_json(force=True).get("speed", 0.6))
        command_queue.put(f"_speed_{spd:.2f}")
        return jsonify({"speed": spd})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/mode", methods=["POST"])
def set_mode_route():
    mode_str = request.get_json(force=True).get("mode", "").upper()
    if mode_str in ("USER", "AUTONOMOUS", "LINE", "FACE"):
        command_queue.put(f"_mode_{mode_str}")
        return jsonify({"mode": mode_str})
    return jsonify({"error": "invalid mode"}), 400

@app.route("/face/results")
def face_results():
    with _face_lock:
        return jsonify({"results": _face_results.copy()})

def _run_flask() -> None:
    import logging as _log
    _log.getLogger("werkzeug").setLevel(_log.ERROR)
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


# ── System stats thread ───────────────────────────────────────────────────────
_system_stats: dict = {}
_stats_lock          = threading.Lock()


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "N/A"


def _stats_worker() -> None:
    while True:
        try:
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory()
            dio = psutil.disk_io_counters()
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                temp = int(f.read()) / 1000.0
            try:
                out  = subprocess.check_output(
                    ["ping", "-c", "1", "-W", "1", "8.8.8.8"], timeout=1.5
                ).decode()
                line = next((l for l in out.splitlines() if "time=" in l), "")
                lat  = line.split("time=")[1].split()[0] + " ms" if line else "N/A"
            except Exception:
                lat = "N/A"
            with _stats_lock:
                _system_stats.update({
                    "cpu":        cpu,
                    "temp":       temp,
                    "ram_used":   mem.used  // (1024 * 1024),
                    "ram_total":  mem.total // (1024 * 1024),
                    "ip":         _get_local_ip(),
                    "disk_read":  round(dio.read_bytes  / 1024 / 1024, 1),
                    "disk_write": round(dio.write_bytes / 1024 / 1024, 1),
                    "boot_time":  datetime.datetime.fromtimestamp(
                                      psutil.boot_time()).strftime("%H:%M %d/%m"),
                    "latency":    lat,
                    "threads":    threading.active_count(),
                })
        except Exception as e:
            logger.warning("Stats error: %s", e)
        time.sleep(2)


# ── Face detection thread ─────────────────────────────────────────────────────
_face_results: list = []
_face_lock           = threading.Lock()
_face_frame_q: queue.Queue = queue.Queue(maxsize=1)
_face_enabled        = threading.Event()
_deepface_ok         = threading.Event()


def _face_worker() -> None:
    try:
        from deepface import DeepFace
        import numpy as np
        _deepface_ok.set()
        logger.info("DeepFace loaded — face mode ready")
    except ImportError:
        logger.warning("DeepFace not installed — face mode unavailable")
        return

    while True:
        _face_enabled.wait()

        try:
            pil_img = _face_frame_q.get(timeout=1.0)
        except queue.Empty:
            continue

        if not _face_enabled.is_set():
            continue

        try:
            arr     = np.array(pil_img)
            results = DeepFace.analyze(arr, actions=["gender", "age"],
                                       enforce_detection=False, silent=True)
            if isinstance(results, dict):
                results = [results]

            parsed = []
            for r in results:
                gs = r.get("gender", {})
                if isinstance(gs, dict) and gs:
                    gender = max(gs, key=gs.get)
                    conf   = round(gs.get(gender, 0), 1)
                elif isinstance(gs, str):
                    gender, conf = gs, 100.0
                else:
                    gender, conf = "?", 0.0
                parsed.append({
                    "gender": gender, "conf": conf,
                    "age":    int(r.get("age", 0)),
                    "region": r.get("region", {}),
                })

            with _face_lock:
                _face_results[:] = parsed
            with _robot_state_lock:
                _robot_state["face_count"] = len(parsed)

        except Exception as e:
            logger.debug("Face analysis error: %s", e)


# ── Draw primitives ───────────────────────────────────────────────────────────
def _hline(surf, y, x0, x1, color=BORDER):
    pygame.draw.line(surf, color, (x0, y), (x1, y))

def _vline(surf, x, y0, y1, color=BORDER):
    pygame.draw.line(surf, color, (x, y0), (x, y1))

def _txt(surf, font, text, pos, color=PRI, anchor="topleft"):
    s = font.render(str(text), True, color)
    r = s.get_rect(**{anchor: pos})
    surf.blit(s, r)
    return r

def _bar(surf, r, pct, color, track=(18, 20, 32)):
    pygame.draw.rect(surf, track, r, border_radius=3)
    fw = max(int(r.width * min(pct, 1.0)), 0)
    if fw:
        pygame.draw.rect(surf, color, pygame.Rect(r.x, r.y, fw, r.height), border_radius=3)

def _led_dot(surf, pos, color, r=6):
    pygame.draw.circle(surf, color, pos, r)

def _btn(surf, font, label, r, mouse, active=False, danger=False, hover_col=ACCENT):
    hov = r.collidepoint(mouse)
    if danger:
        bc, bd, tc = (28, 10, 10), RED, RED
    elif hov or active:
        bc, bd, tc = (22, 10, 18), hover_col, hover_col
    else:
        bc, bd, tc = PANEL, BORDER, SEC
    pygame.draw.rect(surf, bc, r, border_radius=8)
    pygame.draw.rect(surf, bd, r, width=1, border_radius=8)
    if active and not danger:
        pygame.draw.rect(surf, hover_col,
                         pygame.Rect(r.x + 6, r.bottom - 3, r.width - 12, 3),
                         border_radius=2)
    s = font.render(label, True, tc)
    surf.blit(s, (r.x + (r.width - s.get_width()) // 2,
                  r.y + (r.height - s.get_height()) // 2))

def _section_label(surf, font, text, x, y):
    pygame.draw.rect(surf, ACCENT, pygame.Rect(x, y + 2, 3, 12))
    _txt(surf, font, text, (x + 9, y), DIM)

def _waveform(surf, frame: int, r: pygame.Rect, bars: int = 22,
              playing: bool = False, amplitudes: list | None = None):
    bw  = max(r.width // bars, 2)
    for i in range(bars):
        if amplitudes is not None:
            idx = int(i * len(amplitudes) / bars)
            h   = max(int(amplitudes[idx] * r.height * 0.92), 3)
            col = (*ACCENT, 180)
        elif playing:
            h   = int((math.sin(frame * 0.12 + i * 0.3) * 0.5 + 0.5) * r.height * 0.85 + 3)
            col = (*ACCENT, 140)
        else:
            h, col = 3, (*DIM, 80)
        s = pygame.Surface((max(bw - 1, 1), h), pygame.SRCALPHA)
        s.fill(col)
        surf.blit(s, (r.x + i * bw, r.y + r.height - h))


# ── Render sections ───────────────────────────────────────────────────────────
# Each function draws one named region of the UI.  They receive only what
# they need — no access to global mutable state except via explicit args.

def _render_camera(screen, cam_surf, faces, frame, video_rec,
                   mode, CAM_X, CAM_Y, CAM_W, CAM_H,
                   CAM_NATIVE_W, CAM_NATIVE_H,
                   fmono_sm, fmono_xs, deepface_ok):
    screen.blit(cam_surf, (CAM_X, CAM_Y))
    pygame.draw.rect(screen, BORDER,
                     pygame.Rect(CAM_X - 1, CAM_Y - 1, CAM_W + 2, CAM_H + 2), 1)

    if mode == Mode.FACE:
        if faces:
            _render_face_overlays(screen, faces, CAM_X, CAM_Y, CAM_W, CAM_H,
                                  CAM_NATIVE_W, CAM_NATIVE_H, fmono_sm, fmono_xs)
        else:
            scan_y = CAM_Y + int((math.sin(frame * 0.1) * 0.5 + 0.5) * CAM_H)
            sl = pygame.Surface((CAM_W, 2), pygame.SRCALPHA)
            sl.fill((*PURPLE, 90))
            screen.blit(sl, (CAM_X, scan_y))
            txt   = "DEEPFACE NOT INSTALLED" if not deepface_ok else "SCANNING FOR FACES…"
            color = RED if not deepface_ok else PURPLE
            _txt(screen, fmono_sm, txt, (CAM_X + CAM_W // 2, CAM_Y + 10), color, anchor="midtop")
    elif mode == Mode.AUTONOMOUS:
        _render_cam_overlay(screen, "— AUTONOMOUS —", TEAL, CAM_X, CAM_Y, CAM_W, CAM_H, fmono_sm)
    elif mode == Mode.LINE:
        _render_cam_overlay(screen, "— LINE FOLLOW —", BLUE, CAM_X, CAM_Y, CAM_W, CAM_H, fmono_sm)

    # Corner brackets
    blen = 22
    for (cx, cy, sx, sy) in [
        (CAM_X + 5,         CAM_Y + 5,          1,  1),
        (CAM_X + CAM_W - 5, CAM_Y + 5,         -1,  1),
        (CAM_X + 5,         CAM_Y + CAM_H - 5,  1, -1),
        (CAM_X + CAM_W - 5, CAM_Y + CAM_H - 5, -1, -1),
    ]:
        pygame.draw.line(screen, ACCENT, (cx, cy), (cx + sx * blen, cy), 2)
        pygame.draw.line(screen, ACCENT, (cx, cy), (cx, cy + sy * blen), 2)

    # REC blink
    if video_rec and (frame // 12) % 2 == 0:
        pygame.draw.circle(screen, RED, (CAM_X + CAM_W - 18, CAM_Y + 12), 6)
        _txt(screen, fmono_xs, "REC", (CAM_X + CAM_W - 10, CAM_Y + 7), RED)


def _render_cam_overlay(screen, msg, color, CAM_X, CAM_Y, CAM_W, CAM_H, font):
    ms = font.render(msg, True, color)
    mx = CAM_X + (CAM_W - ms.get_width()) // 2
    my = CAM_Y + CAM_H - 28
    ov = pygame.Surface((ms.get_width() + 16, ms.get_height() + 8), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 140))
    screen.blit(ov, (mx - 8, my - 4))
    screen.blit(ms, (mx, my))


def _render_face_overlays(screen, faces, cam_x, cam_y, cam_w, cam_h,
                          native_w, native_h, font_sm, font_xs):
    sx = cam_w / native_w
    sy = cam_h / native_h
    for face in faces:
        reg = face.get("region", {})
        if not reg:
            continue
        x  = int(reg.get("x", 0) * sx) + cam_x
        y  = int(reg.get("y", 0) * sy) + cam_y
        fw = int(reg.get("w", 0) * sx)
        fh = int(reg.get("h", 0) * sy)
        if fw < 4 or fh < 4:
            continue
        gender  = face.get("gender", "?")
        age     = face.get("age", 0)
        conf    = face.get("conf", 0)
        box_col = PURPLE if gender == "Woman" else TEAL
        pygame.draw.rect(screen, box_col, pygame.Rect(x, y, fw, fh), 2, border_radius=4)
        tlen = min(14, fw // 4)
        for (cx, cy, dx, dy) in [
            (x,      y,      1,  1), (x + fw, y,      -1,  1),
            (x,      y + fh, 1, -1), (x + fw, y + fh, -1, -1),
        ]:
            pygame.draw.line(screen, box_col, (cx, cy), (cx + dx * tlen, cy), 2)
            pygame.draw.line(screen, box_col, (cx, cy), (cx, cy + dy * tlen), 2)
        label  = f"{gender[0]}  {age}y  {conf:.0f}%"
        ls     = font_sm.render(label, True, box_col)
        tag_r  = pygame.Rect(x, y - ls.get_height() - 6, ls.get_width() + 10, ls.get_height() + 4)
        tag_r.clamp_ip(screen.get_rect())
        tag_bg = pygame.Surface((tag_r.w, tag_r.h), pygame.SRCALPHA)
        tag_bg.fill((0, 0, 0, 200))
        screen.blit(tag_bg, tag_r)
        screen.blit(ls, (tag_r.x + 5, tag_r.y + 2))


def _render_info_strip(screen, mode, direction, speed, ctrl_scheme,
                       led_color, face_count, CAM_X, CAM_Y, CAM_H,
                       fmono_xs, fmono_sm):
    """Single row of telemetry just below the camera."""
    info_y     = CAM_Y + CAM_H + 10
    face_label = (f"FACES {face_count}" if mode == Mode.FACE
                  else f"R{led_color[0]} G{led_color[1]} B{led_color[2]}")
    items = [
        ("DIR",                                      direction,
         AMBER if direction != "STOPPED" else SEC),
        ("SPEED",                                    f"{speed:.1f}", PRI),
        ("SCHEME",                                   "WASD" if ctrl_scheme == 1 else "QA/WS", PRI),
        ("FACES" if mode == Mode.FACE else "LED",    face_label,
         PURPLE if mode == Mode.FACE else SEC),
    ]
    ix = CAM_X
    for lbl, val, vc in items:
        ls = fmono_xs.render(lbl, True, DIM)
        vs = fmono_sm.render(val, True, vc)
        screen.blit(ls, (ix, info_y))
        screen.blit(vs, (ix, info_y + 16))
        ix += max(ls.get_width(), vs.get_width()) + 22


def _render_top_bar(screen, mode, n_thr, temp_c, st, led_color, tabs, TAB_LABELS,
                    W, TOP_H, fmono_xl, fmono_md, fmono_xs, fbody, mouse):
    logo = fmono_xl.render("KIDA", True, ACCENT)
    screen.blit(logo, (14, (TOP_H - logo.get_height()) // 2))

    for i, (tr, tl) in enumerate(zip(tabs, TAB_LABELS)):
        _btn(screen, fbody, tl, tr, mouse,
             active=(int(mode) == i),
             hover_col=PURPLE if i == 3 else ACCENT)

    chip_x = W - 14
    for lbl, val, warn in [
        ("THR",  str(n_thr),                  False),
        ("TEMP", f"{temp_c:.0f}C",            temp_c > 65),
        ("CPU",  f"{st.get('cpu', 0):.0f}%", False),
    ]:
        col = AMBER if warn else PRI
        vs  = fmono_md.render(val, True, col)
        ls  = fmono_xs.render(lbl, True, DIM)
        chip_x -= vs.get_width() + 4
        screen.blit(vs, (chip_x, (TOP_H - vs.get_height()) // 2))
        chip_x -= ls.get_width() + 8
        screen.blit(ls, (chip_x, (TOP_H - ls.get_height()) // 2))
        chip_x -= 18

    for i in range(8):
        dc = tuple(led_color) if any(c > 10 for c in led_color) else (28, 30, 44)
        _led_dot(screen, (chip_x - 12 - i * 14, TOP_H // 2), dc, r=5)


def _render_left_panel(screen, qr_surf, local_ip, st, cpu_pct, temp_c,
                       temp_pct, ram_u, ram_t, ram_pct, latency, n_thr,
                       disk_r, disk_w, boot_t, music, music_playing,
                       frame, amplitudes, btn_play, btn_skip, mouse,
                       lp_x, lp_w, TOP_H, PAD,
                       fmono_md, fmono_sm, fmono_xs, fbody, flabel, flabel_s):
    lp_y = TOP_H + PAD

    # QR panel
    qr_w = qr_surf.get_width()
    qr_x = lp_x + (lp_w - qr_w) // 2
    pygame.draw.rect(screen, (255, 255, 255),
                     pygame.Rect(qr_x - 4, lp_y - 4, qr_w + 8, qr_w + 8),
                     border_radius=4)
    screen.blit(qr_surf, (qr_x, lp_y))
    url_y = lp_y + qr_w + 10
    _txt(screen, fmono_md, str(local_ip),
         (lp_x + lp_w // 2, url_y), AMBER, anchor="midtop")
    _txt(screen, fmono_sm, "port  5000",
         (lp_x + lp_w // 2, url_y + fmono_md.get_height() + 2), SEC, anchor="midtop")
    lp_y = url_y + fmono_md.get_height() + fmono_sm.get_height() + 14
    _txt(screen, fmono_xs, "SCAN TO OPEN DASHBOARD",
         (lp_x + lp_w // 2, lp_y), DIM, anchor="midtop")
    lp_y += fmono_xs.get_height() + 10

    # System
    _section_label(screen, fmono_xs, "SYSTEM", lp_x, lp_y);  lp_y += 20
    for label, val, pct, bc in [
        ("CPU",  f"{st.get('cpu', 0):.0f}%", cpu_pct,  ACCENT),
        ("TEMP", f"{temp_c:.0f}°C",           temp_pct, AMBER),
        ("RAM",  f"{ram_u}/{ram_t}M",          ram_pct,  BLUE),
    ]:
        _txt(screen, flabel_s, label, (lp_x, lp_y), DIM)
        _txt(screen, fmono_sm, val,   (lp_x + lp_w, lp_y), SEC, anchor="topright")
        _bar(screen, pygame.Rect(lp_x, lp_y + 18, lp_w, 6), pct, bc)
        lp_y += 32

    # Network
    lp_y += 6
    _section_label(screen, fmono_xs, "NETWORK", lp_x, lp_y);  lp_y += 20
    for label, val in [
        ("LATENCY", latency), ("THREADS", str(n_thr)),
        ("DISK R",  f"{disk_r} MB"), ("DISK W", f"{disk_w} MB"),
        ("BOOT",    boot_t),
    ]:
        _txt(screen, flabel_s, label,    (lp_x, lp_y), DIM)
        _txt(screen, fmono_sm, str(val), (lp_x + lp_w, lp_y), SEC, anchor="topright")
        pygame.draw.line(screen, (22, 24, 36),
                         (lp_x, lp_y + 20), (lp_x + lp_w, lp_y + 20))
        lp_y += 24

    # Music
    lp_y += 8
    _section_label(screen, fmono_xs, "MUSIC", lp_x, lp_y);  lp_y += 20
    track = music.current_track or "No track"
    screen.blit(
        flabel.render(str(track)[:22], True, PRI if music_playing else SEC),
        (lp_x, lp_y),
    )
    lp_y += 22
    _waveform(screen, frame, pygame.Rect(lp_x, lp_y, lp_w, 30),
              playing=music_playing, amplitudes=amplitudes)
    lp_y += 38
    _btn(screen, fbody, "PAUSE" if music_playing else "PLAY",
         btn_play, mouse, active=music_playing)
    _btn(screen, fbody, "SKIP ▶", btn_skip, mouse)


def _render_right_panel(screen, mode, direction, speed_idx, ctrl_scheme,
                        video_rec, dpad, DPAD_GLYPHS, spd_dots,
                        sch_btns, btn_photo, btn_video, btn_face_snap,
                        rp_x, spd_y, sch_y, cap_y, TOP_H, PAD, mouse,
                        fmono_md, fmono_xs, fbody, fdpad):
    _section_label(screen, fmono_xs, "DIRECTIONAL CONTROL", rp_x, TOP_H + PAD)
    for cmd, r in dpad.items():
        is_stop = cmd == "stop"
        _btn(screen, fmono_md if is_stop else fdpad,
             DPAD_GLYPHS[cmd], r, mouse, danger=is_stop, hover_col=ACCENT)
        if cmd != "stop" and direction.lower() == cmd:
            pygame.draw.rect(screen, ACCENT, r, width=2, border_radius=8)

    _section_label(screen, fmono_xs, "SPEED", rp_x, spd_y - 20)
    for i, r in enumerate(spd_dots):
        _btn(screen, fmono_md, str(i + 1), r, mouse, active=(speed_idx == i))

    _section_label(screen, fmono_xs, "CONTROL SCHEME", rp_x, sch_y - 20)
    for i, (r, lbl) in enumerate(zip(sch_btns, ["WASD", "QA/WS"])):
        _btn(screen, fbody, lbl, r, mouse, active=(ctrl_scheme == i + 1))

    _section_label(screen, fmono_xs, "CAPTURE", rp_x, cap_y - 20)
    _btn(screen, fbody, "PHOTO", btn_photo, mouse, hover_col=BLUE)
    _btn(screen, fbody, "STOP REC" if video_rec else "REC",
         btn_video, mouse, active=video_rec, hover_col=RED, danger=video_rec)
    _btn(screen, fbody, "SAVE FACES", btn_face_snap, mouse,
         hover_col=PURPLE, active=(mode == Mode.FACE))


def _render_bottom_bar(screen, mode, ctrl_scheme, speed, face_count, frame,
                       W, H, BOT_H, fmono_xs):
    sb_y = H - BOT_H
    _hline(screen, sb_y, 0, W)
    pygame.draw.circle(screen, GREEN, (14, sb_y + BOT_H // 2), 5)
    sx = 28
    for lbl, val in [
        ("FLASK",  ":5000"),
        ("MODE",   mode.name),
        ("SCHEME", "WASD" if ctrl_scheme == 1 else "QA/WS"),
        ("SPEED",  f"{speed:.1f}"),
        ("CAM",    "LIVE"),
        ("FACES",  str(face_count)),
        ("FRM",    str(frame)),
    ]:
        ls = fmono_xs.render(lbl, True, DIM)
        vs = fmono_xs.render(val, True,
                             PURPLE if lbl == "FACES" and face_count > 0 else SEC)
        screen.blit(ls, (sx, sb_y + (BOT_H - ls.get_height()) // 2));  sx += ls.get_width() + 5
        screen.blit(vs, (sx, sb_y + (BOT_H - vs.get_height()) // 2));  sx += vs.get_width() + 14
        pygame.draw.line(screen, BORDER, (sx - 6, sb_y + 6), (sx - 6, sb_y + BOT_H - 6))
    vers = fmono_xs.render("KIDA v2.4 · RASPBERRY PI", True, DIM)
    screen.blit(vers, (W - vers.get_width() - 12,
                       sb_y + (BOT_H - vers.get_height()) // 2))


# ── Camera helper ─────────────────────────────────────────────────────────────
def _cam_to_surface(cam: Picamera2, w: int, h: int) -> tuple:
    try:
        raw = cam.capture_array()
        if raw.ndim == 3 and raw.shape[2] == 4:
            raw = raw[:, :, :3]
        pil = Image.fromarray(raw, "RGB").rotate(180).resize((w, h), Image.NEAREST)
        return pygame.image.fromstring(pil.tobytes(), pil.size, "RGB"), pil
    except Exception:
        s = pygame.Surface((w, h));  s.fill((8, 10, 16))
        return s, None


def _make_qr(url: str, size: int = 130) -> pygame.Surface:
    qr = qrcode.QRCode(version=1,
                       error_correction=qrcode.constants.ERROR_CORRECT_L,
                       box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img = img.resize((size, size), Image.LANCZOS)
    return pygame.image.fromstring(img.tobytes(), img.size, "RGB")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    pygame.init()
    info   = pygame.display.Info()
    W, H   = info.current_w, info.current_h
    screen = pygame.display.set_mode(
        (W, H), pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF)
    pygame.display.set_caption("KIDA")
    clock = pygame.time.Clock()

    TOP_H = 58;  BOT_H = 42;  PAD = 10
    L_W   = 290; R_W   = 300; TAB_H = 50

    CAM_AVAIL_W = W - L_W - R_W
    CAM_AVAIL_H = H - TOP_H - BOT_H
    CAM_W = int(CAM_AVAIL_W * 0.82);  CAM_H = int(CAM_AVAIL_H * 0.60)
    CAM_X = L_W + (CAM_AVAIL_W - CAM_W) // 2
    CAM_Y = TOP_H + TAB_H + PAD
    CAM_NATIVE_W, CAM_NATIVE_H = 320, 240

    # Fonts
    fmono_xl = pygame.font.SysFont("Courier New", 34, bold=True)
    fmono_md = pygame.font.SysFont("Courier New", 20, bold=True)
    fmono_sm = pygame.font.SysFont("Courier New", 17, bold=True)
    fmono_xs = pygame.font.SysFont("Courier New", 14)
    fbody    = pygame.font.SysFont("Arial", 18, bold=True)
    flabel   = pygame.font.SysFont("Arial", 17)
    flabel_s = pygame.font.SysFont("Arial", 15)
    fdpad    = pygame.font.SysFont("Arial", 32, bold=True)

    # Background threads
    threading.Thread(target=_run_flask,    daemon=True).start()
    threading.Thread(target=_stats_worker, daemon=True).start()
    threading.Thread(target=_face_worker,  daemon=True).start()

    # Hardware
    music  = MusicPlayer("/home/nova/Desktop/kida/audio/music/")
    motors = MotorController()

    try:    avoider = ObstacleAvoidance(motors=motors)
    except Exception as e:
        logger.warning("ObstacleAvoidance init failed: %s", e);  avoider = None

    try:    liner = LineFollower(motors=motors)
    except Exception as e:
        logger.warning("LineFollower init failed: %s", e);  liner = None

    led = SPI_WS2812_LEDStrip(8, 128)

    cam = Picamera2()
    cam.configure(cam.create_preview_configuration(
        main={"size": (CAM_NATIVE_W, CAM_NATIVE_H)},
        transform=__import__("libcamera").Transform(hflip=1, vflip=1),
    ))
    cam.start()
    _encoder = H264Encoder(bitrate=4000000)

    if not led.ready:
        logger.error("SPI LED strip not ready — exiting.")
        pygame.quit();  return

    local_ip   = _get_local_ip()
    qr_surf    = _make_qr(f"http://{local_ip}:5000", size=130)
    photos_dir = "/home/nova/Desktop/kida/photos"
    videos_dir = "/home/nova/Desktop/kida/videos"
    face_dir   = "/home/nova/Desktop/kida/faces"
    for d in (photos_dir, videos_dir, face_dir):
        os.makedirs(d, exist_ok=True)

    # LED colour — use nonlocal in closures instead of a mutable list
    led_r = led_g = led_b = 0

    def set_led(color: tuple) -> None:
        nonlocal led_r, led_g, led_b
        led_r, led_g, led_b = color
        led.set_all_led_color(*color)
        with _robot_state_lock:
            _robot_state["led"] = list(color)

    def led_color():
        """Returns current LED colour as a tuple for rendering."""
        return (led_r, led_g, led_b)

    # ModeContext
    ctx = ModeContext(
        motors            = motors,
        led               = led,
        set_led_fn        = set_led,
        face_enabled_event= _face_enabled,
        face_results      = _face_results,
        face_lock         = _face_lock,
        robot_state       = _robot_state,
        robot_state_lock  = _robot_state_lock,
    )

    # State
    mode          = Mode.USER
    speed_levels  = [0.4, 0.6, 0.8, 1.0]
    speed_idx     = 0
    speed         = speed_levels[speed_idx]
    ctrl_scheme   = 1
    music_playing = False
    video_rec     = False
    frame         = 0
    direction     = "STOPPED"
    cam_surf      = pygame.Surface((CAM_W, CAM_H));  cam_surf.fill((8, 10, 14))
    cam_tick      = 0;  face_tick = 0;  cam_pil = None
    analyzer: AudioAnalyzer | None = None

    TAB_LABELS = ["USER CTRL", "AUTONOMOUS", "LINE FOLLOW", "FACE SCAN"]

    tab_w     = min(130, (CAM_AVAIL_W - PAD * 5) // 4)
    tab_x0    = L_W + (CAM_AVAIL_W - (tab_w * 4 + PAD * 3)) // 2
    tabs      = [pygame.Rect(tab_x0 + i * (tab_w + PAD), TOP_H + 6, tab_w, TAB_H - 12)
                 for i in range(4)]

    DP_S = 76;  DP_G = 10
    DP_CX = W - R_W + (R_W - DP_S) // 2
    DP_Y  = TOP_H + TAB_H + PAD + 10
    dpad = {
        "forward":  pygame.Rect(DP_CX,               DP_Y,                     DP_S, DP_S),
        "left":     pygame.Rect(DP_CX - DP_S - DP_G, DP_Y + DP_S + DP_G,      DP_S, DP_S),
        "stop":     pygame.Rect(DP_CX,               DP_Y + DP_S + DP_G,       DP_S, DP_S),
        "right":    pygame.Rect(DP_CX + DP_S + DP_G, DP_Y + DP_S + DP_G,      DP_S, DP_S),
        "backward": pygame.Rect(DP_CX,               DP_Y + (DP_S + DP_G) * 2, DP_S, DP_S),
    }
    DPAD_GLYPHS = {"forward": "▲", "left": "◀", "stop": "■", "right": "▶", "backward": "▼"}

    rp_x = W - R_W + PAD;  rp_w = R_W - PAD * 2
    spd_y = DP_Y + (DP_S + DP_G) * 3 + 22
    spd_w = (rp_w - DP_G * 3) // 4;  spd_h = 44
    spd_dots = [pygame.Rect(rp_x + i * (spd_w + DP_G), spd_y, spd_w, spd_h) for i in range(4)]

    sch_y = spd_y + spd_h + 26;  sch_w = (rp_w - DP_G) // 2;  sch_h = 44
    sch_btns = [
        pygame.Rect(rp_x,                sch_y, sch_w, sch_h),
        pygame.Rect(rp_x + sch_w + DP_G, sch_y, sch_w, sch_h),
    ]

    cap_y = sch_y + sch_h + 26;  cap_w = (rp_w - DP_G) // 2;  cap_h = 48
    btn_photo     = pygame.Rect(rp_x,                cap_y, cap_w, cap_h)
    btn_video     = pygame.Rect(rp_x + cap_w + DP_G, cap_y, cap_w, cap_h)
    btn_face_snap = pygame.Rect(rp_x, cap_y + cap_h + 18, rp_w, 44)

    lp_x = PAD;  lp_w = L_W - PAD * 2
    mus_btn_y = H - BOT_H - 76;  mus_btn_h = 48;  mus_btn_w = (lp_w - DP_G) // 2
    btn_play  = pygame.Rect(lp_x,                    mus_btn_y, mus_btn_w, mus_btn_h)
    btn_skip  = pygame.Rect(lp_x + mus_btn_w + DP_G, mus_btn_y, mus_btn_w, mus_btn_h)

    # Pre-bake static background
    bg_surf = pygame.Surface((W, H));  bg_surf.fill(BG)
    for gx in range(0, W + 1, 44):
        pygame.draw.line(bg_surf, (14, 8, 12), (gx, 0), (gx, H))
    for gy in range(0, H + 1, 44):
        pygame.draw.line(bg_surf, (14, 8, 12), (0, gy), (W, gy))
    pygame.draw.rect(bg_surf, PANEL, pygame.Rect(0,     TOP_H, L_W,   H - TOP_H - BOT_H))
    pygame.draw.rect(bg_surf, PANEL, pygame.Rect(W-R_W, TOP_H, R_W,   H - TOP_H - BOT_H))
    pygame.draw.rect(bg_surf, (10, 11, 16), pygame.Rect(0, H - BOT_H, W, BOT_H))

    # ── Action closures ────────────────────────────────────────────────────────
    def take_photo() -> None:
        fname = os.path.join(photos_dir, f"photo_{int(time.time())}.jpg")
        try:    cam.capture_file(fname);  logger.info("Photo: %s", fname)
        except Exception as e: logger.error("Photo failed: %s", e)

    def toggle_video() -> None:
        nonlocal video_rec
        if not video_rec:
            fname = os.path.join(videos_dir, f"video_{int(time.time())}.mp4")
            try:
                cam.start_encoder(_encoder, FfmpegOutput(fname))
                video_rec = True;  logger.info("Recording: %s", fname)
            except Exception as e: logger.error("Video start failed: %s", e)
        else:
            try:    cam.stop_encoder()
            except Exception as e: logger.error("Video stop failed: %s", e)
            video_rec = False

    def save_face_snapshot() -> None:
        if cam_pil is None:
            return
        try:
            from PIL import ImageDraw
            pil_base = cam_pil.copy()
            draw = ImageDraw.Draw(pil_base)
            with _face_lock:
                faces = _face_results.copy()
            for face in faces:
                reg = face.get("region", {})
                x, y_ = reg.get("x", 0), reg.get("y", 0)
                w_, h_ = reg.get("w", 0), reg.get("h", 0)
                gender = face.get("gender", "?");  age = face.get("age", 0)
                col = (160, 80, 240) if gender == "Woman" else (20, 200, 170)
                draw.rectangle([x, y_, x + w_, y_ + h_], outline=col, width=2)
                draw.text((x + 2, y_ - 14), f"{gender[0]} {age}y", fill=col)
            fname = os.path.join(face_dir, f"face_{int(time.time())}.jpg")
            pil_base.save(fname, "JPEG");  logger.info("Face snapshot: %s", fname)
        except Exception as e: logger.error("Face snapshot failed: %s", e)

    def music_play() -> None:
        nonlocal music_playing
        music.play_next()
        music_playing = True

    def music_stop() -> None:
        nonlocal music_playing
        music.stop()
        music_playing = False

    # ── Command processor ──────────────────────────────────────────────────────
    _MODE_MAP = {
        "_mode_user":       Mode.USER,
        "_mode_autonomous": Mode.AUTONOMOUS,
        "_mode_line":       Mode.LINE,
        "_mode_face":       Mode.FACE,
    }

    def _process_command(cmd: str) -> None:
        nonlocal direction, speed, speed_idx, ctrl_scheme, music_playing, mode
        cmd = cmd.strip().lower()

        if cmd in ("up", "forward"):
            motors.forward(speed);    set_led((0, 255, 0));   direction = "FORWARD"
        elif cmd in ("down", "backward"):
            motors.backward(speed);   set_led((255, 0, 0));   direction = "BACKWARD"
        elif cmd == "left":
            motors.turn_left(speed);  set_led((0, 0, 255));   direction = "LEFT"
        elif cmd == "right":
            motors.turn_right(speed); set_led((255, 255, 0)); direction = "RIGHT"
        elif cmd == "stop":
            motors.stop();            set_led((0, 0, 0));     direction = "STOPPED"
        elif cmd == "photo":
            take_photo()
        elif cmd in ("video", "video_start"):
            if not video_rec: toggle_video()
        elif cmd == "video_stop":
            if video_rec: toggle_video()
        elif cmd in ("music", "play_music", "start_music"):
            if not music_playing: music_play()      # FIX: both calls now guarded
        elif cmd in ("stop_music", "pause_music"):
            music_stop()
        elif cmd in ("skip", "next_music", "skip_music"):
            music.play_next()
        elif cmd == "speed":
            speed_idx = (speed_idx + 1) % len(speed_levels)
            speed = speed_levels[speed_idx]
        elif cmd.startswith("_speed_"):
            try:   speed = float(cmd[7:])
            except ValueError: pass
        elif cmd in _MODE_MAP:
            mode = switch_mode(mode, _MODE_MAP[cmd], ctx)

        with _robot_state_lock:
            _robot_state.update(direction=direction, speed=speed, mode=mode.name,
                                video_rec=video_rec, music_playing=music_playing)

    # ── Main loop ──────────────────────────────────────────────────────────────
    running = True

    while running:
        mouse = pygame.mouse.get_pos()

        with _stats_lock:
            st = _system_stats.copy()

        cpu_pct  = min(st.get("cpu",  0) / 100.0, 1.0)
        temp_c   = st.get("temp",  0)
        temp_pct = min(temp_c / 85.0, 1.0)
        ram_u    = st.get("ram_used",  0)
        ram_t    = st.get("ram_total", 1)
        ram_pct  = min(ram_u / max(ram_t, 1), 1.0)

        # Camera
        cam_tick += 1
        if cam_tick >= 3:
            cam_tick = 0
            cam_surf, cam_pil = _cam_to_surface(cam, CAM_W, CAM_H)

        # Feed face worker
        if mode == Mode.FACE:
            face_tick += 1
            if face_tick >= 45 and cam_pil is not None:
                face_tick = 0
                try:    _face_frame_q.put_nowait(cam_pil.copy())
                except queue.Full: pass
        else:
            face_tick = 0

        # Audio amplitudes
        amplitudes = None
        if music_playing and analyzer is not None:
            try:
                amplitudes = analyzer.get_amplitudes(pygame.mixer.music.get_pos() / 1000.0)
            except Exception:
                pass

        with _face_lock:
            face_snapshot = _face_results.copy()
        face_count = len(face_snapshot)

        # ── Render ─────────────────────────────────────────────────────────────
        screen.blit(bg_surf, (0, 0))

        _render_camera(screen, cam_surf, face_snapshot, frame, video_rec,
                       mode, CAM_X, CAM_Y, CAM_W, CAM_H,
                       CAM_NATIVE_W, CAM_NATIVE_H,
                       fmono_sm, fmono_xs, _deepface_ok.is_set())

        _render_info_strip(screen, mode, direction, speed, ctrl_scheme,
                           led_color(), face_count,
                           CAM_X, CAM_Y, CAM_H, fmono_xs, fmono_sm)

        # Panel dividers
        _hline(screen, TOP_H,     0, W)
        _hline(screen, H - BOT_H, 0, W)
        _vline(screen, L_W,       TOP_H, H - BOT_H)
        _vline(screen, W - R_W,   TOP_H, H - BOT_H)

        _render_top_bar(screen, mode, st.get("threads", 0), temp_c, st,
                        led_color(), tabs, TAB_LABELS,
                        W, TOP_H, fmono_xl, fmono_md, fmono_xs, fbody, mouse)

        _render_left_panel(screen, qr_surf, local_ip, st,
                           cpu_pct, temp_c, temp_pct, ram_u, ram_t, ram_pct,
                           st.get("latency", "N/A"), st.get("threads", 0),
                           st.get("disk_read", 0), st.get("disk_write", 0),
                           st.get("boot_time", "--:--"),
                           music, music_playing, frame, amplitudes,
                           btn_play, btn_skip, mouse,
                           lp_x, lp_w, TOP_H, PAD,
                           fmono_md, fmono_sm, fmono_xs, fbody, flabel, flabel_s)

        _render_right_panel(screen, mode, direction, speed_idx, ctrl_scheme,
                            video_rec, dpad, DPAD_GLYPHS, spd_dots, sch_btns,
                            btn_photo, btn_video, btn_face_snap,
                            rp_x, spd_y, sch_y, cap_y, TOP_H, PAD, mouse,
                            fmono_md, fmono_xs, fbody, fdpad)

        _render_bottom_bar(screen, mode, ctrl_scheme, speed, face_count, frame,
                           W, H, BOT_H, fmono_xs)

        # ── Events ─────────────────────────────────────────────────────────────
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == getattr(music, "SONG_END", -1):
                music.handle_event(event);  music_playing = music.playing

            elif event.type == pygame.KEYDOWN:
                k = event.key
                if   k == pygame.K_ESCAPE:
                    running = False
                elif k == pygame.K_TAB:
                    mode = switch_mode(mode, Mode((int(mode) + 1) % len(Mode)), ctx)
                elif k == pygame.K_m:
                    music_play()
                elif k == pygame.K_SPACE:
                    music_stop()
                elif k == pygame.K_f:
                    mode = switch_mode(mode, Mode.FACE, ctx)
                elif mode == Mode.USER:
                    if   k == pygame.K_x:
                        speed_idx = (speed_idx + 1) % len(speed_levels)
                        speed = speed_levels[speed_idx]
                    elif k == pygame.K_1: ctrl_scheme = 1
                    elif k == pygame.K_2: ctrl_scheme = 2
                    elif k == pygame.K_c: take_photo()
                    elif k == pygame.K_v: toggle_video()
                elif mode == Mode.FACE:
                    if k == pygame.K_s: save_face_snapshot()

            elif event.type == pygame.MOUSEBUTTONDOWN:
                for i, tr in enumerate(tabs):
                    if tr.collidepoint(event.pos):
                        mode = switch_mode(mode, Mode(i), ctx)

                if mode == Mode.USER:
                    for cmd, r in dpad.items():
                        if r.collidepoint(event.pos):
                            if   cmd == "forward":  motors.forward(speed);    set_led((0, 255, 0))
                            elif cmd == "backward": motors.backward(speed);   set_led((255, 0, 0))
                            elif cmd == "left":     motors.turn_left(speed);  set_led((0, 0, 255))
                            elif cmd == "right":    motors.turn_right(speed); set_led((255, 255, 0))
                            elif cmd == "stop":     motors.stop();            set_led((0, 0, 0))
                            direction = cmd.upper()
                    for i, r in enumerate(spd_dots):
                        if r.collidepoint(event.pos):
                            speed_idx = i;  speed = speed_levels[speed_idx]
                    for i, r in enumerate(sch_btns):
                        if r.collidepoint(event.pos): ctrl_scheme = i + 1
                    if btn_photo.collidepoint(event.pos): take_photo()
                    if btn_video.collidepoint(event.pos): toggle_video()

                if btn_face_snap.collidepoint(event.pos) and mode == Mode.FACE:
                    save_face_snapshot()
                if btn_play.collidepoint(event.pos):
                    music_stop() if music_playing else music_play()
                if btn_skip.collidepoint(event.pos) and music_playing:
                    music.play_next()

        # Flask queue
        while not command_queue.empty():
            _process_command(command_queue.get_nowait())

        # ── Drive logic ─────────────────────────────────────────────────────────
        if mode == Mode.AUTONOMOUS:
            if avoider:
                try:
                    if avoider.check_and_avoid(): set_led((255, 0, 0))
                except Exception as e: logger.warning("Avoider: %s", e)
            else:
                motors.stop()

        elif mode == Mode.LINE:
            if liner:
                try:    liner.follow_line()
                except Exception as e: logger.warning("LineFollower: %s", e)
            else:
                motors.stop()

        elif mode == Mode.FACE:
            motors.stop()
            set_led(face_pulse_color(frame))

        elif mode == Mode.USER:
            keys = pygame.key.get_pressed()
            if ctrl_scheme == 1:
                if   keys[pygame.K_w]: motors.forward(speed);    set_led((0, 255, 0));   direction = "FORWARD"
                elif keys[pygame.K_s]: motors.backward(speed);   set_led((255, 0, 0));   direction = "BACKWARD"
                elif keys[pygame.K_a]: motors.turn_left(speed);  set_led((0, 0, 255));   direction = "LEFT"
                elif keys[pygame.K_d]: motors.turn_right(speed); set_led((255, 255, 0)); direction = "RIGHT"
                else:                  motors.stop();            set_led((0, 0, 0));     direction = "STOPPED"
            else:
                left, right = motors.control_tank(keys, speed)
                if left and right:  set_led((0, 255, 255))
                elif left:          set_led((255, 0, 255))
                elif right:         set_led((255, 165, 0))
                else:               set_led((0, 0, 0))

        if music_playing:
            led.rhythm_wave(frame)

        led.show()
        frame += 1
        pygame.display.flip()
        clock.tick(25)

    # ── Cleanup ─────────────────────────────────────────────────────────────────
    logger.info("Shutting down…")
    switch_mode(mode, Mode.USER, ctx)   # FIX: fires real exit hook for current mode
    _face_enabled.clear()
    if video_rec:
        try: cam.stop_encoder()
        except Exception: pass
    motors.cleanup()
    if avoider: avoider.cleanup()
    if liner:   liner.cleanup()
    led.led_close()
    try: cam.stop()
    except Exception: pass
    pygame.quit()


if __name__ == "__main__":
    main()