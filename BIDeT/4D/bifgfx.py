"""bifgfx: the output formats of bifout that are not SIXEL, PNG or GIF: how else a picture reaches a terminal.

    kitty_sequence(png)                       the kitty graphics protocol (kitty, WezTerm, Ghostty ...)
    iterm_sequence(png)                       iTerm2 inline images (iTerm2, WezTerm, mintty ...)
    ansi_art(rgba, cols, rows)                coloured Unicode text: block, quadrant, eighth and Braille characters
    tek_raster(rgba, mode)                    Tektronix 4010/4014 vectors from pixels: hatch, dots, contour
    tek_vectors(pic, frame)                   Tektronix vectors from a BIF's own paths (a vector terminal's native food)
    pick_format(reply, env)                   which of them a terminal should be sent, by what it says about itself

Ported by copy from the converters in ../3D/gfx-conv (sixel2kitty, sixel2iterm, sixel2ans, sixel2tek), which read SIXEL;
here they take the pixels bifout already has.  4D does not import them: tests compare the two where gfx-conv is present.
numpy only (the plain-Python fallbacks of the originals are gone).  GRAPHICS-HISTORY.md is why there are several.
Python 3.7+.
"""
from __future__ import print_function

import base64
import math
import os

import numpy as np

# ---------------------------------------------------------------------------------------------
# kitty graphics protocol, iTerm2 inline images: a PNG in an escape sequence
# ---------------------------------------------------------------------------------------------
CHUNK = 4096


def kitty_sequence(png, cols=None, rows=None, image_id=None):
    """APC sequence(s) that transmit and display one PNG at the cursor (https://sw.kovidgoyal.net/kitty/graphics-protocol/).
    cols / rows: scale to that many character cells; image_id: a later picture with the same id replaces it."""
    b64 = base64.standard_b64encode(png)
    keys = ["a=T", "f=100", "q=2"]                    # transmit+display, PNG, no terminal replies
    if cols:
        keys.append("c=%d" % cols)
    if rows:
        keys.append("r=%d" % rows)
    if image_id:
        keys.append("i=%d" % image_id)
    out = []
    for pos in range(0, len(b64), CHUNK):
        part = b64[pos:pos + CHUNK]
        more = 1 if pos + CHUNK < len(b64) else 0
        head = ",".join(keys + ["m=%d" % more]) if pos == 0 else "m=%d,q=2" % more
        out.append(b"\x1b_G" + head.encode() + b";" + part + b"\x1b\\")
    return b"".join(out)


def iterm_sequence(png, width=None, height=None, name="picture.png"):
    """OSC 1337 sequence that shows one PNG at the cursor (https://iterm2.com/documentation-images.html).
    width / height: character cells, or None for the picture's own size."""
    args = ["name=" + base64.standard_b64encode(name.encode()).decode(), "size=%d" % len(png), "inline=1",
            "preserveAspectRatio=1"]
    if width:
        args.append("width=%d" % width)
    if height:
        args.append("height=%d" % height)
    return b"\x1b]1337;File=" + ";".join(args).encode() + b":" + base64.standard_b64encode(png) + b"\x07"


# ---------------------------------------------------------------------------------------------
# Which format: by what the terminal says about itself
# ---------------------------------------------------------------------------------------------
def pick_format(reply=None, env=None):
    """`auto`: kitty or iTerm2 if the environment says that is the terminal; else SIXEL if it reported it (or nothing could
    be asked, which has always meant "go on with SIXEL"); else ANSI art, which every UTF-8 terminal can show."""
    env = os.environ if env is None else env
    if env.get("KITTY_WINDOW_ID") or "kitty" in env.get("TERM", "") or env.get("TERM_PROGRAM") == "ghostty":
        return "kitty"
    if env.get("TERM_PROGRAM") == "iTerm.app" or env.get("LC_TERMINAL") == "iTerm2":
        return "iterm"
    if reply is None or not reply.asked:
        return "sixel"
    return "sixel" if reply.sixel is True else "ansi"


