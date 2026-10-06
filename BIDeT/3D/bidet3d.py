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
import colorsys
import copy
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

# Pillow < 9.1 (e.g. Ubuntu 20.04's 7.0) has no Image.Quantize / Image.Dither enums
_MEDIANCUT = getattr(getattr(Image, "Quantize", Image), "MEDIANCUT")
_DITHER_NONE = getattr(Image, "Dither", Image).NONE
_DITHER_FS = getattr(Image, "Dither", Image).FLOYDSTEINBERG


def _rng(seed):
    """Seeded generator with .random() and .choice(); default_rng needs numpy >= 1.17."""
    if hasattr(np.random, "default_rng"):
        return np.random.default_rng(seed)
    return np.random.RandomState(seed)

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
# BIDeT (2020) was flat: one colour, no depth.  Used by --time-machine; not listed.
PRESETS["_bidet"] = dict(_DEFAULTS, fill=("solid", "#6495ed"), depth=0.0, view=(0.0, 0.0, 0.0), bevel=0.0)
DEFAULT_VIEW = (-20.0, 8.0, 0.0)
MAX_LOOP_FRAMES = 120     # longest pre-rendered animation loop
SIDE_LEVELS = 48          # distinct extrusion shades (cached per level)
ART_LINE = 0.9            # default line spacing for ASCII art, so | and \ strokes meet between rows
RENDER_THREADS = 1       # threads warping slices in render(); main() raises it for single pictures
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
    ("mono", False): ["courbd.ttf", "Courier New Bold.ttf", "LiberationMono-Bold.ttf", "DejaVuSansMono-Bold.ttf",
                      "cour.ttf", "LiberationMono-Regular.ttf", "DejaVuSansMono.ttf"],
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
def _advance(font, s):
    """Advance width of s; FreeTypeFont.getlength() only exists in Pillow >= 8."""
    try:
        return font.getlength(s)
    except AttributeError:
        return font.getsize(s)[0]


def text_width(font, s, spacing):
    if spacing == 0:
        return _advance(font, s)
    return sum(_advance(font, ch) + spacing for ch in s) - spacing if s else 0


