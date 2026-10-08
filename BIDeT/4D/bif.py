#!/usr/bin/env python3
"""bif: read, write and check BIF (BIDeT Intermediate Format) files.

The format is described in BIF-SPEC.md.  This is the reference implementation: one file, numpy only,
Python 3.7+ (numpy 1.16+).  It is meant to be imported and also runs as a tool:

    bif.py info FILE...        what is in it
    bif.py check FILE...       validate (exit status 1 if any is invalid)
    bif.py chunks FILE         the raw chunk list (type, size, offset)

Reading and writing:

    import bif
    pic = bif.load("x.bif")                       # or bif.read(fp), bif.loads(bytes)
    layer = pic.frames[0].layers[0]
    for pts in layer.paths():                     # numpy (n, 2) views
        ...
    pic = bif.Picture(960, 400, palette=[{"rgb": [0, 0, 0], "role": "ink"}])
    pic.add_frame().layers.append(bif.vector_layer([[(2, 2), (20, 20)]], width=2))
    bif.save(pic, "y.bif")

Arrays returned by load are read-only views of the file's bytes (copy before changing).
Every problem with a file is a BifError.  Nothing in a file can make the reader allocate more than
`max_array` bytes for one array, or run unbounded code.
"""
from __future__ import print_function

import hashlib
import io
import json
import math
import re
import struct
import sys
import zlib

import numpy as np

VERSION = "1.0"
MAGIC = b"\x89BIF\r\n\x1a\n"

MAX_ARRAY_BYTES = 1 << 30           # largest array a reader will build
MAX_JSON_BYTES = 64 << 20           # largest HEAD / FRAM / LAYR payload
MAX_NDIM = 4
COMPRESS_MIN = 512                  # smaller arrays are stored raw

DTYPES = dict((s, np.dtype(s)) for s in ("|u1", "<u2", "<u4", "<i2", "<i4", "<f4"))
KINDS = ("vector", "raster", "height", "cells")
BLENDS = ("normal", "multiply", "screen", "erase")
CAPS = ("round", "butt", "square")
JOINS = ("round", "miter", "bevel")
RESAMPLES = ("smooth", "nearest")
CRITICAL = ("HEAD", "FRAM", "LAYR", "ARRY", "BEND")


class BifError(Exception):
    """The file is not a valid BIF (or cannot be written as one)."""


class Truncated(BifError):
    """The file ends early (in a chunk, or without BEND)."""


# ---------------------------------------------------------------------------------------------
# Chunks
# ---------------------------------------------------------------------------------------------
def chunk(ctype, payload):
    """One chunk, as bytes."""
    if isinstance(ctype, str):
        ctype = ctype.encode("ascii")
    if len(ctype) != 4 or not ctype.isalpha():
        raise BifError("bad chunk type %r" % (ctype,))
    if len(payload) > 0xFFFFFFFF:
        raise BifError("chunk %s too big (%d bytes)" % (ctype.decode(), len(payload)))
    crc = zlib.crc32(ctype + payload) & 0xFFFFFFFF
    return struct.pack("<I", len(payload)) + ctype + payload + struct.pack("<I", crc)


def _read_exact(fp, n):
    """Up to n bytes, reading in blocks so a lying length cannot make us allocate it all."""
    out, got = [], 0
    while got < n:
        b = fp.read(min(n - got, 1 << 20))
        if not b:
            break
        out.append(b)
        got += len(b)
    return b"".join(out)


def chunk_limit(ctype, max_array):
    if ctype in ("ARRY", "srce"):
        return max_array + (max_array >> 10) + (1 << 20)
    return MAX_JSON_BYTES


def iter_chunks(fp, max_array=MAX_ARRAY_BYTES, magic=True):
    """Yield (type, payload, offset) for each chunk of a BIF stream, CRC checked.  Raises Truncated
    if the stream ends inside a chunk; a stream that ends between chunks just stops."""
    off = 0
    if magic:
        m = _read_exact(fp, len(MAGIC))
        if m != MAGIC:
            raise BifError("not a BIF file (bad magic number)")
        off = len(MAGIC)
    while True:
        h = _read_exact(fp, 8)
        if not h:
            return
        if len(h) < 8:
            raise Truncated("truncated chunk header at offset %d" % off)
        n, t = struct.unpack("<I4s", h)
        if len(t) != 4 or not t.isalpha():
            raise BifError("bad chunk type %r at offset %d" % (t, off))
        t = t.decode("ascii")
        if n > chunk_limit(t, max_array):
            raise BifError("chunk %s at offset %d is too big (%d bytes)" % (t, off, n))
        payload = _read_exact(fp, n)
        c = _read_exact(fp, 4)
        if len(payload) < n or len(c) < 4:
            raise Truncated("truncated %s chunk at offset %d" % (t, off))
        if struct.unpack("<I", c)[0] != (zlib.crc32(h[4:] + payload) & 0xFFFFFFFF):
            raise BifError("bad CRC in %s chunk at offset %d" % (t, off))
        yield t, payload, off
        off += 12 + n


