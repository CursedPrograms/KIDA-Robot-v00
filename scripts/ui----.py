"""
KIDA — redesigned main UI
Larger controls · Compact camera · Performance-optimised render loop
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
PANEL  = (14,  15,  22)
PANEL2 = (18,  20,  30)
BORDER = (32,  35,  52)
ACCENT = (255,  30, 100)
GREEN  = (29,  200, 120)
BLUE   = (55,  138, 221)
AMBER  = (255, 160,  40)
RED    = (226,  75,  74)
TEAL   = (20,  200, 170)
PRI    = (230, 230, 225)
SEC    = (130, 132, 125)
DIM    = (60,   62,  75)

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
        time.sleep(2)   # slower polling = less CPU


# ── Helpers ───────────────────────────────────────────────────────────────────
def _make_qr(url: str, size: int = 90) -> pygame.Surface:
    qr = qrcode.QRCode(version=1,
                       error_correction=qrcode.constants.ERROR_CORRECT_L,
                       box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img = img.resize((size, size), Image.LANCZOS)
    return pygame.image.fromstring(img.tobytes(), img.size, "RGB")


# Camera surface — captured into a pre-allocated buffer, scaled with numpy
_cam_buffer: pygame.Surface | None = None

def _cam_to_surface(cam: Picamera2, w: int, h: int) -> pygame.Surface:
    global _cam_buffer
    try:
        frame = cam.capture_array()
        if frame.ndim == 3 and frame.shape[2] == 4:
            frame = frame[:, :, :3]
        # Use PIL NEAREST for speed (camera already small)
        pil = Image.fromarray(frame, "RGB").rotate(180)
        pil = pil.resize((w, h), Image.NEAREST)
        surf = pygame.image.fromstring(pil.tobytes(), pil.size, "RGB")
        return surf
    except Exception:
        s = pygame.Surface((w, h))
        s.fill((8, 10, 16))
        return s


# ── Draw primitives ───────────────────────────────────────────────────────────
def _rect_panel(surf, r, radius=8):
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


def _bar(surf, r, pct, color, track=(18, 20, 32)):
    pygame.draw.rect(surf, track, r, border_radius=3)
    fw = max(int(r.width * min(pct, 1.0)), 0)
    if fw:
        pygame.draw.rect(surf, color,
                         pygame.Rect(r.x, r.y, fw, r.height),
                         border_radius=3)


def _led_dot(surf, pos, color, r=6):
    pygame.draw.circle(surf, color, pos, r)


def _waveform(surf, frame: int, r: pygame.Rect, bars: int = 48,
              playing: bool = False, amplitudes: list | None = None):
    bw = max(r.width // bars, 2)
    gap = 1
    for i in range(bars):
        if amplitudes is not None:
            idx = int(i * len(amplitudes) / bars)
            h   = max(int(amplitudes[idx] * r.height * 0.92), 3)
            col = (*ACCENT, 180)
        elif playing:
            h = int((math.sin(frame * 0.12 + i * 0.3) * 0.5 + 0.5)
                    * r.height * 0.85 + 3)
            col = (*ACCENT, 140)
        else:
            h   = 3
            col = (*DIM, 80)
        x = r.x + i * bw
        y = r.y + r.height - h
        s = pygame.Surface((max(bw - gap, 1), h), pygame.SRCALPHA)
        s.fill(col)
        surf.blit(s, (x, y))


def _btn(surf, font, label, r, mouse, active=False, danger=False, hover_col=ACCENT):
    hov = r.collidepoint(mouse)
    if danger:
        bc = (28, 10, 10)
        bd = RED
        tc = RED
    elif hov or active:
        bc = (22, 10, 18)
        bd = hover_col
        tc = hover_col
    else:
        bc = PANEL
        bd = BORDER
        tc = SEC
    pygame.draw.rect(surf, bc, r, border_radius=8)
    pygame.draw.rect(surf, bd, r, width=1, border_radius=8)
    if active and not danger:
        strip = pygame.Rect(r.x + 6, r.bottom - 3, r.width - 12, 3)
        pygame.draw.rect(surf, hover_col, strip, border_radius=2)
    s = font.render(label, True, tc)
    surf.blit(s, (r.x + (r.width - s.get_width()) // 2,
                  r.y + (r.height - s.get_height()) // 2))


def _section_label(surf, font, text, x, y):
    """Draw a small uppercase section header with left accent tick."""
    pygame.draw.rect(surf, ACCENT, pygame.Rect(x, y + 2, 2, 10))
    _txt(surf, font, text, (x + 7, y), DIM)


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
    # New layout: top bar | left=controls+stats | centre=camera(smaller)+tabs | right=dpad+capture
    TOP_H  = 52
    BOT_H  = 38        # thinner bottom bar
    PAD    = 10

    L_W    = 260       # left panel (stats + music)
    R_W    = 280       # right panel (dpad + capture)

    # Camera sits top-right of centre, smaller proportion
    CAM_AVAIL_W = W - L_W - R_W
    CAM_AVAIL_H = H - TOP_H - BOT_H
    # Camera = 55% of available centre width, full height minus tab strip
    TAB_H  = 44
    CAM_W  = int(CAM_AVAIL_W * 0.80)
    CAM_H  = int(CAM_AVAIL_H * 0.62)
    CAM_X  = L_W + (CAM_AVAIL_W - CAM_W) // 2
    CAM_Y  = TOP_H + TAB_H + PAD

    # ── Fonts — all larger ────────────────────────────────────
    fmono_xl = pygame.font.SysFont("Courier New", 28, bold=True)   # logo
    fmono_lg = pygame.font.SysFont("Courier New", 20, bold=True)
    fmono_md = pygame.font.SysFont("Courier New", 16, bold=True)
    fmono_sm = pygame.font.SysFont("Courier New", 14, bold=True)
    fmono_xs = pygame.font.SysFont("Courier New", 12)
    fbody    = pygame.font.SysFont("Arial", 15, bold=True)
    flabel   = pygame.font.SysFont("Arial", 14)
    flabel_s = pygame.font.SysFont("Arial", 12)
    fdpad    = pygame.font.SysFont("Arial", 26, bold=True)

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
        logger.warning("ObstacleAvoidance init failed: %s", e)
        avoider = None

    try:
        liner = LineFollower(motors=motors)
    except Exception as e:
        logger.warning("LineFollower init failed: %s", e)
        liner = None

    led = SPI_WS2812_LEDStrip(8, 128)

    cam = Picamera2()
    cfg = cam.create_preview_configuration(
        main={"size": (320, 240)},          # smaller native capture = faster resize
        transform=__import__("libcamera").Transform(hflip=1, vflip=1)
    )
    cam.configure(cfg)
    cam.start()

    _encoder = H264Encoder(bitrate=4000000)

    if not led.ready:
        logger.error("SPI LED strip not ready — exiting.")
        pygame.quit()
        return

    # ── QR code ───────────────────────────────────────────────
    local_ip = _get_local_ip()
    qr_surf  = _make_qr(f"http://{local_ip}:5000", size=90)

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

    TAB_LABELS = ["USER CTRL", "AUTONOMOUS", "LINE FOLLOW"]

    # ── Tab buttons in centre area ─────────────────────────────
    tab_w     = min(130, (CAM_AVAIL_W - PAD * 4) // 3)
    tab_total = tab_w * 3 + PAD * 2
    tab_x0    = L_W + (CAM_AVAIL_W - tab_total) // 2
    tabs      = [
        pygame.Rect(tab_x0 + i * (tab_w + PAD), TOP_H + 6, tab_w, TAB_H - 12)
        for i in range(3)
    ]

    # ── D-pad — larger buttons ────────────────────────────────
    DP_S  = 68          # button size
    DP_G  = 8           # gap
    DP_CX = W - R_W + (R_W - DP_S) // 2    # centred in right panel
    DP_Y  = TOP_H + TAB_H + PAD + 10

    dpad = {
        "forward":  pygame.Rect(DP_CX,               DP_Y,                      DP_S, DP_S),
        "left":     pygame.Rect(DP_CX - DP_S - DP_G, DP_Y + DP_S + DP_G,       DP_S, DP_S),
        "stop":     pygame.Rect(DP_CX,               DP_Y + DP_S + DP_G,        DP_S, DP_S),
        "right":    pygame.Rect(DP_CX + DP_S + DP_G, DP_Y + DP_S + DP_G,       DP_S, DP_S),
        "backward": pygame.Rect(DP_CX,               DP_Y + (DP_S + DP_G) * 2,  DP_S, DP_S),
    }
    DPAD_GLYPHS = {"forward": "▲", "left": "◀", "stop": "■", "right": "▶", "backward": "▼"}

    # ── Speed buttons ─────────────────────────────────────────
    spd_y   = DP_Y + (DP_S + DP_G) * 3 + 20
    rp_x    = W - R_W + PAD
    rp_w    = R_W - PAD * 2
    spd_w   = (rp_w - DP_G * 3) // 4
    spd_h   = 40
    spd_dots = [pygame.Rect(rp_x + i * (spd_w + DP_G), spd_y, spd_w, spd_h) for i in range(4)]

    # ── Control scheme buttons ────────────────────────────────
    sch_y   = spd_y + spd_h + 22
    sch_w   = (rp_w - DP_G) // 2
    sch_h   = 40
    sch_btns = [
        pygame.Rect(rp_x,                sch_y, sch_w, sch_h),
        pygame.Rect(rp_x + sch_w + DP_G, sch_y, sch_w, sch_h),
    ]

    # ── Capture buttons ───────────────────────────────────────
    cap_y     = sch_y + sch_h + 22
    cap_w     = (rp_w - DP_G) // 2
    cap_h     = 44
    btn_photo = pygame.Rect(rp_x,               cap_y, cap_w, cap_h)
    btn_video = pygame.Rect(rp_x + cap_w + DP_G, cap_y, cap_w, cap_h)

    # ── Left panel layout ─────────────────────────────────────
    lp_x   = PAD
    lp_w   = L_W - PAD * 2

    # Music play/skip — positioned below stats
    mus_btn_y = H - BOT_H - 70
    mus_btn_h = 44
    mus_btn_w = (lp_w - DP_G) // 2
    btn_play  = pygame.Rect(lp_x,                    mus_btn_y, mus_btn_w, mus_btn_h)
    btn_skip  = pygame.Rect(lp_x + mus_btn_w + DP_G, mus_btn_y, mus_btn_w, mus_btn_h)

    # ── Pre-bake static background surface ────────────────────
    # Draw grid once onto a surface, blit each frame instead of line-by-line
    bg_surf = pygame.Surface((W, H))
    bg_surf.fill(BG)
    gc = (14, 8, 12)
    step = 44
    for x in range(0, W + 1, step):
        pygame.draw.line(bg_surf, gc, (x, 0), (x, H))
    for y in range(0, H + 1, step):
        pygame.draw.line(bg_surf, gc, (0, y), (W, y))
    # Panel backgrounds (static regions)
    pygame.draw.rect(bg_surf, PANEL, pygame.Rect(0, TOP_H, L_W, H - TOP_H - BOT_H))
    pygame.draw.rect(bg_surf, PANEL, pygame.Rect(W - R_W, TOP_H, R_W, H - TOP_H - BOT_H))
    pygame.draw.rect(bg_surf, (10, 11, 16), pygame.Rect(0, H - BOT_H, W, BOT_H))

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
                cam.start_encoder(_encoder, FfmpegOutput(fname))
                video_rec = True
                logger.info("Recording: %s", fname)
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

        # Camera — capture every 3 frames for better perf
        cam_tick += 1
        if cam_tick >= 3:
            cam_tick = 0
            cam_surf = _cam_to_surface(cam, CAM_W, CAM_H)

        amplitudes = None
        if music_playing and analyzer is not None:
            try:
                pos = pygame.mixer.music.get_pos() / 1000.0
                amplitudes = analyzer.get_amplitudes(pos)
            except Exception:
                pass

        # ── Render ────────────────────────────────────────────
        # Blit pre-baked background (grid + panel fills)
        screen.blit(bg_surf, (0, 0))

        # ── Camera feed ───────────────────────────────────────
        screen.blit(cam_surf, (CAM_X, CAM_Y))

        # Camera border
        pygame.draw.rect(screen, BORDER,
                         pygame.Rect(CAM_X - 1, CAM_Y - 1, CAM_W + 2, CAM_H + 2), 1)

        # HUD corner brackets
        blen, bthk = 20, 2
        for (cx, cy, sx, sy) in [
            (CAM_X + 5,         CAM_Y + 5,          1,  1),
            (CAM_X + CAM_W - 5, CAM_Y + 5,         -1,  1),
            (CAM_X + 5,         CAM_Y + CAM_H - 5,  1, -1),
            (CAM_X + CAM_W - 5, CAM_Y + CAM_H - 5, -1, -1),
        ]:
            pygame.draw.line(screen, ACCENT, (cx, cy), (cx + sx * blen, cy), bthk)
            pygame.draw.line(screen, ACCENT, (cx, cy), (cx, cy + sy * blen), bthk)

        # REC blink
        if video_rec and (frame // 12) % 2 == 0:
            pygame.draw.circle(screen, RED, (CAM_X + CAM_W - 18, CAM_Y + 12), 5)
            _txt(screen, fmono_xs, "REC", (CAM_X + CAM_W - 10, CAM_Y + 7), RED)

        # Mode overlay
        if mode == Mode.AUTONOMOUS:
            msg, ov_color = "— AUTONOMOUS —", TEAL
        elif mode == Mode.LINE:
            msg, ov_color = "— LINE FOLLOW —", BLUE
        else:
            msg = None

        if msg:
            ms = fmono_sm.render(msg, True, ov_color)
            mx = CAM_X + (CAM_W - ms.get_width()) // 2
            my = CAM_Y + CAM_H - 26
            ov = pygame.Surface((ms.get_width() + 16, ms.get_height() + 8), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 140))
            screen.blit(ov, (mx - 8, my - 4))
            screen.blit(ms, (mx, my))

        # Info strip below camera
        info_y = CAM_Y + CAM_H + 8
        info_items = [
            ("DIR",    direction,          AMBER if direction != "STOPPED" else SEC),
            ("SPEED",  f"{speed:.1f}",     PRI),
            ("SCHEME", "WASD" if ctrl_scheme == 1 else "QA/WS", PRI),
            ("LED",    f"R{led_color[0]} G{led_color[1]} B{led_color[2]}", SEC),
        ]
        ix = CAM_X
        for lbl, val, vc in info_items:
            ls = fmono_xs.render(lbl, True, DIM)
            vs = fmono_sm.render(val, True, vc)
            screen.blit(ls, (ix, info_y))
            screen.blit(vs, (ix, info_y + 14))
            ix += max(ls.get_width(), vs.get_width()) + 20

        # Dividers
        _hline(screen, TOP_H,     0, W)
        _hline(screen, H - BOT_H, 0, W)
        _vline(screen, L_W,       TOP_H, H - BOT_H)
        _vline(screen, W - R_W,   TOP_H, H - BOT_H)

        # ── Top bar ───────────────────────────────────────────
        logo = fmono_xl.render("KIDA", True, ACCENT)
        screen.blit(logo, (14, (TOP_H - logo.get_height()) // 2))

        # Tabs
        for i, (tr, tl) in enumerate(zip(tabs, TAB_LABELS)):
            _btn(screen, fbody, tl, tr, mouse, active=(mode == i))

        # Top-right chips
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
            chip_x -= 16

        # LED dots
        for i in range(8):
            dc = led_color if any(c > 10 for c in led_color) else (28, 30, 44)
            _led_dot(screen, (chip_x - 12 - i * 14, TOP_H // 2), dc, r=5)

        # ── Left panel ────────────────────────────────────────
        lp_y = TOP_H + PAD

        # QR code
        screen.blit(qr_surf, (lp_x, lp_y))
        _txt(screen, fmono_xs, f"{local_ip}:5000",
             (lp_x + lp_w // 2, lp_y + 94), AMBER, anchor="midtop")
        lp_y += 110

        # System stats
        _section_label(screen, fmono_xs, "SYSTEM", lp_x, lp_y)
        lp_y += 18
        for label, val, pct, bc in [
            ("CPU",  f"{st.get('cpu', 0):.0f}%", cpu_pct,  ACCENT),
            ("TEMP", f"{temp_c:.0f}°C",           temp_pct, AMBER),
            ("RAM",  f"{ram_u}/{ram_t}M",          ram_pct,  BLUE),
        ]:
            _txt(screen, flabel_s, label, (lp_x, lp_y), DIM)
            _txt(screen, fmono_sm, val,   (lp_x + lp_w, lp_y), SEC, anchor="topright")
            _bar(screen, pygame.Rect(lp_x, lp_y + 16, lp_w, 5), pct, bc)
            lp_y += 28

        lp_y += 6
        _section_label(screen, fmono_xs, "NETWORK", lp_x, lp_y)
        lp_y += 18
        for label, val in [
            ("LATENCY", latency),
            ("THREADS", str(n_thr)),
            ("DISK R",  f"{disk_r} MB"),
            ("DISK W",  f"{disk_w} MB"),
            ("BOOT",    boot_t),
        ]:
            _txt(screen, flabel_s, label,    (lp_x, lp_y), DIM)
            _txt(screen, fmono_sm, str(val), (lp_x + lp_w, lp_y), SEC, anchor="topright")
            pygame.draw.line(screen, (22, 24, 36), (lp_x, lp_y + 18), (lp_x + lp_w, lp_y + 18))
            lp_y += 22

        # Music section
        lp_y += 8
        _section_label(screen, fmono_xs, "MUSIC", lp_x, lp_y)
        lp_y += 18
        track = music.current_track or "No track"
        tn = flabel.render(str(track)[:24], True, PRI if music_playing else SEC)
        screen.blit(tn, (lp_x, lp_y))
        lp_y += 20

        _waveform(screen, frame,
                  pygame.Rect(lp_x, lp_y, lp_w, 28),
                  bars=24, playing=music_playing, amplitudes=amplitudes)
        lp_y += 36

        _btn(screen, fbody, "PAUSE" if music_playing else "PLAY",
             btn_play, mouse, active=music_playing)
        _btn(screen, fbody, "SKIP ▶", btn_skip, mouse)

        # ── Right panel ───────────────────────────────────────
        _section_label(screen, fmono_xs, "DIRECTIONAL CONTROL",
                       rp_x, TOP_H + PAD)

        for cmd, r in dpad.items():
            is_stop = cmd == "stop"
            _btn(screen,
                 fmono_md if is_stop else fdpad,
                 DPAD_GLYPHS[cmd], r, mouse,
                 danger=is_stop, hover_col=ACCENT)
            if cmd != "stop" and direction.lower() == cmd:
                pygame.draw.rect(screen, ACCENT, r, width=2, border_radius=8)

        _section_label(screen, fmono_xs, "SPEED", rp_x, spd_y - 18)
        for i, r in enumerate(spd_dots):
            _btn(screen, fmono_md, str(i + 1), r, mouse, active=(speed_idx == i))

        _section_label(screen, fmono_xs, "CONTROL SCHEME", rp_x, sch_y - 18)
        for i, (r, lbl) in enumerate(zip(sch_btns, ["WASD", "QA/WS"])):
            _btn(screen, fbody, lbl, r, mouse, active=(ctrl_scheme == i + 1))

        _section_label(screen, fmono_xs, "CAPTURE", rp_x, cap_y - 18)
        _btn(screen, fbody, "📷 PHOTO", btn_photo, mouse, hover_col=BLUE)
        _btn(screen, fbody,
             "⏹ STOP REC" if video_rec else "⏺ REC",
             btn_video, mouse,
             active=video_rec, hover_col=RED, danger=video_rec)

        # ── Bottom bar ────────────────────────────────────────
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
            ("FRM",    str(frame)),
        ]:
            ls = fmono_xs.render(lbl, True, DIM)
            vs = fmono_xs.render(val, True, SEC)
            screen.blit(ls, (sx, sb_y + (BOT_H - ls.get_height()) // 2))
            sx += ls.get_width() + 5
            screen.blit(vs, (sx, sb_y + (BOT_H - vs.get_height()) // 2))
            sx += vs.get_width() + 14
            pygame.draw.line(screen, BORDER, (sx - 6, sb_y + 6), (sx - 6, sb_y + BOT_H - 6))

        vers = fmono_xs.render("KIDA v2.1 · RASPBERRY PI", True, DIM)
        screen.blit(vers, (W - vers.get_width() - 12,
                           sb_y + (BOT_H - vers.get_height()) // 2))

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
        clock.tick(25)          # 25 fps target — easier on Pi CPU

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