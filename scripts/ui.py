#!/usr/bin/env python3

"""
main.py — KIDA v0.0  Entry point.
Handles hardware init, event loop, drive logic, and shutdown.

Drive schemes
─────────────
Scheme 1 (WASD)   — press 1 to activate
  W = forward  S = backward  A = left  D = right
  W+A / W+D / S+A / S+D arc (inside wheel at 40%) while ARC is on — T toggles
Scheme 2 (QA/WS)  — press 2 to activate
  Tank control via motors.control_tank()
Speed — press X to cycle through [0.4, 0.6, 0.8, 1.0]
Also: on-screen joystick (drag) and a gamepad (gamepad.py) — see drive_mix.py
"""

import logging
import os
import queue
import signal
import sys
import threading
import time
import warnings

warnings.filterwarnings("ignore", category=UserWarning)

import pygame
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput

from mode_control       import Mode, ModeContext, switch_mode, face_pulse_color
from music_player       import MusicPlayer
from motor_control      import MotorController
from obstacle_avoidance import ObstacleAvoidance
from line_follower      import LineFollower
from led_control        import SPI_WS2812_LEDStrip
try:
    from audio_analysis import AudioAnalyzer
except Exception as _e:          # pydub / ffmpeg missing — waveform falls back to the animation
    AudioAnalyzer = None

from shared_state      import (
    command_queue,
    _robot_state, _robot_state_lock,
    _system_stats, _stats_lock,
    _face_results, _face_lock,
    _face_frame_q, _face_enabled, _deepface_ok,
    publish_frame, frame_wanted,
)
from server            import run_flask, shutdown_zeroconf, near
from system_monitor    import start_stats_thread, get_local_ip
from face_detector     import start_face_thread
from camera_utils      import cam_to_surface, make_qr
import hud_layout
from render_helpers    import (
    hline, vline,
    render_camera, render_info_strip, render_top_bar,
    render_left_panel, render_right_panel, render_bottom_bar,
    render_joystick, joystick_value,
    build_background, CAM_BG, PURPLE, TEAL,
)
from drive_mix         import keys_to_wheels, stick_to_wheels, tank_sticks_to_wheels, wheels_label
from gamepad           import Gamepad, button_commands

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("kida.main")
if AudioAnalyzer is None:
    logger.warning("audio_analysis unavailable (%s) — music waveform will be animated, not measured", _e)

# Repo root — photos/videos/faces/music live here no matter where KIDA is started from
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# LED colour per mode while nothing more specific is showing
_MODE_LED = {
    Mode.AUTONOMOUS: (0, 180, 160),   # teal = avoidance live
    Mode.LINE:       (0, 80, 200),    # blue = line-follow live
}


# ── Command processor ──────────────────────────────────────────────────────────
_MODE_MAP = {
    "_mode_user":       Mode.USER,
    "_mode_autonomous": Mode.AUTONOMOUS,
    "_mode_line":       Mode.LINE,
    "_mode_face":       Mode.FACE,
}


REMOTE_HOLD_S = 0.8   # a remote drive command stops unless resent within this


