#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BIDeT3D - the third dimension of BIDeT.

1990s WordArt (after arizzitano/css3wordart), extruded into real 3D and
printed to the terminal as SIXEL graphics (via saitoha/libsixel).

Text -> flat layer (shape warp, material, bevel) -> depth slices ->
perspective camera -> PIL/numpy image -> libsixel -> terminal.
"""

import argparse
import io
import math
import os
import random
import re
import shutil
import subprocess
import sys
import textwrap
import time

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont

VERSION = "0.1"


def C(h):
    """'#rrggbb' -> (r, g, b)"""
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


# --------------------------------------------------------------------------
# Presets: the 30 css3wordart styles, expressed as 3D materials.
#
#   fill    ('solid', hex) | ('linear', 'v'|'h', stops) | ('radial', stops)
#           ('texture', name) | ('tile', name)       stops = [(0..1, hex)]
#   stroke  (hex, em)            outline around the face (css -webkit-text-stroke)
#   side    (back_hex, front_hex) colours of the extrusion sides
#           (css text3d()/text-shadow colours); auto-derived when None
#   depth   extrusion depth in em
#   shape   None | arc | inverted-arc | squeeze | wave   (the curved baselines
#           css3wordart marks "not achievable with CSS3")
#   sy/skewx/skewy   css scaleY / skew() of the original preset
#   view    (yaw, pitch, roll) degrees of the original preset's 3D transform
#   stacked one letter per line (the *-stack presets)
#   bevel   strength of the edge lighting on the face
# --------------------------------------------------------------------------
_DEFAULTS = dict(font="arial", italic=False, spacing=0.0, fill=("solid", "#000000"),
                 stroke=None, side=None, depth=0.08, shape=None, sy=1.0,
                 skewx=0.0, skewy=0.0, view=None, stacked=False, bevel=0.25)

_P = {}


def _preset(name, **kw):
    bad = set(kw) - set(_DEFAULTS)
    assert not bad, (name, bad)
    _P[name] = dict(_DEFAULTS, **kw)


# The original black presets sat on light backgrounds.  "@ink" resolves to white or
# black, whichever contrasts with the terminal background (see resolve_ink).
_INK = ("solid", "@ink")
_GREY_SIDE = ("#303030", "#7a7a7a")

_preset("outline", fill=("solid", "#ffffff"), stroke=("#000000", 0.03), sy=1.2,
        spacing=-0.01, side=("#101010", "#3c3c3c"), depth=0.07, bevel=0.1)
_preset("up", fill=_INK, skewy=-15, sy=1.4, spacing=-0.04, side=_GREY_SIDE)
_preset("arc", fill=_INK, shape="arc", spacing=-0.04, side=_GREY_SIDE)
_preset("squeeze", font="impact", fill=_INK, shape="squeeze", sy=1.3, side=_GREY_SIDE)
_preset("inverted-arc", font="times", fill=_INK, shape="inverted-arc", side=_GREY_SIDE)
_preset("basic-stack", fill=_INK, stacked=True, sy=0.75, side=_GREY_SIDE)
_preset("italic-outline", italic=True, fill=("solid", "#ffffff"), stroke=("#000000", 0.02),
        sy=1.3, spacing=-0.01, side=("#3c3c3c", "#6d6d6d"), depth=0.07, bevel=0.1)
_preset("slate", font="times", fill=("solid", "#2F5485"), sy=1.5,
        side=("#8a8a8a", "#b3b3b3"), depth=0.06)
_preset("mauve", fill=("tile", "gray-check"), stroke=("#1932BD", 0.02), sy=1.4,
        spacing=-0.03, side=("#525dcb", "#828DFB"), depth=0.07, bevel=0.1)
_preset("graydient", fill=("linear", "v", [(0, "#9d9d9d"), (1, "#ffffff")]), sy=1.3,
        spacing=0.08, side=("#3b3b3b", "#5b5b5b"), depth=0.06)
_preset("red-blue", font="impact", fill=("solid", "#1657BD"), stroke=("#91C2FC", 0.02),
        sy=1.2, side=("#4d0d0d", "#771515"), depth=0.09)
_preset("brown-stack", stacked=True, italic=True, fill=("solid", "#601111"), sy=0.75,
        side=("#8a8a8a", "#adadad"), depth=0.07)
_preset("radial", font="impact", fill=("radial", [(0, "#fffa28"), (1, "#ec8a39")]), sy=1.2,
        side=("#7f7f7f", "#B3B3B3"), depth=0.07)
_preset("purple", font="impact", fill=("linear", "v", [(0, "#4222be"), (0.73, "#a62cc1"), (1, "#a62cc1")]),
        stroke=("#B28FFD", 0.015), skewy=-10, sy=1.5, spacing=-0.01,
        side=("#4a52c8", "#828DFB"), depth=0.07)
_preset("green-marble", font="times", fill=("texture", "GreenMarble"), sy=1.2,
        side=("#0c1f10", "#1f4427"), depth=0.08)
_preset("rainbow", fill=("linear", "h", [(0, "#ee00ff"), (.16, "#ff3030"), (.32, "#ff9900"),
                                         (.49, "#fff430"), (.67, "#00ff08"), (.83, "#3223ff"),
                                         (1, "#aa00ff")]),
        sy=1.5, spacing=-0.01, side=("#2a1040", "#5a2a7a"), depth=0.09)
_preset("aqua", font="times", fill=("linear", "v", [(0, "#828dfb"), (1, "#378484")]), sy=1.3,
        spacing=-0.01, side=("#7f7f7f", "#B3B3B3"), depth=0.07)
_preset("texture-stack", font="times", stacked=True, fill=("texture", "Granite"), sy=0.75,
        side=("#8f8f8f", "#b5b5b5"), depth=0.07)
_preset("paper-bag", fill=("texture", "PaperBag"), sy=1.3, spacing=-0.03,
        side=("#0b0701", "#130C02"), depth=0.08)
_preset("sunset", font="times", fill=("linear", "v", [(0, "#fafacc"), (1, "#f3919b")]), sy=1.2,
        side=("#081A33", "#114491"), depth=0.11)
_preset("tilt", fill=("linear", "v", [(0, "#390c0b"), (0.73, "#f6bf28"), (1, "#f6bf28")]),
        stroke=("#A3A3A3", 0.015), sy=1.6, spacing=-0.01, view=(-8, 28, 0),
        side=("#3b2508", "#6D4916"), depth=0.12)
_preset("blues", font="impact", fill=("solid", "#24c0fd"), stroke=("#0000aa", 0.02),
        spacing=-0.05, side=("#00005a", "#0000aa"), depth=0.14)
_preset("marble-slab", fill=("texture", "GreenMarble"), sy=1.2, view=(8, 0, -7),
        side=("#030B00", "#1E4100"), depth=0.25)
_preset("yellow-dash", fill=("tile", "yellow-dash"), stroke=("#000000", 0.015), sy=1.6,
        spacing=-0.03, view=(-10, 0, -4), side=("#3a3a3a", "#6d6d6d"), depth=0.08)
_preset("gray-block", font="impact",
        fill=("linear", "h", [(0, "#606060"), (0.5, "#ffffff"), (1, "#606060")]),
        skewy=12, sy=1.2, view=(5, 0, 0), side=("#27271F", "#60614B"), depth=0.35, bevel=0.4)
_preset("superhero", font="impact",
        fill=("linear", "v", [(0, "#fdea00"), (0.44, "#fdcf00"), (1, "#fc2700")]),
        skewy=-15, sy=1.5, side=("#802700", "#c23d00"), depth=0.12)
_preset("horizon", fill=("linear", "v", [(0, "#7286a7"), (0.13, "#7286a7"), (0.5, "#ffffff"),
                                         (0.56, "#812f30"), (1, "#ffffff")]),
        side=("#161616", "#8d8d8d"), depth=0.12)
_preset("chrome", font="times",
        fill=("linear", "v", [(0, "#b5b5b5"), (0.23, "#4f4f4f"), (0.64, "#f9f9f9"),
                              (0.69, "#212121"), (1, "#d3d3d3")]),
        sy=1.3, side=("#2B2B2B", "#6D6D6D"), depth=0.09, bevel=0.5)
_preset("green-stack", stacked=True, fill=("solid", "#71F504"), skewy=-10, sy=0.75,
        side=("#00116B", "#0a2090"), depth=0.11)
_preset("stack-3d", stacked=True, fill=("solid", "#4E0E0E"), skewy=10, sy=0.75,
        side=("#7C3E2C", "#E8703C"), depth=0.25)

# order as in css3wordart's gallery
PRESET_ORDER = [
    'outline', 'up', 'arc', 'squeeze', 'inverted-arc', 'basic-stack',
    'italic-outline', 'slate', 'mauve', 'graydient', 'red-blue', 'brown-stack',
    'radial', 'purple', 'green-marble', 'rainbow', 'aqua', 'texture-stack',
    'paper-bag', 'sunset', 'tilt', 'blues', 'yellow-dash', 'green-stack',
    'chrome', 'marble-slab', 'gray-block', 'superhero', 'horizon', 'stack-3d',
]
assert sorted(PRESET_ORDER) == sorted(_P), "preset table out of sync"
PRESETS = {n: _P[n] for n in PRESET_ORDER}

DEFAULT_PRESET = "rainbow"
DEFAULT_VIEW = (-20.0, 8.0, 0.0)
SLICE_DENSITY = 2.0      # slices per output pixel of extrusion; higher = smoother near edge-on


# --------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------
FONT_FILES = {
    ("arial", False): ["arialbd.ttf", "Arial Bold.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"],
    ("arial", True): ["arialbi.ttf", "Arial Bold Italic.ttf", "LiberationSans-BoldItalic.ttf",
                      "DejaVuSans-BoldOblique.ttf"],
    ("times", False): ["timesbd.ttf", "Times New Roman Bold.ttf", "LiberationSerif-Bold.ttf",
                       "DejaVuSerif-Bold.ttf"],
    ("times", True): ["timesbi.ttf", "LiberationSerif-BoldItalic.ttf", "DejaVuSerif-BoldItalic.ttf"],
    ("impact", False): ["impact.ttf", "Impact.ttf", "Anton-Regular.ttf", "LiberationSans-Bold.ttf",
                        "DejaVuSans-Bold.ttf"],
}
FONT_DIRS = ["C:/Windows/Fonts", "/cygdrive/c/Windows/Fonts", "/mnt/c/Windows/Fonts",
             "/usr/share/fonts", "/usr/local/share/fonts", "/usr/X11R6/lib/X11/fonts",
             "/Library/Fonts", "/System/Library/Fonts", "~/.fonts", "~/.local/share/fonts",
             "~/Library/Fonts"]
_font_index = None


def font_index():
    """lowercase filename -> full path for every font file we can see."""
    global _font_index
    if _font_index is None:
        _font_index = {}
        for d in FONT_DIRS:
            d = os.path.expanduser(d)
            if not os.path.isdir(d):
                continue
            for root, _dirs, files in os.walk(d):
                for f in files:
                    if f.lower().endswith((".ttf", ".otf", ".ttc")):
                        _font_index.setdefault(f.lower(), os.path.join(root, f))
    return _font_index


def find_font(family, italic, override=None):
    if override:
        if os.path.isfile(override):
            return override
        hit = font_index().get(override.lower()) or font_index().get(override.lower() + ".ttf")
        if hit:
            return hit
        sys.exit("bidet3d: font '%s' not found" % override)
    cands = FONT_FILES.get((family, italic)) or FONT_FILES[(family, False)]
    for c in cands:
        hit = font_index().get(c.lower())
        if hit:
            return hit
    for c in cands:              # let Pillow try its own search path
        try:
            ImageFont.truetype(c, 12)
            return c
        except OSError:
            pass
    return None


def load_font(path, px):
    if path:
        return ImageFont.truetype(path, max(4, int(px)))
    try:
        return ImageFont.load_default(size=max(4, int(px)))
    except TypeError:
        return ImageFont.load_default()


# --------------------------------------------------------------------------
# Flat layer: text mask -> shape warp -> material -> bevel
# --------------------------------------------------------------------------
def text_width(font, s, spacing):
    if spacing == 0:
        return font.getlength(s)
    return sum(font.getlength(ch) + spacing for ch in s) - spacing if s else 0


def draw_mask(lines, font, spacing, line_mul):
    ascent, descent = font.getmetrics()
    lh = int((ascent + descent) * line_mul)
    widths = [text_width(font, ln, spacing) for ln in lines]
    pad = int(ascent * 0.5) + 4
    W = int(max(widths)) + 2 * pad
    H = lh * len(lines) + 2 * pad
    im = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(im)
    for i, ln in enumerate(lines):
        x = (W - widths[i]) / 2.0
        y = pad + i * lh
        if spacing == 0:
            d.text((x, y), ln, font=font, fill=255)
        else:
            for ch in ln:
                d.text((x, y), ch, font=font, fill=255)
                x += font.getlength(ch) + spacing
    return im.crop(im.getbbox() or (0, 0, 1, 1))


def bilinear(arr, sx, sy):
    h, w = arr.shape
    x0 = np.floor(sx).astype(np.int32)
    y0 = np.floor(sy).astype(np.int32)
    fx = (sx - x0).astype(np.float32)
    fy = (sy - y0).astype(np.float32)

    def g(yy, xx):
        ok = (xx >= 0) & (xx < w) & (yy >= 0) & (yy < h)
        out = np.zeros(xx.shape, np.float32)
        out[ok] = arr[yy[ok], xx[ok]]
        return out
    return (g(y0, x0) * (1 - fx) * (1 - fy) + g(y0, x0 + 1) * fx * (1 - fy) +
            g(y0 + 1, x0) * (1 - fx) * fy + g(y0 + 1, x0 + 1) * fx * fy)


def warp_arc(m, invert=False, theta=1.9):
    """Bend the text along a circle ("arch up"); invert for a smile."""
    if invert:
        m = m[::-1]
    H, W = m.shape
    R = max(W / theta, 1.25 * H)
    half = (W / R) / 2.0
    Ro = R + H / 2.0
    out_w = int(math.ceil(2 * Ro * math.sin(half))) + 2
    out_h = int(math.ceil(Ro - (Ro - H) * math.cos(half))) + 2
    ys, xs = np.mgrid[0:out_h, 0:out_w].astype(np.float32)
    dx = xs - out_w / 2.0
    dy = Ro - ys
    sx = W / 2.0 + np.arctan2(dx, dy) * R
    sy = Ro - np.hypot(dx, dy)
    out = bilinear(m, sx, sy)
    return out[::-1] if invert else out


def warp_squeeze(m, peak=1.45, ends=0.8):
    """Tall in the middle, pinched at the ends."""
    H, W = m.shape
    out_h = int(H * peak) + 2
    ys, xs = np.mgrid[0:out_h, 0:W].astype(np.float32)
    t = (xs - W / 2.0) / (W / 2.0)
    s = peak - (peak - ends) * t * t
    return bilinear(m, xs, (ys - out_h / 2.0) / s + H / 2.0)


def warp_wave(m):
    H, W = m.shape
    A = 0.18 * H
    lam = max(W / 1.5, 2.5 * H)
    out_h = int(H + 2 * A) + 2
    ys, xs = np.mgrid[0:out_h, 0:W].astype(np.float32)
    shift = A + A * np.sin(2 * math.pi * xs / lam)
    return bilinear(m, xs, ys - shift)


SHAPES = {"arc": lambda m: warp_arc(m), "inverted-arc": lambda m: warp_arc(m, True),
          "squeeze": warp_squeeze, "wave": warp_wave}


def dilate(u8, r):
    """Disc dilation of a uint8 mask by r pixels."""
    if r <= 0:
        return u8
    H, W = u8.shape
    padded = np.pad(u8, r)
    out = u8.copy()
    for dy in range(-r, r + 1):
        ext = int(math.sqrt(max(0, r * r - dy * dy)) + 0.5)
        for dx in range(-ext, ext + 1):
            np.maximum(out, padded[r + dy:r + dy + H, r + dx:r + dx + W], out=out)
    return out


def lerp_stops(t, stops):
    pos = [s[0] for s in stops]
    cols = np.array([C(s[1]) for s in stops], np.float32)
    return np.stack([np.interp(t, pos, cols[:, i]) for i in range(3)], -1).astype(np.float32)


TEXTURE_FALLBACK = {   # (dark, light) for when the Word textures are not installed
    "GreenMarble": ("#1f4427", "#b2cabd"),
    "Granite": ("#6b6b6b", "#d0d0d0"),
    "PaperBag": ("#9c7d4f", "#d9bd8a"),
}


def texture_dirs(extra=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ds = [extra, os.environ.get("BIDET3D_TEXTURES"), os.path.join(here, "textures"),
          os.path.join(here, "..", "css3wordart", "less", "textures"),
          "/usr/local/share/BIDeT3D/textures"]
    return [d for d in ds if d]


def texture_fill(name, w, h, sz, tex_dir):
    for d in texture_dirs(tex_dir):
        p = os.path.join(d, "Texture-%s.png" % name)
        if os.path.isfile(p):
            tile = Image.open(p).convert("RGB")
            k = max(0.75, sz / 72.0)
            tile = tile.resize((max(1, int(tile.width * k)), max(1, int(tile.height * k))), Image.LANCZOS)
            a = np.asarray(tile, np.float32)
            ry = -(-h // a.shape[0])
            rx = -(-w // a.shape[1])
            return np.tile(a, (ry, rx, 1))[:h, :w]
    # procedural stand-in: blurred noise mapped between two colours
    dark, light = (np.array(C(c), np.float32) for c in TEXTURE_FALLBACK[name])
    rng = np.random.default_rng(zlib_seed(name))
    n = rng.random((h // 4 + 2, w // 4 + 2)).astype(np.float32)
    im = Image.fromarray((n * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    im = im.filter(ImageFilter.GaussianBlur(max(1, sz / 40.0)))
    t = np.asarray(im, np.float32)
    t = (t - t.min()) / max(1e-6, t.max() - t.min())
    return dark + (light - dark) * t[..., None]


def zlib_seed(s):
    import zlib
    return zlib.crc32(s.encode())


def tile_fill(name, w, h, sz):
    if name == "gray-check":
        t = np.array([[(178,) * 3, (232,) * 3], [(232,) * 3, (178,) * 3]], np.float32)
    else:  # yellow-dash, decoded from css3wordart's 8x8 tile
        t = np.empty((8, 8, 3), np.float32)
        t[:] = (255, 250, 40)
        t[0, 0:4] = (109, 109, 109)
        t[4, 4:8] = (109, 109, 109)
    k = max(1, int(round(sz / 48.0)))
    t = np.repeat(np.repeat(t, k, 0), k, 1)
    return np.tile(t, (-(-h // t.shape[0]), -(-w // t.shape[1]), 1))[:h, :w]


def resolve_ink(spec, bg):
    """Swap the '@ink' placeholder for white-on-dark / black-on-light."""
    if spec[0] == "solid" and spec[1] == "@ink":
        lum = (0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]) / 255.0
        return ("solid", "#ffffff" if lum < 0.5 else "#000000")
    return spec


def make_fill(spec, w, h, bbox, sz, tex_dir):
    kind = spec[0]
    x0, y0, x1, y1 = bbox
    if kind == "solid":
        out = np.empty((h, w, 3), np.float32)
        out[:] = C(spec[1])
        return out
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if kind == "linear":
        if spec[1] == "v":
            t = (yy - y0) / max(1.0, y1 - y0)
        else:
            t = (xx - x0) / max(1.0, x1 - x0)
        return lerp_stops(np.clip(t, 0, 1), spec[2])
    if kind == "radial":
        nx = (xx - (x0 + x1) / 2.0) / max(1.0, (x1 - x0) / 2.0)
        ny = (yy - (y0 + y1) / 2.0) / max(1.0, (y1 - y0) / 2.0)
        return lerp_stops(np.clip(np.hypot(nx, ny) / 1.4142, 0, 1), spec[1])
    if kind == "texture":
        return texture_fill(spec[1], w, h, sz, tex_dir)
    if kind == "tile":
        return tile_fill(spec[1], w, h, sz)
    raise ValueError(kind)


LIGHT = np.array([-0.45, -0.55, 0.70], np.float32)
LIGHT /= np.linalg.norm(LIGHT)


class Layer:
    """Everything the 3D stage needs, all at supersampled resolution."""
    pass


def build_layer(lines, p, px, ss, args, tex_dir):
    sz = px * ss
    path = find_font(p["font"], p["italic"], args.font)
    font = load_font(path, sz)
    if args.debug:
        print("font: %s" % path, file=sys.stderr)
    mask_im = draw_mask(lines, font, p["spacing"] * sz, 0.8 if p["stacked"] else args.line)
    m = np.asarray(mask_im, np.float32) / 255.0
    shape = args.shape or p["shape"]
    if shape and shape != "plain":
        m = SHAPES[shape](m)
    pad = int(0.16 * sz) + 2
    m = np.pad(m, pad)
    u8 = (m * 255).astype(np.uint8)
    H, W = u8.shape

    ys, xs = np.nonzero(u8 > 8)
    bbox = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)

    # silhouette (face + outline)
    if p["stroke"]:
        sil = dilate(u8, max(1, int(round(p["stroke"][1] * sz))))
    else:
        sil = u8

    # face material + bevel lighting
    fill = make_fill(resolve_ink(args._fill or p["fill"], args.bg), W, H, bbox, sz, tex_dir)
    sig = max(1.0, 0.045 * sz)
    hmap = np.asarray(Image.fromarray(u8).filter(ImageFilter.GaussianBlur(sig)), np.float32) / 255.0
    gy, gx = np.gradient(hmap)
    k = sig * 3.0
    n = np.stack([-gx * k, -gy * k, np.ones_like(gx)], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    shade = 1.0 + p["bevel"] * 2.4 * (n @ LIGHT - LIGHT[2])
    face = fill * np.clip(shade, 0.35, 1.6)[..., None]
    if p["stroke"]:
        sc = np.array(C(p["stroke"][0]), np.float32)
        face = face * m[..., None] + sc * (1 - m[..., None])
    face = np.clip(face, 0, 255).astype(np.uint8)

    # side shading: brightness by which way the silhouette edge faces
    sig2 = max(1.0, 0.025 * sz)
    sm = np.asarray(Image.fromarray(sil).filter(ImageFilter.GaussianBlur(sig2)), np.float32) / 255.0
    sy_, sx_ = np.gradient(sm)
    mag = np.hypot(sx_, sy_)
    facing = np.where(mag > 1e-4, (-sx_ * LIGHT[0] - sy_ * LIGHT[1]) / np.maximum(mag, 1e-4), 0.0)
    side_shade = 0.55 + 0.75 * np.clip(facing * 0.5 + 0.5, 0, 1)
    side_shade = np.where(mag > 1e-4, side_shade, 0.8).astype(np.float32)

    L = Layer()
    L.w, L.h, L.px, L.sz = W, H, px, sz
    L.face = Image.fromarray(np.dstack([face, sil]))
    L.sil = sil
    L.side_shade = side_shade
    side = p["side"]
    if side is _GREY_SIDE and args.bg and sum(args.bg) < 380:
        side = ("#3a3a3a", "#9a9a9a")          # lighter greys suit white ink
    if side:
        back, front = (np.array(C(c), np.float32) for c in side)
    else:
        avg = fill[u8 > 128].mean(axis=0) if (u8 > 128).any() else np.array([128.0] * 3)
        back, front = avg * 0.25, avg * 0.55
    L.back, L.front = back, front
    L.depth = (args.depth if args.depth is not None else p["depth"]) * sz
    return L


# --------------------------------------------------------------------------
# 3D: rotation, perspective camera, slice-stack renderer
# --------------------------------------------------------------------------
def rot_matrix(yaw, pitch, roll):
    """x right, y down, z away from the viewer.
    yaw: right edge recedes; pitch: top edge recedes; roll: clockwise."""
    y, p, r = (math.radians(a) for a in (yaw, pitch, roll))
    cy, sy = math.cos(y), math.sin(y)
    cp, sp = math.cos(p), math.sin(p)
    cr, sr = math.cos(r), math.sin(r)
    Ry = np.array([[cy, 0, -sy], [0, 1, 0], [sy, 0, cy]])
    Rx = np.array([[1, 0, 0], [0, cp, sp], [0, -sp, cp]])
    Rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]])
    return Rz @ Rx @ Ry


def model_matrix(p, view, args):
    sx = math.tan(math.radians(p["skewx"]))
    sy = math.tan(math.radians(p["skewy"]))
    A = np.array([[1, sx, 0], [sy, 1, 0], [0, 0, 1]]) @ np.diag([1.0, p["sy"], 1.0])
    return rot_matrix(*view) @ A


def project(pts, M, f):
    q = pts @ M.T
    fac = f / (f + q[:, 2])
    return np.stack([q[:, 0] * fac, q[:, 1] * fac], 1)


def persp_coeffs(dest, src):
    A, B = [], []
    for (X, Y), (x, y) in zip(dest, src):
        A.append([X, Y, 1, 0, 0, 0, -X * x, -Y * x])
        B.append(x)
        A.append([0, 0, 0, X, Y, 1, -X * y, -Y * y])
        B.append(y)
    return np.linalg.solve(np.array(A, float), np.array(B, float))


def layer_quads(L, M, f, zs):
    hw, hh = L.w / 2.0, L.h / 2.0
    corners = np.array([[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]])
    return [project(np.c_[corners, np.full(4, z)], M, f) for z in zs]


def view_bounds(L, p, views, persp, args):
    """Union of projected extents over several views (fixed canvas for animation)."""
    f = persp * max(L.w, L.h)
    lo = np.array([1e9, 1e9])
    hi = -lo
    for v in views:
        M = model_matrix(p, v, args)
        for q in layer_quads(L, M, f, (0.0, L.depth)):
            lo = np.minimum(lo, q.min(0))
            hi = np.maximum(hi, q.max(0))
    return lo, hi


def render(L, p, view, persp, bg, args, bounds=None):
    """Returns an RGB PIL image (supersampled, background filled)."""
    M = model_matrix(p, view, args)
    f = persp * max(L.w, L.h)
    q0, q1 = layer_quads(L, M, f, (0.0, L.depth))
    if bounds is None:
        bounds = (np.minimum(q0.min(0), q1.min(0)), np.maximum(q0.max(0), q1.max(0)))
    lo = np.floor(bounds[0]) - 2
    hi = np.ceil(bounds[1]) + 2
    cw, ch = int(hi[0] - lo[0]), int(hi[1] - lo[1])
    if cw * ch > 60_000_000:
        sys.exit("bidet3d: image too large (%dx%d); lower -s or --ss" % (cw, ch))
    canvas = Image.new("RGBA", (cw, ch), tuple(bg) + (255,))

    n = 1
    if L.depth > 0:
        disp = float(np.abs(q1 - q0).max())
        n = int(min(max(math.ceil(disp * SLICE_DENSITY) + 1, 2), 320))
    zs = [L.depth * k / max(1, n - 1) for k in range(n)]
    quads = layer_quads(L, M, f, zs)
    order = sorted(range(n), key=lambda k: -M[2, 2] * zs[k])      # farthest first
    src = [(0, 0), (L.w, 0), (L.w, L.h), (0, L.h)]
    shade3 = L.side_shade[..., None]

    for k in order:
        if k == 0 and M[2, 2] > 0:
            img = L.face                      # front cap, facing us
        else:
            t = k / float(max(1, n - 1))
            col = L.front * (1 - t) + L.back * t
            rgb = np.clip(shade3 * col, 0, 255).astype(np.uint8)
            img = Image.fromarray(np.dstack([rgb, L.sil]))
        try:
            co = persp_coeffs(quads[k] - lo, src)
        except np.linalg.LinAlgError:
            continue                          # edge-on: slice has no area
        canvas.alpha_composite(img.transform((cw, ch), Image.PERSPECTIVE, tuple(co), Image.BILINEAR))
    return canvas.convert("RGB")


def finish(img, ss, max_w, max_h):
    """Downscale the supersampled render and fit it to the terminal."""
    w, h = img.size
    k = 1.0 / ss
    k = min(k, max_w / float(w), max_h / float(h))
    if k < 1.0:
        img = img.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
    return img


# --------------------------------------------------------------------------
# Terminal + SIXEL (libsixel)
# --------------------------------------------------------------------------
def term_geometry(args):
    cols, rows = shutil.get_terminal_size((80, 24))
    cw = ch = None
    cell = args.cell or os.environ.get("BIDET3D_CELL")
    if cell:
        try:
            cw, ch = (float(v) for v in cell.lower().split("x"))
        except ValueError:
            sys.exit("bidet3d: --cell expects WxH, e.g. 10x20")
    elif os.name == "posix":
        try:
            import fcntl, struct, termios
            r, c, xp, yp = struct.unpack("HHHH", fcntl.ioctl(1, termios.TIOCGWINSZ, b"\0" * 8))
            if xp and yp and r and c:
                cw, ch = xp / float(c), yp / float(r)
        except Exception:
            pass
    if not cw:
        cw, ch = 10.0, 20.0
    return cols, rows, cw, ch


def query_bg(timeout=0.25):
    """Ask the terminal for its background colour (OSC 11). POSIX tty only."""
    if os.name != "posix" or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    try:
        import select, termios, tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
    except Exception:
        return None
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\x1b]11;?\x1b\\")
        sys.stdout.flush()
        buf = ""
        while select.select([fd], [], [], timeout)[0]:
            buf += os.read(fd, 64).decode("latin1")
            if buf.endswith("\\") or buf.endswith("\x07"):
                break
        m = re.search(r"rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)", buf)
        if m:
            return tuple(int(int(g, 16) / float(16 ** len(g) - 1) * 255) for g in m.groups())
    except Exception:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return None


_backend = None


def to_sixel(img, ncolors=256, debug=False):
    """RGB PIL image -> SIXEL bytes.  libsixel's Python binding if present,
    otherwise the img2sixel program from the same package."""
    global _backend
    w, h = img.size
    if _backend in (None, "binding"):
        try:
            import libsixel
            data = img.convert("RGB").tobytes()
            buf = io.BytesIO()
            out = libsixel.sixel_output_new(lambda d, fp: fp.write(d), buf)
            dither = libsixel.sixel_dither_new(ncolors)
            libsixel.sixel_dither_initialize(dither, data, w, h, libsixel.SIXEL_PIXELFORMAT_RGB888,
                                             libsixel.SIXEL_LARGE_AUTO, libsixel.SIXEL_REP_AUTO,
                                             libsixel.SIXEL_QUALITY_HIGH)
            status = libsixel.sixel_encode(data, w, h, 3, dither, out)
            if libsixel.SIXEL_FAILED(status):
                raise RuntimeError(libsixel.sixel_helper_format_error(status))
            if debug and _backend is None:
                print("sixel: libsixel python binding", file=sys.stderr)
            _backend = "binding"
            return buf.getvalue()
        except (ImportError, OSError, RuntimeError) as e:
            # OSError: the binding is ctypes, so a missing libsixel.so surfaces here
            if debug and not isinstance(e, ImportError):
                print("sixel: python binding unusable (%s); using img2sixel" % e, file=sys.stderr)
            _backend = "cli"
    exe = shutil.which("img2sixel")
    if not exe:
        sys.exit("bidet3d: need libsixel: 'pip install libsixel-python' or install img2sixel "
                 "(https://github.com/saitoha/libsixel)")
    if debug and _backend == "cli":
        print("sixel: %s" % exe, file=sys.stderr)
        _backend = "cli-announced"
    bio = io.BytesIO()
    img.save(bio, "PNG")
    r = subprocess.run([exe, "-p", str(ncolors)], input=bio.getvalue(), stdout=subprocess.PIPE)
    if r.returncode:
        sys.exit("bidet3d: img2sixel failed")
    return r.stdout


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------
def parse_color(s):
    try:
        return ImageColor.getrgb(s)[:3]
    except ValueError:
        sys.exit("bidet3d: bad colour '%s'" % s)


def get_lines(args, preset):
    if not args.text or args.text == ["-"]:
        raw = sys.stdin.read().splitlines() if not sys.stdin.isatty() else []
    else:
        raw = args.text
    if not raw:
        raw = ["BIDeT3D"]
    if preset["stacked"]:
        chars = "".join(raw).replace("\n", "")
        return [c if c != " " else "" for c in chars] or [" "]
    if args.preserve:
        return [ln.rstrip("\n") for ln in raw] or [" "]
    text = " ".join(ln.strip() for ln in raw)
    return textwrap.fill(text, args.width).split("\n")


def auto_px(lines, p, max_w, max_h):
    longest = max(len(ln) for ln in lines)
    em_w = longest * (0.7 if p["stacked"] else 0.6)
    px = 0.85 * max_w / max(1.0, em_w * (1.1 if p["shape"] == "arc" else 1.0))
    px = min(px, 0.7 * max_h / (len(lines) * 1.2 * max(1.0, p["sy"]) * (0.8 if p["stacked"] else 1.0)))
    return int(max(28, min(px, 150)))


def make_scene(args, name, tex_dir, max_w, max_h, px=None, ss=None):
    p = PRESETS[name]
    lines = get_lines(args, p)
    if px is None:
        px = args.size or auto_px(lines, p, max_w, max_h)
    ss = ss or args.ss
    L = build_layer(lines, p, px, ss, args, tex_dir)
    return p, L


def pick_view(p, args):
    v = tuple(p["view"]) if p["view"] else DEFAULT_VIEW
    if args.view:
        try:
            v = tuple(float(x) for x in args.view.split(","))
            assert len(v) == 3
        except (ValueError, AssertionError):
            sys.exit("bidet3d: --view expects YAW,PITCH,ROLL in degrees")
    over = (args.yaw, args.pitch, args.roll)
    return tuple(o if o is not None else c for o, c in zip(over, v))


def emit(out, sixel):
    out.write(sixel)
    out.flush()


def do_spin(args, p, L, view, bg, max_w, max_h, cell_h):
    out = sys.stdout.buffer
    speed = args.spin_speed
    fps = max(1.0, args.fps)
    if args.sway:
        views = [(view[0] + args.sway * math.sin(2 * math.pi * i / 36.0), view[1], view[2]) for i in range(36)]
    else:
        views = [(view[0] + i * 10.0, view[1], view[2]) for i in range(36)]
    bounds = view_bounds(L, p, views, args.perspective, args)
    t0 = time.time()
    nframes = 0
    rows = None
    try:
        while args.frames == 0 or nframes < args.frames:
            ts = time.time()
            t = ts - t0 if not args.frames else nframes / fps
            if args.sway:
                yaw = view[0] + args.sway * math.sin(2 * math.pi * t * speed / 360.0)
            else:
                yaw = view[0] + speed * t
            img = finish(render(L, p, (yaw, view[1], view[2]), args.perspective, bg, args, bounds),
                         args.ss, max_w, max_h)
            if rows is None:
                rows = int(math.ceil(img.height / cell_h)) + 1
                out.write(b"\n" * rows + ("\x1b[%dA" % rows).encode() + b"\x1b7\x1b[?25l")
            out.write(b"\x1b8")
            emit(out, to_sixel(img, args.colors, args.debug and nframes == 0))
            nframes += 1
            dt = 1.0 / fps - (time.time() - ts)
            if dt > 0:
                time.sleep(dt)
    except KeyboardInterrupt:
        pass
    finally:
        if rows is not None:
            out.write(b"\x1b8" + ("\x1b[%dB" % rows).encode() + b"\x1b[?25h\n")
            out.flush()


def main():
    ap = argparse.ArgumentParser(
        description="BIDeT3D - 3D WordArt for SIXEL terminals. Text comes from the "
                    "arguments, or stdin. (After banner, FIGlet, TOIlet and BIDeT.)")
    ap.add_argument("-b", "--background", default="transparent",
                    help="background colour; 'transparent' = ask the terminal (default), else black")
    ap.add_argument("-c", "--colour", "--color", dest="colour",
                    help="solid face colour (overrides the preset's material)")
    ap.add_argument("-d", "--debug", action="store_true", help="timings and backend info on stderr")
    ap.add_argument("-f", "--font", help="font file or file name (overrides the preset's font)")
    ap.add_argument("-l", "--line", type=float, default=1.0, help="line spacing (default 1.0)")
    ap.add_argument("-p", "--preserve", action="store_true", help="preserve newlines instead of re-wrapping")
    ap.add_argument("-s", "--size", type=int, default=0, help="font size in pixels (default: fit the terminal)")
    ap.add_argument("-w", "--width", type=int, default=20, help="wrap width in characters (default 20)")
    ap.add_argument("-v", "--version", action="store_true")
    ap.add_argument("-P", "--preset", default=DEFAULT_PRESET,
                    help="WordArt style, or 'random' (default %s); see --list-presets" % DEFAULT_PRESET)
    ap.add_argument("--list-presets", action="store_true")
    ap.add_argument("--gallery", action="store_true", help="show every preset with the given text")
    ap.add_argument("--depth", type=float, help="extrusion depth in em (default: per preset)")
    ap.add_argument("--view", metavar="YAW,PITCH,ROLL",
                    help="camera angles in degrees, written --view=-30,10,0 (default: per preset)")
    ap.add_argument("--yaw", type=float, help="set just the yaw (left/right turn)")
    ap.add_argument("--pitch", type=float, help="set just the pitch (tip back/forward)")
    ap.add_argument("--roll", type=float, help="set just the roll (clockwise)")
    ap.add_argument("--shape", choices=["plain", "arc", "inverted-arc", "squeeze", "wave"],
                    help="baseline warp (default: per preset)")
    ap.add_argument("--perspective", type=float, default=2.5,
                    help="camera distance in text-widths; smaller = stronger perspective (default 2.5)")
    ap.add_argument("--spin", action="store_true", help="animate: rotate around the vertical axis (Ctrl-C stops)")
    ap.add_argument("--sway", type=float, metavar="DEG", help="animate: swing +-DEG around the view instead of spinning")
    ap.add_argument("--spin-speed", type=float, default=60.0, help="degrees per second (default 60)")
    ap.add_argument("--fps", type=float, default=8.0, help="target frames per second (default 8)")
    ap.add_argument("--frames", type=int, default=0, help="stop the animation after N frames (default: until Ctrl-C)")
    ap.add_argument("--ss", type=int, help="supersampling factor (default 2, 1 when animating)")
    ap.add_argument("--colors", type=int, default=256, help="SIXEL palette size (default 256)")
    ap.add_argument("--png", metavar="FILE", help="write a PNG instead of printing SIXEL")
    ap.add_argument("--texture-dir", help="directory with css3wordart's Texture-*.png (see README)")
    ap.add_argument("--cell", metavar="WxH", help="terminal cell size in pixels when it cannot be detected")
    ap.add_argument("text", nargs="*")
    args = ap.parse_args()

    if args.version:
        print("BIDeT3D %s" % VERSION)
        return
    if args.list_presets:
        print("\n".join(PRESET_ORDER))
        return
    if args.preset == "random":
        args.preset = random.choice(PRESET_ORDER)
    if args.preset not in PRESETS and not args.gallery:
        sys.exit("bidet3d: unknown preset '%s' (try --list-presets)" % args.preset)
    animate = args.spin or args.sway is not None
    if args.ss is None:
        args.ss = 1 if animate else 2
    args._fill = ("solid", "#%02x%02x%02x" % parse_color(args.colour)) if args.colour else None

    # terminal + background
    cols, rows, cw, ch = term_geometry(args)
    max_w = cols * cw * 0.98
    if "xterm" in os.environ.get("TERM", "") and max_w > 1000:
        max_w = 1000          # xterm cannot show SIXEL wider than 1000px
    max_h = max(1, (rows - 2)) * ch
    if args.background == "transparent":
        bg = query_bg() if not args.png else None
        bg = bg or (0, 0, 0)
    else:
        bg = parse_color(args.background)
    args.bg = bg
    tex_dir = args.texture_dir

    t_start = time.time()
    if args.gallery:
        out = sys.stdout.buffer
        for name in PRESET_ORDER:
            print(name)
            p, L = make_scene(args, name, tex_dir, max_w, max_h / 3, px=args.size or 56, ss=args.ss)
            img = finish(render(L, p, pick_view(p, args), args.perspective, bg, args), args.ss, max_w, max_h / 2)
            emit(out, to_sixel(img, args.colors, args.debug))
            print()
        return

    p, L = make_scene(args, args.preset, tex_dir, max_w, max_h)
    view = pick_view(p, args)
    if args.debug:
        print("preset=%s px=%d layer=%dx%d depth=%.0f view=%s build=%.2fs" %
              (args.preset, L.px, L.w, L.h, L.depth, view, time.time() - t_start), file=sys.stderr)

    if animate and not args.png:
        do_spin(args, p, L, view, bg, max_w, max_h, ch)
        return

    t1 = time.time()
    img = finish(render(L, p, view, args.perspective, bg, args), args.ss, max_w, max_h)
    if args.debug:
        print("render=%.2fs final=%dx%d" % (time.time() - t1, img.width, img.height), file=sys.stderr)
    if args.png:
        img.save(args.png)
        return
    emit(sys.stdout.buffer, to_sixel(img, args.colors, args.debug))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
