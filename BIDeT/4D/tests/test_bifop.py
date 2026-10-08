#!/usr/bin/env python3
"""Tests for bifop.py.   python tests/test_bifop.py"""
from __future__ import print_function

import io
import json
import math
import os
import subprocess
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import bif                                          # noqa: E402
import bifin_text                                   # noqa: E402
import bifop                                        # noqa: E402
import bifrender                                    # noqa: E402

SAMPLES = os.path.join(ROOT, "samples")
TESTDATA = os.path.join(ROOT, "testdata", "good")


def sample(fname, **kw):
    with io.open(os.path.join(SAMPLES, fname), "rb") as f:
        kw.setdefault("name", fname)
        return bifin_text.import_text(f.read(), **kw)


def good(name):
    return bif.load(os.path.join(TESTDATA, name + ".bif"))


def draw(pic, **kw):
    kw.setdefault("ss", 4)
    return bifrender.render(pic, scale=1, **kw)


def layer(pic, id):
    for L in pic.layers:
        if L.id == id:
            return L


def iou(a, b, r=1):
    """How well two drawings agree: the smaller of the shares of each one's ink that lies within r pixels of the
    other's.  (A strict overlap of 1 px lines says nothing: a half-pixel shift of the pen empties it.)"""
    from PIL import Image, ImageFilter

    def grow(m):
        return np.asarray(Image.fromarray((m * 255).astype("uint8")).filter(ImageFilter.MaxFilter(2 * r + 1))) > 0
    a, b = a > 0.5, b > 0.5
    return min(float((a & grow(b)).sum()) / max(1.0, float(a.sum())), float((b & grow(a)).sum()) / max(1.0, float(b.sum())))


def ink_pic(w=100, h=50, paths=None, **props):
    pal = [{"rgb": [0, 0, 0], "role": "ink"}, {"rgb": [255, 255, 255], "role": "paper"}]
    p = bif.Picture(w, h, palette=pal)
    p.add_frame().layers.append(bif.vector_layer(paths or [[(10, 25), (90, 25)]], id="v", width=2, **props))
    return p


