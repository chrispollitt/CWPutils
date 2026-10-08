#!/usr/bin/env python3
"""bifsixel: SIXEL encoder for rendered BIF pictures (a port of unascii's, byte for byte).

    encode(alpha, color, bg)    SIXEL bytes for a picture of coverage `alpha` (float, 0..1) in `color`
                                ((r, g, b) if it is all one colour, else uint8 (H, W, 3)) on paper `bg`.

One colour: painted in `levels` blends from paper to ink, so both are exact.  Several colours: reduced to
`ncolors` clustered colours of `shades` blends each (coloured lines, paper exact), or, when the picture covers
more than a quarter of the area (block art, photographs), painted in its own colours: exactly if there are at
most 254, else median cut.  Python 3.7+, Pillow 5.4+, numpy 1.16+.
"""
from __future__ import print_function

import re

import numpy as np
from PIL import Image


def _rle_rows(bits):
    """SIXEL run-length coding of every row of a (K, W) uint8 array of sixel characters, as K
    strings.  Runs of 1-3 are written out, longer ones as !<count><char>.  All K rows are done
    together with array operations (a big picture has hundreds of thousands of runs, and numpy
    costs too much per call to do them a row at a time)."""
    K, W = bits.shape
    flat = bits.reshape(-1)
    brk = np.zeros(flat.size, bool)
    brk[::W] = True                                         # a run never crosses a row
    brk[1:] |= flat[1:] != flat[:-1]
    starts = np.flatnonzero(brk)
    lens = np.diff(np.append(starts, flat.size))
    chars = flat[starts]
    long_ = lens > 3
    ndig = 1 + (lens >= 10) + (lens >= 100) + (lens >= 1000) + (lens >= 10000)
    size = np.where(long_, ndig + 2, lens)
    off = np.cumsum(size) - size
    out = np.empty(int(size.sum()), np.uint8)
    sh = ~long_
    if sh.any():                                            # a short run: its char, lens times
        n = lens[sh]
        base = np.repeat(off[sh] - (np.cumsum(n) - n), n)
        out[base + np.arange(int(n.sum()))] = np.repeat(chars[sh], n)
    if long_.any():                                         # a long run: ! digits char
        o, n, nd = off[long_], lens[long_], ndig[long_]
        out[o] = 33
        for k in range(5):
            has = nd > k                                    # digit k from the right, if the count has one
            out[(o + nd - k)[has]] = (n[has] // 10 ** k) % 10 + 48
        out[o + nd + 1] = chars[long_]
    text = out.tobytes().decode("ascii")
    first = np.searchsorted(starts, np.arange(K) * W)       # the first run of each row
    bounds = np.append(off, out.size)[np.append(first, len(starts))].tolist()
    return [text[bounds[i]:bounds[i + 1]] for i in range(K)]


def _sixel_stream(idx, palette, transparent):
    """SIXEL bytes for an array of palette indices (uint8; index 0 is the paper, left unpainted
    when transparent) and the palette, a list of (r, g, b) 0..255."""
    H, W = idx.shape
    out = ["\x1bP0;%d;0q\"1;1;%d;%d" % (1 if transparent else 0, W, H)]
    for i, c in enumerate(palette):
        out.append("#%d;2;%d;%d;%d" % (i, int(round(c[0] * 100 / 255.0)), int(round(c[1] * 100 / 255.0)),
                                       int(round(c[2] * 100 / 255.0))))
    weights = (1 << np.arange(6)).astype(np.uint8)[None, :, None]
    tail = re.compile(r"!\d+\?$")
    for top in range(0, H, 6):
        band = idx[top:top + 6]
        if band.shape[0] < 6:
            band = np.vstack([band, np.full((6 - band.shape[0], W), 255, np.uint8)])
        present = [c for c in np.unique(band).tolist() if c != 255 and not (transparent and c == 0)]
        # for each colour present: which of the six pixels in a column have it, as one sixel character
        bits = ((band[None] == np.array(present, np.uint8)[:, None, None]).astype(np.uint8) * weights).sum(1)
        rows = _rle_rows((bits + 63).astype(np.uint8))
        for n, (c, s) in enumerate(zip(present, rows)):
            # a trailing "nothing here" is not needed: a long run "!72?" goes whole (unascii v3 dropped
            # only its "?" and left "!72" before the "$"), then a short one written out
            s = tail.sub("", s).rstrip("?")
            out.append("#%d%s%s" % (c, s, "$" if n < len(present) - 1 else ""))
        out.append("-")
    out.append("\x1b\\")
    return "".join(out).encode("ascii")



def encode(alpha, color, bg=(255, 255, 255), levels=16, transparent=False, ncolors=24, shades=6, image=None):
    """SIXEL stream (bytes).  alpha: float coverage (H, W); color: (r, g, b) or uint8 (H, W, 3); bg: the
    paper.  transparent=True leaves the paper unpainted.  image=True / False forces / forbids painting the
    picture in its own colours (default: when it covers more than a quarter of the area)."""
    ink = np.clip(alpha, 0, 1)
    bg = np.array(bg, np.float64)
    if isinstance(color, tuple):
        fg, rgb = color, None
    else:
        fg, rgb = (0, 0, 0), color

    def blend(c, t):
        return bg + (np.array(c, np.float64) - bg) * t
    sel = ink > 0.25
    if rgb is not None and (image or (image is None and sel.mean() > 0.25)):
        H, W = ink.shape
        comp = np.clip(bg + (rgb.astype(np.float64) - bg) * ink[..., None] + 0.5, 0, 255).astype(np.uint8)
        flat = comp.reshape(-1, 3).astype(np.int32)
        key = (flat[:, 0] << 16) | (flat[:, 1] << 8) | flat[:, 2]
        uniq, inv = np.unique(key, return_inverse=True)
        if len(uniq) <= 254:
            pal = [((k >> 16) & 255, (k >> 8) & 255, k & 255) for k in uniq.tolist()]
            idx = inv.reshape(H, W)
        else:
            q = Image.fromarray(comp).quantize(254, Image.MEDIANCUT)
            p = q.getpalette()[:254 * 3]
            pal = [tuple(p[i:i + 3]) for i in range(0, len(p), 3)]
            idx = np.asarray(q)
        idx = (idx + 1).astype(np.uint8)
        if transparent:
            idx[ink < 0.02] = 0
        return _sixel_stream(idx, [bg] + pal, transparent)
    if rgb is None or not sel.any():
        idx = np.clip(np.rint(ink * (levels - 1)), 0, levels - 1).astype(np.uint8)
        return _sixel_stream(idx, [blend(fg, i / float(levels - 1)) for i in range(levels)], transparent)
    r = rgb.astype(np.int32)
    key = ((r[..., 0] >> 5) << 6) | ((r[..., 1] >> 5) << 3) | (r[..., 2] >> 5)        # 8x8x8 colour cells
    w, k = ink[sel].astype(np.float64), key[sel]
    count = np.bincount(k, weights=w, minlength=512)
    chosen = np.argsort(-count)[:ncolors]
    chosen = chosen[count[chosen] > 0]
    sums = [np.bincount(k, weights=w * r[sel][:, c], minlength=512) for c in range(3)]
    centres = np.stack([sums[c][chosen] / count[chosen] for c in range(3)], 1)         # (K, 3)
    cells = np.arange(512)
    cell_rgb = np.stack([(cells >> 6) * 32 + 16, ((cells >> 3) & 7) * 32 + 16, (cells & 7) * 32 + 16], 1)
    lut = ((cell_rgb[:, None, :] - centres[None]) ** 2).sum(2).argmin(1)               # cell -> nearest colour
    level = np.rint(ink * (shades - 1)).astype(np.int32)
    idx = np.where(level == 0, 0, 1 + lut[key] * (shades - 1) + level - 1).astype(np.uint8)
    palette = [bg] + [blend(c, s / float(shades - 1)) for c in centres for s in range(1, shades)]
    return _sixel_stream(idx, palette, transparent)
