#!/usr/bin/env python3

"""
server.py — Flask app + Zeroconf mesh discovery + fleet registration.
KIDA registers itself on the local network and discovers other robots/nodes
automatically. The dashboard at / shows live status of all found peers.

Fleet: like MILA and WHIP, KIDA heartbeats POST /register to NORA's fleet
registry (192.168.4.1:5000) and to any RIFT fleet manager found over Zeroconf
(_rift._tcp), so it shows up under "Robots" in RIFT, NORA and the PC apps.
Both are needed: while RIFT is the fleet authority NORA hides her own roster
and points callers at RIFT.
"""

import io
import logging
import os
import socket
import threading
import time
import requests
from flask import Flask, Response, jsonify, request, render_template, render_template_string
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser

import colour_scheme
from system_monitor import get_local_ip
from shared_state import (
    command_queue, wait_frame,
    _robot_state, _robot_state_lock,
    _system_stats, _stats_lock,
    _face_results, _face_lock,
)

# ── Config ─────────────────────────────────────────────────────────────────────
THIS_NAME = "KIDA00"
THIS_PORT = 5003
TYPE      = "_flask-link._tcp.local."

# Fleet registry — same wire protocol as NORA (esp32.ino) and RIFT (app.py)
RIFT_TYPE         = "_rift._tcp.local."
FLEET_HOST        = os.environ.get("KIDA_FLEET_HOST", "192.168.4.1")   # NORA's AP; set "" to skip NORA
FLEET_PORT        = 5000
FLEET_HEARTBEAT_S = 10     # NORA and RIFT drop an entry after 20 s of silence
FLEET_TYPE        = "tank"
FLEET_CAPS        = "wasd,tank,obstacle_avoidance,line_follow,camera,face_detection,music"

logger = logging.getLogger("kida.flask")
_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app    = Flask(__name__,
               static_folder=os.path.join(_ROOT, "static"),
               template_folder=os.path.join(_ROOT, "templates"))

# ── Network discovery ──────────────────────────────────────────────────────────
found_servers: dict = {}   # _flask-link peers (other robots / DREAM)
rift_servers:  dict = {}   # _rift._tcp fleet managers
_found_lock = threading.Lock()


def get_ip() -> str:
    ip = get_local_ip()
    return "127.0.0.1" if ip == "N/A" else ip


my_ip = get_ip()   # refreshed by _register_when_online once Wi-Fi is up


class _Listener:
    def __init__(self, servers: dict, kind: str = "Peer"):
        self.servers = servers
        self.kind    = kind

    def remove_service(self, zc, type_, name):
        short = name.split(".")[0]
        with _found_lock:
            self.servers.pop(short, None)
        logger.info("%s left: %s", self.kind, short)

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
                        self.servers[short] = url
                    logger.info("%s found: %s @ %s", self.kind, short, url)


# Zeroconf — browsing starts at import; registering waits for a real IP.
# Started at boot (install_service.sh) Wi-Fi may not be up yet, and
# announcing 127.0.0.1 would make KIDA unreachable to its peers.
_zeroconf = Zeroconf()
_zc_info  = None
ServiceBrowser(_zeroconf, TYPE,      _Listener(found_servers))
ServiceBrowser(_zeroconf, RIFT_TYPE, _Listener(rift_servers, "RIFT"))


def _register_when_online() -> None:
    global my_ip, _zc_info
    while (ip := get_ip()).startswith("127."):
        time.sleep(2)
    my_ip = ip
    info = ServiceInfo(
        TYPE,
        f"{THIS_NAME}.{TYPE}",
        addresses=[socket.inet_aton(my_ip)],
        port=THIS_PORT,
        properties={"version": "1.0"},
    )
    try:
        _zeroconf.register_service(info)
        _zc_info = info
        logger.info("Zeroconf registered: %s on %s:%d", THIS_NAME, my_ip, THIS_PORT)
    except Exception as e:
        logger.warning("Zeroconf registration failed: %s", e)


threading.Thread(target=_register_when_online, daemon=True, name="zeroconf-register").start()


def _fleet_targets() -> dict:
    """{label: base url} of every fleet registry to heartbeat right now."""
    targets = {}
    if FLEET_HOST and FLEET_HOST != my_ip:          # KIDA as its own hotspot is 192.168.4.1 too
        targets["NORA"] = f"http://{FLEET_HOST}:{FLEET_PORT}"
    with _found_lock:
        targets.update(rift_servers)
    return targets


def _fleet_heartbeat() -> None:
    """POST /register to NORA and every RIFT, every FLEET_HEARTBEAT_S. Logs
    only when a registry is reached or lost, not on every beat."""
    body    = {"name": THIS_NAME, "type": FLEET_TYPE, "capabilities": FLEET_CAPS}
    session = requests.Session()
    online: dict = {}
    while True:
        for label, url in _fleet_targets().items():
            try:
                ok = session.post(f"{url}/register", data=body, timeout=2).ok
            except requests.RequestException:
                ok = False
            if ok != online.get(label):
                if ok:
                    logger.info("Fleet: registered with %s (%s)", label, url)
                elif label in online:
                    logger.info("Fleet: lost %s (%s)", label, url)
                online[label] = ok
        time.sleep(FLEET_HEARTBEAT_S)


