#!/usr/bin/env python3

"""
hud_layout.py — Screen layout + fonts for the KIDA HUD.

Shared by the robot's own window (scripts/ui.py) and the remote controller
(controller/main.py), so both compute exactly the same rects from the same
screen size. Pure pygame — no hardware imports.
"""

import pygame

TAB_LABELS   = ["USER CTRL", "AUTONOMOUS", "LINE FOLLOW"]
DPAD_GLYPHS  = {"forward": "▲", "left": "◀", "stop": "■", "right": "▶", "backward": "▼"}
SPEED_LEVELS = [0.4, 0.6, 0.8, 1.0]

CAM_NATIVE_W, CAM_NATIVE_H = 320, 240


def _has_glyphs(font, glyphs: str) -> bool:
    """False if any glyph renders as the font's missing-glyph box."""
    tofu = pygame.image.tostring(font.render("", True, (255, 255, 255)), "RGB")
    return all(pygame.image.tostring(font.render(g, True, (255, 255, 255)), "RGB") != tofu
               for g in glyphs)


def _symbol_font(names, size, glyphs, bold=False):
    """First of *names* that can draw every glyph (d-pad arrows) — Windows
    Arial has ▲▼ but not ◀▶; falls back to the first name."""
    for name in names:
        if pygame.font.match_font(name):
            font = pygame.font.SysFont(name, size, bold=bold)
            if _has_glyphs(font, glyphs):
                return font
    return pygame.font.SysFont(names[0], size, bold=bold)


def make_fonts() -> dict:
    return {
        "fmono_xl": pygame.font.SysFont("Courier New", 34, bold=True),
        "fmono_md": pygame.font.SysFont("Courier New", 20, bold=True),
        "fmono_sm": pygame.font.SysFont("Courier New", 17, bold=True),
        "fmono_xs": pygame.font.SysFont("Courier New", 14),
        "fbody":    pygame.font.SysFont("Arial", 18, bold=True),
        "flabel":   pygame.font.SysFont("Arial", 17),
        "flabel_s": pygame.font.SysFont("Arial", 15),
        "fdpad":    _symbol_font(("Arial", "DejaVu Sans", "Segoe UI Symbol", "FreeSans"),
                                 32, "▲◀▶▼", bold=True),
    }


def compute_layout(W: int, H: int) -> dict:
    TOP_H = 58;  BOT_H = 42;  PAD = 10
    L_W   = 290; R_W   = 300; TAB_H = 50

    CAM_AVAIL_W = W - L_W - R_W
    CAM_AVAIL_H = H - TOP_H - BOT_H
    CAM_W = int(CAM_AVAIL_W * 0.82);  CAM_H = int(CAM_AVAIL_H * 0.60)
    CAM_X = L_W + (CAM_AVAIL_W - CAM_W) // 2
    CAM_Y = TOP_H + TAB_H + PAD

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
    btn_photo     = pygame.Rect(rp_x,                cap_y, cap_w, cap_h)
    btn_video     = pygame.Rect(rp_x + cap_w + DP_G, cap_y, cap_w, cap_h)
    btn_face_snap = pygame.Rect(rp_x, cap_y + cap_h + 10, cap_w, 44)
    btn_face_scan = pygame.Rect(rp_x + cap_w + DP_G, cap_y + cap_h + 10, cap_w, 44)

    lp_x = PAD;  lp_w = L_W - PAD * 2
    mus_btn_y = H - BOT_H - 76;  mus_btn_h = 48;  mus_btn_w = (lp_w - DP_G) // 2
    btn_play = pygame.Rect(lp_x,                    mus_btn_y, mus_btn_w, mus_btn_h)
    btn_skip = pygame.Rect(lp_x + mus_btn_w + DP_G, mus_btn_y, mus_btn_w, mus_btn_h)

    return {
        "W": W, "H": H,
        "TOP_H": TOP_H, "BOT_H": BOT_H, "PAD": PAD, "L_W": L_W, "R_W": R_W,
        "CAM_X": CAM_X, "CAM_Y": CAM_Y, "CAM_W": CAM_W, "CAM_H": CAM_H,
        "tabs": tabs, "dpad": dpad, "spd_dots": spd_dots, "sch_btns": sch_btns,
        "btn_photo": btn_photo, "btn_video": btn_video,
        "btn_face_snap": btn_face_snap, "btn_face_scan": btn_face_scan,
        "btn_play": btn_play, "btn_skip": btn_skip,
        "rp_x": rp_x, "spd_y": spd_y, "sch_y": sch_y, "cap_y": cap_y,
        "lp_x": lp_x, "lp_w": lp_w,
    }
