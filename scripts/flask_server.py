#!/usr/bin/env python3

"""
flask_server.py — Flask app + Zeroconf mesh discovery.
KIDA registers itself on the local network and discovers other robots/nodes
automatically. The dashboard at / shows live status of all found peers.
"""

import logging
import socket
import threading
import requests
from flask import Flask, jsonify, request, render_template, render_template_string
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser

from shared_state import (
    command_queue,
    _robot_state, _robot_state_lock,
    _system_stats, _stats_lock,
    _face_results, _face_lock,
)

# ── Config ─────────────────────────────────────────────────────────────────────
THIS_NAME = "KIDA00"
THIS_PORT = 5003
TYPE      = "_flask-link._tcp.local."

logger = logging.getLogger("kida.flask")
app    = Flask(__name__, static_folder="static", template_folder="templates")

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