# ---------------------------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------------------------
def _json_obj(data, what):
    def bad_const(c):
        raise ValueError("%s is not allowed" % c)

    def float_(s):
        f = float(s)
        if math.isinf(f) or math.isnan(f):
            raise ValueError("number out of range")
        return f

    try:
        s = bytes(data).decode("utf-8")
    except UnicodeDecodeError:
        raise BifError("%s: not UTF-8" % what)
    if s.startswith(u"﻿"):
        raise BifError("%s: byte order mark" % what)
    try:
        o = json.loads(s, parse_constant=bad_const, parse_float=float_)
    except (ValueError, RecursionError) as e:
        raise BifError("%s: bad JSON (%s)" % (what, e))
    if not isinstance(o, dict):
        raise BifError("%s: JSON is not an object" % what)
    return o


def _default(o):
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError("cannot store %s in a BIF" % type(o).__name__)


def _json_bytes(obj):
    try:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False, default=_default).encode("utf-8")
    except (TypeError, ValueError) as e:
        raise BifError("cannot encode JSON: %s" % e)


# ---------------------------------------------------------------------------------------------
# Arrays
# ---------------------------------------------------------------------------------------------
def _is_int(x):
    return isinstance(x, (int, np.integer)) and not isinstance(x, bool)


def _num(x):
    return isinstance(x, (int, float, np.integer, np.floating)) and not isinstance(x, bool) and math.isfinite(x)


def encode_array(name, arr, codec="auto", level=6):
    """The payload of an ARRY chunk."""
    a = np.asarray(arr)
    dt = a.dtype.newbyteorder("<")
    if dt.str not in DTYPES:
        raise BifError("array %s: dtype %s is not allowed in a BIF" % (name, a.dtype))
    if a.ndim < 1 or a.ndim > MAX_NDIM:
        raise BifError("array %s: needs 1 to %d dimensions" % (name, MAX_NDIM))
    a = np.ascontiguousarray(a, dtype=dt)
    data = a.tobytes()
    if codec == "auto":
        codec = "zlib" if len(data) >= COMPRESS_MIN else "raw"
    if codec == "zlib":
        z = zlib.compress(data, level)
        if len(z) < len(data):
            data = z
        else:
            codec = "raw"
    elif codec != "raw":
        raise BifError("unknown codec %r" % (codec,))
    hdr = _json_bytes({"name": name, "dtype": dt.str, "shape": list(a.shape), "codec": codec})
    hdr += b" " * (-(4 + len(hdr)) % 8)             # data start 8-byte aligned in the payload
    return struct.pack("<I", len(hdr)) + hdr + data


def decode_array(payload, max_array=MAX_ARRAY_BYTES):
    """(name, ndarray) from the payload of an ARRY chunk."""
    if len(payload) < 4:
        raise BifError("ARRY: too short")
    hlen = struct.unpack_from("<I", payload, 0)[0]
    if hlen > len(payload) - 4:
        raise BifError("ARRY: header longer than the chunk")
    h = _json_obj(payload[4:4 + hlen], "ARRY header")
    name = h.get("name")
    if not isinstance(name, str) or not name:
        raise BifError("ARRY: no name")
    dt = DTYPES.get(h.get("dtype"))
    if dt is None:
        raise BifError("array %s: dtype %r is not allowed" % (name, h.get("dtype")))
    shape = h.get("shape")
    if (not isinstance(shape, list) or not 1 <= len(shape) <= MAX_NDIM
            or not all(_is_int(d) and d >= 0 for d in shape)):
        raise BifError("array %s: bad shape %r" % (name, shape))
    n = 1
    for d in shape:
        n *= d
        if n * dt.itemsize > max_array:
            raise BifError("array %s: %s is too big (limit %d bytes)" % (name, shape, max_array))
    nbytes = n * dt.itemsize
    codec = h.get("codec", "raw")
    data = memoryview(payload)[4 + hlen:]
    if codec == "raw":
        if len(data) != nbytes:
            raise BifError("array %s: %d bytes of data, shape needs %d" % (name, len(data), nbytes))
        raw = data
    elif codec == "zlib":
        d = zlib.decompressobj()
        try:
            raw = d.decompress(data, nbytes + 1)
        except zlib.error as e:
            raise BifError("array %s: bad zlib data (%s)" % (name, e))
        if len(raw) != nbytes or not d.eof or d.unused_data:
            raise BifError("array %s: zlib data does not expand to exactly %d bytes" % (name, nbytes))
    else:
        raise BifError("array %s: unknown codec %r" % (name, codec))
    if n == 0:
        return name, np.zeros(shape, dtype=dt)
    return name, np.frombuffer(raw, dtype=dt, count=n).reshape(shape)


