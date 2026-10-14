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

Like the rest of the fleet (fleet TODO §1, §7):
  /motorlockOn, /motorlockOff?pw=   the wheel lock, as NORA's. She boots locked; locking is
                                    free, unlocking needs Config.MotorPassword (or K at the robot)
  POST /do {"action", "seconds"}    stop, lock_wheels, music_play/stop/next, photo, and timed
                                    drives (forward, back, left, right, turn_left, turn_right; max 3 s)
  POST /music {"action", "track", "at"}   play along when RIFT conducts (fleet_music.py)
  /status                           + motor_lock, moving, music ("playing"/"stopped"), uptime_s
  and every 15 s her state to NINA (POST :5012/report, on RIFT's PC).
"""

import io
import json
import logging
import os
import socket
import threading
import time
import requests
from flask import Flask, Response, jsonify, request, render_template, render_template_string
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser

import colour_scheme
from fleet_near import FleetNear
from system_monitor import get_local_ip
from shared_state import (
    command_queue, wait_frame,
    _robot_state, _robot_state_lock,
    _system_stats, _stats_lock,
    _face_results, _face_lock,
    motor_lock, lock_wheels, unlock_wheels, STARTED,
)
import fleet_music

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

# What POST /do takes (fleet TODO §1/§7): one "do:<action>" capability each, so RIFT
# relays to /do. Drives stop by themselves after "seconds" (max MAX_DRIVE_S).
DO_SIMPLE = {"music_play": "music", "music_stop": "stop_music", "music_next": "skip", "photo": "photo"}
DO_DRIVE  = {"forward": "forward", "back": "backward", "left": "left", "right": "right",
             "turn_left": "left", "turn_right": "right"}     # she turns on the spot either way
DO_ACTIONS = ["stop", "lock_wheels", *DO_SIMPLE, *DO_DRIVE]
MAX_DRIVE_S = 3.0
FLEET_CAPS = ("wasd,tank,obstacle_avoidance,line_follow,camera,face_detection,music,"
              f"music:{THIS_PORT}," + ",".join(f"do:{a}" for a in DO_ACTIONS))

NINA_PORT     = 5012   # NINA (the fleet's caretaker) runs next to RIFT
NINA_REPORT_S = 15


def _motor_password() -> str:
    """Unlocking needs this: KIDA_MOTOR_PASSWORD, else Config.MotorPassword in config.json
    (empty in the repo; set it on the robot). Empty = remote unlock refused (K at the robot still works)."""
    pw = os.environ.get("KIDA_MOTOR_PASSWORD")
    if pw:
        return pw
    try:
        with open(os.path.join(_ROOT, "config.json"), encoding="utf-8") as f:
            return str(json.load(f)["Config"].get("MotorPassword", ""))
    except (OSError, ValueError, KeyError):
        return ""

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


def _rift_url() -> str:
    """The first RIFT found over Zeroconf ("" if none yet): its clock for music, NINA next to it."""
    with _found_lock:
        return next(iter(rift_servers.values()), "")


def _status() -> dict:
    """/status: her telemetry plus the fleet's common fields (moving, music, motor_lock, uptime_s)."""
    with _robot_state_lock:
        st = _robot_state.copy()
    locked = motor_lock.is_set()
    st.update(motor_lock=locked,
              moving=not locked and st.get("direction", "STOPPED") != "STOPPED",
              music="playing" if st.get("music_playing") else "stopped",
              uptime_s=int(time.time() - STARTED))
    return st


def _nina_report() -> None:
    """Every NINA_REPORT_S, her state to NINA (POST /report), who watches the whole fleet.
    NINA runs on RIFT's PC; nothing happens until a RIFT is found."""
    session = requests.Session()
    while True:
        time.sleep(NINA_REPORT_S)
        rift = _rift_url()
        if not rift:
            continue
        st = _status()
        body = {"name": THIS_NAME, "state": {
            "moving": st["moving"], "turning": st.get("direction") in ("LEFT", "RIGHT"),
            "wheels_locked": st["motor_lock"], "music": st["music"], "mode": st.get("mode")}}
        try:
            session.post(f"{rift.rsplit(':', 1)[0]}:{NINA_PORT}/report", json=body, timeout=2)
        except requests.RequestException:
            pass


def start_fleet_heartbeat() -> None:
    threading.Thread(target=_fleet_heartbeat, daemon=True, name="fleet-heartbeat").start()
    threading.Thread(target=_nina_report, daemon=True, name="nina-report").start()


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


# Which robots are nearby: Bluetooth LE beacons from NORA, WHIP and the other KIDA,
# heard by the Pi's own Bluetooth (fleet_near.py), and this robot's beacon for them.
near = FleetNear(THIS_NAME).start()


@app.route("/near")
def near_robots():
    return jsonify(near.status())


@app.route("/status")
def status():
    return jsonify(_status())


# ── Wheel lock (like NORA's /motorlockOn, /motorlockOff?pw=) ───────────────────
@app.route("/motorlockOn", methods=["GET", "POST"])
def motorlock_on():
    lock_wheels()
    command_queue.put("stop")
    return "OK", 200


@app.route("/motorlockOff", methods=["GET", "POST"])
def motorlock_off():
    pw, want = request.values.get("pw", ""), _motor_password()
    if not want:
        return "DENIED (no MotorPassword set in config.json)", 403
    if pw != want:
        return "DENIED", 403
    unlock_wheels()
    return "OK", 200


# ── The fleet's "do" (RIFT relays POST /talk verb do here) ─────────────────────
_drive = {"until": 0.0}


def _drive_for(cmd: str, seconds: float) -> None:
    """Resend the drive command while it lasts (ui.py stops a remote drive that isn't
    resent within REMOTE_HOLD_S), then stop. The wheel lock or a /do stop ends it early."""
    while time.monotonic() < _drive["until"] and not motor_lock.is_set():
        command_queue.put(cmd)
        time.sleep(0.2)
    _drive["until"] = 0.0
    command_queue.put("stop")


@app.route("/do", methods=["POST"])
def do_action():
    body   = _json_body()
    action = str(body.get("action", "")).strip().lower()
    if action == "stop":                   # always works: ends a timed drive, and autonomous / line driving
        _drive["until"] = 0.0
        command_queue.put("stop")
        if _robot_state.get("mode") in ("AUTONOMOUS", "LINE"):
            command_queue.put("_mode_USER")
        return jsonify({"ok": True, "action": action})
    if action == "lock_wheels":
        lock_wheels()
        command_queue.put("stop")
        return jsonify({"ok": True, "action": action})
    if action in DO_SIMPLE:
        command_queue.put(DO_SIMPLE[action])
        return jsonify({"ok": True, "action": action})
    if action not in DO_DRIVE:
        return jsonify({"ok": False, "error": f"KIDA00 can't {action or '(nothing)'}", "does": DO_ACTIONS}), 400
    if motor_lock.is_set():
        return jsonify({"ok": False, "error": "her wheels are locked"}), 409
    mode = _robot_state.get("mode", "USER")
    if mode != "USER":
        return jsonify({"ok": False, "error": f"she's in {mode} mode; she takes drive commands in USER mode"}), 409
    if time.monotonic() < _drive["until"]:
        return jsonify({"ok": False, "error": "busy: still on the last drive"}), 409
    try:
        seconds = max(0.1, min(MAX_DRIVE_S, float(body.get("seconds", 0.5))))
    except (TypeError, ValueError):
        seconds = 0.5
    _drive["until"] = time.monotonic() + seconds
    threading.Thread(target=_drive_for, args=(DO_DRIVE[action], seconds), daemon=True, name="do-drive").start()
    return jsonify({"ok": True, "action": action, "seconds": seconds})


# ── Music together (RIFT conducts; fleet_music.py) ─────────────────────────────
@app.route("/music", methods=["GET", "POST"])
def music_together():
    if request.method == "GET":
        return jsonify(fleet_music.status())
    out, code = fleet_music.command(_json_body(), _rift_url())
    return jsonify(out), code


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