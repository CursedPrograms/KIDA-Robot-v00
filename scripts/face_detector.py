#!/usr/bin/env python3

"""
face_detector.py — Background face detection worker.
Tries DeepFace first; falls back to OpenCV Haar cascades if unavailable.
Reads PIL frames from _face_frame_q, writes results to _face_results.
"""

import logging
import threading

import numpy as np

from shared_state import (
    _face_frame_q, _face_enabled, _deepface_ok,
    _face_results, _face_lock,
    _robot_state, _robot_state_lock,
)

logger = logging.getLogger("kida.face")


def _face_worker() -> None:
    use_deepface = False
    _DeepFace    = None
    _cascade     = None

    try:
        from deepface import DeepFace
        _DeepFace    = DeepFace
        use_deepface = True
        _deepface_ok.set()
        logger.info("DeepFace loaded OK")
    except Exception:
        try:
            import cv2
            _cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
            logger.warning("DeepFace unavailable — using OpenCV Haar cascades")
        except Exception as e:
            logger.error("No face backend available: %s", e)
            return

    while True:
        _face_enabled.wait()
        try:
            pil_img = _face_frame_q.get(timeout=1.0)
        except Exception:
            continue

        try:
            arr = np.array(pil_img.convert("RGB"))

            if use_deepface:
                raw = _DeepFace.analyze(
                    arr, actions=["gender", "age"],
                    enforce_detection=False, silent=True,
                )
                if not isinstance(raw, list):
                    raw = [raw]
                results = []
                for face in raw:
                    gender_stats = face.get("gender", {})
                    gender = max(gender_stats, key=gender_stats.get) if gender_stats else "Unknown"
                    conf   = float(gender_stats.get(gender, 0.0))
                    reg    = face.get("region", {})
                    results.append({
                        "gender": gender,
                        "age":    int(face.get("age", 0)),
                        "conf":   conf,
                        "region": {
                            "x": reg.get("x", 0), "y": reg.get("y", 0),
                            "w": reg.get("w", 0), "h": reg.get("h", 0),
                        },
                    })
            else:
                import cv2
                gray  = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
                faces = _cascade.detectMultiScale(gray, 1.1, 5, minSize=(30, 30))
                results = [
                    {
                        "gender": "Unknown", "age": 0, "conf": 0.0,
                        "region": {"x": int(x), "y": int(y), "w": int(w), "h": int(h)},
                    }
                    for (x, y, w, h) in (faces if len(faces) else [])
                ]

            with _face_lock:
                _face_results[:] = results
            with _robot_state_lock:
                _robot_state["face_count"] = len(results)

        except Exception as e:
            logger.error("Face detection error: %s", e)


def start_face_thread() -> None:
    t = threading.Thread(target=_face_worker, daemon=True, name="face-worker")
    t.start()
    logger.info("Face detection thread started")
