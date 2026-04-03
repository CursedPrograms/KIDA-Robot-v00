import os
import time
import math
import queue
import socket
import threading
import subprocess
import datetime

import pygame
import numpy as np
import psutil
import qrcode
from PIL import Image
from picamera2 import Picamera2
from flask import Flask, render_template, jsonify, request

from music_player import MusicPlayer
from motor_control import MotorController
from obstacle_avoidance import ObstacleAvoidance
from led_control import SPI_WS2812_LEDStrip

# ══════════════════════════════════════════════════════════════
#  PALETTE
# ══════════════════════════════════════════════════════════════
BG      = (8,   9,  13)
PANEL   = (12,  13,  20)
BORDER  = (28,  30,  44)
ACCENT  = (255,  30, 100)
GREEN   = ( 29, 158, 117)
BLUE    = ( 55, 138, 221)
AMBER   = (255, 144,  32)
RED     = (226,  75,  74)
TEAL    = ( 20, 180, 160)
PRI     = (220, 220, 215)
SEC     = (120, 122, 115)
DIM     = ( 52,  54,  64)

# ══════════════════════════════════════════════════════════════
#  FLASK SERVER
# ══════════════════════════════════════════════════════════════
app           = Flask(__name__, static_folder='static', template_folder='templates')
command_queue = queue.Queue()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/status')
def status():
    return jsonify({'status': 'online', 'robot': 'KIDA'})

@app.route('/command', methods=['POST'])
def receive_command():
    cmd = request.get_json().get('command')
    command_queue.put(cmd)
    return jsonify({'received': cmd, 'status': 'queued'})

@app.route('/control/send/', methods=['POST'])
def control_send():
    cmd = request.get_json().get('command')
    command_queue.put(cmd)
    return jsonify({'received': cmd, 'status': 'executed'})

@app.route('/control/stats/', methods=['GET'])
def control_stats():
    with stats_lock:
        return jsonify({'stats': system_stats.copy()})

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

# ══════════════════════════════════════════════════════════════
#  SYSTEM STATS (background thread)
# ══════════════════════════════════════════════════════════════
system_stats = {}
stats_lock   = threading.Lock()

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "N/A"

def _stats_worker():
    global system_stats
    while True:
        try:
            cpu  = psutil.cpu_percent()
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                temp = int(f.read()) / 1000.0
            mem  = psutil.virtual_memory()
            dio  = psutil.disk_io_counters()
            try:
                ping = subprocess.check_output(
                    ["ping", "-c", "1", "8.8.8.8"], timeout=1).decode()
                lines = [l for l in ping.split("\n") if "time=" in l]
                lat = lines[0].split("time=")[1].split(" ")[0] + "ms" if lines else "N/A"
            except Exception:
                lat = "N/A"
            s = {
                "cpu":        cpu,
                "temp":       temp,
                "ram_used":   mem.used  // (1024 * 1024),
                "ram_total":  mem.total // (1024 * 1024),
                "ip":         get_local_ip(),
                "disk_read":  round(dio.read_bytes  / 1024 / 1024, 1),
                "disk_write": round(dio.write_bytes / 1024 / 1024, 1),
                "boot_time":  datetime.datetime.fromtimestamp(
                                  psutil.boot_time()).strftime("%H:%M %d/%m"),
                "latency":    lat,
                "threads":    threading.active_count(),
            }
        except Exception as e:
            s = {"error": str(e)}
        with stats_lock:
            system_stats = s
        time.sleep(1)

