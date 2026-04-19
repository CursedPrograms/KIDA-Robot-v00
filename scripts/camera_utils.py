"""
camera_utils.py — Camera capture helpers and QR code generator.
"""

import pygame
import qrcode
from PIL import Image
from picamera2 import Picamera2


def cam_to_surface(cam: Picamera2, w: int, h: int) -> tuple:
    """Capture a frame, rotate/resize, return (pygame.Surface, PIL.Image|None)."""
    try:
        raw = cam.capture_array()
        if raw.ndim == 3 and raw.shape[2] == 4:
            raw = raw[:, :, :3]
        pil = Image.fromarray(raw, "RGB").rotate(180).resize((w, h), Image.NEAREST)
        return pygame.image.fromstring(pil.tobytes(), pil.size, "RGB"), pil
    except Exception:
        s = pygame.Surface((w, h))
        s.fill((8, 10, 16))
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
