#!/usr/bin/env python3
"""Tests for ttfglyphs.py, bifin_text.py and bifin.py.   python tests/test_bifin.py"""
from __future__ import print_function

import io
import os
import struct
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import bif                                          # noqa: E402
import bifin                                        # noqa: E402
import bifin_text                                   # noqa: E402
import bifout                                       # noqa: E402
import bifrender                                    # noqa: E402
import ttfglyphs                                    # noqa: E402

BIDET = os.path.dirname(ROOT)
SAMPLES = os.path.join(ROOT, "samples")


def sample(name):
    with io.open(os.path.join(SAMPLES, name), "rb") as f:
        return f.read()


SAMPLE_NAMES = sorted(n for n in os.listdir(SAMPLES) if n.endswith((".txt", ".ans"))) if os.path.isdir(SAMPLES) else []


def imp(data, name=None, **kw):
    return bifin_text.import_text(data, name=name, **kw)


def layer(pic, id):
    for L in pic.layers:
        if L.id == id:
            return L
    return None


def try_import(path, name):
    if not os.path.isdir(path):
        return None
    sys.path.insert(0, path)
    try:
        return __import__(name)
    except ImportError:
        return None


unascii = try_import(os.path.join(HERE, "reference"), "unascii_v3")      # the frozen v3 (the oracle)
FONT = bifin_text.find_font()


@unittest.skipIf(not FONT, "no monospace font found")
class Outlines(unittest.TestCase):
    def setUp(self):
        try:
            self.tt = ttfglyphs.TrueType(FONT)
        except ttfglyphs.Unsupported:
            self.skipTest("the font found is not a TrueType-outline font")

    def test_outlines_match_freetype(self):
        size = 160
        pil = ImageFont.truetype(FONT, size)
        s = size / float(self.tt.units_per_em)
        asc, desc = pil.getmetrics()
        W, H = int(size * 1.2), asc + desc + 10
        for ch in "AgjQ8@%&#{}|mW":
            want = Image.new("L", (W, H), 0)
            ImageDraw.Draw(want).text((0, 0), ch, font=pil, fill=255)
            acc = np.zeros((H, W), np.int8)
            for c in self.tt.contours(ord(ch), tol=0.5 / s):
                im = Image.new("L", (W, H), 0)
                ImageDraw.Draw(im).polygon([(x * s, asc - y * s) for x, y in c], fill=1)
                acc ^= np.asarray(im, np.int8)
            a, b = np.asarray(want) > 127, acc > 0
            iou = (a & b).sum() / float((a | b).sum())
            self.assertGreater(iou, 0.75, "%r: IoU %.2f" % (ch, iou))

    def test_composite_glyphs_and_missing_characters(self):
        e, ee = self.tt.contours(ord("e")), self.tt.contours(0xE9)          # e, e-acute: a base glyph plus an accent
        if self.tt.glyph_id(0xE9):
            self.assertGreater(len(ee), len(e) - 1)
        self.assertEqual(self.tt.glyph_id(0x10FFFF), 0)                      # .notdef
        self.assertTrue(self.tt.contours(0x10FFFF))                          # drawn as a box, as a renderer would
        self.assertEqual(self.tt.contours(ord(" ")), [])

    def test_polygons_are_closed_lists_of_points(self):
        for p in self.tt.contours(ord("g")):
            self.assertGreaterEqual(len(p), 3)
            self.assertNotEqual(p[0], p[-1])

    def test_unsupported_fonts_are_refused(self):
        d = tempfile.mkdtemp()
        for name, blob in (("junk.ttf", b"not a font at all"), ("cff.otf", b"OTTO" + bytes(100)), ("short.ttf", b"\x00\x01\x00\x00\x00")):
            p = os.path.join(d, name)
            with open(p, "wb") as f:
                f.write(blob)
            with self.assertRaises(ttfglyphs.Unsupported):
                ttfglyphs.TrueType(p)


