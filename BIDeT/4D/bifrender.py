#!/usr/bin/env python3
"""bifrender: draw a BIF picture to pixels (the rendering model of BIF-SPEC.md section 8).

    import bif, bifrender
    pic = bif.load("x.bif")
    r = bifrender.render(pic, width=800)          # or scale=2.0 (pixels per canvas unit)
    r.alpha            float32 (H, W), coverage 0..1
    r.color            (r, g, b) when the whole picture is one colour, else uint8 (H, W, 3); straight alpha
    r.paper            the page colour to flatten onto (HEAD.background, a `paper` palette entry, or a guess)
    r.rgba()           uint8 (H, W, 4)        r.flatten()     uint8 (H, W, 3) on the paper

Vector layers are drawn the way unascii draws strokes: at `ss` times the size with an integer-width pen,
then box-filtered down.  Python 3.7+, Pillow 5.4+, numpy 1.16+.
"""
from __future__ import print_function

import math

import numpy as np
from PIL import Image, ImageDraw

import bif

DEFAULT_MAX_PIXELS = 24e6
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


# ---------------------------------------------------------------------------------------------
# A plane of pixels: coverage plus colour, colour being one value while the plane is one colour
# ---------------------------------------------------------------------------------------------
class Plane(object):
    """alpha (H, W) float32; color: None (nothing drawn yet), a (r, g, b) tuple (the same everywhere,
    which keeps single-colour art cheap and lets SIXEL use its line-art path), or (H, W, 3) float32.
    Straight (not premultiplied) alpha."""

    def __init__(self, W, H):
        self.W, self.H = W, H
        self.alpha = np.zeros((H, W), np.float32)
        self.color = None

    def _expand(self):
        if not isinstance(self.color, np.ndarray):
            c = np.empty((self.H, self.W, 3), np.float32)
            c[:] = self.color if self.color is not None else (0, 0, 0)
            self.color = c

    def over_patch(self, x0, y0, a, col):
        """Source-over a window: a (h, w) coverage in colour col ((r, g, b) or (h, w, 3))."""
        h, w = a.shape
        win = (slice(y0, y0 + h), slice(x0, x0 + w))
        ab = self.alpha[win]
        uniform = isinstance(col, tuple)
        if uniform and (self.color is None or (isinstance(self.color, tuple) and self.color == col)):
            self.color = col
            self.alpha[win] = a + ab * (1.0 - a)
            return
        self._expand()
        ao = a + ab * (1.0 - a)
        cs = np.asarray(col, np.float32)
        num = a[..., None] * cs + ((1.0 - a) * ab)[..., None] * self.color[win]
        self.color[win] = np.where(ao[..., None] > 1e-6, num / np.maximum(ao, 1e-6)[..., None], self.color[win])
        self.alpha[win] = ao

    def compose(self, top, blend="normal", opacity=1.0):
        """Draw plane `top` over this one, in place."""
        if top.color is None:
            return
        a_s = top.alpha * np.float32(opacity) if opacity != 1.0 else top.alpha
        if self.color is None:
            if blend == "erase":
                return
            self.alpha[:] = a_s
            self.color = top.color if isinstance(top.color, tuple) else top.color.copy()
            return
        a_b = self.alpha
        if blend == "erase":
            self.alpha = a_b * (1.0 - a_s)
            return
        if (blend == "normal" and isinstance(self.color, tuple) and self.color == top.color
                and isinstance(top.color, tuple)):
            self.alpha = a_s + a_b * (1.0 - a_s)
            return
        cb = np.asarray(self.color, np.float32)
        cs = np.asarray(top.color, np.float32)
        if cb.ndim == 1:
            cb = cb.reshape(1, 1, 3)
        if cs.ndim == 1:
            cs = cs.reshape(1, 1, 3)
        ab, as_ = a_b[..., None], a_s[..., None]
        if blend == "multiply":
            mixed = cb * cs / 255.0
        elif blend == "screen":
            mixed = cb + cs - cb * cs / 255.0
        else:
            mixed = cs
        cs2 = (1.0 - ab) * cs + ab * mixed
        ao = as_ + ab * (1.0 - as_)
        co = np.where(ao > 1e-6, (as_ * cs2 + (1.0 - as_) * ab * cb) / np.maximum(ao, 1e-6), cb)
        self.alpha = ao[..., 0].astype(np.float32)
        self.color = np.broadcast_to(co, (self.H, self.W, 3)).astype(np.float32)