# ---------------------------------------------------------------------------------------------
# The picture
# ---------------------------------------------------------------------------------------------
class Layer(object):
    """kind, props (every JSON key of the LAYR chunk, including `kind`) and arrays (name -> ndarray).
    layer.xy is a shortcut for layer.arrays["xy"]."""

    def __init__(self, kind, props=None, arrays=None):
        self.props = dict(props or {})
        self.props["kind"] = kind
        self.arrays = dict(arrays or {})

    @property
    def kind(self):
        return self.props.get("kind")

    @property
    def id(self):
        return self.props.get("id")

    def get(self, key, default=None):
        return self.props.get(key, default)

    def __getattr__(self, name):
        try:
            return self.__dict__["arrays"][name]
        except KeyError:
            raise AttributeError(name)

    def paths(self):
        """vector layers: a list of (n, 2) views, one per path."""
        xy, st = self.arrays["xy"], self.arrays["start"]
        return [xy[st[i]:st[i + 1]] for i in range(len(st) - 1)]

    def __repr__(self):
        return "<Layer %s %s %s>" % (self.kind, self.id or "", dict((k, v.shape) for k, v in self.arrays.items()))


class Frame(object):
    """props (the FRAM JSON, e.g. {"duration": 100}) and layers, bottom first."""

    def __init__(self, duration=None, props=None):
        self.props = dict(props or {})
        if duration is not None:
            self.props["duration"] = duration
        self.layers = []

    @property
    def duration(self):
        return self.props.get("duration")

    def __repr__(self):
        return "<Frame %s %r>" % (self.duration, self.layers)


class Picture(object):
    """HEAD fields (width, height, unit_aspect, grid, palette, background, animation, meta), the frames,
    `source` (None or (name, bytes), the srce chunk), `head_extra` (unknown HEAD keys) and `extra`
    (unknown ancillary chunks, [(type, payload)], written back before BEND)."""

    def __init__(self, width, height, unit_aspect=1.0, grid=None, palette=None, background=None,
                 animation=None, meta=None):
        self.width, self.height, self.unit_aspect = width, height, unit_aspect
        self.grid, self.background, self.animation = grid, background, animation
        self.palette = [] if palette is None else palette      # as given: check() judges it
        self.meta = {} if meta is None else meta
        self.frames = []
        self.source = None
        self.head_extra = {}
        self.canvas_extra = {}
        self.extra = []
        self.truncated = False

    def add_frame(self, duration=None, **props):
        f = Frame(duration, props)
        self.frames.append(f)
        return f

    @property
    def layers(self):
        """The layers of frame 0 (a still image has no other)."""
        return self.frames[0].layers if self.frames else []

    def head(self):
        h = dict(self.head_extra)
        h["bif"] = VERSION
        c = {"width": self.width, "height": self.height}
        if self.unit_aspect != 1.0:
            c["unit_aspect"] = self.unit_aspect
        h["canvas"] = c
        if self.grid:
            h["grid"] = self.grid
        if self.palette:
            h["palette"] = self.palette
        if self.background is not None:
            h["background"] = self.background
        if self.animation:
            h["animation"] = self.animation
        if self.meta:
            h["meta"] = self.meta
        return h

    def __repr__(self):
        return "<Picture %sx%s %d frame(s)>" % (self.width, self.height, len(self.frames))


def _picture_from_head(h):
    ver = h.get("bif")
    m = re.match(r"^(\d+)\.(\d+)$", ver) if isinstance(ver, str) else None
    if not m:
        raise BifError("HEAD: bad or missing version %r" % (ver,))
    if int(m.group(1)) != int(VERSION.split(".")[0]):
        raise BifError("unsupported BIF version %s (this reader does 1.x)" % ver)
    c = h.get("canvas")
    if not isinstance(c, dict):
        raise BifError("HEAD: no canvas")
    pic = Picture(c.get("width"), c.get("height"), c.get("unit_aspect", 1.0), h.get("grid"),
                  h.get("palette"), h.get("background"), h.get("animation"), h.get("meta"))
    pic.head_extra = dict((k, v) for k, v in h.items()
                          if k not in ("bif", "canvas", "grid", "palette", "background", "animation", "meta"))
    pic.canvas_extra = dict((k, v) for k, v in c.items() if k not in ("width", "height", "unit_aspect"))
    return pic


