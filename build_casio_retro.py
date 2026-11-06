#!/usr/bin/env python3
"""
Builds a custom 'Casio F-91W / A168W Retro Digital' Watchface (.bin)
from scratch for Aolon GTS3 (390x450, UTE WF v2 + PA ARGB8565 format).
"""
import math
import os
import struct
import zlib

from ute_wf import decode_pa, encode_pa, pack_bin, unpack_bin, write_png


class Canvas:
    """Pure-Python RGBA8888 drawing canvas with alpha blending & primitives."""

    def __init__(self, w, h, bg=(0, 0, 0, 0)):
        self.w = w
        self.h = h
        self.buf = bytearray(bytes(bg) * (w * h))

    def set_px(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 4
            sr, sg, sb, sa = color
            if sa == 255:
                self.buf[i : i + 4] = bytes((sr, sg, sb, 255))
            elif sa > 0:
                dr, dg, db, da = self.buf[i : i + 4]
                if da == 0:
                    self.buf[i : i + 4] = bytes((sr, sg, sb, sa))
                else:
                    inv = 255 - sa
                    out_a = sa + (da * inv) // 255
                    out_r = (sr * sa + (dr * da // 255) * inv) // max(1, out_a)
                    out_g = (sg * sa + (dg * da // 255) * inv) // max(1, out_a)
                    out_b = (sb * sa + (db * da // 255) * inv) // max(1, out_a)
                    self.buf[i : i + 4] = bytes((
                        min(255, out_r),
                        min(255, out_g),
                        min(255, out_b),
                        min(255, out_a),
                    ))

    def fill_rect(self, x0, y0, x1, y1, color):
        x0 = max(0, int(x0))
        y0 = max(0, int(y0))
        x1 = min(self.w, int(x1))
        y1 = min(self.h, int(y1))
        if x1 <= x0 or y1 <= y0:
            return
        if color[3] == 255:
            row_bytes = bytes(color) * (x1 - x0)
            for y in range(y0, y1):
                s = (y * self.w + x0) * 4
                self.buf[s : s + (x1 - x0) * 4] = row_bytes
        else:
            for y in range(y0, y1):
                for x in range(x0, x1):
                    self.set_px(x, y, color)

    def fill_rrect(self, x0, y0, x1, y1, r, color):
        """Anti-aliased (2x2 supersampled edge) rounded rectangle."""
        ix0, iy0, ix1, iy1 = int(x0), int(y0), int(x1), int(y1)
        for y in range(max(0, iy0), min(self.h, iy1)):
            for x in range(max(0, ix0), min(self.w, ix1)):
                # Quick interior check
                if (x0 + r <= x <= x1 - r - 1) or (y0 + r <= y <= y1 - r - 1):
                    self.set_px(x, y, color)
                    continue
                hits = 0
                for sy in (0.25, 0.75):
                    py = y + sy
                    cy = min(max(py, y0 + r), y1 - r)
                    for sx in (0.25, 0.75):
                        px = x + sx
                        cx = min(max(px, x0 + r), x1 - r)
                        if (px - cx) ** 2 + (py - cy) ** 2 <= r * r:
                            hits += 1
                if hits:
                    c = (color[0], color[1], color[2], (color[3] * hits) // 4)
                    self.set_px(x, y, c)

    def stroke_rrect(self, x0, y0, x1, y1, r, thickness, color):
        ix0, iy0, ix1, iy1 = int(x0 - 1), int(y0 - 1), int(x1 + 1), int(y1 + 1)
        r_in = max(0.0, r - thickness)
        for y in range(max(0, iy0), min(self.h, iy1)):
            for x in range(max(0, ix0), min(self.w, ix1)):
                if (
                    x0 + r + thickness < x < x1 - r - thickness - 1
                    and y0 + r + thickness < y < y1 - r - thickness - 1
                ):
                    continue
                hits = 0
                for sy in (0.25, 0.75):
                    py = y + sy
                    cy_out = min(max(py, y0 + r), y1 - r)
                    cy_in = min(max(py, y0 + thickness + r_in), y1 - thickness - r_in)
                    for sx in (0.25, 0.75):
                        px = x + sx
                        cx_out = min(max(px, x0 + r), x1 - r)
                        d_out = (px - cx_out) ** 2 + (py - cy_out) ** 2 <= r * r
                        if not d_out:
                            continue
                        in_box = (x0 + thickness <= px <= x1 - thickness) and (
                            y0 + thickness <= py <= y1 - thickness
                        )
                        if in_box:
                            cx_in = min(max(px, x0 + thickness + r_in), x1 - thickness - r_in)
                            d_in = (px - cx_in) ** 2 + (py - cy_in) ** 2 <= r_in * r_in
                        else:
                            d_in = False
                        if d_out and not d_in:
                            hits += 1
                if hits:
                    c = (color[0], color[1], color[2], (color[3] * hits) // 4)
                    self.set_px(x, y, c)

    def fill_poly(self, pts, color):
        """2x2 supersampled polygon fill for crisp 7-segment LCD & logos."""
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        min_x = max(0, int(math.floor(min(xs))))
        max_x = min(self.w - 1, int(math.ceil(max(xs))))
        min_y = max(0, int(math.floor(min(ys))))
        max_y = min(self.h - 1, int(math.ceil(max(ys))))
        n = len(pts)

        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                hits = 0
                for sy in (0.25, 0.75):
                    py = y + sy
                    for sx in (0.25, 0.75):
                        px = x + sx
                        inside = False
                        j = n - 1
                        for i in range(n):
                            xi, yi = pts[i]
                            xj, yj = pts[j]
                            if ((yi > py) != (yj > py)) and (
                                px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi
                            ):
                                inside = not inside
                            j = i
                        if inside:
                            hits += 1
                if hits:
                    c = (color[0], color[1], color[2], (color[3] * hits) // 4)
                    self.set_px(x, y, c)

    def blit(self, src_canvas, dst_x, dst_y):
        for sy in range(src_canvas.h):
            dy = dst_y + sy
            if not (0 <= dy < self.h):
                continue
            for sx in range(src_canvas.w):
                dx = dst_x + sx
                if not (0 <= dx < self.w):
                    continue
                si = (sy * src_canvas.w + sx) * 4
                c = src_canvas.buf[si : si + 4]
                if c[3] > 0:
                    self.set_px(dx, dy, c)


# Clean 5x7 pixel font for crisp retro Casio bezel & LCD micro-labels
FONT_5X7 = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01111", "10000", "10000", "10011", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
    "J": ["00011", "00001", "00001", "00001", "10001", "10001", "01110"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00110", "01000", "10000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["01110", "10000", "11110", "10001", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    ":": ["00000", "00100", "00100", "00000", "00100", "00100", "00000"],
    "/": ["00001", "00010", "00100", "00100", "01000", "10000", "00000"],
    ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
}


def draw_text(cv, text, x, y, scale, color, spacing=1, bold=False, italic_skew=0.0):
    cur_x = x
    for ch in text.upper():
        pat = FONT_5X7.get(ch, FONT_5X7[" "])
        for ry, row in enumerate(pat):
            shift = int(round((6 - ry) * italic_skew))
            for rx, bit in enumerate(row):
                if bit == "1":
                    px = cur_x + rx * scale + shift
                    py = y + ry * scale
                    w_extra = 1 if bold else 0
                    cv.fill_rect(px, py, px + scale + w_extra, py + scale, color)
        cur_x += 5 * scale + spacing * scale + (1 if bold else 0)


def measure_text(text, scale, spacing=1, bold=False):
    if not text:
        return 0
    step = 5 * scale + spacing * scale + (1 if bold else 0)
    return len(text) * step - spacing * scale


# 7-segment bitmask: A(top), B(top-right), C(bot-right), D(bot), E(bot-left), F(top-left), G(mid)
SEG7_DIGITS = {
    "0": "ABCDEF",
    "1": "BC",
    "2": "ABGED",
    "3": "ABGCD",
    "4": "FGBC",
    "5": "AFGCD",
    "6": "AFGCDE",
    "7": "ABC",
    "8": "ABCDEFG",
    "9": "ABCDFG",
    "-": "G",
    " ": "",
    # Weekday letters in authentic retro 7/9-segment style
    "S": "AFGCD",
    "U": "BCDEF",
    "M": "ABCEF",  # we'll draw custom crisp LCD letters for SUN..SAT!
}


def get_7seg_polygons(x0, y0, w, h, thick, gap=1.4, slant=0.06):
    """Return dict of chamfered 7-segment polygons ('A'..'G') with classic Casio italic slant."""
    t = thick
    g = gap

    def sk(px, py):
        # Slant right toward the top
        ny = (y0 + h * 0.5 - py) * slant
        return (px + ny, py)

    ym = y0 + h * 0.5
    ht = t * 0.5

    segs = {}
    # A: top horizontal
    segs["A"] = [
        sk(x0 + g + ht, y0),
        sk(x0 + w - g - ht, y0),
        sk(x0 + w - g - t, y0 + t),
        sk(x0 + g + t, y0 + t),
    ]
    # D: bottom horizontal
    segs["D"] = [
        sk(x0 + g + t, y0 + h - t),
        sk(x0 + w - g - t, y0 + h - t),
        sk(x0 + w - g - ht, y0 + h),
        sk(x0 + g + ht, y0 + h),
    ]
    # G: middle horizontal (hexagonal)
    segs["G"] = [
        sk(x0 + g + ht, ym),
        sk(x0 + g + t, ym - ht),
        sk(x0 + w - g - t, ym - ht),
        sk(x0 + w - g - ht, ym),
        sk(x0 + w - g - t, ym + ht),
        sk(x0 + g + t, ym + ht),
    ]
    # F: top-left vertical
    segs["F"] = [
        sk(x0, y0 + g + ht),
        sk(x0 + t, y0 + g + t),
        sk(x0 + t, ym - g - ht),
        sk(x0 + ht, ym - g),
        sk(x0, ym - g - ht * 0.5),
    ]
    # E: bottom-left vertical
    segs["E"] = [
        sk(x0 + ht, ym + g),
        sk(x0 + t, ym + g + ht),
        sk(x0 + t, y0 + h - g - t),
        sk(x0, y0 + h - g - ht),
        sk(x0, ym + g + ht * 0.5),
    ]
    # B: top-right vertical
    segs["B"] = [
        sk(x0 + w, y0 + g + ht),
        sk(x0 + w, ym - g - ht * 0.5),
        sk(x0 + w - ht, ym - g),
        sk(x0 + w - t, ym - g - ht),
        sk(x0 + w - t, y0 + g + t),
    ]
    # C: bottom-right vertical
    segs["C"] = [
        sk(x0 + w - ht, ym + g),
        sk(x0 + w, ym + g + ht * 0.5),
        sk(x0 + w, y0 + h - g - ht),
        sk(x0 + w - t, y0 + h - g - t),
        sk(x0 + w - t, ym + g + ht),
    ]
    return segs


def draw_7seg_glyph(cv, symbol, box_w, box_h, pad_x, pad_y, thick, ink, shadow=None, ghost=None):
    """Draw one symbol of the 14-frame UTE number font ('-', '.', '/', '0'..'9', ':')."""
    x0 = pad_x
    y0 = pad_y
    dw = box_w - 2 * pad_x
    dh = box_h - 2 * pad_y
    segs = get_7seg_polygons(x0, y0, dw, dh, thick, gap=max(1.0, thick * 0.14), slant=0.055)

    if ghost is not None:
        for poly in segs.values():
            cv.fill_poly(poly, ghost)

    active = None
    if symbol in SEG7_DIGITS:
        active = SEG7_DIGITS[symbol]

    if active is not None:
        if shadow is not None:
            sx_off, sy_off, scol = shadow
            for sname in active:
                spoly = [(px + sx_off, py + sy_off) for (px, py) in segs[sname]]
                cv.fill_poly(spoly, scol)
        for sname in active:
            cv.fill_poly(segs[sname], ink)
    elif symbol == ".":
        r = max(2, int(thick * 0.55))
        cx, cy = box_w // 2, y0 + dh - r
        cv.fill_rrect(cx - r, cy - r, cx + r, cy + r, 1.5, ink)
    elif symbol == ":":
        r = max(2, int(thick * 0.55))
        cx = box_w // 2
        for cy in (int(y0 + dh * 0.32), int(y0 + dh * 0.68)):
            cv.fill_rrect(cx - r, cy - r, cx + r, cy + r, 1.5, ink)
    elif symbol == "/":
        poly = [
            (x0 + dw * 0.68, y0 + dh * 0.12),
            (x0 + dw * 0.84, y0 + dh * 0.12),
            (x0 + dw * 0.32, y0 + dh * 0.88),
            (x0 + dw * 0.16, y0 + dh * 0.88),
        ]
        cv.fill_poly(poly, ink)


def make_14frame_strip(glyph_w, glyph_h, pad_x, pad_y, thick, ink, shadow=None):
    """Create vertical 14-frame RGBA strip: '-', '.', '/', '0'..'9', ':'."""
    symbols = ["-", ".", "/", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", ":"]
    strip = Canvas(glyph_w, glyph_h * 14, bg=(0, 0, 0, 0))
    for idx, sym in enumerate(symbols):
        cell = Canvas(glyph_w, glyph_h, bg=(0, 0, 0, 0))
        draw_7seg_glyph(cell, sym, glyph_w, glyph_h, pad_x, pad_y, thick, ink, shadow=shadow)
        strip.blit(cell, 0, idx * glyph_h)
    return strip


def make_weekday_strip(w, h, ink, shadow_col):
    """Create 7-frame weekday strip: SUN, MON, TUE, WED, THU, FRI, SAT -> SU, MO, TU, WE, TH, FR, SA."""
    days = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]
    strip = Canvas(w, h * 7, bg=(0, 0, 0, 0))
    scale = 3
    for idx, label in enumerate(days):
        cell = Canvas(w, h, bg=(0, 0, 0, 0))
        tw = measure_text(label, scale, spacing=1, bold=True)
        tx = (w - tw) // 2
        ty = (h - 7 * scale) // 2
        draw_text(cell, label, tx + 1, ty + 2, scale, shadow_col, spacing=1, bold=True, italic_skew=0.18)
        draw_text(cell, label, tx, ty, scale, ink, spacing=1, bold=True, italic_skew=0.18)
        strip.blit(cell, 0, idx * h)
    return strip


def make_battery_strip(w, h, ink, ghost_col):
    """Create 5-frame retro LCD battery bar (levels 0..4)."""
    strip = Canvas(w, h * 5, bg=(0, 0, 0, 0))
    for lvl in range(5):
        cell = Canvas(w, h, bg=(0, 0, 0, 0))
        # Outer LCD battery casing
        bx0, by0, bx1, by1 = 4, 4, w - 10, h - 4
        cell.stroke_rrect(bx0, by0, bx1, by1, 2.5, 2.2, ink)
        # Positive terminal nub on right
        cell.fill_rect(bx1, h // 2 - 4, bx1 + 4, h // 2 + 4, ink)
        # 4 internal LCD segments
        seg_count = 4
        inner_x0 = bx0 + 4
        inner_w = (bx1 - bx0 - 8)
        seg_w = (inner_w - (seg_count - 1) * 3) // seg_count
        active_bars = lvl  # 0, 1, 2, 3, 4 bars! (for lvl=0 blink/low outline + 1 thin warning bar)
        for s in range(seg_count):
            sx = inner_x0 + s * (seg_w + 3)
            if s < active_bars:
                cell.fill_rect(sx, by0 + 4, sx + seg_w, by1 - 4, ink)
            elif lvl == 0 and s == 0:
                # Thin low-battery warning sliver
                cell.fill_rect(sx, by0 + 4, sx + 2, by1 - 4, ink)
            else:
                cell.fill_rect(sx, by0 + 4, sx + seg_w, by1 - 4, ghost_col)
        strip.blit(cell, 0, lvl * h)
    return strip


def make_step_progress_strip(w, h, ink, ghost_col):
    """Create 11-frame (0..10) Casio LCD 10-segment step goal progress bar."""
    strip = Canvas(w, h * 11, bg=(0, 0, 0, 0))
    segs = 10
    gap = 4
    seg_w = (w - (segs - 1) * gap) // segs
    start_x = (w - (segs * seg_w + (segs - 1) * gap)) // 2
    for lvl in range(11):
        cell = Canvas(w, h, bg=(0, 0, 0, 0))
        for s in range(segs):
            sx = start_x + s * (seg_w + gap)
            col = ink if s < lvl else ghost_col
            # Skewed parallelogram tick!
            pts = [
                (sx + 2, 1),
                (sx + seg_w + 2, 1),
                (sx + seg_w - 2, h - 1),
                (sx - 2, h - 1),
            ]
            cell.fill_poly(pts, col)
        strip.blit(cell, 0, lvl * h)
    return strip


def downsample_canvas(src, dst_w, dst_h):
    """High-quality area-averaging downsample for the 162x187 watchface preview."""
    dst = Canvas(dst_w, dst_h)
    sx_ratio = src.w / dst_w
    sy_ratio = src.h / dst_h
    for dy in range(dst_h):
        y0 = int(dy * sy_ratio)
        y1 = max(y0 + 1, int((dy + 1) * sy_ratio))
        for dx in range(dst_w):
            x0 = int(dx * sx_ratio)
            x1 = max(x0 + 1, int((dx + 1) * sx_ratio))
            r_sum = g_sum = b_sum = a_sum = cnt = 0
            for sy in range(y0, min(src.h, y1)):
                for sx in range(x0, min(src.w, x1)):
                    i = (sy * src.w + sx) * 4
                    r_sum += src.buf[i]
                    g_sum += src.buf[i + 1]
                    b_sum += src.buf[i + 2]
                    a_sum += src.buf[i + 3]
                    cnt += 1
            di = (dy * dst_w + dx) * 4
            dst.buf[di : di + 4] = bytes((
                r_sum // cnt,
                g_sum // cnt,
                b_sum // cnt,
                a_sum // cnt,
            ))
    return dst


def build_casio_watchface():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    W, H = 390, 450

    # Extract exact hardware corner alpha mask from captured GTS3 stock background!
    cap_dir = os.path.join(base_dir, "captured")
    stock_bins = sorted(f for f in os.listdir(cap_dir) if f.endswith(".bin"))
    stock_data = open(os.path.join(cap_dir, stock_bins[-1]), "rb").read()
    bg_off = struct.unpack_from("<I", stock_data, 0x4C)[0]
    ab = 0x18 + bg_off
    _, _, sw, sh, _, sextra = struct.unpack_from("<2sHHHHH", stock_data, ab)
    end_tbl = struct.unpack_from("<h", stock_data, ab + 16 + sh * 2)[0]
    slen = 16 + (sh + 1) * 2 + sh * sextra + end_tbl
    _, _, stock_bg_rgba = decode_pa(stock_data[ab : ab + slen])

    # Colors — Authentic Casio F-91W / A168W Vintage Palette
    RESIN_DARK = (18, 21, 26, 255)
    BEZEL_CHARCOAL = (27, 31, 38, 255)
    CASIO_BLUE = (29, 98, 196, 255)
    CASIO_RED = (214, 52, 48, 255)
    CASIO_GOLD = (232, 185, 58, 255)
    SILKSCREEN_WHITE = (236, 240, 244, 255)
    SILKSCREEN_MUTED = (164, 174, 186, 255)

    # Classic Vintage Reflective Nematic LCD Palette
    LCD_TOP = (176, 190, 157, 255)
    LCD_BOT = (156, 171, 138, 255)
    LCD_SHADOW_EDGE = (92, 104, 80, 255)
    LCD_INK = (20, 27, 18, 255)
    LCD_DROP_SHADOW = (20, 27, 18, 38)
    LCD_GHOST = (20, 27, 18, 22)
    LCD_LINE = (42, 52, 38, 190)

    bg = Canvas(W, H, bg=RESIN_DARK)

    # 1. Outer faceplate bezel & classic Casio Royal-Blue double border
    bg.fill_rrect(10, 10, W - 10, H - 10, 72, BEZEL_CHARCOAL)
    bg.stroke_rrect(14, 14, W - 14, H - 14, 68, 3.0, CASIO_BLUE)
    bg.stroke_rrect(20, 20, W - 20, H - 20, 63, 1.5, (58, 72, 94, 255))

    # 2. Top Casio Header Silkscreen (y = 26..92)
    # Bold italic "CASIO" on left + "QUARTZ" on right
    draw_text(bg, "CASIO", 54, 34, 3, SILKSCREEN_WHITE, spacing=1, bold=True, italic_skew=0.2)
    draw_text(bg, "F-91W", 252, 38, 2, CASIO_GOLD, spacing=1, bold=True)

    # Blue + Red accent rules
    bg.fill_rect(38, 60, W - 38, 63, CASIO_BLUE)
    bg.fill_rect(38, 66, 130, 68, CASIO_RED)
    bg.fill_rect(W - 130, 66, W - 38, 68, CASIO_RED)
    tw_ac = measure_text("ILLUMINATOR", 1, spacing=2, bold=True)
    draw_text(bg, "ILLUMINATOR", (W - tw_ac) // 2, 64, 1, CASIO_GOLD, spacing=2, bold=True)

    # Pusher button indicator arrows & micro labels
    # Left arrow ◀ LIGHT
    bg.fill_poly([(32, 81), (40, 76), (40, 86)], CASIO_RED)
    draw_text(bg, "LIGHT", 45, 78, 1, SILKSCREEN_MUTED, spacing=1)
    # Center ALARM CHRONOGRAPH
    tw_ch = measure_text("ALARM CHRONOGRAPH", 1, spacing=1)
    draw_text(bg, "ALARM CHRONOGRAPH", (W - tw_ch) // 2, 78, 1, SILKSCREEN_WHITE, spacing=1)
    # Right arrow MODE ▶
    draw_text(bg, "MODE", W - 70, 78, 1, SILKSCREEN_MUTED, spacing=1)
    bg.fill_poly([(W - 32, 81), (W - 40, 76), (W - 40, 86)], CASIO_RED)

    # 3. Recessed Vintage LCD Glass Window (x = 26..364, y = 94..372)
    lx0, ly0, lx1, ly1 = 26, 94, 364, 372
    lcd_r = 18
    # Outer dark bezel lip around LCD
    bg.fill_rrect(lx0 - 5, ly0 - 5, lx1 + 5, ly1 + 5, lcd_r + 4, (10, 12, 15, 255))
    bg.stroke_rrect(lx0 - 3, ly0 - 3, lx1 + 3, ly1 + 3, lcd_r + 2, 2.0, (70, 78, 90, 255))

    # Fill LCD gradient clipped cleanly inside rounded corners!
    lcd_cv = Canvas(lx1 - lx0, ly1 - ly0, bg=(0, 0, 0, 0))
    lcd_mask = Canvas(lx1 - lx0, ly1 - ly0, bg=(0, 0, 0, 0))
    lcd_mask.fill_rrect(0, 0, lx1 - lx0, ly1 - ly0, lcd_r, (255, 255, 255, 255))
    for y in range(ly1 - ly0):
        t = y / max(1, (ly1 - ly0 - 1))
        sheen = int(6 * math.sin(t * math.pi))
        r = min(255, int(LCD_TOP[0] * (1 - t) + LCD_BOT[0] * t) + sheen)
        g = min(255, int(LCD_TOP[1] * (1 - t) + LCD_BOT[1] * t) + sheen)
        b = min(255, int(LCD_TOP[2] * (1 - t) + LCD_BOT[2] * t) + sheen)
        for x in range(lx1 - lx0):
            mi = (y * (lx1 - lx0) + x) * 4
            ma = lcd_mask.buf[mi + 3]
            if ma:
                lcd_cv.buf[mi : mi + 4] = bytes((r, g, b, ma))
    bg.blit(lcd_cv, lx0, ly0)

    # Recessed inner shadow border around LCD glass
    bg.stroke_rrect(lx0 - 1, ly0 - 1, lx1 + 1, ly1 + 1, lcd_r + 1, 2.5, (12, 14, 18, 255))
    bg.fill_rect(lx0 + 14, ly0 + 2, lx1 - 14, ly0 + 5, (72, 82, 62, 130))
    bg.fill_rect(lx0 + 2, ly0 + 14, lx0 + 5, ly1 - 14, (72, 82, 62, 105))

    # 4. Inside LCD: Upper Row Framing & Ghost Segments (y = 104..156)
    # Battery label at top-left
    draw_text(bg, "BATT", 46, 105, 1, LCD_INK, spacing=1, bold=True)
    # Weekday retro bracket box around center (x = 166..226, y = 114..152) -> center (196, 133)
    bg.stroke_rrect(164, 114, 228, 152, 4, 1.8, LCD_LINE)
    draw_text(bg, "DAY", 185, 104, 1, LCD_INK, spacing=1)
    # Date header & static hyphen + ghost '88-88' at right:
    # Month center (268, 133), hyphen at (299, 133), Day center (330, 133)
    draw_text(bg, "DATE", 280, 104, 1, LCD_INK, spacing=1)
    date_gw, date_gh = 20, 34
    month_cx, date_cy = 266, 133
    day_cx = 326
    # Ghost '88' for Month and Day
    for dleft in (month_cx - date_gw, month_cx, day_cx - date_gw, day_cx):
        gcell = Canvas(date_gw, date_gh)
        draw_7seg_glyph(gcell, " ", date_gw, date_gh, 2, 2, 3.6, LCD_INK, ghost=LCD_GHOST)
        bg.blit(gcell, dleft, date_cy - date_gh // 2)
    # Crisp LCD hyphen between Month and Day at x = 296
    bg.fill_rect(291, date_cy - 2, 301, date_cy + 2, LCD_INK)

    # Divider line 1 + classic Casio status icons (bell, wave, 24H)
    bg.fill_rect(40, 158, 350, 160, LCD_LINE)
    draw_text(bg, "24H", 44, 165, 1, LCD_INK, spacing=1, bold=True)
    # Tiny LCD alarm wave '((o))' + bell mark
    draw_text(bg, "ALM  SIG", 90, 165, 1, LCD_LINE, spacing=1)
    draw_text(bg, "CHRONO", 306, 165, 1, LCD_LINE, spacing=1)

    # 5. Giant Main Time LCD Ghost Segments + Static Colon (y = 176..282)
    # Hour (2 digits of 68x102 -> 136x102) centered at (112, 229) -> x = 44..180
    # Minute (2 digits of 68x102 -> 136x102) centered at (278, 229) -> x = 210..346
    time_gw, time_gh = 68, 102
    hour_cx, min_cx, time_cy = 112, 278, 229
    for dleft in (hour_cx - time_gw, hour_cx, min_cx - time_gw, min_cx):
        gcell = Canvas(time_gw, time_gh)
        draw_7seg_glyph(gcell, " ", time_gw, time_gh, 5, 4, 11.5, LCD_INK, ghost=LCD_GHOST)
        bg.blit(gcell, dleft, time_cy - time_gh // 2)

    # Iconic Casio skewed double-square LCD Colon at x = 195, y = 229
    for cy_off, sx_off in ((-20, 1), (20, -1)):
        cx_dot = 195 + sx_off
        cy_dot = time_cy + cy_off
        bg.fill_rrect(cx_dot - 5, cy_dot - 5, cx_dot + 7, cy_dot + 7, 1.5, LCD_DROP_SHADOW)
        bg.fill_rrect(cx_dot - 6, cy_dot - 6, cx_dot + 6, cy_dot + 6, 1.5, LCD_INK)

    # 6. Step Goal Progress Track Header + Divider Line 2 (y = 286..308)
    bg.fill_rect(40, 287, 350, 289, LCD_LINE)
    # Progress bar sits at (195, 298) with size 304x10
    bg.fill_rect(40, 307, 350, 309, LCD_LINE)

    # 7. Lower LCD Telemetry Sub-Windows: STEPS | BPM | KCAL (y = 312..364)
    # Vertical LCD dividers
    bg.fill_rect(148, 312, 150, 362, LCD_LINE)
    bg.fill_rect(242, 312, 244, 362, LCD_LINE)

    draw_text(bg, "STEPS", 73, 314, 1, LCD_INK, spacing=1, bold=True)
    draw_text(bg, "HEART", 178, 314, 1, LCD_INK, spacing=1, bold=True)
    draw_text(bg, "KCAL", 283, 314, 1, LCD_INK, spacing=1, bold=True)

    # Tiny pixel heart icon next to HEART
    heart_pat = [
        "0110110",
        "1111111",
        "1111111",
        "0111110",
        "0011100",
        "0001000",
    ]
    for ry, hrow in enumerate(heart_pat):
        for rx, bit in enumerate(hrow):
            if bit == "1":
                bg.fill_rect(164 + rx, 314 + ry, 165 + rx, 315 + ry, LCD_INK)

    # Sub-telemetry center coordinates:
    # Steps (04 41): (94, 344)
    # Heart BPM (04 42): (195, 344)
    # Calories (04 40): (297, 344)
    stat_gw, stat_gh = 18, 32
    stat_cy = 344

    # 8. Bottom Casio Faceplate Footer (y = 380..434)
    # Classic Casio Blue 'WR' emblem box in center (x = 171..219, y = 384..414)
    bg.fill_rrect(169, 384, 221, 414, 6, CASIO_BLUE)
    bg.stroke_rrect(169, 384, 221, 414, 6, 2.0, CASIO_RED)
    draw_text(bg, "WR", 180, 392, 2, SILKSCREEN_WHITE, spacing=2, bold=True, italic_skew=0.18)

    # "WATER" on left, "RESIST" on right
    draw_text(bg, "WATER", 84, 394, 2, CASIO_GOLD, spacing=1, bold=True)
    draw_text(bg, "RESIST", 232, 394, 2, CASIO_GOLD, spacing=1, bold=True)

    # Bottom accent line
    bg.fill_rect(96, 420, W - 96, 423, CASIO_BLUE)

    # 9. Apply exact hardware rounded-corner alpha mask from stock GTS3 background!
    for i in range(W * H):
        hw_alpha = stock_bg_rgba[i * 4 + 3]
        bg.buf[i * 4 + 3] = hw_alpha
        if hw_alpha == 0:
            bg.buf[i * 4 : i * 4 + 4] = b"\x00\x00\x00\x00"

    # 10. Build all Dynamic Widget Sprite Strips!
    # A) Big 7-segment Time strip (68x102 * 14 = 68x1428)
    strip_time = make_14frame_strip(
        time_gw, time_gh, pad_x=5, pad_y=4, thick=11.5, ink=LCD_INK, shadow=(2, 2, LCD_DROP_SHADOW)
    )
    # B) Date 7-segment strip (20x34 * 14 = 20x476)
    strip_date = make_14frame_strip(
        date_gw, date_gh, pad_x=2, pad_y=2, thick=3.6, ink=LCD_INK, shadow=(1, 1, LCD_DROP_SHADOW)
    )
    # C) Telemetry stats 7-segment strip (18x32 * 14 = 18x448)
    strip_stat = make_14frame_strip(
        stat_gw, stat_gh, pad_x=2, pad_y=2, thick=3.8, ink=LCD_INK, shadow=(1, 1, LCD_DROP_SHADOW)
    )
    # D) Weekday 7-frame strip (58x32 * 7 = 58x224)
    strip_week = make_weekday_strip(58, 32, ink=LCD_INK, shadow_col=LCD_DROP_SHADOW)
    # E) Battery 5-frame strip (74x28 * 5 = 74x140)
    strip_batt = make_battery_strip(74, 28, ink=LCD_INK, ghost_col=LCD_GHOST)
    # F) Step goal 11-frame progress bar (304x10 * 11 = 304x110)
    strip_prog = make_step_progress_strip(304, 10, ink=LCD_INK, ghost_col=LCD_GHOST)

    # 11. Compose a full-resolution Mockup Preview (10:08, MO, 11-05, 80% batt, 7542 steps, 76 bpm, 348 kcal)
    preview_full = Canvas(W, H)
    preview_full.buf[:] = bg.buf[:]

    def blit_frame(dst, strip_cv, frame_idx, frame_h, cx, cy):
        sub = Canvas(strip_cv.w, frame_h)
        s0 = frame_idx * frame_h * strip_cv.w * 4
        s1 = (frame_idx + 1) * frame_h * strip_cv.w * 4
        sub.buf[:] = strip_cv.buf[s0:s1]
        dst.blit(sub, cx - strip_cv.w // 2, cy - frame_h // 2)

    def blit_number(dst, strip_cv, frame_h, text_str, cx, cy):
        sym_map = {"-": 0, ".": 1, "/": 2, ":": 13}
        for d in range(10):
            sym_map[str(d)] = 3 + d
        total_w = len(text_str) * strip_cv.w
        left_x = cx - total_w // 2
        for idx, ch in enumerate(text_str):
            fidx = sym_map[ch]
            blit_frame(dst, strip_cv, fidx, frame_h, left_x + idx * strip_cv.w + strip_cv.w // 2, cy)

    blit_frame(preview_full, strip_batt, 4, 28, 80, 134)
    blit_frame(preview_full, strip_week, 1, 32, 196, 133)  # MO
    blit_number(preview_full, strip_date, date_gh, "11", month_cx, date_cy)
    blit_number(preview_full, strip_date, date_gh, "05", day_cx, date_cy)
    blit_number(preview_full, strip_time, time_gh, "10", hour_cx, time_cy)
    blit_number(preview_full, strip_time, time_gh, "08", min_cx, time_cy)
    blit_frame(preview_full, strip_prog, 7, 10, 195, 298)
    blit_number(preview_full, strip_stat, stat_gh, "7542", 94, stat_cy)
    blit_number(preview_full, strip_stat, stat_gh, "76", 195, stat_cy)
    blit_number(preview_full, strip_stat, stat_gh, "348", 297, stat_cy)

    # Apply corner alpha mask to preview_full too before downsampling to 162x187
    for i in range(W * H):
        if stock_bg_rgba[i * 4 + 3] == 0:
            preview_full.buf[i * 4 : i * 4 + 4] = b"\x00\x00\x00\x00"

    preview_thumb = downsample_canvas(preview_full, 162, 187)

    # Save full-size mockup PNG so we can inspect & share!
    mockup_path = os.path.join(base_dir, "preview_casio_390x450.png")
    write_png(mockup_path, W, H, preview_full.buf)
    print("Saved live mockup PNG:", mockup_path)

    # 12. Encode PA assets & Pack .bin!
    pa_bg = encode_pa(W, H, bg.buf)
    pa_batt = encode_pa(strip_batt.w, strip_batt.h, strip_batt.buf)
    pa_week = encode_pa(strip_week.w, strip_week.h, strip_week.buf)
    pa_prog = encode_pa(strip_prog.w, strip_prog.h, strip_prog.buf)
    pa_date = encode_pa(strip_date.w, strip_date.h, strip_date.buf)
    pa_time = encode_pa(strip_time.w, strip_time.h, strip_time.buf)
    pa_stat = encode_pa(strip_stat.w, strip_stat.h, strip_stat.buf)
    pa_thumb = encode_pa(preview_thumb.w, preview_thumb.h, preview_thumb.buf)

    Z8 = b"\x00" * 8
    N8 = b"\x01\x00\x00\x00\x00\x00\x00\x00"

    widgets = [
        # 0: Background (390x450)
        {"type_bytes": bytes([0x02, 0x10, 0x01, 0x00]), "x": 195, "y": 225, "tail_bytes": Z8, "asset_key": "bg", "asset_pa": pa_bg},
        # 1: Battery Level (5 frames)
        {"type_bytes": bytes([0x02, 0x1D, 0x05, 0x00]), "x": 80, "y": 134, "tail_bytes": Z8, "asset_key": "batt", "asset_pa": pa_batt},
        # 2: Weekday (7 frames: SU..SA)
        {"type_bytes": bytes([0x02, 0x25, 0x07, 0x00]), "x": 196, "y": 133, "tail_bytes": Z8, "asset_key": "week", "asset_pa": pa_week},
        # 3: Step Goal Progress Bar (11 frames: 0..10)
        {"type_bytes": bytes([0x02, 0x1C, 0x0B, 0x00]), "x": 195, "y": 298, "tail_bytes": Z8, "asset_key": "prog", "asset_pa": pa_prog},
        # 4: Month (MM)
        {"type_bytes": bytes([0x04, 0x02, 0x0E, 0x01]), "x": month_cx, "y": date_cy, "tail_bytes": N8, "asset_key": "date", "asset_pa": pa_date},
        # 5: Day (DD)
        {"type_bytes": bytes([0x04, 0x03, 0x0E, 0x01]), "x": day_cx, "y": date_cy, "tail_bytes": N8, "asset_key": "date", "asset_pa": pa_date},
        # 6: Hour (HH)
        {"type_bytes": bytes([0x04, 0x05, 0x0E, 0x01]), "x": hour_cx, "y": time_cy, "tail_bytes": N8, "asset_key": "time", "asset_pa": pa_time},
        # 7: Minute (MM)
        {"type_bytes": bytes([0x04, 0x06, 0x0E, 0x01]), "x": min_cx, "y": time_cy, "tail_bytes": N8, "asset_key": "time", "asset_pa": pa_time},
        # 8: Steps
        {"type_bytes": bytes([0x04, 0x41, 0x0E, 0x01]), "x": 94, "y": stat_cy, "tail_bytes": N8, "asset_key": "stat", "asset_pa": pa_stat},
        # 9: Heart Rate (BPM)
        {"type_bytes": bytes([0x04, 0x42, 0x0E, 0x01]), "x": 195, "y": stat_cy, "tail_bytes": N8, "asset_key": "stat", "asset_pa": pa_stat},
        # 10: Calories (KCAL)
        {"type_bytes": bytes([0x04, 0x40, 0x0E, 0x01]), "x": 297, "y": stat_cy, "tail_bytes": N8, "asset_key": "stat", "asset_pa": pa_stat},
        # 11: Preview Thumbnail (162x187) — always last
        {"type_bytes": bytes([0x02, 0x11, 0x01, 0x00]), "x": 195, "y": 225, "tail_bytes": Z8, "asset_key": "thumb", "asset_pa": pa_thumb},
    ]

    # Default ID from stock #2 (proxy.mjs will also dynamically stamp whichever watchface ID is clicked!)
    wf_id = 26950001
    wf_bcd = bytes.fromhex("009526")
    bin_bytes = pack_bin(wf_id, wf_bcd, W, H, widgets)

    inject_dir = os.path.join(base_dir, "inject")
    os.makedirs(inject_dir, exist_ok=True)
    out_bin = os.path.join(inject_dir, "custom.bin")
    with open(out_bin, "wb") as f:
        f.write(bin_bytes)
    print(f"Compiled custom.bin -> {out_bin} ({len(bin_bytes)} bytes, {len(bin_bytes)/1024:.1f} KB)")

    # Round-trip self-verification!
    verify_dir = os.path.join(base_dir, "unpacked", "verify_custom_casio")
    vman = unpack_bin(out_bin, verify_dir)
    print(f"Round-trip verification: crc_ok={vman['crc_ok']}, widgets={len(vman['widgets'])}")
    assert vman["crc_ok"], "CRC verification failed!"


if __name__ == "__main__":
    build_casio_watchface()
