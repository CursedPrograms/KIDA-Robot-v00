#!/usr/bin/env python3

"""
main.py — KIDA v00 remote controller.

Runs on a separate PC (no picamera2 / gpiozero / LEDs — see requirements.txt)
and renders exactly the same window as the robot's scripts/ui.py: the same
layout (hud_layout.py) and the same drawing code (render_helpers.py), imported
straight from ../scripts. Only the data source differs — camera frames, stats
and state come from the robot's Flask server and every key/click is sent back
as the same command string ui.py's command processor understands.

Usage:
    python main.py <robot-ip-or-url> [--port 5003] [--fullscreen] [--emulate]
    ROBOT_URL=http://192.168.1.50:5003 python main.py
    python main.py                       no robot: EMULATE, her pretend self on this PC (fake_kida00.py)

On top of her own window, the PC's (fleet TODO section 13): EMULATE / THEME / STOP along the top
bar, a drive input in any mode takes over (back to USER, you drive), STOP (the button, Backspace,
the D-pad's middle) stops her in any mode, and settings (mode, speed, scheme, ARC, REC, music) are
sent again until her status says so.
"""

import argparse
import io
import os
import sys
import time
from types import SimpleNamespace
from urllib.parse import urlparse

_HERE        = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.join(os.path.dirname(_HERE), "scripts")
sys.path.insert(0, _SCRIPTS_DIR)   # hud_layout, render_helpers, mode_control, drive_mix, gamepad

# Keep reading the gamepad while another window has focus (e.g. a browser
# showing the camera) — must be set before pygame initialises SDL
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")

import pygame

import hud_layout
import keymap
from mode_control   import Mode
import render_helpers as rh             # THEME swaps its colours (on this PC only)
from render_helpers import (
    hline, vline, txt, btn,
    render_camera, render_info_strip, render_top_bar,
    render_left_panel, render_right_panel, render_bottom_bar,
    render_joystick, joystick_value, render_keymap,
    build_background,
)
from drive_mix      import keys_to_wheels, stick_to_wheels, tank_sticks_to_wheels, wheels_to_command
from gamepad        import Gamepad, button_commands
from remote_client  import RemoteClient
import mind_panel                       # scripts/mind_panel.py: her mind's thinking, as in the other controllers
from drive_mind     import DriveMind    # her MIND mode: this PC drives her when it can think
import controller_kit as kit            # controller/controller_kit.py: themes, settings that stick (every robot's)

APP_NAME     = "KIDA — Remote Controller"
HEARTBEAT_S  = 0.25   # the robot stops a remote drive it hasn't heard for 0.8 s
CAM_PAN_S    = 0.1    # how often the right stick sends a camera pan
MIN_W, MIN_H = 1100, 720
FAKE_URL     = "http://127.0.0.1:5003"   # EMULATE: fake_kida00.py

# THEME: render_helpers' colour names and their roles in colour_scheme.xml
COLOUR_ROLES = {
    "BG": "background", "GRID": "grid", "PANEL": "panel", "BOT_BG": "bottom_bar", "CAM_BG": "camera_bg",
    "BORDER": "border", "DIVIDER": "divider", "TRACK": "track", "LED_OFF": "led_off",
    "PRI": "text", "SEC": "text_sec", "DIM": "text_dim", "ACCENT": "accent",
    "HOVER_BG": "button_hover_bg", "DANGER_BG": "danger_bg", "GREEN": "green", "BLUE": "blue",
    "AMBER": "amber", "RED": "red", "TEAL": "teal", "PURPLE": "purple",
}
_ORIGINAL = {name: getattr(rh, name) for name in COLOUR_ROLES}   # DEFAULT: exactly her own HUD


def apply_theme(name: str, custom=None) -> None:
    """DEFAULT (her HUD's colours), LIGHT or CUSTOM (controller_settings.json) into render_helpers:
    its colour globals, and the defaults its functions took from them (hline's border, txt's text...)."""
    if name == "DEFAULT":
        new = dict(_ORIGINAL)
    else:
        c = kit.theme_colours(name, custom)
        if name == "LIGHT":   # her extra surfaces, from the light ones kit made
            c.update(grid=kit.mix(c["background"], c["divider"], 0.5), bottom_bar=c["panel"],
                     camera_bg=kit.mix(c["panel"], c["border"], 0.5), track=c["divider"], led_off=c["border"])
        new = {g: tuple(c.get(role, _ORIGINAL[g])) for g, role in COLOUR_ROLES.items()}
    swap = {getattr(rh, g): new[g] for g in COLOUR_ROLES}
    for fn in vars(rh).values():
        if callable(fn) and getattr(fn, "__defaults__", None):
            fn.__defaults__ = tuple(swap.get(d, d) if isinstance(d, tuple) else d for d in fn.__defaults__)
    for g, v in new.items():
        setattr(rh, g, v)


