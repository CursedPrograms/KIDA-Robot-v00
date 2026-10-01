#!/usr/bin/env python3

"""
colour_scheme.py — KIDA's UI colours, loaded from colour_scheme.xml at the
repo root. Everything that draws asks for its colours by role name instead
of hardcoding them, so editing that one file restyles all three screens:

  rgb("accent")   → (255, 30, 100)   pygame HUD (render_helpers.py), used by
                                     both scripts/ui.py and controller/main.py
  css()           → ":root{...}"     web dashboard, served by server.py as
                                     /colour_scheme.css over styles.css's defaults

Pure Python — no pygame / hardware imports, so the controller and Flask can use it.
"""

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger("kida.colours")

SCHEME_PATH = Path(__file__).resolve().parent.parent / "colour_scheme.xml"

# Fallback for any role missing from colour_scheme.xml (or if the file is
# missing/unreadable). Keep in sync with the XML and styles.css's :root.
DEFAULTS = {
    "background":      "#08090D",
    "grid":            "#0E080C",
    "panel":           "#0E0F16",
    "bottom_bar":      "#0A0B10",
    "camera_bg":       "#080A0E",
    "border":          "#202334",
    "divider":         "#161824",
    "track":           "#121420",
    "led_off":         "#1C1E2C",
    "text":            "#E6E6E1",
    "text_sec":        "#82847D",
    "text_dim":        "#3C3E4B",
    "accent":          "#FF1E64",
    "button_hover_bg": "#160A12",
    "danger_bg":       "#1C0A0A",
    "green":           "#1DC878",
    "blue":            "#378ADD",
    "amber":           "#FFA028",
    "red":             "#E24B4A",
    "teal":            "#14C8AA",
    "purple":          "#A050F0",
}


def _parse_hex(value: str) -> tuple:
    value = (value or "").strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"expected #RRGGBB, got {value!r}")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def load_scheme(path: Path = SCHEME_PATH) -> dict:
    """Return {role: (r, g, b)}, merging colour_scheme.xml over DEFAULTS."""
    scheme = {name: _parse_hex(value) for name, value in DEFAULTS.items()}

    if not path.exists() or path.stat().st_size == 0:
        return scheme

    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as e:
        logger.warning("Could not read %s (%s) — using default colours", path.name, e)
        return scheme

    for el in root.iter("colour"):
        name = el.get("name")
        if not name:
            continue
        try:
            scheme[name] = _parse_hex(el.get("value", ""))
        except ValueError as e:
            logger.warning("%s: bad value for '%s' (%s) — keeping default", path.name, name, e)
    return scheme


_scheme = load_scheme()


def rgb(name: str) -> tuple:
    """(r, g, b) for a role, e.g. rgb("background")."""
    return _scheme[name]


def hex_colour(name: str) -> str:
    return "#{:02X}{:02X}{:02X}".format(*_scheme[name])


def css() -> str:
    """The scheme as CSS custom properties (text_dim → --text-dim), re-read
    from disk each call so a page reload shows edits without restarting KIDA."""
    scheme = load_scheme()
    body = "\n".join(
        "  --{}: #{:02X}{:02X}{:02X};".format(name.replace("_", "-"), *c)
        for name, c in scheme.items()
    )
    return f"/* Generated from colour_scheme.xml */\n:root {{\n{body}\n}}\n"
