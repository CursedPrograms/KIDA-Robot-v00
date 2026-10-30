#!/usr/bin/env python3

"""
keymap.py — every key and gamepad button KIDA00 takes, in one place.

Read by the robot's HUD (ui.py: H or F1 opens the keys window), the PC controller
(controller/main.py, the same keys), the web dashboard (GET /keymap, its KEYS
button) and the README:

    python scripts/keymap.py        prints the README's Controls tables

Pure data: no pygame or hardware imports, so server.py can serve it as JSON.
"""

ROBOT = "KIDA00"

# (section, [(keys, what it does), ...])
KEYBOARD = [
    ("Drive (USER mode)", [
        ("W A S D", "WASD scheme: forward, turn left, back, turn right"),
        ("W+A, W+D ...", "curve while ARC is on (inside track slows)"),
        ("Q A / W S", "QA/WS scheme: left track / right track, forward and back"),
        ("1 / 2", "WASD scheme / QA/WS tank scheme"),
        ("T", "ARC turns on / off"),
        ("X", "next speed (USER and AUTONOMOUS)"),
    ]),
    ("Modes", [
        ("TAB", "next mode: USER, AUTONOMOUS, LINE FOLLOW"),
        ("U", "USER: you drive"),
        ("O", "AUTONOMOUS: obstacle avoidance"),
        ("L", "LINE FOLLOW"),
        ("9", "MIND: the PC controller's mind drives her (only while one that can think is connected)"),
    ]),
    ("Camera", [
        ("← / →", "pan the camera left / right (FOLLOW off)"),
        ("↑", "centre the camera (FOLLOW off)"),
        ("C", "photo (USER mode)"),
        ("V", "video recording on / off (USER mode)"),
        ("F", "save the faces it sees (USER mode)"),
        ("J / N", "HELLO / DANCE, on the spot (USER mode; PC controller, buttons on her dashboard)"),
    ]),
    ("Music", [
        ("M", "play music"),
        ("SPACE", "stop music"),
    ]),
    ("Robot", [
        ("K", "wheel lock on / off (her own keyboard only, no password)"),
        ("H or F1", "this keys window"),
        ("ESC", "quit"),
    ]),
    ("PC controller only (controller/main.py)", [
        ("Backspace", "STOP: motors off in any mode, back to USER (as the STOP button and the D-pad's middle)"),
        ("Drive keys, pad, D-pad", "in any mode: driving takes over (back to USER, you drive)"),
        ("STOP / EMULATE / THEME", "the top bar: stop in any mode / her pretend self on this PC / DEFAULT, LIGHT, CUSTOM colours"),
    ]),
]

GAMEPAD = [
    ("Gamepad (on her USB or the PC's)", [
        ("Left stick", "drive (WASD scheme)"),
        ("Both sticks", "left / right track (QA/WS scheme)"),
        ("D-pad", "drive like W A S D"),
        ("Right stick ← →", "pan the camera (FOLLOW off)"),
        ("Right stick click", "centre the camera"),
        ("A", "next speed"),
        ("B", "stop: back to USER mode, motors off"),
        ("X", "photo"),
        ("Y", "ARC turns on / off"),
        ("LB / RB", "previous / next mode"),
        ("Back / Select", "save faces"),
        ("Start", "music on / off"),
    ]),
    ("ARM's joystick (raw sticks)", [
        ("Stick", "drive (WASD scheme)"),
        ("Hat", "drive like W A S D"),
        ("Trigger", "next speed (as A)"),
        ("Button 1", "stop (as B)"),
        ("Button 2", "photo (as X)"),
        ("Button 3", "ARC turns on / off (as Y)"),
    ]),
]


def sections() -> list:
    """Keyboard then gamepad, as one list for the keys windows."""
    return KEYBOARD + GAMEPAD


def as_dict() -> dict:
    """For GET /keymap (the web dashboard's KEYS panel)."""
    def conv(groups):
        return [{"title": t, "keys": [{"keys": k, "does": d} for k, d in rows]} for t, rows in groups]
    return {"robot": ROBOT, "keyboard": conv(KEYBOARD), "gamepad": conv(GAMEPAD)}


def markdown() -> str:
    """The README's Controls tables."""
    out = []
    for title, rows in sections():
        out += [f"**{title}**", "", "| Key | Does |", "| :--- | :--- |"]
        out += [f"| <kbd>{k}</kbd> | {d} |" for k, d in rows]
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")      # the arrows, on a Windows console too
    print(markdown())
