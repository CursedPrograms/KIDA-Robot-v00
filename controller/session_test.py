#!/usr/bin/env python3

"""
session_test.py — drives the controller like a person, on her pretend self (fake_kida00.py),
and checks every response (fleet TODO section 13's session test). No window, no robot:

    venv/Scripts/python session_test.py        (Windows)    venv/bin/python session_test.py

Keys held and tapped, clicks on her buttons and the PC's (EMULATE / THEME / STOP), the D-pad held
with the mouse, a command she loses on purpose (the controller sends it again), driving taking
over from AUTONOMOUS and LINE. Screenshots of each THEME go to session_test_*.png (not in git).
"""

import os
import sys
import tempfile
import time

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "scripts"))

import pygame

import controller_kit as kit
import hud_layout

W, H = 1100, 720                       # the window on the dummy driver (MIN_W x MIN_H)
LAY = hud_layout.compute_layout(W, H)

# The PC's buttons, as main.py's relayout() places them
_x, PC = W - 420, {}
for _name, _w in (("THEME", 150), ("EMULATE", 112), ("STOP", 84)):
    _x -= _w
    PC[_name] = pygame.Rect(_x, (LAY["TOP_H"] - 30) // 2, _w - 8, 30)

held = set()          # keys held down now
mouse = [W // 2, H // 2]
queue = []            # events for the next frame
results = []


def tap(key):
    queue.extend([pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, unicode="", scancode=0),
                  pygame.event.Event(pygame.KEYUP, key=key, mod=0, unicode="", scancode=0)])


def press(pos):
    mouse[:] = pos
    queue.append(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=tuple(pos)))


def release():
    queue.append(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=tuple(mouse)))


def click(pos):
    press(pos)
    release()


class Keys:
    def __getitem__(self, k):
        return k in held


