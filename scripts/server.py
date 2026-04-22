#!/usr/bin/env python3

"""
flask_server.py — Flask app + Zeroconf mesh discovery.
KIDA registers itself on the local network and discovers other robots/nodes
automatically. The dashboard at / shows live status of all found peers.
"""

import io
import logging
import os
import socket
import threading
import time
import requests
from flask import Flask, Response, jsonify, request, render_template, render_template_string, send_from_directory
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser

from shared_state import (
    command_queue,
    _robot_state, _robot_state_lock,
    _system_stats, _stats_lock,
    _face_results, _face_lock,
    _cam_jpeg, _cam_jpeg_lock,
    _light_paint_state, _light_paint_lock,
    _media_state, _media_lock,
    _qr_state, _qr_lock,
    _dance_active, _sleep_active,
    _audio_amps, _audio_amps_lock,
)

# ── Config ─────────────────────────────────────────────────────────────────────
THIS_NAME = "KIDA00"
THIS_PORT = 5003
TYPE      = "_flask-link._tcp.local."

logger     = logging.getLogger("kida.flask")
_BASE      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PHOTOS    = os.path.join(_BASE, "photos")
_VIDEOS    = os.path.join(_BASE, "videos")
app     = Flask(__name__,
                static_folder=os.path.join(_BASE, "static"),
                template_folder=os.path.join(_BASE, "templates"))

# ── Network discovery ──────────────────────────────────────────────────────────
found_servers: dict = {}
_found_lock = threading.Lock()


def get_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


my_ip = get_ip()


class _Listener:
    def remove_service(self, zc, type_, name):
        short = name.split(".")[0]
        with _found_lock:
            found_servers.pop(short, None)
        logger.info("Peer left: %s", short)

    def add_service(self, zc, type_, name):
        self.update_service(zc, type_, name)

    def update_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name)
        if info:
            addresses = [socket.inet_ntoa(a) for a in info.addresses]
            if addresses:
                short = name.split(".")[0]
                if short != THIS_NAME:
                    url = f"http://{addresses[0]}:{info.port}"
                    with _found_lock:
                        found_servers[short] = url
                    logger.info("Peer found: %s @ %s", short, url)


# Zeroconf — started once at import time
_zeroconf = Zeroconf()
_zc_info  = ServiceInfo(
    TYPE,
    f"{THIS_NAME}.{TYPE}",
    addresses=[socket.inet_aton(my_ip)],
    port=THIS_PORT,
    properties={"version": "1.0"},
)
_zeroconf.register_service(_zc_info)
ServiceBrowser(_zeroconf, TYPE, _Listener())
logger.info("Zeroconf registered: %s on %s:%d", THIS_NAME, my_ip, THIS_PORT)


