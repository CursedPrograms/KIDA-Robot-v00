#!/usr/bin/env python3

"""
sleep.py — Low-power idle mode for KIDA.

When sleep mode is active (shared _sleep_active event is set):
  • Camera capture is skipped in the main loop.
  • Face detection is paused (_face_enabled cleared).
  • Motors remain stopped.
  • LEDs show a slow amber breathing pattern via sleep_breathe().
  • The pygame display shows a minimal dark sleep screen.

Wake triggers (handled in ui.py):
  • QR code  KIDA:wake
  • Web POST /wake
  • Any local keypress while sleep screen is shown

This module provides only the LED effect and the sleep-screen render.
The main loop in ui.py gates camera and drive logic on _sleep_active.
"""

import math
import logging

logger = logging.getLogger("kida.sleep")


def sleep_breathe(led, frame: int) -> None:
    """
    Slow amber breathing effect ~0.25 Hz (full cycle ≈ 4 s at 25 fps).
    Call once per main-loop frame when sleep mode is active.
    Commits to the LED strip automatically.
    """
    t     = frame * (2 * math.pi / 100)    # 100 frames → 1 cycle at 25 fps
    scale = math.sin(t) * 0.5 + 0.5        # 0.0 → 1.0
    r     = int(scale * 110 + 6)
    g     = int(scale * 38  + 2)
    b     = 0
    led.fill(r, g, b)
    led.show()


def render_sleep_screen(screen, font_hud, font_mono, W: int, H: int,
                         frame: int) -> None:
    """
    Draw a minimal sleep screen on the pygame display.
    Call instead of the normal render pipeline when sleep is active.
    """
    import pygame

    screen.fill((4, 5, 8))

    # Slow-pulse opacity for the text
    t       = frame * (2 * math.pi / 100)
    alpha   = int((math.sin(t) * 0.5 + 0.5) * 180 + 60)

    lbl = font_hud.render("KIDA  SLEEPING", True, (alpha, int(alpha * 0.5), 0))
    sub = font_mono.render("show KIDA:wake QR or press any key", True,
                            (alpha // 3, int(alpha * 0.17), 0))

    screen.blit(lbl, lbl.get_rect(center=(W // 2, H // 2 - 18)))
    screen.blit(sub, sub.get_rect(center=(W // 2, H // 2 + 22)))