def start_fleet_heartbeat() -> None:
    threading.Thread(target=_fleet_heartbeat, daemon=True, name="fleet-heartbeat").start()


def shutdown_zeroconf() -> None:
    """Call this during app shutdown to cleanly deregister from the network."""
    logger.info("Unregistering Zeroconf service...")
    if _zc_info is not None:
        _zeroconf.unregister_service(_zc_info)
    _zeroconf.close()


# ── Routes ─────────────────────────────────────────────────────────────────────
def _json_body() -> dict:
    """Request JSON as a dict — {} for a missing / non-JSON / non-object body
    (get_json(force=True) alone returned None and the route 500'd)."""
    body = request.get_json(force=True, silent=True)
    return body if isinstance(body, dict) else {}


@app.route("/")
def dashboard():
    # Serve index.html from templates first; fall back to live network page
    try:
        return render_template("index.html", this_name=THIS_NAME,
                               this_ip=get_ip(), this_port=THIS_PORT)
    except Exception:
        pass

    # Live network dashboard (fallback if no index.html)
    status_html = (
        f'<div class="peer self">'
        f'<span class="dot green">●</span>'
        f'<b>{THIS_NAME}</b> (this robot — {get_ip()}:{THIS_PORT})</div>'
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
  <link rel="stylesheet" href="/colour_scheme.css">
  <style>
    body{font-family:sans-serif;background:var(--background);color:var(--text);
         display:flex;justify-content:center;padding-top:60px;margin:0}
    .card{background:var(--panel);border:1px solid var(--border);border-radius:14px;
          padding:32px 40px;min-width:340px;box-shadow:0 6px 24px #0007}
    h1{margin:0 0 4px;color:var(--accent);letter-spacing:2px}
    p.sub{color:var(--text-dim);font-size:.75em;margin:0 0 20px}
    hr{border-color:var(--border);margin:16px 0}
    .peer{padding:10px 0;border-bottom:1px solid var(--divider);font-size:.95em}
    .peer:last-child{border-bottom:none}
    .dot{font-size:1.1em;margin-right:8px}
    .green{color:var(--green)}.orange{color:var(--amber)}.red{color:var(--red)}
    a{color:var(--blue);text-decoration:none}
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


@app.route("/colour_scheme.css")
def colour_scheme_css():
    """colour_scheme.xml as CSS variables — linked after styles.css so it
    overrides its defaults. Re-read per request: edit the XML, reload the page."""
    return Response(colour_scheme.css(), mimetype="text/css",
                    headers={"Cache-Control": "no-cache"})


@app.route("/colour_scheme.xml")
def colour_scheme_xml():
    path = colour_scheme.SCHEME_PATH
    return Response(path.read_bytes() if path.exists() else b"",
                    mimetype="application/xml", headers={"Cache-Control": "no-cache"})


@app.route("/ping")
def ping():
    return f"{THIS_NAME} alive", 200


@app.route("/status")
def status():
    with _robot_state_lock:
        return jsonify(_robot_state.copy())


@app.route("/command", methods=["POST"])
def receive_command():
    try:
        cmd = _json_body().get("command", "")
        command_queue.put(cmd)
        return jsonify({"received": cmd, "status": "queued"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/control/send/", methods=["POST"])
def control_send():
    try:
        cmd = _json_body().get("command", "")
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
        spd = max(0.0, min(1.0, float(_json_body().get("speed", 0.6))))
        command_queue.put(f"_speed_{spd:.2f}")
        return jsonify({"speed": spd})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/mode", methods=["POST"])
def set_mode_route():
    mode_str = str(_json_body().get("mode", "")).upper()
    if mode_str in ("USER", "AUTONOMOUS", "LINE", "FACE"):
        command_queue.put(f"_mode_{mode_str}")
        return jsonify({"mode": mode_str})
    return jsonify({"error": "invalid mode"}), 400


@app.route("/video_feed")
def video_feed():
    """MJPEG of the camera panel exactly as ui.py shows it (320x240)."""
    def gen():
        while True:
            jpg = wait_frame(1.0)
            if jpg:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                       + jpg + b"\r\n")
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/qr.png")
def qr_png():
    """Same QR the left panel of ui.py shows — points at this dashboard."""
    import qrcode
    img = qrcode.make(f"http://{get_ip()}:{THIS_PORT}", border=2)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return Response(buf.getvalue(), mimetype="image/png")


@app.route("/face/results")
def face_results():
    with _face_lock:
        return jsonify({"results": _face_results.copy()})


@app.route("/peers")
def peers_route():
    """Returns all currently discovered peers as JSON."""
    with _found_lock:
        return jsonify({"self": THIS_NAME, "peers": dict(found_servers), "rift": dict(rift_servers)})


# ── Runner ─────────────────────────────────────────────────────────────────────
def run_flask() -> None:
    """Call this in a daemon thread from main.py."""
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    logger.info("Flask starting on port %d", THIS_PORT)
    start_fleet_heartbeat()
    app.run(host="0.0.0.0", port=THIS_PORT, debug=False,
            use_reloader=False, threaded=True)