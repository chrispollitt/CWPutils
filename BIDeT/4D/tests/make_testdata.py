#!/usr/bin/env python3
"""Generate ../testdata: BIF files any implementation can be tested against.

  testdata/good/NAME.bif + NAME.json   valid files and what a reader must find in them (bif.summary)
  testdata/bad/NAME.bif                invalid files, each of which a reader must reject; manifest.json
                                       says why (and which ones a reader may still use if it accepts
                                       truncated files)

Run it to regenerate; the committed files are the reference.  The bad files are built from raw chunk
bytes, not through bif.write (which refuses to write them).
"""
from __future__ import print_function

import io
import json
import os
import struct
import sys
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import bif                                              # noqa: E402
from bif import chunk, encode_array, MAGIC              # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), "testdata")
PAL = [{"rgb": [0, 0, 0], "role": "ink"}, {"rgb": [255, 255, 255], "role": "paper"}, {"rgb": [200, 40, 40]}]


def f4(*a):
    return np.array(a, "<f4")


def ramp(h, w):
    """a deterministic test pattern"""
    y, x = np.mgrid[0:h, 0:w]
    return x, y


# ---------------------------------------------------------------------------------------------
# Good files
# ---------------------------------------------------------------------------------------------
def good():
    G = {}

    p = bif.Picture(24, 24)
    p.add_frame()
    G["minimal"] = p

    # the worked example of the spec (section 11)
    p = bif.Picture(24, 24, palette=PAL[:1])
    p.add_frame().layers.append(bif.vector_layer([[(12, 12), (2, 2), (22, 22)], [(12, 6)]], id="strokes", width=2))
    G["spec-example"] = p

    p = bif.Picture(100, 50, unit_aspect=2.0, palette=PAL, background=1,
                    grid={"cols": 10, "rows": 5, "cell_width": 10, "cell_height": 10, "x": 0, "y": 0},
                    meta={"title": "vector, every optional array", "credit": "nobody", "polarity": "dark-on-light"})
    sq = [(10, 10), (40, 10), (40, 40), (10, 40)]
    hole = [(20, 20), (20, 30), (30, 30), (30, 20)]
    p.add_frame().layers.append(bif.vector_layer(
        [sq, hole, [(50, 5), (60, 25), (70, 5)], [(80, 40)]],
        widths=[1, 1, 3, 4], strokes=[0, 0, 2, -1], fills=[1, 1, -1, 2],
        closed=[1, 1, 0, 0], evenodd=[0, 0, 0, 0], groups=[0, 0, -1, -1],
        vwidth=[1, 1, 1, 1, 1, 1, 1, 1, 0.5, 1.5, 1, 0.25],
        vflag=[0, 1, 0, 2, 0, 0, 1, 0, 3, 0, 0, 0], id="shapes", cap="butt", join="miter", miter_limit=3, width=2, fill=None))
    G["vector-full"] = p

    p = bif.Picture(0.5, 0.5)
    p.add_frame().layers.append(bif.vector_layer([], id="nothing"))
    G["vector-empty"] = p

    x, y = ramp(8, 12)
    p = bif.Picture(12, 8, palette=PAL)
    p.add_frame().layers.append(bif.raster_layer(alpha=(x * 20).astype("|u1"), paint=2, resample="nearest",
                                                 bounds=[0, 0, 12, 8], id="mask"))
    G["raster-alpha-paint"] = p

    x, y = ramp(32, 40)
    rgb = np.dstack([x * 6, y * 7, (x + y) * 3]).astype("|u1")
    p = bif.Picture(40, 32)
    p.add_frame().layers.append(bif.raster_layer(alpha=(x / 39.0).astype("<f4"), rgb=rgb, opacity=0.75,
                                                 blend="multiply", transform=[0.5, 0, 0, 0.5, 4, 4]))
    G["raster-rgb-float-alpha"] = p

    x, y = ramp(16, 16)
    p = bif.Picture(16, 16)
    p.add_frame().layers.append(bif.height_layer(np.sqrt((x - 8.0) ** 2 + (y - 8.0) ** 2) * 0.25,
                                                 alpha=((x - 8) ** 2 + (y - 8) ** 2 < 49).astype("|u1") * 255,
                                                 role="shape", id="relief"))
    G["height"] = p

    cp = np.array([[72, 105, 0x4E16, 0xFFFFFFFF], [0, 33, 33, 33]], "<u4")
    fg = np.zeros((2, 4, 4), "|u1")
    fg[:, :, 3] = 255
    fg[0, :, 0] = 255
    bg = np.zeros((2, 4, 4), "|u1")
    p = bif.Picture(40, 40, grid={"cols": 4, "rows": 2, "cell_width": 10, "cell_height": 20})
    p.add_frame().layers.append(bif.cells_layer(cp, fg, bg, np.array([[1, 0, 8, 8], [0, 4, 4, 4]], "|u1")))
    G["cells"] = p

    p = bif.Picture(20, 20, palette=PAL, animation={"loop": 0})
    for i in range(3):
        fr = p.add_frame(100 + 50 * i)
        fr.layers.append(bif.vector_layer([[(2, 2 + 5 * i), (18, 2 + 5 * i)]], width=1 + i, stroke=i % 3, id="line"))
        if i == 1:
            fr.layers.append(bif.raster_layer(alpha=np.full((2, 2), 255, "|u1"), paint=1, bounds=[0, 0, 20, 20]))
    G["animation"] = p

    p = bif.Picture(30, 30, palette=PAL, meta={"x-vendor": {"hint": [1, 2, 3]}, "title": "future-proof"})
    p.head_extra["x-future"] = {"a": 1}
    p.canvas_extra["dpi"] = 96
    fr = p.add_frame(None, **{"x-note": "unknown FRAM key"})
    fr.layers.append(bif.Layer("vector", {"id": "v", "x-extra": True, "blend": "dissolve", "cap": "triangle"},
                               bif.vector_layer([[(1, 1), (9, 9)]]).arrays))
    fr.layers[0].arrays["hint"] = np.arange(3, dtype="<f4")                       # an array nobody defined
    fr.layers.append(bif.Layer("hologram", {"id": "h"}, {"depth": np.ones((2, 2), "<f4")}))   # a kind nobody defined
    p.extra.append(("xtra", b"an unknown ancillary chunk"))
    p.extra.append(("vndR", b"\x00\x01\x02"))
    G["forward-compat"] = p

    p = bif.Picture(30, 30, palette=PAL[:1], meta={"title": u"café 中文 \U0001F42E", "credit": "J. Doe"})
    p.source = ("cow.txt", (b" ____\n< hi >\n ----\n" * 100))
    p.add_frame().layers.append(bif.vector_layer([[(0, 0), (1, 1)]]))
    G["source-and-unicode"] = p

    return G


