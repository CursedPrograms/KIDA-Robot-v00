import os
import time
import pygame
import numpy
import psutil
import socket
import queue
import threading
import qrcode
from PIL import Image
import subprocess
import datetime
import math

from music_player import MusicPlayer
from motor_control import MotorController
from obstacle_avoidance import ObstacleAvoidance
from led_control import SPI_WS2812_LEDStrip
from picamera2 import Picamera2

from flask import Flask, render_template, jsonify, request

# ─────────────────────────────────────────────
#  PALETTE
# ─────────────────────────────────────────────
BG          = (10,  11,  15)
PANEL_BG    = (13,  14,  24)
BORDER      = (30,  33,  48)
ACCENT      = (255, 30,  100)   # hot pink
ACCENT_DIM  = (180, 20,  70)
GREEN       = (29,  158, 117)
BLUE        = (55,  138, 221)
AMBER       = (255, 144, 32)
RED         = (226, 75,  74)
TEXT_PRI    = (226, 226, 221)
TEXT_SEC    = (130, 130, 120)
TEXT_DIM    = (60,  62,  72)

# ─────────────────────────────────────────────
#  FLASK
# ─────────────────────────────────────────────
app = Flask(__name__, static_folder='static', template_folder='templates')
command_queue = queue.Queue()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/status')
def status():
    return jsonify({'status': 'online', 'robot': 'KIDA', 'message': 'All systems go!'})

@app.route('/command', methods=['POST'])
def receive_command():
    data = request.get_json()
    command = data.get('command')
    print(f"📡 Received command: {command}")
    command_queue.put(command)
    return jsonify({'received': command, 'status': 'queued'})

@app.route('/control/send/', methods=['POST'])
def control_send():
    data = request.get_json()
    command = data.get('command')
    print(f"📡 Received command (control/send): {command}")
    command_queue.put(command)
    return jsonify({'received': command, 'status': 'executed'})

@app.route('/control/stats/', methods=['GET'])
def control_stats():
    with stats_lock:
        stats_copy = system_stats.copy()
    return jsonify({'stats': stats_copy})

def run_flask_server():
    app.run(host='0.0.0.0', port=5000, debug=False)

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "N/A"

def get_system_stats():
    try:
        cpu_usage = psutil.cpu_percent()
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            cpu_temp = int(f.read()) / 1000.0
        mem = psutil.virtual_memory()
        ram_used  = mem.used  // (1024 * 1024)
        ram_total = mem.total // (1024 * 1024)
        ip_address = get_local_ip()
        disk_io    = psutil.disk_io_counters()
        boot_time  = datetime.datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M")
        threads    = threading.active_count()
        try:
            ping = subprocess.check_output(["ping", "-c", "1", "8.8.8.8"], timeout=1).decode()
            latency_line = [line for line in ping.split("\n") if "time=" in line]
            latency = latency_line[0].split("time=")[1].split(" ")[0] + "ms" if latency_line else "N/A"
        except:
            latency = "N/A"
        return {
            "cpu": cpu_usage, "temp": cpu_temp,
            "ram_used": ram_used, "ram_total": ram_total,
            "ip": ip_address,
            "disk_read_mb":  round(disk_io.read_bytes  / 1024 / 1024, 1),
            "disk_write_mb": round(disk_io.write_bytes / 1024 / 1024, 1),
            "boot_time": boot_time, "latency": latency, "threads": threads,
        }
    except Exception as e:
        return {"error": str(e)}

system_stats = {}
stats_lock   = threading.Lock()

def stats_updater():
    global system_stats
    while True:
        new_stats = get_system_stats()
        with stats_lock:
            system_stats = new_stats
        time.sleep(1)