class Sauce(unittest.TestCase):
    def record(self, **kw):
        r = bytearray(128)
        r[0:7] = b"SAUCE00"
        for key, off, n in (("title", 7, 35), ("author", 42, 20), ("group", 62, 20), ("date", 82, 8)):
            v = kw.get(key, "").encode("cp437").ljust(n, b" " if key != "date" else b" ")
            r[off:off + n] = v[:n]
        r[94], r[95] = kw.get("datatype", 1), kw.get("filetype", 1)
        struct.pack_into("<4H", r, 96, kw.get("tinfo1", 0), kw.get("tinfo2", 0), 0, 0)
        r[104] = kw.get("ncomments", 0)
        return bytes(r)

    def test_fields(self):
        data = b"hello\r\n" + b"\x1a" + self.record(title="Cow", author="J. Doe", group="ACiD", tinfo1=40)
        s = bifin_text.parse_sauce(data)
        self.assertEqual((s["title"], s["author"], s["group"], s["tinfo1"]), ("Cow", "J. Doe", "ACiD", 40))
        self.assertIsNone(bifin_text.parse_sauce(b"no record here"))
        self.assertIsNone(bifin_text.parse_sauce(b"x" * 300))

    def test_comments(self):
        com = b"COMNT" + b"first line".ljust(64) + b"second".ljust(64)
        data = b"art\x1a" + com + self.record(ncomments=2)
        self.assertEqual(bifin_text.parse_sauce(data)["comments"], ["first line", "second"])

    def test_credit_title_width_and_text(self):
        art = ("ab" * 30 + "\r\n" + "cd" * 30 + "\r\n").encode()
        data = art + b"\x1a" + self.record(title="My Art", author="Anon", group="grp", tinfo1=40)
        pic = imp(data, name="x.ans", cells=True)
        self.assertEqual(pic.meta["title"], "My Art")
        self.assertEqual(pic.meta["credit"], "Anon, grp")
        self.assertEqual(pic.meta["source"]["sauce"]["tinfo1"], 40)
        self.assertEqual(pic.grid["cols"], 40)                               # the file says it is 40 wide: wrapped there
        self.assertNotIn("SAUCE", "".join(chr(c) for c in layer(pic, "cells").cp.ravel() if c))

    def test_credit_survives_a_round_trip_and_bifout(self):
        data = b"/\\\r\n\x1a" + self.record(author="Someone")
        pic = bif.loads(bif.dumps(imp(data)))
        self.assertEqual(pic.meta["credit"], "Someone")


