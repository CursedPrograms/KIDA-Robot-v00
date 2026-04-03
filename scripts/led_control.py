import threading
import logging
import numpy
import spidev

logger = logging.getLogger(__name__)

_LED_TYPES = {
    "RGB": (1, 0, 2),
    "RBG": (1, 2, 0),
    "GRB": (0, 1, 2),  # WS2812 default
    "GBR": (2, 1, 0),
    "BRG": (2, 0, 1),
    "BGR": (0, 2, 1),
}


class SPI_WS2812_LEDStrip:
    """
    WS2812 LED strip driven over SPI.
    Default sequence is GRB (standard WS2812).
    """

    def __init__(
        self,
        count: int = 8,
        brightness: int = 255,
        sequence: str = "GRB",
        bus: int = 0,
        device: int = 0,
    ):
        offsets = _LED_TYPES.get(sequence.upper(), _LED_TYPES["GRB"])
        self._r_off, self._g_off, self._b_off = offsets

        self._count      = count
        self._brightness = max(0, min(255, brightness))
        self._color      = [0] * (count * 3)
        self._lock       = threading.Lock()
        self._ready      = False

        try:
            self._spi = spidev.SpiDev()
            self._spi.open(bus, device)
            self._spi.mode = 0
            self._ready    = True
            logger.info("LED strip ready — %d LEDs, bus=%d dev=%d", count, bus, device)
        except OSError as e:
            logger.error("SPI init failed (%s). Check /boot/config.txt and raspi-config.", e)

        self.clear()

    # ── Public API ────────────────────────────────────────────

    @property
    def ready(self) -> bool:
        return self._ready

    def set_pixel(self, index: int, r: int, g: int, b: int) -> None:
        if not 0 <= index < self._count:
            return
        scale = self._brightness / 255
        p = [0, 0, 0]
        p[self._r_off] = round(r * scale)
        p[self._g_off] = round(g * scale)
        p[self._b_off] = round(b * scale)
        base = index * 3
        self._color[base:base + 3] = p

    def fill(self, r: int, g: int, b: int) -> None:
        for i in range(self._count):
            self.set_pixel(i, r, g, b)

    def set_all_led_color(self, r: int, g: int, b: int) -> None:
        """Alias for fill() — fills all LEDs and pushes to strip."""
        self.fill(r, g, b)
        self.show()

    def clear(self) -> None:
        self.fill(0, 0, 0)
        self.show()

    def show(self) -> None:
        if not self._ready:
            return
        with self._lock:
            d  = numpy.array(self._color, dtype=numpy.uint8)
            tx = numpy.zeros(len(d) * 8, dtype=numpy.uint8)
            for bit in range(8):
                tx[7 - bit::8] = ((d >> bit) & 1) * 0x78 + 0x80
            speed = int(8 / 1.25e-6)
            self._spi.xfer(tx.tolist(), speed)

    def led_close(self) -> None:
        self.clear()
        self._spi.close()
        logger.info("LED strip closed")

    # ── Effects ───────────────────────────────────────────────

    def rhythm_wave(self, frame: int) -> None:
        """
        Animated rainbow wave — call once per frame while music is playing.
        Commits the frame to the strip automatically.
        """
        colors = [
            (255, 0,   0),
            (0,   255, 0),
            (0,   0,   255),
            (255, 255, 0),
            (255, 0,   255),
            (0,   255, 255),
        ]
        base = (frame // 20) % len(colors)

        for i in range(self._count):
            phase  = (frame + i * 6) % (self._count * 12)
            half   = self._count * 6
            bright = phase / half if phase < half else (self._count * 12 - phase) / half
            color  = colors[(base + i) % len(colors)]
            self.set_pixel(i, *(round(c * bright) for c in color))

        self.show()

    # kept for backwards compatibility
    def check_spi_state(self) -> int:
        return int(self._ready)