def _resolve_robot_url() -> tuple:
    """(robot URL or None, fullscreen, emulate)."""
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("robot", nargs="?", default=os.environ.get("ROBOT_URL"),
                        help="Robot IP or URL, e.g. 192.168.1.50 or http://192.168.1.50:5003")
    parser.add_argument("--port", type=int, default=5003)
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--emulate", action="store_true",
                        help="start on her pretend self (fake_kida00.py); the default with no robot given")
    parser.add_argument("--ladder", action="store_true",
                    help="join / host the fleet's WiFi (fleet_ladder.py; FLEET_LADDER=1 does the same)")
    args = parser.parse_args()
    from fleet_ladder import FleetLadder   # the fleet's WiFi ladder (fleet TODO, section 2)
    FleetLadder("KIDA00CTL", enabled=args.ladder or None).start()
    if not args.robot:
        return None, args.fullscreen, True
    robot = args.robot if args.robot.startswith("http") else f"http://{args.robot}:{args.port}"
    return robot, args.fullscreen, args.emulate


def _mode_of(status: dict) -> Mode:
    try:
        return Mode[status.get("mode", "USER")]
    except KeyError:
        return Mode.USER


def _mode_cmd(mode: Mode) -> str:
    return f"_mode_{mode.name.lower()}"


