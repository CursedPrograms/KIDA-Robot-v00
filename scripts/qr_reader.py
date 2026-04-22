#!/usr/bin/env python3

"""
qr_reader.py — Background QR code detection for KIDA QR drive mode.

Reads PIL frames from _qr_frame_q (fed by the main camera loop whenever
QR mode is active), decodes KIDA:<action> codes, and updates
_qr_state["action"].  When nothing is visible for > 0.5 s the action
is cleared so the main loop stops hold-commands.

Hold actions (motor runs while QR is visible):
  KIDA:forward  KIDA:backward  KIDA:left  KIDA:right

One-shot actions (fire once when QR first appears or action changes):
  KIDA:play_music    KIDA:stop_music   KIDA:next_song
  KIDA:mode_user     KIDA:mode_autonomous   KIDA:mode_line
  KIDA:light_paint   KIDA:stop

Decoder priority: pyzbar → cv2.QRCodeDetector.
"""

import logging
import threading
import time

logger = logging.getLogger("kida.qr")

HOLD_ACTIONS    = frozenset({"forward", "backward", "left", "right"})
ONESHOT_ACTIONS = frozenset({
    "play_music", "stop_music", "next_song",
    "mode_user", "mode_autonomous", "mode_line",
    "light_paint", "stop",
    "dance", "sleep", "wake",
})
_VALID_ACTIONS = HOLD_ACTIONS | ONESHOT_ACTIONS
_PREFIX        = "KIDA:"
_GONE_TIMEOUT  = 0.5   # seconds before action clears after last good decode


# ── Decoder factory ────────────────────────────────────────────────────────────

def _build_decoder():
    """Return decode(pil_img) -> action_str | None. Tries pyzbar then cv2."""
    try:
        from pyzbar import pyzbar
        import numpy as np

        def _decode_pyzbar(pil_img):
            arr = np.array(pil_img.convert("L"))
            for code in pyzbar.decode(arr):
                data = code.data.decode("utf-8", errors="ignore")
                if data.startswith(_PREFIX):
                    action = data[len(_PREFIX):]
                    if action in _VALID_ACTIONS:
                        return action
            return None

        logger.info("QR reader: using pyzbar")
        return _decode_pyzbar

    except ImportError:
        pass

    try:
        import cv2
        import numpy as np
        _det = cv2.QRCodeDetector()

        def _decode_cv2(pil_img):
            arr = np.array(pil_img.convert("RGB"))[:, :, ::-1]  # RGB → BGR
            val, _, _ = _det.detectAndDecode(arr)
            if val and val.startswith(_PREFIX):
                action = val[len(_PREFIX):]
                if action in _VALID_ACTIONS:
                    return action
            return None

        logger.info("QR reader: using OpenCV QRCodeDetector")
        return _decode_cv2

    except ImportError:
        logger.error("QR reader: no library found — install pyzbar or opencv-python")
        return None


# ── Worker thread ──────────────────────────────────────────────────────────────

def _worker():
    from shared_state import _qr_frame_q, _qr_state, _qr_lock, _qr_enabled

    decode = _build_decoder()
    if decode is None:
        return

    last_seen = 0.0

    while True:
        _qr_enabled.wait()          # block until QR mode is activated

        try:
            pil_img = _qr_frame_q.get(timeout=0.3)
        except Exception:
            if time.monotonic() - last_seen > _GONE_TIMEOUT:
                with _qr_lock:
                    _qr_state["action"] = ""
            continue

        action = decode(pil_img)
        now    = time.monotonic()

        with _qr_lock:
            if action:
                _qr_state["action"] = action
                last_seen = now
            elif now - last_seen > _GONE_TIMEOUT:
                _qr_state["action"] = ""


def start_qr_thread():
    t = threading.Thread(target=_worker, daemon=True, name="qr-reader")
    t.start()
    return t
