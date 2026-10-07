#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
unascii - turn ASCII / ANSI / Unicode terminal art back into a line drawing.

ASCII art takes a picture and turns it into printable characters; this goes the other
way.  The result is a clean black-on-white (or any colour) PNG, or SIXEL graphics for
the terminal, and it feeds bidet3d:   unascii cow.txt -o - | bidet3d

Two reconstruction methods, picked automatically per input (-m to force one):

  line   hand-drawn line art (cowsay, figlet, boxes: / \\ | _ - ( ) ^ ' . ,):
         the characters are read as pen strokes.  Stroke ends that meet are joined
         into continuous lines and gentle corners are rounded, so  _.-'''-._  becomes
         one smooth curve instead of a row of separate marks.
  tone   picture-converted art (jp2a, chafa, caca; ramps like  .:-=+*#%@, half blocks,
         braille, coloured ANSI): the characters are read as ink density.  The picture
         they were squinted from is recovered, and outlines are traced on it.
  mix    both: strokes for the line characters, outlines for dense fill characters.

Written for old libraries as well as new: Python 3.7+, Pillow 5.4+, numpy 1.16+.
"""

import argparse
import io
import math
import os
import re
import sys
import unicodedata

import numpy as np
from PIL import Image, ImageDraw, ImageFont

VERSION = "0.1"


# --------------------------------------------------------------------------
# Reading: text, ANSI escapes (colours, cursor movement), SAUCE, CP437
# --------------------------------------------------------------------------
_ANSI16 = [(0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238), (205, 0, 205),
           (0, 205, 205), (229, 229, 229), (127, 127, 127), (255, 0, 0), (0, 255, 0),
           (255, 255, 0), (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255)]


def xterm_color(n):
    """Colour of palette entry n (0-255) as an (r, g, b) tuple."""
    if n < 16:
        return _ANSI16[n]
    if n < 232:
        n -= 16
        lv = (0, 95, 135, 175, 215, 255)
        return (lv[n // 36], lv[(n // 6) % 6], lv[n % 6])
    g = 8 + 10 * (n - 232)
    return (g, g, g)


def decode(data, encoding=None):
    """bytes -> str.  UTF-8 if it is, else CP437 (the old DOS .ANS art).  A SAUCE record
    and the Ctrl-Z in front of it are dropped."""
    if isinstance(data, str):
        return data
    i = data.rfind(b"SAUCE00")
    if i > 0 and data[i - 1:i] == b"\x1a":
        data = data[:i - 1]
    data = data.rstrip(b"\x1a")
    if encoding:
        return data.decode(encoding, "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp437", "replace")


class Grid(object):
    """The art as a rectangle of cells: ch[y][x] is one character, fg/bg[y][x] its colours
    ((r, g, b), 'fgdef' / 'bgdef' for reverse video, or None for the terminal default)."""
    def __init__(self, ch, fg, bg):
        self.ch, self.fg, self.bg = ch, fg, bg
        self.rows = len(ch)
        self.cols = len(ch[0]) if ch else 0

    def has_color(self):
        return any(c is not None for row in self.fg + self.bg for c in row)


_CSI = re.compile(r"\x1b\[([0-9;:?<=>]*)([ -/]*[@-~])")


def parse(text, cols=0, tabs=8):
    """Interpret text the way a terminal would (enough of it for art): SGR colours, cursor
    movement, erase, wrap at `cols` (0 = never).  Returns a Grid."""
    cells = {}
    x = y = 0
    saved = (0, 0)
    fg = bg = None
    fg_idx = None
    bold = rev = False
    pos, n = 0, len(text)
    while pos < n:
        c = text[pos]
        if c == "\x1b":
            m = _CSI.match(text, pos)
            if not m:
                pos += 2
                continue
            pos = m.end()
            args, fin = m.group(1), m.group(2)
            if args[:1] in "?<=>":
                continue
            nums = [int(a) if a.isdigit() else 0 for a in args.replace(":", ";").split(";")] if args else []
            one = nums[0] if nums and nums[0] else 1
            if fin == "m":
                if not nums:
                    nums = [0]
                i = 0
                while i < len(nums):
                    v = nums[i]
                    if v == 0:
                        fg = bg = fg_idx = None
                        bold = rev = False
                    elif v == 1:
                        bold = True
                    elif v == 22:
                        bold = False
                    elif v == 7:
                        rev = True
                    elif v == 27:
                        rev = False
                    elif 30 <= v <= 37:
                        fg_idx, fg = v - 30, None
                    elif 90 <= v <= 97:
                        fg_idx, fg = v - 90 + 8, None
                    elif v == 39:
                        fg = fg_idx = None
                    elif 40 <= v <= 47:
                        bg = xterm_color(v - 40)
                    elif 100 <= v <= 107:
                        bg = xterm_color(v - 100 + 8)
                    elif v == 49:
                        bg = None
                    elif v in (38, 48):
                        col = None
                        if i + 2 < len(nums) and nums[i + 1] == 5:
                            col = xterm_color(min(255, nums[i + 2]))
                            i += 2
                        elif i + 4 < len(nums) and nums[i + 1] == 2:
                            col = tuple(min(255, k) for k in nums[i + 2:i + 5])
                            i += 4
                        if v == 38:
                            fg, fg_idx = col, None
                        else:
                            bg = col
                    i += 1
            elif fin == "A":
                y = max(0, y - one)
            elif fin == "B":
                y += one
            elif fin == "C":
                x += one
            elif fin == "D":
                x = max(0, x - one)
            elif fin in ("H", "f"):
                y = max(0, (nums[0] or 1) - 1) if nums else 0
                x = max(0, (nums[1] or 1) - 1) if len(nums) > 1 else 0
            elif fin == "G":
                x = max(0, one - 1)
            elif fin == "J" and (nums[:1] == [2] or nums[:1] == [3]):
                cells.clear()
            elif fin == "K":
                for k in [k for k in cells if k[0] == y and k[1] >= x]:
                    del cells[k]
            elif fin == "s":
                saved = (x, y)
            elif fin == "u":
                x, y = saved
            continue
        pos += 1
        if c == "\n":
            y += 1
            x = 0
        elif c == "\r":
            x = 0
        elif c == "\t":
            x = (x // tabs + 1) * tabs
        elif c == "\b":
            x = max(0, x - 1)
        elif ord(c) < 32 or c == "\x7f":
            pass
        else:
            if cols and x >= cols:
                x = 0
                y += 1
            if c in "\u00a0\u2800":
                c = " "
            f, b = fg, bg
            if f is None and fg_idx is not None:
                f = xterm_color(fg_idx + 8 if bold and fg_idx < 8 else fg_idx)
            if rev:
                f, b = (b if b is not None else "bgdef"), (f if f is not None else "fgdef")
            if c != " " or b is not None:
                cells[(y, x)] = (c, f, b)
            x += 1
    if not cells:
        return Grid([[" "]], [[None]], [[None]])
    rows = max(k[0] for k in cells) + 1
    width = max(k[1] for k in cells) + 1
    ch = [[" "] * width for _ in range(rows)]
    fgs = [[None] * width for _ in range(rows)]
    bgs = [[None] * width for _ in range(rows)]
    for (yy, xx), (c, f, b) in cells.items():
        ch[yy][xx], fgs[yy][xx], bgs[yy][xx] = c, f, b
    return Grid(ch, fgs, bgs)


# --------------------------------------------------------------------------
# What kind of character is it?
# --------------------------------------------------------------------------
STRONG = set("/\\|_()[]{}<>^'`\u00b4\"\u00af\u203e!")        # clearly pen strokes
WEAK = set("-.,:;=~+*oO0vV")                                  # strokes in line art, ramp in tone art
DENSE = set("#%@&$8\u2588\u2593\u2592\u2591")                 # fill characters
LETTERS_OK = True


def is_block(c):
    return "\u2580" <= c <= "\u259f"


def is_braille(c):
    return "\u2800" <= c <= "\u28ff"


def is_box(c):
    return "\u2500" <= c <= "\u257f"


_SHAPEY = set("oOvV0")                       # letters that are also drawing characters
_TEXTY = set(".,:;'!-?")                     # punctuation that belongs to text when it touches a word


def shade_cells(grid, chars):
    """Cells that are shading rather than letters or strokes: a run of two or more of one of
    `chars` (default X), as in the filled regions of cowsay's ghostbusters, plus any such
    character standing directly above or below one."""
    if not chars:
        return None
    base = [[c in chars for c in row] for row in grid.ch]
    run = [[base[y][x] and ((x > 0 and base[y][x - 1]) or (x + 1 < grid.cols and base[y][x + 1]))
            for x in range(grid.cols)] for y in range(grid.rows)]
    out = [row[:] for row in run]
    for y in range(grid.rows):
        for x in range(grid.cols):
            if base[y][x] and not run[y][x] and ((y > 0 and run[y - 1][x]) or (y + 1 < grid.rows and run[y + 1][x])):
                out[y][x] = True
    return out if any(any(r) for r in out) else None


def word_cells(grid, skip=None):
    """Which cells are text rather than drawing?  A run of letters/digits is a word, and is
    drawn from the font, if it holds any letter that is not also a drawing character
    (o O v V 0): 'Moo' is text, '(oo)' is eyes.  Punctuation touching a word is text too.
    Cells in `skip` (shading) do not count as letters."""
    text = [[False] * grid.cols for _ in range(grid.rows)]
    for y, row in enumerate(grid.ch):
        x = 0

        def letter(k):
            return row[k].isalnum() and not (skip and skip[y][k])
        while x < grid.cols:
            if not letter(x):
                x += 1
                continue
            e = x
            while e < grid.cols and letter(e):
                e += 1
            if any(c not in _SHAPEY for c in row[x:e]):
                for k in range(x, e):
                    text[y][k] = True
                for k in (x - 1, e):
                    if 0 <= k < grid.cols and row[k] in _TEXTY:
                        text[y][k] = True
            x = e
    return text


_SIDES = set("<>/\\|()")


def bubble_bottoms(grid):
    """The bottom border of cowsay / cowthink speech bubbles, as a set of (row, col).

        _______        a run of _ ...
       < hello >       ... with side characters (< > / \\ | ( )) beside every row ...
        -------        ... and a run of - of the same width below.

    Drawn normally, the - floats at mid-height, away from the sides.  The caller lifts these
    to the row boundary, the mirror image of where the _ sits on top, so the bubble closes."""
    found = set()
    ch = grid.ch
    for y in range(2, grid.rows):
        x = 0
        while x < grid.cols:
            if ch[y][x] != "-":
                x += 1
                continue
            e = x
            while e < grid.cols and ch[y][e] == "-":
                e += 1
            a, b = x, e - 1                                       # the run, columns a..b
            x = e
            if b - a < 2 or a == 0 or b + 1 >= grid.cols:
                continue
            if ch[y][a - 1] != " " or ch[y][b + 1] != " ":
                continue
            r = y - 1                                             # side characters, going up
            while r >= 1 and ch[r][a - 1] in _SIDES and ch[r][b + 1] in _SIDES:
                r -= 1
            if r == y - 1 or r < 0:
                continue
            top = ch[r][a:b + 1]                                  # row r must be the _ border
            if top.count("_") >= 0.8 * len(top) and ch[r][a - 1] == " " and ch[r][b + 1] == " ":
                found.update((y, k) for k in range(a, b + 1))
    return found


def classify(grid, skip=None):
    """Pick line / tone / mix for this art, with the numbers behind the choice.  Cells in
    `skip` (shading) are left out of it."""
    n = line = pix = dense = 0
    ys, xs = [], []
    for y, row in enumerate(grid.ch):
        for x, c in enumerate(row):
            if (c == " " and grid.bg[y][x] is None) or (skip and skip[y][x]):
                continue
            n += 1
            ys.append(y)
            xs.append(x)
            if c in STRONG or is_box(c):
                line += 1
            elif is_block(c) or is_braille(c) or grid.bg[y][x] is not None:
                pix += 1
            elif c in DENSE:
                dense += 1
    if not n:
        return "line", {}
    area = (max(ys) - min(ys) + 1) * (max(xs) - min(xs) + 1)
    st = {"cells": n, "fill": n / float(area), "strong": line / float(n),
          "pixel": pix / float(n), "dense": dense / float(n)}
    if st["pixel"] > 0.3:
        mode = "tone"
    elif st["strong"] >= 0.45 and st["dense"] < 0.15:
        mode = "line"
    elif st["fill"] > 0.5 and st["strong"] < 0.25:
        mode = "tone"
    elif st["dense"] + st["pixel"] > 0.1:
        mode = "mix"
    else:
        mode = "line"
    return mode, st


# --------------------------------------------------------------------------
# Fonts and glyph coverage masks
# --------------------------------------------------------------------------
FONT_DIRS = ["C:/Windows/Fonts", "/cygdrive/c/Windows/Fonts", "/mnt/c/Windows/Fonts",
             "/usr/share/fonts", "/usr/local/share/fonts", "~/.fonts", "~/.local/share/fonts",
             "/System/Library/Fonts", "/Library/Fonts", "~/Library/Fonts"]
FONT_FILES = ["DejaVuSansMono.ttf", "consola.ttf", "LiberationMono-Regular.ttf", "Menlo.ttc",
              "FreeMono.ttf", "lucon.ttf", "cour.ttf", "UbuntuMono-R.ttf", "NotoSansMono-Regular.ttf"]


def find_font(override=None):
    if override:
        if os.path.isfile(override):
            return override
        sys.exit("unascii: font '%s' not found" % override)
    found = {}
    for d in FONT_DIRS:
        d = os.path.expanduser(d)
        if os.path.isdir(d):
            for root, _dirs, files in os.walk(d):
                for f in files:
                    found.setdefault(f.lower(), os.path.join(root, f))
    for f in FONT_FILES:
        if f.lower() in found:
            return found[f.lower()]
    return None


def _advance(font, s):
    try:
        return font.getlength(s)
    except AttributeError:
        return font.getsize(s)[0]


class Glyphs(object):
    """Coverage masks (float32, ch x cw, 1 = ink) for characters, cached.  Blocks and
    braille are computed exactly; everything else is rendered from a font."""
    def __init__(self, cw, ch, font_path=None):
        self.cw, self.ch = cw, ch
        self.cache = {}
        self.font = None
        self.S = 2
        path = find_font(font_path)
        if path:
            probe = ImageFont.truetype(path, 100)
            size = max(4, int(round(cw * self.S / _advance(probe, "M") * 100)))
            self.font = ImageFont.truetype(path, size)
            asc, desc = self.font.getmetrics()
            self.box = (int(math.ceil(_advance(self.font, "M"))), asc + desc)
        self.path = path

    def mask(self, c):
        m = self.cache.get(c)
        if m is None:
            m = self._make(c)
            self.cache[c] = m
        return m

    def _make(self, c):
        cw, ch = self.cw, self.ch
        m = np.zeros((ch, cw), np.float32)
        if c == " ":
            return m
        o = ord(c)
        if is_braille(c):
            bits = o - 0x2800
            pos = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (0, 3), (1, 3)]
            for b, (cx, cy) in enumerate(pos):
                if bits & (1 << b):
                    m[cy * ch // 4:(cy + 1) * ch // 4, cx * cw // 2:(cx + 1) * cw // 2] = 1
            return m
        if is_block(c):
            h2, w2 = ch // 2, cw // 2
            if o == 0x2580:
                m[:h2] = 1
            elif 0x2581 <= o <= 0x2587:
                m[ch - int(round(ch * (o - 0x2580) / 8.0)):] = 1
            elif o == 0x2588:
                m[:] = 1
            elif 0x2589 <= o <= 0x258f:
                m[:, :int(round(cw * (0x2590 - o) / 8.0))] = 1
            elif o == 0x2590:
                m[:, w2:] = 1
            elif o in (0x2591, 0x2592, 0x2593):
                m[:] = (o - 0x2590) * 0.25
            elif o == 0x2594:
                m[:max(1, ch // 8)] = 1
            elif o == 0x2595:
                m[:, cw - max(1, cw // 8):] = 1
            else:
                quad = {0x2596: "L", 0x2597: "R", 0x2598: "l", 0x2599: "lLR", 0x259a: "lR",
                        0x259b: "lrL", 0x259c: "lrR", 0x259d: "r", 0x259e: "rL", 0x259f: "rLR"}[o]
                for q in quad:
                    ys = slice(0, h2) if q in "lr" else slice(h2, ch)
                    xs = slice(0, w2) if q in "lL" else slice(w2, cw)
                    m[ys, xs] = 1
            return m
        if self.font is None:
            return m
        W, H = self.box
        im = Image.new("L", (W, H), 0)
        ImageDraw.Draw(im).text((0, 0), c, font=self.font, fill=255)
        im = im.resize((cw, ch), Image.LANCZOS)
        return np.clip(np.asarray(im, np.float32) / 255.0, 0, 1)


# --------------------------------------------------------------------------
# Small image-processing helpers (numpy only)
# --------------------------------------------------------------------------
def _kernel(sigma):
    r = max(1, int(math.ceil(3.0 * sigma)))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / float(sigma)) ** 2)
    return (k / k.sum()).astype(np.float32), r


def blur(a, sx, sy=None):
    """Gaussian blur, separable, edge-replicating.  sigma in pixels per axis."""
    sy = sx if sy is None else sy
    a = a.astype(np.float32)
    for axis, s in ((1, sx), (0, sy)):
        if s < 0.3:
            continue
        k, r = _kernel(s)
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r, r)
        p = np.pad(a, pad, mode="edge")
        n = a.shape[axis]
        out = np.zeros_like(a)
        for i, w in enumerate(k):
            out += w * (p[:, i:i + n] if axis == 1 else p[i:i + n, :])
        a = out
    return a


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


# --------------------------------------------------------------------------
# Tone: characters as ink density -> the picture -> outlines
# --------------------------------------------------------------------------
def lum(c):
    return (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255.0


def pitch_of(grid, cw, ch):
    """Size in pixels of the smallest 'dot' this art is made of: a text cell, or half of
    one for half-blocks / quadrants, a quarter for braille."""
    k = {"cell": 0, "half": 0, "quad": 0, "braille": 0}
    for row in grid.ch:
        for c in row:
            o = ord(c)
            if is_braille(c) and o != 0x2800:
                k["braille"] += 1
            elif o in (0x2580, 0x2584, 0x258c, 0x2590):
                k["half"] += 1
            elif 0x2596 <= o <= 0x259f:
                k["quad"] += 1
            elif c != " ":
                k["cell"] += 1
    best = max(k, key=lambda a: k[a])
    return {"cell": (cw, ch), "half": (cw, ch / 2.0), "quad": (cw / 2.0, ch / 2.0),
            "braille": (cw / 2.0, ch / 4.0)}[best]


def darkness(grid, glyphs, only=None, dark=False):
    """Per-pixel 'ink' picture of the grid, float32 0..1 (1 = dark).  Characters not in
    `only` (a predicate) are left blank.  Default colours are black ink on white paper;
    explicit ANSI colours are used as they are."""
    rows, cols = grid.rows, grid.cols
    cw, ch = glyphs.cw, glyphs.ch
    uniq = {}
    idx = np.zeros((rows, cols), np.int32)
    for y in range(rows):
        for x in range(cols):
            c = grid.ch[y][x]
            if only is not None and not only(c):
                c = " "
            idx[y, x] = uniq.setdefault(c, len(uniq))
    masks = np.zeros((len(uniq), ch, cw), np.float32)
    for c, i in uniq.items():
        masks[i] = glyphs.mask(c)
    paper, ink = (0.0, 1.0) if dark else (1.0, 0.0)
    fl = np.empty((rows, cols), np.float32)
    bl = np.empty((rows, cols), np.float32)
    for y in range(rows):
        for x in range(cols):
            f, b = grid.fg[y][x], grid.bg[y][x]
            f = {"fgdef": ink, "bgdef": paper}.get(f, f) if isinstance(f, str) else f
            b = {"fgdef": ink, "bgdef": paper}.get(b, b) if isinstance(b, str) else b
            fl[y, x] = ink if f is None else (f if isinstance(f, float) else lum(f))
            bl[y, x] = paper if b is None else (b if isinstance(b, float) else lum(b))
    big = masks[idx]                                  # rows, cols, ch, cw
    big = big.transpose(0, 2, 1, 3).reshape(rows * ch, cols * cw)
    fl = np.repeat(np.repeat(fl, ch, 0), cw, 1)
    bl = np.repeat(np.repeat(bl, ch, 0), cw, 1)
    return 1.0 - (bl + (fl - bl) * big)


def autolevel(d, lo_pct=2, hi_pct=98):
    lo, hi = np.percentile(d, lo_pct), np.percentile(d, hi_pct)
    if hi - lo < 0.04:
        return np.clip(d - lo, 0, 1)
    return np.clip((d - lo) / (hi - lo), 0, 1)


def halftone_free(d, px, py):
    """Undo the halftone: average d over each dot (a cell, half a cell, a braille dot...),
    then spread the averages back out smoothly (bicubic).  The glyph shapes inside a cell
    are gone, the picture they were chosen to render remains."""
    H, W = d.shape
    ix, iy = max(1, int(round(px))), max(1, int(round(py)))
    nx, ny = W // ix, H // iy
    pooled = d[:ny * iy, :nx * ix].reshape(ny, iy, nx, ix).mean(axis=(1, 3)).astype(np.float32)
    pooled = np.pad(pooled, 1, mode="edge")
    up = Image.fromarray(pooled, "F").resize(((nx + 2) * ix, (ny + 2) * iy), Image.BICUBIC)
    up = np.asarray(up, np.float32)[iy:iy + ny * iy, ix:ix + nx * ix]
    return np.pad(up, ((0, H - ny * iy), (0, W - nx * ix)), mode="edge")


def edge_lines(d, px, py, width, smooth=0.5, scale=0.4, edge=0.12, levels=0):
    """Line drawing of the picture d (float 0..1, 1 = dark).  Strokes `width` pixels wide,
    placed at sub-pixel accuracy as zero crossings: of a difference of Gaussians (outlines
    wherever tone steps by at least `edge` per dot pitch) and of the tone itself at `levels`
    evenly spaced values (contour lines that suggest the shading)."""
    pitch = 0.5 * (px + py)
    f = autolevel(blur(halftone_free(d, px, py), smooth * px, smooth * py))
    sx, sy = scale * px, scale * py
    g1 = blur(f, sx, sy)
    g2 = blur(f, 1.6 * sx, 1.6 * sy)
    dog = g1 - g2
    gy, gx = np.gradient(g1)
    strength = np.hypot(gx, gy) * pitch                          # tone change per dot pitch
    ly, lx = np.gradient(dog)
    dist = np.abs(dog) / (np.hypot(lx, ly) + 1e-6)               # px to the zero crossing
    ink = np.clip(0.5 * width - dist + 0.5, 0.0, 1.0) * \
        np.clip((strength - 0.9 * edge) / (0.2 * edge), 0.0, 1.0)
    if levels > 0:
        gy, gx = np.gradient(blur(f, 0.5 * px, 0.5 * py))
        gm = np.hypot(gx, gy)
        grad = gm * pitch                                        # only where the shading is gentle:
        weak = np.clip((grad - 0.015) / 0.02, 0.0, 1.0) * np.clip((0.7 * edge - grad) / (0.3 * edge), 0.0, 1.0)
        for k in range(1, levels + 1):
            lv = k / (levels + 1.0)
            dist = np.abs(f - lv) / (gm + 1e-6)
            ink = np.maximum(ink, np.clip(0.4 * width - dist + 0.5, 0.0, 1.0) * weak)
    return ink.astype(np.float32)


# --------------------------------------------------------------------------
# Line: characters as pen strokes
# --------------------------------------------------------------------------
def _arc(u_end, bulge, n=9):
    return [(u_end - bulge * math.sin(math.pi * i / (n - 1.0)), i / (n - 1.0)) for i in range(n)]


def _wave():
    return [(i / 8.0, 0.52 - 0.13 * math.sin(2 * math.pi * i / 8.0)) for i in range(9)]


# glyph -> list of ("p", [(u, v), ...], link) polyline, ("d", u, v) dot, ("r", u, v, rx, ry) ring.
# u, v run 0..1 across the cell (v downwards); link = its ends may join other strokes.
GEOM = {
    "/": [("p", [(0, 1), (1, 0)], 1)],
    "\\": [("p", [(0, 0), (1, 1)], 1)],
    "|": [("p", [(0.5, 0), (0.5, 1)], 1)],
    "_": [("p", [(0, 0.93), (1, 0.93)], 1)],
    "\u00af": [("p", [(0, 0.07), (1, 0.07)], 1)],
    "\u203e": [("p", [(0, 0.07), (1, 0.07)], 1)],
    "-": [("p", [(0, 0.5), (1, 0.5)], 1)],
    "=": [("p", [(0, 0.38), (1, 0.38)], 1), ("p", [(0, 0.62), (1, 0.62)], 1)],
    "~": [("p", _wave(), 1)],
    "^": [("p", [(0.08, 0.62), (0.5, 0.1), (0.92, 0.62)], 1)],
    "v": [("p", [(0.08, 0.38), (0.5, 0.9), (0.92, 0.38)], 1)],
    "V": [("p", [(0.0, 0.06), (0.5, 0.95), (1.0, 0.06)], 1)],
    "<": [("p", [(0.92, 0.2), (0.08, 0.5), (0.92, 0.8)], 1)],
    ">": [("p", [(0.08, 0.2), (0.92, 0.5), (0.08, 0.8)], 1)],
    "(": [("p", _arc(0.72, 0.42), 1)],
    ")": [("p", _arc(0.28, -0.42), 1)],
    "[": [("p", [(0.7, 0), (0.3, 0), (0.3, 1), (0.7, 1)], 1)],
    "]": [("p", [(0.3, 0), (0.7, 0), (0.7, 1), (0.3, 1)], 1)],
    "{": [("p", [(0.72, 0), (0.52, 0.08), (0.5, 0.4), (0.18, 0.5), (0.5, 0.6), (0.52, 0.92), (0.72, 1)], 1)],
    "}": [("p", [(0.28, 0), (0.48, 0.08), (0.5, 0.4), (0.82, 0.5), (0.5, 0.6), (0.48, 0.92), (0.28, 1)], 1)],
    "'": [("p", [(0.5, 0.04), (0.5, 0.34)], 1)],
    "`": [("p", [(0.3, 0.04), (0.62, 0.34)], 1)],
    "\u00b4": [("p", [(0.7, 0.04), (0.38, 0.34)], 1)],
    "\"": [("p", [(0.32, 0.04), (0.32, 0.32)], 0), ("p", [(0.68, 0.04), (0.68, 0.32)], 0)],
    ".": [("d", 0.5, 0.9, 1)],
    ",": [("p", [(0.58, 0.84), (0.42, 1.06)], 0)],
    ":": [("d", 0.5, 0.36), ("d", 0.5, 0.9)],
    ";": [("d", 0.5, 0.36), ("p", [(0.58, 0.84), (0.42, 1.06)], 0)],
    "!": [("p", [(0.5, 0.02), (0.5, 0.68)], 1), ("d", 0.5, 0.9)],
    "+": [("p", [(0.08, 0.5), (0.92, 0.5)], 1), ("p", [(0.5, 0.26), (0.5, 0.74)], 0)],
    "*": [("p", [(0.1, 0.4), (0.9, 0.4)], 1), ("p", [(0.5, 0.2), (0.5, 0.6)], 0),
          ("p", [(0.28, 0.27), (0.72, 0.53)], 0), ("p", [(0.28, 0.53), (0.72, 0.27)], 0)],
    "o": [("r", 0.5, 0.66, 0.3, 0.17)],
    "O": [("r", 0.5, 0.5, 0.42, 0.38)],
    "0": [("r", 0.5, 0.5, 0.42, 0.38)],
}


def box_arms(c):
    """Box-drawing character -> ({dir: 'LIGHT'|'HEAVY'|'DOUBLE'}, rounded), from its Unicode
    name; None if it is not an ordinary box piece."""
    try:
        name = unicodedata.name(c)
    except ValueError:
        return None
    if not name.startswith("BOX DRAWINGS "):
        return None
    words = name[13:].replace("DOUBLE DASH", "").replace("TRIPLE DASH", "") \
                     .replace("QUADRUPLE DASH", "").replace("DASH", "").split()
    if "DIAGONAL" in words:
        return None
    arc = "ARC" in words
    groups = [[]]
    for w in words:
        if w == "AND":
            groups.append([])
        else:
            groups[-1].append(w)
    arms, first = {}, None
    for g in groups:
        st = next((w for w in g if w in ("LIGHT", "HEAVY", "DOUBLE", "SINGLE")), None)
        if st is None:
            st = first or "LIGHT"
        else:
            first = first or st
        st = "LIGHT" if st == "SINGLE" else st
        for w in g:
            for k in {"UP": "u", "DOWN": "d", "LEFT": "l", "RIGHT": "r",
                      "VERTICAL": "ud", "HORIZONTAL": "lr"}.get(w, ""):
                arms[k] = st
    return (arms, arc) if arms else None


class Path(object):
    __slots__ = ("pts", "link", "wmul", "join")

    def __init__(self, pts, link=False, wmul=1.0):
        self.pts, self.link, self.wmul = pts, link, wmul
        self.join = [False] * len(pts)


def box_paths(arms, arc, x0, y0, cw, ch):
    cx, cy = x0 + cw / 2.0, y0 + ch / 2.0
    edge = {"u": (cx, y0), "d": (cx, y0 + ch), "l": (x0, cy), "r": (x0 + cw, cy)}
    if arc and len(arms) == 2:
        a, b = sorted(arms)
        pts = []
        for i in range(9):
            t = i / 8.0
            pts.append(((1 - t) ** 2 * edge[a][0] + 2 * t * (1 - t) * cx + t * t * edge[b][0],
                        (1 - t) ** 2 * edge[a][1] + 2 * t * (1 - t) * cy + t * t * edge[b][1]))
        return [Path(pts, False, 1.8 if "HEAVY" in arms.values() else 1.0)]
    dd = 0.15 * cw
    out = []
    for d, st in arms.items():
        wm = 1.8 if st == "HEAVY" else 1.0
        vert = d in "ud"
        perp = [k for k in arms if (k in "lr") == vert]
        if st != "DOUBLE":
            out.append(Path([edge[d], (cx, cy)], False, wm))
            continue
        away = {"u": 1, "d": -1, "l": 1, "r": -1}[d]          # which way is "past the centre"
        for s in (-1, 1):
            if not perp or any(arms[k] != "DOUBLE" for k in perp):
                end = 0
            elif len(perp) == 2:
                end = -away * dd
            else:                                              # corner: outer line goes past
                p_side = {"l": -1, "r": 1, "u": -1, "d": 1}[perp[0]]
                end = away * dd if s == -p_side else -away * dd
            if vert:
                out.append(Path([(cx + s * dd, edge[d][1]), (cx + s * dd, cy + end)], False, 1.0))
            else:
                out.append(Path([(edge[d][0], cy + s * dd), (cx + end, cy + s * dd)], False, 1.0))
    return out


def glyph_paths(c, col, row, cw, ch, cache, lonely=True):
    """Strokes of character c at cell (col, row), in pixels; None if c is not a stroke
    character (the caller then renders the font glyph).  lonely: nothing beside it, so a
    + or * is drawn as the mark it is; inside a run it is just a bump in the line."""
    x0, y0 = col * cw, row * ch
    spec = GEOM.get(c)
    if spec is not None and c in "+*" and not lonely:
        spec = spec[:1]
    if spec is None:
        if c in "\u2571\u2572\u2573":
            spec = ([GEOM["/"][0]] if c != "\u2572" else []) + ([GEOM["\\"][0]] if c != "\u2571" else [])
        else:
            if c not in cache:
                cache[c] = box_arms(c) if is_box(c) else None
            ba = cache[c]
            return box_paths(ba[0], ba[1], x0, y0, cw, ch) if ba else None
    out = []
    for s in spec:
        if s[0] == "p":
            out.append(Path([(x0 + u * cw, y0 + v * ch) for u, v in s[1]], bool(s[2])))
        elif s[0] == "d":
            p = (x0 + s[1] * cw, y0 + s[2] * ch)
            out.append(Path([p, p], bool(s[3]) if len(s) > 3 else False))   # a dot: both ends here
        else:
            _k, u, v, rx, ry = s
            pts = [(x0 + (u + rx * math.cos(2 * math.pi * i / 20.0)) * cw,
                    y0 + (v + ry * math.sin(2 * math.pi * i / 20.0)) * ch) for i in range(21)]
            out.append(Path(pts, False, 1.0))
    return out


def link_paths(paths, thr):
    """Join stroke ends that nearly meet.  Returns {(path index, end 0|1): (index, end)}.
    Closest pairs first; an end joins at most one other, never to its own stroke, and never
    by a link that doubles back over the stroke it leaves."""
    ends = []
    for i, p in enumerate(paths):
        if p.link:
            ends.append((i, 0))
            ends.append((i, 1))
    if not ends:
        return {}, []

    def pt(e):
        return paths[e[0]].pts[0 if e[1] == 0 else -1]

    def out_dir(e):
        p = paths[e[0]].pts
        a, b = (p[1], p[0]) if e[1] == 0 else (p[-2], p[-1])
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy)
        return (dx / n, dy / n) if n > 1e-6 else None

    cell = max(thr, 1.0)
    bins = {}
    for e in ends:
        x, y = pt(e)
        bins.setdefault((int(x // cell), int(y // cell)), []).append(e)
    cand = []
    for e in ends:
        x, y = pt(e)
        bx, by = int(x // cell), int(y // cell)
        de = out_dir(e)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for f in bins.get((bx + dx, by + dy), ()):
                    if f[0] <= e[0]:
                        continue
                    q = pt(f)
                    vx, vy = q[0] - x, q[1] - y
                    dist = math.hypot(vx, vy)
                    if dist > thr:
                        continue
                    if dist > 0.5:
                        df = out_dir(f)
                        if (de and vx * de[0] + vy * de[1] < -0.2 * dist) or \
                           (df and -(vx * df[0] + vy * df[1]) < -0.2 * dist):
                            continue
                    cand.append((dist, e, f))
    cand.sort()
    links = {}
    for dist, e, f in cand:
        if e not in links and f not in links:
            links[e] = f
            links[f] = e
    # a stroke end that found no partner may still touch a junction: join it by a bare segment
    extras = []
    for e in ends:
        if e in links:
            continue
        x, y = pt(e)
        bx, by = int(x // cell), int(y // cell)
        de = out_dir(e)
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for f in bins.get((bx + dx, by + dy), ()):
                    if f[0] == e[0]:
                        continue
                    q = pt(f)
                    vx, vy = q[0] - x, q[1] - y
                    dist = math.hypot(vx, vy)
                    if dist > 0.8 * thr or (de and dist > 0.5 and vx * de[0] + vy * de[1] < -0.2 * dist):
                        continue
                    if best is None or dist < best[0]:
                        best = (dist, q)
        if best:
            extras.append(([[x, y, False], [best[1][0], best[1][1], False]], 1.0, False))
    return links, extras


def chains(paths, links):
    """Walk the links and return strokes as (points [x, y, joined], pen width, smoothable)."""
    done = [False] * len(paths)
    out = []

    def walk(i, start):
        pts = []
        while True:
            done[i] = True
            p = paths[i]
            seq = list(zip(p.pts, p.join))
            if start == 1:
                seq.reverse()
            for k, (pt, _j) in enumerate(seq):
                pts.append([pt[0], pt[1], k == 0 and bool(pts) or (k == len(seq) - 1 and (i, 1 - start) in links)])
            nxt = links.get((i, 1 - start))
            if nxt is None or done[nxt[0]]:
                return pts
            pts[-1][2] = True
            i, start = nxt

    for i, p in enumerate(paths):
        if done[i]:
            continue
        if not p.link:
            done[i] = True
            out.append(([[x, y, False] for x, y in p.pts], p.wmul, False))     # a ring, a box piece: as is
            continue
        if (i, 0) in links and (i, 1) in links:
            continue                                            # inside a chain or a loop: later
        start = 0 if (i, 0) not in links else 1
        out.append((walk(i, start), p.wmul, True))
    for i, p in enumerate(paths):                                # pure loops
        if not done[i]:
            out.append((walk(i, 0), p.wmul, True))
    return out


def fillet(pts, rcap, max_turn, join_turn):
    """Round the corners of a polyline with quadratic curves.  Corners at joins between
    characters are rounded up to join_turn degrees, corners inside a character to max_turn."""
    clean = [pts[0]]
    for p in pts[1:]:
        if math.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1]) > 0.05:
            clean.append(p)
    if len(clean) < 3:
        return [(p[0], p[1]) for p in clean]
    out = [(clean[0][0], clean[0][1])]
    for i in range(1, len(clean) - 1):
        a, v, b = clean[i - 1], clean[i], clean[i + 1]
        ax, ay, bx, by = a[0] - v[0], a[1] - v[1], b[0] - v[0], b[1] - v[1]
        la, lb = math.hypot(ax, ay), math.hypot(bx, by)
        cosv = max(-1.0, min(1.0, (ax * bx + ay * by) / (la * lb)))
        turn = 180.0 - math.degrees(math.acos(cosv))
        if turn < 3 or turn > (join_turn if v[2] else max_turn):
            out.append((v[0], v[1]))
            continue
        r = min(0.5 * la, 0.5 * lb, rcap)
        p0 = (v[0] + ax / la * r, v[1] + ay / la * r)
        p1 = (v[0] + bx / lb * r, v[1] + by / lb * r)
        for k in range(7):
            t = k / 6.0
            out.append(((1 - t) ** 2 * p0[0] + 2 * t * (1 - t) * v[0] + t * t * p1[0],
                        (1 - t) ** 2 * p0[1] + 2 * t * (1 - t) * v[1] + t * t * p1[1]))
    out.append((clean[-1][0], clean[-1][1]))
    return out


def _turn(a, v, b):
    """How far, in degrees, a path turns at v on its way a -> v -> b."""
    ax, ay, bx, by = a[0] - v[0], a[1] - v[1], b[0] - v[0], b[1] - v[1]
    la, lb = math.hypot(ax, ay), math.hypot(bx, by)
    if la < 1e-9 or lb < 1e-9:
        return 0.0
    return 180.0 - math.degrees(math.acos(max(-1.0, min(1.0, (ax * bx + ay * by) / (la * lb)))))


def _smooth_span(pts, sigma, h):
    """Smooth an open polyline, keeping its two ends where they are.  It is resampled every
    h pixels and low-passed with a Gaussian of `sigma` pixels (a smoothing spline): staircases
    of _ and / become a diagonal, rows of marks a wave, straight runs stay straight.  The
    ends are pinned by reflecting the curve through them (odd extension) before filtering."""
    if len(pts) < 3:
        return [(p[0], p[1]) for p in pts]
    P = np.asarray([(p[0], p[1]) for p in pts], np.float64)
    d = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))))
    n = max(2, int(round(d[-1] / h)) + 1)
    if n < 4:
        return [(p[0], p[1]) for p in pts]
    t = np.linspace(0.0, d[-1], n)
    P = np.column_stack([np.interp(t, d, P[:, 0]), np.interp(t, d, P[:, 1])])
    s = max(sigma / h, 0.5)
    r = max(1, int(math.ceil(3.0 * s)))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / s) ** 2)
    k /= k.sum()
    i = np.arange(1, r + 1)
    Q = np.vstack([2 * P[0] - P[np.minimum(i, n - 1)][::-1], P, 2 * P[-1] - P[np.maximum(n - 1 - i, 0)]])
    return list(zip(np.convolve(Q[:, 0], k, mode="valid").tolist(),
                    np.convolve(Q[:, 1], k, mode="valid").tolist()))


def spline_smooth(pts, sigma, h, max_turn, join_turn, step):
    """Smooth a chain [[x, y, joined]] with _smooth_span, but leave the sharp corners alone:
    the chain is cut at them (more than join_turn degrees where two characters meet,
    max_turn inside one: the apex of ^, the tip of <, the corners of [; terraces, two turns
    within `step` pixels, count as smooth up to join_turn) and each stretch
    between is smoothed with both its ends pinned."""
    n = len(pts)
    if n < 3:
        return [(p[0], p[1]) for p in pts]
    # signed turn at every vertex: positive one way, negative the other
    signed = [0.0] * n
    for i in range(1, n - 1):
        a, v, b = pts[i - 1], pts[i], pts[i + 1]
        cross = (v[0] - a[0]) * (b[1] - v[1]) - (v[1] - a[1]) * (b[0] - v[0])
        dot = (v[0] - a[0]) * (b[0] - v[0]) + (v[1] - a[1]) * (b[1] - v[1])
        signed[i] = math.degrees(math.atan2(cross, dot))

    def stepped(i):
        """Is vertex i one half of an S: a turn one way and, within `step` px, one the other
        way (the riser between a _ and a - on the next row)?  That is a terrace to smooth,
        where a single right angle (|_) is a corner to keep."""
        for j in (i - 1, i + 1):
            if 0 < j < n - 1 and signed[j] * signed[i] < 0 and abs(signed[j]) > 40 and \
               math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) <= step:
                return True
        return False

    def corner(i):
        """The turn at vertex i, with its neighbours' if they turn the same way close by: a
        right angle between two characters is two 45 degree turns with a short link between."""
        t = signed[i]
        for j in (i - 1, i + 1):
            if 0 < j < n - 1 and signed[j] * signed[i] > 0 and \
               math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) <= step:
                t += signed[j]
        return abs(t)

    def sharp(i):
        if not pts[i][2]:
            return abs(signed[i]) > max_turn
        if stepped(i):
            return abs(signed[i]) > join_turn
        return corner(i) > 85
    cut = [0] + [i for i in range(1, n - 1) if sharp(i)] + [n - 1]
    out = []
    for a, b in zip(cut, cut[1:]):
        seg = _smooth_span(pts[a:b + 1], sigma, h)
        out.extend(seg if not out else seg[1:])
    return out


def hatch_layer(mask, cw, ch, w, space):
    """Diagonal hatching ("/" lines, w pixels wide, `space` pixels apart across the lines)
    filling the cells where mask is true.  The pattern is anchored to the picture, so
    neighbouring shaded regions line up."""
    m = np.kron(np.asarray(mask, np.float32), np.ones((ch, cw), np.float32))
    # the region follows the cell grid; soften it so slanted edges are slanted, not stepped
    m = smoothstep((blur(np.pad(m, ((ch, ch), (cw, cw)), mode="constant"), 0.5 * cw, 0.25 * ch)
                    [ch:-ch, cw:-cw] - 0.35) / 0.3)
    ys, xs = np.mgrid[0:m.shape[0], 0:m.shape[1]]
    period = space * math.sqrt(2.0)
    u = (xs + ys) % period
    dist = np.minimum(u, period - u) / math.sqrt(2.0)
    return (np.clip(0.5 * w - dist + 0.5, 0.0, 1.0) * m).astype(np.float32)


def draw_strokes(strokes, W, H, w, ss):
    """Antialiased pen strokes: drawn at ss times the size, then box-filtered down."""
    big = Image.new("L", (W * ss, H * ss), 0)
    d = ImageDraw.Draw(big)
    for pts, wmul in strokes:
        if len(pts) == 1:                                        # a dot
            r = 0.9 * w * ss
            x, y = pts[0][0] * ss, pts[0][1] * ss
            d.ellipse([x - r, y - r, x + r, y + r], fill=255)
            continue
        wp = max(1.0, w * wmul * ss)
        r = wp / 2.0
        P = [(x * ss, y * ss) for x, y in pts]
        for a, b in zip(P, P[1:]):
            d.line([a, b], fill=255, width=int(round(wp)))
        for x, y in P:
            d.ellipse([x - r, y - r, x + r, y + r], fill=255)
    return np.asarray(big.resize((W, H), Image.BOX), np.float32) / 255.0


# --------------------------------------------------------------------------
# Putting it together
# --------------------------------------------------------------------------
class Options(object):
    mode = "auto"           # auto | line | tone | mix
    cell_w = 12             # pixels per character cell
    aspect = 2.0            # cell height / width
    weight = 1.0            # pen thickness, relative
    join = 1.0              # how far apart stroke ends may be and still join, in cell widths
    round_lines = True      # smooth the strokes (False: leave every corner sharp)
    spline = 0.6            # line: how much, as a Gaussian sigma in cell widths (0 = round corners only)
    shade = "X"             # line: runs of these characters are shading (hatched); "" = none
    hatch = 1.0             # line: spacing of that hatching, relative
    text_bold = 0.25        # line: how much letters thicken as the pen gets thicker (0 = not at all)
    smooth = 0.7           # tone: blur, in dot pitches (smooths the contours)
    detail = 0.12           # tone: smallest edge (tone change per dot pitch) that is drawn
    scale = 0.4             # tone: finest outline feature, in dot pitches
    levels = 3              # tone: contour lines through the shading (0 = outlines only)
    dark = False            # tone: the art is meant for a dark terminal (default colours)
    invert = False          # tone: draw outlines of the negative (affects nothing for edges)
    font = None
    cols = 0                # wrap column for cursor-addressed .ANS art (0: never)
    crop = True
    verbose = False

    def __init__(self, **kw):
        for k, v in kw.items():
            if not hasattr(self, k):
                raise TypeError("unknown option " + k)
            setattr(self, k, v)


def _log(o, *a):
    if o.verbose:
        sys.stderr.write("unascii: " + " ".join(str(x) for x in a) + "\n")


def render_grid(grid, o):
    """Grid -> ink picture: float32 array, 1 = ink, rows*cell_h x cols*cell_w (+ margin)."""
    cw = max(4, int(o.cell_w))
    cw += cw % 2                                  # half-cell and braille dots need whole pixels
    ch = max(4, int(round(cw * o.aspect / 4.0)) * 4)
    mode = o.mode
    shade = shade_cells(grid, o.shade)
    if mode == "auto":
        mode, st = classify(grid, shade)
        _log(o, "auto ->", mode, " ".join("%s=%.2f" % kv for kv in sorted(st.items())))
    glyphs = Glyphs(cw, ch, o.font)
    _log(o, "font:", glyphs.path)
    pad = cw
    W, H = grid.cols * cw + 2 * pad, grid.rows * ch + 2 * pad
    ink = np.zeros((H, W), np.float32)
    wpx = 0.12 * cw * o.weight

    def put(layer, dy=pad, dx=pad):
        h, w = layer.shape
        ink[dy:dy + h, dx:dx + w] = np.maximum(ink[dy:dy + h, dx:dx + w], layer)

    if mode == "tone" or mode == "mix":
        if mode == "tone":
            only = None
        else:
            def only(c):
                return c in DENSE or is_block(c) or is_braille(c)
        px, py = pitch_of(grid, cw, ch)
        d = darkness(grid, glyphs, only, o.dark)
        if o.invert:
            d = 1.0 - d
        put(edge_lines(d, px, py, wpx, o.smooth, o.scale, o.detail, o.levels))
    if mode == "line" or mode == "mix":
        paths, cache = [], {}
        layer = np.zeros((grid.rows * ch, grid.cols * cw), np.float32)
        text = word_cells(grid, shade)
        lifted = bubble_bottoms(grid)
        for y in range(grid.rows):
            for x in range(grid.cols):
                c = grid.ch[y][x]
                if c == " " or (shade and shade[y][x]):
                    continue
                if mode == "mix" and (c in DENSE or is_block(c) or is_braille(c)):
                    continue
                row = grid.ch[y]
                lonely = (x == 0 or row[x - 1] == " ") and (x == grid.cols - 1 or row[x + 1] == " ")
                if (y, x) in lifted:                             # speech bubble: close it at the bottom
                    ps = [Path([(x * cw, y * ch + 0.07 * ch), ((x + 1) * cw, y * ch + 0.07 * ch)], True)]
                else:
                    ps = None if text[y][x] else glyph_paths(c, x, y, cw, ch, cache, lonely)
                if ps is not None:
                    paths.extend(ps)
                else:                                            # letters etc.: the font's glyph
                    m = glyphs.mask(c)
                    if o.weight > 1.2:
                        m = np.clip(blur(m, 0.25 * wpx) * min(1.6, 1.0 + (o.weight - 1.0) * o.text_bold), 0, 1)
                    layer[y * ch:(y + 1) * ch, x * cw:(x + 1) * cw] = m
        for p in paths:
            p.pts = [(a + pad, b + pad) for a, b in p.pts]
        links, extras = link_paths(paths, o.join * cw)
        strokes = chains(paths, links) + extras
        done = []
        for pts, wm, smoothable in strokes:
            clean = [pts[0]]
            for p in pts[1:]:
                if math.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1]) > 0.05:
                    clean.append(p)                              # (a lone dot ends up as one point)
            if not smoothable:
                done.append(([(p[0], p[1]) for p in clean], wm))
            elif o.round_lines and len(clean) > 2 and o.spline > 0:
                done.append((spline_smooth(clean, o.spline * cw, max(1.0, 0.1 * cw), 80, 100, 1.1 * cw), wm))
            elif o.round_lines and len(clean) > 2:
                done.append((fillet(clean, 0.6 * cw, 80, 100), wm))
            else:
                done.append(([(p[0], p[1]) for p in clean], wm))
        strokes = done
        ss = max(1, min(4, int(math.sqrt(16e6 / float(W * H)))))
        ink = np.maximum(ink, draw_strokes(strokes, W, H, wpx, ss))
        put(layer)
        if shade:
            space = 0.55 * cw * o.hatch
            put(hatch_layer(shade, cw, ch, min(0.55 * wpx, 0.3 * space), space))
        _log(o, "strokes: %d paths, %d joins, %d chains%s" % (len(paths), len(links) // 2, len(strokes),
                                                            ", shaded" if shade else ""))
    if o.crop:
        ys, xs = np.nonzero(ink > 0.02)
        if len(ys):
            m = int(0.5 * cw)
            ink = ink[max(0, ys.min() - m):ys.max() + m + 1, max(0, xs.min() - m):xs.max() + m + 1]
    return ink


def render(data, **kw):
    """text/bytes -> ink array (1 = ink).  Keyword arguments are Options fields."""
    o = Options(**kw)
    grid = parse(decode(data), o.cols)
    return render_grid(grid, o)


def to_image(ink, fg=(0, 0, 0), bg=(255, 255, 255), transparent=False):
    a = np.clip(ink, 0, 1)
    if transparent:
        rgba = np.zeros(a.shape + (4,), np.uint8)
        rgba[..., :3] = fg
        rgba[..., 3] = (a * 255 + 0.5).astype(np.uint8)
        return Image.fromarray(rgba, "RGBA")
    f, b = np.array(fg, np.float32), np.array(bg, np.float32)
    rgb = b + (f - b) * a[..., None]
    return Image.fromarray((rgb + 0.5).astype(np.uint8), "RGB")


def mask(data, cell_w, cell_h=None, **kw):
    """For other programs (bidet3d): the drawing as a PIL 'L' mask, 255 = ink, cropped to the
    drawing.  cell_w / cell_h are the size of one character cell in pixels."""
    kw.setdefault("cell_w", cell_w)
    if cell_h:
        kw["aspect"] = cell_h / float(cell_w)
    ink = render(data, **kw)
    return Image.fromarray((np.clip(ink, 0, 1) * 255 + 0.5).astype(np.uint8), "L")


# --------------------------------------------------------------------------
# SIXEL out (ink picture -> a ramp from paper to ink, so both are exact)
# --------------------------------------------------------------------------
def _rle(vals):
    change = np.flatnonzero(vals[1:] != vals[:-1]) + 1
    starts = np.concatenate(([0], change))
    ends = np.concatenate((change, [len(vals)]))
    parts = []
    for s, e in zip(starts, ends):
        n, c = int(e - s), chr(int(vals[s]))
        parts.append(("!%d%s" % (n, c)) if n > 3 else c * n)
    return "".join(parts)


def sixel(ink, fg=(0, 0, 0), bg=(255, 255, 255), levels=16, transparent=False):
    """SIXEL stream (bytes) for an ink picture.  Pixels are painted in `levels` blends of
    bg -> fg; with transparent=True the bg pixels are left unpainted."""
    H, W = ink.shape
    idx = np.clip(np.rint(np.clip(ink, 0, 1) * (levels - 1)), 0, levels - 1).astype(np.uint8)
    out = ["\x1bP0;%d;0q\"1;1;%d;%d" % (1 if transparent else 0, W, H)]
    for i in range(levels):
        t = i / float(levels - 1)
        rgb = [bg[k] + (fg[k] - bg[k]) * t for k in range(3)]
        out.append("#%d;2;%d;%d;%d" % (i, *[int(round(v * 100 / 255.0)) for v in rgb]))
    weights = (1 << np.arange(6)).astype(np.uint8)[:, None]
    for top in range(0, H, 6):
        band = idx[top:top + 6]
        if band.shape[0] < 6:
            band = np.vstack([band, np.full((6 - band.shape[0], W), 255, np.uint8)])
        present = [c for c in np.unique(band) if c != 255 and not (transparent and c == 0)]
        for n, c in enumerate(present):
            bits = ((band == c).astype(np.uint8) * weights).sum(0).astype(np.uint8) + 63
            s = _rle(bits)
            if s.endswith("?") and not s.endswith("!?"):
                s = s.rstrip("?")
            else:
                s = re.sub(r"!\d+\?$", "", s)
            out.append("#%d%s%s" % (c, s, "$" if n < len(present) - 1 else ""))
        out.append("-")
    out.append("\x1b\\")
    return "".join(out).encode("ascii")


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------
def _color(s):
    from PIL import ImageColor
    try:
        return ImageColor.getrgb(s)[:3]
    except ValueError:
        sys.exit("unascii: bad colour '%s'" % s)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="unascii", description="Turn ASCII/ANSI terminal art back into a line drawing "
        "(PNG, or SIXEL for the terminal).")
    ap.add_argument("file", nargs="?", default="-", help="art file (default: stdin)")
    ap.add_argument("-o", "--output", metavar="FILE", help="write a PNG here ('-' = stdout)")
    ap.add_argument("-s", "--sixel", action="store_true",
                    help="print SIXEL to stdout (default when stdout is a terminal)")
    ap.add_argument("-m", "--mode", choices=["auto", "line", "tone", "mix"], default="auto",
                    help="line: strokes, tone: density -> outlines, mix: both (default auto)")
    ap.add_argument("-c", "--cell", type=int, default=12, metavar="PX",
                    help="width of one character cell in output pixels (default 12)")
    ap.add_argument("-a", "--aspect", type=float, default=2.0,
                    help="cell height / width (default 2.0)")
    ap.add_argument("-w", "--weight", type=float, default=1.0, help="pen thickness (default 1)")
    ap.add_argument("-j", "--join", type=float, default=1.0, metavar="CELLS",
                    help="line mode: join stroke ends this close (cell widths, default 1; 0 = never)")
    ap.add_argument("--no-round", action="store_true", help="line mode: no smoothing, keep every corner sharp")
    ap.add_argument("--spline", type=float, default=0.6, metavar="F",
                    help="line mode: spline smoothing of joined strokes, in cell widths (default 0.6; "
                         "0 = only round the corners)")
    ap.add_argument("--shade", default="X", metavar="CHARS",
                    help="line mode: runs of these characters are shading and get hatched (default X; "
                         "'' = none)")
    ap.add_argument("--text-bold", type=float, default=0.25, metavar="F",
                    help="line mode: how much letters thicken with --weight above 1.2 (default 0.25; 0 = never)")
    ap.add_argument("--hatch", type=float, default=1.0, metavar="F",
                    help="line mode: spacing of the hatching (default 1)")
    ap.add_argument("--smooth", type=float, default=0.7, help="tone: blur in dot pitches (default 0.7)")
    ap.add_argument("--detail", type=float, default=0.12,
                    help="tone: smallest tonal step that gets an outline (0..1, default 0.12)")
    ap.add_argument("--scale", type=float, default=0.4,
                    help="tone: finest outline feature in dot pitches (default 0.4)")
    ap.add_argument("--levels", type=int, default=3,
                    help="tone: contour lines through the shading (default 3, 0 = outlines only)")
    ap.add_argument("--dark", action="store_true", help="the art is light-on-dark (default colours)")
    ap.add_argument("--invert", action="store_true", help="tone: outline the negative")
    ap.add_argument("--ink", default="black", help="line colour (default black)")
    ap.add_argument("--paper", default="white", help="background colour (default white)")
    ap.add_argument("--transparent", action="store_true", help="PNG/SIXEL with a transparent background")
    ap.add_argument("--width", type=int, metavar="PX", help="scale the picture to this width")
    ap.add_argument("--font", help="monospace font file (default: look for DejaVu Sans Mono, Consolas, ...)")
    ap.add_argument("--encoding", help="input encoding (default: UTF-8, else CP437)")
    ap.add_argument("--cols", type=int, default=0, help="wrap column for .ANS art (default: none)")
    ap.add_argument("--no-crop", action="store_true", help="keep the margin around the drawing")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-V", "--version", action="version", version="unascii " + VERSION)
    a = ap.parse_args(argv)

    if a.file == "-":
        if sys.stdin.isatty():
            ap.error("no input: give a file or pipe the art in")
        data = sys.stdin.buffer.read()
    else:
        with open(a.file, "rb") as f:
            data = f.read()
    o = Options(mode=a.mode, cell_w=a.cell, aspect=a.aspect, weight=a.weight, join=a.join * 1.0,
                round_lines=not a.no_round, spline=a.spline, shade=a.shade, hatch=a.hatch, text_bold=a.text_bold, smooth=a.smooth, detail=a.detail, scale=a.scale, levels=a.levels,
                dark=a.dark, invert=a.invert, font=a.font, cols=a.cols or (80 if a.file.lower().endswith(".ans") else 0),
                crop=not a.no_crop, verbose=a.verbose)
    if a.join <= 0:
        o.join = 0.0
    ink = render_grid(parse(decode(data, a.encoding), o.cols), o)
    fg, bg = _color(a.ink), _color(a.paper)
    if a.width and a.width != ink.shape[1]:
        h = max(1, int(round(ink.shape[0] * a.width / float(ink.shape[1]))))
        im = Image.fromarray((np.clip(ink, 0, 1) * 255 + 0.5).astype(np.uint8), "L")
        ink = np.asarray(im.resize((a.width, h), Image.LANCZOS), np.float32) / 255.0

    out = sys.stdout.buffer
    want_sixel = a.sixel or (not a.output and sys.stdout.isatty())
    if a.output:
        img = to_image(ink, fg, bg, a.transparent)
        if a.output == "-":
            buf = io.BytesIO()
            img.save(buf, "PNG")
            out.write(buf.getvalue())
            out.flush()
        else:
            img.save(a.output, "PNG")
    if want_sixel or not a.output and not sys.stdout.isatty():
        if want_sixel:
            out.write(sixel(ink, fg, bg, transparent=a.transparent) + b"\n")
        else:
            buf = io.BytesIO()
            to_image(ink, fg, bg, a.transparent).save(buf, "PNG")
            out.write(buf.getvalue())
        out.flush()


if __name__ == "__main__":
    main()