# Constructors ---------------------------------------------------------------------------------
def paths_to_csr(paths):
    """A list of (n, 2) point lists -> (xy, start) arrays for a vector layer."""
    parts = [np.asarray(p, dtype="<f4").reshape(-1, 2) for p in paths]
    xy = np.concatenate(parts) if parts else np.zeros((0, 2), "<f4")
    start = np.zeros(len(parts) + 1, "<u4")
    if parts:
        start[1:] = np.cumsum([len(p) for p in parts])
    return xy, start


def vector_layer(paths, widths=None, strokes=None, fills=None, closed=None, evenodd=None, groups=None,
                 vwidth=None, vflag=None, **props):
    """paths: list of point lists.  The keyword props are the layer's (width=2, stroke=0, fill=None,
    cap=, join=, id=, ...); the other arguments are per-path (or per-vertex) arrays."""
    xy, start = paths_to_csr(paths)
    a = {"xy": xy, "start": start}
    n = len(start) - 1
    if widths is not None:
        a["width"] = np.asarray(widths, "<f4")
    if strokes is not None:
        a["stroke"] = np.asarray(strokes, "<i2")
    if fills is not None:
        a["fill"] = np.asarray(fills, "<i2")
    if closed is not None or evenodd is not None:
        f = np.zeros(n, "|u1")
        if closed is not None:
            f |= np.asarray(closed, bool).astype("|u1") * 1
        if evenodd is not None:
            f |= np.asarray(evenodd, bool).astype("|u1") * 2
        a["flags"] = f
    if groups is not None:
        a["group"] = np.asarray(groups, "<i4")
    if vwidth is not None:
        a["vwidth"] = np.asarray(vwidth, "<f4")
    if vflag is not None:
        a["vflag"] = np.asarray(vflag, "|u1")
    return Layer("vector", props, a)


def raster_layer(alpha=None, rgb=None, **props):
    """props: bounds=[x0, y0, x1, y1], paint=, resample=, id=, ..."""
    a = {}
    if alpha is not None:
        a["alpha"] = np.asarray(alpha)
    if rgb is not None:
        a["rgb"] = np.asarray(rgb, "|u1")
    return Layer("raster", props, a)


def height_layer(z, alpha=None, **props):
    a = {"z": np.asarray(z, "<f4")}
    if alpha is not None:
        a["alpha"] = np.asarray(alpha)
    return Layer("height", props, a)


def cells_layer(cp, fg=None, bg=None, attr=None, **props):
    props.setdefault("visible", False)
    props.setdefault("role", "source")
    a = {"cp": np.asarray(cp, "<u4")}
    if fg is not None:
        a["fg"] = np.asarray(fg, "|u1")
    if bg is not None:
        a["bg"] = np.asarray(bg, "|u1")
    if attr is not None:
        a["attr"] = np.asarray(attr, "|u1")
    return Layer("cells", props, a)


# ---------------------------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------------------------
def check(pic):
    """(errors, warnings): lists of strings.  A picture with errors must not be written or used."""
    E, W = [], []

    def err(where, msg):
        E.append("%s: %s" % (where, msg))

    if not (_num(pic.width) and pic.width > 0 and _num(pic.height) and pic.height > 0):
        err("canvas", "width and height must be positive numbers")
    if not (_num(pic.unit_aspect) and pic.unit_aspect > 0):
        err("canvas", "unit_aspect must be a positive number")
    if pic.grid is not None:
        g = pic.grid
        if not isinstance(g, dict):
            err("grid", "must be an object")
        else:
            for k in ("cols", "rows"):
                if not (_is_int(g.get(k)) and g[k] > 0):
                    err("grid", "%s must be a positive integer" % k)
            for k in ("cell_width", "cell_height"):
                if not (_num(g.get(k)) and g[k] > 0):
                    err("grid", "%s must be a positive number" % k)
            for k in ("x", "y"):
                if k in g and not _num(g[k]):
                    err("grid", "%s must be a number" % k)
    pal = pic.palette
    if not isinstance(pal, list) or len(pal) > 65535:
        err("palette", "must be a list of at most 65535 entries")
        pal = []
    for i, e in enumerate(pal):
        rgb = e.get("rgb") if isinstance(e, dict) else None
        if not (isinstance(rgb, list) and len(rgb) == 3 and all(_is_int(v) and 0 <= v <= 255 for v in rgb)):
            err("palette[%d]" % i, "needs rgb: [r, g, b] of integers 0-255")
    npal = len(pal)
    bg = pic.background
    if bg is not None and not (_is_int(bg) and 0 <= bg < npal):
        err("background", "%r is not a palette index" % (bg,))
    if pic.animation is not None and not isinstance(pic.animation, dict):
        err("animation", "must be an object")
    if not isinstance(pic.meta, dict):
        err("meta", "must be an object")
    if not pic.frames:
        err("frames", "a BIF needs at least one frame")
    for fi, f in enumerate(pic.frames):
        d = f.props.get("duration")
        if d is not None and not (_num(d) and d >= 0):
            err("frame %d" % fi, "duration must be a non-negative number")
        seen = set()
        for li, L in enumerate(f.layers):
            where = "frame %d layer %d" % (fi, li)
            _check_layer(L, where, npal, E, W)
            if L.id is not None:
                if not isinstance(L.id, str):
                    err(where, "id must be a string")
                elif L.id in seen:
                    err(where, "duplicate id %r" % L.id)
                seen.add(L.id)
    return E, W


