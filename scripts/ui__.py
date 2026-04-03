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

from music_player import MusicPlayer
from motor_control import MotorController
from obstacle_avoidance import ObstacleAvoidance
from led_control import SPI_WS2812_LEDStrip
from picamera2 import Picamera2

from flask import Flask, render_template, jsonify, request

# Flask app setup
app = Flask(__name__, static_folder='static', template_folder='templates')
command_queue = queue.Queue()

#rework ai and show camera in screen

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/status')
def status():
    return jsonify({
        'status': 'online',
        'robot': 'KIDA',
        'message': 'All systems go!'
    })

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
        ram_used = mem.used // (1024 * 1024)
        ram_total = mem.total // (1024 * 1024)
        ip_address = get_local_ip()

        disk_io = psutil.disk_io_counters()
        boot_time = datetime.datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")
        threads = threading.active_count()

        # Ping Google for latency (blocking - moved to thread)
        try:
            ping = subprocess.check_output(["ping", "-c", "1", "8.8.8.8"], timeout=1).decode()
            latency_line = [line for line in ping.split("\n") if "time=" in line]
            latency = latency_line[0].split("time=")[1].split(" ")[0] + " ms" if latency_line else "N/A"
        except:
            latency = "N/A"

        return {
            "cpu": cpu_usage,
            "temp": cpu_temp,
            "ram_used": ram_used,
            "ram_total": ram_total,
            "ip": ip_address,
            "disk_read_mb": round(disk_io.read_bytes / 1024 / 1024, 1),
            "disk_write_mb": round(disk_io.write_bytes / 1024 / 1024, 1),
            "boot_time": boot_time,
            "latency": latency,
            "threads": threads,
        }
    except Exception as e:
        return {"error": str(e)}

def draw_system_stats(screen, font, stats):
    lines = [
        f"🧠 CPU Usage: {stats.get('cpu', 'N/A')}%",
        f"🌡️ CPU Temp: {stats.get('temp', 'N/A')}°C",
        f"📦 RAM Usage: {stats.get('ram_used', 'N/A')}/{stats.get('ram_total', 'N/A')} MB",
        f"🌐 IP Address: {stats.get('ip', 'N/A')}",
        f"📂 Disk Read: {stats.get('disk_read_mb', 'N/A')} MB",
        f"📁 Disk Write: {stats.get('disk_write_mb', 'N/A')} MB",
        f"🕓 Last Boot: {stats.get('boot_time', 'N/A')}",
        f"🔁 Active Threads: {stats.get('threads', 'N/A')}",
        f"🌐 Network Latency: {stats.get('latency', 'N/A')}",
    ]

    for i, line in enumerate(lines):
        text = font.render(line, True, (255, 255, 255))
        screen.blit(text, (750, 10 + i * 22))

def draw_waveform(screen, frame, rect, bars=50, max_height=100):
    import math
    amplitudes = [(math.sin(frame * 0.1 + i * 0.3) + 1) / 2 for i in range(bars)]
    bar_width = rect.width // bars
    surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    for i, amp in enumerate(amplitudes):
        bar_height = int(amp * max_height)
        x = i * bar_width
        y = rect.height - bar_height
        pygame.draw.rect(surface, (255, 20, 147, 128), (x, y, bar_width - 2, bar_height))
    screen.blit(surface, (rect.x, rect.y))

def qr_to_pygame_surface(data, size=150):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    img = img.resize((size, size), Image.LANCZOS)

    mode = img.mode
    size = img.size
    data = img.tobytes()

    if mode == "RGB":
        surface = pygame.image.fromstring(data, size, mode)
    elif mode == "L":
        surface = pygame.image.fromstring(data, size, mode)
        surface = pygame.Surface.convert(surface)
    else:
        img = img.convert("RGB")
        data = img.tobytes()
        surface = pygame.image.fromstring(data, img.size, "RGB")

    return surface

# Global variables for system stats
system_stats = {}
stats_lock = threading.Lock()

def stats_updater():
    global system_stats
    while True:
        new_stats = get_system_stats()
        with stats_lock:
            system_stats = new_stats
        time.sleep(1)  # update every second


