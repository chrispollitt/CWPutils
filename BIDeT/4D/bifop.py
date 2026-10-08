#!/usr/bin/env python3
"""bifop: change a BIF (BIDeT Intermediate Format) and write the result as a BIF.

    bifin cow.txt | bifop pen:2 theme:ink=#00ff66,paper=#101820 crop:margin=8 | bifout -s
    bifop -i art.bif -o thick.bif pen:1.5
    bifop --list

Operations are applied in the order given.  `name`, `name:value` (the operation's first parameter) or
`name:key=value,key=value`; lists inside a value are joined with `+` (`layer=strokes+text`).  Colours are
`#rrggbb` or a name.  Operations that take `layer=` change only those layer ids (default: every layer they
apply to), `frame=` only that frame.

What an operation does not know about it passes through (unknown layers, array names, JSON keys and chunks), it
keeps the credit and licence, and it appends itself to `meta.history`, as BIF-SPEC.md asks of a manipulator.
Operations are registered with @op: to add one, add a function.  Python 3.7+, numpy 1.16+, Pillow 5.4+.
"""
from __future__ import print_function

import copy
import math
import sys

import numpy as np

import bif
import tonetrace

VERSION = "0.1"
IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
OPS = {}


class Notes(object):
    """What an operation wants to tell the user without failing."""
    def __init__(self):
        self.lines = []

    def warn(self, msg):
        self.lines.append(msg)


def op(name, params, doc):
    """Register an operation.  params: [(name, converter, default, help)], the first one may be given bare
    (`pen:2`); a default of REQUIRED makes the parameter mandatory."""
    def register(fn):
        OPS[name] = (fn, params, doc)
        return fn
    return register


REQUIRED = object()


# ---------------------------------------------------------------------------------------------
# Parameter conversion
# ---------------------------------------------------------------------------------------------
def _float(s):
    try:
        v = float(s)
    except ValueError:
        raise bif.BifError("'%s' is not a number" % s)
    if v != v or v in (float("inf"), float("-inf")):
        raise bif.BifError("'%s' is not a finite number" % s)
    return v


def _int(s):
    try:
        return int(s)
    except ValueError:
        raise bif.BifError("'%s' is not a whole number" % s)


def _color(s):
    from PIL import ImageColor
    try:
        return tuple(ImageColor.getrgb(s)[:3])
    except ValueError:
        raise bif.BifError("'%s' is not a colour" % s)


def _ids(s):
    return [x for x in s.split("+") if x]


def _str(s):
    return s


def _bool(s):
    if s.lower() in ("1", "true", "yes", "on"):
        return True
    if s.lower() in ("0", "false", "no", "off"):
        return False
    raise bif.BifError("'%s' is not yes or no" % s)


def parse_spec(text):
    """'name', 'name:value' or 'name:k=v,k=v'  ->  (name, {k: v}) with the values still strings."""
    name, _, rest = text.partition(":")
    if name not in OPS:
        raise bif.BifError("unknown operation '%s' (bifop --list shows them)" % name)
    params = OPS[name][1]
    kw = {}
    if rest:
        for i, item in enumerate(rest.split(",")):
            key, eq, val = item.partition("=")
            if not (eq and key.isidentifier()):              # not "name=value": the first parameter, given bare
                if i != 0 or not params:                     # (so "recolor:2=#f00" is a value, "pen:x=1" a mistake)
                    raise bif.BifError("%s: '%s' needs a name (key=value)" % (name, item))
                key, val = params[0][0], item
            if key not in [p[0] for p in params]:
                raise bif.BifError("%s: no parameter '%s' (it has: %s)" % (name, key, ", ".join(p[0] for p in params) or "none"))
            kw[key] = val
    return name, kw


def convert_args(name, kw):
    fn, params, doc = OPS[name]
    out = {}
    for pname, conv, default, help_ in params:
        if pname in kw:
            try:
                out[pname] = conv(kw[pname])
            except bif.BifError as e:
                raise bif.BifError("%s: %s: %s" % (name, pname, e))
        elif default is REQUIRED:
            raise bif.BifError("%s: needs %s=..." % (name, pname))
        else:
            out[pname] = default
    return out