def shutdown_zeroconf() -> None:
    """Call this during app shutdown to cleanly deregister from the network."""
    logger.info("Unregistering Zeroconf service...")
    _zeroconf.unregister_service(_zc_info)
    _zeroconf.close()


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def dashboard():
    # Serve index.html from templates first; fall back to live network page
    try:
        return render_template("index.html")
    except Exception:
        pass

    # Live network dashboard (fallback if no index.html)
    status_html = (
        f'<div class="peer self">'
        f'<span class="dot green">●</span>'
        f'<b>{THIS_NAME}</b> (this robot — {my_ip}:{THIS_PORT})</div>'
    )
    with _found_lock:
        peers = dict(found_servers)

    for name, url in peers.items():
        try:
            r      = requests.get(f"{url}/ping", timeout=0.5)
            colour = "green" if r.status_code == 200 else "orange"
            label  = "Online" if r.status_code == 200 else f"HTTP {r.status_code}"
        except Exception:
            colour, label = "red", "Unreachable"
        status_html += (
            f'<div class="peer">'
            f'<span class="dot {colour}">●</span>'
            f'<b>{name}</b> {label} — '
            f'<a href="{url}">{url}</a></div>'
        )

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
  <title>{{ name }} — Network</title>
  <meta charset="utf-8">
  <script>setTimeout(()=>location.reload(),3000);</script>
  <style>
    body{font-family:sans-serif;background:#0d0e14;color:#e6e6e1;
         display:flex;justify-content:center;padding-top:60px;margin:0}
    .card{background:#0e0f16;border:1px solid #20233a;border-radius:14px;
          padding:32px 40px;min-width:340px;box-shadow:0 6px 24px #0007}
    h1{margin:0 0 4px;color:#ff1e64;letter-spacing:2px}
    p.sub{color:#3c3e4b;font-size:.75em;margin:0 0 20px}
    hr{border-color:#20233a;margin:16px 0}
    .peer{padding:10px 0;border-bottom:1px solid #1a1c28;font-size:.95em}
    .peer:last-child{border-bottom:none}
    .dot{font-size:1.1em;margin-right:8px}
    .green{color:#1dc878}.orange{color:#ffa028}.red{color:#e24b4a}
    a{color:#378add;text-decoration:none}
  </style>
</head>
<body>
  <div class="card">
    <h1>KIDA NETWORK</h1>
    <p class="sub">Zeroconf · {{ type }} · refreshes every 3 s</p>
    <hr>
    {{ status|safe }}
  </div>
</body>
</html>
    """, name=THIS_NAME, type=TYPE, status=status_html)


@app.route("/ping")
def ping():
    return f"{THIS_NAME} alive", 200


@app.route("/status")
def status():
    with _robot_state_lock:
        state = _robot_state.copy()
    with _media_lock:
        state.update(_media_state)
    state["dancing"] = _dance_active.is_set()
    state["sleeping"] = _sleep_active.is_set()
    return jsonify(state)


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
    # FACE is removed — face scanning always runs; not a selectable mode
    if mode_str in ("USER", "AUTONOMOUS", "LINE", "QR"):
        command_queue.put(f"_mode_{mode_str.lower()}")
        return jsonify({"mode": mode_str})
    return jsonify({"error": "invalid mode"}), 400


@app.route("/face/results")
def face_results():
    with _face_lock:
        return jsonify({"results": _face_results.copy()})


@app.route("/video_feed")
def video_feed():
    """MJPEG stream of the latest camera frame pushed by the main loop."""
    def generate():
        while True:
            with _cam_jpeg_lock:
                frame = _cam_jpeg[0]
            if frame:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )
            time.sleep(0.04)
    return Response(generate(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/media/photo/<path:filename>")
def serve_photo(filename):
    """Serve a captured photo as a file download."""
    return send_from_directory(_PHOTOS, filename, as_attachment=True)


@app.route("/media/video/<path:filename>")
def serve_video(filename):
    """Serve a recorded video as a file download."""
    return send_from_directory(_VIDEOS, filename, as_attachment=True)


@app.route("/rift_status")
def rift_status():
    """Check if something is listening on localhost:5000 (Rift / VR bridge)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.15)
        online = s.connect_ex(("127.0.0.1", 5000)) == 0
        s.close()
        return jsonify({"online": online})
    except Exception:
        return jsonify({"online": False})


@app.route("/light_paint", methods=["POST"])
def light_paint_route():
    """Trigger a long-exposure light-painting capture on the Pi camera."""
    data = request.get_json(force=True) or {}
    try:
        duration = max(1, min(60, int(data.get("duration", 10))))
    except (ValueError, TypeError):
        duration = 10
    with _light_paint_lock:
        if _light_paint_state["active"]:
            return jsonify({"error": "already capturing"}), 409
        _light_paint_state.update({
            "pending": True, "duration": duration,
            "progress": 0.0, "last_file": "",
        })
    return jsonify({"status": "triggered", "duration": duration})


@app.route("/light_paint_status")
def light_paint_status():
    with _light_paint_lock:
        return jsonify(dict(_light_paint_state))


@app.route("/qr_status")
def qr_status():
    """Returns the current QR drive action seen by the camera."""
    with _qr_lock:
        return jsonify(dict(_qr_state))


@app.route("/audio_amps")
def audio_amps():
    """Returns live amplitude bar data for the web waveform visualiser."""
    with _audio_amps_lock:
        return jsonify({"amps": list(_audio_amps)})


@app.route("/dance", methods=["POST"])
def dance_route():
    command_queue.put("dance_start")
    return jsonify({"status": "dance_started"})


@app.route("/dance/stop", methods=["POST"])
def dance_stop_route():
    command_queue.put("dance_stop")
    return jsonify({"status": "dance_stopped"})


@app.route("/sleep", methods=["POST"])
def sleep_route():
    command_queue.put("sleep")
    return jsonify({"status": "sleeping"})


@app.route("/wake", methods=["POST"])
def wake_route():
    command_queue.put("wake")
    return jsonify({"status": "waking"})


@app.route("/qr_codes")
def qr_codes_page():
    """Printable page showing every KIDA QR action code."""
    _ACTIONS = [
        ("forward",         "FORWARD",       "hold", "Drive forward while visible"),
        ("backward",        "BACKWARD",      "hold", "Drive backward while visible"),
        ("left",            "TURN LEFT",     "hold", "Turn left while visible"),
        ("right",           "TURN RIGHT",    "hold", "Turn right while visible"),
        ("play_music",      "PLAY MUSIC",    "shot", "Start playing music"),
        ("stop_music",      "STOP MUSIC",    "shot", "Stop music"),
        ("next_song",       "NEXT SONG",     "shot", "Skip to next track"),
        ("mode_user",       "USER MODE",     "shot", "Exit to user-control mode"),
        ("mode_autonomous", "AUTO MODE",     "shot", "Switch to obstacle-avoid"),
        ("mode_line",       "LINE MODE",     "shot", "Switch to line-follower"),
        ("light_paint",     "LIGHT PAINT",   "shot", "Trigger 10 s long exposure"),
        ("dance",           "DANCE",         "shot", "Start dance routine"),
        ("sleep",           "SLEEP",         "shot", "Enter low-power sleep mode"),
        ("wake",            "WAKE",          "shot", "Wake from sleep"),
        ("stop",            "STOP / HALT",   "shot", "Emergency stop"),
    ]
    return render_template_string("""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>KIDA QR Codes</title>
<style>
  body{font-family:monospace;background:#08090d;color:#e6e6e1;margin:0;padding:24px}
  h1{color:#ff1e64;letter-spacing:4px;margin-bottom:4px}
  p.sub{color:#3c3e4b;font-size:12px;margin:0 0 24px}
  .grid{display:flex;flex-wrap:wrap;gap:18px}
  .card{background:#0e0f16;border:1px solid #20223c;border-radius:10px;
        padding:14px;width:172px;text-align:center}
  .card img{width:130px;height:130px;border-radius:4px;border:1px solid #20223c}
  .label{font-size:13px;font-weight:bold;margin:8px 0 2px;color:#e6e6e1}
  .code{font-size:10px;color:#ffa028;margin-bottom:4px}
  .desc{font-size:10px;color:#3c3e4b}
  .badge{display:inline-block;font-size:9px;letter-spacing:1px;border-radius:3px;
         padding:1px 6px;margin-bottom:6px}
  .hold{background:rgba(20,200,160,0.15);color:#14c8a0;border:1px solid #14c8a0}
  .shot{background:rgba(255,30,100,0.12);color:#ff1e64;border:1px solid #ff1e64}
  @media print{body{background:#fff;color:#000}.card{border-color:#ccc;background:#fff}
    .code{color:#885500}.label{color:#000}.desc{color:#555}
    .hold{background:#e0fff8;color:#006644;border-color:#006644}
    .shot{background:#ffe0e8;color:#990022;border-color:#990022}}
</style></head><body>
<h1>KIDA QR DRIVE CODES</h1>
<p class="sub">HOLD = robot acts while code is in frame &nbsp;·&nbsp; SHOT = fires once per detection</p>
<div class="grid">
{% for action, label, kind, desc in actions %}
<div class="card">
  <img src="https://api.qrserver.com/v1/create-qr-code/?size=130x130&ecc=H&data=KIDA:{{ action }}" alt="{{ label }}">
  <div class="badge {{ kind }}">{{ 'HOLD' if kind=='hold' else 'ONE-SHOT' }}</div>
  <div class="label">{{ label }}</div>
  <div class="code">KIDA:{{ action }}</div>
  <div class="desc">{{ desc }}</div>
</div>{% endfor %}
</div>
</body></html>""", actions=_ACTIONS)


@app.route("/peers")
def peers_route():
    """Returns all currently discovered peers as JSON."""
    with _found_lock:
        return jsonify({"self": THIS_NAME, "peers": dict(found_servers)})


# ── Runner ─────────────────────────────────────────────────────────────────────
def run_flask() -> None:
    """Call this in a daemon thread from main.py."""
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    logger.info("Flask starting on %s:%d", my_ip, THIS_PORT)
    app.run(host="0.0.0.0", port=THIS_PORT, debug=False,
            use_reloader=False, threaded=True)