class Rendering(object):
    """The result of render(): see the module docstring."""

    def __init__(self, W, H, sx, sy, alpha, color, paper, notes):
        self.W, self.H, self.sx, self.sy = W, H, sx, sy
        self.alpha, self.color, self.paper, self.notes = alpha, color, paper, notes

    @property
    def uniform(self):
        return isinstance(self.color, tuple)

    def color_u8(self):
        if self.uniform:
            return np.array(self.color, np.uint8)
        return np.clip(np.rint(self.color), 0, 255).astype(np.uint8)

    def rgba(self):
        out = np.zeros((self.H, self.W, 4), np.uint8)
        out[..., :3] = self.color_u8()
        out[..., 3] = (np.clip(self.alpha, 0, 1) * 255 + 0.5).astype(np.uint8)
        return out

    def flatten(self, paper=None):
        """uint8 (H, W, 3): the picture over the paper colour."""
        a = np.clip(self.alpha, 0, 1)[..., None]
        b = np.array(self.paper if paper is None else paper, np.float32)
        f = self.color_u8().astype(np.float32)
        return ((b + (f - b) * a) + 0.5).astype(np.uint8)


# ---------------------------------------------------------------------------------------------
# Vector layers
# ---------------------------------------------------------------------------------------------
def _fill_mask(rings, size, evenodd):
    """uint8 0/255 mask of the compound shape made of `rings` (lists of (x, y)): even-odd, or non-zero
    (exact for simple rings, which is what holes need)."""
    acc = np.zeros((size[1], size[0]), np.int16)
    for ring in rings:
        if len(ring) < 3:
            continue
        m = Image.new("L", size, 0)
        ImageDraw.Draw(m).polygon(ring, fill=1)
        arr = np.asarray(m, np.int16)
        if evenodd:
            acc ^= arr
        else:
            area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]))
            acc += arr * (1 if area >= 0 else -1)
    return ((acc != 0).astype(np.uint8) * 255)


def _wedge(d, v, d0, d1, r, join, miter_limit):
    """The corner at v between directions d0 and d1, for bevel / miter joins."""
    cross = d0[0] * d1[1] - d0[1] * d1[0]
    dot = d0[0] * d1[0] + d0[1] * d1[1]
    if abs(cross) < 1e-9:
        if dot < 0:                                          # a hairpin: the end is round
            d.ellipse([v[0] - r, v[1] - r, v[0] + r, v[1] + r], fill=255)
        return
    s = -1.0 if cross > 0 else 1.0
    n0, n1 = (-d0[1], d0[0]), (-d1[1], d1[0])
    A = (v[0] + s * n0[0] * r, v[1] + s * n0[1] * r)
    B = (v[0] + s * n1[0] * r, v[1] + s * n1[1] * r)
    poly = [v, A, B]
    if join == "miter":
        k = 1.0 + n0[0] * n1[0] + n0[1] * n1[1]              # 2 cos^2 (turn / 2)
        if k > 1e-9 and math.sqrt(2.0 / k) <= miter_limit:
            tip = (v[0] + s * r * (n0[0] + n1[0]) / k, v[1] + s * r * (n0[1] + n1[1]) / k)
            poly = [v, A, tip, B]
    d.polygon(poly, fill=255)


def _unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 1e-12 else None