class ImportBasics(unittest.TestCase):
    def test_all_samples_import_save_load_render(self):
        self.assertTrue(SAMPLE_NAMES)
        for name in SAMPLE_NAMES:
            for kw in ({}, {"outlines": False}):
                pic = imp(sample(name), name=name, **kw)
                E, W = bif.check(pic)
                self.assertEqual(E, [], name)
                again = bif.loads(bif.dumps(pic))
                self.assertEqual(len(again.layers), len(pic.layers))
                r = bifrender.render(again, scale=1)
                self.assertEqual((r.W, r.H), (int(pic.width + 0.999), int(pic.height + 0.999)))
                self.assertTrue(np.isfinite(r.alpha).all())

    def test_cells_layer_is_the_art(self):
        for name in ("cow.txt", "figlet_big.txt", "dragon_lolcat.ans", "blocks_color.ans", "braille.txt"):
            data = sample(name)
            pic = imp(data, name=name)
            c = layer(pic, "cells")
            self.assertEqual((c.get("visible"), c.get("role")), (False, "source"))
            text, enc = bifin_text.decode2(data)
            grid = bifin_text.parse(text, 80 if name.endswith(".ans") else 0, glyphs=name.endswith(".ans"))
            self.assertEqual(c.cp.shape, (grid.rows, grid.cols))
            for y in range(grid.rows):
                got = "".join(chr(v) if v else " " for v in c.cp[y])
                self.assertEqual(got, "".join(grid.ch[y]), (name, y))
            self.assertEqual(pic.grid["cols"], grid.cols)
            self.assertEqual(pic.grid["rows"], grid.rows)

    def test_cells_can_be_left_out(self):
        self.assertIsNone(layer(imp(sample("cow.txt"), cells=False), "cells"))

    def test_modes(self):
        cow = sample("cow.txt")
        self.assertEqual({L.id for L in imp(cow).layers}, {"strokes", "text", "cells"})
        self.assertEqual(imp(cow).meta["mode"], "line")
        t = imp(cow, mode="tone")
        self.assertEqual(t.meta["mode"], "tone")
        self.assertEqual({L.id for L in t.layers}, {"tone", "cells"})
        mix = {L.id for L in imp(cow, mode="mix").layers}
        self.assertTrue({"strokes", "cells"} <= mix, mix)                    # line strokes (plus a tone layer if there is tone art)
        b = imp(sample("blocks_color.ans"), name="blocks_color.ans")
        self.assertEqual((b.meta["mode"], b.meta["polarity"]), ("block", "light-on-dark"))
        self.assertIsNotNone(layer(b, "picture"))
        self.assertEqual(imp(sample("blocks_color.ans"), mode="lineart").meta["mode"], "tone")     # lines asked for: outline it

    def test_shading_is_hatched(self):
        data = b"XXXXXXXX\r\nXXXXXXXX\r\nXXXXXXXX\r\n"
        pic = imp(data)
        self.assertIsNotNone(layer(pic, "hatch"))
        self.assertIsNone(layer(imp(data, shade=""), "hatch"))

    def test_nothing_drawn_gives_a_valid_empty_picture(self):
        for data in (b"", b"\n\n", b"   ", b"\x1b[31m\x1b[0m"):
            pic = imp(data)
            self.assertEqual(bif.check(pic)[0], [])
            self.assertEqual([L.id for L in pic.layers if L.get("visible") is not False], [])

    def test_hostile_input(self):
        cases = [bytes(range(256)) * 3, bytes((i * 37 + 11) % 256 for i in range(3000)), b"\x1b[" * 200 + b"\x1b]" + b"x" * 500,
                 b"\x1b[38;2;999;0;0mX\x1b[48;5;300mY", b"abc\x1aSAUCE00" + bytes(100), b"\0" * 50, u"日本語 ｱｲｳ".encode("utf-8"),
                 b"\x1b[9999;9999H*\x1b[9999S", b"-" * 5000]
        for data in cases:
            pic = imp(data)
            bif.loads(bif.dumps(pic))

    def test_nul_in_dos_art_is_ignored(self):
        pic = imp(b"a\0b\r\n/\\", name="x.ans")                           # v3 raised KeyError(0) here
        self.assertEqual("".join(chr(v) if v else " " for v in layer(pic, "cells").cp[0]), "ab")

    def test_metadata(self):
        data = sample("cow.txt")
        pic = imp(data, name=os.path.join("some", "dir", "cow.txt"))
        src = pic.meta["source"]
        self.assertEqual((src["kind"], src["name"], src["encoding"], src["bytes"]), ("text", "cow.txt", "utf-8", len(data)))
        self.assertEqual(len(src["sha256"]), 64)
        self.assertEqual((pic.meta["generator"]["name"], pic.meta["polarity"]), ("bifin", "dark-on-light"))
        self.assertEqual(imp(sample("dragon_lolcat.ans")).meta["source"]["kind"], "ansi")
        self.assertEqual(imp(data, weight=2.0, mode="line").meta["generator"]["args"], {"weight": 2.0, "mode": "line"})
        self.assertIsNone(pic.source)
        kept = bif.loads(bif.dumps(imp(data, name="cow.txt", keep_source=True)))
        self.assertEqual(kept.source, ("cow.txt", data))

    def test_options_object_is_not_changed(self):
        o = bifin_text.Options()
        bifin_text.import_grid(bifin_text.parse(u"/\\", 0), o)
        self.assertIsNone(o.ink)
        self.assertIsNone(o.paper)

    def test_palette_and_roles(self):
        pic = imp(sample("cow.txt"))
        self.assertEqual(pic.palette[:2], [{"rgb": [0, 0, 0], "role": "ink"}, {"rgb": [255, 255, 255], "role": "paper"}])
        self.assertEqual(pic.background, 1)
        pic = imp(sample("cow.txt"), ink=(10, 20, 30), paper=(250, 240, 230))
        self.assertEqual(pic.palette[0]["rgb"], [10, 20, 30])
        r = bifrender.render(pic, scale=1)
        self.assertEqual(tuple(r.flatten()[0, 0]), (250, 240, 230))
        # and a manipulator-style re-theme of the written file needs no re-import:
        r = bifrender.render(pic, scale=1, ink=(255, 0, 0))
        self.assertEqual(r.color, (255.0, 0.0, 0.0))

    def test_colour_makes_a_palette_and_mono_does_not(self):
        data = sample("dragon_lolcat.ans")
        col, mono = imp(data), imp(data, color="off")
        self.assertGreater(len(col.palette), 10)
        self.assertEqual(len(mono.palette), 2)
        self.assertGreater(len(set(layer(col, "strokes").stroke.tolist())), 5)
        self.assertTrue(bifrender.render(mono, scale=1).uniform)
        self.assertFalse(bifrender.render(col, scale=1).uniform)

    def test_pen_weight_and_bold_letters(self):
        thin, heavy = imp(sample("cow.txt")), imp(sample("cow.txt"), weight=2.0)
        self.assertGreater(float(layer(heavy, "strokes").width.mean()), float(layer(thin, "strokes").width.mean()) * 1.9)
        self.assertEqual(float(layer(thin, "text").width.max()), 0.0)
        self.assertGreater(float(layer(heavy, "text").width.min()), 0.0)             # letters thicken with the pen

    def test_cell_size_scales_the_units(self):
        a, b = imp(sample("cow.txt"), cell_w=12), imp(sample("cow.txt"), cell_w=24)
        self.assertAlmostEqual(b.width / float(a.width), 2.0, delta=0.1)
        self.assertEqual((a.grid["cell_width"], b.grid["cell_width"]), (12, 24))

    def test_no_crop_keeps_the_margin(self):
        a, b = imp(sample("cow.txt")), imp(sample("cow.txt"), crop=False)
        self.assertGreater(b.width, a.width)
        self.assertEqual((b.grid["x"], b.grid["y"]), (12, 12))

    def test_vector_letters_are_sharp_at_any_scale_and_the_raster_fallback_is_not_needed(self):
        if bifin_text.Outlines(bifin_text.Glyphs(12, 24, None)).ok:
            pic = imp(sample("cow.txt"))
            self.assertIsNotNone(layer(pic, "text"))
            self.assertIsNone(layer(pic, "text-mask"))
            r = bifrender.render(pic, scale=4)
            self.assertEqual(r.W, pic.width * 4)

    def test_without_outlines_letters_are_a_raster(self):
        pic = imp(sample("cow.txt"), outlines=False)
        self.assertIsNone(layer(pic, "text"))
        self.assertEqual(layer(pic, "text-mask").kind, "raster")

    def test_without_ttfglyphs_letters_are_a_raster(self):
        saved = bifin_text.ttfglyphs
        bifin_text.ttfglyphs = None
        try:
            pic = imp(sample("cow.txt"))
        finally:
            bifin_text.ttfglyphs = saved
        self.assertIsNone(layer(pic, "text"))
        self.assertIsNotNone(layer(pic, "text-mask"))

    def test_blocks_among_letters_use_the_mask_layer(self):
        pic = imp(u"Hello ▀▄ /\\_ world".encode("utf-8"), mode="line")
        self.assertIsNotNone(layer(pic, "text-mask"))
        self.assertEqual([L.id for L in pic.layers if L.kind == "vector"].count("text"), 1 if bifin_text.Outlines(bifin_text.Glyphs(12, 24, None)).ok else 0)

    def test_big_art_is_drawn_smaller(self):
        pic = imp(("/" * 200 + "\r\n") * 200, cell_w=40)
        self.assertLess(pic.grid["cell_width"], 40)