# ══════════════════════════════════════════════════════════════
#  QR CODE HELPER
# ══════════════════════════════════════════════════════════════
def make_qr_surface(url: str, size: int = 110) -> pygame.Surface:
    qr = qrcode.QRCode(version=1,
                       error_correction=qrcode.constants.ERROR_CORRECT_L,
                       box_size=10, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img = img.resize((size, size), Image.LANCZOS)
    return pygame.image.fromstring(img.tobytes(), img.size, "RGB")

# ══════════════════════════════════════════════════════════════
#  CAMERA FRAME → PYGAME SURFACE
# ══════════════════════════════════════════════════════════════
def cam_frame_to_surface(cam: Picamera2,
                          target_w: int, target_h: int) -> pygame.Surface:
    try:
        frame = cam.capture_array()
        if frame.shape[2] == 4:
            frame = frame[:, :, :3]
        pil = Image.fromarray(frame, "RGB")
        pil = pil.resize((target_w, target_h), Image.BILINEAR)
        return pygame.image.fromstring(pil.tobytes(), pil.size, "RGB")
    except Exception:
        s = pygame.Surface((target_w, target_h))
        s.fill((8, 10, 16))
        return s

# ══════════════════════════════════════════════════════════════
#  DRAW HELPERS
# ══════════════════════════════════════════════════════════════
def rect_panel(surf, r, radius=6, fill=PANEL, border=BORDER):
    pygame.draw.rect(surf, fill,   r, border_radius=radius)
    pygame.draw.rect(surf, border, r, width=1, border_radius=radius)

def hline(surf, y, x0, x1, color=BORDER):
    pygame.draw.line(surf, color, (x0, y), (x1, y))

def vline(surf, x, y0, y1, color=BORDER):
    pygame.draw.line(surf, color, (x, y0), (x, y1))

def txt(surf, font, text, pos, color=PRI, anchor="topleft"):
    s = font.render(str(text), True, color)
    r = s.get_rect(**{anchor: pos})
    surf.blit(s, r)
    return r

def draw_bar(surf, r, pct, color, track=(22, 24, 36)):
    pygame.draw.rect(surf, track, r, border_radius=2)
    fw = max(int(r.width * min(pct, 1.0)), 0)
    if fw:
        pygame.draw.rect(surf, color,
                         pygame.Rect(r.x, r.y, fw, r.height),
                         border_radius=2)

def draw_led_dot(surf, pos, color, r=5):
    pygame.draw.circle(surf, color, pos, r)
    if any(c > 10 for c in color):
        g = pygame.Surface((r * 4, r * 4), pygame.SRCALPHA)
        pygame.draw.circle(g, (*color, 55), (r * 2, r * 2), r * 2)
        surf.blit(g, (pos[0] - r * 2, pos[1] - r * 2))

def draw_waveform(surf, frame, r, bars=60, playing=False):
    bw = r.width // bars
    for i in range(bars):
        if playing:
            h = int((math.sin(frame * 0.14 + i * 0.32) * 0.5 + 0.5)
                    * r.height * 0.88 + 2)
            a = 160
        else:
            h = 2
            a = 40
        x = r.x + i * bw
        y = r.y + r.height - h
        s = pygame.Surface((max(bw - 1, 1), h), pygame.SRCALPHA)
        s.fill((*ACCENT, a))
        surf.blit(s, (x, y))

def draw_grid(surf, w, h, step=40):
    gc = (18, 10, 16)
    for x in range(0, w + 1, step):
        pygame.draw.line(surf, gc, (x, 0), (x, h))
    for y in range(0, h + 1, step):
        pygame.draw.line(surf, gc, (0, y), (w, y))

def draw_btn(surf, font, label, r, mouse,
             active=False, danger=False,
             base=PANEL, hover_col=ACCENT):
    hov = r.collidepoint(mouse)
    if danger:
        bc = (22, 8, 8)
        bd = RED
        tc = RED
    elif hov or active:
        bc = (20, 9, 16)
        bd = hover_col
        tc = hover_col
    else:
        bc = base
        bd = BORDER
        tc = SEC
    pygame.draw.rect(surf, bc, r, border_radius=6)
    pygame.draw.rect(surf, bd, r, width=1, border_radius=6)
    if active:
        strip = pygame.Rect(r.x + 4, r.bottom - 2, r.width - 8, 2)
        pygame.draw.rect(surf, hover_col if not danger else RED,
                         strip, border_radius=1)
    s = font.render(label, True, tc)
    surf.blit(s, (r.x + (r.width  - s.get_width())  // 2,
                  r.y + (r.height - s.get_height()) // 2))

# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════
def main():
    pygame.init()

    # ── Fullscreen at native resolution ───────────────────────
    info  = pygame.display.Info()
    W, H  = info.current_w, info.current_h
    screen = pygame.display.set_mode(
        (W, H), pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF)
    pygame.display.set_caption("KIDA")
    pygame.mouse.set_visible(False)
    clock = pygame.time.Clock()

    # ── Layout ────────────────────────────────────────────────
    TOP_H   = 48
    BOT_H   = 56
    STAT_H  = 22
    WAVE_H  = BOT_H - STAT_H
    L_W     = 230
    R_W     = 260
    CAM_X   = L_W
    CAM_Y   = TOP_H
    CAM_W   = W - L_W - R_W
    CAM_H   = H - TOP_H - BOT_H
    LP_X    = 8
    LP_W    = L_W - 16
    RP_X    = W - R_W + 12
    RP_W    = R_W - 24

    # ── Fonts ─────────────────────────────────────────────────
    fmono_lg = pygame.font.SysFont("Courier New", 22, bold=True)
    fmono_md = pygame.font.SysFont("Courier New", 13, bold=True)
    fmono_sm = pygame.font.SysFont("Courier New", 11)
    fmono_xs = pygame.font.SysFont("Courier New", 10)
    fbody    = pygame.font.SysFont("Arial", 13)
    flabel   = pygame.font.SysFont("Arial", 11)
    fdpad    = pygame.font.SysFont("Arial", 20, bold=True)

    # ── Background threads ────────────────────────────────────
    threading.Thread(target=run_flask,     daemon=True).start()
    threading.Thread(target=_stats_worker, daemon=True).start()
    print("🌐 Flask: http://0.0.0.0:5000")

    # ── Hardware ──────────────────────────────────────────────
    music   = MusicPlayer("/home/nova/Desktop/kida/audio/music/")
    motors  = MotorController()
    avoider = ObstacleAvoidance(motors=motors)
    led     = SPI_WS2812_LEDStrip(8, 128)
    cam     = Picamera2()
    cam.start_preview()
    cam.start()

    if not led.check_spi_state():
        print("SPI init failed — exiting.")
        return

    # ── QR code ───────────────────────────────────────────────
    local_ip = get_local_ip()
    qr_surf  = make_qr_surface(f"http://{local_ip}:5000", size=110)

    # ── Directories ───────────────────────────────────────────
    photos_dir = "/home/nova/Desktop/kida/photos"
    videos_dir = "/home/nova/Desktop/kida/videos"
    os.makedirs(photos_dir, exist_ok=True)
    os.makedirs(videos_dir, exist_ok=True)

    # ── State ─────────────────────────────────────────────────
    MODE_USER, MODE_AUTO = 0, 1
    mode          = MODE_USER
    speed_levels  = [0.4, 0.6, 0.8, 1.0]
    speed_idx     = 0
    speed         = speed_levels[speed_idx]
    ctrl_scheme   = 1
    music_playing = False
    video_rec     = False
    video_fname   = None
    frame         = 0
    direction     = "STOPPED"
    led_color     = (0, 0, 0)
    cam_surf      = pygame.Surface((CAM_W, CAM_H))
    cam_surf.fill((8, 10, 14))
    cam_tick      = 0

    # ── Button rects ──────────────────────────────────────────
    # Mode tabs
    tab_w  = 145
    tab_gap = 8
    tab_y  = (TOP_H - 30) // 2
    tabs   = [
        pygame.Rect(L_W + 8 + i * (tab_w + tab_gap), tab_y, tab_w, 30)
        for i in range(2)
    ]
    TAB_LABELS = ["🕹  USER CONTROL", "🤖  AUTONOMOUS"]

    # D-pad
    DP_Y  = TOP_H + 24
    DP_S  = 52
    DP_G  = 6
    DP_CX = RP_X + RP_W // 2 - DP_S // 2
    dpad  = {
        "forward":  pygame.Rect(DP_CX,                DP_Y,                     DP_S, DP_S),
        "left":     pygame.Rect(DP_CX - DP_S - DP_G,  DP_Y + DP_S + DP_G,      DP_S, DP_S),
        "stop":     pygame.Rect(DP_CX,                DP_Y + DP_S + DP_G,       DP_S, DP_S),
        "right":    pygame.Rect(DP_CX + DP_S + DP_G,  DP_Y + DP_S + DP_G,      DP_S, DP_S),
        "backward": pygame.Rect(DP_CX,                DP_Y + (DP_S + DP_G) * 2, DP_S, DP_S),
    }
    DPAD_GLYPHS = {
        "forward": "▲", "left": "◀", "stop": "■",
        "right": "▶",  "backward": "▼"
    }

    # Speed dots
    spd_y    = DP_Y + (DP_S + DP_G) * 3 + 22
    spd_w    = (RP_W - DP_G * 3) // 4
    spd_dots = [
        pygame.Rect(RP_X + i * (spd_w + DP_G), spd_y, spd_w, 32)
        for i in range(4)
    ]

    # Scheme
    sch_y   = spd_y + 48
    sch_w   = (RP_W - DP_G) // 2
    sch_btns = [
        pygame.Rect(RP_X,              sch_y, sch_w, 30),
        pygame.Rect(RP_X + sch_w + DP_G, sch_y, sch_w, 30),
    ]

    # Capture
    pv_y    = sch_y + 48
    pv_w    = (RP_W - DP_G) // 2
    btn_photo = pygame.Rect(RP_X,             pv_y, pv_w, 34)
    btn_video = pygame.Rect(RP_X + pv_w + DP_G, pv_y, pv_w, 34)

    # Music controls (left panel)
    mus_base  = TOP_H + 130
    btn_play  = pygame.Rect(LP_X,                      mus_base + 38, (LP_W - 6) // 2, 30)
    btn_skip  = pygame.Rect(LP_X + (LP_W - 6) // 2 + 6, mus_base + 38, (LP_W - 6) // 2, 30)

    # ── Helpers ───────────────────────────────────────────────
    def take_photo():
        fname = os.path.join(photos_dir, f"photo_{int(time.time())}.jpg")
        cam.capture_file(fname)
        print(f"📸 {fname}")

    def toggle_video():
        nonlocal video_rec, video_fname
        if not video_rec:
            video_fname = os.path.join(videos_dir, f"video_{int(time.time())}.h264")
            cam.start_recording(video_fname)
            video_rec = True
        else:
            cam.stop_recording()
            video_rec = False
            video_fname = None

    def set_led(color):
        nonlocal led_color
        led_color = color
        led.set_all_led_color(*color)

    # ── Main loop ─────────────────────────────────────────────
    running = True
    while running:
        mouse = pygame.mouse.get_pos()

        with stats_lock:
            st = system_stats.copy()

        cpu_pct  = min(st.get("cpu",   0) / 100.0, 1.0)
        temp_c   = st.get("temp",   0)
        temp_pct = min(temp_c / 85.0, 1.0)
        ram_u    = st.get("ram_used",   0)
        ram_t    = st.get("ram_total",  1)
        ram_pct  = min(ram_u / max(ram_t, 1), 1.0)
        latency  = st.get("latency",    "N/A")
        n_thr    = st.get("threads",    0)
        disk_r   = st.get("disk_read",  0)
        disk_w   = st.get("disk_write", 0)
        boot_t   = st.get("boot_time",  "--:--")

        # Camera: capture every 2nd frame for performance
        cam_tick += 1
        if cam_tick >= 2:
            cam_tick = 0
            cam_surf = cam_frame_to_surface(cam, CAM_W, CAM_H)

        # ════════════════════════════════════════════════════
        #  RENDER
        # ════════════════════════════════════════════════════
        screen.fill(BG)
        draw_grid(screen, W, H)

        # ── Live camera feed fills the center ────────────────
        screen.blit(cam_surf, (CAM_X, CAM_Y))

        # Soft dark vignette on left/right camera edges
        # so it blends into the sidebars
        vw = 32
        for i in range(vw):
            a = int(200 * (1 - i / vw))
            s = pygame.Surface((1, CAM_H), pygame.SRCALPHA)
            s.fill((0, 0, 0, a))
            screen.blit(s, (CAM_X + i,           CAM_Y))
            screen.blit(s, (CAM_X + CAM_W - 1 - i, CAM_Y))

        # HUD corner brackets on camera feed
        blen = 24
        bthk = 2
        for (cx, cy, sx, sy) in [
            (CAM_X + 6,           CAM_Y + 6,            1,  1),
            (CAM_X + CAM_W - 6,   CAM_Y + 6,           -1,  1),
            (CAM_X + 6,           CAM_Y + CAM_H - 6,    1, -1),
            (CAM_X + CAM_W - 6,   CAM_Y + CAM_H - 6,   -1, -1),
        ]:
            pygame.draw.line(screen, ACCENT,
                             (cx, cy), (cx + sx * blen, cy), bthk)
            pygame.draw.line(screen, ACCENT,
                             (cx, cy), (cx, cy + sy * blen), bthk)

        # REC indicator
        if video_rec and (frame // 15) % 2 == 0:
            pygame.draw.circle(screen, RED,
                               (CAM_X + CAM_W - 22, CAM_Y + 14), 5)
            txt(screen, fmono_xs, "REC",
                (CAM_X + CAM_W - 14, CAM_Y + 9), RED)

        # Autonomous mode overlay
        if mode == MODE_AUTO:
            msg = "— AUTONOMOUS OBSTACLE AVOIDANCE —"
            ms  = fmono_sm.render(msg, True, TEAL)
            mx  = CAM_X + (CAM_W - ms.get_width()) // 2
            my  = CAM_Y + CAM_H - 28
            ov  = pygame.Surface((ms.get_width() + 20, ms.get_height() + 10),
                                 pygame.SRCALPHA)
            ov.fill((0, 0, 0, 130))
            screen.blit(ov, (mx - 10, my - 4))
            screen.blit(ms, (mx, my))

        # ── Structural dividers ───────────────────────────────
        hline(screen, TOP_H,       0, W)
        hline(screen, H - BOT_H,   0, W)
        hline(screen, H - STAT_H,  0, W)
        vline(screen, L_W,         TOP_H, H - BOT_H)
        vline(screen, W - R_W,     TOP_H, H - BOT_H)

        # ════════════════════════════════════════════════════
        #  TOP BAR
        # ════════════════════════════════════════════════════
        logo = fmono_lg.render("KIDA", True, ACCENT)
        screen.blit(logo, (12, (TOP_H - logo.get_height()) // 2))

        for i, (tr, tl) in enumerate(zip(tabs, TAB_LABELS)):
            draw_btn(screen, fbody, tl, tr, mouse,
                     active=(mode == i), hover_col=ACCENT)

        # Top-right stat chips
        chip_x = W - 14
        for lbl, val in [
            ("THR",  str(n_thr)),
            ("TEMP", f"{temp_c:.0f}C"),
            ("CPU",  f"{st.get('cpu', 0):.0f}%"),
        ]:
            vs = fmono_sm.render(val, True, AMBER if lbl == "TEMP" and temp_c > 65 else PRI)
            ls = fmono_xs.render(lbl, True, DIM)
            chip_x -= vs.get_width() + 4
            screen.blit(vs, (chip_x, (TOP_H - vs.get_height()) // 2))
            chip_x -= ls.get_width() + 10
            screen.blit(ls, (chip_x, (TOP_H - ls.get_height()) // 2))
            chip_x -= 12

        # LED strip preview
        for i in range(8):
            dc = led_color if any(c > 10 for c in led_color) else (24, 26, 38)
            draw_led_dot(screen, (chip_x - 14 - i * 14, TOP_H // 2), dc, r=4)

        # ════════════════════════════════════════════════════
        #  LEFT PANEL
        # ════════════════════════════════════════════════════
        lp_y = TOP_H + 10

        # QR
        screen.blit(qr_surf, (LP_X, lp_y))
        txt(screen, fmono_xs, f"{local_ip}:5000",
            (LP_X + LP_W // 2, lp_y + 114), AMBER, anchor="midtop")
        lp_y += 132

        # System stats
        txt(screen, fmono_xs, "SYSTEM", (LP_X, lp_y), DIM)
        lp_y += 13
        for label, val, pct, bc in [
            ("CPU",  f"{st.get('cpu', 0):.0f}%", cpu_pct,  ACCENT),
            ("TEMP", f"{temp_c:.0f}C",             temp_pct, AMBER),
            ("RAM",  f"{ram_u}/{ram_t}M",           ram_pct,  BLUE),
        ]:
            txt(screen, flabel,   label, (LP_X, lp_y), DIM)
            txt(screen, fmono_xs, val,   (LP_X + LP_W, lp_y + 1), SEC, anchor="topright")
            draw_bar(screen, pygame.Rect(LP_X, lp_y + 12, LP_W, 3), pct, bc)
            lp_y += 22

        # Network stats
        lp_y += 4
        txt(screen, fmono_xs, "NETWORK", (LP_X, lp_y), DIM)
        lp_y += 13
        for label, val in [
            ("LATENCY", latency),
            ("THREADS", str(n_thr)),
            ("DISK R",  f"{disk_r}MB"),
            ("DISK W",  f"{disk_w}MB"),
            ("BOOT",    boot_t),
        ]:
            txt(screen, flabel,   label, (LP_X, lp_y), DIM)
            txt(screen, fmono_xs, str(val), (LP_X + LP_W, lp_y + 1), SEC, anchor="topright")
            pygame.draw.line(screen, (20, 22, 32),
                             (LP_X, lp_y + 13), (LP_X + LP_W, lp_y + 13))
            lp_y += 16

        # Music section
        lp_y += 8
        txt(screen, fmono_xs, "MUSIC", (LP_X, lp_y), DIM)
        lp_y += 13

        # Track name
        track = "No track"
        try:
            ct = music.current_track
            track = (ct() if callable(ct) else ct) or "No track"
        except Exception:
            pass
        tn = fbody.render(str(track)[:26], True, PRI if music_playing else SEC)
        screen.blit(tn, (LP_X, lp_y))
        lp_y += 18

        # Waveform
        draw_waveform(screen, frame,
                      pygame.Rect(LP_X, lp_y, LP_W, 26),
                      bars=26, playing=music_playing)
        lp_y += 30

        # Music buttons (anchored from mus_base so they don't drift)
        btn_play = pygame.Rect(LP_X,                        mus_base + 38,
                               (LP_W - 6) // 2, 30)
        btn_skip = pygame.Rect(LP_X + (LP_W - 6) // 2 + 6,  mus_base + 38,
                               (LP_W - 6) // 2, 30)
        draw_btn(screen, flabel,
                 "PAUSE" if music_playing else "PLAY",
                 btn_play, mouse, active=music_playing)
        draw_btn(screen, flabel, "SKIP", btn_skip, mouse)

        # ════════════════════════════════════════════════════
        #  RIGHT PANEL
        # ════════════════════════════════════════════════════
        txt(screen, fmono_xs, "DIRECTIONAL CONTROL",
            (RP_X, TOP_H + 10), DIM)

        # D-pad
        for cmd, r in dpad.items():
            is_stop = cmd == "stop"
            draw_btn(screen,
                     fmono_sm if is_stop else fdpad,
                     DPAD_GLYPHS[cmd], r, mouse,
                     base=(22, 8, 14) if is_stop else PANEL,
                     hover_col=ACCENT)
            # Highlight active direction
            if cmd != "stop" and direction.lower() == cmd:
                pygame.draw.rect(screen, ACCENT, r, width=2, border_radius=6)

        # Speed
        txt(screen, fmono_xs, "SPEED LEVEL",
            (RP_X, spd_y - 14), DIM)
        for i, r in enumerate(spd_dots):
            draw_btn(screen, fmono_md, str(i + 1),
                     r, mouse, active=(speed_idx == i))

        # Scheme
        txt(screen, fmono_xs, "CONTROL SCHEME",
            (RP_X, sch_y - 14), DIM)
        for i, (r, lbl) in enumerate(zip(sch_btns, ["WASD", "QA/WS"])):
            draw_btn(screen, flabel, lbl, r, mouse,
                     active=(ctrl_scheme == i + 1))

        # Capture
        txt(screen, fmono_xs, "CAPTURE",
            (RP_X, pv_y - 14), DIM)
        draw_btn(screen, flabel, "PHOTO", btn_photo, mouse, hover_col=BLUE)
        draw_btn(screen, flabel,
                 "STOP REC" if video_rec else "REC",
                 btn_video, mouse,
                 active=video_rec,
                 base=(20, 6, 6) if video_rec else PANEL,
                 hover_col=RED, danger=video_rec)

        # Motor readout at bottom of right panel
        mrd_y = H - BOT_H - 76
        for label, val in [
            ("DIR",    direction),
            ("SPEED",  f"{speed:.1f}"),
            ("SCHEME", "WASD" if ctrl_scheme == 1 else "QA/WS"),
            ("LED",    f"R{led_color[0]} G{led_color[1]} B{led_color[2]}"),
        ]:
            txt(screen, flabel,   label, (RP_X, mrd_y), DIM)
            txt(screen, fmono_xs, str(val), (RP_X + RP_W, mrd_y), SEC, anchor="topright")
            pygame.draw.line(screen, (18, 20, 30),
                             (RP_X, mrd_y + 15), (RP_X + RP_W, mrd_y + 15))
            mrd_y += 18

        # ════════════════════════════════════════════════════
        #  BOTTOM — WAVEFORM + STATUS BAR
        # ════════════════════════════════════════════════════
        draw_waveform(screen, frame,
                      pygame.Rect(0, H - BOT_H, W, WAVE_H),
                      bars=96, playing=music_playing)

        sb_y = H - STAT_H
        screen.fill((10, 11, 16), pygame.Rect(0, sb_y, W, STAT_H))
        hline(screen, sb_y, 0, W)

        # Online ping dot
        pygame.draw.circle(screen, GREEN, (14, sb_y + STAT_H // 2), 4)

        sx = 28
        for lbl, val in [
            ("FLASK",  ":5000"),
            ("MODE",   ["USER CTRL", "AUTONOMOUS"][mode]),
            ("SCHEME", "WASD" if ctrl_scheme == 1 else "QA/WS"),
            ("SPEED",  f"{speed:.1f}"),
            ("FRM",    str(frame)),
            ("CAM",    "LIVE"),
        ]:
            ls = fmono_xs.render(lbl, True, DIM)
            vs = fmono_xs.render(val,  True, SEC)
            screen.blit(ls, (sx, sb_y + (STAT_H - ls.get_height()) // 2))
            sx += ls.get_width() + 4
            screen.blit(vs, (sx, sb_y + (STAT_H - vs.get_height()) // 2))
            sx += vs.get_width() + 14
            pygame.draw.line(screen, BORDER,
                             (sx - 6, sb_y + 4), (sx - 6, sb_y + STAT_H - 4))

        vers = fmono_xs.render("KIDA v1.0 · RASPBERRY PI", True, DIM)
        screen.blit(vers, (W - vers.get_width() - 12,
                           sb_y + (STAT_H - vers.get_height()) // 2))

        # ════════════════════════════════════════════════════
        #  EVENTS
        # ════════════════════════════════════════════════════
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == getattr(music, 'SONG_END', -1):
                music.handle_event(event)
                music_playing = music.playing

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_TAB:
                    mode = 1 - mode
                elif event.key == pygame.K_m:
                    music.play_next(); music_playing = True
                elif event.key == pygame.K_SPACE:
                    music.stop();      music_playing = False
                elif mode == MODE_USER:
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
                # Mode tabs
                for i, tr in enumerate(tabs):
                    if tr.collidepoint(event.pos):
                        mode = i

                # D-pad
                if mode == MODE_USER:
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

        # ════════════════════════════════════════════════════
        #  FLASK COMMAND QUEUE
        # ════════════════════════════════════════════════════
        while not command_queue.empty():
            cmd = command_queue.get()
            if cmd in ("up", "forward"):
                motors.forward(speed);    set_led((0, 255, 0));  direction = "FORWARD"
            elif cmd in ("down", "backward"):
                motors.backward(speed);   set_led((255, 0, 0));  direction = "BACKWARD"
            elif cmd == "left":
                motors.turn_left(speed);  set_led((0, 0, 255));  direction = "LEFT"
            elif cmd == "right":
                motors.turn_right(speed); set_led((255, 255, 0)); direction = "RIGHT"
            elif cmd == "stop":
                motors.stop();            set_led((0, 0, 0));    direction = "STOPPED"
            elif cmd == "photo":
                take_photo()
            elif cmd == "video":
                toggle_video()
            elif cmd in ("music", "play_music", "start_music"):
                if not music_playing:
                    music.play_next(); music_playing = True
            elif cmd in ("stop_music", "pause_music", "music_stop"):
                music.stop(); music_playing = False
            elif cmd in ("skip", "skip_music", "next_music"):
                music.play_next()
            elif cmd == "speed":
                speed_idx = (speed_idx + 1) % len(speed_levels)
                speed = speed_levels[speed_idx]
            elif cmd == "mode":
                ctrl_scheme = 2 if ctrl_scheme == 1 else 1

        # ════════════════════════════════════════════════════
        #  DRIVE LOGIC
        # ════════════════════════════════════════════════════
        if mode == MODE_AUTO:
            if avoider.check_and_avoid():
                set_led((255, 0, 0))
                led.show()
                pygame.display.flip()
                frame += 1
                clock.tick(30)
                continue

        elif mode == MODE_USER:
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
                left, right = motors.control_mode_2(keys, speed)
                if left and right:   set_led((0, 255, 255))
                elif left:           set_led((255, 0, 255))
                elif right:          set_led((255, 165, 0))
                else:                set_led((0, 0, 0))

        if music_playing:
            led.rhythm_wave(frame)

        led.show()
        frame += 1
        pygame.display.flip()
        clock.tick(30)

    # ── Cleanup ───────────────────────────────────────────────
    led.led_close()
    cam.stop_preview()
    cam.stop()
    avoider.cleanup()
    pygame.mouse.set_visible(True)
    pygame.quit()


if __name__ == "__main__":
    main()