def _stroke(d, P, wpx, closed, cap, join, miter_limit, vw):
    """One stroked polyline on a PIL draw at the working size.  wpx: the pen width in working pixels;
    vw: per-vertex width multipliers or None."""
    n = len(P)
    if n == 1:                                               # a dot: a disc as wide as the pen
        r = wpx * (vw[0] if vw else 1.0) / 2.0
        d.ellipse([P[0][0] - r, P[0][1] - r, P[0][0] + r, P[0][1] + r], fill=255)
        return
    closed = closed and n > 2
    wi = max(1, int(round(wpx)))                             # the pen is a whole number of pixels
    r = wi / 2.0
    P = list(P)
    if not closed and cap == "square":
        u0, u1 = _unit(P[1], P[0]), _unit(P[-2], P[-1])
        if u0:
            P[0] = (P[0][0] + u0[0] * r, P[0][1] + u0[1] * r)
        if u1:
            P[-1] = (P[-1][0] + u1[0] * r, P[-1][1] + u1[1] * r)
    pairs = list(zip(P, P[1:])) + ([(P[-1], P[0])] if closed else [])
    ws = [(vw[i] if vw else 1.0) for i in range(n)]
    for k, (a, b) in enumerate(pairs):
        if vw is None:
            if b < a:                                        # PIL rounds a wide line differently
                a, b = b, a                                  # drawn backwards: always go the same way
            d.line([a, b], fill=255, width=wi)
        else:
            i, j = k, (k + 1) % n
            u = _unit(a, b)
            if u:
                ha, hb = wpx * ws[i] / 2.0, wpx * ws[j] / 2.0
                nx, ny = -u[1], u[0]
                d.polygon([(a[0] + nx * ha, a[1] + ny * ha), (b[0] + nx * hb, b[1] + ny * hb),
                           (b[0] - nx * hb, b[1] - ny * hb), (a[0] - nx * ha, a[1] - ny * ha)], fill=255)
    for i, (x, y) in enumerate(P):
        interior = closed or 0 < i < n - 1
        rr = r if vw is None else wpx * ws[i] / 2.0
        if interior:
            if join == "round" or vw is not None:
                d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=255)
            else:
                prev, nxt = P[i - 1], P[(i + 1) % n]
                d0, d1 = _unit(prev, (x, y)), _unit((x, y), nxt)
                if d0 and d1:
                    _wedge(d, (x, y), d0, d1, r, join, miter_limit)
        elif cap == "round":
            d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=255)


def _render_vector(L, geo, pal, ss):
    A = L.arrays
    xy, st = A["xy"], A["start"].tolist()
    P = len(st) - 1
    if P == 0:
        return None
    t = [float(v) for v in (L.get("transform") or IDENTITY)]
    a, b, c, d_, e, f = t
    k = geo.sx * math.sqrt(abs(a * d_ - b * c))
    if k <= 0:
        return None
    xy = xy.astype(np.float64)
    X = (a * xy[:, 0] + c * xy[:, 1] + e) * geo.sx
    Y = (b * xy[:, 0] + d_ * xy[:, 1] + f) * geo.sy
    width = A["width"].tolist() if "width" in A else [float(L.get("width", 1.0))] * P
    stroke = A["stroke"].tolist() if "stroke" in A else [L.get("stroke", 0)] * P
    fill_def = L.get("fill")
    fill = A["fill"].tolist() if "fill" in A else [-1 if fill_def is None else fill_def] * P
    flags = A["flags"].tolist() if "flags" in A else [0] * P
    group = A["group"].tolist() if "group" in A else [-1] * P
    vwidth = A["vwidth"].tolist() if "vwidth" in A else None
    cap, join, miter = L.get("cap", "round"), L.get("join", "round"), float(L.get("miter_limit", 4.0))
    if cap not in bif.CAPS:
        cap = "round"
    if join not in bif.JOINS:
        join = "round"

    ops = []                                                 # (paint, kind, path ids)
    i = 0
    while i < P:
        j = i + 1
        if group[i] >= 0:
            while j < P and group[j] == group[i]:
                j += 1
        if fill[i] >= 0:
            ops.append((fill[i], "fill", list(range(i, j))))
        for q in range(i, j):
            if width[q] > 0 and stroke[q] >= 0:
                ops.append((stroke[q], "stroke", [q]))
        i = j

    plane = Plane(geo.W, geo.H)
    run = []
    for op in ops + [None]:
        if op is not None and (not run or run[0][0] == op[0]):
            run.append(op)
            continue
        if run:
            _draw_run(plane, run, X, Y, st, k, width, flags, vwidth, cap, join, miter, geo, ss, pal)
        run = [op] if op is not None else []
    return plane if plane.color is not None else None


