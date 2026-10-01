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
import types

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
MAX_LOOP_FRAMES = 120     # longest pre-rendered animation loop
SIDE_LEVELS = 48          # distinct extrusion shades (cached per level)
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
    L.side_cache = {}
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
    """Returns an RGB PIL image (supersampled, background filled), or with bg=None an
    RGBA one whose background is truly transparent."""
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
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0) if bg is None else tuple(bg) + (255,))

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
            # side colour depends only on depth, so quantize it and reuse the images
            # across slices and across animation frames
            lvl = int(round(k / float(max(1, n - 1)) * SIDE_LEVELS))
            img = L.side_cache.get(lvl)
            if img is None:
                t = lvl / float(SIDE_LEVELS)
                col = L.front * (1 - t) + L.back * t
                rgb = np.clip(shade3 * col, 0, 255).astype(np.uint8)
                img = L.side_cache[lvl] = Image.fromarray(np.dstack([rgb, L.sil]))
        q = quads[k] - lo
        x0 = max(0, int(math.floor(q[:, 0].min())) - 1)
        y0 = max(0, int(math.floor(q[:, 1].min())) - 1)
        x1 = min(cw, int(math.ceil(q[:, 0].max())) + 1)
        y1 = min(ch, int(math.ceil(q[:, 1].max())) + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        try:
            co = persp_coeffs(q - (x0, y0), src)
        except np.linalg.LinAlgError:
            continue                          # edge-on: slice has no area
        # rasterize only the slice's own bounding box, not the whole canvas
        canvas.alpha_composite(img.transform((x1 - x0, y1 - y0), Image.PERSPECTIVE, tuple(co),
                                             Image.BILINEAR), (x0, y0))
    return canvas if bg is None else canvas.convert("RGB")


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


def query_terminal(want_bg=True, timeout=0.25, da_timeout=1.0, debug=False):
    """Ask the terminal two things in one raw-mode session (POSIX tty only):
    does it report SIXEL (DA1 attribute 4, like BIDeT's test-sixel), and what is its
    background colour (OSC 11).  Returns (sixel, bg): sixel is True/False, or None when
    we cannot ask or it did not answer; bg is an (r, g, b) tuple or None."""
    if os.name != "posix" or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None, None
    if os.environ.get("TERM", "").startswith("yaft"):
        return True, (0, 0, 0)            # yaft cannot answer DA1 (as in test-sixel.sh)
    try:
        import select, termios, tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
    except Exception:
        return None, None

    def ask(seq, done, to):
        sys.stdout.write(seq)
        sys.stdout.flush()
        buf = ""
        while select.select([fd], [], [], to)[0]:
            buf += os.read(fd, 64).decode("latin1")
            if done(buf):
                break
        return buf

    sixel = bg = None
    try:
        tty.setcbreak(fd)
        da = ask("\x1b[c", lambda b: b.endswith("c"), da_timeout)
        if debug:
            print("terminal: DA1 reply %r" % da, file=sys.stderr)
        m = re.search(r"\x1b\[\?([0-9;]*)c", da)
        if m:
            sixel = "4" in m.group(1).split(";")
        if want_bg:
            buf = ask("\x1b]11;?\x1b\\", lambda b: b.endswith("\\") or b.endswith("\x07"), timeout)
            if debug:
                print("terminal: OSC 11 (background) reply %r" % buf, file=sys.stderr)
            m = re.search(r"rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)", buf)
            if m:
                bg = tuple(int(round(int(g, 16) / float(16 ** len(g) - 1) * 255)) for g in m.groups())
    except Exception:
        pass
    finally:
        try:
            termios.tcflush(fd, termios.TCIFLUSH)      # drop any reply that arrived too late
        except Exception:
            pass
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return sixel, bg


_backend = None


def _keyed_header(six, key):
    """P2=1 in the DCS header: unpainted pixels stay as they are (transparent) rather than
    being filled with a background colour the terminal may choose differently."""
    if key is not None and six.startswith(b"\x1bPq"):
        return b"\x1bP0;1;q" + six[3:]
    return six


def to_sixel(img, ncolors=256, debug=False):
    """PIL image -> SIXEL bytes.  libsixel's Python binding if present, otherwise the
    img2sixel program from the same package.  A P-mode image whose info["transparency"]
    is a palette index gets that colour left unpainted (a transparent background)."""
    global _backend
    w, h = img.size
    key = img.info.get("transparency") if img.mode == "P" else None
    if not isinstance(key, int):
        key = None
    if _backend in (None, "binding"):
        try:
            import libsixel
            data = img.convert("RGB").tobytes()
            buf = io.BytesIO()
            out = libsixel.sixel_output_new(lambda d, fp: fp.write(d), buf)
            dither = None
            if img.mode == "P":
                # We quantized already (exact background): give libsixel that very palette.
                # Its own quantizer would average the flat background with nearby colours.
                # The binding's sixel_dither_set_palette() is Python-2 code (a str handed to
                # a c_char_p), so call the underlying ctypes function with bytes.
                try:
                    import ctypes
                    nent = img.getextrema()[1] + 1
                    d = libsixel.sixel_dither_new(nent)
                    libsixel._sixel.sixel_dither_set_palette.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
                    libsixel._sixel.sixel_dither_set_palette(d, bytes(img.getpalette()[:3 * nent]))
                    libsixel.sixel_dither_set_diffusion_type(d, libsixel.SIXEL_DIFFUSE_NONE)
                    if key is not None:
                        libsixel.sixel_dither_set_transparent(d, key)
                    dither = d
                except Exception as e:
                    if debug:
                        print("sixel: cannot set exact palette (%s); letting libsixel quantize" % e,
                              file=sys.stderr)
            if dither is None:
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
            return _keyed_header(buf.getvalue(), key)
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
    return _keyed_header(r.stdout, key)     # (PNG saving writes the tRNS chunk img2sixel keys on)


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


_SPINNER = "|/-\\"
_verbose = False      # -d: show the full progress text instead of a spinner


def busy(i, text=""):
    """Show that we are working: a spinning cursor on stderr (the text itself with -d).
    Nothing at all when stderr is not a terminal."""
    if not sys.stderr.isatty():
        return
    sys.stderr.write(("\r%s " % text) if _verbose else (_SPINNER[i % 4] + "\b"))
    sys.stderr.flush()


def busy_done():
    if sys.stderr.isatty():
        sys.stderr.write("\r\x1b[K" if _verbose else " \b")
        sys.stderr.flush()


_W = {}


def _worker_init(state):
    _W.update(state)


def _worker_frame(view):
    s = _W
    return finish(render(s["L"], s["p"], view, s["persp"], s["bg"], s["args"], s["bounds"]),
                  s["ss"], s["max_w"], s["max_h"])


def render_frames(views, state, debug=False):
    """Render every view, spread over the CPU cores; plain loop if a pool can't be had."""
    n = len(views)

    def progress(i):
        busy(i, "pre-rendering %d/%d frames" % (i, n))

    _worker_init(state)
    t = time.time()
    imgs = [_worker_frame(views[0])]
    per_frame = time.time() - t
    progress(1)
    # Starting a pool costs ~1-2 s, so only use one when the rest of the loop is long
    # enough to repay it.  Physical cores ~ half the logical ones.
    workers = min(4, max(2, (os.cpu_count() or 2) // 2), n - 1)
    if (n - 1) * per_frame > 4.0 and workers > 1 and not os.environ.get("BIDET3D_SERIAL"):
        try:
            from concurrent.futures import ProcessPoolExecutor
            more = []
            with ProcessPoolExecutor(workers, initializer=_worker_init, initargs=(state,)) as ex:
                for im in ex.map(_worker_frame, views[1:]):
                    more.append(im)
                    progress(1 + len(more))
            if debug:
                print("rendered on %d processes" % workers, file=sys.stderr)
            return imgs + more
        except KeyboardInterrupt:
            raise
        except Exception as e:     # fork/spawn trouble (e.g. Cygwin): just do it serially
            if debug:
                print("process pool failed (%s: %s); rendering serially" % (type(e).__name__, e), file=sys.stderr)
    for v in views[len(imgs):]:
        imgs.append(_worker_frame(v))
        progress(len(imgs))
    return imgs


def to_sixel_many(imgs, ncolors, debug=False):
    """SIXEL for many frames.  The libsixel binding is cheap per call; img2sixel is a
    process per run (slow to fork on Cygwin), so hand it all the frames in one run."""
    first = to_sixel(imgs[0], ncolors, debug)
    rest = imgs[1:]
    if not rest:
        return [first]
    exe = shutil.which("img2sixel")
    if _backend != "binding" and exe:
        import tempfile
        try:
            with tempfile.TemporaryDirectory(prefix="bidet3d_") as d:
                names = []
                for i, im in enumerate(rest):
                    names.append("f%04d.png" % i)
                    im.save(os.path.join(d, names[-1]))
                proc = subprocess.Popen([exe, "-p", str(ncolors)] + names, cwd=d, stdout=subprocess.PIPE)
                tick = 0
                while True:
                    try:
                        out_bytes, _ = proc.communicate(timeout=0.15)
                        break
                    except subprocess.TimeoutExpired:
                        tick += 1
                        busy(tick, "encoding SIXEL")
                r = types.SimpleNamespace(returncode=proc.returncode, stdout=out_bytes)
            key = rest[0].info.get("transparency")
            key = key if isinstance(key, int) else None
            segs = [_keyed_header(b"\x1bP" + s.split(b"\x1b\\")[0] + b"\x1b\\", key)
                    for s in r.stdout.split(b"\x1bP")[1:]]
            if r.returncode == 0 and len(segs) == len(rest):
                return [first] + segs
            if debug:
                print("batch img2sixel gave %d images for %d frames; encoding one by one" %
                      (len(segs), len(rest)), file=sys.stderr)
        except OSError as e:
            if debug:
                print("batch img2sixel failed (%s); encoding one by one" % e, file=sys.stderr)
    return [first] + [to_sixel(im, ncolors) for im in rest]


BG_TOL = 2     # pixels this close to the background colour count as background


def _bg_mask(a, bg):
    return (np.abs(a.astype(np.int16) - np.array(bg, np.int16)) <= BG_TOL).all(-1)


def palette_with_bg(imgs, bg, ncolors, masks=None):
    """Palette for everything that is not background (at most ncolors-1 colours).  The
    background gets its own index, one past the end, added by quantize_exact.  libsixel's
    own quantizer averages a big flat background with nearby colours (white came out as
    247), and a background kept in the nearest-colour search would swallow real pixels
    that happen to be close to it.  masks: per-image boolean "this is background" arrays
    (e.g. alpha < 128); default: pixels within BG_TOL of the colour bg.
    Returns (palette image, index the background will have)."""
    parts = []
    for n, im in enumerate(imgs):
        a = np.asarray(im.convert("RGB"))
        m = _bg_mask(a, bg) if masks is None else masks[n]
        px = a[~m]
        if len(px) > 50000:
            px = px[np.random.default_rng(0).choice(len(px), 50000, replace=False)]
        parts.append(px)
    px = np.concatenate(parts)
    pal = [0, 0, 0]
    if len(px):
        q = Image.fromarray(px.reshape(1, -1, 3)).quantize(
            max(1, ncolors - 1), method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        used = max(i for _n, i in q.getcolors()) + 1
        pal = list(q.getpalette()[:3 * used])
    pimg = Image.new("P", (1, 1))
    # exactly the entries we use: a PNG palette padded past the requested colour count
    # makes img2sixel re-quantize it (and average the background again)
    pimg.putpalette(pal)
    return pimg, len(pal) // 3


def quantize_exact(img, pimg, bg_index, bg, dither, mask=None):
    """Map img onto the palette; every background pixel becomes exactly index bg_index."""
    pal = list(pimg.getpalette()[:3 * bg_index])
    a = np.array(img.convert("RGB"))
    m = _bg_mask(a, bg) if mask is None else mask
    # an exact palette colour has zero quantization error, so no dither error leaks from
    # the background into the pixels beside it
    a[m] = pal[:3]
    q = Image.fromarray(a).quantize(palette=pimg, dither=Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE)
    idx = np.array(q)
    idx[m] = bg_index
    out = Image.frombytes("P", q.size, idx.tobytes())
    out.putpalette(pal + list(bg))
    return out


def sixel_ready(img, bg, ncolors, dither=False, transparent=False):
    """Quantize for SIXEL.  An RGBA image (see render with bg=None) is treated as having a
    transparent background: pixels with alpha < 128 are the background.  With
    transparent=True that entry is marked transparent, so the terminal shows its own
    background there."""
    mask = None
    if img.mode == "RGBA":
        mask = np.asarray(img.getchannel("A")) < 128
    pimg, bi = palette_with_bg([img], bg, ncolors, None if mask is None else [mask])
    q = quantize_exact(img, pimg, bi, bg, dither, mask)
    if transparent:
        q.info["transparency"] = bi
    return q


def do_spin(args, p, L, view, bg, max_w, max_h, cell_w, cell_h, transparent=False):
    """Pre-render one seamless loop, encode it once, then replay the cached
    SIXEL on a steady clock.  Rendering/encoding per frame while playing made
    the frame rate (and the angle jumps) depend on how slow the machine was."""
    out = sys.stdout.buffer
    fps = max(1.0, args.fps)
    speed = max(1.0, abs(args.spin_speed))
    n = max(4, int(round(360.0 / speed * fps)))                              # frames per loop
    if n > MAX_LOOP_FRAMES:      # keep the rotation speed; just show fewer frames per second
        n = MAX_LOOP_FRAMES
        fps = n * speed / 360.0
        if args.debug:
            print("loop capped at %d frames: playing at %.1f fps" % (n, fps), file=sys.stderr)
    sgn = 1.0 if args.spin_speed >= 0 else -1.0
    if args.sway:
        views = [(view[0] + args.sway * math.sin(2 * math.pi * i / n), view[1], view[2]) for i in range(n)]
    else:
        views = [(view[0] + sgn * 360.0 * i / n, view[1], view[2]) for i in range(n)]
    bounds = view_bounds(L, p, views, args.perspective, args)
    keys = [tuple(round(x, 3) for x in v) for v in views]      # sway repeats itself: render each look once
    first_of = {}
    for key, v in zip(keys, views):
        first_of.setdefault(key, v)
    uviews = list(first_of.values())
    slot = {key: i for i, key in enumerate(first_of)}
    order = [slot[key] for key in keys]

    t0 = time.time()
    state = dict(L=L, p=p, persp=args.perspective, bg=None if transparent else bg, args=args, bounds=bounds,
                 ss=args.ss, max_w=max_w, max_h=max_h)
    try:
        imgs = render_frames(uviews, state, args.debug)
        t_render = time.time() - t0
        # one shared palette (colours don't shimmer between frames), exact background
        masks = [np.asarray(im.getchannel("A")) < 128 for im in imgs] if transparent else None
        pick = list(range(0, len(imgs), max(1, len(imgs) // 8)))[:8]
        pimg, bi = palette_with_bg([imgs[i] for i in pick], bg, args.colors,
                                   [masks[i] for i in pick] if masks else None)
        qs = [quantize_exact(im, pimg, bi, bg, False, masks[k] if masks else None)
              for k, im in enumerate(imgs)]
        if transparent:
            for q in qs:
                q.info["transparency"] = bi
        busy(0, "encoding SIXEL")
        usixels = to_sixel_many(qs, args.colors, args.debug)
        sixels = [usixels[j] for j in order]
    except KeyboardInterrupt:
        busy_done()
        return
    busy_done()
    if args.debug:
        print("loop: %d frames (%d distinct), %dx%d; render %.1fs + encode %.1fs; avg %.0f KB/frame" %
              (n, len(uviews), imgs[0].width, imgs[0].height, t_render, time.time() - t0 - t_render,
               sum(map(len, sixels)) / n / 1024.0), file=sys.stderr)

    rows = int(math.ceil(imgs[0].height / cell_h)) + 1
    clear = b""
    if transparent:
        cols = int(math.ceil(imgs[0].width / cell_w)) + 1
        clear = b"\x1b8" + (b"\x1b[%dX\x1b[B" % cols) * (rows - 1)      # ECH each row of the picture
    out.write(b"\n" * rows + ("\x1b[%dA" % rows).encode() + b"\x1b7\x1b[?25l")
    start = time.monotonic()
    last = -1
    shown = 0
    blocked = 0.0
    try:
        while args.frames == 0 or shown < args.frames:
            tick = int((time.monotonic() - start) * fps)
            if tick == last:
                time.sleep(max(0.0, (last + 1) / fps - (time.monotonic() - start)))
                continue
            last = tick                     # a slow terminal skips ticks instead of slowing the motion
            tw = time.monotonic()
            # ?2026: synchronized output (no tearing where supported, ignored elsewhere)
            out.write(b"\x1b[?2026h\x1b8" + clear + b"\x1b8" + sixels[tick % n] + b"\x1b[?2026l")
            out.flush()
            blocked += time.monotonic() - tw
            shown += 1
    except KeyboardInterrupt:
        pass
    finally:
        out.write(b"\x1b[?2026l\x1b8" + ("\x1b[%dB" % rows).encode() + b"\x1b[?25h\n")
        out.flush()
        if args.debug and shown:
            el = time.monotonic() - start
            print("played %d frames in %.1fs = %.1f fps (target %.1f); terminal took %.0f ms/frame to accept data" %
                  (shown, el, shown / el, fps, blocked / shown * 1000), file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(
        description="BIDeT3D - 3D WordArt for SIXEL terminals. Text comes from the "
                    "arguments, or stdin. (After banner, FIGlet, TOIlet and BIDeT.)")
    ap.add_argument("-b", "--background", default="transparent",
                    help="background colour; the default asks the terminal for its own, and if it will not say "
                         "uses a transparent background")
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
    ap.add_argument("--fps", type=float, default=10.0, help="frames per second; also sets the loop length (default 10)")
    ap.add_argument("--frames", type=int, default=0, help="stop after showing N frames (default: until Ctrl-C)")
    ap.add_argument("--ss", type=int, help="supersampling factor (default 2, 1 when animating)")
    ap.add_argument("--colors", type=int, help="SIXEL palette size (default 256; fewer = smaller frames, more banding)")
    ap.add_argument("--png", metavar="FILE", help="write a PNG instead of printing SIXEL")
    ap.add_argument("--texture-dir", help="directory with css3wordart's Texture-*.png (see README)")
    ap.add_argument("--max-width", type=int, metavar="PX",
                    help="cap the image width; smaller = faster animation prep and less data to the terminal")
    ap.add_argument("--dither", action="store_true",
                    help="Floyd-Steinberg dithering of still pictures (default off: the palette is built for "
                         "the picture, and dithering only adds speckle)")
    ap.add_argument("--transparent", action="store_true",
                    help="leave the background unpainted so the terminal shows its own (animations erase the "
                         "picture area before each frame); also the automatic fallback when the terminal "
                         "won't report its colour")
    ap.add_argument("--force", action="store_true",
                    help="print SIXEL even if the terminal does not report support (or set LSIX_FORCE_SIXEL_SUPPORT)")
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
    if args.colors is None:
        args.colors = 256       # animations share one palette across frames; 128 showed contour banding
    args._fill = ("solid", "#%02x%02x%02x" % parse_color(args.colour)) if args.colour else None

    global _verbose
    _verbose = args.debug
    # terminal + background
    cols, rows, cw, ch = term_geometry(args)
    max_w = cols * cw * 0.98
    if "xterm" in os.environ.get("TERM", "") and max_w > 1000:
        max_w = 1000          # xterm cannot show SIXEL wider than 1000px
    if args.max_width:
        max_w = min(max_w, args.max_width)
    max_h = max(1, (rows - 2)) * ch
    sixel_ok, term_bg = ((None, None) if args.png else
                         query_terminal(want_bg=args.background == "transparent", debug=args.debug))
    if sixel_ok is False and not (args.force or os.environ.get("LSIX_FORCE_SIXEL_SUPPORT")):
        sys.exit("bidet3d: Sixel not supported: your terminal does not report having sixel graphics "
                 "support.\nTry mintty, xterm -ti vt340, mlterm, Windows Terminal or WezTerm "
                 "(see TERMINAL-SUPPORT-LIST.txt), or use --force / --png.")
    # Background: an explicit -b wins; otherwise the colour the terminal reported.  If it
    # would not say (Windows Terminal does not answer OSC 11) the picture gets a
    # transparent background, so the terminal shows its own colour.  An animation then
    # erases the picture area before every frame, or the old frame would show through.
    transparent = False
    if args.background == "transparent":
        if term_bg:
            bg = term_bg
        elif args.png:
            bg = (0, 0, 0)
        else:
            transparent = True
    else:
        bg = parse_color(args.background)
    if args.transparent:
        transparent = True
    if transparent:
        # Rendered against mid-grey so anti-aliased edges look right on light and dark
        # terminals alike; below the 0.5 luminance cut-off, so "ink" presets use white.
        bg = (127, 127, 127)       # only steers the "ink" choice; the picture itself keeps real alpha
        if args.debug:
            print("background: transparent sixel", file=sys.stderr)
    args.bg = bg
    tex_dir = args.texture_dir

    t_start = time.time()
    if args.gallery:
        if not args.text:
            args.text = ["BIDeT3D"]      # a gallery should not sit waiting on stdin
        out = sys.stdout.buffer
        for name in PRESET_ORDER:
            print(name)
            p, L = make_scene(args, name, tex_dir, max_w, max_h / 3, px=args.size or 56, ss=args.ss)
            img = finish(render(L, p, pick_view(p, args), args.perspective, None if transparent else bg, args),
                         args.ss, max_w, max_h / 2)
            emit(out, to_sixel(sixel_ready(img, bg, args.colors, dither=args.dither, transparent=transparent), args.colors, args.debug))
            print()
        return

    p, L = make_scene(args, args.preset, tex_dir, max_w, max_h)
    view = pick_view(p, args)
    if args.debug:
        print("preset=%s px=%d layer=%dx%d depth=%.0f view=%s build=%.2fs" %
              (args.preset, L.px, L.w, L.h, L.depth, view, time.time() - t_start), file=sys.stderr)

    if animate and not args.png:
        do_spin(args, p, L, view, bg, max_w, max_h, cw, ch, transparent)
        return

    t1 = time.time()
    img = finish(render(L, p, view, args.perspective, None if transparent else bg, args), args.ss, max_w, max_h)
    if args.debug:
        print("render=%.2fs final=%dx%d" % (time.time() - t1, img.width, img.height), file=sys.stderr)
    if args.png:
        img.save(args.png)
        return
    emit(sys.stdout.buffer, to_sixel(sixel_ready(img, bg, args.colors, dither=args.dither, transparent=transparent), args.colors, args.debug))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