class ToneVectors(unittest.TestCase):
    """Tone mode (picture-style art) as traced vector lines."""

    def test_the_tone_layer_is_vector_and_the_raster_is_still_available(self):
        v = imp(sample("tone80.txt"), mode="tone")
        r = imp(sample("tone80.txt"), mode="tone", tone_vectors=False)
        self.assertEqual((layer(v, "tone").kind, layer(r, "tone").kind), ("vector", "raster"))
        self.assertEqual({L.id for L in v.layers}, {"tone", "cells"})
        self.assertLess(len(bif.dumps(v)), len(bif.dumps(r)))                  # a few hundred vertices, not a bitmap

    def test_lines_fade_out_with_the_edge(self):
        L = layer(imp(sample("tone80.txt"), mode="tone"), "tone")
        vw = L.vwidth
        self.assertTrue(0.0 < float(vw.min()) < 0.5)                           # the faint ends taper to a hair
        self.assertLessEqual(float(vw.max()), 1.0)
        self.assertGreater(float((vw == 1.0).mean()), 0.3)                     # and strong edges are full pen
        self.assertEqual(L.get("cap"), None)                                   # round caps: the default

    def test_everything_lies_inside_the_canvas(self):
        for name in ("tone80.txt", "tone70_alt.txt", "tone100_inv.txt", "braille.txt", "chafa_ascii.txt"):
            pic = imp(sample(name), mode="tone")
            L = layer(pic, "tone")
            self.assertGreaterEqual(float(L.xy.min()), -1.0, name)
            self.assertLessEqual(float(L.xy[:, 0].max()), pic.width + 1.0, name)
            self.assertLessEqual(float(L.xy[:, 1].max()), pic.height + 1.0, name)

    def test_it_is_a_picture_at_any_size(self):
        pic = imp(sample("tone80.txt"), mode="tone")
        a, b = bifrender.render(pic, scale=1), bifrender.render(pic, scale=4)
        self.assertEqual((b.W, b.H), (a.W * 4, a.H * 4))
        self.assertAlmostEqual(float(b.alpha.sum()) / float(a.alpha.sum()), 16.0, delta=3.5)       # length x width
        # sharp: the biggest rendering has pure paper between the lines and solid ink on them
        self.assertGreater(float((b.alpha > 0.99).sum()), 0.3 * float((b.alpha > 0.5).sum()))

    def test_colour_follows_the_picture(self):
        pic = imp(sample("dragon_lolcat.ans"), name="dragon_lolcat.ans", mode="tone", color="on")
        self.assertGreater(len(pic.palette), 8)
        self.assertGreater(len(set(layer(pic, "tone").stroke.tolist())), 4)
        self.assertFalse(bifrender.render(pic, scale=1).uniform)
        mono = imp(sample("dragon_lolcat.ans"), name="dragon_lolcat.ans", mode="tone", color="off")
        self.assertEqual(len(mono.palette), 2)
        self.assertTrue(bifrender.render(mono, scale=1).uniform)

    def test_grey_stays_the_ink_colour(self):
        pic = imp(sample("tone80.txt"), mode="tone", color="on")             # no colour in it: nothing to cut up
        self.assertEqual(len(pic.palette), 2)
        L = layer(pic, "tone")
        self.assertNotIn("stroke", L.arrays)

    def test_every_sample_in_tone_mode(self):
        for name in SAMPLE_NAMES:
            pic = imp(sample(name), name=name, mode="tone")
            self.assertEqual(bif.check(pic)[0], [], name)
            r = bifrender.render(bif.loads(bif.dumps(pic)), scale=1)
            self.assertTrue(np.isfinite(r.alpha).all(), name)

    def test_nothing_to_trace_makes_no_layer(self):
        pic = imp(b"x", mode="tone")
        self.assertIsNone(layer(pic, "tone"))
        self.assertEqual(bif.check(pic)[0], [])

    def test_same_input_same_bytes(self):
        a = bif.dumps(imp(sample("tone80.txt"), mode="tone"))
        self.assertEqual(a, bif.dumps(imp(sample("tone80.txt"), mode="tone")))

    def test_mix_has_tone_lines_and_strokes(self):
        art = (u"/\\_/\\\n" + u"@%#*+=-:.  \n" * 6).encode("utf-8")
        pic = imp(art, mode="mix")
        self.assertIsNotNone(layer(pic, "strokes"))
        t = layer(pic, "tone")
        self.assertTrue(t is None or t.kind == "vector")

    def test_options_reach_the_tracer(self):
        base = imp(sample("tone80.txt"), mode="tone")
        faint = imp(sample("tone80.txt"), mode="tone", detail=0.02)            # more edges count
        none = imp(sample("tone80.txt"), mode="tone", levels=0, detail=5.0)    # almost no edge is strong enough
        n = lambda p: len(layer(p, "tone").xy) if layer(p, "tone") else 0      # (vertices: fragments join up as more edges count)
        self.assertGreater(n(faint), n(base))
        self.assertLess(n(none), n(base))
        heavy = imp(sample("tone80.txt"), mode="tone", weight=2.0)
        self.assertAlmostEqual(layer(heavy, "tone").get("width"), 2.0 * layer(base, "tone").get("width"), places=5)

    def test_flag_on_the_command_line(self):
        rc, blob, e = run("-m", "tone", "--tone-raster", input=sample("tone80.txt"))
        self.assertEqual(rc, 0, e)
        self.assertEqual(layer(bif.loads(blob), "tone").kind, "raster")
        rc, blob, e = run("-m", "tone", input=sample("tone80.txt"))
        self.assertEqual(layer(bif.loads(blob), "tone").kind, "vector")