# ---------------------------------------------------------------------------------------------
# ANSI art: every character cell is an 8x8 patch of the picture; the glyph and the two colours that fit it best
# ---------------------------------------------------------------------------------------------
N = 8                                   # samples per cell, each way
FULL = (1 << (N * N)) - 1
GLYPHS = ("half", "quad", "blocks", "braille")
COLOR_DEPTHS = (24, 256, 16)


def rect(x0, x1, y0, y1):
    m = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            m |= 1 << (y * N + x)
    return m


def glyph_set(name):
    """list of (character, mask) for the named set; bit y*8+x of mask = pixel (x, y) is foreground."""
    g = [("▀", rect(0, 8, 0, 4)), ("▄", rect(0, 8, 4, 8))]                    # upper / lower half
    if name == "half":
        return g
    q = {"▘": rect(0, 4, 0, 4), "▝": rect(4, 8, 0, 4), "▖": rect(0, 4, 4, 8),
         "▗": rect(4, 8, 4, 8)}                                                       # quadrants
    ul, ur, ll, lr = (q[c] for c in "▘▝▖▗")
    g += [("▌", ul | ll), ("▐", ur | lr), ("▚", ul | lr), ("▞", ur | ll),
          ("▛", ul | ur | ll), ("▜", ul | ur | lr), ("▙", ul | ll | lr), ("▟", ur | ll | lr)]
    g += list(q.items())
    if name == "quad":
        return g
    if name == "blocks":
        for n, ch in enumerate("▏▎▍▌▋▊▉", 1):          # left n/8
            g.append((ch, rect(0, n, 0, 8)))
        for n, ch in enumerate("▁▂▃▄▅▆▇", 1):          # lower n/8
            g.append((ch, rect(0, 8, 8 - n, 8)))
        g += [("▔", rect(0, 8, 0, 1)), ("▕", rect(7, 8, 0, 8))]                  # upper / right eighth
        return g
    if name == "braille":
        dots = [(0, 0, 1), (0, 1, 2), (0, 2, 4), (1, 0, 8), (1, 1, 16), (1, 2, 32), (0, 3, 64), (1, 3, 128)]
        out = []
        for code in range(1, 255):
            m = 0
            for c, r, bit in dots:
                if code & bit:
                    m |= rect(4 * c, 4 * c + 4, 2 * r, 2 * r + 2)
            out.append((chr(0x2800 + code), m))
        return out
    raise ValueError("no glyph set '%s' (have: %s)" % (name, ", ".join(GLYPHS)))


def partitions(glyphs):
    """Group glyphs that split the cell the same way (a glyph and its complement): [(rep_mask, {mask: char})]."""
    by = {}
    for ch, m in glyphs:
        if m in (0, FULL):
            continue
        by.setdefault(min(m, FULL ^ m), {})[m] = ch
    return sorted(by.items())