def _check_layer(L, where, npal, E, W):
    def err(msg):
        E.append("%s (%s): %s" % (where, L.kind, msg))

    p = L.props
    if not isinstance(L.kind, str):
        err("kind must be a string")
        return
    op = p.get("opacity", 1)
    if not (_num(op) and 0 <= op <= 1):
        err("opacity must be 0 to 1")
    if p.get("blend", "normal") not in BLENDS:
        W.append("%s: unknown blend %r (drawn as normal)" % (where, p.get("blend")))
    if "visible" in p and not isinstance(p["visible"], bool):
        err("visible must be true or false")
    t = p.get("transform")
    if t is not None and not (isinstance(t, list) and len(t) == 6 and all(_num(v) for v in t)):
        err("transform must be six numbers")
    if L.kind not in KINDS:
        W.append("%s: unknown layer kind %r (ignored)" % (where, L.kind))
        return
    A = L.arrays
    for k, a in A.items():
        if a.dtype.kind == "f" and a.size and not np.isfinite(a).all():
            err("array %s has NaN or infinite values" % k)

    def need(name, dts, nd=None, shape=None):
        a = A.get(name)
        if a is None:
            err("missing array %s" % name)
            return None
        if a.dtype.newbyteorder("<").str not in dts:
            err("array %s must be %s, not %s" % (name, "/".join(dts), a.dtype.newbyteorder("<").str))
            return None
        if nd is not None and a.ndim != nd:
            err("array %s must have %d dimension(s)" % (name, nd))
            return None
        if shape is not None and a.shape != tuple(shape):
            err("array %s has shape %s, expected %s" % (name, a.shape, tuple(shape)))
            return None
        return a

    def opt(name, dts, nd=None, shape=None):
        return need(name, dts, nd, shape) if name in A else None

    def paint_range(a, what):
        if a is not None and a.size and (int(a.min()) < -1 or int(a.max()) >= npal):
            err("%s has palette indices outside 0..%d" % (what, npal - 1))

    def bounds_ok():
        b = p.get("bounds")
        if b is None:
            return
        if not (isinstance(b, list) and len(b) == 4 and all(_num(v) for v in b) and b[2] > b[0] and b[3] > b[1]):
            err("bounds must be [x0, y0, x1, y1] with x1 > x0 and y1 > y0")
        if p.get("resample", "smooth") not in RESAMPLES:
            W.append("%s: unknown resample %r (drawn smooth)" % (where, p.get("resample")))

    if L.kind == "vector":
        xy = need("xy", ("<f4",), 2)
        st = need("start", ("<u4",), 1)
        if xy is not None and xy.shape[1] != 2:
            err("array xy must be (N, 2)")
            xy = None
        if xy is None or st is None:
            return
        if len(st) < 1:
            err("start must have at least one element")
            return
        N, P = len(xy), len(st) - 1
        if int(st[0]) != 0 or int(st[-1]) != N:
            err("start must begin at 0 and end at N=%d" % N)
        elif (np.diff(st.astype(np.int64)) < 0).any():
            err("start must not decrease")
        for nm, dt in (("width", "<f4"), ("stroke", "<i2"), ("fill", "<i2"), ("flags", "|u1"),
                       ("group", "<i4")):
            opt(nm, (dt,), 1, (P,))
        for nm, dt in (("vwidth", "<f4"), ("vflag", "|u1")):
            opt(nm, (dt,), 1, (N,))
        if not _num(p.get("width", 1.0)) or p.get("width", 1.0) < 0:
            err("width must be a non-negative number")
        paint_range(A.get("stroke"), "array stroke")
        paint_range(A.get("fill"), "array fill")
        w = A.get("width")
        stroking = bool(P) and (bool((w > 0).any()) if w is not None and w.shape == (P,) else p.get("width", 1.0) > 0)
        s0, f0 = p.get("stroke", 0), p.get("fill")
        if "stroke" not in A and stroking and not (_is_int(s0) and -1 <= s0 < npal):
            err("default stroke paint %r is not a palette index" % (s0,))
        if "fill" not in A and f0 is not None and P and not (_is_int(f0) and -1 <= f0 < npal):
            err("default fill paint %r is not a palette index" % (f0,))
        for k in ("cap", "join"):
            if k in p and p[k] not in (CAPS if k == "cap" else JOINS):
                W.append("%s: unknown %s %r" % (where, k, p[k]))
        g = A.get("group")
        if g is not None and g.shape == (P,) and P:
            g = g.astype(np.int64)
            first = np.nonzero((g >= 0) & np.concatenate(([True], g[1:] != g[:-1])))[0]
            ids = g[first]
            if len(np.unique(ids)) != len(ids):
                err("paths of a group must be adjacent")
    elif L.kind == "raster":
        a = A.get("alpha")
        c = A.get("rgb")
        if a is None and c is None:
            err("needs an alpha or rgb array")
            return
        if a is not None:
            a = need("alpha", ("|u1", "<f4"), 2)
        if c is not None:
            c = need("rgb", ("|u1",), 3)
            if c is not None and c.shape[2] != 3:
                err("array rgb must be (H, W, 3)")
                c = None
        if a is not None and c is not None and a.shape != c.shape[:2]:
            err("alpha %s and rgb %s differ in size" % (a.shape, c.shape))
        ref = a if a is not None else c
        if ref is not None and (ref.shape[0] < 1 or ref.shape[1] < 1):
            err("a raster needs at least one pixel")
        if a is not None and a.dtype.kind == "f" and a.size and (float(a.min()) < 0 or float(a.max()) > 1):
            err("float alpha must be within 0 to 1")
        if c is None and not (_is_int(p.get("paint", 0)) and 0 <= p.get("paint", 0) < npal):
            err("without an rgb array the paint must be a palette index")
        bounds_ok()
    elif L.kind == "height":
        z = need("z", ("<f4",), 2)
        if z is not None and (z.shape[0] < 1 or z.shape[1] < 1):
            err("a height map needs at least one sample")
        if z is not None:
            opt("alpha", ("|u1", "<f4"), 2, z.shape)
        bounds_ok()
    elif L.kind == "cells":
        cp = need("cp", ("<u4",), 2)
        if cp is not None:
            for nm in ("fg", "bg"):
                a = opt(nm, ("|u1",), 3, cp.shape + (4,))
            opt("attr", ("|u1",), 2, cp.shape)