@unittest.skipIf(unascii is None, "tests/reference/unascii_v3.py not found")
class ParityWithUnascii(unittest.TestCase):
    """bifin | render at scale 1 against what unascii draws, per sample."""

    def v3(self, name, data):
        a = name.endswith(".ans")
        o = unascii.Options(crop=True)
        return unascii.render_grid_color(unascii.parse(unascii.decode2(data)[0], 80 if a else 0, glyphs=a), o)

    def test_every_sample(self):
        for name in SAMPLE_NAMES:
            data = sample(name)
            ink, rgb = self.v3(name, data)
            for kw, tol in (({"outlines": False, "tone_vectors": False}, 2e-3), ({"tone_vectors": False}, 8e-3)):
                pic = imp(data, name=name, **kw)
                r = bifrender.render(pic, scale=1)
                label = "%s %s" % (name, kw)
                self.assertEqual(r.alpha.shape, ink.shape, label)
                d = np.abs(r.alpha - ink)
                self.assertLess(float(d.mean()), tol, "%s: mean difference %.5f" % (label, float(d.mean())))
                if rgb is not None and not r.uniform:
                    both = (r.alpha > 0.5) & (ink > 0.5)
                    if both.any():
                        cd = np.abs(r.color_u8()[both].astype(int) - rgb[both].astype(int)).mean()
                        self.assertLess(float(cd), 3.0, "%s: colour differs by %.2f" % (label, cd))

    def test_raster_letters_are_exactly_unascii(self):
        for name in ("cow.txt", "figlet_big.txt", "hello.txt", "toilet_future.txt", "tone80.txt", "blocks_color.ans"):
            data = sample(name)
            ink, rgb = self.v3(name, data)
            r = bifrender.render(imp(data, name=name, outlines=False, tone_vectors=False), scale=1)
            self.assertLess(float(np.abs(r.alpha - ink).max()), 0.3, name)