# ---------------------------------------------------------------------------------------------
# The picture
# ---------------------------------------------------------------------------------------------
def clone(pic):
    """A copy that operations may change.  Arrays are shared: an operation replaces an array, never writes into one."""
    q = bif.Picture(pic.width, pic.height, pic.unit_aspect, copy.deepcopy(pic.grid), copy.deepcopy(pic.palette),
                    pic.background, copy.deepcopy(pic.animation), copy.deepcopy(pic.meta))
    q.head_extra, q.canvas_extra = copy.deepcopy(pic.head_extra), copy.deepcopy(pic.canvas_extra)
    q.source, q.extra, q.truncated = pic.source, list(pic.extra), pic.truncated
    for f in pic.frames:
        g = bif.Frame(props=copy.deepcopy(f.props))
        for L in f.layers:
            g.layers.append(bif.Layer(L.kind, copy.deepcopy(L.props), dict(L.arrays)))
        q.frames.append(g)
    return q


def apply(pic, specs, notes=None):
    """Apply operations (strings like 'pen:2', or (name, {k: v}) with string values) to a Picture: a new Picture."""
    notes = notes or Notes()
    pic = clone(pic)
    for spec in specs:
        name, raw = parse_spec(spec) if isinstance(spec, str) else spec
        args = convert_args(name, raw)
        OPS[name][0](pic, notes, **args)
        hist = pic.meta.setdefault("history", [])
        if isinstance(hist, list):
            hist.append({"tool": "bifop", "version": VERSION, "op": name,
                         "args": dict((k, raw[k]) for k in sorted(raw))})
    errors, _w = bif.check(pic)
    if errors:
        raise bif.BifError("the result is not a valid BIF: " + "; ".join(errors[:3]))
    return pic


def layers(pic, ids=None, kinds=None, frame=None):
    """The layers an operation applies to: of these ids, kinds and frame (None = any)."""
    out = []
    for fi, f in enumerate(pic.frames):
        if frame is not None and fi != frame:
            continue
        for L in f.layers:
            if kinds is not None and L.kind not in kinds:
                continue
            if ids is not None and L.id not in ids:
                continue
            out.append(L)
    return out


def _need_layers(found, ids, name):
    if not found and ids:
        raise bif.BifError("%s: no layer with id %s" % (name, "+".join(ids)))


def mmul(m, n):
    """The matrix that does n first, then m (SVG order a b c d e f)."""
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + c * B, b * A + d * B, a * C + c * D, b * C + d * D, a * E + c * F + e, b * E + d * F + f)


def layer_matrix(L):
    t = L.get("transform")
    return tuple(float(v) for v in t) if t else IDENT


def post_transform(pic, m, frame=None):
    """Move every picture layer by m, after its own transform.  (`cells` layers sit on the grid, not on the canvas.)"""
    for L in layers(pic, frame=frame):
        if L.kind != "cells":
            L.props["transform"] = list(mmul(m, layer_matrix(L)))


def drop_grid(pic):
    """The character grid no longer describes the picture: forget it and the cells layer that sits on it."""
    pic.grid = None
    for f in pic.frames:
        f.layers = [L for L in f.layers if L.kind != "cells"]


def scale_of(m):
    return math.sqrt(abs(m[0] * m[3] - m[1] * m[2]))


# ---------------------------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------------------------
@op("pen", [("factor", _float, REQUIRED, "multiply the stroke width by this"),
            ("layer", _ids, None, "only these layer ids"), ("frame", _int, None, "only this frame")],
    "Thicker or thinner lines: scales the stroke width of vector layers.  Letters (filled outlines with a `stem`) "
    "get bolder: an outline of (factor - 1) stems is added; they cannot be made thinner than the font drew them.")
