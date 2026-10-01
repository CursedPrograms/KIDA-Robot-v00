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
    python main.py <robot-ip-or-url> [--port 5003] [--fullscreen]
    ROBOT_URL=http://192.168.1.50:5003 python main.py
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
sys.path.insert(0, _SCRIPTS_DIR)   # hud_layout, render_helpers, mode_control

import pygame

import hud_layout
from mode_control   import Mode
from render_helpers import (
    hline, vline, txt,
    render_camera, render_info_strip, render_top_bar,
    render_left_panel, render_right_panel, render_bottom_bar,
    build_background, RED, CAM_BG,
)
from remote_client  import RemoteClient

APP_NAME     = "KIDA — Remote Controller"
HEARTBEAT_S  = 0.25   # the robot stops a remote drive it hasn't heard for 0.8 s
MIN_W, MIN_H = 1100, 720


def _resolve_robot_url() -> tuple:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("robot", nargs="?", default=os.environ.get("ROBOT_URL"),
                        help="Robot IP or URL, e.g. 192.168.1.50 or http://192.168.1.50:5003")
    parser.add_argument("--port", type=int, default=5003)
    parser.add_argument("--fullscreen", action="store_true")
    args = parser.parse_args()
    if not args.robot:
        parser.error("robot IP/URL required (positional arg, or ROBOT_URL env var)")
    robot = args.robot if args.robot.startswith("http") else f"http://{args.robot}:{args.port}"
    return robot, args.fullscreen


def _mode_of(status: dict) -> Mode:
    try:
        return Mode[status.get("mode", "USER")]
    except KeyError:
        return Mode.USER


def _mode_cmd(mode: Mode) -> str:
    return f"_mode_{mode.name.lower()}"


def run_controller() -> None:
    base_url, fullscreen = _resolve_robot_url()
    print(f"{APP_NAME} - connecting to {base_url}")
    remote = RemoteClient(base_url)

    pygame.init()
    pygame.display.set_caption(APP_NAME)
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
        cs  = pygame.Surface((lay["CAM_W"], lay["CAM_H"]));  cs.fill(CAM_BG)
        return lay, bg, cs

    lay, bg_surf, cam_surf = relayout(W, H)
    cam_seq  = -1
    qr_surf  = pygame.Surface((130, 130));  qr_surf.fill((255, 255, 255))
    have_qr  = False
    host_ip  = urlparse(base_url).hostname or base_url

    frame     = 0
    hold_dir  = None     # on-screen d-pad held with the mouse
    last_sent = None     # last drive intent sent
    last_beat = 0.0

    print("Keys (same as the robot): TAB=cycle mode  U/O/L=user/auto/line  M=music  SPACE=stop music  X=speed (user + auto)")
    print("   USER mode: WASD or QA/WS drive  1/2=scheme  C=photo  V=video  F=save faces  ESC=quit")

    running = True
    while running:
        mouse  = pygame.mouse.get_pos()
        status = remote.status
        st     = remote.stats

        mode        = _mode_of(status)
        direction   = status.get("direction", "STOPPED")
        speed       = status.get("speed", hud_layout.SPEED_LEVELS[0])
        speed_idx   = status.get("speed_idx", 0)
        ctrl_scheme = status.get("ctrl_scheme", 1)
        video_rec   = status.get("video_rec", False)
        music_on    = status.get("music_playing", False)
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
                           TOP_H, PAD, mouse, fmono_md, fmono_xs, fbody, fdpad)

        render_bottom_bar(screen, mode, ctrl_scheme, speed, len(faces),
                          status.get("frame", frame), W, H, BOT_H, fmono_xs,
                          online=remote.connected)

        if not remote.connected:
            txt(screen, fmono_md, "[ NO CONNECTION TO ROBOT ]",
                (W // 2, TOP_H + lay["CAM_H"] // 2 + 60), RED, anchor="center")

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
                if   k == pygame.K_ESCAPE:
                    running = False
                elif k == pygame.K_TAB:
                    remote.send(_mode_cmd(Mode((int(mode) + 1) % 3)))
                elif k == pygame.K_m:
                    remote.send("play_music")
                elif k == pygame.K_SPACE:
                    remote.send("stop_music")
                elif k == pygame.K_u:
                    remote.send(_mode_cmd(Mode.USER))
                elif k == pygame.K_o:
                    remote.send(_mode_cmd(Mode.AUTONOMOUS))
                elif k == pygame.K_l:
                    remote.send(_mode_cmd(Mode.LINE))
                elif k == pygame.K_x and mode in (Mode.USER, Mode.AUTONOMOUS):
                    remote.send("speed")   # autonomous cruises at the selected speed too
                elif mode == Mode.USER:
                    if   k == pygame.K_1: remote.send("scheme_1")
                    elif k == pygame.K_2: remote.send("scheme_2")
                    elif k == pygame.K_c: remote.send("photo")
                    elif k == pygame.K_v: remote.send("video_toggle")
                    elif k == pygame.K_f: remote.send("face_save")   # not S — that drives

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                pos = event.pos
                for i, tr in enumerate(lay["tabs"]):
                    if tr.collidepoint(pos):
                        remote.send(_mode_cmd(Mode(i)))

                if mode == Mode.USER:
                    for cmd, r in lay["dpad"].items():
                        if r.collidepoint(pos):
                            hold_dir = None if cmd == "stop" else cmd
                            if cmd == "stop":
                                remote.send("stop")
                    for i, r in enumerate(lay["sch_btns"]):
                        if r.collidepoint(pos): remote.send(f"scheme_{i + 1}")
                    if lay["btn_photo"].collidepoint(pos): remote.send("photo")
                    if lay["btn_video"].collidepoint(pos): remote.send("video_toggle")

                if mode in (Mode.USER, Mode.AUTONOMOUS):
                    for i, r in enumerate(lay["spd_dots"]):
                        if r.collidepoint(pos): remote.send(f"speed_{i + 1}")

                if lay["btn_face_snap"].collidepoint(pos): remote.send("face_save")
                if lay["btn_face_scan"].collidepoint(pos): remote.send("face_scan_toggle")
                if lay["btn_play"].collidepoint(pos):      remote.send("music_toggle")
                if lay["btn_skip"].collidepoint(pos) and music_on:
                    remote.send("skip_music")

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                hold_dir = None

        # ── Drive — held keys / d-pad become a resent intent (dead-man) ───────
        intent = None
        if mode == Mode.USER and pygame.key.get_focused():
            keys = pygame.key.get_pressed()
            if ctrl_scheme == 1 and any(keys[k] for k in (pygame.K_w, pygame.K_s, pygame.K_a, pygame.K_d)):
                intent = ("forward"  if keys[pygame.K_w] else
                          "backward" if keys[pygame.K_s] else
                          "left"     if keys[pygame.K_a] else "right")
            elif ctrl_scheme == 2 and any(keys[k] for k in (pygame.K_q, pygame.K_a, pygame.K_w, pygame.K_s)):
                l = 1 if keys[pygame.K_q] else -1 if keys[pygame.K_a] else 0
                r = 1 if keys[pygame.K_w] else -1 if keys[pygame.K_s] else 0
                intent = f"tank:{l}:{r}"
            elif hold_dir:
                intent = hold_dir

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
    remote.send_now("stop")
    remote.stop()
    pygame.quit()
    print("Controller closed")


if __name__ == "__main__":
    run_controller()