def run(*args, **kw):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, kw.pop("tool", "bifin.py"))] + list(args), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    out, err = p.communicate(kw.get("input"))
    return p.returncode, out, err


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_file_to_file(self):
        out = os.path.join(self.dir, "cow.bif")
        rc, o, e = run(os.path.join(SAMPLES, "cow.txt"), "-o", out, "-v")
        self.assertEqual(rc, 0, e)
        pic = bif.load(out)
        self.assertEqual(pic.meta["source"]["name"], "cow.txt")
        self.assertIn(b"layer(s)", e)

    def test_pipe_in_and_out_and_into_bifout(self):
        rc, blob, e = run(input=sample("cow.txt"))
        self.assertEqual((rc, blob[:8]), (0, bif.MAGIC), e)
        rc, png, e = run("-", "-o", "-", input=blob, tool="bifout.py")
        self.assertEqual((rc, png[:4]), (0, b"\x89PNG"), e)
        direct = io.BytesIO()
        bifout.convert(imp(sample("cow.txt")), "png", direct)
        self.assertEqual(Image.open(io.BytesIO(png)).size, Image.open(io.BytesIO(direct.getvalue())).size)

    def test_options_reach_the_importer(self):
        rc, blob, e = run("-m", "tone", "-c", "20", "--ink", "red", "--paper", "#102030", "--no-cells", "--keep-source", input=sample("cow.txt"))
        self.assertEqual(rc, 0, e)
        pic = bif.loads(blob)
        self.assertEqual(pic.meta["mode"], "tone")
        self.assertEqual(pic.grid["cell_width"], 20)
        self.assertEqual((pic.palette[0]["rgb"], pic.palette[1]["rgb"]), ([255, 0, 0], [16, 32, 48]))
        self.assertIsNone(layer(pic, "cells"))
        self.assertEqual(pic.source[1], sample("cow.txt"))

    def test_errors(self):
        rc, o, e = run(os.path.join(self.dir, "missing.txt"))
        self.assertEqual((rc, o), (1, b""))
        self.assertIn(b"bifin:", e)
        png = os.path.join(self.dir, "x.png")
        Image.new("RGB", (4, 4)).save(png)
        rc, o, e = run(png, "-o", os.path.join(self.dir, "y.bif"))
        self.assertEqual(rc, 1)
        self.assertIn(b"no importer for png", e)
        blob = bif.dumps(imp(b"/\\"))
        rc, o, e = run("-", "-o", os.path.join(self.dir, "z.bif"), input=blob)
        self.assertEqual(rc, 1)
        self.assertIn(b"already a BIF", e)
        self.assertEqual(len(e.strip().splitlines()), 1)
        rc, o, e = run("--font", os.path.join(self.dir, "nofont.ttf"), "-o", os.path.join(self.dir, "f.bif"), input=b"/\\")
        self.assertEqual(rc, 1)
        self.assertIn(b"not found", e)

    def test_sniff(self):
        self.assertEqual(bifin.sniff(bif.MAGIC + b"x"), "bif")
        self.assertEqual(bifin.sniff(b"\x89PNG\r\n\x1a\n.."), "png")
        self.assertEqual(bifin.sniff(b"\x1bP0;0;0q#0;2;0;0;0~\x1b\\"), "sixel")
        self.assertEqual(bifin.sniff(b"  <svg xmlns='x'/>"), "svg")
        self.assertEqual(bifin.sniff(b"\x1b[31mhello\x1b[0m"), "text")
        self.assertEqual(bifin.sniff(b""), "text")


if __name__ == "__main__":
    unittest.main(verbosity=1)