def summary(pic):
    """A JSON-able description of a picture, with a SHA-256 of every array's bytes: what test data
    files record so another implementation can check it read the same thing."""
    def arr(a):
        a = np.ascontiguousarray(a, dtype=a.dtype.newbyteorder("<"))
        return {"dtype": a.dtype.str, "shape": list(a.shape), "sha256": hashlib.sha256(a.tobytes()).hexdigest()}

    return {
        "bif": VERSION,
        "canvas": [pic.width, pic.height, pic.unit_aspect],
        "grid": pic.grid, "palette": pic.palette, "background": pic.background,
        "animation": pic.animation, "meta": pic.meta,
        "source": None if pic.source is None else [pic.source[0], hashlib.sha256(pic.source[1]).hexdigest()],
        "frames": [{
            "props": f.props,
            "layers": [{"props": L.props, "arrays": dict((k, arr(v)) for k, v in sorted(L.arrays.items()))}
                       for L in f.layers]} for f in pic.frames],
    }


# ---------------------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------------------
def read(fp, max_array=MAX_ARRAY_BYTES, allow_truncated=False, validate=True):
    """A Picture from a binary stream.  allow_truncated: a stream cut short (no BEND, or cut inside
    a chunk) gives what arrived, with pic.truncated set, instead of an error; a last layer that did not
    arrive whole is dropped."""
    pic = None
    frame = layer = None
    ended = False
    try:
        for t, payload, off in iter_chunks(fp, max_array):
            if ended:
                raise BifError("data after BEND")
            if pic is None:
                if t != "HEAD":
                    raise BifError("the first chunk must be HEAD, not %s" % t)
                pic = _picture_from_head(_json_obj(payload, "HEAD"))
            elif t == "HEAD":
                raise BifError("second HEAD chunk at offset %d" % off)
            elif t == "FRAM":
                frame = Frame(props=_json_obj(payload, "FRAM"))
                pic.frames.append(frame)
                layer = None
            elif t == "LAYR":
                if frame is None:
                    raise BifError("LAYR before any FRAM")
                props = _json_obj(payload, "LAYR")
                if not isinstance(props.get("kind"), str):
                    raise BifError("LAYR without a kind")
                layer = Layer(props["kind"], props)
                frame.layers.append(layer)
            elif t == "ARRY":
                if layer is None:
                    raise BifError("ARRY before any LAYR")
                name, a = decode_array(payload, max_array)
                if name in layer.arrays:
                    raise BifError("array %s twice in one layer" % name)
                layer.arrays[name] = a
            elif t == "BEND":
                if payload:
                    raise BifError("BEND must be empty")
                ended = True
            elif t == "srce":
                pic.source = _decode_source(payload, max_array)
            elif t[0].isupper():
                raise BifError("unknown critical chunk %s at offset %d" % (t, off))
            else:
                pic.extra.append((t, payload))
        if pic is None:
            raise BifError("empty file (no HEAD chunk)")
        if not ended:
            raise Truncated("file ends without BEND")
    except Truncated:
        if ended:
            raise BifError("data after BEND")
        if not (allow_truncated and pic is not None):
            raise
        pic.truncated = True
    if validate:
        E, W = check(pic)
        if E and pic.truncated and pic.frames and pic.frames[-1].layers:
            pic.frames[-1].layers.pop()             # the layer that was arriving when the stream stopped
            E, W = check(pic)
        if E:
            raise BifError("%d problem(s): %s" % (len(E), "; ".join(E[:5]) + (" ..." if len(E) > 5 else "")))
    return pic


