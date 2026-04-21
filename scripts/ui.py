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

import logging
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
)
from scripts.server    import run_flask, shutdown_zeroconf
from system_monitor    import start_stats_thread, get_local_ip
from face_detector     import start_face_thread
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


# ── Command processor ──────────────────────────────────────────────────────────
_MODE_MAP = {
    "_mode_user":       Mode.USER,
    "_mode_autonomous": Mode.AUTONOMOUS,
    "_mode_line":       Mode.LINE,
    "_mode_face":       Mode.FACE,
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
    CAM_NATIVE_W, CAM_NATIVE_H = 320, 240

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

    # ── Hardware ───────────────────────────────────────────────────────────────
    music  = MusicPlayer("/home/nova/Desktop/kida/audio/music/")
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
    photos_dir = "../kida/photos"
    videos_dir = "../kida/videos"
    face_dir   = "../kida/faces"
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

    # Face scanning runs in all modes — enable immediately
    face_scan_active = True
    _face_enabled.set()

    # ── Per-frame state ────────────────────────────────────────────────────────
    frame    = 0
    cam_surf = pygame.Surface((CAM_W, CAM_H));  cam_surf.fill((8, 10, 14))
    cam_tick = 0;  face_tick = 0
    analyzer: AudioAnalyzer | None = None

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

        # Camera frame
        cam_tick += 1
        if cam_tick >= 3:
            cam_tick = 0
            cam_surf, cam_pil = cam_to_surface(cam, CAM_W, CAM_H)

        # Feed face worker in all modes when scanning is active
        if face_scan_active:
            face_tick += 1
            if face_tick >= 45 and cam_pil is not None:
                face_tick = 0
                try:    _face_frame_q.put_nowait(cam_pil.copy())
                except queue.Full: pass
        else:
            face_tick = 0

        # Audio amplitudes
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
                      fmono_sm, fmono_xs, _deepface_ok.is_set(), face_scan_active)

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
                           face_scan_active,
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
                if btn_face_scan.collidepoint(event.pos):
                    face_scan_active = not face_scan_active
                    if face_scan_active:
                        _face_enabled.set()
                    else:
                        _face_enabled.clear()
                        with _face_lock:
                            _face_results.clear()
                if btn_play.collidepoint(event.pos):
                    music_stop() if ds["music_playing"] else music_play()
                if btn_skip.collidepoint(event.pos) and ds["music_playing"]:
                    music.play_next()

        # Flask command queue
        while not command_queue.empty():
            process_cmd(command_queue.get_nowait(), ctx)

        # ── Drive logic ─────────────────────────────────────────────────────────
        mode = ds["mode"]

        if mode == Mode.AUTONOMOUS:
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

        if ds["music_playing"]:
            led.rhythm_wave(frame)

        led.show()
        frame += 1
        pygame.display.flip()
        clock.tick(25)

    # ── Cleanup ────────────────────────────────────────────────────────────────
    logger.info("Shutting down…")
    shutdown_zeroconf()
    switch_mode(ds["mode"], Mode.USER, ctx)
    _face_enabled.clear()
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