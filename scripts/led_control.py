import threading
import numpy
import spidev

class SPI_WS2812_LEDStrip:
    def __init__(self, count=8, brightness=255, sequence='GRB', bus=0, device=0):
        self.set_led_type(sequence)
        self.set_led_count(count)
        self.set_led_brightness(brightness)
        self.led_begin(bus, device)
        self.set_all_led_color(0, 0, 0)
        self.lock = threading.Lock()

    def set_led_type(self, rgb_type):
        led_types = ['RGB', 'RBG', 'GRB', 'GBR', 'BRG', 'BGR']
        offsets = [0x06, 0x09, 0x12, 0x21, 0x18, 0x24]
        try:
            idx = led_types.index(rgb_type)
            offset = offsets[idx]
            self.led_red_offset = (offset >> 4) & 3
            self.led_green_offset = (offset >> 2) & 3
            self.led_blue_offset = offset & 3
        except ValueError:
            self.led_red_offset, self.led_green_offset, self.led_blue_offset = 1, 0, 2

    def set_led_count(self, count):
        self.led_count = count
        self.led_color = [0] * (count * 3)
        self.led_original_color = [0] * (count * 3)

    def set_led_brightness(self, brightness):
        self.led_brightness = brightness
        for i in range(self.led_count):
            self.set_led_rgb_data(i, [0, 0, 0])

    def set_ledpixel(self, index, r, g, b):
        p = [0, 0, 0]
        p[self.led_red_offset] = round(r * self.led_brightness / 255)
        p[self.led_green_offset] = round(g * self.led_brightness / 255)
        p[self.led_blue_offset] = round(b * self.led_brightness / 255)
        for i, color in enumerate((r, g, b)):
            self.led_original_color[index * 3 + i] = color
        for i in range(3):
            self.led_color[index * 3 + i] = p[i]

    def set_led_rgb_data(self, index, color):
        self.set_ledpixel(index, *color)

    def set_all_led_color(self, r, g, b):
        for i in range(self.led_count):
            self.set_ledpixel(i, r, g, b)
        self.show()

    def led_begin(self, bus=0, device=0):
        self.bus, self.device = bus, device
        try:
            self.spi = spidev.SpiDev()
            self.spi.open(bus, device)
            self.spi.mode = 0
            self.led_init_state = 1
        except OSError:
            print("SPI init failed. Check config.txt and raspi-config.")
            self.led_init_state = 0

    def check_spi_state(self):
        return self.led_init_state

    def show(self):
        d = numpy.array(self.led_color).ravel()
        tx = numpy.zeros(len(d) * 8, dtype=numpy.uint8)
        for ibit in range(8):
            tx[7 - ibit::8] = ((d >> ibit) & 1) * 0x78 + 0x80
        if self.led_init_state:
            speed = int(8 / (1.25e-6 if self.bus == 0 else 1.0e-6))
            self.spi.xfer(tx.tolist(), speed)

    def led_close(self):
        self.set_all_led_color(0, 0, 0)
        self.spi.close()

    def rhythm_wave(self, frame):
        colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255)]
        count = self.led_count
        base = (frame // 20) % len(colors)
        self.set_all_led_color(0, 0, 0)
        for i in range(count):
            phase = (frame + i * 6) % (count * 12)
            bright = phase / (count * 6) if phase < count * 6 else (count * 12 - phase) / (count * 6)
            color = colors[(base + i) % len(colors)]
            scaled = [int(c * bright) for c in color]
            self.set_ledpixel(i, *scaled)
        self.show()
