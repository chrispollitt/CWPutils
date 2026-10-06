#!/usr/bin/env python3
"""sixel2tek - turn a SIXEL picture (or any image Pillow can read) into Tektronix 4010/4014
vector graphics, for xterm's Tek mode.

SIXEL is raster, Tektronix is vector, so the picture is vectorised.  Bright = ink:

  hatch    horizontal scan lines, denser where the picture is brighter (engraving look)
  dots     point-plot mode, Floyd-Steinberg dithered
  contour  outlines of brightness levels (marching squares), like a topographic map

    bidet3d --force | sixel2tek --xterm            # in an xterm:  xterm -t   (or just ^MiddleClick -> Enter Tek Mode)
    sixel2tek -m contour picture.png > pic.tek     # then:  cat pic.tek   inside xterm's Tek window

Stdlib only for SIXEL input; Pillow is needed for PNG/JPEG input.  Python 3.5+.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sixeldec  # noqa: E402

VERSION = "0.1"
TEK_W, TEK_H = 1024, 780          # Tektronix 4010 addressing; 4014 accepts it too

GS, FS, US, ESC = b"\x1d", b"\x1c", b"\x1f", b"\x1b"


# --------------------------------------------------------------------------
# Picture -> brightness grid
# --------------------------------------------------------------------------
def load_brightness(data):
    """SIXEL or image bytes -> (w, h, rows) with rows[y][x] = brightness 0..1.  Transparent
    pixels count as black, which is no ink on a Tek screen."""
    w, h, rgba = sixeldec.load_picture(data)
    rows = []
    for y in range(h):
        base = y * w * 4
        row = []
        for x in range(w):
            r, g, b, a = rgba[base + 4 * x:base + 4 * x + 4]
            row.append((0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0 * (a / 255.0))
        rows.append(row)
    return w, h, rows


# --------------------------------------------------------------------------
# Tektronix encoder
# --------------------------------------------------------------------------
class Tek:
    def __init__(self):
        self.out = bytearray()
        self.hy = self.hx = self.lx = None

    def addr(self, x, y):
        """Append one 10-bit address, leaving out the high bytes that did not change."""
        x = min(TEK_W - 1, max(0, int(round(x))))
        y = min(TEK_H - 1, max(0, int(round(y))))
        if y & 31 == 31:
            y -= 1                      # LoY 0x7F is DEL, which terminals discard
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


# --------------------------------------------------------------------------
# Vectorisers
# --------------------------------------------------------------------------
def make_map(w, h, args):
    """Source pixel -> Tek coordinates (fit, centre, y up)."""
    s = min((TEK_W - 1.0) / w, (TEK_H - 1.0) / h) * args.scale
    ox = (TEK_W - w * s) / 2.0
    oy = (TEK_H - h * s) / 2.0
    return s, (lambda x, y: (ox + x * s, TEK_H - 1 - (oy + y * s)))


def tone(grid, args):
    """Brightness 0..1 -> ink density.  Unless --no-auto, stretch so the brightest few per cent
    of the lit pixels reach 1 (rainbow faces are mid-grey otherwise and hatch too thinly)."""
    inv = args.invert
    gam = args.gamma
    scale = 1.0
    if not args.no_auto:
        lit = sorted(v for r in grid for v in r if v > 0.02)
        if lit:
            scale = 1.0 / max(0.05, lit[int(len(lit) * 0.97)])
    return [[(min(1.0, v * scale) if not inv else 1.0 - min(1.0, v * scale)) ** gam for v in r] for r in grid]


def do_hatch(w, h, g, args, tek):
    s, m = make_map(w, h, args)
    k = args.lines
    # row j of every group of k draws where brightness exceeds t_j: brighter => more rows inked
    thr = [(j + 0.5) / k for j in range(k)]
    order = sorted(range(k), key=lambda j: bin(j).count("1") * 100 - j * 0 + (j & -j))   # spread the levels
    step = max(1, int(round(args.pitch / s)))
    for y in range(0, h, step):
        t = thr[order[(y // step) % k]]
        row = g[y]
        x = 0
        while x < w:
            if row[x] > t:
                x0 = x
                while x < w and row[x] > t:
                    x += 1
                a = m(x0, y)
                b = m(x - 1, y)
                tek.polyline([a, b] if b != a else [a, (a[0] + 1, a[1])])
            else:
                x += 1


def do_dots(w, h, g, args, tek):
    s, m = make_map(w, h, args)
    err = [row[:] for row in g]
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
    inside = [[v > level for v in r] for r in g]
    adj = {}

    def edge_pt(cx, cy, e):
        return {0: (2 * cx + 1, 2 * cy), 1: (2 * cx + 2, 2 * cy + 1),
                2: (2 * cx + 1, 2 * cy + 2), 3: (2 * cx, 2 * cy + 1)}[e]

    for cy in range(h - 1):
        a, b = inside[cy], inside[cy + 1]
        for cx in range(w - 1):
            case = (8 if a[cx] else 0) | (4 if a[cx + 1] else 0) | (2 if b[cx + 1] else 0) | (1 if b[cx] else 0)
            if case in (0, 15):
                continue
            for e1, e2 in _MS[case]:
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


def do_contour(w, h, g, args, tek):
    """The outline of everything lit, then iso-lines through the lit pixels' brightness
    (at quantiles, so each line encloses a similar share of the picture)."""
    s, m = make_map(w, h, args)
    lit = sorted(v for r in g for v in r if v > 0.02)
    levels = [lit[int(len(lit) * (j + 1.0) / (args.levels + 1))] for j in range(args.levels)] if lit else []
    mask = [[1.0 if v > 0.02 else 0.0 for v in r] for r in g]
    for field, lv in [(mask, 0.5)] + [(g, lv) for lv in levels]:
        for line in contours(field, w, h, lv):
            pts = simplify(line, args.simplify)
            tek.polyline([m(x / 2.0, y / 2.0) for x, y in pts])


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="SIXEL (or image) -> Tektronix 4010/4014 vector graphics")
    ap.add_argument("file", nargs="?", help="SIXEL or image file (default: stdin)")
    ap.add_argument("-m", "--mode", choices=["hatch", "dots", "contour"], default="hatch")
    ap.add_argument("-i", "--invert", action="store_true",
                    help="dark = ink (for a light-on-dark picture on a dark-on-light xterm -rv screen)")
    ap.add_argument("-g", "--gamma", type=float, default=1.0, help="brightness gamma (<1 brightens)")
    ap.add_argument("--no-auto", action="store_true", help="do not stretch the contrast")
    ap.add_argument("-s", "--scale", type=float, default=1.0, help="size relative to full screen (default 1)")
    ap.add_argument("-l", "--lines", type=int, default=4, help="hatch: tone levels (rows per group, default 4)")
    ap.add_argument("--pitch", type=float, default=2.0, help="hatch: spacing of scan lines in Tek units (default 2)")
    ap.add_argument("--levels", type=int, default=5, help="contour: number of brightness levels (default 5)")
    ap.add_argument("--simplify", type=float, default=1.2, help="contour: line simplification in half pixels (default 1.2)")
    ap.add_argument("--xterm", action="store_true",
                    help="switch xterm into Tek mode, draw, wait for Enter, switch back (output must be a terminal)")
    ap.add_argument("--no-erase", action="store_true", help="do not clear the Tek screen first")
    ap.add_argument("--stats", action="store_true", help="byte and shape counts on stderr")
    ap.add_argument("-v", "--version", action="store_true")
    args = ap.parse_args()
    if args.version:
        print("sixel2tek %s" % VERSION)
        return

    w, h, g = load_brightness(sixeldec.read_input(args.file))
    g = tone(g, args)
    tek = Tek()
    {"hatch": do_hatch, "dots": do_dots, "contour": do_contour}[args.mode](w, h, g, args, tek)
    tek.end()
    body = bytes(tek.out)
    if args.stats:
        print("%dx%d source -> %d bytes, %d strokes" % (w, h, len(body), body.count(GS) + body.count(FS)),
              file=sys.stderr)
    out = sys.stdout.buffer
    pre = b"" if args.no_erase else ESC + b"\x0c"
    if args.xterm:
        out.write(ESC + b"[?38h" + pre + body)
        out.flush()
        try:
            tty = open("/dev/tty", "r")
            tty.readline()
        except OSError:
            pass
        out.write(ESC + b"\x03")                  # back to the VT window
        out.flush()
    else:
        out.write(pre + body)


if __name__ == "__main__":
    main()
