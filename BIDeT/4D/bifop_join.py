"""bifop_join: put pictures together: one after another in time (`join`), or one on top of another (`overlay`).

    bifop join:b.bif                    the frames of b.bif after this picture's; the canvas is the larger of the two
    bifop overlay:caption.bif           the layers of caption.bif on every frame (here: the captions of a time machine)
    bifop overlay:c.bif,first=26,x=40   ... from frame 26 on, 40 units in

The palettes are merged (the colours of the other picture are added, and its layers are renumbered to match), and the
other picture is drawn on this one's page.  `join` centres the smaller canvas in the larger.  An `overlay` of several
frames goes frame by frame onto the frames it covers (the first frame of it on `first`, ...); one frame goes on all of them.

The library functions (merge_palette, append, overlay) are what bifop's operations, and the time machine, use.
"""
from __future__ import print_function

import copy

import numpy as np

import bif
import bifop
from bifop import op, REQUIRED, _float, _int, _ids


def merge_palette(dst, src):
    """Add what `src` has and `dst` has not to dst's palette.  Returns the new index of each of src's entries."""
    mapping = []
    for e in src.palette:
        rgb = list(e["rgb"])
        found = None
        for i, d in enumerate(dst.palette):
            if list(d["rgb"]) == rgb and d.get("role") == e.get("role"):
                found = i
                break
        if found is None:
            n = dict(e)
            if n.get("role") in ("ink", "paper") and any(d.get("role") == n["role"] for d in dst.palette):
                del n["role"]                                    # (one ink and one paper: bifout --ink must find only one)
            dst.palette.append(n)
            found = len(dst.palette) - 1
        mapping.append(found)
    return mapping


def remap_layer(L, mapping):
    """Renumber the palette indices a layer uses (arrays are replaced, never written into: they may be shared)."""
    if not mapping:
        return
    m = np.asarray(mapping, "<i2")
    if L.kind == "vector":
        for key in ("stroke", "fill"):
            a = L.arrays.get(key)
            if a is not None:
                L.arrays[key] = np.where(a >= 0, m[np.clip(a, 0, len(m) - 1)], a).astype("<i2")
            elif isinstance(L.props.get(key), int) and 0 <= L.props[key] < len(m):
                L.props[key] = int(m[L.props[key]])
            elif key == "stroke" and key not in L.props:
                L.props["stroke"] = int(m[0])                    # (the default stroke is paint 0)
    elif L.kind == "raster" and "rgb" not in L.arrays:
        L.props["paint"] = int(m[min(int(L.props.get("paint", 0)), len(m) - 1)])


def _shift(pic, dx, dy):
    if dx or dy:
        bifop.post_transform(pic, (1.0, 0.0, 0.0, 1.0, float(dx), float(dy)))
        if pic.grid:
            pic.grid["x"], pic.grid["y"] = pic.grid.get("x", 0) + dx, pic.grid.get("y", 0) + dy


def append(pic, other):
    """The frames of `other` after pic's, on the larger of the two canvases (each centred).  Changes pic; returns the
    (dx, dy) that pic's and other's contents were moved by, in canvas units."""
    if abs(float(pic.unit_aspect) - float(other.unit_aspect)) > 1e-9:
        raise bif.BifError("join: the pictures have different unit aspects")
    other = bifop.clone(other)
    bifop.drop_grid(other)                                        # (its character grid would be in the wrong place)
    W, H = max(pic.width, other.width), max(pic.height, other.height)
    d1 = (int((W - pic.width) // 2), int((H - pic.height) // 2))
    d2 = (int((W - other.width) // 2), int((H - other.height) // 2))
    _shift(pic, *d1)
    _shift(other, *d2)
    mapping = merge_palette(pic, other)
    for f in other.frames:
        for L in f.layers:
            remap_layer(L, mapping)
    pic.frames.extend(other.frames)
    pic.width, pic.height = W, H
    if not pic.animation:
        pic.animation = other.animation or {"loop": 0}
    return d1, d2


def _unique_id(frame, id_):
    """`id_`, or that with a number, so that it is not the id of a layer already in the frame (ids are unique per frame)."""
    taken = set(L.id for L in frame.layers if L.id)
    if not id_ or id_ not in taken:
        return id_
    n = 2
    while "%s-%d" % (id_, n) in taken:
        n += 1
    return "%s-%d" % (id_, n)


def overlay(pic, other, first=0, last=-1, x=0.0, y=0.0):
    """The layers of `other` on top of pic's frames first..last (negative: from the end; inclusive).  Several frames of
    `other` go on one frame each, from `first`; a single frame goes on all of them.  other is moved by (x, y)."""
    n = len(pic.frames)
    first = first + n if first < 0 else first
    last = last + n if last < 0 else last
    if not (0 <= first <= last < n):
        raise bif.BifError("overlay: frames %d to %d are not in a picture of %d frames" % (first, last, n))
    other = bifop.clone(other)
    bifop.drop_grid(other)
    _shift(other, x, y)
    mapping = merge_palette(pic, other)
    for f in other.frames:
        for L in f.layers:
            remap_layer(L, mapping)
    single = len(other.frames) == 1
    for i in range(first, last + 1):
        src = other.frames[0] if single else (other.frames[i - first] if i - first < len(other.frames) else None)
        if src is None:
            break
        for L in src.layers:
            props = copy.deepcopy(L.props)
            if props.get("id"):
                props["id"] = _unique_id(pic.frames[i], props["id"])
            pic.frames[i].layers.append(bif.Layer(L.kind, props, dict(L.arrays)))


def _load(path):
    try:
        return bif.load(path)
    except (IOError, OSError) as e:
        raise bif.BifError("%s" % e)


@op("join", [("file", _ids, REQUIRED, "a .bif whose frames follow this picture's (several: a.bif+b.bif)")],
    "Plays the other picture(s) after this one: their frames are added, the colours merged, and the canvas is the larger of the "
    "two (the smaller is centred).  Both must have the same unit aspect.")
def op_join(pic, notes, file):
    for path in file:
        append(pic, _load(path))
    if pic.animation is None:
        pic.animation = {"loop": 0}


@op("overlay", [("file", _ids, REQUIRED, "a .bif whose layers go on top of this picture's frames"),
                ("first", _int, 0, "the first frame it covers (negative: from the end)"),
                ("last", _int, -1, "the last frame it covers (default: the last frame)"),
                ("x", _float, 0.0, "move it this far right"), ("y", _float, 0.0, "move it this far down")],
    "Draws the other picture's layers on top of frames of this one (colours merged).  A one-frame picture goes on every "
    "frame it covers; a longer one goes frame by frame.  For captions, tickers and logos.")
def op_overlay(pic, notes, file, first, last, x, y):
    for path in file:
        overlay(pic, _load(path), first, last, x, y)