def _decode_source(payload, max_array):
    if len(payload) < 4:
        raise BifError("srce: too short")
    hlen = struct.unpack_from("<I", payload, 0)[0]
    if hlen > len(payload) - 4:
        raise BifError("srce: header longer than the chunk")
    h = _json_obj(payload[4:4 + hlen], "srce header")
    data = bytes(payload[4 + hlen:])
    size = h.get("size")
    if not (_is_int(size) and 0 <= size <= max_array):
        raise BifError("srce: bad size")
    if h.get("codec", "raw") == "zlib":
        d = zlib.decompressobj()
        try:
            data = d.decompress(data, size + 1)
        except zlib.error as e:
            raise BifError("srce: bad zlib data (%s)" % e)
        if not d.eof or d.unused_data:
            raise BifError("srce: bad zlib data")
    elif h.get("codec", "raw") != "raw":
        raise BifError("srce: unknown codec")
    if len(data) != size:
        raise BifError("srce: size mismatch")
    return (h.get("name") if isinstance(h.get("name"), str) else "", data)


def load(path, **kw):
    with open(path, "rb") as f:
        return read(f, **kw)


def loads(data, **kw):
    return read(io.BytesIO(data), **kw)


# ---------------------------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------------------------
def write(pic, fp, compress=True, validate=True):
    """Write a Picture to a binary stream.  compress=False stores every array raw; a number is the zlib level."""
    if validate:
        E, W = check(pic)
        if E:
            raise BifError("invalid picture: " + "; ".join(E[:5]))
    level = 6 if compress is True else (int(compress) if compress else 0)
    codec = "auto" if level else "raw"
    fp.write(MAGIC)
    fp.write(chunk("HEAD", _json_bytes(_head_with_extra(pic))))
    if pic.source is not None:
        name, data = pic.source
        z = zlib.compress(data, level) if level and len(data) >= COMPRESS_MIN else data
        use = "zlib" if z is not data and len(z) < len(data) else "raw"
        hdr = _json_bytes({"name": name, "codec": use, "size": len(data)})
        fp.write(chunk("srce", struct.pack("<I", len(hdr)) + hdr + (z if use == "zlib" else data)))
    for f in pic.frames:
        fp.write(chunk("FRAM", _json_bytes(f.props)))
        for L in f.layers:
            fp.write(chunk("LAYR", _json_bytes(L.props)))
            for name, a in L.arrays.items():
                fp.write(chunk("ARRY", encode_array(name, a, codec, level or 6)))
    for t, payload in pic.extra:
        fp.write(chunk(t, payload))
    fp.write(chunk("BEND", b""))