def patches(rgba, tw, th):
    """RGBA picture (uint8 (H, W, 4)) -> (pm, al): premultiplied colour (th, tw, 3), 0..255, and alpha (th, tw), 0..1, area-
    averaged down to (or point-sampled up to) a grid of tw x th samples."""
    a = np.asarray(rgba).astype(np.float32)
    al = a[..., 3] / 255.0
    arr = np.concatenate([a[..., :3] * al[..., None], al[..., None]], axis=2)           # premultiplied
    for axis, new in ((0, th), (1, tw)):
        n = arr.shape[axis]
        if new <= n:
            edges = (np.arange(new + 1) * n // new)
            arr = np.add.reduceat(arr, edges[:-1], axis=axis) / np.diff(edges).reshape((-1, 1, 1) if axis == 0 else (1, -1, 1))
        else:
            idx = np.minimum(((np.arange(new) + 0.5) * n / new).astype(int), n - 1)
            arr = np.take(arr, idx, axis=axis)
    return arr[..., :3], arr[..., 3]


def fit(pm, al, parts, bg, rows, cols):
    """For every cell choose a partition.  Returns rows x cols entries (part_index or -1 for flat, fg_pm[3], fg_a, bg_pm[3],
    bg_a), 'fg' being the rep_mask side."""
    bgc = np.array(bg, np.float32)
    pm = np.asarray(pm, np.float32)
    al = np.asarray(al, np.float32)
    comp = pm + (1.0 - al[..., None]) * bgc                    # composited over bg: what the eye sees

    def cells(a):                                              # (rows*cols, 64, ...) in the sample order y*8+x
        s = a.shape
        t = a.reshape((rows, N, cols, N) + s[2:])
        t = np.swapaxes(t, 1, 2)
        return t.reshape((rows * cols, N * N) + s[2:])
    C, P, A = cells(comp), cells(pm), cells(al)
    Mv = np.array([[m >> i & 1 for i in range(N * N)] for m, _ in parts], np.float32)       # (G, 64)
    n1 = Mv.sum(1)
    n0 = N * N - n1
    tot = C.sum(1)
    flat = (tot ** 2).sum(-1) / (N * N)
    best = np.empty(len(C), int)
    for s in range(0, len(C), 1024):
        c = C[s:s + 1024]
        sf = np.einsum("gp,npc->ngc", Mv, c)
        sb = c.sum(1)[:, None, :] - sf
        score = (sf ** 2 / n1[None, :, None] + sb ** 2 / n0[None, :, None]).sum(-1)
        g = score.argmax(1)
        top = score[np.arange(len(c)), g]
        best[s:s + 1024] = np.where(top > flat[s:s + 1024] + 2.0, g, -1)
    sel = Mv[np.maximum(best, 0)] * (best >= 0)[:, None]
    sel = np.where((best >= 0)[:, None], sel, 1.0)             # flat: everything is "fg"
    fgpm = np.einsum("np,npc->nc", sel, P)
    fga = (sel * A).sum(1)
    bgpm = P.sum(1) - fgpm
    bga = A.sum(1) - fga
    return [(int(best[i]), fgpm[i], float(fga[i]), bgpm[i], float(bga[i])) for i in range(len(C))]


_ANSI16 = [(0, 0, 0), (170, 0, 0), (0, 170, 0), (170, 85, 0), (0, 0, 170), (170, 0, 170), (0, 170, 170),
           (170, 170, 170), (85, 85, 85), (255, 85, 85), (85, 255, 85), (255, 255, 85), (85, 85, 255),
           (255, 85, 255), (85, 255, 255), (255, 255, 255)]
_LEVELS = (0, 95, 135, 175, 215, 255)


def _d2(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def _near256(c):
    ci = [min(range(6), key=lambda i: abs(_LEVELS[i] - v)) for v in c]
    cube = tuple(_LEVELS[i] for i in ci)
    gi = min(range(24), key=lambda i: abs(8 + 10 * i - sum(c) / 3.0))
    grey = (8 + 10 * gi,) * 3
    if _d2(c, grey) < _d2(c, cube):
        return 232 + gi
    return 16 + 36 * ci[0] + 6 * ci[1] + ci[2]


def sgr(rgb, depth, bg):
    """SGR parameter string for a colour (None = the terminal's default)."""
    if rgb is None:
        return "49" if bg else "39"
    c = tuple(int(round(min(255, max(0, v)))) for v in rgb)
    if depth == 24:
        return "%d;2;%d;%d;%d" % (48 if bg else 38, c[0], c[1], c[2])
    if depth == 256:
        return "%d;5;%d" % (48 if bg else 38, _near256(c))
    i = min(range(16), key=lambda k: _d2(c, _ANSI16[k]))
    return str((100 if bg else 90) + i - 8) if i >= 8 else str((40 if bg else 30) + i)


def ansi_size(w, h, cols=None, rows=None, aspect=2.0, term_cols=80, term_rows=24):
    """(cols, rows) in characters for a w x h picture: what was asked for (negative = that many fewer than the terminal), else
    its own size at 8 pixels a character, at most the terminal's width; the picture's shape is kept (aspect = cell height / width)."""
    if cols is not None and cols <= 0:
        cols = max(1, term_cols + cols)
    if rows is not None and rows <= 0:
        rows = max(1, term_rows + rows)
    if cols is None and rows is None:
        cols = max(1, min(term_cols, int(round(w / 8.0))))
    if cols is not None and rows is not None:
        rows = max(1, min(rows, int(round(cols * h / float(w) / aspect))))
        cols = max(1, min(cols, int(round(rows * w / float(h) * aspect))))
    elif cols is not None:
        rows = max(1, int(round(cols * h / float(w) / aspect)))
    else:
        cols = max(1, int(round(rows * w / float(h) * aspect)))
    return cols, rows


def ansi_lines(rgba, cols, rows, glyphs="blocks", colors=24, background=None):
    """The picture as `rows` lines (bytes, no newline) of coloured Unicode text, `cols` characters wide.  background: an
    (r, g, b) to fill transparent areas with, or None to leave the terminal's own background showing."""
    if colors not in COLOR_DEPTHS:
        raise ValueError("colors is 24, 256 or 16")
    parts = partitions(glyph_set(glyphs))
    pm, al = patches(rgba, cols * N, rows * N)
    bg = background or (0, 0, 0)
    if background is not None:                    # composite once, so alpha is 1 everywhere from here on
        pm = np.asarray(pm, np.float32) + (1.0 - np.asarray(al, np.float32))[..., None] * np.array(bg, np.float32)
        al = np.ones_like(al)
    cells = fit(pm, al, parts, bg, rows, cols)
    lines = []
    see = 0.25                                    # below this alpha a side counts as transparent
    for cy in range(rows):
        cur = ["39", "49"]                        # SGR strings in force after a reset: fg, bg
        buf = []
        for cx in range(cols):
            best, fgpm, fga, bgpm, bga = cells[cy * cols + cx]
            if best < 0:                          # one colour
                a = fga / float(N * N)
                ch = " "
                fg = None
                bgc = None if a < see else [v / fga for v in fgpm]
            else:
                rep, chars = parts[best]
                n1 = bin(rep).count("1")
                fa, ba = fga / n1, bga / (N * N - n1)
                comp = FULL ^ rep
                # orientation: the more transparent side should be the background
                if rep in chars and (comp not in chars or fa >= ba):
                    ch, side_fg = chars[rep], (fgpm, fga, fa, bgpm, bga, ba)
                else:
                    ch, side_fg = chars[comp], (bgpm, bga, ba, fgpm, fga, fa)
                fpm, fa_sum, fa_frac, bpm, ba_sum, ba_frac = side_fg
                if fa_frac < see and ba_frac < see:
                    ch, fg, bgc = " ", None, None
                else:
                    fg = [v / fa_sum for v in fpm] if fa_sum > 1e-6 else [0, 0, 0]
                    bgc = None if ba_frac < see else [v / ba_sum for v in bpm]
            want = [sgr(fg, colors, False) if (ch != " " and fg is not None) else cur[0], sgr(bgc, colors, True)]
            change = [p for p, c in zip(want, cur) if p != c]
            if change:
                buf.append("\x1b[" + ";".join(change) + "m")
                cur = want
            buf.append(ch)
        buf.append("\x1b[0m")
        lines.append("".join(buf).encode("utf-8"))
    return lines


def ansi_art(rgba, cols, rows, glyphs="blocks", colors=24, background=None):
    """ansi_lines() as one block of bytes, a newline after every line (what `cat` shows)."""
    return b"".join(line + b"\n" for line in ansi_lines(rgba, cols, rows, glyphs, colors, background))


# ---------------------------------------------------------------------------------------------
# Tektronix 4010 / 4014: vectors.  Bright means ink.
# ---------------------------------------------------------------------------------------------
TEK_W, TEK_H = 1024, 780                        # the 4010's addressing; the 4014 accepts it too
GS, FS, US, ESC = b"\x1d", b"\x1c", b"\x1f", b"\x1b"
TEK_MODES = ("hatch", "dots", "contour")


class Tek(object):
    """An encoder of Tektronix coordinates, leaving out the high bytes that did not change."""

    def __init__(self):
        self.out = bytearray()
        self.hy = self.hx = None

    def addr(self, x, y):
        x = min(TEK_W - 1, max(0, int(round(x))))
        y = min(TEK_H - 1, max(0, int(round(y))))
        if y & 31 == 31:
            y -= 1                              # LoY 0x7F is DEL, which terminals discard
        hy, ly, hx, lx = 0x20 | (y >> 5), 0x60 | (y & 31), 0x20 | (x >> 5), 0x40 | (x & 31)
        o = self.out
        if hy != self.hy:
            o.append(hy)
        o.append(ly)
        if hx != self.hx:
            o.append(hx)
        o.append(lx)
        self.hy, self.hx = hy, hx

    def polyline(self, pts):
        """Beam off to the first point, then draw to the rest."""
        self.out += GS
        self.hy = self.hx = None
        for p in pts:
            self.addr(*p)

    def points(self, pts):
        self.out += FS
        self.hy = self.hx = None
        for p in pts:
            self.addr(*p)

    def end(self):
        self.out += US


def brightness(rgba):
    """RGBA uint8 (H, W, 4) -> float64 (H, W) 0..1; transparent pixels count as black, which is no ink on a Tek screen."""
    a = np.asarray(rgba).astype(np.float64)
    return (0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]) / 255.0 * (a[..., 3] / 255.0)


def tone(grid, invert=False, gamma=1.0, auto=True):
    """Brightness 0..1 -> ink density.  With `auto`, stretch so that the brightest few per cent of the lit pixels reach 1
    (rainbow faces are mid-grey otherwise and hatch too thinly)."""
    scale = 1.0
    if auto:
        lit = np.sort(grid[grid > 0.02])
        if len(lit):
            scale = 1.0 / max(0.05, float(lit[int(len(lit) * 0.97)]))
    v = np.minimum(1.0, grid * scale)
    if invert:
        v = 1.0 - v
    return v ** gamma


def tek_map(w, h, scale=1.0):
    """Source pixel -> Tek coordinates (fit, centre, y up)."""
    s = min((TEK_W - 1.0) / w, (TEK_H - 1.0) / h) * scale
    ox = (TEK_W - w * s) / 2.0
    oy = (TEK_H - h * s) / 2.0
    return s, (lambda x, y: (ox + x * s, TEK_H - 1 - (oy + y * s)))


def do_hatch(w, h, g, tek, scale=1.0, lines=4, pitch=2.0):
    """Horizontal scan lines, denser where the picture is brighter (an engraving)."""
    s, m = tek_map(w, h, scale)
    k = lines
    thr = [(j + 0.5) / k for j in range(k)]
    order = sorted(range(k), key=lambda j: bin(j).count("1") * 100 - j * 0 + (j & -j))     # spread the levels
    step = max(1, int(round(pitch / s)))
    for y in range(0, h, step):
        t = thr[order[(y // step) % k]]
        on = g[y] > t
        if not on.any():
            continue
        d = np.diff(np.concatenate(([0], on.astype(np.int8), [0])))
        for x0, x1 in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]):               # runs [x0, x1)
            a, b = m(int(x0), y), m(int(x1) - 1, y)
            tek.polyline([a, b] if b != a else [a, (a[0] + 1, a[1])])


def do_dots(w, h, g, tek, scale=1.0):
    """Point-plot mode, Floyd-Steinberg dithered."""
    s, m = tek_map(w, h, scale)
    err = [row[:] for row in g.tolist()]
    pts = []
    for y in range(h):
        row = err[y]
        nxt = err[y + 1] if y + 1 < h else None
        rng = range(w) if y % 2 == 0 else range(w - 1, -1, -1)       # serpentine
        d = 1 if y % 2 == 0 else -1
        for x in rng:
            old = row[x]
            new = 1.0 if old > 0.5 else 0.0
            e = old - new
            if new:
                pts.append(m(x, y))
            if 0 <= x + d < w:
                row[x + d] += e * 7 / 16.0
            if nxt is not None:
                if 0 <= x - d < w:
                    nxt[x - d] += e * 3 / 16.0
                nxt[x] += e * 5 / 16.0
                if 0 <= x + d < w:
                    nxt[x + d] += e * 1 / 16.0
    tek.points(pts)


# marching squares: cell corners tl,tr,br,bl -> list of (edgeA, edgeB); edges 0=top 1=right 2=bottom 3=left
_MS = {0: [], 15: [], 1: [(2, 3)], 14: [(2, 3)], 2: [(1, 2)], 13: [(1, 2)], 3: [(1, 3)], 12: [(1, 3)],
       4: [(0, 1)], 11: [(0, 1)], 5: [(0, 3), (1, 2)], 10: [(0, 1), (2, 3)], 6: [(0, 2)], 9: [(0, 2)],
       7: [(0, 3)], 8: [(0, 3)]}


def contours(g, w, h, level):
    """Closed/open polylines (in doubled pixel coordinates) of the iso-line g == level."""
    inside = g > level
    if w < 2 or h < 2:
        return []
    case = ((inside[:-1, :-1] * 8) | (inside[:-1, 1:] * 4) | (inside[1:, 1:] * 2) | (inside[1:, :-1] * 1))
    adj = {}

    def edge_pt(cx, cy, e):
        return {0: (2 * cx + 1, 2 * cy), 1: (2 * cx + 2, 2 * cy + 1),
                2: (2 * cx + 1, 2 * cy + 2), 3: (2 * cx, 2 * cy + 1)}[e]

    ys, xs = np.nonzero((case != 0) & (case != 15))                     # only the cells the line passes through
    order = np.lexsort((xs, ys))                                        # (rows first, as the original scanned them)
    for cy, cx in zip(ys[order].tolist(), xs[order].tolist()):
        for e1, e2 in _MS[int(case[cy, cx])]:
            p, q = edge_pt(cx, cy, e1), edge_pt(cx, cy, e2)
            adj.setdefault(p, []).append(q)
            adj.setdefault(q, []).append(p)
    seen = set()
    lines = []
    ends = [p for p, n in adj.items() if len(n) == 1]
    for start in ends + list(adj):
        if start in seen:
            continue
        line = [start]
        seen.add(start)
        prev, cur = None, start
        while True:
            nxt = None
            for c in adj[cur]:
                if c not in seen or (c == start and len(line) > 2 and c != prev):
                    nxt = c
                    break
            if nxt is None:
                break
            line.append(nxt)
            if nxt == start:
                break
            seen.add(nxt)
            prev, cur = cur, nxt
        if len(line) > 1:
            lines.append(line)
    return lines


def simplify(pts, tol):
    """Douglas-Peucker, iterative."""
    if len(pts) < 3 or tol <= 0:
        return pts
    if pts[0] == pts[-1] and len(pts) > 3:        # closed loop: no baseline, so split at the farthest point
        (x0, y0) = pts[0]
        f = max(range(1, len(pts) - 1), key=lambda i: (pts[i][0] - x0) ** 2 + (pts[i][1] - y0) ** 2)
        return simplify(pts[:f + 1], tol) + simplify(pts[f:], tol)[1:]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        L = (dx * dx + dy * dy) ** 0.5 or 1.0
        far, fi = 0.0, None
        for i in range(a + 1, b):
            d = abs(dy * (pts[i][0] - x1) - dx * (pts[i][1] - y1)) / L
            if d > far:
                far, fi = d, i
        if fi is not None and far > tol:
            keep[fi] = True
            stack += [(a, fi), (fi, b)]
    return [p for p, k in zip(pts, keep) if k]


def do_contour(w, h, g, tek, scale=1.0, levels=5, tol=1.2):
    """The outline of everything lit, then iso-lines through the lit pixels' brightness (at quantiles, so each line encloses a
    similar share of the picture): a topographic map."""
    s, m = tek_map(w, h, scale)
    lit = np.sort(g[g > 0.02])
    lv = [float(lit[int(len(lit) * (j + 1.0) / (levels + 1))]) for j in range(levels)] if len(lit) else []
    mask = np.where(g > 0.02, 1.0, 0.0)
    for field, level in [(mask, 0.5)] + [(g, v) for v in lv]:
        for line in contours(field, w, h, level):
            pts = simplify(line, tol)
            tek.polyline([m(x / 2.0, y / 2.0) for x, y in pts])


def tek_raster(rgba, mode="hatch", invert=False, gamma=1.0, auto=True, scale=1.0, lines=4, pitch=2.0, levels=5, tol=1.2):
    """Pixels -> Tektronix vectors (bytes ending in US, without the erase or the mode switch: see tek_emit).  The picture is
    brought down to what the screen can show first (1024 x 780).  Returns (stream, width, height) of what was vectorised."""
    if mode not in TEK_MODES:
        raise ValueError("no Tektronix mode '%s' (have: %s)" % (mode, ", ".join(TEK_MODES)))
    rgba = np.asarray(rgba)
    h, w = rgba.shape[:2]
    if w > TEK_W or h > TEK_H:                                   # no use giving it more than 1024 x 780
        from PIL import Image
        k = min(TEK_W / float(w), TEK_H / float(h))
        w, h = max(1, int(w * k)), max(1, int(h * k))
        rgba = np.asarray(Image.fromarray(np.ascontiguousarray(rgba), "RGBA").resize((w, h), Image.BOX))
    g = tone(brightness(rgba), invert, gamma, auto)
    tek = Tek()
    if mode == "hatch":
        do_hatch(w, h, g, tek, scale, lines, pitch)
    elif mode == "dots":
        do_dots(w, h, g, tek, scale)
    else:
        do_contour(w, h, g, tek, scale, levels, tol)
    tek.end()
    return bytes(tek.out), w, h


def vector_paths(pic, frame=0):
    """The paths of a BIF frame as polylines in canvas units: [(N, 2) float arrays], layer transforms applied, closed paths
    closed.  Only vector layers that are drawn (not hidden, not a record of the source) count."""
    out = []
    for L in pic.frames[frame].layers:
        if L.kind != "vector" or not L.get("visible", True) or L.get("role") == "source":
            continue
        if float(L.get("opacity", 1.0)) <= 0:
            continue
        xy, st = L.arrays["xy"].astype(np.float64), L.arrays["start"].astype(np.int64)
        flags = L.arrays["flags"] if "flags" in L.arrays else np.zeros(len(st) - 1, "|u1")
        t = L.get("transform")
        a, b, c, d, e, f = [float(v) for v in t] if t else (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        X = a * xy[:, 0] + c * xy[:, 1] + e
        Y = b * xy[:, 0] + d * xy[:, 1] + f
        for i in range(len(st) - 1):
            s0, s1 = int(st[i]), int(st[i + 1])
            if s1 <= s0:
                continue
            pts = np.stack([X[s0:s1], Y[s0:s1]], 1)
            if (int(flags[i]) & 1) and len(pts) > 2:
                pts = np.vstack([pts, pts[:1]])
            out.append(pts)
    return out


def tek_vectors(pic, frame=0, scale=1.0):
    """A BIF's own paths as Tektronix strokes, or None if the frame has no vector layer (rasters: use tek_raster).  A stroke
    is its centre line and a filled letter its outline; there is no colour and no thickness on a Tek screen."""
    paths = vector_paths(pic, frame)
    if not paths:
        return None
    W, H = float(pic.width), float(pic.height) * float(pic.unit_aspect)
    s = min((TEK_W - 1.0) / W, (TEK_H - 1.0) / H) * scale
    ox, oy = (TEK_W - W * s) / 2.0, (TEK_H - H * s) / 2.0
    ua = float(pic.unit_aspect)
    tek = Tek()
    for pts in paths:
        pp = [(ox + x * s, TEK_H - 1 - (oy + y * ua * s)) for x, y in pts.tolist()]
        if len(pp) == 1:
            pp.append((pp[0][0] + 1, pp[0][1]))                    # a lone dot: a short stroke
        tek.polyline(pp)
    tek.end()
    return bytes(tek.out)


def tek_emit(body, out, xterm=False, erase=True, wait=None):
    """Write a Tek stream.  xterm=True switches an xterm into Tek mode (ESC [ ? 38 h), draws, waits (wait() is called; the
    default waits for Enter on the terminal) and switches back (ESC ETX), which hides the Tek window."""
    pre = ESC + b"\x0c" if erase else b""
    if xterm:
        out.write(ESC + b"[?38h" + pre + body)
        out.flush()
        if wait is None:
            try:
                with open("/dev/tty", "r") as tty:
                    tty.readline()
            except (OSError, IOError):
                pass
        else:
            wait()
        out.write(ESC + b"\x03")                               # back to the VT window
    else:
        out.write(pre + body)
    out.flush()