def op_pen(pic, notes, factor, layer, frame):
    if factor < 0:
        raise bif.BifError("pen: the factor must not be negative")
    found = layers(pic, layer, ("vector",), frame)
    _need_layers(found, layer, "pen")
    for L in found:
        stem = float(L.get("stem", 0) or 0)
        extra = max(0.0, factor - 1.0) * stem                  # filled letters: the weight is added round the outline
        if stem and factor < 1.0:
            notes.warn("pen: layer '%s' is lettering, which cannot be drawn thinner than the font made it" % (L.id or "?"))
        L.props["width"] = float(L.get("width", 1.0)) * factor
        if "width" in L.arrays:
            L.arrays["width"] = (L.arrays["width"].astype(np.float64) * factor + extra).astype("<f4")
        elif extra:
            L.arrays["width"] = np.full(len(L.arrays["start"]) - 1, L.props["width"] + extra, "<f4")


@op("theme", [("ink", _color, None, "the line colour"), ("paper", _color, None, "the page colour"),
              ("text", _color, None, "colour of palette entries with role `text`"),
              ("accent", _color, None, "colour of palette entries with role `accent`")],
    "Re-colour by role: every palette entry with that role gets the colour. A `paper` also becomes the background.")
def op_theme(pic, notes, **colours):
    for role, rgb in sorted(colours.items()):
        if rgb is None:
            continue
        hit = [e for e in pic.palette if e.get("role") == role]
        if not hit:
            if role != "paper":                  # nothing is drawn in a colour with no role, so there is nothing to change
                notes.warn("theme: the picture has no `%s` colour (recolor changes a colour by number)" % role)
                continue
            if len(pic.palette) >= 65535:
                raise bif.BifError("theme: the palette is full")
            pic.palette.append({"rgb": list(rgb), "role": role})                  # a page colour can always be added
            hit = [pic.palette[-1]]
        for e in hit:
            e["rgb"] = [int(v) for v in rgb]
        if role == "paper":
            pic.background = pic.palette.index(hit[0])


@op("recolor", [("map", _str, REQUIRED, "FROM=TO pairs joined with +: FROM is a palette index or #rrggbb, TO a colour")],
    "Change particular palette colours: recolor:2=#ff0000  or  recolor:#cc2828=#00aa00+3=blue.")
def op_recolor(pic, notes, map):
    for pair in map.split("+"):
        src, eq, dst = pair.partition("=")
        if not eq:
            raise bif.BifError("recolor: '%s' is not FROM=TO" % pair)
        rgb = [int(v) for v in _color(dst)]
        if src.isdigit():
            idx = [int(src)] if int(src) < len(pic.palette) else []
        else:
            want = list(_color(src))
            idx = [i for i, e in enumerate(pic.palette) if e["rgb"] == want]
        if not idx:
            notes.warn("recolor: nothing matches '%s'" % src)
        for i in idx:
            pic.palette[i]["rgb"] = rgb


@op("opacity", [("value", _float, REQUIRED, "0 to 1"), ("layer", _ids, None, "only these layer ids"),
                ("frame", _int, None, "only this frame")], "Layer opacity.")
def op_opacity(pic, notes, value, layer, frame):
    if not 0.0 <= value <= 1.0:
        raise bif.BifError("opacity: 0 to 1")
    found = layers(pic, layer, None, frame)
    _need_layers(found, layer, "opacity")
    for L in found:
        if L.kind != "cells":
            L.props["opacity"] = value


@op("blend", [("mode", _str, REQUIRED, "normal, multiply, screen or erase"), ("layer", _ids, None, "only these layer ids"),
              ("frame", _int, None, "only this frame")], "How a layer combines with what is below it.")
def op_blend(pic, notes, mode, layer, frame):
    if mode not in bif.BLENDS:
        raise bif.BifError("blend: one of %s" % ", ".join(bif.BLENDS))
    found = layers(pic, layer, None, frame)
    _need_layers(found, layer, "blend")
    for L in found:
        if L.kind != "cells":
            L.props["blend"] = mode


# ---------------------------------------------------------------------------------------------
# Layers and frames
# ---------------------------------------------------------------------------------------------
def _select(pic, ids, name):
    found = layers(pic, ids)
    if not found:
        raise bif.BifError("%s: no layer with id %s" % (name, "+".join(ids)))
    return found


