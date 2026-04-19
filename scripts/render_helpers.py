"""
render_helpers.py — All pygame draw primitives and named render sections.
No mutable global state — everything is passed as arguments.
"""

import math
import pygame
from mode_control import Mode

# ── Palette ───────────────────────────────────────────────────────────────────
BG     = (8,   9,  13)
PANEL  = (14,  15,  22)
BORDER = (32,  35,  52)
ACCENT = (255,  30, 100)
GREEN  = (29,  200, 120)
BLUE   = (55,  138, 221)
AMBER  = (255, 160,  40)
RED    = (226,  75,  74)
TEAL   = (20,  200, 170)
PURPLE = (160,  80, 240)
PRI    = (230, 230, 225)
SEC    = (130, 132, 125)
DIM    = (60,   62,  75)


# ── Primitives ─────────────────────────────────────────────────────────────────
def hline(surf, y, x0, x1, color=BORDER):
    pygame.draw.line(surf, color, (x0, y), (x1, y))

def vline(surf, x, y0, y1, color=BORDER):
    pygame.draw.line(surf, color, (x, y0), (x, y1))

def txt(surf, font, text, pos, color=PRI, anchor="topleft"):
    s = font.render(str(text), True, color)
    r = s.get_rect(**{anchor: pos})
    surf.blit(s, r)
    return r

def bar(surf, r, pct, color, track=(18, 20, 32)):
    pygame.draw.rect(surf, track, r, border_radius=3)
    fw = max(int(r.width * min(pct, 1.0)), 0)
    if fw:
        pygame.draw.rect(surf, color, pygame.Rect(r.x, r.y, fw, r.height), border_radius=3)

def led_dot(surf, pos, color, r=6):
    pygame.draw.circle(surf, color, pos, r)