def _draw_run(plane, run, X, Y, st, k, width, flags, vwidth, cap, join, miter, geo, ss, pal):
    ids = [q for _, _, qs in run for q in qs]
    lo, hi = min(st[q] for q in ids), max(st[q + 1] for q in ids)
    if hi <= lo:
        return
    wmax = max([width[q] * k for _, kind, qs in run if kind == "stroke" for q in qs] + [0.0])
    wmax *= max(1.0, miter) * (max(vwidth[lo:hi]) if vwidth else 1.0)
    pad = wmax + 2.0
    x0 = int(max(0, math.floor(X[lo:hi].min() - pad)))
    y0 = int(max(0, math.floor(Y[lo:hi].min() - pad)))
    x1 = int(min(geo.W, math.ceil(X[lo:hi].max() + pad)))
    y1 = int(min(geo.H, math.ceil(Y[lo:hi].max() + pad)))
    if x1 <= x0 or y1 <= y0:
        return
    if ss is None:                                   # as much as fits in a 64 MB mask for this run, at most 4
        ss = max(1, min(4, int(math.sqrt(64e6 / float((x1 - x0) * (y1 - y0))))))
    size = ((x1 - x0) * ss, (y1 - y0) * ss)
    mask = Image.new("L", size, 0)
    dr = ImageDraw.Draw(mask)

    def pts(q):
        return [((X[v] - x0) * ss, (Y[v] - y0) * ss) for v in range(st[q], st[q + 1])]

    for paint, kind, qs in run:
        if kind == "fill":
            rings = [pts(q) for q in qs]
            if len(rings) == 1:
                if len(rings[0]) >= 3:
                    dr.polygon(rings[0], fill=255)
            else:                                            # a compound shape: work in a window around it
                allp = [p for r_ in rings for p in r_]
                bx0 = max(0, int(math.floor(min(p[0] for p in allp))) - 1)
                by0 = max(0, int(math.floor(min(p[1] for p in allp))) - 1)
                bx1 = min(size[0], int(math.ceil(max(p[0] for p in allp))) + 2)
                by1 = min(size[1], int(math.ceil(max(p[1] for p in allp))) + 2)
                if bx1 > bx0 and by1 > by0:
                    local = [[(px - bx0, py - by0) for px, py in r_] for r_ in rings]
                    sub = _fill_mask(local, (bx1 - bx0, by1 - by0), flags[qs[0]] & 2)
                    mask.paste(255, (bx0, by0), Image.fromarray(sub))
        else:
            q = qs[0]
            vw = vwidth[st[q]:st[q + 1]] if vwidth else None
            wq = width[q] * k * ss
            if vw and min(vw) == max(vw):                    # the same multiplier all along: an ordinary pen
                wq, vw = wq * vw[0], None
            if st[q + 1] > st[q]:
                _stroke(dr, pts(q), wq, bool(flags[q] & 1), cap, join, miter, vw)
    if ss > 1:
        mask = mask.resize((x1 - x0, y1 - y0), Image.BOX)
    cov = np.asarray(mask, np.float32) / 255.0
    plane.over_patch(x0, y0, cov, pal[run[0][0]])


# ---------------------------------------------------------------------------------------------
# Raster layers
# ---------------------------------------------------------------------------------------------
def _inv3(m):
    return np.linalg.inv(m)