@op("keep", [("layer", _ids, REQUIRED, "layer ids to keep, joined with +")], "Remove every layer but these.")
def op_keep(pic, notes, layer):
    _select(pic, layer, "keep")
    for f in pic.frames:
        f.layers = [L for L in f.layers if L.id in layer]


@op("drop", [("layer", _ids, REQUIRED, "layer ids to remove, joined with +")], "Remove these layers.")
def op_drop(pic, notes, layer):
    _select(pic, layer, "drop")
    for f in pic.frames:
        f.layers = [L for L in f.layers if L.id not in layer]


@op("hide", [("layer", _ids, REQUIRED, "layer ids, joined with +")], "Keep these layers but do not draw them.")
def op_hide(pic, notes, layer):
    for L in _select(pic, layer, "hide"):
        L.props["visible"] = False


@op("show", [("layer", _ids, REQUIRED, "layer ids, joined with +")], "Draw these layers (again).")
def op_show(pic, notes, layer):
    for L in _select(pic, layer, "show"):
        L.props["visible"] = True


@op("frame", [("n", _int, REQUIRED, "frame number, from 0")], "Keep one frame of an animation, as a still picture.")
def op_frame(pic, notes, n):
    if not 0 <= n < len(pic.frames):
        raise bif.BifError("frame: the picture has frames 0 to %d" % (len(pic.frames) - 1))
    pic.frames = [pic.frames[n]]
    pic.animation = None


@op("meta", [("title", _str, None, "the title"), ("comment", _str, None, "a comment"), ("author", _str, None, "the author")],
    "Set descriptive metadata. (Credit and licence are carried through, not edited here.)")
def op_meta(pic, notes, **kv):
    for k, v in sorted(kv.items()):
        if v is not None:
            pic.meta[k] = v


# ---------------------------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------------------------
def extent(pic, frame=0):
    """(x0, y0, x1, y1) of what a frame draws, in canvas units, or None: strokes with their pens, filled shapes,
    the part of a raster that has any alpha."""
    boxes = []
    for L in pic.frames[frame].layers:
        if L.kind not in ("vector", "raster") or not L.get("visible", True) or L.get("role") == "source":
            continue
        if float(L.get("opacity", 1.0)) <= 0:
            continue
        m = layer_matrix(L)
        if L.kind == "vector":
            b = _vector_extent(L, m)
        else:
            b = _raster_extent(L, m)
        if b:
            boxes.append(b)
    if not boxes:
        return None
    b = np.array(boxes)
    return float(b[:, 0].min()), float(b[:, 1].min()), float(b[:, 2].max()), float(b[:, 3].max())


def _vector_extent(L, m):
    xy, st = L.arrays["xy"].astype(np.float64), L.arrays["start"].astype(np.int64)
    if len(xy) == 0:
        return None
    X = m[0] * xy[:, 0] + m[2] * xy[:, 1] + m[4]
    Y = m[1] * xy[:, 0] + m[3] * xy[:, 1] + m[5]
    P = len(st) - 1
    first, last = st[:-1], st[1:]
    ne = np.nonzero(last > first)[0]
    if len(ne) == 0:
        return None
    k = scale_of(m)
    width = L.arrays["width"].astype(np.float64) if "width" in L.arrays else np.full(P, float(L.get("width", 1.0)))
    stroke = L.arrays["stroke"] if "stroke" in L.arrays else np.full(P, L.get("stroke", 0))
    half = np.where((width > 0) & (stroke >= 0), 0.5 * width * k, 0.0)
    h = half[ne]
    if "vwidth" in L.arrays:                                        # the widest the pen gets along each path
        h = h * np.maximum.reduceat(L.arrays["vwidth"].astype(np.float64), first[ne])
    if L.get("join") == "miter":
        h = h * max(1.0, float(L.get("miter_limit", 4.0)))
    xs0, xs1 = np.minimum.reduceat(X, first[ne]), np.maximum.reduceat(X, first[ne])
    ys0, ys1 = np.minimum.reduceat(Y, first[ne]), np.maximum.reduceat(Y, first[ne])
    return (float((xs0 - h).min()), float((ys0 - h).min()), float((xs1 + h).max()), float((ys1 + h).max()))