def _make_command_processor(take_photo, toggle_video, music, speed_levels):
    """Returns a closure that processes a single command string.

    Drive commands (forward/backward/left/right, tank:L:R) don't touch the
    motors directly — they set a remote drive intent that the USER-mode drive
    logic in main() applies each frame, so the per-frame "no key held → stop"
    doesn't cancel them. Clients resend while held (dead-man timeout)."""

    state = {
        "direction":     "STOPPED",
        "speed":         speed_levels[0],
        "speed_idx":     0,
        "ctrl_scheme":   1,
        "music_playing": False,
        "mode":          Mode.USER,
        "video_rec":     False,
        "face_scan":     True,
        "arc_turn":      True,    # W+A etc. curve (inside wheel slows) instead of driving straight
        "remote":        None,    # ("dir", "forward") | ("tank", (l, r)) | ("mix", (l, r))
        "remote_until":  0.0,
        "hold_dir":      None,    # on-screen d-pad held with the mouse
        "joy":           None,    # on-screen joystick (x, y) while dragged
    }

    def drive_intent(kind, value):
        state["remote"]       = (kind, value)
        state["remote_until"] = time.monotonic() + REMOTE_HOLD_S

    def music_play():
        music.play_next()
        state["music_playing"] = music.playing

    def music_stop():
        music.stop()
        state["music_playing"] = False

    state["_music_play"] = music_play
    state["_music_stop"] = music_stop

    def process(cmd: str, ctx: ModeContext) -> dict:
        cmd = cmd.strip().lower()

        if cmd in ("up", "forward"):
            drive_intent("dir", "forward")
        elif cmd in ("down", "backward"):
            drive_intent("dir", "backward")
        elif cmd in ("left", "right"):
            drive_intent("dir", cmd)
        elif cmd.startswith("tank:"):            # tank:<left>:<right>, each -1/0/1
            try:
                l, r = (max(-1, min(1, int(v))) for v in cmd[5:].split(":"))
                drive_intent("tank", (l, r))
            except ValueError:
                pass
        elif cmd.startswith("drive:"):           # drive:<left>:<right>, each -1..1 (joystick / arc turns)
            try:
                l, r = (max(-1.0, min(1.0, float(v))) for v in cmd[6:].split(":"))
                drive_intent("mix", (l, r))
            except ValueError:
                pass
        elif cmd == "stop":
            state["remote_until"] = 0.0
        elif cmd == "arc_toggle":
            state["arc_turn"] = not state["arc_turn"]
        elif cmd in ("arc_on", "arc_off"):
            state["arc_turn"] = cmd == "arc_on"
        elif cmd == "photo":
            take_photo()
        elif cmd in ("video", "video_start"):
            if not state["video_rec"]:         toggle_video(state)
        elif cmd == "video_stop":
            if state["video_rec"]:             toggle_video(state)
        elif cmd == "video_toggle":
            toggle_video(state)
        elif cmd in ("music", "play_music", "start_music"):
            if not state["music_playing"]:     music_play()
        elif cmd in ("stop_music", "pause_music"):
            music_stop()
        elif cmd == "music_toggle":
            music_stop() if state["music_playing"] else music_play()
        elif cmd in ("skip", "next_music", "skip_music"):
            if state["music_playing"]:         music.play_next()
        elif cmd == "speed":
            state["speed_idx"] = (state["speed_idx"] + 1) % len(speed_levels)
            state["speed"]     = speed_levels[state["speed_idx"]]
        elif cmd.startswith("speed_"):           # speed_1 … speed_4 (the 4 buttons)
            try:
                i = int(cmd[6:]) - 1
                if 0 <= i < len(speed_levels):
                    state["speed_idx"] = i
                    state["speed"]     = speed_levels[i]
            except ValueError:
                pass
        elif cmd.startswith("_speed_"):         # /speed route: any value 0..1
            try:
                state["speed"]     = max(0.0, min(1.0, float(cmd[7:])))
                state["speed_idx"] = min(range(len(speed_levels)),
                                         key=lambda i: abs(speed_levels[i] - state["speed"]))
            except ValueError:
                pass
        elif cmd in ("scheme_1", "scheme_wasd"):
            state["ctrl_scheme"] = 1
        elif cmd in ("scheme_2", "scheme_tank"):
            state["ctrl_scheme"] = 2
        elif cmd in ("face_save", "face_snapshot"):
            state["_face_snapshot"]()
        elif cmd == "face_scan_toggle":
            state["_face_scan_toggle"]()
        elif cmd in _MODE_MAP:
            state["mode"] = switch_mode(state["mode"], _MODE_MAP[cmd], ctx)
        return state

    return process, state