def draw_mask(lines, font, spacing, line_mul, block=False):
    """block=True keeps lines aligned to each other (ASCII art, -p); otherwise
    each line is centred on its own (re-wrapped WordArt text)."""
    ascent, descent = font.getmetrics()
    lh = int((ascent + descent) * line_mul)
    widths = [text_width(font, ln, spacing) for ln in lines]
    pad = int(ascent * 0.5) + 4
    W = int(max(widths)) + 2 * pad
    H = lh * len(lines) + 2 * pad
    im = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(im)
    for i, ln in enumerate(lines):
        x = (W - max(widths)) / 2.0 if block else (W - widths[i]) / 2.0
        y = pad + i * lh
        if spacing == 0:
            d.text((x, y), ln, font=font, fill=255)
        else:
            for ch in ln:
                d.text((x, y), ch, font=font, fill=255)
                x += _advance(font, ch) + spacing
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
    padded = np.pad(u8, r, mode="constant")
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
          os.path.join(here, "..", "share", "BIDeT3D", "textures"),      # <prefix>/bin/bidet3d
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
    rng = _rng(zlib_seed(name))
    rand = rng.random if hasattr(rng, "random") else rng.random_sample
    n = rand((h // 4 + 2, w // 4 + 2)).astype(np.float32)
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
    art = bool(args.art)
    path = find_font("mono" if art else p["font"], False if art else p["italic"], args.font)
    font = load_font(path, sz)
    if args.debug:
        print("font: %s" % path, file=sys.stderr)
    if args.line is not None:
        line_mul = args.line
    else:
        line_mul = ART_LINE if art else (0.8 if p["stacked"] else 1.0)
    mask_im = draw_mask(lines, font, 0.0 if art else p["spacing"] * sz, line_mul,
                         block=args.preserve)
    m = np.asarray(mask_im, np.float32) / 255.0
    shape = args.shape or p["shape"]
    if shape and shape != "plain":
        m = SHAPES[shape](m)
    pad = int(0.16 * sz) + 2
    m = np.pad(m, pad, mode="constant")
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

    jobs = []
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
        jobs.append((img, x0, y0, x1, y1, tuple(co)))

    def warp(j):
        # rasterize only the slice's own bounding box, not the whole canvas
        img, x0, y0, x1, y1, co = j
        return img.transform((x1 - x0, y1 - y0), Image.PERSPECTIVE, co, Image.BILINEAR)

    if RENDER_THREADS > 1 and len(jobs) > 3:
        # Pillow drops the GIL inside transform(), so the slices warp in parallel (a Pi has 4
        # cores); they are still composited farthest-first, and only a few wait in memory.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(RENDER_THREADS) as ex:
            window = RENDER_THREADS * 2
            pending = [ex.submit(warp, j) for j in jobs[:window]]
            for i, j in enumerate(jobs):
                canvas.alpha_composite(pending[i].result(), (j[1], j[2]))
                pending[i] = None
                if i + window < len(jobs):
                    pending.append(ex.submit(warp, jobs[i + window]))
    else:
        for j in jobs:
            canvas.alpha_composite(warp(j), (j[1], j[2]))
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
    return cols, rows, cw, ch          # cw, ch None when the terminal cannot say (ssh, Cygwin ptys)


def query_terminal(want_bg=True, want_cell=False, timeout=0.25, da_timeout=1.0, debug=False):
    """Ask the terminal up to three things in one raw-mode session (POSIX tty only):
    does it report SIXEL (DA1 attribute 4, like BIDeT's test-sixel), what is its
    background colour (OSC 11), and how big is a character cell in pixels (CSI 16 t; the
    tty's own pixel size is empty over ssh).  Returns (sixel, bg, cell): sixel is True/False,
    or None when we cannot ask or it did not answer; bg is an (r, g, b) tuple or None;
    cell is (width, height) or None."""
    if os.name != "posix" or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None, None, None
    if os.environ.get("TERM", "").startswith("yaft"):
        return True, (0, 0, 0), None      # yaft cannot answer DA1 (as in test-sixel.sh)
    try:
        import select, termios, tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
    except Exception:
        return None, None, None

    def ask(seq, done, to):
        sys.stdout.write(seq)
        sys.stdout.flush()
        buf = ""
        while select.select([fd], [], [], to)[0]:
            buf += os.read(fd, 64).decode("latin1")
            if done(buf):
                break
        return buf

    sixel = bg = cell = None
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
        if want_cell:
            buf = ask("\x1b[16t", lambda b: b.endswith("t"), timeout)
            if debug:
                print("terminal: cell size reply %r" % buf, file=sys.stderr)
            m = re.search(r"\x1b\[6;(\d+);(\d+)t", buf)
            if m and int(m.group(1)) > 0 and int(m.group(2)) > 0:
                cell = (float(m.group(2)), float(m.group(1)))        # reply is height;width
    except Exception:
        pass
    finally:
        try:
            termios.tcflush(fd, termios.TCIFLUSH)      # drop any reply that arrived too late
        except Exception:
            pass
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return sixel, bg, cell


_backend = None


def _keyed_header(six, key):
    """P2=1 in the DCS header: unpainted pixels stay as they are (transparent) rather than
    being filled with a background colour the terminal may choose differently."""
    if key is not None and six.startswith(b"\x1bPq"):
        return b"\x1bP0;1;q" + six[3:]
    return six


def encode_keyed(img, key):
    """SIXEL for a P-mode image straight from numpy, leaving palette index `key` unpainted
    (transparent).  img2sixel cannot be trusted with this: 1.5.0 ignored the PNG transparent
    index for some pictures and 1.8.2 (Raspberry Pi OS) for all of them, and either may also
    re-quantize or reorder our exact palette.  Colours are written at SIXEL's 1% resolution."""
    idx = np.asarray(img, np.uint8)
    h, w = idx.shape
    if h % 6:
        idx = np.vstack([idx, np.full((6 - h % 6, w), key, np.uint8)])
    pal = img.getpalette()
    out = [b"\x1bP0;1;q", b'"1;1;%d;%d' % (w, h)]
    for c in np.unique(idx).tolist():            # python ints: 3 * np.uint8 would wrap
        if c != key:
            rgb = tuple(int(round(v * 100 / 255.0)) for v in pal[3 * c:3 * c + 3])
            out.append(b"#%d;2;%d;%d;%d" % ((int(c),) + rgb))
    weights = (1 << np.arange(6)).astype(np.uint8)[:, None]
    for top in range(0, idx.shape[0], 6):
        band = idx[top:top + 6]
        strokes = []
        for c in np.unique(band).tolist():
            if c == key:
                continue
            v = ((band == c) * weights).sum(0).astype(np.uint8) + 63        # one sixel char per column
            change = np.empty(w, bool)
            change[0] = True
            np.not_equal(v[1:], v[:-1], out=change[1:])
            starts = np.flatnonzero(change)
            lens = np.empty_like(starts)
            lens[:-1] = starts[1:] - starts[:-1]
            lens[-1] = w - starts[-1]
            chars = v[starts]
            if chars[-1] == 63:                                              # trailing blanks need no strokes
                chars, lens = chars[:-1], lens[:-1]
            runs = [b"!%d%c" % (n, ch) if n > 3 else bytes([ch]) * n for ch, n in zip(chars.tolist(), lens.tolist())]
            strokes.append(b"#%d" % c + b"".join(runs))
        out.append(b"$".join(strokes) + b"-")
    out.append(b"\x1b\\")
    return b"".join(out)


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
    if key is not None:
        return encode_keyed(img, key)
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


def looks_like_art(raw):
    """Guess whether piped text is ASCII art (cowsay, figlet, banner, boxes) rather than prose:
    several lines, and either mostly punctuation or ragged runs of interior spaces."""
    rows = [ln.rstrip() for ln in raw if ln.strip()]
    if len(rows) < 3:
        return False
    ink = [c for ln in rows for c in ln if not c.isspace()]
    symbols = sum(1 for c in ink if not c.isalnum()) / float(len(ink))
    gappy = sum(1 for ln in rows if "   " in ln.strip())
    return symbols >= 0.3 or gappy >= 2 and gappy * 3 >= len(rows)


def get_lines(args, preset):
    from_stdin = not args.text or args.text == ["-"]
    if from_stdin:
        raw = sys.stdin.read().splitlines() if not sys.stdin.isatty() else []
    else:
        raw = args.text
    if not raw:
        raw = ["BIDeT3D"]
    if args.art is None:
        args.art = from_stdin and looks_like_art(raw)
        if args.art and args.debug:
            print("art: detected ASCII art (use --no-art to wrap as prose)", file=sys.stderr)
    if args.art:
        args.preserve = True
        return [l.expandtabs(8) for ln in raw for l in ln.split("\n")]
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
            px = px[_rng(0).choice(len(px), 50000, replace=False)]
        parts.append(px)
    px = np.concatenate(parts)
    pal = [0, 0, 0]
    if len(px):
        q = _quantize_median(Image.fromarray(px.reshape(1, -1, 3)), max(1, ncolors - 1))
        used = max(i for _n, i in q.getcolors()) + 1
        pal = list(q.getpalette()[:3 * used])
    pimg = Image.new("P", (1, 1))
    # exactly the entries we use: a PNG palette padded past the requested colour count
    # makes img2sixel re-quantize it (and average the background again)
    pimg.putpalette(pal)
    return pimg, len(pal) // 3


def _quantize_median(img, ncolors):
    try:
        return img.quantize(ncolors, method=_MEDIANCUT, dither=_DITHER_NONE)
    except TypeError:       # Pillow < 7: no dither keyword (median cut never dithers)
        return img.quantize(ncolors, method=_MEDIANCUT)


def _quantize_palette(img, pimg, dither, n):
    """img (RGB) onto the first n entries of palette image pimg, with or without
    Floyd-Steinberg dither."""
    try:
        return img.quantize(palette=pimg, dither=_DITHER_FS if dither else _DITHER_NONE)
    except TypeError:       # Pillow < 7: no dither keyword, palette mapping always dithers
        if dither:
            return img.quantize(palette=pimg)
    pal = np.array(pimg.getpalette()[:3 * n], np.float32).reshape(-1, 3)
    rgb = np.asarray(img.convert("RGB"), np.uint32).reshape(-1, 3)
    # nearest palette entry per *distinct* colour (flat backgrounds and anti-aliasing repeat a
    # lot), with |c-p|^2 = |c|^2 - 2c.p + |p|^2 as one matrix product: ~20x faster on a Pi
    keys, inv = np.unique((rgb[:, 0] << 16) | (rgb[:, 1] << 8) | rgb[:, 2], return_inverse=True)
    uc = np.stack([keys >> 16, (keys >> 8) & 255, keys & 255], 1).astype(np.float32)
    half = (pal ** 2).sum(1) * 0.5
    near = np.empty(len(uc), np.uint8)
    for i in range(0, len(uc), 8192):
        near[i:i + 8192] = (uc[i:i + 8192].dot(pal.T) - half).argmax(1)
    idx = near[inv.reshape(-1)]
    out = Image.frombytes("P", img.size, idx.tobytes())
    out.putpalette(pimg.getpalette()[:3 * n])
    return out


def _unused_colour(pal, bg):
    """bg, nudged until it matches no entry of the flat RGB list pal."""
    used = set(zip(pal[0::3], pal[1::3], pal[2::3]))
    c = list(bg)
    while tuple(c) in used:
        c[0] = (c[0] + 1) % 256
    return c


def quantize_exact(img, pimg, bg_index, bg, dither, mask=None, keyed=False):
    """Map img onto the palette; every background pixel becomes exactly index bg_index.
    keyed: the background is marked transparent, and moved to palette index 0 with a colour
    that differs from every real entry.  img2sixel only honours the PNG transparent index
    reliably when it is 0 (a grey picture such as chrome, with the key last, came out with
    the background painted black), and identical palette colours get folded together."""
    pal = list(pimg.getpalette()[:3 * bg_index])
    a = np.array(img.convert("RGB"))
    m = _bg_mask(a, bg) if mask is None else mask
    # an exact palette colour has zero quantization error, so no dither error leaks from
    # the background into the pixels beside it
    a[m] = pal[:3]
    q = _quantize_palette(Image.fromarray(a), pimg, dither, bg_index)
    idx = np.array(q)
    idx[m] = bg_index
    if keyed:
        idx = np.where(m, 0, idx + 1).astype(np.uint8)
        out = Image.frombytes("P", q.size, idx.tobytes())
        out.putpalette(_unused_colour(pal, bg) + pal)
        out.info["transparency"] = 0
        return out
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
    return quantize_exact(img, pimg, bi, bg, dither, mask, keyed=transparent)


def render_loop(args, p, L, view, bg, max_w, max_h, transparent=False):
    """Pre-render one seamless loop and encode it once.  Returns what play_loop needs,
    or None if interrupted.  Rendering/encoding per frame while playing made the frame
    rate (and the angle jumps) depend on how slow the machine was."""
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
        qs = [quantize_exact(im, pimg, bi, bg, False, masks[k] if masks else None, keyed=transparent)
              for k, im in enumerate(imgs)]
        busy(0, "encoding SIXEL")
        usixels = to_sixel_many(qs, args.colors, args.debug)
        sixels = [usixels[j] for j in order]
    except KeyboardInterrupt:
        busy_done()
        return None
    busy_done()
    if args.debug:
        print("loop: %d frames (%d distinct), %dx%d; render %.1fs + encode %.1fs; avg %.0f KB/frame" %
              (n, len(uviews), imgs[0].width, imgs[0].height, t_render, time.time() - t0 - t_render,
               sum(map(len, sixels)) / n / 1024.0), file=sys.stderr)
    return dict(sixels=sixels, n=n, fps=fps, w=imgs[0].width, h=imgs[0].height)


def play_loop(args, loop, cell_w, cell_h, transparent=False):
    """Replay the cached SIXEL frames on a steady clock until Ctrl-C (or --frames)."""
    out = sys.stdout.buffer
    sixels, n, fps = loop["sixels"], loop["n"], loop["fps"]
    rows = int(math.ceil(loop["h"] / cell_h)) + 1
    clear = b""
    if transparent:
        cols = int(math.ceil(loop["w"] / cell_w)) + 1
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


def do_spin(args, p, L, view, bg, max_w, max_h, cell_w, cell_h, transparent=False):
    loop = render_loop(args, p, L, view, bg, max_w, max_h, transparent)
    if loop:
        play_loop(args, loop, cell_w, cell_h, transparent)


# --------------------------------------------------------------------------
# --time-machine: banner -> FIGlet -> TOIlet -> BIDeT -> BIDeT3D
# --------------------------------------------------------------------------
TM_STAGES = [
    (1983, "banner(1)", "AT&T, UNIX System V: big text out of # characters"),
    (1991, "FIGlet", "Chappell and Chai: numerous fonts"),
    (2004, "TOIlet", "Sam Hocevar: more fonts, colour and filters"),
    (2020, "BIDeT", "Chris Pollitt: SIXEL graphics and real fonts"),
    (2026, "BIDeT3D", "the third dimension"),
]
_QUAD = " .,_')//`\\(L\"7[#"      # figlet-ish character for each 2x2 block of ink: tl*8+tr*4+bl*2+br


def _text_mask(line):
    return draw_mask([line], load_font(find_font("arial", False), 160), 0, 1.0)


def _grid(mask, gw, gh):
    return np.asarray(mask.resize((max(1, gw), max(1, gh)), Image.BOX), np.float32) / 255.0


def _tool(argv, line=None, stdin=False):
    """Output of a real banner/figlet/toilet, or None if it is missing or fails."""
    if os.environ.get("BIDET3D_EMULATE") or not shutil.which(argv[0]):
        return None
    try:
        r = subprocess.run(argv + ([] if stdin else [line]), input=(line + "\n").encode("utf-8") if stdin else None,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    out = r.stdout.decode("utf-8", "replace").rstrip("\n")
    return out if r.returncode == 0 and out.strip() else None


def _emulate_banner(line, cols):
    mask = _text_mask(line)
    a = mask.width / float(mask.height)
    rows = 7
    gw = int(round(a * rows * 1.5))
    if gw > cols - 4:
        gw = cols - 4
        rows = max(3, int(gw / (a * 1.5)))
    g = _grid(mask, gw, rows) > 0.35
    return "\n".join("".join("#" if v else " " for v in row) for row in g)


def _emulate_figlet(line, cols):
    mask = _text_mask(line)
    a = mask.width / float(mask.height)
    rows = 6
    gw = min(cols - 4, int(round(a * rows * 1.6)))
    g = _grid(mask, gw * 2, rows * 2) > 0.4
    out = []
    for y in range(rows):
        row = ""
        for x in range(gw):
            t = y * 2
            row += _QUAD[g[t, 2 * x] * 8 + g[t, 2 * x + 1] * 4 + g[t + 1, 2 * x] * 2 + g[t + 1, 2 * x + 1]]
        out.append(row)
    return "\n".join(out)


def _emulate_toilet(line, cols):
    mask = _text_mask(line)
    a = mask.width / float(mask.height)
    gh = 8
    gw = int(round(a * gh))
    if gw > cols - 4:
        gw = cols - 4
        gh = max(2, int(gw / a) // 2 * 2)
    g = _grid(mask, gw, gh) > 0.4                    # half-blocks: every pixel is square
    out = []
    for y in range(0, gh, 2):
        row = ""
        for x in range(gw):
            top, bot = g[y, x], g[y + 1, x]
            if not (top or bot):
                row += " "
                continue
            r, gr, b = (int(255 * c) for c in colorsys.hsv_to_rgb(0.85 * x / gw, 0.8, 1.0))
            row += "\x1b[38;2;%d;%d;%dm%s" % (r, gr, b, "\u2588" if top and bot else "\u2580" if top else "\u2584")
        out.append(row + "\x1b[0m")
    return "\n".join(out)


def tm_text(stage, lines, cols):
    """The text-mode stages: the real program when installed, else an imitation."""
    blocks = []
    for ln in lines:
        if not ln.strip():
            continue
        if stage == 0:
            txt = None
            if not ln.startswith("-"):
                txt = _tool(["banner", "-w", str(cols - 4)], ln)
                if txt and max(len(r) for r in txt.split("\n")) > cols - 2:
                    txt = None
            txt = txt or _emulate_banner(ln, cols)
        elif stage == 1:
            txt = _tool(["figlet", "-w", str(cols - 4)], ln, stdin=True) or _emulate_figlet(ln, cols)
        else:
            txt = (_tool(["toilet", "-f", "future", "-F", "gay", "-w", str(cols - 4)], ln, stdin=True)
                   or _tool(["toilet", "-F", "gay", "-w", str(cols - 4)], ln, stdin=True)
                   or _emulate_toilet(ln, cols))
        blocks.append(txt)
    return "\n\n".join(blocks)


def tm_sleep(sec):
    time.sleep(max(0.0, sec))


def time_machine(args, bg, transparent, max_w, max_h, cw, ch, tex_dir):
    """Cycle through the history of big terminal text with the user's text."""
    out = sys.stdout.buffer
    cols, rows = shutil.get_terminal_size((80, 24))
    top = 3                                          # caption rows
    max_h = max(4 * ch, max_h - top * ch)
    lines = get_lines(args, _DEFAULTS)               # reads stdin once; every stage then reuses it
    args.text = list(lines)
    if args.sway is None:
        args.spin = True

    # the slow part first: the 3D loop is rendered before the show starts
    p, L = make_scene(args, args.preset, tex_dir, max_w, max_h)
    view = pick_view(p, args)
    sys.stderr.write("Charging the flux capacitor (%s)...\n" % args.preset)
    loop = render_loop(args, p, L, view, bg, max_w, max_h, transparent)
    if loop is None:
        return
    # BIDeT was flat: plain, no depth, camera straight on
    flat = copy.copy(args)
    flat.shape, flat.depth, flat.ss = None, 0.0, 2
    pf, Lf = make_scene(flat, "_bidet", tex_dir, max_w, max_h, ss=2)
    img = finish(render(Lf, pf, (0.0, 0.0, 0.0), args.perspective, None if transparent else bg, flat), 2, max_w, max_h)
    flat_sixel = to_sixel(sixel_ready(img, bg, args.colors, dither=args.dither, transparent=transparent),
                          args.colors, args.debug)

    def caption(i):
        year, name, note = TM_STAGES[i]
        out.write(b"\x1b[2J\x1b[H\x1b[1m  %d  %s\x1b[0m  \x1b[2m%s\x1b[0m\n\n" % (year, name.encode(), note.encode()))
        out.flush()

    out.write(b"\x1b[?1049h\x1b[?25l")                # alternate screen: leave the user's terminal as it was
    try:
        for i in range(4):
            if i:
                # the year ticker: wind forward to the next era
                y0, y1 = TM_STAGES[i - 1][0], TM_STAGES[i][0]
                steps = 24
                for k in range(steps + 1):
                    t = k / float(steps)
                    yr = int(round(y0 + (y1 - y0) * (1 - (1 - t) ** 2)))
                    out.write(b"\r\x1b[K  >>> %d <<<" % yr)
                    out.flush()
                    tm_sleep(min(0.9, args.stage_time) / steps)
            caption(i)
            if i < 3:
                out.write(("\n".join("  " + r for r in tm_text(i, lines, cols).split("\n")) + "\n").encode("utf-8"))
            else:
                out.write(b"\x1b7")
                emit(out, flat_sixel)
                out.write(b"\n")
            out.flush()
            tm_sleep(args.stage_time)
        y0, y1 = TM_STAGES[3][0], TM_STAGES[4][0]
        for k in range(25):
            t = k / 24.0
            out.write(b"\r\x1b[K  >>> %d <<<" % int(round(y0 + (y1 - y0) * (1 - (1 - t) ** 2))))
            out.flush()
            tm_sleep(min(0.9, args.stage_time) / 24)
        caption(4)
        play_loop(args, loop, cw, ch, transparent)
    except KeyboardInterrupt:
        pass
    finally:
        out.write(b"\x1b[?25h\x1b[?1049l")
        out.flush()


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
    ap.add_argument("-a", "--art", dest="art", action="store_true", default=None,
                    help="input is ASCII art: keep lines aligned, use a monospace font, no letter-spacing, "
                         "tighter lines (implies -p).  Piped multi-line art is detected automatically")
    ap.add_argument("--no-art", dest="art", action="store_false", help="never auto-detect ASCII art")
    ap.add_argument("-l", "--line", type=float, default=None,
                    help="line spacing (default 1.0; %s for ASCII art)" % ART_LINE)
    ap.add_argument("-p", "--preserve", action="store_true", help="preserve newlines instead of re-wrapping")
    ap.add_argument("-s", "--size", type=int, default=0, help="font size in pixels (default: fit the terminal)")
    ap.add_argument("-w", "--width", type=int, default=20, help="wrap width in characters (default 20)")
    ap.add_argument("-v", "--version", action="store_true")
    ap.add_argument("-P", "--preset", default=DEFAULT_PRESET,
                    help="WordArt style, or 'random' (default %s); see --list-presets" % DEFAULT_PRESET)
    ap.add_argument("--list-presets", action="store_true")
    ap.add_argument("--gallery", action="store_true", help="show every preset with the given text")
    ap.add_argument("--time-machine", action="store_true",
                    help="animate the history of terminal text: banner, FIGlet, TOIlet, BIDeT, BIDeT3D")
    ap.add_argument("--stage-time", type=float, default=3.0, metavar="SEC",
                    help="seconds to show each earlier era with --time-machine (default 3)")
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
    animate = args.spin or args.sway is not None or args.time_machine
    if args.time_machine and (args.png or args.gallery):
        sys.exit("bidet3d: --time-machine cannot be combined with --png or --gallery")
    if args.ss is None:
        args.ss = 1 if animate else 2
    if args.colors is None:
        args.colors = 256       # animations share one palette across frames; 128 showed contour banding
    args._fill = ("solid", "#%02x%02x%02x" % parse_color(args.colour)) if args.colour else None

    global _verbose
    _verbose = args.debug
    # terminal + background
    cols, rows, cw, ch = term_geometry(args)
    sixel_ok, term_bg, cell = ((None, None, None) if args.png else
                               query_terminal(want_bg=args.background == "transparent", want_cell=not cw,
                                              debug=args.debug))
    if not cw:
        cw, ch = cell or (10.0, 20.0)
        if args.debug:
            print("cell size: %gx%g (%s)" % (cw, ch, "from the terminal" if cell else "guessed; try --cell WxH"),
                  file=sys.stderr)
    max_w = cols * cw * 0.98
    if "xterm" in os.environ.get("TERM", "") and max_w > 1000:
        max_w = 1000          # xterm cannot show SIXEL wider than 1000px
    if args.max_width:
        max_w = min(max_w, args.max_width)
    max_h = max(1, (rows - 2)) * ch
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

    if args.time_machine:
        time_machine(args, bg, transparent, max_w, max_h, cw, ch, tex_dir)
        return

    p, L = make_scene(args, args.preset, tex_dir, max_w, max_h)
    view = pick_view(p, args)
    if args.debug:
        print("preset=%s px=%d layer=%dx%d depth=%.0f view=%s build=%.2fs" %
              (args.preset, L.px, L.w, L.h, L.depth, view, time.time() - t_start), file=sys.stderr)

    if animate and not args.png:
        do_spin(args, p, L, view, bg, max_w, max_h, cw, ch, transparent)
        return

    global RENDER_THREADS
    RENDER_THREADS = min(4, os.cpu_count() or 1)
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
