#!/usr/bin/env python3
"""bifin_lettering: a string and a font -> BIF (the lettering importer of bifin).

    import bifin_lettering
    pic = bifin_lettering.lettering("Hello, World!", font="impact", size=100)
    bif.save(pic, "hello.bif")

Not terminal art: lettering, set the way a typesetter would.  Proportional fonts (the advance widths of the font
itself, kerning from its `kern` table), letter spacing, line height, alignment, word wrapping; the letters are one
vector layer `text` of filled outlines (nonzero fill, so the holes of an `o` are holes), sharp at any size and ready
for bifop's warps.  Units are font pixels at `size` (default 100 per em).  Faces are found by name (fonts.py);
a bold or italic that the family lacks is faked (an outline stroke, a shear).

Python 3.7+, numpy 1.16+.
"""
from __future__ import print_function

import math

import numpy as np

import bif
import fonts
import ttfglyphs

VERSION = "0.1"
SYNTHETIC_ITALIC_DEGREES = 12.0
SYNTHETIC_BOLD_EM = 0.035            # outline width of faked bold, in ems
STEM_EM = 0.04                       # the layer's `stem`, in ems: bifop's pen:2 adds an outline this thick


def _clean(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    if text.endswith("\n"):
        text = text[:-1]
    return "".join(c for c in text if c == "\n" or ord(c) >= 32 and ord(c) != 127)


def layout(text, tt, size, spacing=0.0, wrap=0.0, align="left", line_height=None):
    """Place the characters: ([(codepoint, glyph id, x, line)], line pitch, widths of the lines), all in pixels.
    x is the pen position of the glyph's origin; line numbers count from 0."""
    s = size / float(tt.units_per_em)
    m = tt.metrics()
    pitch = line_height * size if line_height else (m["ascent"] + m["descent"] + m["line_gap"]) * s
    kern = tt.kerning()
    gap = spacing * size

    def run(chars):
        """Pen positions along one line, and the width."""
        out, x, prev = [], 0.0, None
        for c in chars:
            gid = tt.glyph_id(ord(c))
            if prev is not None:
                x += kern.get((prev, gid), 0) * s
            out.append((ord(c), gid, x))
            x += tt.advance(gid) * s + gap
            prev = gid
        return out, max(0.0, x - gap if chars else 0.0)

    lines = []
    for para in text.split("\n"):
        if wrap and wrap > 0 and para.strip():
            words, cur = para.split(" "), ""
            for w in words:
                trial = (cur + " " + w) if cur else w
                if cur and run(trial)[1] > wrap:
                    lines.append(cur)
                    cur = w
                else:
                    cur = trial
            lines.append(cur)
        else:
            lines.append(para)
    placed, widths = [], []
    for li, chars in enumerate(lines):
        glyphs, w = run(chars)
        widths.append(w)
        placed.append(glyphs)
    full = max(widths) if widths else 0.0
    out = []
    for li, glyphs in enumerate(placed):
        shift = {"left": 0.0, "center": (full - widths[li]) / 2.0, "right": full - widths[li]}[align]
        out.extend((cp, gid, x + shift, li) for cp, gid, x in glyphs)
    return out, pitch, widths


def lettering(text, font=None, size=100.0, spacing=0.0, line_height=None, align="left", wrap=0.0, bold=False,
              italic=False, margin=0.15, ink=(0, 0, 0), paper=(255, 255, 255), name=None):
    """A bif.Picture of `text` set in `font` (a name, a list of names joined with commas, or a file)."""
    if size <= 0:
        raise bif.BifError("lettering: the size must be positive")
    if align not in ("left", "center", "right"):
        raise bif.BifError("lettering: align is left, center or right")
    try:
        face = fonts.resolve(font or "sans", bold, italic)
        tt = ttfglyphs.TrueType(face.path)
    except fonts.FontNotFound as e:
        raise bif.BifError(str(e))
    except ttfglyphs.Unsupported as e:
        raise bif.BifError("font %s: %s" % (face.path, e))
    text = _clean(text)
    s = size / float(tt.units_per_em)
    m = tt.metrics()
    placed, pitch, widths = layout(text, tt, size, spacing, wrap, align, line_height)
    shear = math.tan(math.radians(SYNTHETIC_ITALIC_DEGREES)) if face.need_italic else 0.0
    stroke = SYNTHETIC_BOLD_EM * size if face.need_bold else 0.0
    tol = max(0.02, size * 0.0004) / s                                  # curves flattened to ~0.04 px at size 100
    paths, grp, n = [], [], -1                  # one ring per contour; the rings of a glyph share a group (holes)
    for cp, gid, x, li in placed:
        if cp == 32:
            continue
        try:
            contours = tt.contours(cp, tol)
        except ttfglyphs.Unsupported as e:
            raise bif.BifError("font %s: %s" % (face.path, e))
        if not contours:
            continue
        n += 1
        base = m["ascent"] * s + li * pitch
        for c in contours:
            arr = np.asarray(c, np.float64)
            gy = arr[:, 1] * s                                           # height above the baseline
            paths.append(np.stack([x + arr[:, 0] * s + shear * gy, base - gy], 1))
            grp.append(n)
    pad = margin * size
    if paths:
        allp = np.concatenate(paths)
        x0, y0 = allp[:, 0].min() - stroke / 2.0, allp[:, 1].min() - stroke / 2.0
        x1, y1 = allp[:, 0].max() + stroke / 2.0, allp[:, 1].max() + stroke / 2.0
        shift = np.array([pad - x0, pad - y0])
        paths = [p + shift for p in paths]
        W, H = (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad
    else:
        W, H = 2 * pad + size * 0.5, 2 * pad + size * 0.5
    pic = bif.Picture(round(W, 3), round(H, 3), palette=[{"rgb": [int(v) for v in ink], "role": "ink"},
                                                           {"rgb": [int(v) for v in paper], "role": "paper"}], background=1)
    frame = pic.add_frame()
    if paths:
        n = len(paths)
        frame.layers.append(bif.vector_layer(paths, widths=[stroke] * n, strokes=[0] * n, fills=[0] * n, closed=[1] * n,
                                             groups=grp, id="text", width=0, stem=round(STEM_EM * size, 3)))
    pic.meta = {
        "generator": {"name": "bifin", "version": VERSION, "importer": "lettering",
                      "args": {"font": font or "sans", "size": size, "spacing": spacing, "align": align}},
        "mode": "lettering", "polarity": "dark-on-light",
        "source": {"kind": "lettering", "characters": len(text.replace("\n", "")),
                   "font": {"family": face.family, "style": face.style, "file": face.path.replace("\\", "/").split("/")[-1],
                            "synthetic": [k for k, v in (("bold", face.need_bold), ("italic", face.need_italic)) if v]}},
    }
    if name:
        pic.meta["source"]["name"] = name.replace("\\", "/").split("/")[-1]
    return pic
