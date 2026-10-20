#!/usr/bin/env python3

"""
mind_drive.py — her MIND mode, the robot's side (fleet TODO section 10): the PC controller's
LLM drives her, stop-look-think-move. The mind itself runs on the PC (controller/drive_mind.py);
her Pi only does what it's asked, with every reflex still on.

  /unlock?pw=&ctl=1          a PC that can think signs in as her mind host (her wheel lock stays
                             as it is: the mind can't unlock her)
  /status?ctl=1              the host checks in; silent HOST_TTL_S and MIND ends (ui.py), she stands
  /mode?m=mind               only while the host checks in (409 otherwise); 9 on her keyboard too
  /mind?act=fwd|bwd|left|right|stop&steps=1-4
                             from the host, in MIND: STEP_S of driving a step. A forward move with a
                             wall ahead is refused ({"ok": false, "blocked": true})
  /look?at=left|centre|right her camera's servo turns there, and a JPEG of what she sees. Her camera
                             is centred again before she drives
  POST /speak                a WAV (mind.windows_wav) on her speaker

The drive goes through ui.py's command processor ("_mind:<dir>", resent like a remote drive),
so the wheel lock and the wall guard (motor_control.WALL_GUARD_M) still apply.
"""

import threading
import time

import camera_servo
from shared_state import body_ref, command_queue, motor_lock, wait_frame, _robot_state, _robot_state_lock

HOST_TTL_S    = 5.0
STEP_S        = 0.4
RESEND_S      = 0.2     # ui.py stops a remote drive it hasn't heard for REMOTE_HOLD_S (0.8 s)
MAX_STEPS     = 4
LOOK_DEG      = 45      # how far she turns her camera to look to one side
LOOK_SETTLE_S = 0.7     # the servo gets there and the picture stops shaking
CENTRE_S      = 0.3
MOVES = {"fwd": "forward", "bwd": "backward", "left": "left", "right": "right"}

_host = {"ip": None, "seen": 0.0}
_move = {"steps": 0, "blocked": False, "busy": False}
_lock = threading.Lock()


# ── The mind host ──────────────────────────────────────────────────────────────
def sign_in(ip: str) -> None:
    _host.update(ip=ip, seen=time.monotonic())


def check_in(ip: str) -> None:
    if ip == _host["ip"]:
        _host["seen"] = time.monotonic()


def host_alive() -> bool:
    return _host["ip"] is not None and time.monotonic() - _host["seen"] < HOST_TTL_S


def is_host(ip: str) -> bool:
    return ip == _host["ip"] and host_alive()


def in_mind() -> bool:
    with _robot_state_lock:
        return _robot_state.get("mode") == "MIND"


# ── Her body ───────────────────────────────────────────────────────────────────
def wall_ahead() -> bool:
    m = body_ref.get("motors")
    return bool(m and m.wall_ahead())


def distance_cm():
    """Her front sensor in cm, or None (no sensor / no reading)."""
    m = body_ref.get("motors")
    if not (m and m.distance):
        return None
    try:
        d = m.distance()
    except Exception:
        return None
    return None if d is None else round(d * 100, 1)


def status_fields() -> dict:
    """What /status adds for her mind."""
    return {"mindHost": int(host_alive()), "mindSteps": _move["steps"], "blocked": _move["blocked"],
            "distance_cm": distance_cm()}


def act(move: str, steps) -> tuple:
    """/mind?act=&steps=: (json, http code)."""
    move = str(move).strip().lower()
    if move == "stop":
        stop()
        return {"ok": True, "move": "stop"}, 200
    if move not in MOVES:
        return {"ok": False, "error": f"unknown move {move or '(none)'}", "moves": [*MOVES, "stop"]}, 400
    if not in_mind():
        return {"ok": False, "error": "she's not in MIND mode"}, 409
    if motor_lock.is_set():
        return {"ok": False, "error": "her wheels are locked"}, 409
    try:
        steps = max(1, min(MAX_STEPS, int(steps)))
    except (TypeError, ValueError):
        steps = 1
    with _lock:
        if _move["busy"]:
            return {"ok": False, "error": "busy: still on the last move"}, 409
        if move == "fwd" and wall_ahead():
            _move["blocked"] = True
            return {"ok": False, "blocked": True, "distance_cm": distance_cm()}, 409
        _move.update(steps=steps, blocked=False, busy=True)
    threading.Thread(target=_drive, args=(MOVES[move],), daemon=True, name="mind-move").start()
    return {"ok": True, "move": move, "steps": steps}, 200


def _drive(cmd: str) -> None:
    try:
        cs = camera_servo.camera_servo
        if cs.mode != "sweep" and abs(cs.angle - cs.centre_deg) > 1:
            cs.centre()                        # eyes front before she drives
            time.sleep(CENTRE_S)
        while _move["steps"] > 0:
            end = time.monotonic() + STEP_S
            while time.monotonic() < end:
                if not in_mind() or motor_lock.is_set() or _move["steps"] <= 0:
                    return
                if cmd == "forward" and wall_ahead():
                    _move["blocked"] = True
                    return
                command_queue.put(f"_mind:{cmd}")
                time.sleep(RESEND_S)
            _move["steps"] = max(0, _move["steps"] - 1)
    finally:
        command_queue.put("_mind:stop")
        _move.update(steps=0, busy=False)


def stop() -> None:
    _move["steps"] = 0
    command_queue.put("_mind:stop")


def look(at: str) -> tuple:
    """/look?at=: (jpeg bytes, "") or (None, why)."""
    side = {"left": 1, "centre": 0, "center": 0, "ahead": 0, "right": -1}.get(str(at).strip().lower())
    if side is None:
        return None, "at= left, centre or right"
    cs = camera_servo.camera_servo
    if cs.mode == "sweep":
        return None, "her camera is sweeping"
    if _move["busy"]:
        return None, "she's moving"
    cs.set_follow(False)
    turn = side * LOOK_DEG                     # a higher angle looks left (camera_servo.follow_step)
    cs.set_angle(cs.centre_deg + (-turn if cs.invert else turn))
    time.sleep(LOOK_SETTLE_S)
    wait_frame(1.0)                            # a frame from after the turn (ui.py publishes while asked)
    jpg = wait_frame(1.0)
    return (jpg, "") if jpg else (None, "no picture (no camera?)")