def _raster_extent(L, m):
    a = L.arrays.get("alpha")
    ref = a if a is not None else L.arrays.get("rgb")
    if ref is None:
        return None
    H, W = ref.shape[:2]
    x0, y0, x1, y1 = [float(v) for v in (L.get("bounds") or (0, 0, W, H))]
    r0, r1, c0, c1 = 0, H, 0, W
    if a is not None:
        ys, xs = np.nonzero(a > 0)
        if len(ys) == 0:
            return None
        r0, r1, c0, c1 = int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1
    sx, sy = (x1 - x0) / W, (y1 - y0) / H
    cx = [x0 + c0 * sx, x0 + c1 * sx, x0 + c1 * sx, x0 + c0 * sx]
    cy = [y0 + r0 * sy, y0 + r0 * sy, y0 + r1 * sy, y0 + r1 * sy]
    X = [m[0] * x + m[2] * y + m[4] for x, y in zip(cx, cy)]
    Y = [m[1] * x + m[3] * y + m[5] for x, y in zip(cx, cy)]
    return (min(X), min(Y), max(X), max(Y))


@op("crop", [("margin", _float, 0.0, "blank space to leave round the drawing, in canvas units"),
             ("box", _ids, None, "x0+y0+x1+y1: crop to this rectangle instead of to the ink")],
    "Cut the canvas down to what is drawn (plus a margin), or to a box. The edges fall on whole units, so a pixel "
    "picture is not resampled.")
def op_crop(pic, notes, margin, box):
    if box:
        if len(box) != 4:
            raise bif.BifError("crop: box is x0+y0+x1+y1")
        x0, y0, x1, y1 = [_float(v) for v in box]
    else:
        e = extent(pic, 0)
        if e is None:
            notes.warn("crop: nothing is drawn, so nothing to crop to")
            return
        x0, y0, x1, y1 = e[0] - margin, e[1] - margin, e[2] + margin, e[3] + margin
    x0, y0 = math.floor(x0 + 1e-9), math.floor(y0 + 1e-9)
    x1, y1 = math.ceil(x1 - 1e-9), math.ceil(y1 - 1e-9)
    if x1 <= x0 or y1 <= y0:
        raise bif.BifError("crop: the box is empty")
    post_transform(pic, (1.0, 0.0, 0.0, 1.0, -x0, -y0))
    pic.width, pic.height = x1 - x0, y1 - y0
    if pic.grid:
        pic.grid["x"], pic.grid["y"] = pic.grid.get("x", 0) - x0, pic.grid.get("y", 0) - y0


@op("scale", [("factor", _float, REQUIRED, "multiply every size by this")],
    "Change the units: the canvas, the grid and everything on it grow by the factor (a picture drawn at 1 pixel per "
    "unit gets bigger or smaller, vectors without loss).")
def op_scale(pic, notes, factor):
    if factor <= 0:
        raise bif.BifError("scale: the factor must be positive")
    pic.width, pic.height = pic.width * factor, pic.height * factor
    if pic.grid:
        for k in ("cell_width", "cell_height", "x", "y"):
            if k in pic.grid:
                pic.grid[k] = pic.grid[k] * factor
    post_transform(pic, (factor, 0.0, 0.0, factor, 0.0, 0.0))


@op("rotate", [("degrees", _float, REQUIRED, "clockwise")],
    "Turn the picture; the canvas grows to hold it (the corners stay transparent). Forgets the character grid.")
def op_rotate(pic, notes, degrees):
    if pic.unit_aspect != 1.0:
        raise bif.BifError("rotate: the units are not square (unit_aspect %s); scale first" % pic.unit_aspect)
    t = math.radians(degrees)
    c, s = math.cos(t), math.sin(t)
    if abs(c) < 1e-12:
        c = 0.0
    if abs(s) < 1e-12:
        s = 0.0
    W, H = pic.width, pic.height
    nw, nh = abs(W * c) + abs(H * s), abs(W * s) + abs(H * c)
    # about the centre, then to the new canvas' centre (y is down, so a positive angle is clockwise)
    to = (1.0, 0.0, 0.0, 1.0, -W / 2.0, -H / 2.0)
    rot = (c, s, -s, c, 0.0, 0.0)
    back = (1.0, 0.0, 0.0, 1.0, nw / 2.0, nh / 2.0)
    post_transform(pic, mmul(back, mmul(rot, to)))
    pic.width, pic.height = nw, nh
    drop_grid(pic)


