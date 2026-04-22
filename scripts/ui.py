#!/usr/bin/env python3

"""
main.py — KIDA v0.0  Entry point.
Handles hardware init, event loop, drive logic, and shutdown.

Drive schemes
─────────────
Scheme 1 (WASD)   — press 1 to activate
  W = forward  S = backward  A = left  D = right
Scheme 2 (QA/WS)  — press 2 to activate
  Tank control via motors.control_tank()
Speed — press X to cycle through [0.4, 0.6, 0.8, 1.0]
"""

import io
import json
import logging
import math
import os
import queue
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
from audio_analysis     import AudioAnalyzer

from shared_state      import (
    command_queue,
    _robot_state, _robot_state_lock,
    _system_stats, _stats_lock,
    _face_results, _face_lock,
    _face_frame_q, _face_enabled, _deepface_ok,
    _cam_jpeg, _cam_jpeg_lock,
    _cam_lock,
    _light_paint_state, _light_paint_lock,
    _media_state, _media_lock,
    _qr_state, _qr_lock,
    _qr_frame_q, _qr_enabled,
    _dance_active,
    _sleep_active,
    _audio_amps, _audio_amps_lock,
)
from server            import run_flask, shutdown_zeroconf
from system_monitor    import start_stats_thread, get_local_ip
from face_detector     import start_face_thread
from qr_reader         import start_qr_thread
from dance             import start_dance
from sleep             import sleep_breathe, render_sleep_screen
from camera_utils      import cam_to_surface, make_qr
from render_helpers    import (
    hline, vline,
    render_camera, render_info_strip, render_top_bar,
    render_left_panel, render_right_panel, render_bottom_bar,
    build_background,
    BORDER, ACCENT, GREEN, BLUE, AMBER, RED, TEAL, PURPLE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("kida.main")

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    with open(os.path.join(_BASE, "config.json")) as _f:
        _config = json.load(_f)
    _CAM_ROTATION = int(_config.get("Config", {}).get("Settings", {}).get("Camera Rotation", "0"))
except Exception:
    _CAM_ROTATION = 0


_CAM_NATIVE_W, _CAM_NATIVE_H = 320, 240


def _do_light_paint(cam, duration: int, photos_dir: str) -> None:
    """Run a long-exposure still capture then restore the preview stream."""
    fname = os.path.join(photos_dir, f"lp_{int(time.time())}.jpg")
    with _cam_lock:
        with _light_paint_lock:
            _light_paint_state.update({"active": True, "progress": 0.0})
        done = [False]
        start_t = [0.0]

        def _progress_ticker():
            while not done[0]:
                elapsed = time.time() - start_t[0]
                pct = min(0.1 + elapsed / max(duration, 1) * 0.88, 0.98)
                with _light_paint_lock:
                    _light_paint_state["progress"] = round(pct, 3)
                time.sleep(0.25)

        try:
            cam.stop()
            cam.configure(cam.create_still_configuration())
            cam.start()
            cam.set_controls({
                "ExposureTime": int(duration * 1_000_000),
                "AeEnable": False,
                "AnalogueGain": 1.0,
                "AwbEnable": False,
            })
            time.sleep(2)   # let controls settle
            start_t[0] = time.time()
            ticker = threading.Thread(target=_progress_ticker, daemon=True)
            ticker.start()
            cam.capture_file(fname)
        except Exception as e:
            logger.error("Light paint capture: %s", e)
            fname = ""
        finally:
            done[0] = True
            try:
                cam.stop()
                cam.configure(cam.create_preview_configuration(
                    main={"size": (_CAM_NATIVE_W, _CAM_NATIVE_H)},
                    transform=__import__("libcamera").Transform(hflip=1, vflip=1),
                ))
                cam.start()
            except Exception as e:
                logger.error("Light paint restore: %s", e)
            with _light_paint_lock:
                _light_paint_state.update({
                    "pending": False, "active": False,
                    "progress": 1.0,
                    "last_file": os.path.basename(fname) if fname else "",
                })


# ── Command processor ──────────────────────────────────────────────────────────
_MODE_MAP = {
    "_mode_user":       Mode.USER,
    "_mode_autonomous": Mode.AUTONOMOUS,
    "_mode_line":       Mode.LINE,
    # FACE is not a selectable mode — face scanning always runs
}


def _make_command_processor(motors, set_led, take_photo, toggle_video,
                             music, speed_levels):
    """Returns a closure that processes a single command string."""

    state = {
        "direction":     "STOPPED",
        "speed":         speed_levels[0],
        "speed_idx":     0,
        "ctrl_scheme":   1,
        "music_playing": False,
        "mode":          Mode.USER,
        "video_rec":     False,
    }

    def music_play():
        music.play_next()
        state["music_playing"] = True

    def music_stop():
        music.stop()
        state["music_playing"] = False

    state["_music_play"] = music_play
    state["_music_stop"] = music_stop

    def process(cmd: str, ctx: ModeContext) -> dict:
        cmd = cmd.strip().lower()

        if cmd in ("up", "forward"):
            motors.forward(state["speed"]);    set_led((0, 255, 0));   state["direction"] = "FORWARD"
        elif cmd in ("down", "backward"):
            motors.backward(state["speed"]);   set_led((255, 0, 0));   state["direction"] = "BACKWARD"
        elif cmd == "left":
            motors.turn_left(state["speed"]);  set_led((0, 0, 255));   state["direction"] = "LEFT"
        elif cmd == "right":
            motors.turn_right(state["speed"]); set_led((255, 255, 0)); state["direction"] = "RIGHT"
        elif cmd == "stop":
            motors.stop();                     set_led((0, 0, 0));     state["direction"] = "STOPPED"
        elif cmd == "tank_left_fwd":
            motors.left.forward(state["speed"])
        elif cmd == "tank_left_bwd":
            motors.left.backward(state["speed"])
        elif cmd == "tank_left_stop":
            motors.left.stop()
        elif cmd == "tank_right_fwd":
            motors.right.forward(state["speed"])
        elif cmd == "tank_right_bwd":
            motors.right.backward(state["speed"])
        elif cmd == "tank_right_stop":
            motors.right.stop()
        elif cmd == "photo":
            take_photo()
        elif cmd in ("video", "video_start"):
            if not state["video_rec"]:         toggle_video(state)
        elif cmd == "video_stop":
            if state["video_rec"]:             toggle_video(state)
        elif cmd in ("music", "play_music", "start_music"):
            if not state["music_playing"]:     music_play()
        elif cmd in ("stop_music", "pause_music"):
            music_stop()
        elif cmd in ("skip", "next_music", "skip_music"):
            music.play_next()
        elif cmd == "speed":
            state["speed_idx"] = (state["speed_idx"] + 1) % len(speed_levels)
            state["speed"]     = speed_levels[state["speed_idx"]]
        elif cmd.startswith("_speed_"):
            try:   state["speed"] = float(cmd[7:])
            except ValueError: pass
        elif cmd in _MODE_MAP:
            state["mode"] = switch_mode(state["mode"], _MODE_MAP[cmd], ctx)

        with _robot_state_lock:
            _robot_state.update(
                direction=state["direction"], speed=state["speed"],
                mode=state["mode"].name, video_rec=state["video_rec"],
                music_playing=state["music_playing"],
            )
        return state

    return process, state


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    pygame.init()
    info   = pygame.display.Info()
    W, H   = info.current_w, info.current_h
    screen = pygame.display.set_mode(
        (W, H), pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF)
    pygame.display.set_caption("KIDA")
    clock = pygame.time.Clock()

    TOP_H = 58;  BOT_H = 42;  PAD = 10
    L_W   = 290; R_W   = 300; TAB_H = 50

    CAM_AVAIL_W = W - L_W - R_W
    CAM_AVAIL_H = H - TOP_H - BOT_H
    CAM_W = int(CAM_AVAIL_W * 0.82);  CAM_H = int(CAM_AVAIL_H * 0.60)
    CAM_X = L_W + (CAM_AVAIL_W - CAM_W) // 2
    CAM_Y = TOP_H + TAB_H + PAD
    CAM_NATIVE_W, CAM_NATIVE_H = _CAM_NATIVE_W, _CAM_NATIVE_H

    # ── Fonts ──────────────────────────────────────────────────────────────────
    fmono_xl = pygame.font.SysFont("Courier New", 34, bold=True)
    fmono_md = pygame.font.SysFont("Courier New", 20, bold=True)
    fmono_sm = pygame.font.SysFont("Courier New", 17, bold=True)
    fmono_xs = pygame.font.SysFont("Courier New", 14)
    fbody    = pygame.font.SysFont("Arial", 18, bold=True)
    flabel   = pygame.font.SysFont("Arial", 17)
    flabel_s = pygame.font.SysFont("Arial", 15)
    fdpad    = pygame.font.SysFont("Arial", 32, bold=True)

    # ── Background threads ─────────────────────────────────────────────────────
    threading.Thread(target=run_flask,  daemon=True).start()
    start_stats_thread()
    start_face_thread()
    start_qr_thread()

    # ── Hardware ───────────────────────────────────────────────────────────────
    music  = MusicPlayer(os.path.join(_BASE, "audio", "music"))
    motors = MotorController()

    try:    avoider = ObstacleAvoidance(motors=motors)
    except Exception as e:
        logger.warning("ObstacleAvoidance init failed: %s", e);  avoider = None

    try:    liner = LineFollower(motors=motors)
    except Exception as e:
        logger.warning("LineFollower init failed: %s", e);  liner = None

    led = SPI_WS2812_LEDStrip(8, 128)

    cam = Picamera2()
    cam.configure(cam.create_preview_configuration(
        main={"size": (CAM_NATIVE_W, CAM_NATIVE_H)},
        transform=__import__("libcamera").Transform(hflip=1, vflip=1),
    ))
    cam.start()
    _encoder = H264Encoder(bitrate=4000000)

    if not led.ready:
        logger.error("SPI LED strip not ready — exiting.")
        pygame.quit();  return

    local_ip   = get_local_ip()
    qr_surf    = make_qr(f"http://{local_ip}:5003", size=130)
    photos_dir = os.path.join(_BASE, "photos")
    videos_dir = os.path.join(_BASE, "videos")
    face_dir   = os.path.join(_BASE, "faces")
    for d in (photos_dir, videos_dir, face_dir):
        os.makedirs(d, exist_ok=True)

    # ── LED helpers ────────────────────────────────────────────────────────────
    led_r = led_g = led_b = 0

    def set_led(color: tuple) -> None:
        nonlocal led_r, led_g, led_b
        led_r, led_g, led_b = color
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

    # ── Action helpers ─────────────────────────────────────────────────────────
    cam_pil         = None   # latest PIL frame; used by face snapshot
    _flash          = [0]    # frames remaining for white LED flash (photo)
    _video_fname    = [""]   # path of the currently recording video
    _qr_active      = [False]  # True while QR drive mode is active
    _prev_qr_action = [""]     # last QR action seen (one-shot dedup)

    # Dance
    _dance_stop_evt  = threading.Event()
    _dance_thread    = [None]

    # Audio analyzer (created in background when track changes)
    _last_track_name = [""]
    _analyzer_box    = [None]   # holds AudioAnalyzer instance or None

    def _load_analyzer_bg(path: str) -> None:
        try:
            _analyzer_box[0] = AudioAnalyzer(path, num_bars=24)
            logger.info("AudioAnalyzer ready for: %s", os.path.basename(path))
        except Exception as e:
            logger.warning("AudioAnalyzer failed: %s", e)
            _analyzer_box[0] = None

    def take_photo() -> None:
        fname = os.path.join(photos_dir, f"photo_{int(time.time())}.jpg")
        try:
            cam.capture_file(fname)
            _flash[0] = 10                                   # ~400 ms at 25 fps
            with _media_lock:
                _media_state["last_photo"] = os.path.basename(fname)
            logger.info("Photo saved: %s", fname)
        except Exception as e:
            logger.error("Photo failed: %s", e)

    def toggle_video(vs: dict) -> None:
        if not vs["video_rec"]:
            fname = os.path.join(videos_dir, f"video_{int(time.time())}.mp4")
            _video_fname[0] = fname
            try:
                cam.start_encoder(_encoder, FfmpegOutput(fname))
                vs["video_rec"] = True
                logger.info("Recording: %s", fname)
            except Exception as e:
                logger.error("Video start failed: %s", e)
        else:
            try:
                cam.stop_encoder()
            except Exception as e:
                logger.error("Video stop failed: %s", e)
            vs["video_rec"] = False
            if _video_fname[0]:
                with _media_lock:
                    _media_state["last_video"] = os.path.basename(_video_fname[0])
                _video_fname[0] = ""

    def save_face_snapshot() -> None:
        nonlocal cam_pil
        if cam_pil is None:
            return
        try:
            from PIL import ImageDraw
            pil_base = cam_pil.copy()
            draw = ImageDraw.Draw(pil_base)
            with _face_lock:
                faces = _face_results.copy()
            for face in faces:
                reg = face.get("region", {})
                x, y_ = reg.get("x", 0), reg.get("y", 0)
                w_, h_ = reg.get("w", 0), reg.get("h", 0)
                gender = face.get("gender", "?");  age = face.get("age", 0)
                col = (160, 80, 240) if gender == "Woman" else (20, 200, 170)
                draw.rectangle([x, y_, x + w_, y_ + h_], outline=col, width=2)
                draw.text((x + 2, y_ - 14), f"{gender[0]} {age}y", fill=col)
            fname = os.path.join(face_dir, f"face_{int(time.time())}.jpg")
            pil_base.save(fname, "JPEG");  logger.info("Face snapshot: %s", fname)
        except Exception as e: logger.error("Face snapshot failed: %s", e)

    # ── Command processor + shared drive state ─────────────────────────────────
    speed_levels = [0.4, 0.6, 0.8, 1.0]
    process_cmd, ds = _make_command_processor(
        motors, set_led, take_photo, toggle_video, music, speed_levels
    )

    def music_play():  ds["_music_play"]()
    def music_stop():  ds["_music_stop"]()

    # ── QR drive mode helpers ──────────────────────────────────────────────────
    _QR_HOLD = frozenset({"forward", "backward", "left", "right"})

    def _fire_qr_oneshot(action: str) -> None:
        """Execute a one-shot QR action. Called at most once per new QR code."""
        if action == "play_music":
            music_play()
        elif action == "stop_music":
            music_stop()
        elif action == "next_song":
            music.play_next()
        elif action == "light_paint":
            with _light_paint_lock:
                if not _light_paint_state["active"]:
                    _light_paint_state.update({
                        "pending": True, "duration": 10,
                        "progress": 0.0, "last_file": "",
                    })
        elif action == "stop":
            motors.stop();  ds["direction"] = "STOPPED"
            if ds["video_rec"]:
                toggle_video(ds)
        elif action == "dance":
            stop_dance_mode() if _dance_active.is_set() else start_dance_mode()
        elif action == "sleep":
            enter_sleep()
        elif action == "wake":
            exit_sleep()
        elif action == "mode_user":
            _qr_active[0] = False;  _qr_enabled.clear()
            with _qr_lock: _qr_state["action"] = ""
            ds["mode"] = switch_mode(ds["mode"], Mode.USER, ctx)
        elif action == "mode_autonomous":
            _qr_active[0] = False;  _qr_enabled.clear()
            with _qr_lock: _qr_state["action"] = ""
            ds["mode"] = switch_mode(ds["mode"], Mode.AUTONOMOUS, ctx)
        elif action == "mode_line":
            _qr_active[0] = False;  _qr_enabled.clear()
            with _qr_lock: _qr_state["action"] = ""
            ds["mode"] = switch_mode(ds["mode"], Mode.LINE, ctx)

    # ── Dance / sleep helpers ──────────────────────────────────────────────────
    def start_dance_mode() -> None:
        if _dance_active.is_set():
            return
        music_play()
        _dance_active.set()
        _dance_thread[0] = start_dance(motors, led, _dance_stop_evt, ds["speed"])
        logger.info("Dance mode started")

    def stop_dance_mode() -> None:
        if not _dance_active.is_set():
            return
        _dance_stop_evt.set()
        _dance_active.clear()
        logger.info("Dance mode stopped")

    def enter_sleep() -> None:
        if _sleep_active.is_set():
            return
        motors.stop();  ds["direction"] = "STOPPED"
        _face_enabled.clear()
        _sleep_active.set()
        logger.info("Sleep mode entered")

    def exit_sleep() -> None:
        if not _sleep_active.is_set():
            return
        _sleep_active.clear()
        _face_enabled.set()
        logger.info("Sleep mode exited")

    # ── UI layout ──────────────────────────────────────────────────────────────
    TAB_LABELS = ["USER CTRL", "AUTONOMOUS", "LINE FOLLOW"]
    tab_w  = min(160, (CAM_AVAIL_W - PAD * 4) // 3)
    tab_x0 = L_W + (CAM_AVAIL_W - (tab_w * 3 + PAD * 2)) // 2
    tabs   = [pygame.Rect(tab_x0 + i * (tab_w + PAD), TOP_H + 6, tab_w, TAB_H - 12)
              for i in range(3)]

    DP_S = 76;  DP_G = 10
    DP_CX = W - R_W + (R_W - DP_S) // 2
    DP_Y  = TOP_H + TAB_H + PAD + 10
    dpad = {
        "forward":  pygame.Rect(DP_CX,               DP_Y,                      DP_S, DP_S),
        "left":     pygame.Rect(DP_CX - DP_S - DP_G, DP_Y + DP_S + DP_G,       DP_S, DP_S),
        "stop":     pygame.Rect(DP_CX,               DP_Y + DP_S + DP_G,        DP_S, DP_S),
        "right":    pygame.Rect(DP_CX + DP_S + DP_G, DP_Y + DP_S + DP_G,       DP_S, DP_S),
        "backward": pygame.Rect(DP_CX,               DP_Y + (DP_S + DP_G) * 2, DP_S, DP_S),
    }
    DPAD_GLYPHS = {"forward": "▲", "left": "◀", "stop": "■", "right": "▶", "backward": "▼"}

    rp_x = W - R_W + PAD;  rp_w = R_W - PAD * 2
    spd_y = DP_Y + (DP_S + DP_G) * 3 + 22
    spd_w = (rp_w - DP_G * 3) // 4;  spd_h = 44
    spd_dots = [pygame.Rect(rp_x + i * (spd_w + DP_G), spd_y, spd_w, spd_h) for i in range(4)]

    sch_y = spd_y + spd_h + 26;  sch_w = (rp_w - DP_G) // 2;  sch_h = 44
    sch_btns = [
        pygame.Rect(rp_x,                sch_y, sch_w, sch_h),
        pygame.Rect(rp_x + sch_w + DP_G, sch_y, sch_w, sch_h),
    ]

    cap_y = sch_y + sch_h + 26;  cap_w = (rp_w - DP_G) // 2;  cap_h = 48
    btn_photo      = pygame.Rect(rp_x,                cap_y, cap_w, cap_h)
    btn_video      = pygame.Rect(rp_x + cap_w + DP_G, cap_y, cap_w, cap_h)
    btn_face_snap  = pygame.Rect(rp_x, cap_y + cap_h + 10, cap_w, 44)
    btn_face_scan  = pygame.Rect(rp_x + cap_w + DP_G, cap_y + cap_h + 10, cap_w, 44)

    lp_x = PAD;  lp_w = L_W - PAD * 2
    mus_btn_y = H - BOT_H - 76;  mus_btn_h = 48;  mus_btn_w = (lp_w - DP_G) // 2
    btn_play = pygame.Rect(lp_x,                    mus_btn_y, mus_btn_w, mus_btn_h)
    btn_skip = pygame.Rect(lp_x + mus_btn_w + DP_G, mus_btn_y, mus_btn_w, mus_btn_h)

    bg_surf = build_background(W, H, TOP_H, BOT_H, L_W, R_W)

    # Face scanning is always on — enable now and never toggle
    _face_enabled.set()

    # ── Per-frame state ────────────────────────────────────────────────────────
    frame    = 0
    cam_surf = pygame.Surface((CAM_W, CAM_H));  cam_surf.fill((8, 10, 14))
    cam_tick = 0;  face_tick = 0

    # ── Main loop ──────────────────────────────────────────────────────────────
    running = True
    while running:
        mouse = pygame.mouse.get_pos()

        with _stats_lock:
            st = _system_stats.copy()

        cpu_pct  = min(st.get("cpu", 0)  / 100.0, 1.0)
        temp_c   = st.get("temp", 0)
        temp_pct = min(temp_c / 85.0, 1.0)
        ram_u    = st.get("ram_used",  0)
        ram_t    = st.get("ram_total", 1)
        ram_pct  = min(ram_u / max(ram_t, 1), 1.0)

        # Light paint — start if pending
        with _light_paint_lock:
            _lp_pending = _light_paint_state["pending"]
            _lp_dur     = _light_paint_state["duration"]
        if _lp_pending:
            with _light_paint_lock:
                _light_paint_state["pending"] = False
            threading.Thread(
                target=_do_light_paint, args=(cam, _lp_dur, photos_dir),
                daemon=True, name="light-paint",
            ).start()

        # Camera frame — skip during sleep or while light paint holds the lock
        cam_tick += 1
        if cam_tick >= 3 and not _sleep_active.is_set():
            cam_tick = 0
            if _cam_lock.acquire(blocking=False):
                try:
                    cam_surf, cam_pil = cam_to_surface(cam, CAM_W, CAM_H, _CAM_ROTATION)
                    if cam_pil is not None:
                        buf = io.BytesIO()
                        cam_pil.save(buf, "JPEG", quality=70)
                        with _cam_jpeg_lock:
                            _cam_jpeg[0] = buf.getvalue()
                finally:
                    _cam_lock.release()

        # Feed face worker every ~45 frames (always-on face scanning)
        face_tick += 1
        if face_tick >= 45 and cam_pil is not None and not _sleep_active.is_set():
            face_tick = 0
            try:    _face_frame_q.put_nowait(cam_pil.copy())
            except queue.Full: pass

        # Reload audio analyzer when track changes
        if music.current_track != _last_track_name[0]:
            _last_track_name[0] = music.current_track
            _analyzer_box[0]    = None
            with _robot_state_lock:
                _robot_state["track_name"] = music.current_track
            if music.playing and music.current_path:
                threading.Thread(
                    target=_load_analyzer_bg, args=(music.current_path,),
                    daemon=True, name="audio-analyze",
                ).start()

        # Compute amplitudes from analyzer; share with web UI via shared_state
        amplitudes = None
        _cur_analyzer = _analyzer_box[0]
        if ds["music_playing"] and _cur_analyzer is not None:
            try:
                amplitudes = _cur_analyzer.get_amplitudes(
                    pygame.mixer.music.get_pos() / 1000.0)
                with _audio_amps_lock:
                    _audio_amps[:] = amplitudes
            except Exception:
                pass
        elif not ds["music_playing"]:
            with _audio_amps_lock:
                _audio_amps.clear()

        with _face_lock:
            face_snapshot = _face_results.copy()
        face_count = len(face_snapshot)

        # ── Render ─────────────────────────────────────────────────────────────
        if _sleep_active.is_set():
            render_sleep_screen(screen, fmono_xl, fmono_sm, W, H, frame)
        else:
            screen.blit(bg_surf, (0, 0))

            render_camera(screen, cam_surf, face_snapshot, frame, ds["video_rec"],
                          ds["mode"], CAM_X, CAM_Y, CAM_W, CAM_H,
                          CAM_NATIVE_W, CAM_NATIVE_H,
                          fmono_sm, fmono_xs, _deepface_ok.is_set(), True)

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
                               True,
                               rp_x, spd_y, sch_y, cap_y, TOP_H, PAD, mouse,
                               fmono_md, fmono_xs, fbody, fdpad)

        render_bottom_bar(screen, ds["mode"], ds["ctrl_scheme"], ds["speed"],
                          face_count, frame, W, H, BOT_H, fmono_xs)

        # ── Events ─────────────────────────────────────────────────────────────
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == getattr(music, "SONG_END", -1):
                music.handle_event(event)
                ds["music_playing"] = music.playing

            elif event.type == pygame.KEYDOWN:
                k = event.key
                if _sleep_active.is_set():
                    exit_sleep()   # any key wakes
                    continue
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
                elif ds["mode"] == Mode.USER:
                    if   k == pygame.K_x:               # ← cycle speed
                        ds["speed_idx"] = (ds["speed_idx"] + 1) % len(speed_levels)
                        ds["speed"]     = speed_levels[ds["speed_idx"]]
                    elif k == pygame.K_1: ds["ctrl_scheme"] = 1  # ← WASD
                    elif k == pygame.K_2: ds["ctrl_scheme"] = 2  # ← QA/WS
                    elif k == pygame.K_c: take_photo()
                    elif k == pygame.K_v: toggle_video(ds)
                    elif k == pygame.K_s: save_face_snapshot()

            elif event.type == pygame.MOUSEBUTTONDOWN:
                for i, tr in enumerate(tabs):
                    if tr.collidepoint(event.pos):
                        ds["mode"] = switch_mode(ds["mode"], Mode(i), ctx)

                if ds["mode"] == Mode.USER:
                    for cmd, r in dpad.items():
                        if r.collidepoint(event.pos):
                            if   cmd == "forward":  motors.forward(ds["speed"]);    set_led((0, 255, 0))
                            elif cmd == "backward": motors.backward(ds["speed"]);   set_led((255, 0, 0))
                            elif cmd == "left":     motors.turn_left(ds["speed"]);  set_led((0, 0, 255))
                            elif cmd == "right":    motors.turn_right(ds["speed"]); set_led((255, 255, 0))
                            elif cmd == "stop":     motors.stop();                  set_led((0, 0, 0))
                            ds["direction"] = cmd.upper()
                    for i, r in enumerate(spd_dots):
                        if r.collidepoint(event.pos):
                            ds["speed_idx"] = i
                            ds["speed"]     = speed_levels[ds["speed_idx"]]
                    for i, r in enumerate(sch_btns):
                        if r.collidepoint(event.pos): ds["ctrl_scheme"] = i + 1
                    if btn_photo.collidepoint(event.pos): take_photo()
                    if btn_video.collidepoint(event.pos): toggle_video(ds)

                if btn_face_snap.collidepoint(event.pos):
                    save_face_snapshot()
                if btn_play.collidepoint(event.pos):
                    music_stop() if ds["music_playing"] else music_play()
                if btn_skip.collidepoint(event.pos) and ds["music_playing"]:
                    music.play_next()

        # Flask command queue
        while not command_queue.empty():
            cmd = command_queue.get_nowait()
            if cmd == "dance_start":
                start_dance_mode()
            elif cmd == "dance_stop":
                stop_dance_mode()
            elif cmd == "sleep":
                enter_sleep()
            elif cmd == "wake":
                exit_sleep()
            elif cmd == "_mode_qr":
                _qr_active[0] = True
                _qr_enabled.set()
                motors.stop();  ds["direction"] = "STOPPED"
                with _robot_state_lock:
                    _robot_state["mode"] = "QR"
            else:
                if _qr_active[0] and cmd.startswith("_mode_"):
                    _qr_active[0] = False
                    _qr_enabled.clear()
                    with _qr_lock: _qr_state["action"] = ""
                    _prev_qr_action[0] = ""
                process_cmd(cmd, ctx)

        # ── Drive logic ─────────────────────────────────────────────────────────
        mode = None   # assigned below when not in a special mode

        # Auto-stop dance when song ends
        if _dance_active.is_set() and not ds["music_playing"]:
            stop_dance_mode()

        if _dance_active.is_set():
            # Dance thread owns motors + LEDs — main loop stays hands-off
            with _robot_state_lock:
                _robot_state["mode"] = "DANCE"

        elif _sleep_active.is_set():
            # Sleep: motors already stopped; LEDs handled after drive logic
            with _robot_state_lock:
                _robot_state["mode"] = "SLEEP"

        elif _qr_active[0]:
            # Feed latest PIL frame to QR reader
            if cam_pil is not None:
                try:    _qr_frame_q.put_nowait(cam_pil.copy())
                except queue.Full: pass

            with _qr_lock:
                qr_action = _qr_state["action"]

            if qr_action in _QR_HOLD:
                if   qr_action == "forward":   motors.forward(ds["speed"]);    ds["direction"] = "FORWARD"
                elif qr_action == "backward":  motors.backward(ds["speed"]);   ds["direction"] = "BACKWARD"
                elif qr_action == "left":      motors.turn_left(ds["speed"]);  ds["direction"] = "LEFT"
                elif qr_action == "right":     motors.turn_right(ds["speed"]); ds["direction"] = "RIGHT"
            else:
                if _prev_qr_action[0] in _QR_HOLD:
                    motors.stop();  ds["direction"] = "STOPPED"
                if qr_action and qr_action != _prev_qr_action[0]:
                    _fire_qr_oneshot(qr_action)

            _prev_qr_action[0] = qr_action
            with _robot_state_lock:
                _robot_state["mode"] = "QR"

        else:
            mode = ds["mode"]

        if not _qr_active[0] and mode == Mode.AUTONOMOUS:
            if avoider:
                try:
                    if avoider.check_and_avoid(): set_led((255, 0, 0))
                except Exception as e: logger.warning("Avoider: %s", e)
            else:
                motors.stop()

        elif mode == Mode.LINE:
            if liner:
                try:    liner.follow_line()
                except Exception as e: logger.warning("LineFollower: %s", e)
            else:
                motors.stop()

        elif mode == Mode.USER:
            keys = pygame.key.get_pressed()
            if ds["ctrl_scheme"] == 1:
                # ── WASD (press 1) ─────────────────────────────────────────────
                if   keys[pygame.K_w]: motors.forward(ds["speed"]);    set_led((0, 255, 0));   ds["direction"] = "FORWARD"
                elif keys[pygame.K_s]: motors.backward(ds["speed"]);   set_led((255, 0, 0));   ds["direction"] = "BACKWARD"
                elif keys[pygame.K_a]: motors.turn_left(ds["speed"]);  set_led((0, 0, 255));   ds["direction"] = "LEFT"
                elif keys[pygame.K_d]: motors.turn_right(ds["speed"]); set_led((255, 255, 0)); ds["direction"] = "RIGHT"
                else:                  motors.stop();                  set_led((0, 0, 0));     ds["direction"] = "STOPPED"
            else:
                # ── QA/WS tank (press 2) ───────────────────────────────────────
                left, right = motors.control_tank(keys, ds["speed"])
                if left and right:  set_led((0, 255, 255))
                elif left:          set_led((255, 0, 255))
                elif right:         set_led((255, 165, 0))
                else:               set_led((0, 0, 0))

        # ── LED effects ─────────────────────────────────────────────────────────
        # Dance thread owns LEDs while active; sleep has its own breathing effect
        if _dance_active.is_set():
            pass   # dance loop calls led.show() on its own thread
        elif _sleep_active.is_set():
            sleep_breathe(led, frame)
        elif _flash[0] > 0:
            led.set_all_led_color(255, 255, 255)
            _flash[0] -= 1
        elif ds["video_rec"]:
            bright = int((math.sin(frame * 0.08) * 0.5 + 0.5) * 200 + 55)
            led.set_all_led_color(bright, 0, 0)
        elif ds["music_playing"]:
            led.rhythm_wave(frame)
        else:
            led.show()
        frame += 1
        pygame.display.flip()
        clock.tick(25)

    # ── Cleanup ────────────────────────────────────────────────────────────────
    logger.info("Shutting down…")
    shutdown_zeroconf()
    if _dance_active.is_set():
        _dance_stop_evt.set()
        _dance_active.clear()
    _sleep_active.clear()
    switch_mode(ds["mode"], Mode.USER, ctx)
    _face_enabled.clear()
    _qr_enabled.clear()
    if ds["video_rec"]:
        try: cam.stop_encoder()
        except Exception: pass
    motors.cleanup()
    if avoider: avoider.cleanup()
    if liner:   liner.cleanup()
    led.led_close()
    try: cam.stop()
    except Exception: pass
    pygame.quit()


if __name__ == "__main__":
    main()