def run_controller() -> None:
    real_url, fullscreen, emulate = _resolve_robot_url()
    settings = kit.Settings()               # controller/controller_settings.json: THEME (this PC's, not in git)
    apply_theme(settings.theme, settings.get("custom"))
    fake = {"robot": None}

    def start_fake() -> None:
        if fake["robot"] is None:
            try:
                import fake_kida00
                fake["robot"] = fake_kida00.FakeKida()
                fake["robot"].quiet = True
            except OSError:              # port 5003 taken: a fake_kida00.py already running? use that
                print("EMULATE: port 5003 is taken; talking to whatever answers there")

    if emulate:
        start_fake()
    base_url = FAKE_URL if emulate else real_url
    print(f"{APP_NAME} - connecting to {base_url}" + ("  (EMULATE: her pretend self)" if emulate else ""))
    remote  = RemoteClient(base_url)
    brain   = DriveMind(remote)
    pending = kit.Pending()                 # settings sent again until her status says so

    pygame.init()
    pygame.display.set_caption(APP_NAME)
    try:  # window icon: the robot's avatar
        pygame.display.set_icon(pygame.image.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "images", "kida-icon.png")))
    except (pygame.error, OSError):
        pass
    info = pygame.display.Info()
    if fullscreen:
        W, H  = info.current_w, info.current_h
        flags = pygame.FULLSCREEN
    else:
        W, H  = max(MIN_W, int(info.current_w * 0.9)), max(MIN_H, int(info.current_h * 0.9))
        flags = pygame.RESIZABLE
    screen = pygame.display.set_mode((W, H), flags)
    clock  = pygame.time.Clock()

    fonts    = hud_layout.make_fonts()
    fmono_xl = fonts["fmono_xl"];  fmono_md = fonts["fmono_md"]
    fmono_sm = fonts["fmono_sm"];  fmono_xs = fonts["fmono_xs"]
    fbody    = fonts["fbody"];     flabel   = fonts["flabel"]
    flabel_s = fonts["flabel_s"];  fdpad    = fonts["fdpad"]

    def relayout(w, h):
        lay = hud_layout.compute_layout(w, h)
        bg  = build_background(w, h, lay["TOP_H"], lay["BOT_H"], lay["L_W"], lay["R_W"])
        cs  = pygame.Surface((lay["CAM_W"], lay["CAM_H"]));  cs.fill(rh.CAM_BG)
        # the PC's own buttons, in the top bar between her logo and the LED dots / CPU chips
        th, bw = lay["TOP_H"], {"STOP": 84, "EMULATE": 112, "THEME": 150}
        x, y = w - 420, (th - 30) // 2
        lay["pc_btns"] = {}
        for name in ("THEME", "EMULATE", "STOP"):
            x -= bw[name]
            lay["pc_btns"][name] = pygame.Rect(x, y, bw[name] - 8, 30)
        return lay, bg, cs

    lay, bg_surf, cam_surf = relayout(W, H)
    cam_seq  = -1
    qr_surf  = pygame.Surface((130, 130));  qr_surf.fill((255, 255, 255))
    have_qr  = False
    host_ip  = urlparse(base_url).hostname or base_url
    status   = {}

    def set_emulate(on: bool) -> None:
        nonlocal emulate, host_ip, have_qr, cam_seq
        if on == emulate or (not on and not real_url):
            return                        # no robot to go back to: she stays emulated
        emulate = on
        if on:
            start_fake()
        remote.retarget(FAKE_URL if on else real_url)
        if not on and fake["robot"] is not None:
            fake["robot"].stop()
            fake["robot"] = None
        host_ip  = urlparse(remote.base_url).hostname or remote.base_url
        have_qr, cam_seq = False, -1
        print("EMULATE on: her pretend self" if on else f"EMULATE off: {real_url}")

    def want_mode(m: Mode) -> None:
        pending.want("mode", m.name, lambda c=_mode_cmd(m): remote.send(c))

    def want(key, value, cmd) -> None:
        pending.want(key, value, lambda: remote.send(cmd))

    def shown(key, default):
        """A setting as just picked (before she confirms it), else as her status says."""
        v = pending.value(key)
        return status.get(key, default) if v is None else v

    def stop_anywhere() -> None:
        """STOP: motors off in any mode, back to USER (as the pad's B)."""
        if shown("mode", "USER") != "USER":
            want_mode(Mode.USER)
        remote.send("stop")

    frame     = 0
    hold_dir  = None     # on-screen d-pad held with the mouse
    joy       = None     # on-screen joystick (x, y) while dragged
    pad_knob  = None     # gamepad stick, shown on the on-screen joystick
    gamepad   = Gamepad()
    last_sent = None     # last drive intent sent
    last_beat = 0.0
    last_pan  = 0.0
    show_keys = False    # the keys window (H / F1)

    print("Keys: the same as on the robot. H or F1 shows them all.")

    running = True
    while running:
        mouse  = pygame.mouse.get_pos()
        at     = remote.status_at   # first: the status read after it is at least that new
        status = remote.status
        st     = remote.stats
        pending.check(status, at)

        mode        = _mode_of({"mode": shown("mode", "USER")})
        direction   = status.get("direction", "STOPPED")
        speed_idx   = shown("speed_idx", 0)
        speed       = hud_layout.SPEED_LEVELS[speed_idx] if pending.value("speed_idx") is not None \
            else status.get("speed", hud_layout.SPEED_LEVELS[0])
        ctrl_scheme = shown("ctrl_scheme", 1)
        arc_turn    = shown("arc_turn", True)
        video_rec   = shown("video_rec", False)
        music_on    = shown("music_playing", False)
        face_scan   = status.get("face_scan", True)
        faces       = status.get("faces", [])
        led_color   = tuple(status.get("led", (0, 0, 0)))

        cpu_pct  = min(st.get("cpu", 0)  / 100.0, 1.0)
        temp_c   = st.get("temp", 0)
        temp_pct = min(temp_c / 85.0, 1.0)
        ram_u    = st.get("ram_used",  0)
        ram_t    = st.get("ram_total", 1)
        ram_pct  = min(ram_u / max(ram_t, 1), 1.0)
        local_ip = st.get("ip") if st.get("ip") not in (None, "", "N/A") else host_ip

        # ── Network images → surfaces (decoded here, on the main thread) ──────
        if remote.jpeg_seq != cam_seq and remote.jpeg:
            cam_seq = remote.jpeg_seq
            try:
                img      = pygame.image.load(io.BytesIO(remote.jpeg), "frame.jpg")
                cam_surf = pygame.transform.scale(img, (lay["CAM_W"], lay["CAM_H"]))
            except pygame.error:
                pass
        if not have_qr and remote.qr_png:
            try:
                qr_surf = pygame.transform.smoothscale(
                    pygame.image.load(io.BytesIO(remote.qr_png), "qr.png").convert(), (130, 130))
                have_qr = True
            except pygame.error:
                pass

        music = SimpleNamespace(current_track=status.get("track", ""))
        W, H  = lay["W"], lay["H"]
        TOP_H, BOT_H, PAD = lay["TOP_H"], lay["BOT_H"], lay["PAD"]

        # ════════════════════════════════
        #  RENDER — same calls as ui.py
        # ════════════════════════════════
        screen.blit(bg_surf, (0, 0))

        render_camera(screen, cam_surf, faces, frame, video_rec, mode,
                      lay["CAM_X"], lay["CAM_Y"], lay["CAM_W"], lay["CAM_H"],
                      hud_layout.CAM_NATIVE_W, hud_layout.CAM_NATIVE_H,
                      fmono_sm, fmono_xs, status.get("deepface_ok", True), face_scan)

        render_info_strip(screen, mode, direction, speed, ctrl_scheme, led_color,
                          len(faces), lay["CAM_X"], lay["CAM_Y"], lay["CAM_H"],
                          fmono_xs, fmono_sm)

        hline(screen, TOP_H,          0, W)
        hline(screen, H - BOT_H,      0, W)
        vline(screen, lay["L_W"],     TOP_H, H - BOT_H)
        vline(screen, W - lay["R_W"], TOP_H, H - BOT_H)

        render_top_bar(screen, mode, st.get("threads", 0), temp_c, st,
                       led_color, lay["tabs"], hud_layout.TAB_LABELS,
                       W, TOP_H, fmono_xl, fmono_md, fmono_xs, fbody, mouse)

        render_left_panel(screen, qr_surf, local_ip, st,
                          cpu_pct, temp_c, temp_pct, ram_u, ram_t, ram_pct,
                          st.get("latency", "N/A"), st.get("threads", 0),
                          st.get("disk_read", 0), st.get("disk_write", 0),
                          st.get("boot_time", "--:--"),
                          music, music_on, frame, None,
                          lay["btn_play"], lay["btn_skip"], mouse,
                          lay["lp_x"], lay["lp_w"], TOP_H, PAD,
                          fmono_md, fmono_sm, fmono_xs, fbody, flabel, flabel_s)

        render_right_panel(screen, mode, direction, speed_idx, ctrl_scheme, video_rec,
                           lay["dpad"], hud_layout.DPAD_GLYPHS, lay["spd_dots"], lay["sch_btns"],
                           lay["btn_photo"], lay["btn_video"],
                           lay["btn_face_snap"], lay["btn_face_scan"], face_scan,
                           lay["rp_x"], lay["spd_y"], lay["sch_y"], lay["cap_y"],
                           TOP_H, PAD, mouse, fmono_md, fmono_xs, fbody, fdpad,
                           arc_turn=arc_turn)

        render_joystick(screen, lay["joy"], joy or pad_knob, mouse, mode == Mode.USER, fmono_xs)

        render_bottom_bar(screen, mode, ctrl_scheme, speed, len(faces),
                          status.get("frame", frame), W, H, BOT_H, fmono_xs,
                          online=remote.connected, pad=gamepad.name)

        for name, r in lay["pc_btns"].items():   # the PC's own: EMULATE / THEME / STOP
            label = f"THEME {settings.theme}" if name == "THEME" else name
            btn(screen, flabel_s, label, r, mouse, active=(name == "EMULATE" and emulate), danger=(name == "STOP"))

        if not remote.connected:
            txt(screen, fmono_md, "[ NO CONNECTION TO ROBOT ]",
                (W // 2, TOP_H + lay["CAM_H"] // 2 + 60), rh.RED, anchor="center")
        elif emulate:
            txt(screen, fmono_xs, kit.fit("EMULATE: her pretend self on this PC (fake_kida00.py)", fmono_xs, lay["CAM_W"] - 16),
                (lay["CAM_X"] + 8, lay["CAM_Y"] + 6), rh.AMBER)

        brain.update(status)
        if brain.mind.on or mode == Mode.MIND:   # her thinking, over the bottom of the camera
            ph = min(170, lay["CAM_H"] // 2)
            mind_panel.draw(screen, pygame.Rect(lay["CAM_X"] + 8, lay["CAM_Y"] + lay["CAM_H"] - ph - 8,
                                                lay["CAM_W"] - 16, ph),
                            brain.mind, fmono_sm, fmono_xs, "KIDA-00", note="9: MIND, U: you drive")

        if show_keys:
            render_keymap(screen, f"{keymap.ROBOT} KEYS", keymap.sections(), W, H,
                          fmono_md, fmono_sm, flabel_s)

        pygame.display.flip()

        # ════════════════════════════════
        #  EVENTS — same bindings as ui.py, sent as commands
        # ════════════════════════════════
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.VIDEORESIZE and not fullscreen:
                w, h   = max(MIN_W, event.w), max(MIN_H, event.h)
                screen = pygame.display.set_mode((w, h), pygame.RESIZABLE)
                lay, bg_surf, cam_surf = relayout(w, h)
                cam_seq = -1

            elif event.type == pygame.KEYDOWN:
                k = event.key
                if   k in (pygame.K_h, pygame.K_F1) or (k == pygame.K_ESCAPE and show_keys):
                    show_keys = not show_keys and k != pygame.K_ESCAPE
                elif k == pygame.K_ESCAPE:
                    running = False
                elif k == pygame.K_BACKSPACE:
                    stop_anywhere()
                elif k == pygame.K_LEFT:
                    remote.send("cam_left")
                elif k == pygame.K_RIGHT:
                    remote.send("cam_right")
                elif k == pygame.K_UP:
                    remote.send("cam_centre")
                elif k == pygame.K_TAB:
                    want_mode(Mode((int(mode) + 1) % 3) if int(mode) < 3 else Mode.USER)
                elif k == pygame.K_m:
                    want("music_playing", True, "play_music")
                elif k == pygame.K_SPACE:
                    want("music_playing", False, "stop_music")
                elif k == pygame.K_u:
                    want_mode(Mode.USER)
                elif k == pygame.K_o:
                    want_mode(Mode.AUTONOMOUS)
                elif k == pygame.K_l:
                    want_mode(Mode.LINE)
                elif k == pygame.K_9:
                    if brain.capable and status.get("mindHost"):
                        want_mode(Mode.MIND)
                    else:
                        print(f"MIND: not available: {brain.why or 'she has not heard this PC check in yet'}")
                elif k == pygame.K_x and mode in (Mode.USER, Mode.AUTONOMOUS):
                    i = (speed_idx + 1) % len(hud_layout.SPEED_LEVELS)   # autonomous cruises at it too
                    want("speed_idx", i, f"speed_{i + 1}")
                elif mode == Mode.USER:
                    if   k == pygame.K_1: want("ctrl_scheme", 1, "scheme_1")
                    elif k == pygame.K_2: want("ctrl_scheme", 2, "scheme_2")
                    elif k == pygame.K_t: want("arc_turn", not arc_turn, "arc_off" if arc_turn else "arc_on")
                    elif k == pygame.K_c: remote.send("photo")
                    elif k == pygame.K_v: want("video_rec", not video_rec, "video_stop" if video_rec else "video_start")
                    elif k == pygame.K_f: remote.send("face_save")   # not S — that drives
                    elif k == pygame.K_j: remote.send("hello")
                    elif k == pygame.K_n: remote.send("dance")

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                pos = event.pos
                for name, r in lay["pc_btns"].items():
                    if r.collidepoint(pos):
                        if name == "STOP":
                            stop_anywhere()
                        elif name == "EMULATE":
                            set_emulate(not emulate)
                        elif name == "THEME":
                            settings.next_theme()
                            apply_theme(settings.theme, settings.get("custom"))
                            lay, bg_surf, cam_surf = relayout(lay["W"], lay["H"])
                            cam_seq = -1
                for i, tr in enumerate(lay["tabs"]):
                    if tr.collidepoint(pos):
                        want_mode(Mode(i))

                # the D-pad and the joystick take over in any mode (back to USER, you drive)
                for cmd, r in lay["dpad"].items():
                    if r.collidepoint(pos):
                        hold_dir = None if cmd == "stop" else cmd
                        if cmd == "stop":
                            stop_anywhere()
                jc = lay["joy"]
                if jc and (pos[0] - jc[0]) ** 2 + (pos[1] - jc[1]) ** 2 <= jc[2] ** 2:
                    joy = joystick_value(jc, pos)      # dragged until the button comes up

                if mode == Mode.USER:
                    for i, r in enumerate(lay["sch_btns"]):
                        if r.collidepoint(pos):
                            if i < 2:
                                want("ctrl_scheme", i + 1, f"scheme_{i + 1}")
                            else:
                                want("arc_turn", not arc_turn, "arc_off" if arc_turn else "arc_on")
                    if lay["btn_photo"].collidepoint(pos): remote.send("photo")
                    if lay["btn_video"].collidepoint(pos):
                        want("video_rec", not video_rec, "video_stop" if video_rec else "video_start")

                if mode in (Mode.USER, Mode.AUTONOMOUS):
                    for i, r in enumerate(lay["spd_dots"]):
                        if r.collidepoint(pos): want("speed_idx", i, f"speed_{i + 1}")

                if lay["btn_face_snap"].collidepoint(pos): remote.send("face_save")
                if lay["btn_face_scan"].collidepoint(pos): remote.send("face_scan_toggle")
                if lay["btn_play"].collidepoint(pos):
                    want("music_playing", not music_on, "stop_music" if music_on else "play_music")
                if lay["btn_skip"].collidepoint(pos) and music_on:
                    remote.send("skip_music")

            elif event.type == pygame.MOUSEMOTION and joy is not None:
                joy = joystick_value(lay["joy"], event.pos)

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                hold_dir = None
                joy      = None

        # ── Gamepad buttons → the same commands as the keys / buttons ─────────
        pad = gamepad.poll()
        pad_knob = None
        if pad:
            for cmd in button_commands(pad.pressed, mode.name):
                remote.send(cmd)
            if abs(pad.rx) > 0.3 and time.monotonic() - last_pan >= CAM_PAN_S:   # right stick pans the camera
                remote.send(f"cam_pan:{-pad.rx * 7.5:.1f}")
                last_pan = time.monotonic()

        # ── Drive — keys / gamepad / joystick / d-pad become a resent intent ──
        # Priority matches the robot: keyboard, gamepad, on-screen joystick, d-pad.
        # Read in every mode: a drive input while she drives herself takes over (back to USER).
        intent = None
        keys = pygame.key.get_pressed() if pygame.key.get_focused() else None
        key_wheels = keys and keys_to_wheels(keys[pygame.K_w], keys[pygame.K_s],
                                             keys[pygame.K_a], keys[pygame.K_d], arc_turn)
        pad_wheels = None
        if pad:
            if ctrl_scheme == 2:
                pad_wheels = tank_sticks_to_wheels(pad.ly, pad.ry)
            else:
                pad_wheels = stick_to_wheels(pad.lx, pad.ly)
                if pad_wheels:
                    pad_knob = (pad.lx, pad.ly)
            pad_wheels = pad_wheels or keys_to_wheels(pad.up, pad.down, pad.left, pad.right, arc_turn)

        if ctrl_scheme == 1 and key_wheels:
            intent = wheels_to_command(*key_wheels)
        elif keys and ctrl_scheme == 2 and any(keys[k] for k in (pygame.K_q, pygame.K_a, pygame.K_w, pygame.K_s)):
            l = 1 if keys[pygame.K_q] else -1 if keys[pygame.K_a] else 0
            r = 1 if keys[pygame.K_w] else -1 if keys[pygame.K_s] else 0
            intent = f"tank:{l}:{r}"
        elif pad_wheels:
            intent = wheels_to_command(*pad_wheels)
        elif joy is not None:
            intent = wheels_to_command(*(stick_to_wheels(*joy) or (0.0, 0.0)))
        elif hold_dir:
            intent = hold_dir

        if intent and mode != Mode.USER:
            print(f"Driving takes over: {mode.name} -> USER")
            want_mode(Mode.USER)
            mode = Mode.USER

        now = time.monotonic()
        if intent != last_sent:
            remote.send(intent or "stop")
            last_sent, last_beat = intent, now
        elif intent and now - last_beat >= HEARTBEAT_S:
            remote.send(intent)
            last_beat = now

        frame += 1
        clock.tick(25)

    # ── Cleanup — never leave the robot driving after this window closes ──────
    if brain.mind.on:
        brain.mind.stop()
    remote.send_now("stop")
    remote.stop()
    if fake["robot"] is not None:
        fake["robot"].stop()
    pygame.quit()
    print("Controller closed")


if __name__ == "__main__":
    run_controller()