@op("flip", [("axis", _str, "h", "h (left to right) or v (top to bottom)")], "Mirror the picture. Forgets the character grid.")
def op_flip(pic, notes, axis):
    if axis not in ("h", "v"):
        raise bif.BifError("flip: axis is h or v")
    m = (-1.0, 0.0, 0.0, 1.0, pic.width, 0.0) if axis == "h" else (1.0, 0.0, 0.0, -1.0, 0.0, pic.height)
    post_transform(pic, m)
    drop_grid(pic)


@op("skew", [("x", _float, 0.0, "degrees to lean the verticals to the right (italic); negative to the left"),
             ("y", _float, 0.0, "degrees to tilt the baseline downwards to the right; negative: rising")],
    "Shear the picture; the canvas grows to hold it. Forgets the character grid.")
def op_skew(pic, notes, x, y):
    if pic.unit_aspect != 1.0:
        raise bif.BifError("skew: the units are not square (unit_aspect %s); scale first" % pic.unit_aspect)
    if abs(x) >= 89.0 or abs(y) >= 89.0:
        raise bif.BifError("skew: the angles must be within 89 degrees")
    tx, ty = -math.tan(math.radians(x)), math.tan(math.radians(y))      # (y is down: the top moves right for x > 0)
    W, H = pic.width, pic.height
    xs = [px + tx * py for px, py in ((0, 0), (W, 0), (W, H), (0, H))]
    ys = [ty * px + py for px, py in ((0, 0), (W, 0), (W, H), (0, H))]
    x0, y0 = min(xs), min(ys)
    post_transform(pic, (1.0, ty, tx, 1.0, -x0, -y0))              # x' = x + tx y,  y' = y + ty x, then to the new corner
    pic.width, pic.height = max(xs) - x0, max(ys) - y0
    drop_grid(pic)


# ---------------------------------------------------------------------------------------------
# Vector shapes: simplifying and warping
# ---------------------------------------------------------------------------------------------
def _rebuild(L, paths, vw=None, vf=None):
    """Replace a vector layer's geometry: paths (a list of (n, 2) arrays), with the per-vertex arrays that go with them."""
    xy, start = bif.paths_to_csr(paths)
    L.arrays["xy"], L.arrays["start"] = xy, start
    for name, data in (("vwidth", vw), ("vflag", vf)):
        if data is not None:
            L.arrays[name] = np.concatenate(data).astype("<f4" if name == "vwidth" else "|u1") if data else \
                np.zeros(0, "<f4" if name == "vwidth" else "|u1")


@op("simplify", [("tolerance", _float, REQUIRED, "the most a point may move, in canvas units"),
                 ("layer", _ids, None, "only these layer ids"), ("frame", _int, None, "only this frame")],
    "Fewer vertices: drops points of vector paths that lie within the tolerance of the line between their neighbours.")
def op_simplify(pic, notes, tolerance, layer, frame):
    if tolerance < 0:
        raise bif.BifError("simplify: the tolerance must not be negative")
    found = layers(pic, layer, ("vector",), frame)
    _need_layers(found, layer, "simplify")
    for L in found:
        k = scale_of(layer_matrix(L))
        tol = tolerance / k if k > 0 else 0.0
        xy, st = L.arrays["xy"].astype(np.float64), L.arrays["start"].astype(np.int64)
        flags = L.arrays["flags"] if "flags" in L.arrays else np.zeros(len(st) - 1, "|u1")
        paths, vw, vf = [], [], []
        for i in range(len(st) - 1):
            a, b = int(st[i]), int(st[i + 1])
            pts = xy[a:b]
            closed = bool(flags[i] & 1) and len(pts) > 3
            if closed:
                keep = tonetrace.simplify(np.vstack([pts, pts[:1]]), tol, index=True)
                keep = keep[keep < len(pts)]
                if len(keep) < 3:
                    keep = np.arange(len(pts))
            else:
                keep = tonetrace.simplify(pts, tol, index=True)
            paths.append(pts[keep])
            if "vwidth" in L.arrays:
                vw.append(L.arrays["vwidth"][a:b][keep])
            if "vflag" in L.arrays:
                vf.append(L.arrays["vflag"][a:b][keep])
        _rebuild(L, paths, vw if "vwidth" in L.arrays else None, vf if "vflag" in L.arrays else None)