# ─────────────────────────────────────────────
#  QR CODE → PYGAME SURFACE
# ─────────────────────────────────────────────
def qr_to_pygame_surface(data, size=100):
    qr = qrcode.QRCode(version=1,
                       error_correction=qrcode.constants.ERROR_CORRECT_L,
                       box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img = img.resize((size, size), Image.LANCZOS)
    return pygame.image.fromstring(img.tobytes(), img.size, "RGB")

# ─────────────────────────────────────────────
#  DRAW HELPERS
# ─────────────────────────────────────────────
def draw_panel(surf, rect, radius=6, color=PANEL_BG, border=BORDER):
    """Filled rounded rect with 0.5px-style thin border."""
    pygame.draw.rect(surf, color,  rect, border_radius=radius)
    pygame.draw.rect(surf, border, rect, width=1, border_radius=radius)

def draw_label(surf, font, text, pos, color=TEXT_DIM):
    s = font.render(text, True, color)
    surf.blit(s, pos)

def draw_hline(surf, y, x1=0, x2=960, color=BORDER):
    pygame.draw.line(surf, color, (x1, y), (x2, y))

def draw_vline(surf, x, y1=0, y2=640, color=BORDER):
    pygame.draw.line(surf, x, (x, y1), (x, y2), 1)


def draw_grid(surf):
    """Faint pink grid background."""
    grid_color = (22, 12, 20)
    for x in range(0, 961, 40):
        pygame.draw.line(surf, grid_color, (x, 0), (x, 640))
    for y in range(0, 641, 40):
        pygame.draw.line(surf, grid_color, (0, y), (960, y))


def draw_bar(surf, rect, pct, color):
    """Thin horizontal progress bar."""
    pygame.draw.rect(surf, (25, 27, 38), rect, border_radius=2)
    filled = pygame.Rect(rect.x, rect.y, int(rect.width * pct), rect.height)
    if filled.width > 0:
        pygame.draw.rect(surf, color, filled, border_radius=2)


def draw_led(surf, pos, color, radius=5):
    """LED dot with inner glow."""
    pygame.draw.circle(surf, color, pos, radius)
    glow = (*color[:3], 60)
    glow_surf = pygame.Surface((radius*4, radius*4), pygame.SRCALPHA)
    pygame.draw.circle(glow_surf, glow, (radius*2, radius*2), radius*2)
    surf.blit(glow_surf, (pos[0]-radius*2, pos[1]-radius*2))


def draw_waveform(surf, frame, rect, bars=64, playing=False):
    bar_w = rect.width // bars
    for i in range(bars):
        if playing:
            h = int((math.sin(frame * 0.15 + i * 0.35) * 0.5 + 0.5) * rect.height * 0.85 + 3)
            alpha = 180
        else:
            h = 3
            alpha = 60
        x = rect.x + i * bar_w
        y = rect.y + rect.height - h
        color = (*ACCENT, alpha)
        s = pygame.Surface((max(bar_w-1, 1), h), pygame.SRCALPHA)
        s.fill(color)
        surf.blit(s, (x, y))


def draw_button(surf, font, text, rect, mouse, active=False,
                base_col=PANEL_BG, border_col=BORDER,
                text_col=TEXT_SEC, hover_col=ACCENT):
    hovered = rect.collidepoint(mouse)
    bg  = base_col if not (hovered or active) else (18, 8, 16)
    bdr = hover_col if (hovered or active) else border_col
    txt = hover_col if (hovered or active) else text_col
    pygame.draw.rect(surf, bg,  rect, border_radius=6)
    pygame.draw.rect(surf, bdr, rect, width=1, border_radius=6)
    # accent bottom strip when active
    if active:
        strip = pygame.Rect(rect.x+4, rect.bottom-2, rect.width-8, 2)
        pygame.draw.rect(surf, hover_col, strip, border_radius=1)
    label = font.render(text, True, txt)
    lx = rect.x + (rect.width  - label.get_width())  // 2
    ly = rect.y + (rect.height - label.get_height()) // 2
    surf.blit(label, (lx, ly))


def draw_mono(surf, font, text, pos, color=TEXT_PRI):
    s = font.render(text, True, color)
    surf.blit(s, pos)


# ─────────────────────────────────────────────
#  LAYOUT CONSTANTS
# ─────────────────────────────────────────────
LEFT_W   = 200
RIGHT_W  = 240
TOP_H    = 48
WAVE_H   = 70
STATUS_H = 28
MID_Y    = TOP_H
MID_H    = 640 - TOP_H - WAVE_H - STATUS_H
MID_X    = LEFT_W
MID_W    = 960 - LEFT_W - RIGHT_W


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
def main():
    pygame.init()
    screen = pygame.display.set_mode((960, 640))
    pygame.display.set_caption("KIDA Controller")
    clock = pygame.time.Clock()

    # Fonts
    font_mono  = pygame.font.SysFont("Courier New", 11)
    font_mono_sm = pygame.font.SysFont("Courier New", 10)
    font_label = pygame.font.SysFont("Arial", 10)
    font_body  = pygame.font.SysFont("Arial", 13)
    font_title = pygame.font.SysFont("Arial", 15, bold=True)
    font_logo  = pygame.font.SysFont("Courier New", 22, bold=True)

    # Threads
    flask_thread = threading.Thread(target=run_flask_server)
    flask_thread.daemon = True
    flask_thread.start()
    print("🌐 Flask server started on http://0.0.0.0:5000")

    stats_thread = threading.Thread(target=stats_updater, daemon=True)
    stats_thread.start()

    # Devices
    music         = MusicPlayer("/home/nova/Desktop/kida/audio/music/")
    motors        = MotorController()
    obstacle_avoid = ObstacleAvoidance(motors=motors)
    led           = SPI_WS2812_LEDStrip(8, 128)
    cam           = Picamera2()
    cam.start_preview()
    cam.start()

    if not led.check_spi_state():
        print("SPI init failed. Exiting.")
        return

    # QR code surface
    local_ip  = get_local_ip()
    qr_url    = f"http://{local_ip}:5000"
    qr_surf   = qr_to_pygame_surface(qr_url, size=100)

    # ── State ──────────────────────────────────
    MODE_USER = 0
    MODE_AUTO = 1
    MODE_CAM  = 2
    MODE_LABELS = ["USER CONTROL", "AUTONOMOUS", "CAM AVOIDANCE"]

    mode          = MODE_USER
    speed_levels  = [0.4, 0.6, 0.8, 1.0]
    speed_idx     = 0
    speed         = speed_levels[speed_idx]
    control_mode  = 1
    music_playing = False
    video_recording = False
    video_file_name = None
    frame         = 0
    direction     = "STOPPED"
    led_color     = (0, 0, 0)

    photos_dir = "/home/nova/Desktop/kida/photos"
    videos_dir = "/home/nova/Desktop/kida/videos"
    os.makedirs(photos_dir, exist_ok=True)
    os.makedirs(videos_dir, exist_ok=True)

    # ── Button rects ───────────────────────────
    # Mode tabs (top of center panel)
    TAB_Y  = MID_Y + 10
    TAB_H  = 34
    tab_w  = (MID_W - 30) // 3
    tabs   = [
        pygame.Rect(MID_X + 10 + i * (tab_w + 5), TAB_Y, tab_w, TAB_H)
        for i in range(3)
    ]

    # D-pad (center left)
    DP_X, DP_Y = MID_X + 20, MID_Y + 65
    DP_S = 44
    DP_G = 5
    dpad = {
        "forward":  pygame.Rect(DP_X + DP_S + DP_G, DP_Y,                   DP_S, DP_S),
        "left":     pygame.Rect(DP_X,                DP_Y + DP_S + DP_G,    DP_S, DP_S),
        "stop":     pygame.Rect(DP_X + DP_S + DP_G,  DP_Y + DP_S + DP_G,   DP_S, DP_S),
        "right":    pygame.Rect(DP_X + (DP_S+DP_G)*2,DP_Y + DP_S + DP_G,   DP_S, DP_S),
        "backward": pygame.Rect(DP_X + DP_S + DP_G,  DP_Y + (DP_S+DP_G)*2, DP_S, DP_S),
    }
    DPAD_ARROWS = {"forward": "↑", "left": "←", "stop": "■",
                   "right": "→", "backward": "↓"}

    # Speed dots
    SPD_Y  = MID_Y + 68
    spd_dots = [
        pygame.Rect(MID_X + 165 + i * 36, SPD_Y, 30, 30)
        for i in range(4)
    ]
    SCH_Y  = MID_Y + 108
    sch_dots = [
        pygame.Rect(MID_X + 165, SCH_Y, 50, 28),
        pygame.Rect(MID_X + 220, SCH_Y, 60, 28),
    ]

    # Camera feed placeholder rect
    CAM_RECT = pygame.Rect(MID_X + 308, MID_Y + 60, 196, 148)

    # Photo / Video
    btn_photo = pygame.Rect(CAM_RECT.x,            CAM_RECT.bottom + 6, 94, 30)
    btn_video = pygame.Rect(CAM_RECT.x + 100,       CAM_RECT.bottom + 6, 96, 30)

    # Music controls (right panel)
    RP_X = 960 - RIGHT_W + 10
    RP_W = RIGHT_W - 20
    btn_play = pygame.Rect(RP_X,            TOP_H + 90, (RP_W - 6) // 2, 28)
    btn_skip = pygame.Rect(RP_X + (RP_W - 6) // 2 + 6, TOP_H + 90, (RP_W - 6) // 2, 28)

    # Quick actions (right panel bottom)
    QA_Y  = TOP_H + MID_H - 80
    qa_w  = (RP_W - 6) // 2
    btn_snap  = pygame.Rect(RP_X,            QA_Y,      qa_w, 28)
    btn_vrec  = pygame.Rect(RP_X + qa_w + 6, QA_Y,      qa_w, 28)
    btn_led_g = pygame.Rect(RP_X,            QA_Y + 34, qa_w, 28)
    btn_led_x = pygame.Rect(RP_X + qa_w + 6, QA_Y + 34, qa_w, 28)

    # Back (TAB area)
    btn_back = pygame.Rect(10, 10, 80, 26)

    # ── Photo / Video helpers ──────────────────
    def take_photo():
        fname = os.path.join(photos_dir, f"photo_{int(time.time())}.jpg")
        cam.capture_file(fname)
        print(f"📸 Photo saved: {fname}")

    def toggle_video_recording():
        nonlocal video_recording, video_file_name
        if not video_recording:
            video_file_name = os.path.join(videos_dir, f"video_{int(time.time())}.h264")
            cam.start_recording(video_file_name)
            video_recording = True
            print(f"🎥 Recording: {video_file_name}")
        else:
            cam.stop_recording()
            video_recording = False
            print(f"🛑 Stopped recording: {video_file_name}")
            video_file_name = None

    # ── Main loop ──────────────────────────────
    running = True
    while running:
        mouse = pygame.mouse.get_pos()

        # ── Stats ──────────────────────────────
        with stats_lock:
            stats = system_stats.copy()

        cpu_pct  = min(stats.get("cpu",  0) / 100, 1.0)
        temp_c   = stats.get("temp", 0)
        temp_pct = min(temp_c / 85.0, 1.0)
        ram_used  = stats.get("ram_used",  0)
        ram_total = stats.get("ram_total", 1)
        ram_pct   = min(ram_used / max(ram_total, 1), 1.0)
        ip_addr  = stats.get("ip", "N/A")
        latency  = stats.get("latency", "N/A")
        threads  = stats.get("threads", 0)
        disk_r   = stats.get("disk_read_mb",  0)
        disk_w   = stats.get("disk_write_mb", 0)
        boot_t   = stats.get("boot_time", "—")

        # ═══════════════════════════════════════
        #  DRAW
        # ═══════════════════════════════════════
        screen.fill(BG)
        draw_grid(screen)

        # ── BORDER LINES ───────────────────────
        draw_hline(screen, TOP_H)
        draw_hline(screen, 640 - WAVE_H - STATUS_H)
        draw_hline(screen, 640 - STATUS_H)
        pygame.draw.line(screen, BORDER, (LEFT_W,  TOP_H), (LEFT_W,  640 - WAVE_H - STATUS_H))
        pygame.draw.line(screen, BORDER, (960 - RIGHT_W, TOP_H), (960 - RIGHT_W, 640 - WAVE_H - STATUS_H))

        # ══════════════════════════════════════
        #  TOP BAR
        # ══════════════════════════════════════
        logo_surf = font_logo.render("KIDA", True, ACCENT)
        screen.blit(logo_surf, (18, (TOP_H - logo_surf.get_height()) // 2))

        # Status pills
        pill_x = 80
        for pill_txt, pill_col in [("ONLINE", GREEN), (MODE_LABELS[mode], ACCENT)]:
            ps = font_mono_sm.render(pill_txt, True, pill_col)
            pr = pygame.Rect(pill_x, (TOP_H - 18) // 2, ps.get_width() + 16, 18)
            pygame.draw.rect(screen, (*pill_col, 30), pr, border_radius=9)
            pygame.draw.rect(screen, pill_col, pr, width=1, border_radius=9)
            screen.blit(ps, (pr.x + 8, pr.y + 3))
            pill_x += pr.width + 8

        # Top-right stat chips
        chip_x = 955
        for label, val in [
            ("THREADS", str(threads)),
            ("TEMP",    f"{temp_c:.0f}°C"),
            ("CPU",     f"{stats.get('cpu',0):.0f}%"),
        ]:
            vs = font_mono.render(val,   True, TEXT_PRI)
            ls = font_mono.render(label, True, TEXT_DIM)
            chip_x -= vs.get_width() + 6
            screen.blit(vs, (chip_x, (TOP_H - vs.get_height()) // 2))
            chip_x -= ls.get_width() + 12
            screen.blit(ls, (chip_x, (TOP_H - ls.get_height()) // 2))
            chip_x -= 6

        # LED dots top-right
        led_row_x = chip_x - 12
        led_colors_display = [led_color] * 8
        for i, lc in enumerate(led_colors_display):
            dot_col = lc if lc != (0,0,0) else (30, 32, 45)
            pos = (led_row_x - i * 14, TOP_H // 2)
            draw_led(screen, pos, dot_col, radius=4)

        # ══════════════════════════════════════
        #  LEFT PANEL
        # ══════════════════════════════════════
        LP_X = 10

        # QR code
        screen.blit(qr_surf, (LP_X, MID_Y + 8))

        qr_label = font_label.render(f"{local_ip}:5000", True, AMBER)
        screen.blit(qr_label, (LP_X, MID_Y + 114))

        # Section: SYSTEM
        sy = MID_Y + 136
        draw_mono(screen, font_mono_sm, "SYSTEM", (LP_X, sy), TEXT_DIM)
        sy += 14

        for label, val, pct, bar_col in [
            ("CPU",  f"{stats.get('cpu',0):.0f}%",        cpu_pct,  ACCENT),
            ("TEMP", f"{temp_c:.0f}°C",                    temp_pct, AMBER),
            ("RAM",  f"{ram_used}/{ram_total}MB",           ram_pct,  BLUE),
        ]:
            ls = font_label.render(label, True, TEXT_DIM)
            vs = font_mono_sm.render(val, True, TEXT_SEC)
            screen.blit(ls, (LP_X, sy))
            screen.blit(vs, (LEFT_W - 8 - vs.get_width(), sy))
            draw_bar(screen, pygame.Rect(LP_X, sy + 13, LEFT_W - 16, 3), pct, bar_col)
            sy += 24

        # Section: NETWORK
        draw_mono(screen, font_mono_sm, "NETWORK", (LP_X, sy), TEXT_DIM)
        sy += 14
        for label, val in [
            ("LATENCY", latency),
            ("THREADS", str(threads)),
            ("DISK R",  f"{disk_r}MB"),
            ("DISK W",  f"{disk_w}MB"),
            ("BOOT",    boot_t[-8:] if len(str(boot_t)) > 8 else str(boot_t)),
        ]:
            ls = font_label.render(label, True, TEXT_DIM)
            vs = font_mono_sm.render(val,   True, TEXT_SEC)
            screen.blit(ls, (LP_X, sy))
            screen.blit(vs, (LEFT_W - 8 - vs.get_width(), sy))
            pygame.draw.line(screen, (20, 22, 32),
                             (LP_X, sy + 12), (LEFT_W - 4, sy + 12))
            sy += 16

        # ══════════════════════════════════════
        #  CENTER – MODE TABS
        # ══════════════════════════════════════
        tab_labels = ["🕹  USER", "🤖  AUTO", "📷  CAM"]
        for i, (trect, tlbl) in enumerate(zip(tabs, tab_labels)):
            draw_button(screen, font_body, tlbl, trect, mouse,
                        active=(mode == i),
                        hover_col=ACCENT)

        # ── USER / shared controls ──────────────
        if mode == MODE_USER:
            # D-pad
            draw_mono(screen, font_mono_sm, "DIRECTIONAL CONTROL",
                      (DP_X, DP_Y - 14), TEXT_DIM)
            for cmd, r in dpad.items():
                is_stop = cmd == "stop"
                bc = (26, 8, 18) if is_stop else PANEL_BG
                tc = ACCENT if is_stop else TEXT_SEC
                hc = ACCENT
                draw_button(screen, font_title, DPAD_ARROWS[cmd], r, mouse,
                            base_col=bc, text_col=tc, hover_col=hc)

            # Speed
            draw_mono(screen, font_mono_sm, "SPEED", (MID_X + 165, SPD_Y - 14), TEXT_DIM)
            for i, r in enumerate(spd_dots):
                draw_button(screen, font_body, str(i+1), r, mouse,
                            active=(speed_idx == i), hover_col=ACCENT)

            # Scheme
            draw_mono(screen, font_mono_sm, "SCHEME", (MID_X + 165, SCH_Y - 14), TEXT_DIM)
            for i, (r, lbl) in enumerate(zip(sch_dots, ["WASD", "QA/WS"])):
                draw_button(screen, font_label, lbl, r, mouse,
                            active=(control_mode == i + 1), hover_col=ACCENT)

        elif mode == MODE_AUTO:
            msg = "AUTONOMOUS OBSTACLE AVOIDANCE ACTIVE"
            ms = font_body.render(msg, True, GREEN)
            screen.blit(ms, (MID_X + 20, MID_Y + 80))

        elif mode == MODE_CAM:
            msg = "CAMERA NAVIGATION ACTIVE"
            ms = font_body.render(msg, True, BLUE)
            screen.blit(ms, (MID_X + 20, MID_Y + 80))

        # Camera feed box
        draw_panel(screen, CAM_RECT, radius=6,
                   color=(8, 9, 15), border=(26, 28, 42))
        cl = font_mono_sm.render("CAM", True, (50, 52, 65))
        screen.blit(cl, (CAM_RECT.x + (CAM_RECT.w - cl.get_width()) // 2,
                          CAM_RECT.y + CAM_RECT.h // 2 - 8))
        # Blink dot
        if (frame // 15) % 2 == 0:
            pygame.draw.circle(screen, RED,
                               (CAM_RECT.right - 10, CAM_RECT.y + 10), 4)

        # Photo / Video buttons
        draw_button(screen, font_label, "📷  PHOTO", btn_photo, mouse,
                    hover_col=BLUE, text_col=TEXT_DIM)
        draw_button(screen, font_label,
                    "⏹  STOP" if video_recording else "⏺  REC",
                    btn_video, mouse,
                    active=video_recording,
                    base_col=(20, 8, 8) if video_recording else PANEL_BG,
                    border_col=RED if video_recording else BORDER,
                    text_col=RED if video_recording else TEXT_DIM,
                    hover_col=RED)

        # ══════════════════════════════════════
        #  RIGHT PANEL
        # ══════════════════════════════════════
        rp_inner = pygame.Rect(RP_X, MID_Y + 8, RP_W, MID_H - 16)
        ry = MID_Y + 8

        # Music card
        mcard = pygame.Rect(RP_X, ry, RP_W, 130)
        draw_panel(screen, mcard)
        draw_mono(screen, font_mono_sm, "NOW PLAYING", (RP_X + 8, ry + 8), TEXT_DIM)
        track_name = music.current_track() if hasattr(music, 'current_track') else "No track"
        tn = font_body.render(track_name[:28], True, TEXT_PRI)
        screen.blit(tn, (RP_X + 8, ry + 22))
        # Mini waveform inside card
        wave_rect = pygame.Rect(RP_X + 4, ry + 40, RP_W - 8, 30)
        draw_waveform(screen, frame, wave_rect, bars=32, playing=music_playing)
        # Controls
        draw_button(screen, font_label,
                    "⏸  PAUSE" if music_playing else "▶  PLAY",
                    btn_play, mouse,
                    active=music_playing, hover_col=ACCENT)
        draw_button(screen, font_label, "⏭  SKIP", btn_skip, mouse,
                    hover_col=ACCENT)
        ry += 138

        # Motor status block
        draw_mono(screen, font_mono_sm, "MOTOR STATUS", (RP_X, ry), TEXT_DIM)
        ry += 14
        for lbl, val in [
            ("DIRECTION", direction),
            ("SPEED",     f"{speed:.1f}"),
            ("SCHEME",    f"MODE {control_mode}"),
            ("LED",       f"RGB {led_color}"),
        ]:
            ms_r = pygame.Rect(RP_X, ry, RP_W, 22)
            draw_panel(screen, ms_r, radius=4, color=(11, 12, 20), border=(20, 22, 32))
            ls = font_label.render(lbl, True, TEXT_DIM)
            vs = font_mono_sm.render(str(val), True, TEXT_SEC)
            screen.blit(ls, (RP_X + 6, ry + 5))
            screen.blit(vs, (RP_X + RP_W - vs.get_width() - 6, ry + 5))
            ry += 26

        # Quick actions
        ry += 4
        draw_mono(screen, font_mono_sm, "QUICK ACTIONS", (RP_X, ry), TEXT_DIM)
        ry += 14
        btn_snap  = pygame.Rect(RP_X,            ry,      qa_w, 28)
        btn_vrec  = pygame.Rect(RP_X + qa_w + 6, ry,      qa_w, 28)
        btn_led_g = pygame.Rect(RP_X,            ry + 34, qa_w, 28)
        btn_led_x = pygame.Rect(RP_X + qa_w + 6, ry + 34, qa_w, 28)
        draw_button(screen, font_label, "📷  SNAP",  btn_snap,  mouse, hover_col=BLUE)
        draw_button(screen, font_label,
                    "⏹  STOP" if video_recording else "⏺  VIDEO",
                    btn_vrec, mouse,
                    active=video_recording,
                    border_col=RED if video_recording else BORDER,
                    text_col=RED if video_recording else TEXT_DIM,
                    hover_col=RED)
        draw_button(screen, font_label, "◉  GREEN", btn_led_g, mouse, hover_col=GREEN)
        draw_button(screen, font_label, "◎  OFF",   btn_led_x, mouse, hover_col=TEXT_DIM)

        # ══════════════════════════════════════
        #  BOTTOM WAVEFORM BAR
        # ══════════════════════════════════════
        wave_bottom_rect = pygame.Rect(0, 640 - WAVE_H - STATUS_H, 960, WAVE_H)
        draw_waveform(screen, frame, wave_bottom_rect, bars=80, playing=music_playing)

        # ══════════════════════════════════════
        #  STATUS BAR
        # ══════════════════════════════════════
        sb_y = 640 - STATUS_H
        sb_items = [
            ("▸ FLASK", f":5000"),
            ("MODE",    MODE_LABELS[mode]),
            ("SCHEME",  f"{'WASD' if control_mode==1 else 'QA/WS'}"),
            ("SPEED",   f"{speed:.1f}"),
            ("FRAME",   str(frame)),
        ]
        sx = 14
        for lbl, val in sb_items:
            ls = font_mono_sm.render(lbl, True, TEXT_DIM)
            vs = font_mono_sm.render(val,  True, TEXT_SEC)
            screen.blit(ls, (sx, sb_y + (STATUS_H - ls.get_height()) // 2))
            sx += ls.get_width() + 4
            screen.blit(vs, (sx, sb_y + (STATUS_H - vs.get_height()) // 2))
            sx += vs.get_width() + 16
            # separator
            pygame.draw.line(screen, BORDER,
                             (sx - 6, sb_y + 6), (sx - 6, sb_y + STATUS_H - 6))

        vers = font_mono_sm.render("KIDA v1.0 · RASPBERRY PI", True, TEXT_DIM)
        screen.blit(vers, (955 - vers.get_width(),
                           sb_y + (STATUS_H - vers.get_height()) // 2))

        # ══════════════════════════════════════
        #  EVENTS
        # ══════════════════════════════════════
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == music.SONG_END:
                music.handle_event(event)
                music_playing = music.playing

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_TAB:
                    mode = (mode + 1) % 3
                elif event.key == pygame.K_m and music.playlist:
                    music.play_next()
                    music_playing = True
                elif event.key == pygame.K_SPACE:
                    music.stop()
                    music_playing = False
                elif mode == MODE_USER:
                    if event.key == pygame.K_x:
                        speed_idx = (speed_idx + 1) % len(speed_levels)
                        speed = speed_levels[speed_idx]
                    elif event.key == pygame.K_1:
                        control_mode = 1
                    elif event.key == pygame.K_2:
                        control_mode = 2
                    elif event.key == pygame.K_c:
                        take_photo()
                    elif event.key == pygame.K_v:
                        toggle_video_recording()

            elif event.type == pygame.MOUSEBUTTONDOWN:
                # Mode tabs
                for i, trect in enumerate(tabs):
                    if trect.collidepoint(event.pos):
                        mode = i

                # D-pad
                if mode == MODE_USER:
                    for cmd, r in dpad.items():
                        if r.collidepoint(event.pos):
                            if cmd == "forward":
                                motors.forward(speed); led_color = (0,255,0)
                            elif cmd == "backward":
                                motors.backward(speed); led_color = (255,0,0)
                            elif cmd == "left":
                                motors.turn_left(speed); led_color = (0,0,255)
                            elif cmd == "right":
                                motors.turn_right(speed); led_color = (255,255,0)
                            elif cmd == "stop":
                                motors.stop(); led_color = (0,0,0)
                            direction = cmd.upper()
                            led.set_all_led_color(*led_color)

                    # Speed dots
                    for i, r in enumerate(spd_dots):
                        if r.collidepoint(event.pos):
                            speed_idx = i
                            speed = speed_levels[speed_idx]

                    # Scheme
                    for i, r in enumerate(sch_dots):
                        if r.collidepoint(event.pos):
                            control_mode = i + 1

                    # Photo / Video
                    if btn_photo.collidepoint(event.pos):
                        take_photo()
                    if btn_video.collidepoint(event.pos):
                        toggle_video_recording()
                    if btn_snap.collidepoint(event.pos):
                        take_photo()
                    if btn_vrec.collidepoint(event.pos):
                        toggle_video_recording()
                    if btn_led_g.collidepoint(event.pos):
                        led_color = (0,255,0); led.set_all_led_color(0,255,0)
                    if btn_led_x.collidepoint(event.pos):
                        led_color = (0,0,0);   led.set_all_led_color(0,0,0)

                # Music
                if btn_play.collidepoint(event.pos):
                    if music_playing:
                        music.stop(); music_playing = False
                    else:
                        music.play_next(); music_playing = True
                if btn_skip.collidepoint(event.pos) and music_playing:
                    music.play_next()

        # ══════════════════════════════════════
        #  FLASK COMMAND QUEUE
        # ══════════════════════════════════════
        while not command_queue.empty():
            cmd = command_queue.get()
            print(f"🤖 Flask cmd: {cmd}")

            if cmd in ("up", "forward"):
                motors.forward(speed); led_color=(0,255,0)
                direction = "FORWARD"
            elif cmd in ("down", "backward"):
                motors.backward(speed); led_color=(255,0,0)
                direction = "BACKWARD"
            elif cmd == "left":
                motors.turn_left(speed); led_color=(0,0,255)
                direction = "LEFT"
            elif cmd == "right":
                motors.turn_right(speed); led_color=(255,255,0)
                direction = "RIGHT"
            elif cmd == "stop":
                motors.stop(); led_color=(0,0,0)
                direction = "STOPPED"
            elif cmd == "photo":
                take_photo()
            elif cmd == "video":
                toggle_video_recording()
            elif cmd in ("music", "play_music", "start_music"):
                if not music_playing:
                    music.play_next(); music_playing = True
            elif cmd in ("stop_music", "pause_music", "music_stop"):
                if music_playing:
                    music.stop(); music_playing = False
            elif cmd in ("skip", "skip_music", "next_music"):
                music.play_next()
            elif cmd == "speed":
                speed_idx = (speed_idx + 1) % len(speed_levels)
                speed = speed_levels[speed_idx]
            elif cmd == "mode":
                control_mode = 2 if control_mode == 1 else 1
            else:
                print(f"⚠️ Unknown command: {cmd}")

            led.set_all_led_color(*led_color)

        # ══════════════════════════════════════
        #  CONTROL LOGIC
        # ══════════════════════════════════════
        if mode == MODE_AUTO:
            if obstacle_avoid.check_and_avoid():
                led_color = (255, 0, 0)
                led.set_all_led_color(*led_color)
                led.show()
                pygame.display.flip()
                frame += 1
                clock.tick(30)
                continue

        elif mode == MODE_USER:
            keys = pygame.key.get_pressed()
            if control_mode == 1:
                if keys[pygame.K_w]:
                    motors.forward(speed);    led_color=(0,255,0);   direction="FORWARD"
                elif keys[pygame.K_s]:
                    motors.backward(speed);   led_color=(255,0,0);   direction="BACKWARD"
                elif keys[pygame.K_a]:
                    motors.turn_left(speed);  led_color=(0,0,255);   direction="LEFT"
                elif keys[pygame.K_d]:
                    motors.turn_right(speed); led_color=(255,255,0); direction="RIGHT"
                else:
                    motors.stop(); led_color=(0,0,0); direction="STOPPED"
            else:
                left, right = motors.control_mode_2(keys, speed)
                if left and right:   led_color=(0,255,255)
                elif left:           led_color=(255,0,255)
                elif right:          led_color=(255,165,0)
                else:                led_color=(0,0,0)
            led.set_all_led_color(*led_color)

        elif mode == MODE_CAM:
            # Camera navigation (uncomment when cam_nav is available)
            # img, scene_description = cam_nav.navigate()
            led_color = (100, 100, 255)
            led.set_all_led_color(*led_color)

        if music_playing:
            led.rhythm_wave(frame)

        led.show()
        frame += 1
        pygame.display.flip()
        clock.tick(30)

    # ── Cleanup ────────────────────────────────
    led.led_close()
    cam.stop_preview()
    cam.stop()
    obstacle_avoid.cleanup()
    pygame.quit()


if __name__ == "__main__":
    main()