def script(robot):
    """A generator: each yield is one frame. yield from wait_for(...) checks a response."""
    def wait_for(what, cond, frames=75):          # 75 frames = 3 s at 25 fps
        for _ in range(frames):
            yield
            if cond():
                results.append((True, what))
                return
        results.append((False, what + f"   (status: mode {robot.state['mode']}, dir {robot.state['direction']}, "
                                       f"speed {robot.state['speed_idx']}, scheme {robot.state['ctrl_scheme']})"))

    def frames(n):
        for _ in range(n):
            yield

    st = robot.state
    yield from frames(10)
    yield from wait_for("starts on her pretend self (no robot given)", lambda: st["frame"] > 0)

    tap(pygame.K_x); yield; tap(pygame.K_x)
    yield from wait_for("X X: speed 3", lambda: st["speed_idx"] == 2)
    tap(pygame.K_2)
    yield from wait_for("2: QA/WS scheme", lambda: st["ctrl_scheme"] == 2)
    tap(pygame.K_1)
    yield from wait_for("1: WASD scheme", lambda: st["ctrl_scheme"] == 1)
    tap(pygame.K_t)
    yield from wait_for("T: ARC off", lambda: st["arc_turn"] is False)
    tap(pygame.K_t)
    yield from wait_for("T: ARC on", lambda: st["arc_turn"] is True)

    x0 = robot.x
    held.add(pygame.K_w)
    yield from wait_for("W held: forward", lambda: st["direction"] == "FORWARD")
    yield from frames(20)
    held.discard(pygame.K_w)
    yield from wait_for("W let go: stops", lambda: st["direction"] == "STOPPED")
    results.append((robot.x != x0, f"she moved ({x0:.0f} -> {robot.x:.0f} cm)"))

    held.update({pygame.K_w, pygame.K_d})
    yield from wait_for("W+D, ARC on: curves right", lambda: st["direction"].startswith("FWD") or "RIGHT" in st["direction"])
    held.clear()
    yield from wait_for("let go: stops", lambda: st["direction"] == "STOPPED")

    tap(pygame.K_o)
    yield from wait_for("O: AUTONOMOUS", lambda: st["mode"] == "AUTONOMOUS")
    yield from frames(15)
    held.add(pygame.K_s)
    yield from wait_for("S held in AUTONOMOUS: driving takes over (USER, backward)",
                        lambda: st["mode"] == "USER" and st["direction"] == "BACKWARD")
    held.clear()
    yield from wait_for("let go: stops", lambda: st["direction"] == "STOPPED")

    tap(pygame.K_l)
    yield from wait_for("L: LINE FOLLOW", lambda: st["mode"] == "LINE")
    tap(pygame.K_BACKSPACE)
    yield from wait_for("Backspace: STOP in LINE (USER, stopped)", lambda: st["mode"] == "USER" and st["direction"] == "STOPPED")

    tap(pygame.K_TAB)
    yield from wait_for("TAB: next mode (AUTONOMOUS)", lambda: st["mode"] == "AUTONOMOUS")
    click(PC["STOP"].center)
    yield from wait_for("STOP button in AUTONOMOUS: USER, stopped", lambda: st["mode"] == "USER" and st["direction"] == "STOPPED")

    click(LAY["tabs"][2].center)
    yield from wait_for("LINE FOLLOW tab", lambda: st["mode"] == "LINE")
    press(LAY["dpad"]["forward"].center)
    yield from wait_for("D-pad held in LINE: takes over, forward", lambda: st["mode"] == "USER" and st["direction"] == "FORWARD")
    release()
    yield from wait_for("D-pad let go: stops", lambda: st["direction"] == "STOPPED")
    click(LAY["tabs"][1].center)
    yield from wait_for("AUTONOMOUS tab", lambda: st["mode"] == "AUTONOMOUS")
    click(LAY["dpad"]["stop"].center)
    yield from wait_for("D-pad's middle in AUTONOMOUS: STOP (USER)", lambda: st["mode"] == "USER")

    robot.drop = 1
    tap(pygame.K_o)
    yield from wait_for("O, and she loses it: sent again until she's AUTONOMOUS", lambda: st["mode"] == "AUTONOMOUS")
    tap(pygame.K_u)
    yield from wait_for("U: USER", lambda: st["mode"] == "USER")
    robot.drop = 1
    click(LAY["spd_dots"][3].center)
    yield from wait_for("speed 4 button, lost once: sent again", lambda: st["speed_idx"] == 3)

    tap(pygame.K_v)
    yield from wait_for("V: recording", lambda: st["video_rec"] is True)
    tap(pygame.K_v)
    yield from wait_for("V: recording off", lambda: st["video_rec"] is False)
    tap(pygame.K_m)
    yield from wait_for("M: music on", lambda: st["music_playing"] is True)
    tap(pygame.K_SPACE)
    yield from wait_for("Space: music off", lambda: st["music_playing"] is False)
    click(LAY["btn_play"].center)
    yield from wait_for("PLAY button: music on", lambda: st["music_playing"] is True)
    click(LAY["btn_play"].center)
    yield from wait_for("PLAY button again: music off", lambda: st["music_playing"] is False)

    tap(pygame.K_LEFT)
    yield from wait_for("Left arrow: camera pans left", lambda: robot.cam_pan > 0)
    tap(pygame.K_UP)
    yield from wait_for("Up arrow: camera centred", lambda: robot.cam_pan == 0)

    for theme in ("LIGHT", "CUSTOM", "DEFAULT"):
        click(PC["THEME"].center)
        yield from frames(4)
        shot = os.path.join(_HERE, f"session_test_{theme.lower()}.png")
        pygame.image.save(pygame.display.get_surface(), shot)
        results.append((kit.Settings(SETTINGS).theme == theme, f"THEME button: {theme} (saved; {os.path.basename(shot)})"))

    click(PC["EMULATE"].center)
    yield from frames(5)
    results.append((robot._servers and not robot._stop.is_set(), "EMULATE with no robot to go back to: stays emulated"))

    tap(pygame.K_ESCAPE)
    for _ in range(50):
        yield


SETTINGS = os.path.join(tempfile.mkdtemp(), "controller_settings.json")   # not this PC's own THEME


def main():
    kit.Settings.__init__.__defaults__ = (SETTINGS,)
    import main as controller
    import fake_kida00

    made = []
    real_fake = fake_kida00.FakeKida

    class Watched(real_fake):            # the fake main.py starts for EMULATE, kept for the script
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            made.append(self)
    fake_kida00.FakeKida = Watched

    steps = {"gen": None}
    real_get = pygame.event.get

    def get(*a, **k):
        real_get()                       # keep SDL's own queue empty
        if steps["gen"] is None and made:
            steps["gen"] = script(made[0])
        if steps["gen"] is not None:
            try:
                next(steps["gen"])
            except StopIteration:
                queue.append(pygame.event.Event(pygame.QUIT))
        out, queue[:] = list(queue), []
        return out

    pygame.event.get = get
    pygame.key.get_pressed = lambda: Keys()
    pygame.key.get_focused = lambda: True
    pygame.mouse.get_pos = lambda: tuple(mouse)
    sys.argv = ["main.py"]
    t0 = time.monotonic()
    controller.run_controller()

    ok = sum(1 for r in results if r[0])
    for good, what in results:
        print(("  ok   " if good else "  FAIL ") + what)
    print(f"{ok} / {len(results)} as expected  ({time.monotonic() - t0:.0f} s)")
    if made and made[0].heard:
        print("she heard the last stop:", made[0].heard[-1] == "stop")
    sys.exit(0 if ok == len(results) else 1)


if __name__ == "__main__":
    main()