def _render_raster(L, geo, pal):
    A = L.arrays
    alpha, rgb = A.get("alpha"), A.get("rgb")
    Hr, Wr = (alpha if alpha is not None else rgb).shape[:2]
    bx0, by0, bx1, by1 = [float(v) for v in (L.get("bounds") or (0, 0, Wr, Hr))]
    a, b, c, d, e, f = [float(v) for v in (L.get("transform") or IDENTITY)]
    B = np.array([[(bx1 - bx0) / Wr, 0, bx0], [0, (by1 - by0) / Hr, by0], [0, 0, 1]])
    T = np.array([[a, c, e], [b, d, f], [0, 0, 1]])
    S = np.array([[geo.sx, 0, 0], [0, geo.sy, 0], [0, 0, 1]])
    M = S.dot(T).dot(B)                                      # source pixel -> output pixel
    if abs(np.linalg.det(M[:2, :2])) < 1e-12:
        return None
    nearest = L.get("resample", "smooth") == "nearest"

    chans = []
    al = np.ones((Hr, Wr), np.float32) if alpha is None else (
        alpha.astype(np.float32) / 255.0 if alpha.dtype == np.uint8 else alpha.astype(np.float32))
    if rgb is not None:
        for i in range(3):
            ch = rgb[..., i].astype(np.float32)
            chans.append(ch if nearest else ch * al)
    chans = [al] + chans
    # the part of the output the picture reaches
    corners = M.dot(np.array([[0, Wr, Wr, 0], [0, 0, Hr, Hr], [1, 1, 1, 1]], np.float64))
    wx0 = int(max(0, math.floor(corners[0].min()) - 1))
    wy0 = int(max(0, math.floor(corners[1].min()) - 1))
    wx1 = int(min(geo.W, math.ceil(corners[0].max()) + 1))
    wy1 = int(min(geo.H, math.ceil(corners[1].max()) + 1))
    if wx1 <= wx0 or wy1 <= wy0:
        return None
    # a much smaller picture: average the source down first (a bilinear lookup would alias)
    fu = min(1.0, math.hypot(M[0, 0], M[1, 0]))
    fv = min(1.0, math.hypot(M[0, 1], M[1, 1]))
    imgs = [Image.fromarray(ch) for ch in chans]
    if fu < 0.5 or fv < 0.5:
        nw, nh = max(1, int(round(Wr * fu))), max(1, int(round(Hr * fv)))
        imgs = [im.resize((nw, nh), Image.BOX) for im in imgs]
        M = M.dot(np.diag([Wr / float(nw), Hr / float(nh), 1.0]))
    Mi = _inv3(M)
    shift = np.array([[1, 0, wx0], [0, 1, wy0], [0, 0, 1]], np.float64)
    Mw = Mi.dot(shift)
    data = (Mw[0, 0], Mw[0, 1], Mw[0, 2], Mw[1, 0], Mw[1, 1], Mw[1, 2])
    resample = Image.NEAREST if nearest else Image.BICUBIC
    out = [np.asarray(im.transform((wx1 - wx0, wy1 - wy0), Image.AFFINE, data, resample), np.float32) for im in imgs]
    al = np.clip(out[0], 0.0, 1.0)
    if rgb is None:
        col = pal[int(L.get("paint", 0))]
    else:
        col = np.stack(out[1:], -1)
        if not nearest:
            col = col / np.maximum(al, 1e-6)[..., None]
        col = np.clip(col, 0, 255)
    plane = Plane(geo.W, geo.H)
    plane.over_patch(wx0, wy0, al, col)
    return plane


# ---------------------------------------------------------------------------------------------
# The picture
# ---------------------------------------------------------------------------------------------
def _palette(pic, ink, paper):
    pal = []
    for e in pic.palette:
        c = tuple(float(v) for v in e["rgb"])
        role = e.get("role")
        if role == "ink" and ink is not None:
            c = tuple(float(v) for v in ink)
        if role == "paper" and paper is not None:
            c = tuple(float(v) for v in paper)
        pal.append(c)
    return pal


