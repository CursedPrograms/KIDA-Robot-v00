#!/usr/bin/env python3

# server.py — KIDA Web Control Server
from flask import Flask, jsonify, request, Response, render_template_string
import threading
import queue
import time
import cv2
from picamera2 import Picamera2


app = Flask(__name__)
command_queue = queue.Queue()

# ── State ─────────────────────────────────────────────────────────────────────
current_mode   = "USER"
direction      = "STOPPED"
speed          = 0.6
video_rec      = False
music_playing  = False
led_color      = (0, 0, 0)

# ── Camera ────────────────────────────────────────────────────────────────────
picam2 = Picamera2()
picam2.configure(picam2.create_preview_configuration(main={"size": (640, 480)}))
picam2.start()

# ── HTML template (inline so it's one file) ───────────────────────────────────
HTML = open("templates/index.html").read()

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return render_template_string(HTML)

@app.route("/status")
def status():
    return jsonify({
        "status":        "online",
        "robot":         "KIDA",
        "mode":          current_mode,
        "direction":     direction,
        "speed":         speed,
        "video_rec":     video_rec,
        "music_playing": music_playing,
        "led":           list(led_color),
    })

@app.route("/command", methods=["POST"])
def receive_command():
    global direction, speed, music_playing, video_rec
    try:
        data    = request.get_json(force=True)
        command = data.get("command", "").strip().lower()
        command_queue.put(command)

        # Update state immediately so /status reflects it fast
        if command in ("forward", "up"):      direction = "FORWARD"
        elif command in ("backward", "down"): direction = "BACKWARD"
        elif command == "left":               direction = "LEFT"
        elif command == "right":              direction = "RIGHT"
        elif command == "stop":               direction = "STOPPED"
        elif command == "play_music":         music_playing = True
        elif command == "stop_music":         music_playing = False
        elif command == "video_start":        video_rec = True
        elif command == "video_stop":         video_rec = False

        return jsonify({"received": command, "status": "queued"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/speed", methods=["POST"])
def set_speed():
    global speed
    try:
        speed = float(request.get_json(force=True).get("speed", speed))
        speed = max(0.1, min(1.0, speed))
        return jsonify({"speed": speed})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/mode", methods=["POST"])
def set_mode():
    global current_mode
    mode_str = request.get_json(force=True).get("mode", "").upper()
    if mode_str in ("USER", "AUTONOMOUS", "LINE"):
        current_mode = mode_str
        return jsonify({"mode": current_mode})
    return jsonify({"error": "invalid mode"}), 400

# ── Video streaming ───────────────────────────────────────────────────────────
def generate_frames():
    while True:
        try:
            frame = picam2.capture_array()
            if frame.shape[2] == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            else:
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            frame = cv2.rotate(frame, cv2.ROTATE_180)
            _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                   + buffer.tobytes() + b"\r\n")
        except Exception:
            time.sleep(0.05)

@app.route("/video_feed")
def video_feed():
    return Response(generate_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

# ── Command worker ────────────────────────────────────────────────────────────
def command_worker():
    while True:
        cmd = command_queue.get()
        print(f"[KIDA] Executing: {cmd}")
        # Hook in your motor controller here, e.g.:
        # if cmd == "forward": motors.forward(speed)
        # elif cmd == "stop":  motors.stop()

# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    threading.Thread(target=command_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=False)