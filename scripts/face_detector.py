#!/usr/bin/env python3

"""
face_detector.py — Background thread for DeepFace gender/age analysis.
"""

import logging
import queue
import threading

from shared_state import (
    _face_results, _face_lock,
    _face_frame_q, _face_enabled, _deepface_ok,
    _robot_state, _robot_state_lock,
)

logger = logging.getLogger("kida.face")


def _face_worker() -> None:
    try:
        from deepface import DeepFace
        import numpy as np
        _deepface_ok.set()
        logger.info("DeepFace loaded — face mode ready")
    except ImportError:
        logger.warning("DeepFace not installed — face mode unavailable")
        return

    while True:
        _face_enabled.wait()

        try:
            pil_img = _face_frame_q.get(timeout=1.0)
        except queue.Empty:
            continue

        if not _face_enabled.is_set():
            continue

        try:
            arr     = np.array(pil_img)
            results = DeepFace.analyze(arr, actions=["gender", "age"],
                                       enforce_detection=False, silent=True)
            if isinstance(results, dict):
                results = [results]

            parsed = []
            for r in results:
                gs = r.get("gender", {})
                if isinstance(gs, dict) and gs:
                    gender = max(gs, key=gs.get)
                    conf   = round(gs.get(gender, 0), 1)
                elif isinstance(gs, str):
                    gender, conf = gs, 100.0
                else:
                    gender, conf = "?", 0.0
                parsed.append({
                    "gender": gender, "conf": conf,
                    "age":    int(r.get("age", 0)),
                    "region": r.get("region", {}),
                })

            with _face_lock:
                _face_results[:] = parsed
            with _robot_state_lock:
                _robot_state["face_count"] = len(parsed)

        except Exception as e:
            logger.debug("Face analysis error: %s", e)


def start_face_thread() -> threading.Thread:
    t = threading.Thread(target=_face_worker, daemon=True)
    t.start()
    return t