def pick_paper(pic, pal, paper, alpha, color):
    """The colour to flatten onto: given; else the picture's background; else its `paper` colour;
    else white, or black if the picture is light (a guess, so light-on-dark art stays visible)."""
    if paper is not None:
        return tuple(float(v) for v in paper)
    if pic.background is not None:
        return pal[pic.background]
    for e, c in zip(pic.palette, pal):
        if e.get("role") == "paper":
            return c
    w = float(alpha.sum())
    if w > 0:
        col = np.array(color, np.float64) if isinstance(color, tuple) else (color.reshape(-1, 3) * alpha.reshape(-1, 1)).sum(0) / w
        if 0.299 * col[0] + 0.587 * col[1] + 0.114 * col[2] > 153:
            return (0.0, 0.0, 0.0)
    return (255.0, 255.0, 255.0)


class _Geo(object):
    def __init__(self, W, H, sx, sy):
        self.W, self.H, self.sx, self.sy = W, H, sx, sy


def size_for(pic, scale=None, width=None, height=None, max_pixels=DEFAULT_MAX_PIXELS):
    """(sx, sy, W, H, notes): pixels per canvas unit on each axis, and the picture size."""
    ua = float(pic.unit_aspect)
    notes = []
    if scale is not None:
        sx = float(scale)
    elif width is not None or height is not None:
        cand = []
        if width is not None:
            cand.append(width / float(pic.width))
        if height is not None:
            cand.append(height / (float(pic.height) * ua))
        sx = min(cand)
    else:
        sx = 1.0
    sy = sx * ua
    W = max(1, int(math.ceil(pic.width * sx - 1e-9)))
    H = max(1, int(math.ceil(pic.height * sy - 1e-9)))
    if W * H > max_pixels:
        f = math.sqrt(max_pixels / float(W * H))
        notes.append("picture too big (%dx%d): drawn %.0f%% smaller" % (W, H, 100 * (1 - f)))
        sx, sy = sx * f, sy * f
        W = max(1, int(math.ceil(pic.width * sx - 1e-9)))
        H = max(1, int(math.ceil(pic.height * sy - 1e-9)))
    return sx, sy, W, H, notes


def render(pic, frame=0, scale=None, width=None, height=None, ss=None, ink=None, paper=None,
           max_pixels=DEFAULT_MAX_PIXELS, layers=None):
    """Draw frame `frame` of a picture.  scale: pixels per canvas unit (default 1), or width / height in
    pixels (the picture is fitted inside both).  ss: supersampling of vector layers (default: for each run of
    strokes, as much as fits in a 64 MB mask, at most 4: a big drawing of small strokes is antialiased fully,
    one huge stroke layer a little less).  ink / paper: colours that replace the palette entries with those
    roles, and the page colour.  layers: only draw these layer ids."""
    if not 0 <= frame < len(pic.frames):
        raise bif.BifError("no frame %d (the picture has %d)" % (frame, len(pic.frames)))
    sx, sy, W, H, notes = size_for(pic, scale, width, height, max_pixels)
    geo = _Geo(W, H, sx, sy)
    pal = _palette(pic, ink, paper)
    canvas = Plane(W, H)
    for L in pic.frames[frame].layers:
        if L.kind not in ("vector", "raster") or not L.get("visible", L.kind != "cells"):
            continue
        if L.get("role") == "source" or (layers is not None and L.id not in layers):
            continue
        plane = _render_vector(L, geo, pal, ss) if L.kind == "vector" else _render_raster(L, geo, pal)
        if plane is None:
            continue
        blend = L.get("blend", "normal")
        canvas.compose(plane, blend if blend in bif.BLENDS else "normal", float(L.get("opacity", 1.0)))
    if canvas.color is None:
        canvas.color = pal[0] if pal else (0.0, 0.0, 0.0)
    elif isinstance(canvas.color, tuple):
        canvas.color = tuple(float(round(v)) for v in canvas.color)
    return Rendering(W, H, sx, sy, np.clip(canvas.alpha, 0.0, 1.0), canvas.color,
                     pick_paper(pic, pal, paper, canvas.alpha, canvas.color), notes)
