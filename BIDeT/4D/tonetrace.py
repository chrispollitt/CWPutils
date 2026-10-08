#!/usr/bin/env python3
"""tonetrace: contour lines of a scalar field, as polylines (marching squares), numpy and the standard library.

    contours(F, level=0.0)         [(pts, closed), ...]   pts: float (n, 2) of (x, y) = (column, row), sub-cell exact
    bilinear(A, x, y)              the field sampled at points (arrays), edge values repeated outside
    simplify(pts, tol)             Ramer-Douglas-Peucker
    runs(mask)                     [(start, stop), ...] of the True stretches

A contour is where the field crosses `level`; where it crosses a grid edge the position is interpolated
linearly, so a smooth field gives smooth, sub-pixel-accurate lines.  Contours that reach the border of the
array end there; the others are closed.  Used by bifin to turn the outline fields of picture-style art
(tone mode) into vector layers.  Python 3.7+, numpy 1.16+.
"""
from __future__ import print_function

import numpy as np

# Cell corners a b / d c (a top-left, b top-right, c bottom-right, d bottom-left) that are above the level
# make the case number 1*a + 2*b + 4*c + 8*d.  Edges: 0 top, 1 right, 2 bottom, 3 left.  Each case lists the
# edge pairs a contour segment joins; cases 5 and 10 are saddles, resolved by the value at the cell centre.
_SEGS = {
    1: [(3, 0)], 2: [(0, 1)], 3: [(3, 1)], 4: [(1, 2)], 6: [(0, 2)], 7: [(3, 2)], 8: [(2, 3)], 9: [(0, 2)],
    11: [(1, 2)], 12: [(3, 1)], 13: [(0, 1)], 14: [(3, 0)],
}
_SADDLE = {  # case -> (segments when the centre is above the level, when it is below)
    5: ([(0, 1), (2, 3)], [(3, 0), (1, 2)]),
    10: ([(3, 0), (1, 2)], [(0, 1), (2, 3)]),
}


def _tables():
    """(16, 3, 2) edge pairs per case (-1 = none) for a cell whose centre is below, and for one above."""
    lo = -np.ones((16, 2, 2), np.int64)
    hi = -np.ones((16, 2, 2), np.int64)
    for case, segs in _SEGS.items():
        for k, s in enumerate(segs):
            lo[case, k] = hi[case, k] = s
    for case, (above, below) in _SADDLE.items():
        for k in range(2):
            hi[case, k], lo[case, k] = above[k], below[k]
    return lo, hi


_LO, _HI = _tables()


def contours(F, level=0.0):
    """Contour lines of F at `level`: a list of (points, closed).  points: float64 (n, 2), columns (x) and
    rows (y) in the array's own coordinates (a sample at row i, column j is at (j, i))."""
    F = np.asarray(F, np.float64) - level
    H, W = F.shape
    if H < 2 or W < 2:
        return []
    pos = F > 0
    a, b, c, d = pos[:-1, :-1], pos[:-1, 1:], pos[1:, 1:], pos[1:, :-1]
    case = a.astype(np.int64) + 2 * b + 4 * c + 8 * d
    live = (case != 0) & (case != 15)
    if not live.any():
        return []
    ii, jj = np.nonzero(live)
    cs = case[ii, jj]
    centre = (F[:-1, :-1] + F[:-1, 1:] + F[1:, 1:] + F[1:, :-1])[ii, jj] > 0
    pairs = np.where(centre[:, None, None], _HI[cs], _LO[cs])                    # (n, 2, 2)
    nh = H * (W - 1)
    # global ids of a cell's four edges: horizontal edges first (row i, between columns j and j+1), then vertical
    eid = np.stack([ii * (W - 1) + jj, nh + ii * W + jj + 1, (ii + 1) * (W - 1) + jj, nh + ii * W + jj], 1)   # (n, 4)
    seg_a, seg_b = [], []
    for k in range(2):
        e1, e2 = pairs[:, k, 0], pairs[:, k, 1]
        ok = e1 >= 0
        rows = np.nonzero(ok)[0]
        seg_a.append(eid[rows, e1[ok]])
        seg_b.append(eid[rows, e2[ok]])
    sa, sb = np.concatenate(seg_a), np.concatenate(seg_b)
    chains = _stitch(sa.tolist(), sb.tolist())
    # positions of every edge crossing that is used, all at once
    used = np.unique(np.concatenate([sa, sb]))
    hmask = used < nh
    hi_ids, vi_ids = used[hmask], used[~hmask] - nh
    hy, hx = hi_ids // (W - 1), hi_ids % (W - 1)
    xs_h = hx + F[hy, hx] / (F[hy, hx] - F[hy, hx + 1])
    vy, vx = vi_ids // W, vi_ids % W
    ys_v = vy + F[vy, vx] / (F[vy, vx] - F[vy + 1, vx])
    X = np.empty(len(used))
    Y = np.empty(len(used))
    X[hmask], Y[hmask] = xs_h, hy
    X[~hmask], Y[~hmask] = vx, ys_v
    out = []
    for ids, closed in chains:
        k = np.searchsorted(used, np.asarray(ids))
        out.append((np.stack([X[k], Y[k]], 1), closed))
    return out


