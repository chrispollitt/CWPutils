#!/usr/bin/env python3
"""Tests for bifrender.py, bifsixel.py and bifout.py.   python tests/test_bifout.py"""
from __future__ import print_function

import glob
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

# the tests must not ask the terminal they happen to run in (bifterm.py): it may not have SIXEL
os.environ.setdefault("BIDET_NO_QUERY", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import bif                                          # noqa: E402
import bifout                                       # noqa: E402
import bifrender                                    # noqa: E402
import bifsixel                                     # noqa: E402

BIDET = os.path.dirname(ROOT)
GOOD = sorted(glob.glob(os.path.join(ROOT, "testdata", "good", "*.bif")))
INK = {"rgb": [0, 0, 0], "role": "ink"}
PAPER = {"rgb": [255, 255, 255], "role": "paper"}


def pic(w=20, h=20, palette=None, **kw):
    p = bif.Picture(w, h, palette=[INK, PAPER] if palette is None else palette, **kw)
    p.add_frame()
    return p


def vec(p, paths, **kw):
    p.frames[-1].layers.append(bif.vector_layer(paths, **kw))
    return p


def draw(p, **kw):
    kw.setdefault("ss", 4)
    return bifrender.render(p, **kw)


def square(x0, y0, x1, y1, ccw=False):
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return pts[::-1] if ccw else pts


def try_import(path, name):
    if not os.path.isdir(path):
        return None
    sys.path.insert(0, path)
    try:
        return __import__(name)
    except ImportError:
        return None


unascii = try_import(os.path.join(HERE, "reference"), "unascii_v3")      # the frozen v3 (the oracle)
sixeldec = try_import(os.path.join(BIDET, "3D", "gfx-conv"), "sixeldec")


class Strokes(unittest.TestCase):
    def test_line_width_and_antialiasing(self):
        r = draw(vec(pic(), [[(2, 10), (18, 10)]], width=4, cap="butt"))
        col = r.alpha[:, 10]
        self.assertEqual(col[9:11].tolist(), [1, 1])
        self.assertAlmostEqual(float(col.sum()), 4.0, delta=0.3)         # (PIL's even-width line is a sub-pixel off centre)
        self.assertEqual((col[6], col[13]), (0, 0))
        self.assertEqual(r.alpha[10, 1], 0)                              # butt: nothing before the start
        half = draw(vec(pic(), [[(2, 10.5), (18, 10.5)]], width=1, cap="butt")).alpha[:, 10]
        self.assertAlmostEqual(float(half.sum()), 1.0, delta=0.3)       # a 1-wide line (PIL's 4-subpixel pen is 3 thick: as in v3)
        self.assertGreater(float(half[9] + half[10]), 0.6)               # straddling two rows

    def test_caps(self):
        base = lambda cap: draw(vec(pic(), [[(6, 10), (14, 10)]], width=4, cap=cap)).alpha
        self.assertEqual(base("butt")[10, 4], 0)
        self.assertGreater(base("round")[10, 4], 0.3)                   # 2 px past the end, round
        self.assertLess(base("round")[8, 4], 0.45)                       # but hardly at the corner
        self.assertGreater(base("square")[8, 4], 0.6)                    # square covers the corner
        self.assertEqual(base("square")[10, 3], 0)

    def test_joins(self):
        path = [[(4, 16), (16, 16), (16, 4)]]
        at = lambda join: draw(vec(pic(), path, width=6, join=join, cap="butt")).alpha[18, 18]
        self.assertEqual(at("miter"), 1)                                 # the corner square is filled
        self.assertLess(at("round"), 0.3)
        self.assertEqual(at("bevel"), 0)
        sharp = draw(vec(pic(), [[(4, 16), (16, 16), (6, 4)]], width=6, join="miter", miter_limit=1.5, cap="butt"))
        self.assertTrue(np.isfinite(sharp.alpha).all())                  # over the limit: bevelled, not a spike
        self.assertEqual(sharp.alpha[19, 19], 0)

    def test_dot(self):
        r = draw(vec(pic(), [[(10, 10)]], width=8))
        self.assertAlmostEqual(float(r.alpha.sum()), np.pi * 16, delta=6.0)
        self.assertEqual(r.alpha[10, 10], 1)

    def test_closed_path_has_no_ends(self):
        p = vec(pic(), [square(4, 4, 16, 16)], width=3, closed=[1], cap="butt", join="miter")
        r = draw(p)
        self.assertEqual(r.alpha[4, 4], 1)                               # a mitred corner, no gap
        self.assertEqual(r.alpha[10, 10], 0)

    def test_layer_transform_scales_positions_and_widths(self):
        a = draw(vec(pic(40, 40), [[(4, 10), (16, 10)]], width=2, cap="butt", transform=[2, 0, 0, 2, 0, 0])).alpha
        b = draw(vec(pic(40, 40), [[(8, 20), (32, 20)]], width=4, cap="butt")).alpha
        self.assertLess(float(np.abs(a - b).max()), 0.01)

    def test_variable_width(self):
        r = draw(vec(pic(30, 20), [[(2, 10), (28, 10)]], vwidth=[0.5, 3.0], width=2, cap="butt"))
        thin, thick = (r.alpha[:, 4] > 0.5).sum(), (r.alpha[:, 26] > 0.5).sum()
        self.assertLess(thin, thick)
        self.assertAlmostEqual(thick, 6, delta=1)

    def test_scale_changes_pixels_not_picture(self):
        p = vec(pic(20, 10), [[(2, 5), (18, 5)]], width=2, cap="butt")
        r1, r4 = draw(p, scale=1), draw(p, scale=4)
        self.assertEqual((r1.W, r1.H, r4.W, r4.H), (20, 10, 80, 40))
        small = np.asarray(Image.fromarray((r4.alpha * 255).astype(np.uint8)).resize((20, 10), Image.BOX), np.float32) / 255
        self.assertAlmostEqual(float(small.sum() / r1.alpha.sum()), 1.0, delta=0.06)   # same ink (a whole-pixel pen)

    def test_unit_aspect(self):
        r = draw(pic(10, 10, unit_aspect=2.0), scale=4)
        self.assertEqual((r.W, r.H), (40, 80))
        r = draw(pic(10, 10, unit_aspect=2.0), width=40, height=40)       # fitted inside both
        self.assertEqual((r.W, r.H), (20, 40))


class Fills(unittest.TestCase):
    def test_hole_by_opposite_winding(self):
        p = vec(pic(), [square(2, 2, 18, 18), square(7, 7, 13, 13, ccw=True)], widths=[0, 0], fills=[0, 0], groups=[0, 0])
        a = draw(p).alpha
        self.assertEqual((a[4, 4], a[10, 10]), (1, 0))

    def test_same_winding_nonzero_is_solid_but_even_odd_has_a_hole(self):
        paths = [square(2, 2, 18, 18), square(7, 7, 13, 13)]
        solid = draw(vec(pic(), paths, widths=[0, 0], fills=[0, 0], groups=[0, 0])).alpha
        holed = draw(vec(pic(), paths, widths=[0, 0], fills=[0, 0], groups=[0, 0], evenodd=[1, 1])).alpha
        self.assertEqual((solid[10, 10], holed[10, 10], holed[4, 4]), (1, 0, 1))

    def test_single_path_fill_and_stroke_in_two_colours(self):
        pal = [INK, {"rgb": [255, 0, 0]}]
        p = vec(pic(palette=pal), [square(4, 4, 16, 16)], widths=[2], strokes=[0], fills=[1], closed=[1])
        r = draw(p, ss=1)
        self.assertFalse(r.uniform)
        c = r.color_u8()
        self.assertEqual(tuple(c[10, 10]), (255, 0, 0))                  # inside: the fill
        self.assertEqual(tuple(c[4, 10]), (0, 0, 0))                     # the edge: the stroke on top

    def test_open_path_fill_closes_it(self):
        r = draw(vec(pic(), [[(4, 4), (16, 4), (10, 16)]], widths=[0], fills=[0]))
        self.assertEqual(r.alpha[8, 10], 1)


class Painting(unittest.TestCase):
    def test_one_colour_stays_uniform(self):
        r = draw(vec(pic(), [[(2, 2), (18, 18)]], width=2))
        self.assertTrue(r.uniform)
        self.assertEqual(r.color, (0.0, 0.0, 0.0))

    def test_later_paths_cover_earlier_ones(self):
        pal = [{"rgb": [255, 0, 0]}, {"rgb": [0, 0, 255]}]
        p = vec(pic(palette=pal), [[(2, 10), (18, 10)], [(10, 2), (10, 18)]], widths=[4, 4], strokes=[0, 1], cap="butt")
        c = draw(p).color_u8()
        self.assertEqual(tuple(c[10, 10]), (0, 0, 255))                  # blue is later, so on top
        self.assertEqual(tuple(c[10, 4]), (255, 0, 0))
        p = vec(pic(palette=pal), [[(2, 10), (18, 10)], [(10, 2), (10, 18)]], widths=[4, 4], strokes=[1, 0], cap="butt")
        self.assertEqual(tuple(draw(p).color_u8()[10, 10]), (255, 0, 0))

    def test_ink_and_paper_override_roles(self):
        p = vec(pic(), [[(2, 10), (18, 10)]], width=2)
        r = draw(p, ink=(10, 20, 30), paper=(250, 240, 230))
        self.assertEqual(r.color, (10.0, 20.0, 30.0))
        self.assertEqual(tuple(r.flatten()[0, 0]), (250, 240, 230))

    def test_paper_choice(self):
        p = vec(pic(palette=[{"rgb": [0, 0, 0]}]), [[(2, 10), (18, 10)]], width=2)
        self.assertEqual(draw(p).paper, (255.0, 255.0, 255.0))                    # dark art: white
        light = vec(pic(palette=[{"rgb": [240, 240, 240]}]), [[(2, 10), (18, 10)]], width=2)
        self.assertEqual(draw(light).paper, (0.0, 0.0, 0.0))                     # light art: black
        p2 = vec(pic(palette=[INK, {"rgb": [10, 10, 80], "role": "paper"}]), [[(2, 10), (18, 10)]], width=2)
        self.assertEqual(draw(p2).paper, (10.0, 10.0, 80.0))                     # a paper-role colour
        p2.background = 0
        self.assertEqual(draw(p2).paper, (0.0, 0.0, 0.0))                        # the background wins
        self.assertEqual(draw(p2, paper=(1, 2, 3)).paper, (1.0, 2.0, 3.0))       # and the caller wins

    def test_empty_picture(self):
        r = draw(pic())
        self.assertEqual(float(r.alpha.sum()), 0)
        self.assertEqual(r.flatten().min(), 255)

    def test_hidden_source_and_filtered_layers_are_not_drawn(self):
        p = pic()
        p.frames[0].layers.append(bif.vector_layer([[(2, 5), (18, 5)]], width=2, id="a", visible=False))
        p.frames[0].layers.append(bif.vector_layer([[(2, 10), (18, 10)]], width=2, id="b", role="source"))
        p.frames[0].layers.append(bif.vector_layer([[(2, 15), (18, 15)]], width=2, id="c"))
        a = draw(p).alpha
        self.assertEqual((a[5, 10], a[10, 10], a[15, 10] > 0.5), (0, 0, True))
        p.frames[0].layers[0].props["visible"] = True
        self.assertEqual(draw(p, layers=set(["a"])).alpha[5, 10] > 0.5, True)
        self.assertEqual(draw(p, layers=set(["a"])).alpha[15, 10], 0)

    def test_frames(self):
        p = pic()
        vec(p, [[(2, 5), (18, 5)]], width=2)
        p.add_frame()
        vec(p, [[(2, 15), (18, 15)]], width=2)
        self.assertGreater(draw(p, frame=0).alpha[5, 10], 0.5)
        self.assertGreater(draw(p, frame=1).alpha[15, 10], 0.5)
        with self.assertRaises(bif.BifError):
            draw(p, frame=2)

    def test_too_big_is_drawn_smaller(self):
        r = draw(pic(1000, 1000), scale=10, max_pixels=1e6)
        self.assertLessEqual(r.W * r.H, 1e6)
        self.assertTrue(r.notes)

    def test_every_reference_file_renders(self):
        self.assertTrue(GOOD)
        for path in GOOD:
            pc = bif.load(path)
            for scale in (0.5, 3.0):
                r = bifrender.render(pc, scale=scale)
                self.assertTrue(np.isfinite(r.alpha).all(), path)
                self.assertTrue(0 <= r.alpha.min() and r.alpha.max() <= 1, path)
                self.assertEqual(r.flatten().shape, (r.H, r.W, 3))


class Blending(unittest.TestCase):
    def two(self, blend, opacity=1.0):
        pal = [{"rgb": [255, 0, 0]}, {"rgb": [0, 255, 0]}]
        p = bif.Picture(4, 4, palette=pal)
        f = p.add_frame()
        f.layers.append(bif.raster_layer(alpha=np.full((4, 4), 255, "|u1"), paint=1))
        f.layers.append(bif.raster_layer(alpha=np.full((4, 4), 255, "|u1"), paint=0, blend=blend, opacity=opacity))
        return draw(p)

    def test_modes(self):
        self.assertEqual(tuple(self.two("normal").color_u8()[1, 1]), (255, 0, 0))
        self.assertEqual(tuple(self.two("multiply").color_u8()[1, 1]), (0, 0, 0))
        self.assertEqual(tuple(self.two("screen").color_u8()[1, 1]), (255, 255, 0))
        self.assertEqual(float(self.two("erase").alpha.max()), 0.0)

    def test_opacity(self):
        r = self.two("normal", 0.5)
        self.assertEqual(r.alpha[1, 1], 1.0)
        self.assertEqual(tuple(r.color_u8()[1, 1]), (128, 128, 0))
        pal = [{"rgb": [255, 0, 0]}]
        p = bif.Picture(4, 4, palette=pal)
        p.add_frame().layers.append(bif.raster_layer(alpha=np.full((4, 4), 255, "|u1"), paint=0, opacity=0.25))
        self.assertAlmostEqual(float(draw(p).alpha[1, 1]), 0.25, places=5)


class Rasters(unittest.TestCase):
    def raster(self, alpha=None, rgb=None, w=8, h=6, **props):
        p = bif.Picture(w, h, palette=[INK, PAPER])
        p.add_frame().layers.append(bif.raster_layer(alpha=alpha, rgb=rgb, **props))
        return p

    def test_identity_reproduces_pixels(self):
        rs = np.random.RandomState(3)
        rgb = rs.randint(0, 256, (6, 8, 3)).astype("|u1")
        al = rs.randint(60, 256, (6, 8)).astype("|u1")
        r = draw(self.raster(al, rgb))
        self.assertLess(float(np.abs(r.alpha - al / 255.0).max()), 0.01)
        self.assertLessEqual(int(np.abs(r.color_u8().astype(int) - rgb).max()), 2)

    def test_nearest_upscale_makes_blocks(self):
        al = np.array([[255, 0], [0, 255]], "|u1")
        r = draw(self.raster(al, w=2, h=2, resample="nearest", paint=0), scale=4)
        want = np.kron(al / 255.0, np.ones((4, 4)))
        self.assertLess(float(np.abs(r.alpha - want).max()), 1e-5)

    def test_smooth_upscale_is_smooth(self):
        al = np.array([[255, 0], [0, 255]], "|u1")
        r = draw(self.raster(al, w=2, h=2, paint=0), scale=8)
        self.assertGreater(len(np.unique(np.round(r.alpha, 2))), 10)

    def test_bounds_place_the_pixels(self):
        al = np.full((2, 2), 255, "|u1")
        r = draw(self.raster(al, w=20, h=20, bounds=[10, 4, 14, 8], resample="nearest", paint=0))
        ys, xs = np.nonzero(r.alpha > 0.5)
        self.assertEqual((xs.min(), xs.max(), ys.min(), ys.max()), (10, 13, 4, 7))

    def test_transform_translates_exactly(self):
        al = np.full((2, 2), 255, "|u1")
        r = draw(self.raster(al, w=20, h=20, resample="nearest", paint=0, transform=[1, 0, 0, 1, 5, 3]))
        ys, xs = np.nonzero(r.alpha > 0.5)
        self.assertEqual((xs.min(), xs.max(), ys.min(), ys.max()), (5, 6, 3, 4))

    def test_transform_rotates_90(self):
        al = np.zeros((2, 4), "|u1")
        al[:, :2] = 255                                                   # left half of a wide picture
        r = draw(self.raster(al, w=10, h=10, resample="nearest", paint=0, transform=[0, 1, -1, 0, 8, 0]))
        ys, xs = np.nonzero(r.alpha > 0.5)                                # turned clockwise: left half -> top
        self.assertEqual((xs.min(), xs.max()), (6, 7))
        self.assertEqual((ys.min(), ys.max()), (0, 1))

    def test_downscale_averages(self):
        y, x = np.mgrid[0:64, 0:64]
        al = (((x + y) % 2) * 255).astype("|u1")
        r = draw(self.raster(al, w=8, h=8, paint=0, bounds=[0, 0, 8, 8]))
        self.assertLess(float(np.abs(r.alpha - 0.5).max()), 0.02)

    def test_color_only_raster_is_opaque(self):
        rgb = np.full((6, 8, 3), 77, "|u1")
        r = draw(self.raster(None, rgb))
        self.assertGreater(float(r.alpha.min()), 0.99)

    def test_outside_the_canvas_is_clipped(self):
        al = np.full((2, 2), 255, "|u1")
        r = draw(self.raster(al, w=5, h=5, bounds=[-10, -10, 3, 3], resample="nearest", paint=0))
        self.assertEqual(r.alpha.shape, (5, 5))
        self.assertEqual((r.alpha[0, 0], r.alpha[4, 4]), (1, 0))


@unittest.skipIf(unascii is None, "tests/reference/unascii_v3.py not found")
class ParityWithUnascii(unittest.TestCase):
    """The same strokes drawn by unascii.draw_strokes and by the BIF renderer."""

    def capture(self, name, **kw):
        cap = {}
        orig = unascii.draw_strokes

        def spy(strokes, W, H, w, ss):
            out = orig(strokes, W, H, w, ss)
            cap["a"] = (strokes, W, H, w, ss, out.copy())          # (unascii then draws its lettering into `out`)
            return out
        unascii.draw_strokes = spy
        try:
            with open(os.path.join(ROOT, "samples", name), "rb") as f:
                data = f.read()
            text, enc = unascii.decode2(data)
            o = unascii.Options(mode="line", cell_w=12, **kw)
            ink, rgb = unascii.render_grid_color(unascii.parse(text, 0), o)
        finally:
            unascii.draw_strokes = orig
        return cap["a"], ink, rgb, o

    def test_strokes_match(self):
        for name in ("cow.txt", "figlet_big.txt", "ghostbusters.txt"):
            (strokes, W, H, w, ss, want), ink, rgb, o = self.capture(name)
            paths, widths = [], []
            for pts, wmul in strokes:
                paths.append(pts)
                widths.append(1.8 * w if len(pts) == 1 else w * wmul)         # a dot is a disc 0.9 w in radius
            p = bif.Picture(W, H, palette=[INK])
            p.add_frame().layers.append(bif.vector_layer(paths, widths=widths))
            got = bifrender.render(p, scale=1, ss=ss).alpha
            diff = np.abs(got - want)
            self.assertEqual(got.shape, want.shape, name)
            self.assertLess(float((diff > 0.05).mean()), 5e-3, "%s: %.4f%% of pixels differ" % (name, 100 * float((diff > 0.05).mean())))
            self.assertLess(float(diff.mean()), 1e-3, name)

    def test_sixel_bytes_match(self):
        for name, kw in (("cow.txt", {}), ("dragon_lolcat.ans", {}), ("blocks_color.ans", {"mode": "ansi-block"})):
            path = os.path.join(ROOT, "samples", name)
            with open(path, "rb") as f:
                data = f.read()
            text, enc = unascii.decode2(data)
            oo = unascii.Options(**kw)
            ink, rgb = unascii.render_grid_color(unascii.parse(text, 0), oo)
            fg, bg = oo.ink, oo.paper
            col = tuple(fg) if rgb is None else rgb
            # byte for byte the same as the (fixed) v3 encoder; the original left "!72" before "$" or "-" when a
            # row ended in a long blank run
            self.assertEqual(bifsixel.encode(ink, col, bg), unascii.sixel(ink, fg, bg, rgb=rgb), name)
            tr = bifsixel.encode(ink, col, bg, transparent=True)
            self.assertEqual(tr, unascii.sixel(ink, fg, bg, transparent=True, rgb=rgb), name + " transparent")
            self.assertIsNone(re.search(br"!\d+[^?-~\d]", tr), name)


@unittest.skipIf(sixeldec is None, "../3D/gfx-conv not found")
class SixelRoundTrip(unittest.TestCase):
    def decode(self, data):
        w, h, rgba = sixeldec.decode_rgba(data)
        return np.frombuffer(rgba, np.uint8).reshape(h, w, 4)

    def test_mono_line_art(self):
        p = vec(pic(40, 30), [[(3, 3), (37, 27)], [(3, 27), (37, 3)]], width=3)
        r = draw(p, scale=2)
        got = self.decode(bifsixel.encode(r.alpha, r.color, r.paper))
        self.assertEqual(got.shape[:2], (r.H, r.W))
        diff = np.abs(got[..., :3].astype(int) - r.flatten().astype(int))
        self.assertLessEqual(int(diff.max()), 17)                        # one step of the 16-level ramp
        self.assertEqual(tuple(got[0, 0, :3]), (255, 255, 255))           # the paper is exact

    def test_coloured_lines(self):
        pal = [{"rgb": [200, 0, 0]}, {"rgb": [0, 0, 200]}]
        p = vec(pic(40, 30, palette=pal), [[(3, 3), (37, 27)], [(3, 27), (37, 3)]], width=3, strokes=[0, 1])
        r = draw(p, scale=2)
        self.assertFalse(r.uniform)
        got = self.decode(bifsixel.encode(r.alpha, r.color_u8(), r.paper))
        diff = np.abs(got[..., :3].astype(int) - r.flatten().astype(int))
        self.assertLessEqual(int(diff.max()), 60)
        self.assertEqual(tuple(got[0, 0, :3]), (255, 255, 255))

    def test_picture_in_its_own_colours(self):
        rs = np.random.RandomState(1)
        rgb = rs.randint(0, 256, (24, 32, 3)).astype("|u1")
        p = bif.Picture(32, 24)
        p.add_frame().layers.append(bif.raster_layer(rgb=rgb, resample="nearest"))
        r = draw(p)
        got = self.decode(bifsixel.encode(r.alpha, r.color_u8(), (255, 255, 255)))
        self.assertGreater(float(np.abs(got[..., :3].astype(int) - rgb.astype(int)).mean()), -1)
        self.assertLess(float(np.abs(got[..., :3].astype(int) - rgb.astype(int)).mean()), 40)   # median cut

    def test_exact_when_few_colours(self):
        rgb = np.zeros((10, 10, 3), "|u1")
        rgb[:5] = (10, 200, 30)
        rgb[5:] = (250, 10, 90)
        p = bif.Picture(10, 10)
        p.add_frame().layers.append(bif.raster_layer(rgb=rgb, resample="nearest"))
        r = draw(p)
        got = self.decode(bifsixel.encode(r.alpha, r.color_u8(), (255, 255, 255)))
        self.assertLessEqual(int(np.abs(got[..., :3].astype(int) - rgb.astype(int)).max()), 3)   # SIXEL has 1% steps

    def test_transparent_leaves_paper_unpainted(self):
        r = draw(vec(pic(20, 20), [[(2, 10), (18, 10)]], width=2))
        got = self.decode(bifsixel.encode(r.alpha, r.color, r.paper, transparent=True))
        self.assertEqual(int(got[0, 0, 3]), 0)
        self.assertEqual(int(got[10, 10, 3]), 255)


def run(*args, **kw):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "bifout.py")] + list(args), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    out, err = p.communicate(kw.get("input"))
    return p.returncode, out, err


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.bif = os.path.join(self.dir, "x.bif")
        bif.save(vec(pic(40, 20), [[(2, 10), (38, 10)]], width=2), self.bif)

    def test_png_file(self):
        out = os.path.join(self.dir, "x.png")
        rc, o, e = run(self.bif, "-o", out, "--scale", "3")
        self.assertEqual(rc, 0, e)
        im = Image.open(out)
        self.assertEqual((im.size, im.mode), ((120, 60), "RGB"))

    def test_transparent_png(self):
        out = os.path.join(self.dir, "t.png")
        self.assertEqual(run(self.bif, "-o", out, "--transparent")[0], 0)
        im = Image.open(out)
        self.assertEqual(im.mode, "RGBA")
        self.assertEqual(im.getpixel((0, 0))[3], 0)

    def test_stdin_to_stdout_is_png_and_sixel_flag_works(self):
        data = open(self.bif, "rb").read()
        rc, o, e = run("-", "-o", "-", input=data)
        self.assertEqual((rc, o[:8]), (0, b"\x89PNG\r\n\x1a\n"))
        rc, o, e = run("-s", input=data)
        self.assertEqual(rc, 0)
        self.assertTrue(o.startswith(b"\x1bP") and o.rstrip().endswith(b"\x1b\\"))
        rc, o, e = run("-o", os.path.join(self.dir, "y.six"), self.bif)
        self.assertEqual(rc, 0)
        self.assertTrue(open(os.path.join(self.dir, "y.six"), "rb").read().startswith(b"\x1bP"))

    def test_width_ink_paper_layer_options(self):
        out = os.path.join(self.dir, "w.png")
        rc, o, e = run(self.bif, "-o", out, "--width", "200", "--ink", "red", "--paper", "#102030", "-v")
        self.assertEqual(rc, 0, e)
        im = Image.open(out)
        self.assertEqual(im.size, (200, 100))
        self.assertEqual(im.getpixel((0, 0)), (16, 32, 48))
        self.assertEqual(im.getpixel((100, 50)), (255, 0, 0))
        self.assertIn(b"200x100", e)

    def test_errors_are_one_line_and_nonzero(self):
        bad = os.path.join(self.dir, "bad.bif")
        open(bad, "wb").write(b"not a bif at all")
        rc, o, e = run(bad, "-o", os.path.join(self.dir, "n.png"))
        self.assertEqual((rc, o), (1, b""))
        self.assertIn(b"bifout:", e)
        self.assertEqual(len(e.strip().splitlines()), 1)
        self.assertNotEqual(run(os.path.join(self.dir, "missing.bif"), "-o", "-")[0], 0)
        self.assertNotEqual(run(self.bif, "--frame", "5", "-o", os.path.join(self.dir, "z.png"))[0], 0)

    def test_truncated_input(self):
        data = open(self.bif, "rb").read()
        rc, o, e = run("-", "-o", "-", input=data[:-30])
        self.assertEqual(rc, 1)
        rc, o, e = run("-", "-o", "-", "-t", input=data[:-30])
        self.assertEqual((rc, o[:4]), (0, b"\x89PNG"))

    def test_library_convert(self):
        buf = io.BytesIO()
        r = bifout.convert(bif.load(self.bif), "png", buf, scale=2)
        self.assertEqual((r.W, r.H), (80, 40))
        with self.assertRaises(bif.BifError):
            bifout.convert(bif.load(self.bif), "tiff", buf)


if __name__ == "__main__":
    unittest.main(verbosity=1)