def _face_json(face: dict) -> dict:
    """Plain-Python copy of a face result (DeepFace hands back numpy numbers)."""
    reg = face.get("region", {}) or {}
    return {
        "region": {k: int(reg.get(k, 0)) for k in ("x", "y", "w", "h")},
        "gender": str(face.get("gender", "?")),
        "age":    int(face.get("age", 0) or 0),
        "conf":   float(face.get("conf", 0) or 0),
    }


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    pygame.init()
    info   = pygame.display.Info()
    W, H   = info.current_w, info.current_h
    screen = pygame.display.set_mode(
        (W, H), pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF)
    W, H   = screen.get_size()   # what we actually got (scaling / Wayland can differ)
    pygame.display.set_caption("KIDA")
    try:  # window icon: the robot's avatar
        pygame.display.set_icon(pygame.image.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "images", "kida-icon.png")))
    except (pygame.error, OSError):
        pass
    clock = pygame.time.Clock()

    # ── Layout + fonts — shared with controller/main.py (hud_layout.py) ──────
    lay = hud_layout.compute_layout(W, H)
    TOP_H, BOT_H, PAD = lay["TOP_H"], lay["BOT_H"], lay["PAD"]
    L_W, R_W          = lay["L_W"], lay["R_W"]
    CAM_X, CAM_Y      = lay["CAM_X"], lay["CAM_Y"]
    CAM_W, CAM_H      = lay["CAM_W"], lay["CAM_H"]
    CAM_NATIVE_W, CAM_NATIVE_H = hud_layout.CAM_NATIVE_W, hud_layout.CAM_NATIVE_H

    fonts    = hud_layout.make_fonts()
    fmono_xl = fonts["fmono_xl"];  fmono_md = fonts["fmono_md"]
    fmono_sm = fonts["fmono_sm"];  fmono_xs = fonts["fmono_xs"]
    fbody    = fonts["fbody"];     flabel   = fonts["flabel"]
    flabel_s = fonts["flabel_s"];  fdpad    = fonts["fdpad"]

    # ── Background threads ─────────────────────────────────────────────────────
    threading.Thread(target=run_flask,  daemon=True).start()
    start_stats_thread()
    start_face_thread()

    # ── Hardware ───────────────────────────────────────────────────────────────
    music  = MusicPlayer(os.path.join(_ROOT, "audio", "music"))
    motors = MotorController()

    try:    avoider = ObstacleAvoidance(motors=motors)
    except Exception as e:
        logger.warning("ObstacleAvoidance init failed: %s", e);  avoider = None

    try:    liner = LineFollower(motors=motors)
    except Exception as e:
        logger.warning("LineFollower init failed: %s", e);  liner = None

    led = SPI_WS2812_LEDStrip(8, 128)
    if not led.ready:
        # Drive, camera and dashboard all still work without the strip
        logger.error("SPI LED strip not ready — carrying on without LEDs")

    cam = Picamera2()
    cam.configure(cam.create_preview_configuration(
        main={"size": (CAM_NATIVE_W, CAM_NATIVE_H)},
        transform=__import__("libcamera").Transform(hflip=1, vflip=1),
    ))
    cam.start()
    _encoder = H264Encoder(bitrate=4000000)

    # Rebuilt in the loop if the address changes (Wi-Fi came up after boot)
    local_ip   = get_local_ip()
    qr_surf    = make_qr(f"http://{local_ip}:5003", size=130)
    photos_dir = os.path.join(_ROOT, "photos")
    videos_dir = os.path.join(_ROOT, "videos")
    face_dir   = os.path.join(_ROOT, "faces")
    for d in (photos_dir, videos_dir, face_dir):
        os.makedirs(d, exist_ok=True)

    # ── LED helpers ────────────────────────────────────────────────────────────
    led_r = led_g = led_b = 0
    led_stale = False     # True after rhythm_wave drew over the strip

    def set_led(color: tuple) -> None:
        nonlocal led_r, led_g, led_b, led_stale
        if tuple(color) == (led_r, led_g, led_b) and not led_stale:
            return            # unchanged — skip the SPI write
        led_r, led_g, led_b = color
        led_stale = False
        led.set_all_led_color(*color)
        with _robot_state_lock:
            _robot_state["led"] = list(color)

    def led_color():
        return (led_r, led_g, led_b)

    # ── ModeContext ────────────────────────────────────────────────────────────
    ctx = ModeContext(
        motors=motors, led=led, set_led_fn=set_led,
        face_enabled_event=_face_enabled,
        face_results=_face_results, face_lock=_face_lock,
        robot_state=_robot_state, robot_state_lock=_robot_state_lock,
    )

    # ── Voice: greet on startup, the way NORA plays her hello line ──────────────
    try:
        from voice import voice
        voice.hello()
    except Exception as e:
        logger.debug("voice hello skipped: %s", e)

    # ── Action helpers ─────────────────────────────────────────────────────────
    cam_pil = None  # updated each frame; used by face snapshot

    def take_photo() -> None:
        fname = os.path.join(photos_dir, f"photo_{int(time.time())}.jpg")
        try:    cam.capture_file(fname);  logger.info("Photo: %s", fname)
        except Exception as e: logger.error("Photo failed: %s", e)

    def toggle_video(vs: dict) -> None:
        if not vs["video_rec"]:
            fname = os.path.join(videos_dir, f"video_{int(time.time())}.mp4")
            try:
                cam.start_encoder(_encoder, FfmpegOutput(fname))
                vs["video_rec"] = True;  logger.info("Recording: %s", fname)
            except Exception as e: logger.error("Video start failed: %s", e)
        else:
            try:    cam.stop_encoder()
            except Exception as e: logger.error("Video stop failed: %s", e)
            vs["video_rec"] = False

    def save_face_snapshot() -> None:
        nonlocal cam_pil
        if cam_pil is None:
            return
        try:
            from PIL import ImageDraw
            pil_base = cam_pil.copy()
            draw = ImageDraw.Draw(pil_base)
            sx = pil_base.width  / CAM_NATIVE_W     # face regions are in native coords
            sy = pil_base.height / CAM_NATIVE_H
            with _face_lock:
                faces = _face_results.copy()
            for face in faces:
                reg = face.get("region", {})
                x,  y_ = reg.get("x", 0) * sx, reg.get("y", 0) * sy
                w_, h_ = reg.get("w", 0) * sx, reg.get("h", 0) * sy
                gender = str(face.get("gender", "?")) or "?";  age = face.get("age", 0)
                col = PURPLE if gender == "Woman" else TEAL
                draw.rectangle([x, y_, x + w_, y_ + h_], outline=col, width=2)
                draw.text((x + 2, y_ - 14), f"{gender[0]} {age}y", fill=col)
            fname = os.path.join(face_dir, f"face_{int(time.time())}.jpg")
            pil_base.save(fname, "JPEG");  logger.info("Face snapshot: %s", fname)
        except Exception as e: logger.error("Face snapshot failed: %s", e)

    # ── Command processor + shared drive state ─────────────────────────────────
    speed_levels = hud_layout.SPEED_LEVELS
    process_cmd, ds = _make_command_processor(
        take_photo, toggle_video, music, speed_levels
    )

    def music_play():  ds["_music_play"]()
    def music_stop():  ds["_music_stop"]()

    def toggle_face_scan() -> None:
        ds["face_scan"] = not ds["face_scan"]
        if ds["face_scan"]:
            _face_enabled.set()
        else:
            _face_enabled.clear()
            with _face_lock:
                _face_results.clear()

    ds["_face_snapshot"]    = save_face_snapshot
    ds["_face_scan_toggle"] = toggle_face_scan

    # ── Drive helpers ──────────────────────────────────────────────────────────
    def drive_dir(d: str) -> None:
        if   d == "forward":  motors.forward(ds["speed"]);    set_led((0, 255, 0))
        elif d == "backward": motors.backward(ds["speed"]);   set_led((255, 0, 0))
        elif d == "left":     motors.turn_left(ds["speed"]);  set_led((0, 0, 255))
        elif d == "right":    motors.turn_right(ds["speed"]); set_led((255, 255, 0))
        else:                 motors.stop();                  set_led((0, 0, 0)); d = "stopped"
        ds["direction"] = d.upper()

    def drive_tank(l: int, r: int) -> None:
        for wheel, v in ((motors.left, l), (motors.right, r)):
            if   v > 0: wheel.forward(ds["speed"])
            elif v < 0: wheel.backward(ds["speed"])
            else:       wheel.stop()
        if l and r:  set_led((0, 255, 255))
        elif l:      set_led((255, 0, 255))
        elif r:      set_led((255, 165, 0))
        else:        set_led((0, 0, 0))
        ds["direction"] = "TANK" if (l or r) else "STOPPED"

    def drive_wheels(l: float, r: float) -> None:
        """Each wheel at its own fraction of the selected speed (arc turns,
        joystick, gamepad) — see drive_mix.py."""
        motors.drive(l * ds["speed"], r * ds["speed"])
        label = wheels_label(l, r)
        if   label == "FORWARD":      set_led((0, 255, 0))
        elif label == "BACKWARD":     set_led((255, 0, 0))
        elif label == "STOPPED":      set_led((0, 0, 0))
        elif label.endswith("LEFT"):  set_led((0, 0, 255))
        else:                         set_led((255, 255, 0))
        ds["direction"] = label

    gamepad  = Gamepad()
    pad_knob = None       # gamepad stick shown on the on-screen joystick

    # ── UI layout (hud_layout.compute_layout) ──────────────────────────────────
    TAB_LABELS  = hud_layout.TAB_LABELS
    DPAD_GLYPHS = hud_layout.DPAD_GLYPHS
    tabs, dpad  = lay["tabs"], lay["dpad"]
    spd_dots, sch_btns = lay["spd_dots"], lay["sch_btns"]
    btn_photo, btn_video = lay["btn_photo"], lay["btn_video"]
    btn_face_snap, btn_face_scan = lay["btn_face_snap"], lay["btn_face_scan"]
    btn_play, btn_skip = lay["btn_play"], lay["btn_skip"]
    rp_x, spd_y, sch_y, cap_y = lay["rp_x"], lay["spd_y"], lay["sch_y"], lay["cap_y"]
    lp_x, lp_w = lay["lp_x"], lay["lp_w"]

    bg_surf = build_background(W, H, TOP_H, BOT_H, L_W, R_W)

    # Face scanning runs in all modes — enable immediately
    _face_enabled.set()

    # ── Per-frame state ────────────────────────────────────────────────────────
    frame    = 0
    cam_surf = pygame.Surface((CAM_W, CAM_H));  cam_surf.fill(CAM_BG)
    cam_tick = 0;  face_tick = 0

    # Waveform data for the current track. Decoding an mp3 takes seconds, so it
    # happens on a worker thread; until it's ready the waveform just animates.
    analyzer       = None
    analyzer_track = None

    def load_analyzer(path: str) -> None:
        nonlocal analyzer
        try:
            a = AudioAnalyzer(path, num_bars=22)
        except Exception as e:
            logger.warning("Audio analysis failed for %s: %s", path, e)
            return
        if analyzer_track == path:          # still the same song
            analyzer = a

    # ── Main loop ──────────────────────────────────────────────────────────────
    # systemctl stop sends SIGTERM — turn it into a normal exit so the
    # finally: below still stops the motors, camera and LEDs
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    running = True
    try:
        while running:
            mouse = pygame.mouse.get_pos()

            with _stats_lock:
                st = _system_stats.copy()

            if st.get("ip") not in (None, "N/A", local_ip):
                local_ip = st["ip"]
                qr_surf  = make_qr(f"http://{local_ip}:5003", size=130)

            cpu_pct  = min(st.get("cpu", 0)  / 100.0, 1.0)
            temp_c   = st.get("temp", 0)
            temp_pct = min(temp_c / 85.0, 1.0)
            ram_u    = st.get("ram_used",  0)
            ram_t    = st.get("ram_total", 1)
            ram_pct  = min(ram_u / max(ram_t, 1), 1.0)

            # Camera frame
            cam_tick += 1
            if cam_tick >= 3:
                cam_tick = 0
                cam_surf, cam_pil = cam_to_surface(cam, CAM_W, CAM_H)
                if cam_pil is not None and frame_wanted():
                    publish_frame(cam_pil, (CAM_NATIVE_W, CAM_NATIVE_H))

            # Feed face worker in all modes when scanning is active
            if ds["face_scan"] or ds["mode"] == Mode.FACE:
                face_tick += 1
                if face_tick >= 45 and cam_pil is not None:
                    face_tick = 0
                    try:    _face_frame_q.put_nowait(cam_pil.resize((CAM_NATIVE_W, CAM_NATIVE_H)))
                    except queue.Full: pass
            else:
                face_tick = 0

            # Audio amplitudes
            track_path = music.current_path if ds["music_playing"] else None
            if track_path != analyzer_track:
                analyzer, analyzer_track = None, track_path
                if track_path and AudioAnalyzer is not None:
                    threading.Thread(target=load_analyzer, args=(track_path,), daemon=True).start()
            amplitudes = None
            if ds["music_playing"] and analyzer is not None:
                try:
                    amplitudes = analyzer.get_amplitudes(pygame.mixer.music.get_pos() / 1000.0)
                except Exception:
                    pass

            with _face_lock:
                face_snapshot = _face_results.copy()
            face_count = len(face_snapshot)

            # ── Render ─────────────────────────────────────────────────────────────
            screen.blit(bg_surf, (0, 0))

            render_camera(screen, cam_surf, face_snapshot, frame, ds["video_rec"],
                          ds["mode"], CAM_X, CAM_Y, CAM_W, CAM_H,
                          CAM_NATIVE_W, CAM_NATIVE_H,
                          fmono_sm, fmono_xs, _deepface_ok.is_set(), ds["face_scan"])

            render_info_strip(screen, ds["mode"], ds["direction"], ds["speed"],
                              ds["ctrl_scheme"], led_color(), face_count,
                              CAM_X, CAM_Y, CAM_H, fmono_xs, fmono_sm)

            hline(screen, TOP_H,     0, W)
            hline(screen, H - BOT_H, 0, W)
            vline(screen, L_W,       TOP_H, H - BOT_H)
            vline(screen, W - R_W,   TOP_H, H - BOT_H)

            render_top_bar(screen, ds["mode"], st.get("threads", 0), temp_c, st,
                           led_color(), tabs, TAB_LABELS,
                           W, TOP_H, fmono_xl, fmono_md, fmono_xs, fbody, mouse)

            render_left_panel(screen, qr_surf, local_ip, st,
                              cpu_pct, temp_c, temp_pct, ram_u, ram_t, ram_pct,
                              st.get("latency", "N/A"), st.get("threads", 0),
                              st.get("disk_read", 0), st.get("disk_write", 0),
                              st.get("boot_time", "--:--"),
                              music, ds["music_playing"], frame, amplitudes,
                              btn_play, btn_skip, mouse,
                              lp_x, lp_w, TOP_H, PAD,
                              fmono_md, fmono_sm, fmono_xs, fbody, flabel, flabel_s)

            render_right_panel(screen, ds["mode"], ds["direction"], ds["speed_idx"],
                               ds["ctrl_scheme"], ds["video_rec"],
                               dpad, DPAD_GLYPHS, spd_dots, sch_btns,
                               btn_photo, btn_video, btn_face_snap, btn_face_scan,
                               ds["face_scan"],
                               rp_x, spd_y, sch_y, cap_y, TOP_H, PAD, mouse,
                               fmono_md, fmono_xs, fbody, fdpad, arc_turn=ds["arc_turn"])

            render_joystick(screen, lay["joy"], ds["joy"] or pad_knob, mouse,
                            ds["mode"] == Mode.USER, fmono_xs)

            render_bottom_bar(screen, ds["mode"], ds["ctrl_scheme"], ds["speed"],
                              face_count, frame, W, H, BOT_H, fmono_xs,
                              pad=gamepad.name)

            # ── Events ─────────────────────────────────────────────────────────────
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                elif event.type == getattr(music, "SONG_END", -1):
                    music.handle_event(event)
                    ds["music_playing"] = music.playing

                elif event.type == pygame.KEYDOWN:
                    k = event.key
                    if   k == pygame.K_ESCAPE:
                        running = False
                    elif k == pygame.K_TAB:
                        ds["mode"] = switch_mode(
                            ds["mode"], Mode((int(ds["mode"]) + 1) % 3), ctx)
                    elif k == pygame.K_m:
                        music_play()
                    elif k == pygame.K_SPACE:
                        music_stop()
                    elif k == pygame.K_u:
                        ds["mode"] = switch_mode(ds["mode"], Mode.USER, ctx)
                    elif k == pygame.K_o:
                        ds["mode"] = switch_mode(ds["mode"], Mode.AUTONOMOUS, ctx)
                    elif k == pygame.K_l:
                        ds["mode"] = switch_mode(ds["mode"], Mode.LINE, ctx)
                    elif k == pygame.K_x and ds["mode"] in (Mode.USER, Mode.AUTONOMOUS):
                        # ← cycle speed (autonomous cruises at the selected speed too)
                        ds["speed_idx"] = (ds["speed_idx"] + 1) % len(speed_levels)
                        ds["speed"]     = speed_levels[ds["speed_idx"]]
                    elif ds["mode"] == Mode.USER:
                        if   k == pygame.K_1: ds["ctrl_scheme"] = 1  # ← WASD
                        elif k == pygame.K_2: ds["ctrl_scheme"] = 2  # ← QA/WS
                        elif k == pygame.K_t: ds["arc_turn"] = not ds["arc_turn"]   # ← arc turns on/off
                        elif k == pygame.K_c: take_photo()
                        elif k == pygame.K_v: toggle_video(ds)
                        elif k == pygame.K_f: save_face_snapshot()   # not S — that drives

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    for i, tr in enumerate(tabs):
                        if tr.collidepoint(event.pos):
                            ds["mode"] = switch_mode(ds["mode"], Mode(i), ctx)

                    if ds["mode"] == Mode.USER:
                        for cmd, r in dpad.items():
                            if r.collidepoint(event.pos):
                                # held until MOUSEBUTTONUP (drive logic below)
                                ds["hold_dir"] = None if cmd == "stop" else cmd
                                if cmd == "stop":
                                    ds["remote_until"] = 0.0
                        for i, r in enumerate(sch_btns):
                            if r.collidepoint(event.pos):
                                if i < 2: ds["ctrl_scheme"] = i + 1
                                else:     ds["arc_turn"] = not ds["arc_turn"]
                        joy = lay["joy"]
                        if joy and (event.pos[0] - joy[0]) ** 2 + (event.pos[1] - joy[1]) ** 2 <= joy[2] ** 2:
                            ds["joy"] = joystick_value(joy, event.pos)   # dragged until MOUSEBUTTONUP
                        if btn_photo.collidepoint(event.pos): take_photo()
                        if btn_video.collidepoint(event.pos): toggle_video(ds)

                    if ds["mode"] in (Mode.USER, Mode.AUTONOMOUS):
                        for i, r in enumerate(spd_dots):
                            if r.collidepoint(event.pos):
                                ds["speed_idx"] = i
                                ds["speed"]     = speed_levels[ds["speed_idx"]]

                    if btn_face_snap.collidepoint(event.pos):
                        save_face_snapshot()
                    if btn_face_scan.collidepoint(event.pos):
                        toggle_face_scan()
                    if btn_play.collidepoint(event.pos):
                        music_stop() if ds["music_playing"] else music_play()
                    if btn_skip.collidepoint(event.pos) and ds["music_playing"]:
                        music.play_next()

                elif event.type == pygame.MOUSEMOTION and ds["joy"] is not None:
                    ds["joy"] = joystick_value(lay["joy"], event.pos)

                elif event.type == pygame.MOUSEBUTTONUP:
                    ds["hold_dir"] = None
                    ds["joy"]      = None

            # Gamepad — buttons become the same commands the web/controller send
            pad = gamepad.poll()
            pad_knob = None
            if pad:
                for cmd in button_commands(pad.pressed, ds["mode"].name):
                    process_cmd(cmd, ctx)

            # Flask command queue
            while not command_queue.empty():
                process_cmd(command_queue.get_nowait(), ctx)

            # ── Drive logic ─────────────────────────────────────────────────────────
            mode = ds["mode"]
            # what KIDA tells the other robots (fleet_near.py), set once per frame
            near.set_state("driving" if mode in (Mode.AUTONOMOUS, Mode.LINE) else "user" if mode == Mode.USER else "parked")

            if mode == Mode.AUTONOMOUS:
                avoiding = False
                way = near.give_way(can_turn=True)   # another robot close with right of way: stop, then turn away
                if way == "wait":
                    motors.stop()
                    avoiding = True
                elif way == "turn":
                    motors.turn_left(max(ds["speed"], 0.5))
                    avoiding = True
                elif avoider:
                    # a robot near (or coming closer): slower, so the sensors have time
                    speed = ds["speed"] * (0.6 if near.advice() == "caution" else 1.0)
                    try:    avoiding = avoider.check_and_avoid(speed)
                    except Exception as e: logger.warning("Avoider: %s", e)
                else:
                    motors.stop()
                # red while stopping/scanning/turning, back to teal once clear
                set_led((255, 0, 0) if avoiding else _MODE_LED[Mode.AUTONOMOUS])
                ds["direction"] = "AVOIDING" if avoiding else ("FORWARD" if avoider else "STOPPED")

            elif mode == Mode.LINE:
                correcting = False
                if near.give_way(can_turn=False) != "go":   # wait on the line while a robot with right of way passes
                    motors.stop()
                    correcting = True
                elif liner:
                    try:    correcting = liner.follow_line()
                    except Exception as e: logger.warning("LineFollower: %s", e)
                else:
                    motors.stop()
                set_led(_MODE_LED[Mode.LINE])
                ds["direction"] = "CORRECTING" if correcting else ("FORWARD" if liner else "STOPPED")

            elif mode == Mode.USER:
                keys = pygame.key.get_pressed()
                # Remote intent (controller / web, resent while held) or the
                # on-screen d-pad held with the mouse — local keys win.
                remote = ds["remote"] if time.monotonic() < ds["remote_until"] else None
                if ds["hold_dir"]:
                    remote = ("dir", ds["hold_dir"])

                # Gamepad: left stick (WASD scheme) or both sticks (tank), else d-pad
                pad_wheels = None
                if pad:
                    if ds["ctrl_scheme"] == 2:
                        pad_wheels = tank_sticks_to_wheels(pad.ly, pad.ry)
                    else:
                        pad_wheels = stick_to_wheels(pad.lx, pad.ly)
                        if pad_wheels:
                            pad_knob = (pad.lx, pad.ly)
                    pad_wheels = pad_wheels or keys_to_wheels(pad.up, pad.down, pad.left, pad.right,
                                                              ds["arc_turn"])
                key_wheels = keys_to_wheels(keys[pygame.K_w], keys[pygame.K_s],
                                            keys[pygame.K_a], keys[pygame.K_d], ds["arc_turn"])

                # Priority: keyboard, gamepad, on-screen joystick, on-screen d-pad, remote
                if ds["ctrl_scheme"] == 1 and key_wheels:
                    # ── WASD (press 1) — W+A etc. arc while ARC is on ──────────────
                    drive_wheels(*key_wheels)
                elif ds["ctrl_scheme"] == 2 and any(keys[k] for k in (pygame.K_q, pygame.K_a, pygame.K_w, pygame.K_s)):
                    # ── QA/WS tank (press 2) ───────────────────────────────────────
                    drive_tank(1 if keys[pygame.K_q] else -1 if keys[pygame.K_a] else 0,
                               1 if keys[pygame.K_w] else -1 if keys[pygame.K_s] else 0)
                elif pad_wheels:
                    drive_wheels(*pad_wheels)
                elif ds["joy"] is not None:
                    drive_wheels(*(stick_to_wheels(*ds["joy"]) or (0.0, 0.0)))
                elif remote and remote[0] == "dir":
                    drive_dir(remote[1])
                elif remote and remote[0] == "tank":
                    drive_tank(*remote[1])
                elif remote and remote[0] == "mix":
                    drive_wheels(*remote[1])
                else:
                    drive_dir("stop")

            if ds["music_playing"]:
                led.rhythm_wave(frame)
                led_stale = True

            # Face scanning follows the SCAN button in every mode (FACE mode always
            # scans). Mode hooks also poke this event, so re-assert it each frame.
            if ds["face_scan"] or mode == Mode.FACE:
                _face_enabled.set()
            else:
                _face_enabled.clear()

            # ── Publish for Flask /status (controller + web dashboard) ────────────
            with _robot_state_lock:
                _robot_state.update(
                    direction=ds["direction"], speed=ds["speed"],
                    speed_idx=ds["speed_idx"], ctrl_scheme=ds["ctrl_scheme"],
                    arc_turn=ds["arc_turn"], gamepad=gamepad.name,
                    mode=ds["mode"].name, video_rec=ds["video_rec"],
                    music_playing=ds["music_playing"],
                    track=music.current_track or "",
                    face_scan=ds["face_scan"], face_count=face_count,
                    faces=[_face_json(f) for f in face_snapshot], deepface_ok=_deepface_ok.is_set(),
                    frame=frame,
                )

            led.show()
            frame += 1
            pygame.display.flip()
            clock.tick(25)

    # ── Cleanup — also runs after a crash or SIGTERM ──────────────────────────
    finally:
        logger.info("Shutting down…")
        # Motors first; each step guarded so one failure can't skip the rest
        steps = [
            ("motors",    motors.stop),
            ("mode",      lambda: switch_mode(ds["mode"], Mode.USER, ctx)),
            ("faces",     _face_enabled.clear),
            ("video",     lambda: ds["video_rec"] and cam.stop_encoder()),
            ("avoider",   lambda: avoider and avoider.cleanup()),
            ("liner",     lambda: liner and liner.cleanup()),
            ("motor pins", motors.cleanup),
            ("leds",      led.led_close),
            ("camera",    cam.stop),
            ("zeroconf",  shutdown_zeroconf),
        ]
        for name, step in steps:
            try:
                step()
            except Exception as e:
                logger.warning("Cleanup %s failed: %s", name, e)
        pygame.quit()


if __name__ == "__main__":
    main()