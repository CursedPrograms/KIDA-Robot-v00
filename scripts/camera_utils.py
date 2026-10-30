#!/usr/bin/env python3

"""
camera_utils.py — Camera capture helpers and QR code generator.
"""

import pygame
import qrcode
from PIL import Image
from picamera2 import Picamera2

from colour_scheme import rgb


camera_error = ""      # why there's no picture: shown on the HUD, the page and the PC controller


def cam_to_surface(cam: Picamera2, w: int, h: int) -> tuple:
    """Capture a frame, rotate/resize, return (pygame.Surface, PIL.Image|None)."""
    global camera_error
    try:
        raw = cam.capture_array()
        if raw.ndim == 3 and raw.shape[2] == 4:
            raw = raw[:, :, :3]
        pil = Image.fromarray(raw).rotate(180).resize((w, h), Image.NEAREST)
        camera_error = ""
        return pygame.image.fromstring(pil.tobytes(), pil.size, "RGB"), pil
    except Exception as e:
        if not camera_error:
            print(f"Camera: no picture: {e!r}", flush=True)
        camera_error = "not started" if cam is None else str(e)[:60]
        s = pygame.Surface((w, h))
        s.fill(rgb("camera_bg"))
        return s, None


def make_qr(url: str, size: int = 130) -> pygame.Surface:
    """Generate a QR code and return it as a pygame surface."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img = img.resize((size, size), Image.LANCZOS)
    return pygame.image.fromstring(img.tobytes(), img.size, "RGB")