def _densify(pts, step, vw=None, vf=None):
    """Points along a polyline no further apart than `step` (new vertices take the line's width, no flags)."""
    if len(pts) < 2:
        return pts, vw, vf
    out, ow, of = [pts[:1]], ([vw[:1]] if vw is not None else None), ([vf[:1]] if vf is not None else None)
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        n = max(1, int(math.ceil(float(np.hypot(*(b - a))) / step)))
        t = (np.arange(1, n + 1) / float(n))[:, None]
        out.append(a + (b - a) * t)
        if ow is not None:
            ow.append(vw[i] + (vw[i + 1] - vw[i]) * t[:, 0])
        if of is not None:
            z = np.zeros(n, vf.dtype)
            z[-1] = vf[i + 1]
            of.append(z)
    return np.vstack(out), (np.concatenate(ow) if ow is not None else None), (np.concatenate(of) if of is not None else None)


def _warp_layer(pic, L, fn, step):
    """Bake the layer's transform into its vertices, move them with fn(X, Y) -> (X', Y') in canvas units."""
    m = layer_matrix(L)
    k = scale_of(m)
    xy, st = L.arrays["xy"].astype(np.float64), L.arrays["start"].astype(np.int64)
    X = m[0] * xy[:, 0] + m[2] * xy[:, 1] + m[4]
    Y = m[1] * xy[:, 0] + m[3] * xy[:, 1] + m[5]
    P = np.stack([X, Y], 1)
    paths, vw, vf = [], [], []
    has_w, has_f = "vwidth" in L.arrays, "vflag" in L.arrays
    for i in range(len(st) - 1):
        a, b = int(st[i]), int(st[i + 1])
        p, w, f = _densify(P[a:b], step, L.arrays["vwidth"][a:b].astype(np.float64) if has_w else None,
                           L.arrays["vflag"][a:b] if has_f else None)
        if len(p):
            nx, ny = fn(p[:, 0], p[:, 1])
            p = np.stack([nx, ny], 1)
        paths.append(p)
        if has_w:
            vw.append(w)
        if has_f:
            vf.append(f)
    _rebuild(L, paths, vw if has_w else None, vf if has_f else None)
    L.props.pop("transform", None)                                  # baked in; the pen keeps its size
    L.props["width"] = float(L.get("width", 1.0)) * k
    if "stem" in L.props:
        L.props["stem"] = float(L.props["stem"]) * k
    if "width" in L.arrays:
        L.arrays["width"] = (L.arrays["width"].astype(np.float64) * k).astype("<f4")


def _warp(pic, notes, fn, layer, frame, name, step):
    found = layers(pic, layer, None, frame)
    _need_layers(found, layer, name)
    for L in found:
        if L.kind == "vector":
            _warp_layer(pic, L, fn, step if step else max(pic.width, pic.height) / 300.0)
        elif L.kind in ("raster", "height"):
            notes.warn("%s: layer '%s' is a raster and is left as it is (only vector layers can be warped)" % (name, L.id or L.kind))
    drop_grid(pic)


@op("wave", [("amplitude", _float, 0.1, "height of the wave, as a fraction of the picture height"),
             ("length", _float, 1.0, "wave length, as a fraction of the picture width"),
             ("phase", _float, 0.0, "start of the wave, in turns"),
             ("layer", _ids, None, "only these layer ids"), ("frame", _int, None, "only this frame"),
             ("step", _float, None, "longest segment before warping, in canvas units")],
    "Ripple vector shapes up and down (WordArt 'wave'). Strokes are made finer first so they bend. Forgets the grid.")