def main():
    pygame.init()
    screen = pygame.display.set_mode((960, 640))
    pygame.display.set_caption("KIDA Controller")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("Arial", 20)

    # Start Flask server in background thread
    flask_thread = threading.Thread(target=run_flask_server)
    flask_thread.daemon = True
    flask_thread.start()
    print("🌐 Flask server started on http://0.0.0.0:5000")

    # Start system stats updater thread
    stats_thread = threading.Thread(target=stats_updater, daemon=True)
    stats_thread.start()

    bg = pygame.image.load("/home/nova/Desktop/kida/images/bg.jpg")
    bg = pygame.transform.scale(bg, (960, 640))

    music = MusicPlayer("/home/nova/Desktop/kida/audio/music/")
    motors = MotorController()
    obstacle_avoid = ObstacleAvoidance(motors=motors)
    led = SPI_WS2812_LEDStrip(8, 128)
    cam = Picamera2()
    cam.start_preview()
    cam.start()
    
    #cam_nav = CameraNavigator(cam, motors, speed=0.6)

    if not led.check_spi_state():
        print("SPI init failed. Exiting.")
        return

    qr_url = "http://0.0.0.0:5000"
    qr_surface = qr_to_pygame_surface(qr_url)

    MODE_MENU = 0
    MODE_USER = 1
    MODE_AUTO = 2
    MODE_CAM_AVOID = 3
    BRIGHT_PINK = (255, 20, 147)

    def draw_button(screen, font, text, rect, mouse, frame, base=BRIGHT_PINK, hover=(255, 105, 180)):
        pulse = 50 + int(50 * (1 + numpy.sin(frame * 0.1)) / 2)
        color_base = hover if rect.collidepoint(mouse) else base
        color = tuple(min(255, max(0, c + pulse - 50)) for c in color_base)
        pygame.draw.rect(screen, color, rect, border_radius=10)
        label = font.render(text, True, (255, 255, 255))
        screen.blit(label, (rect.x + 10, rect.y + 10))

    mode = MODE_MENU
    speed_levels = [0.4, 0.6, 0.8, 1.0]
    speed_idx = 0
    speed = speed_levels[speed_idx]
    control_mode = 1
    music_playing = False
    frame = 0

    photos_dir = "/home/nova/Desktop/kida/photos" #make paths relative
    videos_dir = "/home/nova/Desktop/kida/videos" #make paths relative
    os.makedirs(photos_dir, exist_ok=True)
    os.makedirs(videos_dir, exist_ok=True)

    btns = {
        "user_mode": pygame.Rect(250, 200, 200, 60),
        "auto_mode": pygame.Rect(510, 200, 200, 60),
        "music": pygame.Rect(30, 400, 180, 40),
        "skip": pygame.Rect(30, 460, 180, 40),
        "speed": pygame.Rect(230, 400, 180, 40),
        "switch_control": pygame.Rect(430, 400, 220, 40),
        "back": pygame.Rect(30, 20, 100, 30),
        "photo": pygame.Rect(750, 400, 100, 40),
        "video": pygame.Rect(870, 400, 100, 40),
        "cam_mode": pygame.Rect(380, 280, 200, 60),
    }

    def take_photo():
        filename = os.path.join(photos_dir, f"photo_{int(time.time())}.jpg")
        cam.capture_file(filename)
        print(f"📸 Photo saved: {filename}")

    video_recording = False
    video_file_name = None

    def toggle_video_recording():
        nonlocal video_recording, video_file_name
        if not video_recording:
            video_file_name = os.path.join(videos_dir, f"video_{int(time.time())}.h264")
            cam.start_recording(video_file_name)
            video_recording = True
            print(f"🎥 Started recording video: {video_file_name}")
        else:
            cam.stop_recording()
            video_recording = False
            print(f"🛑 Stopped recording video: {video_file_name}")
            video_file_name = None

    running = True
    while running:
        screen.blit(bg, (0, 0))
        mouse = pygame.mouse.get_pos()

        # Draw QR code once
        screen.blit(qr_surface, (10, 10))

        # Read stats safely from the background thread
        with stats_lock:
            stats_copy = system_stats.copy()

        draw_waveform(screen, frame, pygame.Rect(30, 540, 900, 100))
        draw_system_stats(screen, font, stats_copy)

        # Draw UI buttons
        if mode == MODE_MENU:
            draw_button(screen, font, "🚩 User Control", btns["user_mode"], mouse, frame)
            draw_button(screen, font, "🚩 Autonomy", btns["auto_mode"], mouse, frame)
            draw_button(screen, font, "🎥 Cam Avoidance", btns["cam_mode"], mouse, frame)

        if mode in (MODE_USER, MODE_AUTO, MODE_CAM_AVOID):
            draw_button(screen, font, "⏹ Stop Music" if music_playing else "🎵 Play Music", btns["music"], mouse, frame)
            draw_button(screen, font, "⏭ Skip Song", btns["skip"], mouse, frame)
            draw_button(screen, font, "⏹ Back", btns["back"], mouse, frame)

        if mode == MODE_USER:
            draw_button(screen, font, f"🚀 Speed {speed_idx + 1}", btns["speed"], mouse, frame)
            draw_button(screen, font, f"🎮 Mode {control_mode}", btns["switch_control"], mouse, frame)
            draw_button(screen, font, "📸 Photo", btns["photo"], mouse, frame)
            draw_button(screen, font, "🎥 Video", btns["video"], mouse, frame)

        if mode in (MODE_USER, MODE_AUTO):
            status_text = (f"Mode: {'WASD' if control_mode == 1 else 'QA/WS'} | Speed: {speed:.1f}"
                           if mode == MODE_USER else "Autonomous Obstacle Avoidance") #Think about MODE_CAM_AVOID
            status = font.render(status_text, True, (255, 255, 255))
            screen.blit(status, (30, 610))

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == music.SONG_END:
                print("🎵 Song ended event detected, playing next track.")
                music.handle_event(event)
                music_playing = music.playing

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_TAB:
                    mode = MODE_MENU
                elif event.key == pygame.K_m and music.playlist:
                    print("🎵 'M' pressed: playing next song")
                    music.play_next()
                    music_playing = True
                elif event.key == pygame.K_SPACE:
                    print("⏹ Spacebar pressed: stopping music")
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
                if mode == MODE_MENU:
                    if btns["user_mode"].collidepoint(event.pos):
                        mode = MODE_USER
                    elif btns["auto_mode"].collidepoint(event.pos):
                        mode = MODE_AUTO
                    elif btns["cam_mode"].collidepoint(event.pos):
                        mode = MODE_CAM_AVOID
                else:
                    if btns["music"].collidepoint(event.pos):
                        if music_playing:
                            print("⏹ Music button clicked: stopping music")
                            music.stop()
                            music_playing = False
                        else:
                            print("▶️ Music button clicked: playing next song")
                            music.play_next()
                            music_playing = True
                    elif btns["skip"].collidepoint(event.pos) and music_playing:
                        music.play_next()
                    elif btns["back"].collidepoint(event.pos):
                        mode = MODE_MENU
                    elif mode == MODE_USER:
                        if btns["speed"].collidepoint(event.pos):
                            speed_idx = (speed_idx + 1) % len(speed_levels)
                            speed = speed_levels[speed_idx]
                        elif btns["switch_control"].collidepoint(event.pos):
                            control_mode = 2 if control_mode == 1 else 1
                        elif btns["photo"].collidepoint(event.pos):
                            take_photo()
                        elif btns["video"].collidepoint(event.pos):
                            toggle_video_recording()

        # Process commands from Flask queue
        while not command_queue.empty():
            cmd = command_queue.get()
            print(f"🤖 Processing command from Flask: {cmd}")

            if cmd in ("up", "forward"):
                motors.forward(speed)
                led.set_all_led_color(0, 255, 0)

            elif cmd in ("down", "backward"):
                motors.backward(speed)
                led.set_all_led_color(255, 0, 0)

            elif cmd == "left":
                motors.turn_left(speed)
                led.set_all_led_color(0, 0, 255)

            elif cmd == "right":
                motors.turn_right(speed)
                led.set_all_led_color(255, 255, 0)

            elif cmd == "stop":
                motors.stop()
                led.set_all_led_color(0, 0, 0)

            elif cmd == "photo":
                take_photo()

            elif cmd == "video":
                toggle_video_recording()

            elif cmd in ("music", "play_music", "start_music"):
                if not music_playing:
                    music.play_next()
                    music_playing = True

            elif cmd in ("stop_music", "pause_music", "music_stop"):
                if music_playing:
                    music.stop()
                    music_playing = False

            elif cmd in ("skip", "skip_music", "next_music"):
                music.play_next()

            elif cmd == "speed":
                speed_idx = (speed_idx + 1) % len(speed_levels)
                speed = speed_levels[speed_idx]

            elif cmd == "mode":
                control_mode = 2 if control_mode == 1 else 1

            else:
                print(f"⚠️ Unknown command: {cmd}")

        # Control logic based on mode
        if mode == MODE_AUTO:
            if obstacle_avoid.check_and_avoid():
                led.set_all_led_color(255, 0, 0)
                led.show()
                pygame.display.flip()
                continue

        elif mode == MODE_USER:
            keys = pygame.key.get_pressed()
            if control_mode == 1:
                if keys[pygame.K_w]:
                    motors.forward(speed)
                    led.set_all_led_color(0, 255, 0)
                elif keys[pygame.K_s]:
                    motors.backward(speed)
                    led.set_all_led_color(255, 0, 0)
                elif keys[pygame.K_a]:
                    motors.turn_left(speed)
                    led.set_all_led_color(0, 0, 255)
                elif keys[pygame.K_d]:
                    motors.turn_right(speed)
                    led.set_all_led_color(255, 255, 0)
                else:
                    motors.stop()
                    led.set_all_led_color(0, 0, 0)
            else:
                left, right = motors.control_mode_2(keys, speed)
                led.set_all_led_color(
                    *(0, 255, 255) if left and right else
                    (255, 0, 255) if left else
                    (255, 165, 0) if right else
                    (0, 0, 0)
                )
        elif mode == MODE_CAM_AVOID:
            img, scene_description = cam_nav.navigate()
            led.set_all_led_color(100, 100, 255)

    # Convert image and display
            cam_surface = cv2image_to_pygame(img)
            screen.blit(cam_surface, (620, 380))  # Adjust position as needed

    # Draw scene description
            desc = font.render(scene_description, True, (255, 255, 255))
            screen.blit(desc, (30, 580))

        if mode == MODE_CAM_AVOID:
            status = font.render("Camera Obstacle Avoidance", True, (255, 255, 255))
            screen.blit(status, (30, 610))     #Display the photo and the description from camera_navigation in th Pygame Window      

        if music_playing:
            led.rhythm_wave(frame)

        led.show()
        frame += 1
        pygame.display.flip()
        clock.tick(30)

    # Cleanup
    led.led_close()
    cam.stop_preview()
    cam.stop()
    obstacle_avoid.cleanup()
    pygame.quit()

if __name__ == "__main__":
    main()
