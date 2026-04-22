#!/usr/bin/env python3

"""
dance.py — Autonomous dance choreography for KIDA.

start_dance(motors, led, stop_event, speed) launches a daemon thread
that drives both motors and LEDs in a looping choreography until
stop_event is set (or the caller joins the returned thread).

The caller is responsible for:
  • Playing music before/after calling start_dance
  • Not touching motors or LEDs while dancing (thread owns them)
  • Setting stop_event to end the routine cleanly

QR trigger: KIDA:dance  (fires once when code first appears)
"""

import logging
import math
import threading
import time

logger = logging.getLogger("kida.dance")

# ── Choreography ──────────────────────────────────────────────────────────────
# Each step: (move, duration_seconds)
# Moves: "fwd" "bwd" "spin_l" "spin_r" "stop"
_SEQ = [
    # ── Intro march ─────────────────────────────────────────────────────────
    ("fwd",    0.40), ("stop", 0.12),
    ("fwd",    0.40), ("stop", 0.12),
    ("bwd",    0.40), ("stop", 0.12),
    ("bwd",    0.40), ("stop", 0.20),
    # ── Side shake ──────────────────────────────────────────────────────────
    ("spin_l", 0.22), ("spin_r", 0.22),
    ("spin_l", 0.22), ("spin_r", 0.22),
    ("spin_l", 0.22), ("spin_r", 0.22),
    ("stop",   0.22),
    # ── Spin out ────────────────────────────────────────────────────────────
    ("spin_l", 0.90), ("stop", 0.12),
    ("spin_r", 0.90), ("stop", 0.12),
    # ── Charge + retreat ────────────────────────────────────────────────────
    ("fwd",    0.65), ("bwd", 0.65), ("stop", 0.20),
    # ── Wiggle ──────────────────────────────────────────────────────────────
    ("spin_l", 0.18), ("spin_r", 0.18),
    ("spin_l", 0.18), ("spin_r", 0.18),
    ("spin_l", 0.18), ("spin_r", 0.18),
    ("stop",   0.28),
    # ── Moonwalk ────────────────────────────────────────────────────────────
    ("bwd",    1.10), ("stop", 0.35),
    ("bwd",    1.10), ("stop", 0.35),
    # ── Double finale spin ──────────────────────────────────────────────────
    ("spin_r", 1.70), ("stop", 0.18),
    ("spin_l", 1.70), ("stop", 0.18),
    # ── Rest before loop ────────────────────────────────────────────────────
    ("stop",   0.80),
]


# ── LED colour helpers ────────────────────────────────────────────────────────

def _hsv(h: float, s: float = 1.0, v: float = 0.75):
    """Return (r, g, b) 0-255 from HSV.  h in degrees."""
    h = h % 360
    hi = int(h / 60) % 6
    f  = h / 60 - int(h / 60)
    p  = v * (1 - s)
    q  = v * (1 - f * s)
    t  = v * (1 - (1 - f) * s)
    r, g, b = [(v, t, p), (q, v, p), (p, v, t),
               (p, q, v), (t, p, v), (v, p, q)][hi]
    return int(r * 255), int(g * 255), int(b * 255)


def _dance_leds(led, frame: int, move: str) -> None:
    """Per-frame LED effect; called at ~25 Hz."""
    count = led._count

    if move == "spin_l" or move == "spin_r":
        # Fast accent-colour chase in spin direction
        idx   = (frame * (1 if move == "spin_r" else -1)) % count
        led.clear()
        led.set_pixel(idx % count,               255,  30, 100)   # accent pink
        led.set_pixel((idx + count // 2) % count, 255, 100,   0)  # amber
        led.show()

    elif move == "fwd":
        # Rainbow sweep toward front
        for i in range(count):
            h = ((frame * 6) + i * (360 // count)) % 360
            led.set_pixel(i, *_hsv(h))
        led.show()

    elif move == "bwd":
        # Reverse rainbow
        for i in range(count):
            h = ((frame * -6) + i * (360 // count)) % 360
            led.set_pixel(i, *_hsv(h))
        led.show()

    else:  # stop / pause
        # Slow white breathe
        t      = frame * (2 * math.pi / 60)
        bright = int((math.sin(t) * 0.5 + 0.5) * 180 + 40)
        led.fill(bright, bright, bright)
        led.show()


# ── Motor helper ──────────────────────────────────────────────────────────────

def _apply_move(motors, move: str, speed: float) -> None:
    if   move == "fwd":    motors.forward(speed)
    elif move == "bwd":    motors.backward(speed)
    elif move == "spin_l": motors.turn_left(speed)
    elif move == "spin_r": motors.turn_right(speed)
    else:                  motors.stop()


# ── Dance loop (runs in its own thread) ───────────────────────────────────────

def _dance_loop(motors, led, stop_event: threading.Event, speed: float) -> None:
    seq_idx      = 0
    move, dur    = _SEQ[0]
    deadline     = time.monotonic() + dur
    frame        = 0

    logger.info("Dance loop running")
    while not stop_event.is_set():
        now = time.monotonic()
        if now >= deadline:
            seq_idx      = (seq_idx + 1) % len(_SEQ)
            move, dur    = _SEQ[seq_idx]
            deadline     = now + dur

        _apply_move(motors, move, speed)
        _dance_leds(led, frame, move)
        frame += 1
        time.sleep(0.04)   # ~25 Hz

    motors.stop()
    led.clear()
    logger.info("Dance loop stopped")


# ── Public API ────────────────────────────────────────────────────────────────

def start_dance(motors, led, stop_event: threading.Event,
                speed: float = 0.62) -> threading.Thread:
    """
    Launch the dance choreography thread.
    The thread runs until stop_event.set() is called.
    Returns the Thread so the caller can join() if needed.
    """
    stop_event.clear()
    t = threading.Thread(
        target=_dance_loop,
        args=(motors, led, stop_event, speed),
        daemon=True,
        name="dance",
    )
    t.start()
    return t
