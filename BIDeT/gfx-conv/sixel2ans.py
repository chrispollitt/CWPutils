#!/usr/bin/env python3
"""sixel2ans - turn a SIXEL (or PNG/JPEG...) picture into coloured Unicode text, ANSI art.

    bidet3d --transparent --force "Hello" | sixel2ans
    sixel2ans -x 60 photo.jpg
    sixel2ans -C 256 -g half picture.png > picture.ans       # a file you can `cat` anywhere

The successor to img2ans (csdvrx and Justine Tunney's derasterize, ISC licence), which BIDeT
v1 used for terminals without SIXEL.  Each character cell is an 8x8 patch of the picture; the
program picks the block glyph and the two colours (foreground, background) that fit the patch
best.  Compared with the original:

  * nothing to compile and no ImageMagick: Python 3, and numpy if you have it (faster; without
    it the work is done in plain Python, fine for small pictures);
  * reads SIXEL as well as PNG/JPEG (via Pillow), so it can sit at the end of a bidet3d pipe;
  * transparency is kept: transparent areas show the terminal's own background;
  * 24-bit colour, or 256 or 16 colours for terminals that need it;
  * glyph sets from plain half blocks to eighths and Braille; sizes from the terminal.
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sixeldec  # noqa: E402

try:
    import numpy as np
except ImportError:
    np = None

N = 8                                   # samples per cell, each way
FULL = (1 << (N * N)) - 1


def rect(x0, x1, y0, y1):
    m = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            m |= 1 << (y * N + x)
    return m


def glyph_set(name):
    """list of (character, mask) for the named set; bit y*8+x of mask = pixel (x, y) is foreground."""
    g = [("▀", rect(0, 8, 0, 4)), ("▄", rect(0, 8, 4, 8))]                  # upper / lower half
    if name == "half":
        return g
    q = {"▘": rect(0, 4, 0, 4), "▝": rect(4, 8, 0, 4), "▖": rect(0, 4, 4, 8),
         "▗": rect(4, 8, 4, 8)}                                                   # quadrants
    ul, ur, ll, lr = (q[c] for c in "▘▝▖▗")
    g += [("▌", ul | ll), ("▐", ur | lr), ("▚", ul | lr), ("▞", ur | ll),
          ("▛", ul | ur | ll), ("▜", ul | ur | lr), ("▙", ul | ll | lr), ("▟", ur | ll | lr)]
    g += list(q.items())
    if name == "quad":
        return g
    if name == "blocks":
        for n, ch in enumerate("▏▎▍▌▋▊▉", 1):      # left n/8
            g.append((ch, rect(0, n, 0, 8)))
        for n, ch in enumerate("▁▂▃▄▅▆▇", 1):      # lower n/8
            g.append((ch, rect(0, 8, 8 - n, 8)))
        g += [("▔", rect(0, 8, 0, 1)), ("▕", rect(7, 8, 0, 8))]             # upper / right eighth
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
    raise ValueError(name)


def partitions(glyphs):
    """Group glyphs that split the cell the same way (a glyph and its complement).
    Returns a list of (rep_mask, {mask: char})."""
    by = {}
    for ch, m in glyphs:
        if m in (0, FULL):
            continue
        by.setdefault(min(m, FULL ^ m), {})[m] = ch
    return sorted(by.items())


def mask_bits(m):
    return [i for i in range(N * N) if m >> i & 1]


# --------------------------------------------------------------------------
# Picture -> cell patches
# --------------------------------------------------------------------------
def patches(w, h, rgba, tw, th):
    """RGBA picture -> (pm, al): premultiplied colour and alpha for a (th x tw) sample grid, as
    numpy arrays pm[y][x][3] (0..255 scale) and al[y][x] (0..1), or nested lists without numpy."""
    if np is not None:
        a = np.frombuffer(rgba, np.uint8).reshape(h, w, 4).astype(np.float32)
        al = a[..., 3] / 255.0
        arr = np.concatenate([a[..., :3] * al[..., None], al[..., None]], axis=2)       # premultiplied
        for axis, new in ((0, th), (1, tw)):
            n = arr.shape[axis]
            if new <= n:
                edges = (np.arange(new + 1) * n // new)
                arr = np.add.reduceat(arr, edges[:-1], axis=axis) / np.diff(edges).reshape(
                    (-1, 1, 1) if axis == 0 else (1, -1, 1))
            else:
                idx = np.minimum(((np.arange(new) + 0.5) * n / new).astype(int), n - 1)
                arr = np.take(arr, idx, axis=axis)
        return arr[..., :3], arr[..., 3]
    # plain Python: area average, one axis at a time
    px = [[(rgba[4 * (y * w + x)] * rgba[4 * (y * w + x) + 3] / 255.0,
            rgba[4 * (y * w + x) + 1] * rgba[4 * (y * w + x) + 3] / 255.0,
            rgba[4 * (y * w + x) + 2] * rgba[4 * (y * w + x) + 3] / 255.0,
            rgba[4 * (y * w + x) + 3] / 255.0) for x in range(w)] for y in range(h)]

    def shrink(line, new):
        n = len(line)
        if new <= n:
            edges = [i * n // new for i in range(new + 1)]
            out = []
            for k in range(new):
                seg = line[edges[k]:edges[k + 1]]
                out.append(tuple(sum(c[j] for c in seg) / len(seg) for j in range(4)))
            return out
        return [line[min(n - 1, int((i + 0.5) * n / new))] for i in range(new)]

    px = [shrink(r, tw) for r in px]
    cols = [shrink([px[y][x] for y in range(h)], th) for x in range(tw)]
    pm = [[cols[x][y][:3] for x in range(tw)] for y in range(th)]
    al = [[cols[x][y][3] for x in range(tw)] for y in range(th)]
    return pm, al


# --------------------------------------------------------------------------
# Glyph + colour choice
# --------------------------------------------------------------------------
def fit(pm, al, parts, bg, rows, cols, opaque):
    """For every cell choose a partition.  Returns rows x cols entries
    (part_index or -1 for flat, fg_pm[3], fg_a, bg_pm[3], bg_a) where 'fg' is the rep_mask side."""
    bgc = np.array(bg, np.float32) if np is not None else bg
    out = []
    if np is not None:
        pm = np.asarray(pm, np.float32)
        al = np.asarray(al, np.float32)
        comp = pm + (1.0 - al[..., None]) * bgc                  # composited over bg: what the eye sees
        # cells: (rows*cols, 64, ...) with the sample order y*8+x
        def cells(a):
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
        sel = np.where((best >= 0)[:, None], sel, 1.0)            # flat: everything is "fg"
        fgpm = np.einsum("np,npc->nc", sel, P)
        fga = (sel * A).sum(1)
        bgpm = P.sum(1) - fgpm
        bga = A.sum(1) - fga
        for i in range(len(C)):
            out.append((int(best[i]), fgpm[i], float(fga[i]), bgpm[i], float(bga[i])))
        return out
    # plain Python
    idxs = [mask_bits(m) for m, _ in parts]
    flat_idx = list(range(N * N))
    for cy in range(rows):
        for cx in range(cols):
            P, A, C = [], [], []
            for y in range(N):
                for x in range(N):
                    p = pm[cy * N + y][cx * N + x]
                    a = al[cy * N + y][cx * N + x]
                    P.append(p)
                    A.append(a)
                    C.append(tuple(p[k] + (1 - a) * bg[k] for k in range(3)))
            tot = [sum(c[k] for c in C) for k in range(3)]
            best, bests = -1, sum(t * t for t in tot) / (N * N) + 2.0
            for gi, ix in enumerate(idxs):
                n1 = len(ix)
                sf = [sum(C[i][k] for i in ix) for k in range(3)]
                s = sum(sf[k] ** 2 / n1 + (tot[k] - sf[k]) ** 2 / (N * N - n1) for k in range(3))
                if s > bests:
                    best, bests = gi, s
            ix = idxs[best] if best >= 0 else flat_idx
            fgpm = [sum(P[i][k] for i in ix) for k in range(3)]
            fga = sum(A[i] for i in ix)
            out.append((best, fgpm, fga, [sum(p[k] for p in P) - fgpm[k] for k in range(3)], sum(A) - fga))
    return out


# --------------------------------------------------------------------------
# Colour output
# --------------------------------------------------------------------------
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


def render(w, h, rgba, args):
    """-> list of text lines (bytes) for the picture."""
    glyphs = glyph_set(args.glyphs)
    parts = partitions(glyphs)
    cols, rows = args.cols, args.rows
    pm, al = patches(w, h, rgba, cols * N, rows * N)
    opaque = args.background is not None
    bg = args.background or (0, 0, 0)
    if opaque:                                    # composite once, so alpha is 1 everywhere from here on
        if np is not None:
            pm = np.asarray(pm, np.float32) + (1.0 - np.asarray(al, np.float32))[..., None] * np.array(bg, np.float32)
            al = np.ones_like(al)
        else:
            pm = [[tuple(p[k] + (1 - a) * bg[k] for k in range(3)) for p, a in zip(pr, ar)] for pr, ar in zip(pm, al)]
            al = [[1.0] * len(r) for r in al]
    cells = fit(pm, al, parts, bg, rows, cols, opaque)
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
            want = [sgr(fg, args.colors, False) if (ch != " " and fg is not None) else cur[0],
                    sgr(bgc, args.colors, True)]
            change = [p for p, c in zip(want, cur) if p != c]
            if change:
                buf.append("\x1b[" + ";".join(change) + "m")
                cur = want
            buf.append(ch)
        buf.append("\x1b[0m")
        lines.append("".join(buf).encode("utf-8"))
    return lines


def term_size():
    try:
        sz = os.get_terminal_size(sys.stderr.fileno())
        return sz.columns, sz.lines
    except OSError:
        sz = shutil.get_terminal_size((80, 24))
        return sz.columns, sz.lines


def parse_colour(s):
    names = {"black": (0, 0, 0), "white": (255, 255, 255)}
    if s.lower() in names:
        return names[s.lower()]
    s = s.lstrip("#")
    try:
        if "," in s:
            c = tuple(int(v) for v in s.split(","))
        elif len(s) == 6:
            c = (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        else:
            raise ValueError
        return c
    except ValueError:
        sys.exit("sixel2ans: bad colour '%s' (use #rrggbb, r,g,b, black or white)" % s)


def ans_args(**kw):
    """The option set convert() reads, with the command line's defaults."""
    a = argparse.Namespace(cols=None, rows=None, aspect=2.0, glyphs="blocks", colors=24, background=None)
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def convert(data, args=None):
    """SIXEL or image bytes -> the ANSI art, as bytes (lines end in newline)."""
    args = args or ans_args()
    w, h, rgba = sixeldec.load_picture(data)
    tcols, trows = term_size()
    cols, rows = args.cols, args.rows
    if cols is not None and cols <= 0:
        cols = max(1, tcols + cols)
    if rows is not None and rows <= 0:
        rows = max(1, trows + rows)
    if cols is None and rows is None:
        cols = max(1, min(tcols, int(round(w / 8.0))))
    # keep the picture's shape: fit inside the box that was asked for
    if cols is not None and rows is not None:
        rows = max(1, min(rows, int(round(cols * h / float(w) / args.aspect))))
        cols = max(1, min(cols, int(round(rows * w / float(h) * args.aspect))))
    elif cols is not None:
        rows = max(1, int(round(cols * h / float(w) / args.aspect)))
    else:
        cols = max(1, int(round(rows * w / float(h) * args.aspect)))
    args = argparse.Namespace(**vars(args))
    args.cols, args.rows = cols, rows
    return b"".join(line + b"\n" for line in render(w, h, rgba, args))