# ---------------------------------------------------------------------------------------------
# Bad files
# ---------------------------------------------------------------------------------------------
def jb(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":")).encode()


def head(**kw):
    d = {"bif": "1.0", "canvas": {"width": 24, "height": 24}, "palette": PAL[:1]}
    d.update(kw)
    return chunk("HEAD", jb(d))


FRAM = chunk("FRAM", b"{}")
BEND = chunk("BEND", b"")


def layr(**kw):
    d = {"kind": "vector", "id": "v"}
    d.update(kw)
    return chunk("LAYR", jb(d))


def arry(name, arr):
    return chunk("ARRY", encode_array(name, arr))


def raw_arry(hdr, data):
    h = jb(hdr) if isinstance(hdr, dict) else hdr
    return chunk("ARRY", struct.pack("<I", len(h)) + h + data)


XY = f4(0, 0, 1, 1, 2, 0).reshape(3, 2)
ST = np.array([0, 3], "<u4")


def vec(extra=(), xy=XY, st=ST, **props):
    return [layr(**props), arry("xy", xy), arry("start", st)] + list(extra)


def file(*chunks, **kw):
    return kw.get("magic", MAGIC) + b"".join(b for c in chunks for b in (c if isinstance(c, list) else [c]))


def bad():
    B = {}      # name -> (bytes, why, regex the error must match, truncated_ok)

    def add(name, data, why, rx, trunc=False):
        B[name] = (data, why, rx, trunc)

    ok = file(head(), FRAM, vec(), BEND)
    add("empty", b"", "zero bytes", "magic")
    add("bad-magic", b"\x89PNG\r\n\x1a\n" + ok[8:], "a PNG's magic number", "magic")
    add("magic-lf-only", b"\x89BIF\n\x1a\n" + ok[8:], "newlines converted by a text-mode transfer", "magic")
    add("magic-only", MAGIC, "magic and nothing else", "empty|HEAD")
    add("no-head", file(FRAM, vec(), BEND), "first chunk is not HEAD", "HEAD")
    add("second-head", file(head(), FRAM, head(), BEND), "two HEAD chunks", "second HEAD")
    c = bytearray(ok)
    c[len(MAGIC) + 10] ^= 0x01
    add("bad-crc", bytes(c), "one flipped bit in the HEAD payload", "CRC")
    add("truncated-in-chunk", ok[:-30], "ends inside a chunk", "truncat", True)
    add("truncated-in-header", ok[:len(MAGIC) + 5], "ends inside the first chunk header", "truncat")
    add("missing-bend", file(head(), FRAM, vec()), "ends cleanly between chunks but without BEND", "BEND", True)
    add("data-after-bend", ok + chunk("FRAM", b"{}"), "a chunk after BEND", "after BEND")
    add("garbage-after-bend", ok + b"xyz", "three stray bytes after BEND", "after BEND")
    add("bend-not-empty", file(head(), FRAM, vec(), chunk("BEND", b"x")), "BEND with a payload", "BEND")
    add("unknown-critical", file(head(), chunk("XTRA", b"?"), FRAM, vec(), BEND), "unknown chunk with an upper-case first letter", "critical")
    add("bad-chunk-type", file(head(), chunk("FRAM", b"{}")[:4] + b"HE4D" + b"{}" + b"\0\0\0\0", BEND), "chunk type with a digit", "chunk type")
    add("huge-chunk-length", file(head(), struct.pack("<I", 0xFFFFFFF0) + b"ARRY" + b"tiny"), "claims a 4 GB payload", "too big")
    add("version-2", file(head(bif="2.0"), FRAM, vec(), BEND), "major version 2", "version")
    add("version-string", file(head(bif="one"), FRAM, vec(), BEND), "version is not major.minor", "version")
    add("no-canvas", file(chunk("HEAD", jb({"bif": "1.0"})), FRAM, BEND), "HEAD without a canvas", "canvas")
    add("canvas-zero", file(head(canvas={"width": 0, "height": 5}), FRAM, BEND), "zero width", "canvas")
    add("no-frames", file(head(), BEND), "no FRAM at all", "frame")
    add("layr-before-fram", file(head(), vec(), FRAM, BEND), "LAYR before FRAM", "before any FRAM")
    add("arry-before-layr", file(head(), FRAM, arry("xy", XY), BEND), "ARRY before LAYR", "before any LAYR")
    add("layer-no-kind", file(head(), FRAM, chunk("LAYR", b"{}"), BEND), "LAYR without kind", "kind")
    # array headers
    add("dtype-f8", file(head(), FRAM, layr(), raw_arry({"name": "xy", "dtype": "<f8", "shape": [1, 2], "codec": "raw"}, bytes(16)), BEND), "float64 is not allowed", "dtype")
    add("dtype-bogus", file(head(), FRAM, layr(), raw_arry({"name": "xy", "dtype": "banana", "shape": [1], "codec": "raw"}, b""), BEND), "nonsense dtype", "dtype")
    add("data-short", file(head(), FRAM, layr(), raw_arry({"name": "xy", "dtype": "<f4", "shape": [3, 2], "codec": "raw"}, bytes(8)), BEND), "fewer bytes than the shape needs", "bytes")
    add("shape-huge", file(head(), FRAM, layr(), raw_arry({"name": "xy", "dtype": "<f4", "shape": [2 ** 31, 2 ** 31], "codec": "raw"}, b""), BEND), "shape far beyond the limit", "too big")
    add("shape-ndim5", file(head(), FRAM, layr(), raw_arry({"name": "xy", "dtype": "|u1", "shape": [1, 1, 1, 1, 1], "codec": "raw"}, b"x"), BEND), "five dimensions", "shape")
    add("shape-negative", file(head(), FRAM, layr(), raw_arry({"name": "xy", "dtype": "|u1", "shape": [-1], "codec": "raw"}, b""), BEND), "negative dimension", "shape")
    add("shape-float", file(head(), FRAM, layr(), raw_arry({"name": "xy", "dtype": "|u1", "shape": [1.5], "codec": "raw"}, b"x"), BEND), "non-integer dimension", "shape")
    add("codec-unknown", file(head(), FRAM, layr(), raw_arry({"name": "xy", "dtype": "|u1", "shape": [1], "codec": "lzma"}, b"x"), BEND), "unknown codec", "codec")
    z = zlib.compress(bytes(1 << 20))
    add("zlib-bomb", file(head(), FRAM, layr(), raw_arry({"name": "xy", "dtype": "|u1", "shape": [10], "codec": "zlib"}, z), BEND), "10 declared bytes, 1 MB of zeros inside", "zlib")
    add("zlib-short", file(head(), FRAM, layr(), raw_arry({"name": "xy", "dtype": "|u1", "shape": [100], "codec": "zlib"}, zlib.compress(bytes(10))), BEND), "expands to fewer bytes than declared", "zlib")
    add("zlib-garbage", file(head(), FRAM, layr(), raw_arry({"name": "xy", "dtype": "|u1", "shape": [8], "codec": "zlib"}, b"not zlib at all"), BEND), "not a zlib stream", "zlib")
    add("zlib-trailing", file(head(), FRAM, layr(), raw_arry({"name": "xy", "dtype": "|u1", "shape": [4], "codec": "zlib"}, zlib.compress(bytes(4)) + b"junk"), BEND), "bytes after the zlib stream", "zlib")
    add("arry-header-overruns", file(head(), FRAM, layr(), chunk("ARRY", struct.pack("<I", 999) + b"{}")), "header length longer than the chunk", "header")
    add("arry-too-short", file(head(), FRAM, layr(), chunk("ARRY", b"ab")), "two-byte ARRY", "short")
    add("arry-no-name", file(head(), FRAM, layr(), raw_arry({"dtype": "|u1", "shape": [1], "codec": "raw"}, b"x"), BEND), "array without a name", "name")
    add("array-twice", file(head(), FRAM, vec([arry("xy", XY)]), BEND), "the same array twice in a layer", "twice")
    # JSON
    add("json-nan", file(head(), FRAM, chunk("LAYR", b'{"kind":"vector","opacity":NaN}'), BEND), "NaN literal", "JSON")
    add("json-huge-number", file(head(), FRAM, chunk("LAYR", b'{"kind":"vector","opacity":1e999}'), BEND), "number that overflows to infinity", "JSON")
    add("json-not-object", file(chunk("HEAD", b"[1,2]"), FRAM, BEND), "HEAD is an array", "object")
    add("json-bad-utf8", file(chunk("HEAD", b'{"bif":"1.0","meta":{"x":"\xff\xfe"}}'), FRAM, BEND), "invalid UTF-8", "UTF-8")
    add("json-bom", file(chunk("HEAD", b"\xef\xbb\xbf" + jb({"bif": "1.0", "canvas": {"width": 1, "height": 1}})), FRAM, BEND), "byte order mark", "byte order")
    add("json-garbage", file(chunk("HEAD", b"{not json"), FRAM, BEND), "invalid JSON", "JSON")
    # HEAD / layer properties
    add("palette-bad-rgb", file(head(palette=[{"rgb": [300, 0, 0]}]), FRAM, BEND), "colour component 300", "palette")
    add("palette-not-list", file(head(palette="red"), FRAM, BEND), "palette is a string", "palette")
    add("background-oob", file(head(background=5), FRAM, BEND), "background outside the palette", "background")
    add("grid-bad", file(head(grid={"cols": 0, "rows": 1, "cell_width": 1, "cell_height": 1}), FRAM, BEND), "grid with zero columns", "grid")
    add("opacity-range", file(head(), FRAM, vec(opacity=2), BEND), "opacity 2", "opacity")
    add("transform-length", file(head(), FRAM, vec(transform=[1, 0, 0, 1]), BEND), "four-number transform", "transform")
    add("layer-id-twice", file(head(), FRAM, vec(), vec(), BEND), "two layers called v", "duplicate id")
    add("frame-duration", file(head(), chunk("FRAM", b'{"duration":-5}'), BEND), "negative duration", "duration")
    # vector layers
    add("vector-no-xy", file(head(), FRAM, layr(), arry("start", ST), BEND), "missing xy", "xy")
    add("vector-xy-3d", file(head(), FRAM, vec(xy=np.zeros((3, 3), "<f4")), BEND), "(N, 3) vertices", "xy")
    add("vector-start-decreasing", file(head(), FRAM, vec(st=np.array([0, 2, 1, 3], "<u4")), BEND), "offsets go backwards", "decrease")
    add("vector-start-end", file(head(), FRAM, vec(st=np.array([0, 2], "<u4")), BEND), "last offset is not N", "begin at 0")
    add("vector-start-begin", file(head(), FRAM, vec(st=np.array([1, 3], "<u4")), BEND), "first offset is not 0", "begin at 0")
    add("vector-nan-vertex", file(head(), FRAM, vec(xy=np.array([[0, 0], [np.nan, 1], [2, 0]], "<f4")), BEND), "NaN vertex", "NaN")
    add("vector-width-length", file(head(), FRAM, vec([arry("width", f4(1, 2))]), BEND), "two widths for one path", "width")
    add("vector-paint-oob", file(head(), FRAM, vec([arry("stroke", np.array([5], "<i2"))]), BEND), "stroke paint 5 in a one-colour palette", "palette")
    add("vector-no-palette", file(head(palette=[]), FRAM, vec(), BEND), "stroked paths but no palette", "palette")
    add("vector-fill-no-palette", file(head(palette=[]), FRAM, vec(fill=0, width=0), BEND), "default fill but no palette", "palette")
    add("vector-group-split", file(head(), FRAM, vec(xy=np.zeros((6, 2), "<f4"), st=np.array([0, 2, 4, 6], "<u4"),
                                                    extra=[arry("group", np.array([0, 1, 0], "<i4"))]), BEND), "group 0 is split by group 1", "adjacent")
    add("vector-vflag-length", file(head(), FRAM, vec([arry("vflag", np.zeros(5, "|u1"))]), BEND), "vflag longer than the vertices", "vflag")
    add("vector-flags-dtype", file(head(), FRAM, vec([arry("flags", np.array([1], "<u4"))]), BEND), "flags as 32-bit", "flags")
    # rasters
    add("raster-empty", file(head(), FRAM, layr(kind="raster"), BEND), "raster with no arrays", "alpha or rgb")
    add("raster-alpha-range", file(head(), FRAM, layr(kind="raster", paint=0), arry("alpha", np.full((2, 2), 1.5, "<f4")), BEND), "float alpha 1.5", "alpha")
    add("raster-size-mismatch", file(head(), FRAM, layr(kind="raster"), arry("alpha", np.zeros((2, 2), "|u1")), arry("rgb", np.zeros((3, 3, 3), "|u1")), BEND), "alpha and rgb differ in size", "differ")
    add("raster-rgb-4", file(head(), FRAM, layr(kind="raster"), arry("rgb", np.zeros((2, 2, 4), "|u1")), BEND), "rgb with four channels", "rgb")
    add("raster-paint-oob", file(head(), FRAM, layr(kind="raster", paint=3), arry("alpha", np.zeros((2, 2), "|u1")), BEND), "paint 3 in a one-colour palette", "paint")
    add("raster-bounds", file(head(), FRAM, layr(kind="raster", bounds=[0, 0, 0, 5]), arry("alpha", np.zeros((2, 2), "|u1")), BEND), "zero-width bounds", "bounds")
    add("raster-zero-pixels", file(head(), FRAM, layr(kind="raster"), arry("alpha", np.zeros((0, 4), "|u1")), BEND), "no pixels", "pixel")
    add("height-no-z", file(head(), FRAM, layr(kind="height"), BEND), "height layer without z", "z")
    add("cells-fg-shape", file(head(), FRAM, layr(kind="cells"), arry("cp", np.zeros((2, 3), "<u4")), arry("fg", np.zeros((2, 3, 3), "|u1")), BEND), "fg is RGB, not RGBA", "fg")
    return B


# ---------------------------------------------------------------------------------------------
def main():
    gd, bd = os.path.join(OUT, "good"), os.path.join(OUT, "bad")
    for d in (gd, bd):
        if not os.path.isdir(d):
            os.makedirs(d)
    for name, pic in sorted(good().items()):
        path = os.path.join(gd, name + ".bif")
        bif.save(pic, path)
        back = bif.load(path)
        want = json.dumps(bif.summary(pic), sort_keys=True)
        got = json.dumps(bif.summary(back), sort_keys=True)
        assert want == got, "%s does not round-trip" % name
        with io.open(os.path.join(gd, name + ".json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(bif.summary(back), f, indent=1, sort_keys=True, ensure_ascii=False)
            f.write("\n")
    manifest = {}
    for name, (data, why, rx, trunc) in sorted(bad().items()):
        with open(os.path.join(bd, name + ".bif"), "wb") as f:
            f.write(data)
        manifest[name] = {"why": why, "error": rx, "usable_if_truncated_accepted": trunc}
    with io.open(os.path.join(bd, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
        f.write("\n")
    print("wrote %d good and %d bad files to %s" % (len(good()), len(manifest), OUT))


if __name__ == "__main__":
    main()