class Parsing(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(bifop.parse_spec("pen"), ("pen", {}))
        self.assertEqual(bifop.parse_spec("pen:2"), ("pen", {"factor": "2"}))
        self.assertEqual(bifop.parse_spec("pen:factor=2,layer=a+b"), ("pen", {"factor": "2", "layer": "a+b"}))
        self.assertEqual(bifop.convert_args("pen", {"factor": "1.5", "layer": "a+b"}),
                         {"factor": 1.5, "layer": ["a", "b"], "frame": None})

    def test_mistakes_are_reported_plainly(self):
        for bad in ("nosuchop", "pen:x=1", "pen:2,3", "pen:abc", "theme:ink=notacolour", "crop:margin=1,margin2=2"):
            with self.assertRaises(bif.BifError, msg=bad):
                bifop.apply(ink_pic(), [bad])
        with self.assertRaises(bif.BifError):                              # a required parameter missing
            bifop.apply(ink_pic(), ["pen"])
        with self.assertRaises(bif.BifError):                              # a layer that is not there
            bifop.apply(ink_pic(), ["pen:2,layer=nope"])

    def test_every_operation_describes_itself(self):
        text = bifop.describe()
        for name in bifop.OPS:
            self.assertIn(name + "  -  ", text)


class Contract(unittest.TestCase):
    def test_the_input_is_not_changed(self):
        pic = sample("cow.txt")
        before = bif.dumps(pic)
        bifop.apply(pic, ["pen:3", "theme:ink=red", "crop:margin=5", "wave", "drop:strokes"])
        self.assertEqual(bif.dumps(pic), before)

    def test_history_and_credit(self):
        pic = ink_pic()
        pic.meta.update({"credit": "J. Doe", "license": "CC0", "title": "t"})
        out = bifop.apply(pic, ["pen:2", "theme:ink=#ff0000"])
        self.assertEqual((out.meta["credit"], out.meta["license"], out.meta["title"]), ("J. Doe", "CC0", "t"))
        h = out.meta["history"]
        self.assertEqual([e["op"] for e in h], ["pen", "theme"])
        self.assertEqual((h[0]["tool"], h[0]["args"]), ("bifop", {"factor": "2"}))
        self.assertEqual(h[1]["args"], {"ink": "#ff0000"})
        again = bifop.apply(out, ["opacity:0.5"])
        self.assertEqual([e["op"] for e in again.meta["history"]], ["pen", "theme", "opacity"])      # appended, not replaced

    def test_what_it_does_not_know_passes_through(self):
        pic = good("forward-compat")
        out = bif.loads(bif.dumps(bifop.apply(pic, ["pen:2", "theme:ink=blue", "opacity:0.9", "crop"])))
        self.assertEqual(out.extra, pic.extra)
        self.assertEqual(out.head_extra, pic.head_extra)
        self.assertEqual(out.meta["x-vendor"], pic.meta["x-vendor"])
        self.assertEqual(out.frames[0].props["x-note"], "unknown FRAM key")
        kinds = [L.kind for L in out.frames[0].layers]
        self.assertIn("hologram", kinds)                                    # an unknown layer kind is kept
        self.assertEqual(layer(out, "v").get("x-extra"), True)
        self.assertIn("hint", layer(out, "v").arrays)                       # and so is an array nobody defined

    def test_results_are_valid_and_deterministic(self):
        for name in ("cow.txt", "tone80.txt", "blocks_color.ans", "dragon_lolcat.ans"):
            pic = sample(name, name=name)
            a = bifop.apply(pic, ["pen:1.5", "crop:margin=3", "rotate:20", "scale:0.5"])
            self.assertEqual(bif.check(a)[0], [], name)
            b = bifop.apply(pic, ["pen:1.5", "crop:margin=3", "rotate:20", "scale:0.5"])
            self.assertEqual(bif.dumps(a), bif.dumps(b), name)


class Style(unittest.TestCase):
    def test_pen(self):
        pic = sample("cow.txt")
        out = bifop.apply(pic, ["pen:2"])
        a, b = layer(pic, "strokes"), layer(out, "strokes")
        self.assertAlmostEqual(b.get("width"), 2 * a.get("width"), places=5)
        self.assertTrue(np.allclose(b.width, 2 * a.width))
        self.assertEqual(float(layer(out, "text").width.max()), 0.0)             # filled letters have no pen
        self.assertGreater(float(draw(out).alpha.sum()), 1.5 * float(draw(pic).alpha.sum()) * 0.9)
        only = bifop.apply(pic, ["pen:2,layer=text"])
        self.assertEqual(layer(only, "strokes").get("width"), a.get("width"))

    def test_pen_without_a_width_property(self):
        out = bifop.apply(ink_pic(), ["pen:3"])
        self.assertEqual(layer(out, "v").get("width"), 6.0)                       # the layer's 2, not the default 1

    def test_theme(self):
        pic = sample("cow.txt")
        out = bifop.apply(pic, ["theme:ink=#00ff66,paper=#101820"])
        self.assertEqual((out.palette[0]["rgb"], out.palette[1]["rgb"]), ([0, 255, 102], [16, 24, 32]))
        r = draw(out)
        self.assertEqual(r.color, (0.0, 255.0, 102.0))
        self.assertEqual(tuple(r.flatten()[0, 0]), (16, 24, 32))

    def test_theme_adds_a_paper_but_not_an_ink(self):
        pic = ink_pic()
        pic.palette = [{"rgb": [0, 0, 0]}]                                        # no roles
        notes = bifop.Notes()
        out = bifop.apply(pic, ["theme:paper=#ffeecc,ink=red"], notes)
        self.assertEqual(out.background, 1)
        self.assertEqual(out.palette[1], {"rgb": [255, 238, 204], "role": "paper"})
        self.assertEqual(out.palette[0]["rgb"], [0, 0, 0])
        self.assertTrue(any("ink" in n for n in notes.lines))

    def test_recolor(self):
        pic = sample("dragon_lolcat.ans", name="dragon_lolcat.ans", mode="line")
        n = len(pic.palette)
        out = bifop.apply(pic, ["recolor:2=#ff0000", "recolor:%s=#00ff00" % ("#%02x%02x%02x" % tuple(pic.palette[3]["rgb"]))])
        self.assertEqual(out.palette[2]["rgb"], [255, 0, 0])
        self.assertEqual(out.palette[3]["rgb"], [0, 255, 0])
        self.assertEqual(len(out.palette), n)
        notes = bifop.Notes()
        bifop.apply(pic, ["recolor:#123456=#000000"], notes)
        self.assertTrue(notes.lines)

    def test_opacity_and_blend(self):
        out = bifop.apply(ink_pic(), ["opacity:0.25,layer=v", "blend:multiply"])
        self.assertEqual((layer(out, "v").get("opacity"), layer(out, "v").get("blend")), (0.25, "multiply"))
        self.assertAlmostEqual(float(draw(out).alpha.max()), 0.25, places=4)
        for bad in ("opacity:2", "blend:dissolve"):
            with self.assertRaises(bif.BifError):
                bifop.apply(ink_pic(), [bad])


class Layers(unittest.TestCase):
    def test_keep_drop_hide_show(self):
        pic = sample("cow.txt")
        self.assertEqual({L.id for L in bifop.apply(pic, ["keep:strokes"]).layers}, {"strokes"})
        self.assertEqual({L.id for L in bifop.apply(pic, ["drop:strokes+cells"]).layers}, {"text"})
        hidden = bifop.apply(pic, ["hide:text"])
        self.assertEqual(layer(hidden, "text").get("visible"), False)
        self.assertLess(float(draw(hidden).alpha.sum()), float(draw(pic).alpha.sum()))
        self.assertTrue(np.array_equal(draw(bifop.apply(hidden, ["show:text"])).alpha, draw(pic).alpha))
        with self.assertRaises(bif.BifError):
            bifop.apply(pic, ["keep:nothing"])

    def test_frame(self):
        anim = good("animation")
        self.assertEqual(len(anim.frames), 3)
        one = bifop.apply(anim, ["frame:1"])
        self.assertEqual((len(one.frames), one.animation), (1, None))
        self.assertEqual(len(one.layers), len(anim.frames[1].layers))
        with self.assertRaises(bif.BifError):
            bifop.apply(anim, ["frame:3"])

    def test_ops_apply_to_every_frame_or_the_chosen_one(self):
        anim = good("animation")
        out = bifop.apply(anim, ["opacity:0.5"])
        self.assertTrue(all(L.get("opacity") == 0.5 for f in out.frames for L in f.layers))
        out = bifop.apply(anim, ["opacity:0.5,frame=2"])
        self.assertEqual([L.get("opacity") for f in out.frames for L in f.layers].count(0.5), len(out.frames[2].layers))

    def test_meta(self):
        pic = sample("cow.txt")
        out = bifop.apply(pic, ["meta:title=Moo", "meta:comment=hello"])
        self.assertEqual((out.meta["title"], out.meta["comment"]), ("Moo", "hello"))
        self.assertEqual(out.meta["source"], pic.meta["source"])


class Geometry(unittest.TestCase):
    def test_extent_is_the_ink(self):
        e = bifop.extent(ink_pic())
        self.assertEqual(e, (9.0, 24.0, 91.0, 26.0))                              # the line and half its pen
        self.assertIsNone(bifop.extent(_empty()))

    def test_crop_is_a_window_on_the_same_picture(self):
        pic = sample("figlet_big.txt")
        e = bifop.extent(pic)
        out = bifop.apply(pic, ["crop"])
        x0, y0 = math.floor(e[0] + 1e-9), math.floor(e[1] + 1e-9)
        self.assertEqual((out.width, out.height), (math.ceil(e[2] - 1e-9) - x0, math.ceil(e[3] - 1e-9) - y0))
        self.assertLess(out.width, pic.width)
        A, B = draw(pic).alpha, draw(out).alpha
        self.assertEqual(B.shape, (out.height, out.width))
        self.assertLess(float(np.abs(A[y0:y0 + B.shape[0], x0:x0 + B.shape[1]] - B).max()), 1e-6)
        self.assertAlmostEqual(float(A.sum()), float(B.sum()), delta=0.5)              # nothing was cut off

    def test_crop_margin_and_box(self):
        pic = sample("cow.txt")
        a, b = bifop.apply(pic, ["crop"]), bifop.apply(pic, ["crop:margin=10"])
        self.assertEqual((b.width - a.width, b.height - a.height), (20, 20))
        c = bifop.apply(pic, ["crop:box=5+6+45+36"])
        self.assertEqual((c.width, c.height), (40, 30))
        with self.assertRaises(bif.BifError):
            bifop.apply(pic, ["crop:box=1+2+3"])
        with self.assertRaises(bif.BifError):
            bifop.apply(pic, ["crop:box=10+10+10+20"])

    def test_crop_keeps_the_grid_in_step(self):
        pic = sample("cow.txt")
        out = bifop.apply(pic, ["crop"])
        e = bifop.extent(pic)
        self.assertEqual(out.grid["x"], pic.grid["x"] - math.floor(e[0] + 1e-9))
        self.assertEqual(out.grid["cols"], pic.grid["cols"])
        self.assertIsNotNone(layer(out, "cells"))

    def test_crop_of_a_raster_goes_to_where_it_has_alpha(self):
        pic = sample("blocks_color.ans", name="blocks_color.ans")
        e = bifop.extent(pic)
        self.assertLessEqual(e[2] - e[0], pic.width)
        out = bifop.apply(pic, ["crop"])
        self.assertAlmostEqual(draw(out).alpha.sum(), draw(pic).alpha.sum(), delta=2.0)

    def test_nothing_drawn_is_left_alone(self):
        pic = _empty()
        notes = bifop.Notes()
        out = bifop.apply(pic, ["crop"], notes)
        self.assertEqual((out.width, out.height), (pic.width, pic.height))
        self.assertTrue(notes.lines)

    def test_scale(self):
        pic = sample("cow.txt")
        out = bifop.apply(pic, ["scale:2"])
        self.assertEqual((out.width, out.height), (2 * pic.width, 2 * pic.height))
        self.assertEqual(out.grid["cell_width"], 2 * pic.grid["cell_width"])
        a, b = draw(pic, ).alpha, draw(out).alpha
        self.assertEqual(b.shape, (2 * a.shape[0], 2 * a.shape[1]))
        c = bifrender.render(pic, scale=2, ss=4).alpha                              # the same as drawing it twice as big
        self.assertGreater(iou(b, c), 0.97)
        with self.assertRaises(bif.BifError):
            bifop.apply(pic, ["scale:0"])

    def test_flip(self):
        pic = sample("figlet_big.txt")
        A = draw(pic).alpha
        h = draw(bifop.apply(pic, ["flip:h"])).alpha
        v = draw(bifop.apply(pic, ["flip:v"])).alpha
        self.assertEqual((h.shape, v.shape), (A.shape, A.shape))
        self.assertGreater(iou(h, A[:, ::-1]), 0.9)
        self.assertGreater(iou(v, A[::-1]), 0.9)
        out = bifop.apply(pic, ["flip"])
        self.assertIsNone(out.grid)
        self.assertIsNone(layer(out, "cells"))

    def test_rotate(self):
        pic = sample("figlet_big.txt")
        A = draw(pic).alpha
        for deg, want in ((90, np.rot90(A, -1)), (180, np.rot90(A, 2)), (270, np.rot90(A, 1))):
            out = bifop.apply(pic, ["rotate:%d" % deg])
            B = draw(out).alpha
            self.assertEqual(B.shape, want.shape, deg)
            self.assertGreater(iou(B, want), 0.9, deg)
        out = bifop.apply(pic, ["rotate:30"])
        c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
        self.assertAlmostEqual(out.width, pic.width * c + pic.height * s, places=6)
        self.assertAlmostEqual(out.height, pic.width * s + pic.height * c, places=6)
        self.assertAlmostEqual(float(draw(out).alpha.sum()), float(A.sum()), delta=0.05 * float(A.sum()))
        odd = bif.Picture(10, 10, unit_aspect=2.0)
        odd.add_frame()
        with self.assertRaises(bif.BifError):
            bifop.apply(odd, ["rotate:10"])

    def test_composition_of_transforms(self):
        pic = sample("cow.txt")
        a = bifop.apply(pic, ["flip:h", "flip:h"])
        self.assertGreater(iou(draw(a).alpha, draw(pic).alpha), 0.9)
        b = bifop.apply(pic, ["rotate:90", "rotate:90", "rotate:90", "rotate:90"])
        self.assertAlmostEqual(b.width, pic.width, places=6)
        self.assertGreater(iou(draw(b).alpha, draw(pic).alpha), 0.9)


def _empty():
    p = bif.Picture(30, 20, palette=[{"rgb": [0, 0, 0], "role": "ink"}])
    p.add_frame()
    return p


class VectorShapes(unittest.TestCase):
    def test_simplify(self):
        pic = sample("tone80.txt", mode="tone")
        out = bifop.apply(pic, ["simplify:0.5"])
        a, b = layer(pic, "tone"), layer(out, "tone")
        self.assertLess(len(b.xy), len(a.xy))
        self.assertEqual(len(b.vwidth), len(b.xy))                                    # per-vertex data kept in step
        self.assertEqual(len(b.paths()), len(a.paths()))
        self.assertGreater(iou(draw(out).alpha, draw(pic).alpha), 0.9)
        same = bifop.apply(pic, ["simplify:0"])
        self.assertEqual(len(layer(same, "tone").xy), len(a.xy))
        for p in layer(out, "tone").paths():
            self.assertGreaterEqual(len(p), 2)

    def test_simplify_keeps_closed_shapes_closed(self):
        sq = [(10, 10), (30, 10), (30, 30), (10, 30)]
        pic = ink_pic(paths=[sq], closed=[1])
        out = bifop.apply(pic, ["simplify:1"])
        self.assertEqual(len(layer(out, "v").xy), 4)
        self.assertEqual(int(layer(out, "v").flags[0]) & 1, 1)

    def test_simplify_respects_the_layer_transform(self):
        pic = ink_pic(paths=[[(0, 0), (10, 0.4), (20, 0)]], transform=[2, 0, 0, 2, 0, 0])    # 0.8 units off in the picture
        self.assertEqual(len(layer(bifop.apply(pic, ["simplify:1"]), "v").xy), 2)
        self.assertEqual(len(layer(bifop.apply(pic, ["simplify:0.5"]), "v").xy), 3)

    def test_wave_moves_points_by_the_formula(self):
        pic = ink_pic(w=200, h=100, paths=[[(0, 50), (200, 50)]])
        out = bifop.apply(pic, ["wave:amplitude=0.1,length=0.5,phase=0.25,step=5"])
        xy = layer(out, "v").xy.astype(np.float64)
        self.assertGreater(len(xy), 40)                                               # made finer so it can bend
        want = 50 + 0.1 * 100 * np.sin(2 * math.pi * (xy[:, 0] / (0.5 * 200) + 0.25))
        self.assertLess(float(np.abs(xy[:, 1] - want).max()), 1e-3)
        self.assertEqual((xy[0, 0], xy[-1, 0]), (0.0, 200.0))                         # x is untouched

    def test_arc(self):
        pic = ink_pic(w=200, h=100, paths=[[(0, 50), (100, 50), (200, 50)]])
        xy = layer(bifop.apply(pic, ["arc:bend=0.4,step=10"]), "v").xy.astype(np.float64)
        self.assertAlmostEqual(float(xy[0, 1]), 50.0, places=4)                       # the ends stay
        self.assertAlmostEqual(float(xy[-1, 1]), 50.0, places=4)
        mid = xy[np.argmin(np.abs(xy[:, 0] - 100))]
        self.assertAlmostEqual(float(mid[1]), 50 - 0.4 * 100, places=3)               # the middle rises (y is down)

    def test_squeeze(self):
        pic = ink_pic(w=200, h=100, paths=[[(0, 20), (100, 20), (200, 20)]])
        xy = layer(bifop.apply(pic, ["squeeze:peak=2,ends=0.5,step=10"]), "v").xy.astype(np.float64)
        self.assertAlmostEqual(float(xy[0, 1]), 50 + (20 - 50) * 0.5, places=3)
        mid = xy[np.argmin(np.abs(xy[:, 0] - 100))]
        self.assertAlmostEqual(float(mid[1]), 50 + (20 - 50) * 2.0, places=3)

    def test_a_warp_bakes_the_layer_transform_and_keeps_the_pen(self):
        pic = ink_pic(paths=[[(5, 12), (45, 12)]], transform=[2, 0, 0, 2, 0, 0])
        before = draw(pic).alpha
        out = bifop.apply(pic, ["wave:amplitude=0"])
        L = layer(out, "v")
        self.assertIsNone(L.get("transform"))
        self.assertEqual(L.get("width"), 4.0)                                         # 2 x the layer's 2
        self.assertGreater(iou(draw(out).alpha, before), 0.95)

    def test_warps_leave_rasters_alone_and_say_so(self):
        pic = sample("blocks_color.ans", name="blocks_color.ans")
        notes = bifop.Notes()
        out = bifop.apply(pic, ["wave"], notes)
        self.assertTrue(any("raster" in n for n in notes.lines))
        self.assertTrue(np.array_equal(layer(out, "picture").alpha, layer(pic, "picture").alpha))

    def test_a_warp_forgets_the_grid(self):
        out = bifop.apply(sample("cow.txt"), ["arc"])
        self.assertIsNone(out.grid)
        self.assertIsNone(layer(out, "cells"))

    def test_big_pictures_are_quick(self):
        import time
        pic = sample("tone100_inv.txt", mode="tone")
        t = time.time()
        bifop.apply(pic, ["pen:2", "simplify:0.3", "wave", "crop:margin=4", "rotate:15"])
        self.assertLess(time.time() - t, 10.0)


def run(*args, **kw):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, kw.pop("tool", "bifop.py"))] + list(args), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    out, err = p.communicate(kw.get("input"))
    return p.returncode, out, err