def _head_with_extra(pic):
    h = pic.head()
    if pic.canvas_extra:
        h["canvas"].update(pic.canvas_extra)
    return h


def save(pic, path, **kw):
    with open(path, "wb") as f:
        write(pic, f, **kw)


def dumps(pic, **kw):
    b = io.BytesIO()
    write(pic, b, **kw)
    return b.getvalue()


# ---------------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------------
def _describe(pic, out):
    p = out.write
    p("BIF %s  canvas %s x %s units (unit aspect %s)\n" % (VERSION, pic.width, pic.height, pic.unit_aspect))
    if pic.grid:
        g = pic.grid
        p("grid    %s x %s cells of %s x %s\n" % (g.get("cols"), g.get("rows"), g.get("cell_width"), g.get("cell_height")))
    if pic.palette:
        p("palette %s\n" % "  ".join("%d:#%02x%02x%02x%s" % (i, e["rgb"][0], e["rgb"][1], e["rgb"][2],
                                                           "(" + e["role"] + ")" if e.get("role") else "")
                                      for i, e in enumerate(pic.palette[:16])) + (" ..." if len(pic.palette) > 16 else "") + "\n")
    for k in sorted(pic.meta):
        v = json.dumps(pic.meta[k], ensure_ascii=False)
        p("meta    %s = %s\n" % (k, v if len(v) < 100 else v[:97] + "..."))
    if pic.source is not None:
        p("source  %r, %d bytes kept\n" % (pic.source[0], len(pic.source[1])))
    if pic.truncated:
        p("WARNING truncated file\n")
    for fi, f in enumerate(pic.frames):
        p("frame %d%s\n" % (fi, "  %s ms" % f.duration if f.duration is not None else ""))
        for li, L in enumerate(f.layers):
            extra = ""
            if L.kind == "vector" and "start" in L.arrays:
                extra = "  %d paths, %d vertices" % (len(L.start) - 1, len(L.xy))
            elif L.kind in ("raster", "height") and L.arrays:
                a = next(iter(L.arrays.values()))
                extra = "  %d x %d" % (a.shape[1], a.shape[0])
            elif L.kind == "cells" and "cp" in L.arrays:
                extra = "  %d x %d cells" % (L.cp.shape[1], L.cp.shape[0])
            flags = "".join(" " + k + "=" + str(L.props[k]) for k in ("role", "blend", "opacity", "visible") if k in L.props)
            p("  layer %d %-7s %s%s%s\n" % (li, L.kind, L.id or "", extra, flags))
            for name, a in L.arrays.items():
                p("      %-8s %s %s\n" % (name, a.dtype.str, list(a.shape)))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="bif.py", description="Inspect and validate BIF files.")
    sub = ap.add_subparsers(dest="cmd")
    for name, h in (("info", "describe each file"), ("check", "validate each file"),
                    ("chunks", "list the raw chunks")):
        s = sub.add_parser(name, help=h)
        s.add_argument("files", nargs="+", metavar="FILE", help="a .bif file, or - for standard input")
        if name == "info":
            s.add_argument("--json", action="store_true", help="the machine-readable summary (with array hashes)")
        if name == "check":
            s.add_argument("-t", "--truncated", action="store_true", help="accept files that end early")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    status = 0
    for fn in a.files:
        label = "<stdin>" if fn == "-" else fn
        try:
            fp = sys.stdin.buffer if fn == "-" else open(fn, "rb")
        except IOError as e:
            print("%s: %s" % (label, e), file=sys.stderr)
            status = 1
            continue
        try:
            if a.cmd == "chunks":
                for t, payload, off in iter_chunks(fp):
                    print("%8d  %s  %9d bytes  %s" % (off, t, len(payload), "critical" if t[0].isupper() else "ancillary"))
            elif a.cmd == "check":
                pic = read(fp, allow_truncated=a.truncated)
                E, W = check(pic)
                print("%s: ok%s%s" % (label, " (truncated)" if pic.truncated else "", "".join("\n  warning: " + w for w in W)))
            else:
                pic = read(fp)
                if a.json:
                    print(json.dumps(summary(pic), indent=1, sort_keys=True, ensure_ascii=False))
                else:
                    if len(a.files) > 1:
                        print("== %s" % label)
                    _describe(pic, sys.stdout)
        except BifError as e:
            print("%s: %s" % (label, e), file=sys.stderr)
            status = 1
        finally:
            if fp is not sys.stdin.buffer:
                fp.close()
    return status


if __name__ == "__main__":
    sys.exit(main())
