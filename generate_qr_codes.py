#!/usr/bin/env python3

"""
generate_qr_codes.py — Export QR code PNGs for every KIDA robot action.

Usage:
  python generate_qr_codes.py            # saves to ./qrcodes/
  python generate_qr_codes.py ./my/dir   # saves to a custom directory

Requires:  pip install qrcode[pil]

Each PNG contains the QR code with the action label below it.
Print them out, laminate, and place them anywhere the robot's camera
can see — the robot reacts as long as the code stays in frame.

Hold actions  (robot moves continuously while QR is visible):
  forward · backward · left · right

One-shot actions  (fire once per new detection):
  play_music · stop_music · next_song
  mode_user · mode_autonomous · mode_line
  light_paint · stop
"""

import os
import sys


ACTIONS = {
    # ── Movement hold commands ──────────────────────────────────────────────────
    "forward":          ("FORWARD",         "▲"),
    "backward":         ("BACKWARD",        "▼"),
    "left":             ("TURN LEFT",       "◀"),
    "right":            ("TURN RIGHT",      "▶"),
    # ── One-shot commands ───────────────────────────────────────────────────────
    "play_music":       ("PLAY MUSIC",      "♪"),
    "stop_music":       ("STOP MUSIC",      "■"),
    "next_song":        ("NEXT SONG",       "▶▶"),
    "mode_user":        ("USER MODE",       "👤"),
    "mode_autonomous":  ("AUTO MODE",       "🤖"),
    "mode_line":        ("LINE MODE",       "〰"),
    "light_paint":      ("LIGHT PAINT",     "✦"),
    "dance":            ("DANCE",           "♫"),
    "sleep":            ("SLEEP",          "💤"),
    "wake":             ("WAKE",           "☀"),
    "stop":             ("STOP / HALT",     "✖"),
}

_PREFIX = "KIDA:"

_FONT_PATHS_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
]
_FONT_PATHS_REG = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/calibri.ttf",
]


def _load_font(paths, size):
    from PIL import ImageFont
    for fp in paths:
        try:
            return ImageFont.truetype(fp, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _make_qr(action: str, label: str, glyph: str, out_dir: str) -> str:
    import qrcode
    from PIL import Image, ImageDraw

    data = _PREFIX + action

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    W, H = qr_img.size
    pad  = 70          # extra height below QR for the label
    canvas = Image.new("RGB", (W, H + pad), "white")
    canvas.paste(qr_img, (0, 0))

    draw       = ImageDraw.Draw(canvas)
    font_label = _load_font(_FONT_PATHS_BOLD, 22)
    font_data  = _load_font(_FONT_PATHS_REG,  13)

    # Centred label line
    bbox = draw.textbbox((0, 0), label, font=font_label)
    tw   = bbox[2] - bbox[0]
    draw.text(((W - tw) // 2, H + 8), label, fill="black", font=font_label)

    # Centred data string in grey
    sbbox = draw.textbbox((0, 0), data, font=font_data)
    sw    = sbbox[2] - sbbox[0]
    draw.text(((W - sw) // 2, H + 40), data, fill="#888888", font=font_data)

    out_path = os.path.join(out_dir, f"qr_{action}.png")
    canvas.save(out_path, "PNG")
    return out_path


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "qrcodes"
    os.makedirs(out_dir, exist_ok=True)

    try:
        import qrcode  # noqa: F401
    except ImportError:
        print("Error: qrcode library not found.")
        print("  pip install qrcode[pil]")
        sys.exit(1)

    print(f"Generating {len(ACTIONS)} QR codes → ./{out_dir}/\n")

    hold_cmds    = {"forward", "backward", "left", "right"}
    for action, (label, glyph) in ACTIONS.items():
        kind = "HOLD" if action in hold_cmds else "SHOT"
        path = _make_qr(action, label, glyph, out_dir)
        print(f"  [{kind}]  {os.path.basename(path):<34}  {_PREFIX}{action}")

    print(f"\nDone — {len(ACTIONS)} files saved to ./{out_dir}/")
    print("\nHOLD = robot moves while QR is in frame")
    print("SHOT = action fires once per new detection")


if __name__ == "__main__":
    main()