class Cli(unittest.TestCase):
    def setUp(self):
        self.blob = bif.dumps(sample("cow.txt"))

    def test_pipe(self):
        rc, out, err = run("pen:2", "theme:ink=red", input=self.blob)
        self.assertEqual((rc, out[:8]), (0, bif.MAGIC), err)
        pic = bif.loads(out)
        self.assertEqual(pic.palette[0]["rgb"], [255, 0, 0])
        self.assertEqual([e["op"] for e in pic.meta["history"]], ["pen", "theme"])

    def test_the_whole_pipeline(self):
        rc, blob, e = run(input=open(os.path.join(SAMPLES, "cow.txt"), "rb").read(), tool="bifin.py")
        rc, blob, e = run("wave:amplitude=0.06", "crop:margin=6", input=blob)
        self.assertEqual(rc, 0, e)
        rc, png, e = run("-", "-o", "-", input=blob, tool="bifout.py")
        self.assertEqual((rc, png[:4]), (0, b"\x89PNG"), e)

    def test_files(self):
        import tempfile
        d = tempfile.mkdtemp()
        src, dst = os.path.join(d, "a.bif"), os.path.join(d, "b.bif")
        with open(src, "wb") as f:
            f.write(self.blob)
        rc, out, err = run("-i", src, "-o", dst, "scale:2")
        self.assertEqual((rc, out), (0, b""), err)
        self.assertEqual(bif.load(dst).width, 2 * bif.loads(self.blob).width)

    def test_list_and_help(self):
        rc, out, err = run("--list")
        self.assertEqual(rc, 0)
        for name in ("pen", "theme", "crop", "wave", "rotate"):
            self.assertIn(name.encode(), out)

    def test_errors_are_one_line_and_nonzero(self):
        for args, text in ((("nosuchop",), b"unknown operation"), (("pen:abc",), b"not a number"),
                           (("pen:2,layer=zzz",), b"no layer"), (("crop:box=1+2",), b"box is")):
            rc, out, err = run(*args, input=self.blob)
            self.assertEqual((rc, out), (1, b""), args)
            self.assertIn(text, err)
            self.assertEqual(len(err.strip().splitlines()), 1, err)
        rc, out, err = run(input=self.blob)                                           # no operation
        self.assertEqual(rc, 2)
        rc, out, err = run("pen:2", input=b"not a bif")
        self.assertEqual(rc, 1)
        self.assertIn(b"bifop:", err)

    def test_warnings_go_to_stderr_and_the_result_still_comes(self):
        blob = bif.dumps(sample("blocks_color.ans", name="blocks_color.ans"))
        rc, out, err = run("wave", input=blob)
        self.assertEqual((rc, out[:8]), (0, bif.MAGIC))
        self.assertIn(b"raster", err)

    def test_truncated_input(self):
        rc, out, err = run("pen:2", input=self.blob[:-30])
        self.assertEqual(rc, 1)
        rc, out, err = run("-t", "pen:2", input=self.blob[:-30])
        self.assertEqual((rc, out[:8]), (0, bif.MAGIC), err)


if __name__ == "__main__":
    unittest.main(verbosity=1)
