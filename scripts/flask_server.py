"""
flask_server.py — Flask app, all routes, and the thread runner.
"""

import logging
from flask import Flask, jsonify, request, render_template

from shared_state import (
    command_queue,
    _robot_state, _robot_state_lock,
    _system_stats, _stats_lock,
    _face_results, _face_lock,
)

app = Flask(__name__, static_folder="static", template_folder="templates")

logger = logging.getLogger("kida.flask")


@app.route("/")
def home():
    return render_template("index.html")


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


def run_flask() -> None:
    """Call this in a daemon thread."""
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