def btn(surf, font, label, r, mouse, active=False, danger=False, hover_col=ACCENT):
    hov = r.collidepoint(mouse)
    if danger:
        bc, bd, tc = (28, 10, 10), RED, RED
    elif hov or active:
        bc, bd, tc = (22, 10, 18), hover_col, hover_col
    else:
        bc, bd, tc = PANEL, BORDER, SEC
    pygame.draw.rect(surf, bc, r, border_radius=8)
    pygame.draw.rect(surf, bd, r, width=1, border_radius=8)
    if active and not danger:
        pygame.draw.rect(surf, hover_col,
                         pygame.Rect(r.x + 6, r.bottom - 3, r.width - 12, 3),
                         border_radius=2)
    s = font.render(label, True, tc)
    surf.blit(s, (r.x + (r.width - s.get_width()) // 2,
                  r.y + (r.height - s.get_height()) // 2))

def section_label(surf, font, text, x, y):
    pygame.draw.rect(surf, ACCENT, pygame.Rect(x, y + 2, 3, 12))
    txt(surf, font, text, (x + 9, y), DIM)

def waveform(surf, frame: int, r: pygame.Rect, bars: int = 22,
             playing: bool = False, amplitudes: list | None = None):
    bw = max(r.width // bars, 2)
    for i in range(bars):
        if amplitudes is not None:
            idx = int(i * len(amplitudes) / bars)
            h   = max(int(amplitudes[idx] * r.height * 0.92), 3)
            col = (*ACCENT, 180)
        elif playing:
            h   = int((math.sin(frame * 0.12 + i * 0.3) * 0.5 + 0.5) * r.height * 0.85 + 3)
            col = (*ACCENT, 140)
        else:
            h, col = 3, (*DIM, 80)
        s = pygame.Surface((max(bw - 1, 1), h), pygame.SRCALPHA)
        s.fill(col)
        surf.blit(s, (r.x + i * bw, r.y + r.height - h))


# ── Named sections ─────────────────────────────────────────────────────────────
def render_camera(screen, cam_surf, faces, frame, video_rec, mode,
                  CAM_X, CAM_Y, CAM_W, CAM_H, CAM_NATIVE_W, CAM_NATIVE_H,
                  fmono_sm, fmono_xs, deepface_ok, face_scan_active=True):
    screen.blit(cam_surf, (CAM_X, CAM_Y))
    pygame.draw.rect(screen, BORDER,
                     pygame.Rect(CAM_X - 1, CAM_Y - 1, CAM_W + 2, CAM_H + 2), 1)

    # Face overlays — always drawn in any mode when scanning is active
    if face_scan_active:
        if faces:
            render_face_overlays(screen, faces, CAM_X, CAM_Y, CAM_W, CAM_H,
                                 CAM_NATIVE_W, CAM_NATIVE_H, fmono_sm, fmono_xs)
        elif not deepface_ok:
            txt(screen, fmono_xs, "DEEPFACE NOT INSTALLED",
                (CAM_X + 6, CAM_Y + 6), RED)
        else:
            # Subtle scan line so you know it's working
            scan_y = CAM_Y + int((math.sin(frame * 0.08) * 0.5 + 0.5) * CAM_H)
            sl = pygame.Surface((CAM_W, 1), pygame.SRCALPHA)
            sl.fill((*PURPLE, 55))
            screen.blit(sl, (CAM_X, scan_y))

    # Mode-specific overlay text at bottom of camera
    if mode == Mode.AUTONOMOUS:
        _cam_overlay(screen, "— AUTONOMOUS —", TEAL, CAM_X, CAM_Y, CAM_W, CAM_H, fmono_sm)
    elif mode == Mode.LINE:
        _cam_overlay(screen, "— LINE FOLLOW —", BLUE, CAM_X, CAM_Y, CAM_W, CAM_H, fmono_sm)

    blen = 22
    for (cx, cy, sx, sy) in [
        (CAM_X + 5,         CAM_Y + 5,           1,  1),
        (CAM_X + CAM_W - 5, CAM_Y + 5,          -1,  1),
        (CAM_X + 5,         CAM_Y + CAM_H - 5,   1, -1),
        (CAM_X + CAM_W - 5, CAM_Y + CAM_H - 5,  -1, -1),
    ]:
        pygame.draw.line(screen, ACCENT, (cx, cy), (cx + sx * blen, cy), 2)
        pygame.draw.line(screen, ACCENT, (cx, cy), (cx, cy + sy * blen), 2)

    if video_rec and (frame // 12) % 2 == 0:
        pygame.draw.circle(screen, RED, (CAM_X + CAM_W - 18, CAM_Y + 12), 6)
        txt(screen, fmono_xs, "REC", (CAM_X + CAM_W - 10, CAM_Y + 7), RED)


def _cam_overlay(screen, msg, color, CAM_X, CAM_Y, CAM_W, CAM_H, font):
    ms = font.render(msg, True, color)
    mx = CAM_X + (CAM_W - ms.get_width()) // 2
    my = CAM_Y + CAM_H - 28
    ov = pygame.Surface((ms.get_width() + 16, ms.get_height() + 8), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 140))
    screen.blit(ov, (mx - 8, my - 4))
    screen.blit(ms, (mx, my))


def render_face_overlays(screen, faces, cam_x, cam_y, cam_w, cam_h,
                         native_w, native_h, font_sm, font_xs):
    sx = cam_w / native_w
    sy = cam_h / native_h
    for face in faces:
        reg = face.get("region", {})
        if not reg:
            continue
        x  = int(reg.get("x", 0) * sx) + cam_x
        y  = int(reg.get("y", 0) * sy) + cam_y
        fw = int(reg.get("w", 0) * sx)
        fh = int(reg.get("h", 0) * sy)
        if fw < 4 or fh < 4:
            continue
        gender  = face.get("gender", "?")
        age     = face.get("age", 0)
        conf    = face.get("conf", 0)
        box_col = PURPLE if gender == "Woman" else TEAL
        pygame.draw.rect(screen, box_col, pygame.Rect(x, y, fw, fh), 2, border_radius=4)
        tlen = min(14, fw // 4)
        for (cx, cy, dx, dy) in [
            (x,      y,      1,  1), (x + fw, y,      -1,  1),
            (x,      y + fh, 1, -1), (x + fw, y + fh, -1, -1),
        ]:
            pygame.draw.line(screen, box_col, (cx, cy), (cx + dx * tlen, cy), 2)
            pygame.draw.line(screen, box_col, (cx, cy), (cx, cy + dy * tlen), 2)
        label  = f"{gender[0]}  {age}y  {conf:.0f}%"
        ls     = font_sm.render(label, True, box_col)
        tag_r  = pygame.Rect(x, y - ls.get_height() - 6, ls.get_width() + 10, ls.get_height() + 4)
        tag_r.clamp_ip(screen.get_rect())
        tag_bg = pygame.Surface((tag_r.w, tag_r.h), pygame.SRCALPHA)
        tag_bg.fill((0, 0, 0, 200))
        screen.blit(tag_bg, tag_r)
        screen.blit(ls, (tag_r.x + 5, tag_r.y + 2))


def render_info_strip(screen, mode, direction, speed, ctrl_scheme,
                      led_color, face_count, CAM_X, CAM_Y, CAM_H,
                      fmono_xs, fmono_sm):
    info_y     = CAM_Y + CAM_H + 10
    face_label = (f"FACES {face_count}" if mode == Mode.FACE
                  else f"R{led_color[0]} G{led_color[1]} B{led_color[2]}")
    items = [
        ("DIR",                                   direction,
         AMBER if direction != "STOPPED" else SEC),
        ("SPEED",                                 f"{speed:.1f}", PRI),
        ("SCHEME",                                "WASD" if ctrl_scheme == 1 else "QA/WS", PRI),
        ("FACES" if mode == Mode.FACE else "LED", face_label,
         PURPLE if mode == Mode.FACE else SEC),
    ]
    ix = CAM_X
    for lbl, val, vc in items:
        ls = fmono_xs.render(lbl, True, DIM)
        vs = fmono_sm.render(val, True, vc)
        screen.blit(ls, (ix, info_y))
        screen.blit(vs, (ix, info_y + 16))
        ix += max(ls.get_width(), vs.get_width()) + 22


def render_top_bar(screen, mode, n_thr, temp_c, st, led_color, tabs, TAB_LABELS,
                   W, TOP_H, fmono_xl, fmono_md, fmono_xs, fbody, mouse):
    logo = fmono_xl.render("KIDA", True, ACCENT)
    screen.blit(logo, (14, (TOP_H - logo.get_height()) // 2))

    for i, (tr, tl) in enumerate(zip(tabs, TAB_LABELS)):
        btn(screen, fbody, tl, tr, mouse,
            active=(int(mode) == i),
            hover_col=PURPLE if i == 3 else ACCENT)

    chip_x = W - 14
    for lbl, val, warn in [
        ("THR",  str(n_thr),                  False),
        ("TEMP", f"{temp_c:.0f}C",            temp_c > 65),
        ("CPU",  f"{st.get('cpu', 0):.0f}%", False),
    ]:
        col = AMBER if warn else PRI
        vs  = fmono_md.render(val, True, col)
        ls  = fmono_xs.render(lbl, True, DIM)
        chip_x -= vs.get_width() + 4
        screen.blit(vs, (chip_x, (TOP_H - vs.get_height()) // 2))
        chip_x -= ls.get_width() + 8
        screen.blit(ls, (chip_x, (TOP_H - ls.get_height()) // 2))
        chip_x -= 18

    for i in range(8):
        dc = tuple(led_color) if any(c > 10 for c in led_color) else (28, 30, 44)
        led_dot(screen, (chip_x - 12 - i * 14, TOP_H // 2), dc, r=5)


def render_left_panel(screen, qr_surf, local_ip, st,
                      cpu_pct, temp_c, temp_pct, ram_u, ram_t, ram_pct,
                      latency, n_thr, disk_r, disk_w, boot_t,
                      music, music_playing, frame, amplitudes,
                      btn_play, btn_skip, mouse,
                      lp_x, lp_w, TOP_H, PAD,
                      fmono_md, fmono_sm, fmono_xs, fbody, flabel, flabel_s):
    lp_y = TOP_H + PAD

    qr_w = qr_surf.get_width()
    qr_x = lp_x + (lp_w - qr_w) // 2
    pygame.draw.rect(screen, (255, 255, 255),
                     pygame.Rect(qr_x - 4, lp_y - 4, qr_w + 8, qr_w + 8),
                     border_radius=4)
    screen.blit(qr_surf, (qr_x, lp_y))
    url_y = lp_y + qr_w + 10
    txt(screen, fmono_md, str(local_ip), (lp_x + lp_w // 2, url_y), AMBER, anchor="midtop")
    txt(screen, fmono_sm, "port  5003",
        (lp_x + lp_w // 2, url_y + fmono_md.get_height() + 2), SEC, anchor="midtop")
    lp_y = url_y + fmono_md.get_height() + fmono_sm.get_height() + 14
    txt(screen, fmono_xs, "SCAN TO OPEN DASHBOARD",
        (lp_x + lp_w // 2, lp_y), DIM, anchor="midtop")
    lp_y += fmono_xs.get_height() + 10

    section_label(screen, fmono_xs, "SYSTEM", lp_x, lp_y);  lp_y += 20
    for label, val, pct, bc in [
        ("CPU",  f"{st.get('cpu', 0):.0f}%", cpu_pct,  ACCENT),
        ("TEMP", f"{temp_c:.0f}°C",           temp_pct, AMBER),
        ("RAM",  f"{ram_u}/{ram_t}M",          ram_pct,  BLUE),
    ]:
        txt(screen, flabel_s, label, (lp_x, lp_y), DIM)
        txt(screen, fmono_sm, val,   (lp_x + lp_w, lp_y), SEC, anchor="topright")
        bar(screen, pygame.Rect(lp_x, lp_y + 18, lp_w, 6), pct, bc)
        lp_y += 32

    lp_y += 6
    section_label(screen, fmono_xs, "NETWORK", lp_x, lp_y);  lp_y += 20
    for label, val in [
        ("LATENCY", latency), ("THREADS", str(n_thr)),
        ("DISK R",  f"{disk_r} MB"), ("DISK W", f"{disk_w} MB"),
        ("BOOT",    boot_t),
    ]:
        txt(screen, flabel_s, label,    (lp_x, lp_y), DIM)
        txt(screen, fmono_sm, str(val), (lp_x + lp_w, lp_y), SEC, anchor="topright")
        pygame.draw.line(screen, (22, 24, 36),
                         (lp_x, lp_y + 20), (lp_x + lp_w, lp_y + 20))
        lp_y += 24

    lp_y += 8
    section_label(screen, fmono_xs, "MUSIC", lp_x, lp_y);  lp_y += 20
    track = music.current_track or "No track"
    screen.blit(
        flabel.render(str(track)[:22], True, PRI if music_playing else SEC),
        (lp_x, lp_y),
    )
    lp_y += 22
    waveform(screen, frame, pygame.Rect(lp_x, lp_y, lp_w, 30),
             playing=music_playing, amplitudes=amplitudes)
    lp_y += 38
    btn(screen, fbody, "PAUSE" if music_playing else "PLAY", btn_play, mouse, active=music_playing)
    btn(screen, fbody, "SKIP ▶", btn_skip, mouse)


def render_right_panel(screen, mode, direction, speed_idx, ctrl_scheme,
                       video_rec, dpad, DPAD_GLYPHS, spd_dots, sch_btns,
                       btn_photo, btn_video, btn_face_snap, btn_face_scan,
                       face_scan_active,
                       rp_x, spd_y, sch_y, cap_y, TOP_H, PAD, mouse,
                       fmono_md, fmono_xs, fbody, fdpad):
    section_label(screen, fmono_xs, "DIRECTIONAL CONTROL", rp_x, TOP_H + PAD)
    for cmd, r in dpad.items():
        is_stop = cmd == "stop"
        btn(screen, fmono_md if is_stop else fdpad,
            DPAD_GLYPHS[cmd], r, mouse, danger=is_stop, hover_col=ACCENT)
        if cmd != "stop" and direction.lower() == cmd:
            pygame.draw.rect(screen, ACCENT, r, width=2, border_radius=8)

    section_label(screen, fmono_xs, "SPEED", rp_x, spd_y - 20)
    for i, r in enumerate(spd_dots):
        btn(screen, fmono_md, str(i + 1), r, mouse, active=(speed_idx == i))

    section_label(screen, fmono_xs, "CONTROL SCHEME", rp_x, sch_y - 20)
    for i, (r, lbl) in enumerate(zip(sch_btns, ["WASD", "QA/WS"])):
        btn(screen, fbody, lbl, r, mouse, active=(ctrl_scheme == i + 1))

    section_label(screen, fmono_xs, "CAPTURE", rp_x, cap_y - 20)
    btn(screen, fbody, "PHOTO", btn_photo, mouse, hover_col=BLUE)
    btn(screen, fbody, "STOP REC" if video_rec else "REC",
        btn_video, mouse, active=video_rec, hover_col=RED, danger=video_rec)
    btn(screen, fbody, "SAVE FACES", btn_face_snap, mouse, hover_col=PURPLE)
    btn(screen, fbody, "SCAN OFF" if face_scan_active else "SCAN ON",
        btn_face_scan, mouse, active=face_scan_active, hover_col=PURPLE)


def render_bottom_bar(screen, mode, ctrl_scheme, speed, face_count, frame,
                      W, H, BOT_H, fmono_xs):
    sb_y = H - BOT_H
    hline(screen, sb_y, 0, W)
    pygame.draw.circle(screen, GREEN, (14, sb_y + BOT_H // 2), 5)
    sx = 28
    for lbl, val in [
        ("FLASK",  ":5003"),
        ("MODE",   mode.name),
        ("SCHEME", "WASD" if ctrl_scheme == 1 else "QA/WS"),
        ("SPEED",  f"{speed:.1f}"),
        ("CAM",    "LIVE"),
        ("FACES",  str(face_count)),
        ("FRM",    str(frame)),
    ]:
        ls = fmono_xs.render(lbl, True, DIM)
        vs = fmono_xs.render(val, True,
                             PURPLE if lbl == "FACES" and face_count > 0 else SEC)
        screen.blit(ls, (sx, sb_y + (BOT_H - ls.get_height()) // 2));  sx += ls.get_width() + 5
        screen.blit(vs, (sx, sb_y + (BOT_H - vs.get_height()) // 2));  sx += vs.get_width() + 14
        pygame.draw.line(screen, BORDER, (sx - 6, sb_y + 6), (sx - 6, sb_y + BOT_H - 6))
    vers = fmono_xs.render("KIDA v2.4 · RASPBERRY PI", True, DIM)
    screen.blit(vers, (W - vers.get_width() - 12,
                       sb_y + (BOT_H - vers.get_height()) // 2))


def build_background(W: int, H: int, TOP_H: int, BOT_H: int, L_W: int, R_W: int) -> pygame.Surface:
    """Pre-bake the static grid + panel background — call once at startup."""
    bg = pygame.Surface((W, H))
    bg.fill(BG)
    for gx in range(0, W + 1, 44):
        pygame.draw.line(bg, (14, 8, 12), (gx, 0), (gx, H))
    for gy in range(0, H + 1, 44):
        pygame.draw.line(bg, (14, 8, 12), (0, gy), (W, gy))
    pygame.draw.rect(bg, PANEL, pygame.Rect(0,     TOP_H, L_W,   H - TOP_H - BOT_H))
    pygame.draw.rect(bg, PANEL, pygame.Rect(W-R_W, TOP_H, R_W,   H - TOP_H - BOT_H))
    pygame.draw.rect(bg, (10, 11, 16), pygame.Rect(0, H - BOT_H, W, BOT_H))
    return bg