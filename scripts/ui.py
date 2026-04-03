"""
KIDA — main UI
Fullscreen pygame dashboard + Flask web-control server.
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

# Suppress gpiozero ultrasonic / PWM fallback warnings at import time
warnings.filterwarnings("ignore", category=UserWarning)

import pygame
import numpy as np
import psutil
import qrcode
from PIL import Image
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput
from flask import Flask, jsonify, request

from mode_control       import Mode
from music_player       import MusicPlayer
from motor_control      import MotorController
from obstacle_avoidance import ObstacleAvoidance
from line_follower      import LineFollower
from led_control        import SPI_WS2812_LEDStrip
from audio_analysis     import AudioAnalyzer

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("kida.ui")

# ── Palette ───────────────────────────────────────────────────────────────────
BG     = (8,   9,  13)
PANEL  = (12,  13,  20)
BORDER = (28,  30,  44)
ACCENT = (255,  30, 100)
GREEN  = (29,  158, 117)
BLUE   = (55,  138, 221)
AMBER  = (255, 144,  32)
RED    = (226,  75,  74)
TEAL   = (20,  180, 160)
PRI    = (220, 220, 215)
SEC    = (120, 122, 115)
DIM    = (52,   54,  64)

# ── Flask ─────────────────────────────────────────────────────────────────────
app           = Flask(__name__, static_folder="static", template_folder="templates")
command_queue: queue.Queue = queue.Queue()


@app.route("/")
def home():
    return jsonify({"status": "online", "robot": "KIDA"})


@app.route("/status")
def status():
    return jsonify({"status": "online", "robot": "KIDA"})


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
            cpu  = psutil.cpu_percent()
            mem  = psutil.virtual_memory()
            dio  = psutil.disk_io_counters()
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
        time.sleep(1)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _make_qr(url: str, size: int = 110) -> pygame.Surface:
    qr = qrcode.QRCode(version=1,
                       error_correction=qrcode.constants.ERROR_CORRECT_L,
                       box_size=10, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img = img.resize((size, size), Image.LANCZOS)
    return pygame.image.fromstring(img.tobytes(), img.size, "RGB")


def _cam_to_surface(cam: Picamera2, w: int, h: int) -> pygame.Surface:
    try:
        frame = cam.capture_array()
        if frame.ndim == 3 and frame.shape[2] == 4:
            frame = frame[:, :, :3]
        pil = Image.fromarray(frame, "RGB").rotate(180)
        pil = pil.resize((w, h), Image.BILINEAR)
        return pygame.image.fromstring(pil.tobytes(), pil.size, "RGB")
    except Exception:
        s = pygame.Surface((w, h))
        s.fill((8, 10, 16))
        return s


# ── Draw primitives ───────────────────────────────────────────────────────────
def _rect_panel(surf, r, radius=6):
    pygame.draw.rect(surf, PANEL,  r, border_radius=radius)
    pygame.draw.rect(surf, BORDER, r, width=1, border_radius=radius)


def _hline(surf, y, x0, x1, color=BORDER):
    pygame.draw.line(surf, color, (x0, y), (x1, y))


def _vline(surf, x, y0, y1, color=BORDER):
    pygame.draw.line(surf, color, (x, y0), (x, y1))


def _txt(surf, font, text, pos, color=PRI, anchor="topleft"):
    s = font.render(str(text), True, color)
    r = s.get_rect(**{anchor: pos})
    surf.blit(s, r)
    return r


def _bar(surf, r, pct, color, track=(22, 24, 36)):
    pygame.draw.rect(surf, track, r, border_radius=2)
    fw = max(int(r.width * min(pct, 1.0)), 0)
    if fw:
        pygame.draw.rect(surf, color,
                         pygame.Rect(r.x, r.y, fw, r.height),
                         border_radius=2)


def _led_dot(surf, pos, color, r=5):
    pygame.draw.circle(surf, color, pos, r)
    if any(c > 10 for c in color):
        g = pygame.Surface((r * 4, r * 4), pygame.SRCALPHA)
        pygame.draw.circle(g, (*color, 55), (r * 2, r * 2), r * 2)
        surf.blit(g, (pos[0] - r * 2, pos[1] - r * 2))


def _waveform(surf, frame: int, r: pygame.Rect, bars: int = 60,
              playing: bool = False, amplitudes: list | None = None):
    bw = max(r.width // bars, 1)
    for i in range(bars):
        if amplitudes is not None:
            idx = int(i * len(amplitudes) / bars)
            h   = max(int(amplitudes[idx] * r.height * 0.95), 2)
            a   = 200
        elif playing:
            h = int((math.sin(frame * 0.14 + i * 0.32) * 0.5 + 0.5)
                    * r.height * 0.88 + 2)
            a = 160
        else:
            h, a = 2, 40
        x = r.x + i * bw
        y = r.y + r.height - h
        s = pygame.Surface((max(bw - 1, 1), h), pygame.SRCALPHA)
        s.fill((*ACCENT, a))
        surf.blit(s, (x, y))


def _grid(surf, w, h, step=40):
    gc = (18, 10, 16)
    for x in range(0, w + 1, step):
        pygame.draw.line(surf, gc, (x, 0), (x, h))
    for y in range(0, h + 1, step):
        pygame.draw.line(surf, gc, (0, y), (w, y))


def _btn(surf, font, label, r, mouse, active=False, danger=False, hover_col=ACCENT):
    hov = r.collidepoint(mouse)
    if danger:
        bc, bd, tc = (22, 8, 8), RED, RED
    elif hov or active:
        bc, bd, tc = (20, 9, 16), hover_col, hover_col
    else:
        bc, bd, tc = PANEL, BORDER, SEC
    pygame.draw.rect(surf, bc, r, border_radius=6)
    pygame.draw.rect(surf, bd, r, width=1, border_radius=6)
    if active:
        strip = pygame.Rect(r.x + 4, r.bottom - 2, r.width - 8, 2)
        pygame.draw.rect(surf, hover_col if not danger else RED, strip, border_radius=1)
    s = font.render(label, True, tc)
    surf.blit(s, (r.x + (r.width - s.get_width()) // 2,
                  r.y + (r.height - s.get_height()) // 2))


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    pygame.init()

    info   = pygame.display.Info()
    W, H   = info.current_w, info.current_h
    screen = pygame.display.set_mode(
        (W, H), pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF)
    pygame.display.set_caption("KIDA")
    clock = pygame.time.Clock()

    # ── Layout ────────────────────────────────────────────────
    TOP_H  = 48
    BOT_H  = 56
    STAT_H = 22
    WAVE_H = BOT_H - STAT_H
    L_W    = 230
    R_W    = 260
    CAM_X  = L_W
    CAM_Y  = TOP_H
    CAM_W  = W - L_W - R_W
    CAM_H  = H - TOP_H - BOT_H
    LP_X   = 8
    LP_W   = L_W - 16
    RP_X   = W - R_W + 12
    RP_W   = R_W - 24

    # ── Fonts ─────────────────────────────────────────────────
    fmono_lg = pygame.font.SysFont("Courier New", 22, bold=True)
    fmono_md = pygame.font.SysFont("Courier New", 13, bold=True)
    fmono_sm = pygame.font.SysFont("Courier New", 11)
    fmono_xs = pygame.font.SysFont("Courier New", 10)
    fbody    = pygame.font.SysFont("Arial", 13)
    flabel   = pygame.font.SysFont("Arial", 11)
    fdpad    = pygame.font.SysFont("Arial", 20, bold=True)

    # ── Background threads ────────────────────────────────────
    threading.Thread(target=_run_flask,    daemon=True).start()
    threading.Thread(target=_stats_worker, daemon=True).start()
    logger.info("Flask server started on :5000")

    # ── Hardware ──────────────────────────────────────────────
    music  = MusicPlayer("/home/nova/Desktop/kida/audio/music/")
    motors = MotorController()

    try:
        avoider = ObstacleAvoidance(motors=motors)
    except Exception as e:
        logger.warning("ObstacleAvoidance init failed: %s — autonomous mode disabled", e)
        avoider = None

    try:
        liner = LineFollower(motors=motors)
    except Exception as e:
        logger.warning("LineFollower init failed: %s — line follow mode disabled", e)
        liner = None

    led = SPI_WS2812_LEDStrip(8, 128)

    # Camera — flipped 180 via transform in config
    cam = Picamera2()
    cfg = cam.create_preview_configuration(
        main={"size": (640, 480)},
        transform=__import__("libcamera").Transform(hflip=1, vflip=1)
    )
    cam.configure(cfg)
    cam.start()

    # Video encoder (reused across recordings)
    _encoder = H264Encoder(bitrate=4000000)

    if not led.ready:
        logger.error("SPI LED strip not ready — exiting.")
        pygame.quit()
        return

    # ── QR code ───────────────────────────────────────────────
    local_ip = _get_local_ip()
    qr_surf  = _make_qr(f"http://{local_ip}:5000", size=110)

    # ── Directories ───────────────────────────────────────────
    photos_dir = "/home/nova/Desktop/kida/photos"
    videos_dir = "/home/nova/Desktop/kida/videos"
    os.makedirs(photos_dir, exist_ok=True)
    os.makedirs(videos_dir, exist_ok=True)

    # ── State ─────────────────────────────────────────────────
    mode          = Mode.USER
    speed_levels  = [0.4, 0.6, 0.8, 1.0]
    speed_idx     = 0
    speed         = speed_levels[speed_idx]
    ctrl_scheme   = 1
    music_playing = False
    video_rec     = False
    frame         = 0
    direction     = "STOPPED"
    led_color     = (0, 0, 0)
    cam_surf      = pygame.Surface((CAM_W, CAM_H))
    cam_surf.fill((8, 10, 14))
    cam_tick      = 0
    analyzer: AudioAnalyzer | None = None

    TAB_LABELS = ["🕹  USER CONTROL", "🤖  AUTONOMOUS", "〰  LINE FOLLOW"]

    # ── Button layout ─────────────────────────────────────────
    tab_w   = 130
    tab_gap = 8
    tab_y   = (TOP_H - 30) // 2
    tabs    = [
        pygame.Rect(L_W + 8 + i * (tab_w + tab_gap), tab_y, tab_w, 30)
        for i in range(len(TAB_LABELS))
    ]

    DP_Y  = TOP_H + 24
    DP_S  = 52
    DP_G  = 6
    DP_CX = RP_X + RP_W // 2 - DP_S // 2
    dpad  = {
        "forward":  pygame.Rect(DP_CX,               DP_Y,                      DP_S, DP_S),
        "left":     pygame.Rect(DP_CX - DP_S - DP_G, DP_Y + DP_S + DP_G,       DP_S, DP_S),
        "stop":     pygame.Rect(DP_CX,               DP_Y + DP_S + DP_G,        DP_S, DP_S),
        "right":    pygame.Rect(DP_CX + DP_S + DP_G, DP_Y + DP_S + DP_G,       DP_S, DP_S),
        "backward": pygame.Rect(DP_CX,               DP_Y + (DP_S + DP_G) * 2,  DP_S, DP_S),
    }
    DPAD_GLYPHS = {"forward": "▲", "left": "◀", "stop": "■", "right": "▶", "backward": "▼"}

    spd_y    = DP_Y + (DP_S + DP_G) * 3 + 22
    spd_w    = (RP_W - DP_G * 3) // 4
    spd_dots = [pygame.Rect(RP_X + i * (spd_w + DP_G), spd_y, spd_w, 32) for i in range(4)]

    sch_y    = spd_y + 48
    sch_w    = (RP_W - DP_G) // 2
    sch_btns = [
        pygame.Rect(RP_X,                sch_y, sch_w, 30),
        pygame.Rect(RP_X + sch_w + DP_G, sch_y, sch_w, 30),
    ]

    pv_y      = sch_y + 48
    pv_w      = (RP_W - DP_G) // 2
    btn_photo = pygame.Rect(RP_X,               pv_y, pv_w, 34)
    btn_video = pygame.Rect(RP_X + pv_w + DP_G, pv_y, pv_w, 34)

    mus_base = TOP_H + 130
    btn_play = pygame.Rect(LP_X,                        mus_base + 38, (LP_W - 6) // 2, 30)
    btn_skip = pygame.Rect(LP_X + (LP_W - 6) // 2 + 6, mus_base + 38, (LP_W - 6) // 2, 30)

    # ── Closures ──────────────────────────────────────────────
    def take_photo() -> None:
        fname = os.path.join(photos_dir, f"photo_{int(time.time())}.jpg")
        try:
            cam.capture_file(fname)
            logger.info("Photo saved: %s", fname)
        except Exception as e:
            logger.error("Photo failed: %s", e)

    def toggle_video() -> None:
        nonlocal video_rec
        if not video_rec:
            fname = os.path.join(videos_dir, f"video_{int(time.time())}.mp4")
            try:
                output = FfmpegOutput(fname)
                cam.start_encoder(_encoder, output)
                video_rec = True
                logger.info("Recording started: %s", fname)
            except Exception as e:
                logger.error("Video start failed: %s", e)
        else:
            try:
                cam.stop_encoder()
            except Exception as e:
                logger.error("Video stop failed: %s", e)
            video_rec = False
            logger.info("Recording stopped")

    def set_led(color: tuple) -> None:
        nonlocal led_color
        led_color = color
        led.set_all_led_color(*color)

    def _process_command(cmd: str) -> None:
        nonlocal direction, speed, speed_idx, ctrl_scheme, music_playing
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
        elif cmd == "video":
            toggle_video()
        elif cmd in ("music", "play_music", "start_music"):
            if not music_playing:
                music.play_next(); music_playing = True
        elif cmd in ("stop_music", "pause_music"):
            music.stop(); music_playing = False
        elif cmd in ("skip", "next_music"):
            music.play_next()
        elif cmd == "speed":
            speed_idx = (speed_idx + 1) % len(speed_levels)
            speed = speed_levels[speed_idx]

    # ── Main loop ─────────────────────────────────────────────
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
        latency  = st.get("latency",  "N/A")
        n_thr    = st.get("threads",  0)
        disk_r   = st.get("disk_read",  0)
        disk_w   = st.get("disk_write", 0)
        boot_t   = st.get("boot_time", "--:--")

        # Camera — capture every 2 frames
        cam_tick += 1
        if cam_tick >= 2:
            cam_tick = 0
            cam_surf = _cam_to_surface(cam, CAM_W, CAM_H)

        # Real waveform amplitudes when music is playing
        amplitudes = None
        if music_playing and analyzer is not None:
            try:
                pos = pygame.mixer.music.get_pos() / 1000.0
                amplitudes = analyzer.get_amplitudes(pos)
            except Exception:
                pass

        # ── Render ────────────────────────────────────────────
        screen.fill(BG)
        _grid(screen, W, H)

        screen.blit(cam_surf, (CAM_X, CAM_Y))

        # Vignette
        vw = 32
        for i in range(vw):
            a = int(200 * (1 - i / vw))
            s = pygame.Surface((1, CAM_H), pygame.SRCALPHA)
            s.fill((0, 0, 0, a))
            screen.blit(s, (CAM_X + i,             CAM_Y))
            screen.blit(s, (CAM_X + CAM_W - 1 - i, CAM_Y))

        # HUD corner brackets
        blen, bthk = 24, 2
        for (cx, cy, sx, sy) in [
            (CAM_X + 6,         CAM_Y + 6,          1,  1),
            (CAM_X + CAM_W - 6, CAM_Y + 6,         -1,  1),
            (CAM_X + 6,         CAM_Y + CAM_H - 6,  1, -1),
            (CAM_X + CAM_W - 6, CAM_Y + CAM_H - 6, -1, -1),
        ]:
            pygame.draw.line(screen, ACCENT, (cx, cy), (cx + sx * blen, cy), bthk)
            pygame.draw.line(screen, ACCENT, (cx, cy), (cx, cy + sy * blen), bthk)

        # REC blink
        if video_rec and (frame // 15) % 2 == 0:
            pygame.draw.circle(screen, RED, (CAM_X + CAM_W - 22, CAM_Y + 14), 5)
            _txt(screen, fmono_xs, "REC", (CAM_X + CAM_W - 14, CAM_Y + 9), RED)

        # Mode overlay
        if mode == Mode.AUTONOMOUS:
            msg      = "— AUTONOMOUS OBSTACLE AVOIDANCE —"
            ov_color = TEAL
        elif mode == Mode.LINE:
            msg      = "— LINE FOLLOWER —"
            ov_color = BLUE
        else:
            msg = None

        if msg:
            ms = fmono_sm.render(msg, True, ov_color)
            mx = CAM_X + (CAM_W - ms.get_width()) // 2
            my = CAM_Y + CAM_H - 28
            ov = pygame.Surface((ms.get_width() + 20, ms.get_height() + 10), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 130))
            screen.blit(ov, (mx - 10, my - 4))
            screen.blit(ms, (mx, my))

        # Dividers
        _hline(screen, TOP_H,      0, W)
        _hline(screen, H - BOT_H,  0, W)
        _hline(screen, H - STAT_H, 0, W)
        _vline(screen, L_W,        TOP_H, H - BOT_H)
        _vline(screen, W - R_W,    TOP_H, H - BOT_H)

        # ── Top bar ───────────────────────────────────────────
        logo = fmono_lg.render("KIDA", True, ACCENT)
        screen.blit(logo, (12, (TOP_H - logo.get_height()) // 2))

        for i, (tr, tl) in enumerate(zip(tabs, TAB_LABELS)):
            _btn(screen, fbody, tl, tr, mouse, active=(mode == i))

        chip_x = W - 14
        for lbl, val, warn in [
            ("THR",  str(n_thr),                   False),
            ("TEMP", f"{temp_c:.0f}C",             temp_c > 65),
            ("CPU",  f"{st.get('cpu', 0):.0f}%",  False),
        ]:
            col = AMBER if warn else PRI
            vs  = fmono_sm.render(val, True, col)
            ls  = fmono_xs.render(lbl, True, DIM)
            chip_x -= vs.get_width() + 4
            screen.blit(vs, (chip_x, (TOP_H - vs.get_height()) // 2))
            chip_x -= ls.get_width() + 10
            screen.blit(ls, (chip_x, (TOP_H - ls.get_height()) // 2))
            chip_x -= 12

        for i in range(8):
            dc = led_color if any(c > 10 for c in led_color) else (24, 26, 38)
            _led_dot(screen, (chip_x - 14 - i * 14, TOP_H // 2), dc, r=4)

        # ── Left panel ────────────────────────────────────────
        lp_y = TOP_H + 10

        screen.blit(qr_surf, (LP_X, lp_y))
        _txt(screen, fmono_xs, f"{local_ip}:5000",
             (LP_X + LP_W // 2, lp_y + 114), AMBER, anchor="midtop")
        lp_y += 132

        _txt(screen, fmono_xs, "SYSTEM", (LP_X, lp_y), DIM)
        lp_y += 13
        for label, val, pct, bc in [
            ("CPU",  f"{st.get('cpu', 0):.0f}%", cpu_pct,  ACCENT),
            ("TEMP", f"{temp_c:.0f}C",            temp_pct, AMBER),
            ("RAM",  f"{ram_u}/{ram_t}M",          ram_pct,  BLUE),
        ]:
            _txt(screen, flabel,   label, (LP_X, lp_y), DIM)
            _txt(screen, fmono_xs, val,   (LP_X + LP_W, lp_y + 1), SEC, anchor="topright")
            _bar(screen, pygame.Rect(LP_X, lp_y + 12, LP_W, 3), pct, bc)
            lp_y += 22

        lp_y += 4
        _txt(screen, fmono_xs, "NETWORK", (LP_X, lp_y), DIM)
        lp_y += 13
        for label, val in [
            ("LATENCY", latency),
            ("THREADS", str(n_thr)),
            ("DISK R",  f"{disk_r}MB"),
            ("DISK W",  f"{disk_w}MB"),
            ("BOOT",    boot_t),
        ]:
            _txt(screen, flabel,   label,    (LP_X, lp_y), DIM)
            _txt(screen, fmono_xs, str(val), (LP_X + LP_W, lp_y + 1), SEC, anchor="topright")
            pygame.draw.line(screen, (20, 22, 32), (LP_X, lp_y + 13), (LP_X + LP_W, lp_y + 13))
            lp_y += 16

        # Music section
        lp_y += 8
        _txt(screen, fmono_xs, "MUSIC", (LP_X, lp_y), DIM)
        lp_y += 13

        track = music.current_track or "No track"
        tn = fbody.render(str(track)[:26], True, PRI if music_playing else SEC)
        screen.blit(tn, (LP_X, lp_y))
        lp_y += 18

        _waveform(screen, frame,
                  pygame.Rect(LP_X, lp_y, LP_W, 26),
                  bars=26, playing=music_playing, amplitudes=amplitudes)
        lp_y += 30

        btn_play = pygame.Rect(LP_X,                        mus_base + 38, (LP_W - 6) // 2, 30)
        btn_skip = pygame.Rect(LP_X + (LP_W - 6) // 2 + 6, mus_base + 38, (LP_W - 6) // 2, 30)
        _btn(screen, flabel, "PAUSE" if music_playing else "PLAY", btn_play, mouse,
             active=music_playing)
        _btn(screen, flabel, "SKIP", btn_skip, mouse)

        # ── Right panel ───────────────────────────────────────
        _txt(screen, fmono_xs, "DIRECTIONAL CONTROL", (RP_X, TOP_H + 10), DIM)

        for cmd, r in dpad.items():
            is_stop = cmd == "stop"
            _btn(screen,
                 fmono_sm if is_stop else fdpad,
                 DPAD_GLYPHS[cmd], r, mouse,
                 danger=is_stop,
                 hover_col=ACCENT)
            if cmd != "stop" and direction.lower() == cmd:
                pygame.draw.rect(screen, ACCENT, r, width=2, border_radius=6)

        _txt(screen, fmono_xs, "SPEED LEVEL", (RP_X, spd_y - 14), DIM)
        for i, r in enumerate(spd_dots):
            _btn(screen, fmono_md, str(i + 1), r, mouse, active=(speed_idx == i))

        _txt(screen, fmono_xs, "CONTROL SCHEME", (RP_X, sch_y - 14), DIM)
        for i, (r, lbl) in enumerate(zip(sch_btns, ["WASD", "QA/WS"])):
            _btn(screen, flabel, lbl, r, mouse, active=(ctrl_scheme == i + 1))

        _txt(screen, fmono_xs, "CAPTURE", (RP_X, pv_y - 14), DIM)
        _btn(screen, flabel, "PHOTO", btn_photo, mouse, hover_col=BLUE)
        _btn(screen, flabel,
             "STOP REC" if video_rec else "REC",
             btn_video, mouse,
             active=video_rec,
             hover_col=RED, danger=video_rec)

        # Motor readout
        mrd_y = H - BOT_H - 76
        for label, val in [
            ("DIR",    direction),
            ("SPEED",  f"{speed:.1f}"),
            ("SCHEME", "WASD" if ctrl_scheme == 1 else "QA/WS"),
            ("LED",    f"R{led_color[0]} G{led_color[1]} B{led_color[2]}"),
        ]:
            _txt(screen, flabel,   label,    (RP_X, mrd_y), DIM)
            _txt(screen, fmono_xs, str(val), (RP_X + RP_W, mrd_y), SEC, anchor="topright")
            pygame.draw.line(screen, (18, 20, 30),
                             (RP_X, mrd_y + 15), (RP_X + RP_W, mrd_y + 15))
            mrd_y += 18

        # ── Bottom — waveform + status bar ────────────────────
        _waveform(screen, frame,
                  pygame.Rect(0, H - BOT_H, W, WAVE_H),
                  bars=96, playing=music_playing, amplitudes=amplitudes)

        sb_y = H - STAT_H
        screen.fill((10, 11, 16), pygame.Rect(0, sb_y, W, STAT_H))
        _hline(screen, sb_y, 0, W)
        pygame.draw.circle(screen, GREEN, (14, sb_y + STAT_H // 2), 4)

        sx = 28
        for lbl, val in [
            ("FLASK",  ":5000"),
            ("MODE",   mode.name),
            ("SCHEME", "WASD" if ctrl_scheme == 1 else "QA/WS"),
            ("SPEED",  f"{speed:.1f}"),
            ("FRM",    str(frame)),
            ("CAM",    "LIVE"),
        ]:
            ls = fmono_xs.render(lbl, True, DIM)
            vs = fmono_xs.render(val, True, SEC)
            screen.blit(ls, (sx, sb_y + (STAT_H - ls.get_height()) // 2))
            sx += ls.get_width() + 4
            screen.blit(vs, (sx, sb_y + (STAT_H - vs.get_height()) // 2))
            sx += vs.get_width() + 14
            pygame.draw.line(screen, BORDER, (sx - 6, sb_y + 4), (sx - 6, sb_y + STAT_H - 4))

        vers = fmono_xs.render("KIDA v2.0 · RASPBERRY PI", True, DIM)
        screen.blit(vers, (W - vers.get_width() - 12,
                           sb_y + (STAT_H - vers.get_height()) // 2))

        # ── Events ────────────────────────────────────────────
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == getattr(music, "SONG_END", -1):
                music.handle_event(event)
                music_playing = music.playing

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_TAB:
                    mode = Mode((mode + 1) % len(Mode))
                elif event.key == pygame.K_m:
                    music.play_next(); music_playing = True
                elif event.key == pygame.K_SPACE:
                    music.stop();      music_playing = False
                elif mode == Mode.USER:
                    if event.key == pygame.K_x:
                        speed_idx = (speed_idx + 1) % len(speed_levels)
                        speed = speed_levels[speed_idx]
                    elif event.key == pygame.K_1:
                        ctrl_scheme = 1
                    elif event.key == pygame.K_2:
                        ctrl_scheme = 2
                    elif event.key == pygame.K_c:
                        take_photo()
                    elif event.key == pygame.K_v:
                        toggle_video()

            elif event.type == pygame.MOUSEBUTTONDOWN:
                for i, tr in enumerate(tabs):
                    if tr.collidepoint(event.pos):
                        mode = Mode(i)

                if mode == Mode.USER:
                    for cmd, r in dpad.items():
                        if r.collidepoint(event.pos):
                            if cmd == "forward":
                                motors.forward(speed);    set_led((0, 255, 0))
                            elif cmd == "backward":
                                motors.backward(speed);   set_led((255, 0, 0))
                            elif cmd == "left":
                                motors.turn_left(speed);  set_led((0, 0, 255))
                            elif cmd == "right":
                                motors.turn_right(speed); set_led((255, 255, 0))
                            elif cmd == "stop":
                                motors.stop();            set_led((0, 0, 0))
                            direction = cmd.upper()

                    for i, r in enumerate(spd_dots):
                        if r.collidepoint(event.pos):
                            speed_idx = i
                            speed = speed_levels[speed_idx]

                    for i, r in enumerate(sch_btns):
                        if r.collidepoint(event.pos):
                            ctrl_scheme = i + 1

                    if btn_photo.collidepoint(event.pos):
                        take_photo()
                    if btn_video.collidepoint(event.pos):
                        toggle_video()

                if btn_play.collidepoint(event.pos):
                    if music_playing:
                        music.stop();      music_playing = False
                    else:
                        music.play_next(); music_playing = True
                if btn_skip.collidepoint(event.pos) and music_playing:
                    music.play_next()

        # ── Flask command queue ───────────────────────────────
        while not command_queue.empty():
            _process_command(command_queue.get_nowait())

        # ── Drive logic ───────────────────────────────────────
        if mode == Mode.AUTONOMOUS:
            if avoider is not None:
                try:
                    if avoider.check_and_avoid():
                        set_led((255, 0, 0))
                except Exception as e:
                    logger.warning("Avoider error: %s", e)
            else:
                motors.stop()

        elif mode == Mode.LINE:
            if liner is not None:
                try:
                    liner.follow_line()
                except Exception as e:
                    logger.warning("LineFollower error: %s", e)
            else:
                motors.stop()

        elif mode == Mode.USER:
            keys = pygame.key.get_pressed()
            if ctrl_scheme == 1:
                if keys[pygame.K_w]:
                    motors.forward(speed);    set_led((0, 255, 0));   direction = "FORWARD"
                elif keys[pygame.K_s]:
                    motors.backward(speed);   set_led((255, 0, 0));   direction = "BACKWARD"
                elif keys[pygame.K_a]:
                    motors.turn_left(speed);  set_led((0, 0, 255));   direction = "LEFT"
                elif keys[pygame.K_d]:
                    motors.turn_right(speed); set_led((255, 255, 0)); direction = "RIGHT"
                else:
                    motors.stop();            set_led((0, 0, 0));     direction = "STOPPED"
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
        clock.tick(30)

    # ── Cleanup ───────────────────────────────────────────────
    logger.info("Shutting down…")
    if video_rec:
        try:
            cam.stop_encoder()
        except Exception:
            pass
    motors.cleanup()
    if avoider is not None:
        avoider.cleanup()
    if liner is not None:
        liner.cleanup()
    led.led_close()
    try:
        cam.stop()
    except Exception:
        pass
    pygame.quit()


if __name__ == "__main__":
    main()
