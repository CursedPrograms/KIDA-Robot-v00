#!/usr/bin/env python3

import logging
from gpiozero import Motor
import pygame

logger = logging.getLogger(__name__)


class MotorController:
    """Controls the left and right drive motors."""

    def __init__(self, left_pins: tuple = (24, 23), right_pins: tuple = (5, 6)):
        try:
            self.left  = Motor(forward=left_pins[0],  backward=left_pins[1])
            self.right = Motor(forward=right_pins[0], backward=right_pins[1])
            logger.info("Motors initialised on pins L=%s R=%s", left_pins, right_pins)
        except Exception as e:
            logger.error("Motor init failed: %s", e)
            raise

    # ── Primitives ────────────────────────────────────────────

    def stop(self) -> None:
        self.left.stop()
        self.right.stop()

    def forward(self, speed: float = 1.0) -> None:
        speed = self._clamp(speed)
        self.left.forward(speed)
        self.right.forward(speed)

    def backward(self, speed: float = 1.0) -> None:
        speed = self._clamp(speed)
        self.left.backward(speed)
        self.right.backward(speed)

    def turn_left(self, speed: float = 1.0) -> None:
        speed = self._clamp(speed)
        self.left.backward(speed)
        self.right.forward(speed)

    def turn_right(self, speed: float = 1.0) -> None:
        speed = self._clamp(speed)
        self.left.forward(speed)
        self.right.backward(speed)

    # ── Tank / independent-wheel scheme ───────────────────────

    def control_tank(self, keys, speed: float) -> tuple[bool, bool]:
        """
        QA = left wheel forward/backward
        WS = right wheel forward/backward
        Returns (left_active, right_active).
        """
        speed = self._clamp(speed)
        left_active = right_active = False

        if keys[pygame.K_q]:
            self.left.forward(speed);  left_active = True
        elif keys[pygame.K_a]:
            self.left.backward(speed); left_active = True
        else:
            self.left.stop()

        if keys[pygame.K_w]:
            self.right.forward(speed);  right_active = True
        elif keys[pygame.K_s]:
            self.right.backward(speed); right_active = True
        else:
            self.right.stop()

        return left_active, right_active

    # ── Cleanup ───────────────────────────────────────────────

    def cleanup(self) -> None:
        self.stop()
        self.left.close()
        self.right.close()
        logger.info("Motors closed")

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _clamp(speed: float) -> float:
        return max(0.0, min(1.0, speed))