def _stitch(sa, sb):
    """Join segments (pairs of edge ids; an id is shared by at most two) into chains of ids: [(ids, closed)]."""
    at = {}
    for k, (p, q) in enumerate(zip(sa, sb)):
        at.setdefault(p, []).append(k)
        at.setdefault(q, []).append(k)
    seen = [False] * len(sa)
    out = []
    for k0 in range(len(sa)):
        if seen[k0]:
            continue
        seen[k0] = True
        chain = [sa[k0], sb[k0]]
        for forward in (True, False):
            while True:
                end = chain[-1] if forward else chain[0]
                nxt = None
                for k in at[end]:
                    if not seen[k]:
                        nxt = k
                        break
                if nxt is None:
                    break
                seen[nxt] = True
                other = sb[nxt] if sa[nxt] == end else sa[nxt]
                if forward:
                    chain.append(other)
                else:
                    chain.insert(0, other)
        closed = len(chain) > 3 and chain[0] == chain[-1]
        if closed:
            chain.pop()
        out.append((chain, closed))
    return out


def bilinear(A, x, y):
    """A (2-D) sampled at float arrays x (columns) and y (rows); the nearest edge value outside the array."""
    A = np.asarray(A, np.float64)
    H, W = A.shape
    x = np.clip(np.asarray(x, np.float64), 0, W - 1)
    y = np.clip(np.asarray(y, np.float64), 0, H - 1)
    x0, y0 = np.minimum(x.astype(np.int64), max(W - 2, 0)), np.minimum(y.astype(np.int64), max(H - 2, 0))
    x1, y1 = np.minimum(x0 + 1, W - 1), np.minimum(y0 + 1, H - 1)
    fx, fy = x - x0, y - y0
    return (A[y0, x0] * (1 - fx) + A[y0, x1] * fx) * (1 - fy) + (A[y1, x0] * (1 - fx) + A[y1, x1] * fx) * fy


def simplify(pts, tol, index=False):
    """Ramer-Douglas-Peucker: fewer points, no point of the original further than `tol` from the result.
    index=True returns the indices of the points kept (to thin per-vertex data the same way)."""
    pts = np.asarray(pts, np.float64)
    n = len(pts)
    if n < 3 or tol <= 0:
        return np.arange(n) if index else pts
    keep = np.zeros(n, bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        s, e = stack.pop()
        if e <= s + 1:
            continue
        p, a, b = pts[s + 1:e], pts[s], pts[e]
        d = b - a
        L = float(np.hypot(d[0], d[1]))
        if L == 0.0:
            dist = np.hypot(p[:, 0] - a[0], p[:, 1] - a[1])
        else:
            dist = np.abs(d[0] * (p[:, 1] - a[1]) - d[1] * (p[:, 0] - a[0])) / L
        k = int(np.argmax(dist))
        if dist[k] > tol:
            m = s + 1 + k
            keep[m] = True
            stack.append((s, m))
            stack.append((m, e))
    return np.flatnonzero(keep) if index else pts[keep]


def runs(mask):
    """The stretches of True in a 1-D boolean array, as [(start, stop), ...] (stop exclusive)."""
    m = np.concatenate(([False], np.asarray(mask, bool), [False]))
    edges = np.flatnonzero(m[1:] != m[:-1])
    return [(int(a), int(b)) for a, b in zip(edges[::2], edges[1::2])]