def op_wave(pic, notes, amplitude, length, phase, layer, frame, step):
    if length <= 0:
        raise bif.BifError("wave: the length must be positive")
    W, H = pic.width, pic.height
    _warp(pic, notes, lambda x, y: (x, y + amplitude * H * np.sin(2 * math.pi * (x / (length * W) + phase))),
          layer, frame, "wave", step)


@op("arc", [("bend", _float, 0.4, "how far the middle rises, as a fraction of the picture height (negative: sinks)"),
            ("layer", _ids, None, "only these layer ids"), ("frame", _int, None, "only this frame"),
            ("step", _float, None, "longest segment before warping, in canvas units")],
    "Bow vector shapes into an arch (WordArt 'arch'). Forgets the grid.")
def op_arc(pic, notes, bend, layer, frame, step):
    W, H = pic.width, pic.height
    _warp(pic, notes, lambda x, y: (x, y - bend * H * (1.0 - (2.0 * x / W - 1.0) ** 2)), layer, frame, "arc", step)


@op("squeeze", [("peak", _float, 1.4, "height scale in the middle"), ("ends", _float, 0.8, "height scale at the two ends"),
                ("layer", _ids, None, "only these layer ids"), ("frame", _int, None, "only this frame"),
                ("step", _float, None, "longest segment before warping, in canvas units")],
    "Make vector shapes taller in the middle than at the ends (WordArt 'squeeze'). Forgets the grid.")
def op_squeeze(pic, notes, peak, ends, layer, frame, step):
    W, H = pic.width, pic.height

    def fn(x, y):
        s = ends + (peak - ends) * (1.0 - (2.0 * x / W - 1.0) ** 2)
        return x, H / 2.0 + (y - H / 2.0) * s
    _warp(pic, notes, fn, layer, frame, "squeeze", step)


# ---------------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------------
def describe():
    lines = []
    for name in sorted(OPS):
        fn, params, doc = OPS[name]
        lines.append("%s  -  %s" % (name, doc))
        for pname, conv, default, help_ in params:
            lines.append("      %-10s %s%s" % (pname, help_, "" if default is REQUIRED or default is None else "  (default %s)" % (default,)))
    return "\n".join(lines)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="bifop", description="Change a BIF: bifop OP [OP ...] reads a BIF from standard input "
                                 "(or -i) and writes the changed BIF to standard output (or -o).",
                                 epilog="Operations: " + ", ".join(sorted(OPS)) + ".  bifop --list describes them.")
    ap.add_argument("ops", nargs="*", metavar="OP", help="name, name:value or name:key=value,key=value")
    ap.add_argument("-i", "--input", metavar="FILE", help="the BIF to change (default: standard input)")
    ap.add_argument("-o", "--output", metavar="FILE", help="write here (default: standard output)")
    ap.add_argument("-l", "--list", action="store_true", help="describe the operations and exit")
    ap.add_argument("-t", "--truncated", action="store_true", help="work on what arrived of a file that ends early")
    ap.add_argument("-V", "--version", action="version", version="bifop " + VERSION)
    a = ap.parse_args(argv)
    if a.list:
        print(describe())
        return 0
    if not a.ops:
        ap.error("no operation given (bifop --list shows them)")
    if not a.output and sys.stdout.isatty():
        ap.error("will not write a BIF to a terminal: use -o FILE, or pipe it into bifout")
    if not a.input and sys.stdin.isatty():
        ap.error("no input: give -i FILE or pipe a BIF in")
    notes = Notes()
    try:
        if a.input:
            pic = bif.load(a.input, allow_truncated=a.truncated)
        else:
            pic = bif.read(sys.stdin.buffer, allow_truncated=a.truncated)
        out = apply(pic, a.ops, notes)
        blob = bif.dumps(out)
    except (bif.BifError, IOError) as e:
        sys.exit("bifop: %s" % e)
    for line in notes.lines:
        sys.stderr.write("bifop: %s\n" % line)
    if a.output:
        with open(a.output, "wb") as f:
            f.write(blob)
    else:
        sys.stdout.buffer.write(blob)
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