def main():
    ap = argparse.ArgumentParser(description="SIXEL / image -> ANSI art (Unicode block characters)")
    ap.add_argument("file", nargs="?", help="SIXEL or image file (default: standard input)")
    ap.add_argument("-x", "--cols", type=int,
                    help="width in characters; negative = that many fewer than the terminal (default: the "
                         "picture's own size at 8 pixels a character, at most the terminal's width)")
    ap.add_argument("-y", "--rows", type=int, help="height in characters; negative = that many fewer than the terminal")
    ap.add_argument("-a", "--aspect", type=float, default=2.0,
                    help="character cell height / width (default 2.0)")
    ap.add_argument("-g", "--glyphs", choices=["half", "quad", "blocks", "braille"], default="blocks",
                    help="characters to use: half blocks; plus quadrants; plus eighths (default); Braille dots")
    ap.add_argument("-C", "--colors", type=int, choices=[24, 256, 16], default=24,
                    help="colour depth: 24-bit (default), 256 or 16 colours")
    ap.add_argument("-b", "--background", metavar="COLOR",
                    help="fill transparent areas with this colour (#rrggbb, r,g,b, black, white) instead of "
                         "leaving the terminal's own background showing")
    args = ap.parse_args()
    if args.background:
        args.background = parse_colour(args.background)

    out = sys.stdout.buffer
    out.write(convert(sixeldec.read_input(args.file), args))
    out.flush()


if __name__ == "__main__":
    main()
