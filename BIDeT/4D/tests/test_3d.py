#!/usr/bin/env python3
"""Tests for the 3D stage and the animations built on it: bif3d.py, bifop_3d.py (extrude spin sway popout motion),
bifop_join.py (join, overlay), bifout's playback on a terminal (SIXEL) and --fps, bidet's flags, timemachine.py.
Self-contained: the font is written by ttfbuild.py.   python tests/test_3d.py"""
from __future__ import print_function

import io
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

os.environ.setdefault("BIDET_NO_QUERY", "1")
os.environ["BIDET_EMULATE"] = "1"                   # no banner / figlet / toilet from the machine
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import bif                                          # noqa: E402
import bif3d                                        # noqa: E402
import bifin_lettering                              # noqa: E402
import bifop                                        # noqa: E402
import bifop_join                                   # noqa: E402
import bifout                                       # noqa: E402
import bifrender                                    # noqa: E402
import timemachine                                  # noqa: E402
import ttfbuild                                     # noqa: E402

FONTS = tempfile.mkdtemp()
FONT = ttfbuild.write(os.path.join(FONTS, "test-regular.ttf"), family="Testface", style="Regular")


def flat_picture(text="AB", size=60, ink=(255, 255, 255), paper=(38, 43, 51)):
    return bifin_lettering.lettering(text, font=FONT, size=size, ink=ink, paper=paper)


def disc_solid(material=None):
    a = np.zeros((60, 90), np.float32)
    a[10:50, 15:75] = 1.0
    rgb = np.zeros((60, 90, 3), np.uint8)
    rgb[:] = (200, 40, 40)
    return bif3d.Solid(rgb, a, material=material), a


def one_frame(solid, state, persp=2.5):
    imgs, lo, hi = bif3d.render_frames(solid, [state], persp)
    return np.asarray(imgs[0])


class Engine(unittest.TestCase):
    def test_flat_state_is_the_picture(self):
        solid, a = disc_solid()
        im = one_frame(solid, bif3d.State(depth=0, hover=0, bevel=0, paint=0, shadow=0))
        self.assertAlmostEqual(im[..., 3].astype(float).sum() / 255.0, a.sum(), delta=0.02 * a.sum())
        inside = im[..., 3] == 255
        self.assertTrue(inside.any())
        self.assertTrue((np.abs(im[inside][:, :3].astype(int) - (200, 40, 40)) <= 1).all())

    def test_depth_adds_sides_darker_than_the_face(self):
        solid, a = disc_solid()
        flat = one_frame(solid, bif3d.State(shadow=0))
        deep = one_frame(solid, bif3d.State(depth=20, yaw=-35, shadow=0))
        self.assertGreater(int((deep[..., 3] > 128).sum()), int((flat[..., 3] > 128).sum()) * 0.9)
        lum = deep[..., :3].astype(float).mean(axis=2)
        solid_px = deep[..., 3] > 250
        self.assertGreater(lum[solid_px].max() - lum[solid_px].min(), 30)              # face and sides differ

    def test_shadow_only_when_lifted(self):
        solid, a = disc_solid()
        low = one_frame(solid, bif3d.State(depth=0, hover=0))
        up = one_frame(solid, bif3d.State(depth=10, hover=30))
        partial = lambda im: ((im[..., 3] > 10) & (im[..., 3] < 200) & (im[..., :3].max(axis=2) < 10)).sum()
        self.assertEqual(int(partial(low)), 0)
        self.assertGreater(int(partial(up)), 200)                                      # translucent black on the page

    def test_shadow_geometry(self):
        solid, _ = disc_solid()
        cam = bif3d.Camera(solid, 2.5)
        P = np.array([[0.0, 0.0, -10.0], [5.0, 5.0, 0.0], [1.0, 1.0, 4.0]])
        s = cam.shadow(P)
        self.assertAlmostEqual(s[0, 0], 10 * bif3d.SHADOW_DIR[0])
        self.assertAlmostEqual(s[0, 1], 10 * bif3d.SHADOW_DIR[1])
        self.assertEqual(tuple(s[1]), (5.0, 5.0))                                      # on the screen: its own place
        self.assertEqual(tuple(s[2]), (1.0, 1.0))                                      # behind it: no shadow, no shift

    def test_lift_enlarges_with_perspective(self):
        solid, _ = disc_solid()
        cam = bif3d.Camera(solid, 2.5)
        flat = cam.project(cam.world(bif3d.State(), 0.0))
        up = cam.project(cam.world(bif3d.State(hover=60), 0.0))
        self.assertGreater(up[:, 0].max(), flat[:, 0].max())

    def test_paths(self):
        view = (-20.0, 8.0, 0.0)
        pop = bif3d.pop_path(12, 30.0, 40.0, view)
        self.assertEqual((pop[0].depth, pop[0].hover, pop[0].yaw), (0.0, 0.0, 0.0))          # starts as the flat picture
        self.assertEqual((pop[0].bevel, pop[0].paint), (0.0, 0.0))
        self.assertAlmostEqual(pop[-1].depth, 30.0)
        self.assertAlmostEqual(pop[-1].hover, 40.0)
        self.assertAlmostEqual(pop[-1].yaw, -20.0)
        self.assertTrue(all(b.depth >= a.depth - 1e-9 for a, b in zip(pop, pop[1:])))
        spin = bif3d.spin_path(40, 30.0, 40.0, view)
        self.assertEqual(len(spin), 40)
        self.assertAlmostEqual(spin[1].yaw - spin[0].yaw, 9.0)                                 # a seamless loop of 360 degrees
        self.assertAlmostEqual(bif3d.spin_path(8, 1, 1, view, sign=-1)[1].yaw, -20.0 - 45.0)
        sway = bif3d.sway_path(8, 30.0, 40.0, view, 25.0)
        self.assertAlmostEqual(sway[0].yaw, -20.0)
        self.assertAlmostEqual(sway[2].yaw, 5.0)
        self.assertAlmostEqual(sway[6].yaw, -45.0)
        hold = bif3d.hold_path(0.5, 30.0, 40.0, view)
        self.assertEqual((len(hold), hold[0].duration), (1, 500.0))
        flat = bif3d.flat_path(3, 40.0)
        self.assertEqual((len(flat), flat[0].depth, flat[0].duration), (3, 0.0, 40.0))

    def test_materials_and_errors(self):
        solid, a = disc_solid("rainbow")
        im = one_frame(solid, bif3d.State(shadow=0, bevel=0))
        cols = im[im[..., 3] == 255][:, :3]
        self.assertGreater(len(np.unique(cols, axis=0)), 20)                           # a gradient
        with self.assertRaises(ValueError):
            disc_solid("nonesuch")
        with self.assertRaises(ValueError):
            bif3d.Solid(np.zeros((4, 4, 3)), np.zeros((4, 4)))                         # nothing to extrude
        s2, _ = disc_solid("#112233")
        self.assertEqual(tuple(s2.fill[20, 30]), (17.0, 34.0, 51.0))

    def test_paint_blends_from_the_picture_to_the_material(self):
        solid, _ = disc_solid("#0000ff")
        mid = np.asarray(solid.face(0.0, 0.5))
        self.assertAlmostEqual(float(mid[30, 45, 0]), 100.0, delta=2)                  # halfway from (200,40,40) to (0,0,255)
        self.assertAlmostEqual(float(mid[30, 45, 2]), 147.0, delta=3)

    def test_frames_share_one_canvas(self):
        solid, _ = disc_solid()
        states = bif3d.pop_path(5, 15.0, 20.0, (-20.0, 8.0, 0.0)) + bif3d.spin_path(4, 15.0, 20.0, (-20.0, 8.0, 0.0))
        imgs, lo, hi = bif3d.render_frames(solid, states, 2.5, workers=2)
        self.assertEqual(len(imgs), 9)
        self.assertEqual(len(set(i.size for i in imgs)), 1)
        self.assertEqual(imgs[0].size, (int(hi[0] - lo[0]), int(hi[1] - lo[1])))


class Ops(unittest.TestCase):
    def test_extrude_is_one_frame(self):
        pic = bifop.apply(flat_picture(), ["extrude:depth=0.2,view=-30"], bifop.Notes())
        self.assertEqual(len(pic.frames), 1)
        L = pic.frames[0].layers
        self.assertEqual([x.kind for x in L], ["raster"])
        self.assertIsNone(pic.animation)
        self.assertIsNone(pic.grid)
        self.assertEqual(pic.meta["solid"]["view"], [-30.0, 8.0, 0.0])
        bif.check(pic)
        self.assertEqual(len(bif.loads(bif.dumps(pic)).frames), 1)
        r = bifrender.render(pic)
        self.assertEqual((r.W, r.H), (pic.width, pic.height))

    def test_spin_and_sway_are_seamless_loops(self):
        flat = flat_picture()
        spin = bifop.apply(flat, ["spin:fps=8,speed=90"], bifop.Notes())
        self.assertEqual(len(spin.frames), 32)                                         # 360 / 90 * 8
        self.assertEqual(spin.animation, {"loop": 0})
        self.assertEqual(spin.frames[0].duration, 125)
        two = bifop.apply(flat, ["spin:fps=8,speed=180,turns=2"], bifop.Notes())
        self.assertEqual(len(two.frames), 32)                                          # 2 turns at 180 deg/s: also 4 s
        sway = bifop.apply(flat, ["sway:fps=8,time=2,degrees=10"], bifop.Notes())
        self.assertEqual(len(sway.frames), 16)

    def test_popout_starts_as_the_flat_picture(self):
        flat = flat_picture()
        pop = bifop.apply(flat, ["popout:fps=10,time=1"], bifop.Notes())
        self.assertEqual(len(pop.frames), 10)
        first = bifrender.render(pop, frame=0)
        ref = bifrender.render(flat, scale=2.0)
        got, want = float(first.alpha.sum()), float(ref.alpha.sum()) / 4.0              # (the frames are drawn at res 2: 4x the area)
        self.assertAlmostEqual(got, want, delta=0.05 * want)
        last = bifrender.render(pop, frame=9)
        self.assertGreater(int((last.alpha > 0.5).sum()), int((first.alpha > 0.5).sum()))        # it has depth and a shadow now

    def test_motion_path(self):
        pic = bifop.apply(flat_picture(), ["motion:path=flat+tick+pop+hold+spin,fps=5,flat=2,ticks=3,tickms=40,time=1,hold=1,speed=180"],
                          bifop.Notes())
        d = [f.duration for f in pic.frames]
        self.assertEqual(d[0], 2000)                                                    # one long flat frame
        self.assertEqual(d[1:4], [40, 40, 40])                                          # the ticks
        self.assertEqual(len(pic.frames), 1 + 3 + 5 + 1 + 10)                           # flat, ticks, pop, hold, spin (2 s at 5 fps)
        self.assertEqual(d[9], 1000)                                                    # the hold: one frame that lasts
        self.assertEqual(len(set(f.layers[0].arrays["alpha"].shape for f in pic.frames)), 1)

    def test_errors(self):
        flat = flat_picture()
        with self.assertRaises(bif.BifError):
            bifop.apply(flat, ["motion:path=pop+wobble"], bifop.Notes())
        moving = bifop.apply(flat, ["sway:fps=4,time=1"], bifop.Notes())
        with self.assertRaises(bif.BifError):
            bifop.apply(moving, ["spin"], bifop.Notes())                                     # (it needs a flat picture)
        with self.assertRaises(bif.BifError):
            bifop.apply(flat, ["extrude:depth=-1"], bifop.Notes())
        with self.assertRaises(bif.BifError):
            bifop.apply(flat, ["extrude:view=a+b+c"], bifop.Notes())
        with self.assertRaises(bif.BifError):
            bifop.apply(flat, ["extrude:material=nonesuch"], bifop.Notes())
        with self.assertRaises(bif.BifError):
            bifop.apply(flat, ["extrude:view=1+2"], bifop.Notes())

    def test_resolution_and_registry(self):
        flat = flat_picture(size=30)
        r1 = bifop.apply(flat, ["extrude:res=1"], bifop.Notes())
        r2 = bifop.apply(flat, ["extrude:res=2"], bifop.Notes())
        a1, a2 = r1.frames[0].layers[0].arrays["alpha"], r2.frames[0].layers[0].arrays["alpha"]
        self.assertAlmostEqual(a2.shape[1] / float(a1.shape[1]), 2.0, delta=0.1)
        self.assertAlmostEqual(r1.width, r2.width, delta=2)                              # the same size in canvas units
        for name in ("extrude", "spin", "sway", "popout", "motion", "join", "overlay"):
            self.assertIn(name, bifop.OPS)


def painted(color, w=40, h=30, x0=5, x1=20, paper=(255, 255, 255)):
    p = bif.Picture(w, h, palette=[{"rgb": list(color), "role": "ink"}, {"rgb": list(paper), "role": "paper"}], background=1)
    f = p.add_frame(duration=50)
    f.layers.append(bif.vector_layer([[(x0, h / 2.0), (x1, h / 2.0)]], widths=[6], strokes=[0], id="s", width=6))
    return p


class Join(unittest.TestCase):
    def test_join_appends_frames_merges_palette_centres_canvas(self):
        a, b = painted((255, 0, 0)), painted((0, 0, 255), w=60, h=50)
        a2 = bifop.clone(a)
        d1, d2 = bifop_join.append(a2, b)
        self.assertEqual(len(a2.frames), 2)
        self.assertEqual((a2.width, a2.height), (60, 50))
        self.assertEqual(d1, (10, 10))                                                  # the smaller canvas is centred
        self.assertEqual(d2, (0, 0))
        rgbs = [e["rgb"] for e in a2.palette]
        self.assertIn([255, 0, 0], rgbs)
        self.assertIn([0, 0, 255], rgbs)
        self.assertEqual(sum(1 for e in a2.palette if e.get("role") == "ink"), 1)       # one ink: --ink finds only one
        f0, f1 = bifrender.render(a2, frame=0).flatten(), bifrender.render(a2, frame=1).flatten()
        self.assertEqual(tuple(f0[25, 25]), (255, 0, 0))                                # a's stroke, moved by (10, 10): y 15+10
        self.assertEqual(tuple(f1[25, 20]), (0, 0, 255))                                # b's stroke, remapped to its own colour
        bif.check(a2)

    def test_overlay_one_frame_on_all_and_pairwise(self):
        base = bifop.apply(flat_picture(), ["spin:fps=4,speed=360"], bifop.Notes())       # 4 frames
        n = len(base.frames)
        logo = painted((0, 255, 0))
        before = [len(f.layers) for f in base.frames]
        bifop_join.overlay(base, logo, 1, 2, 3, 4)
        after = [len(f.layers) for f in base.frames]
        self.assertEqual([y - x for x, y in zip(before, after)], [0, 1, 1, 0][:n])
        self.assertEqual(base.frames[1].layers[-1].props["transform"][4:], [3.0, 4.0])
        seq = painted((0, 255, 0))
        seq.frames.append(bif.Frame(duration=50))
        seq.frames[1].layers.append(bif.vector_layer([[(1, 1), (9, 9)]], widths=[2], strokes=[0], id="t", width=2))
        bifop_join.overlay(base, seq, 0, 1)
        self.assertEqual(base.frames[0].layers[-1].id, "s")
        self.assertEqual(base.frames[1].layers[-1].id, "t")                              # frame by frame
        with self.assertRaises(bif.BifError):
            bifop_join.overlay(base, logo, 3, 9)
        bif.check(base)

    def test_ops_with_files_and_errors(self):
        d = tempfile.mkdtemp()
        b = os.path.join(d, "b.bif")
        bif.save(painted((0, 0, 255)), b)
        out = bifop.apply(painted((255, 0, 0)), ["join:" + b, "overlay:" + b + ",first=0,last=0,x=2"], bifop.Notes())
        self.assertEqual(len(out.frames), 2)
        self.assertEqual(len(out.frames[0].layers), 2)
        self.assertEqual(out.animation, {"loop": 0})
        with self.assertRaises(bif.BifError):
            bifop.apply(painted((1, 2, 3)), ["join:" + os.path.join(d, "missing.bif")], bifop.Notes())
        odd = painted((1, 2, 3))
        odd.unit_aspect = 2.0
        with self.assertRaises(bif.BifError):
            bifop_join.append(bifop.clone(painted((1, 2, 3))), odd)

    def test_remap_changes_arrays_it_does_not_share(self):
        p = painted((1, 2, 3))
        L = p.frames[0].layers[0]
        old = L.arrays["stroke"]
        bifop_join.remap_layer(L, [5, 6])
        self.assertEqual(int(L.arrays["stroke"][0]), 5)
        self.assertEqual(int(old[0]), 0)                                                 # (the old array is as it was)


class Playback(unittest.TestCase):
    def pic(self):
        return bifop.apply(flat_picture(size=30), ["spin:fps=6,speed=180,res=1"], bifop.Notes())              # 12 frames

    def test_schedule_keeps_the_time_and_thins(self):
        pic = self.pic()
        full = bifout.schedule(pic)
        self.assertEqual(len(full), 12)
        total = sum(d for _, d in full)
        fast = bifout.schedule(pic, speed=2.0)
        self.assertAlmostEqual(sum(d for _, d in fast), total / 2.0, delta=1)
        thin = bifout.schedule(pic, fps=3)
        self.assertEqual(len(thin), 6)
        self.assertAlmostEqual(sum(d for _, d in thin), total, delta=1000 / 3.0 / 2 + 1)         # (to within half a tick)
        self.assertEqual([i for i, _ in thin][:3], [0, 1, 3])                               # (the frame showing at 0, 333, 667 ms)
        with self.assertRaises(bif.BifError):
            bifout.schedule(pic, speed=0)

    def test_gif_with_fps(self):
        buf = io.BytesIO()
        bifout.convert(self.pic(), "gif", buf, fps=3)
        g = Image.open(io.BytesIO(buf.getvalue()))
        self.assertEqual(g.n_frames, 6)

    def test_sixel_frames_share_a_palette(self):
        pic = self.pic()
        first, frames, samples = bifout.draw_all(pic, list(range(len(pic.frames))), {})
        six = list(bifout.sixel_frames(frames, samples))
        self.assertEqual(len(six), 12)
        self.assertTrue(all(s.startswith(b"\x1bP") and s.endswith(b"\x1b\\") for s in six))
        import re
        palettes = set(tuple(re.findall(rb"#\d+;2;\d+;\d+;\d+", s)) for s in six)
        self.assertEqual(len(palettes), 1)                                                  # every frame defines the same colours
        self.assertEqual(len(next(iter(palettes))), 255)                                    # the page, and 254

    def test_player_clock_loops_and_cleanup(self):
        class Fake(object):
            def __init__(self):
                self.t = 0.0
                self.sleeps = []

            def now(self):
                return self.t

            def sleep(self, s):
                self.sleeps.append(s)
                self.t += s
        clk, out = Fake(), io.BytesIO()
        sent = bifout.play_sixel([b"<A>", b"<B>", b"<C>"], [100, 100, 100], 5, 12, out, loops=2, clock=clk.now, sleep=clk.sleep)
        data = out.getvalue()
        self.assertEqual(sent, 6)
        self.assertEqual([data.count(b) for b in (b"<A>", b"<B>", b"<C>")], [2, 2, 2])
        self.assertTrue(data.startswith(b"\n" * 5 + b"\x1b[5A" + b"\x1b7\x1b[?25l"))        # makes room, remembers the place
        self.assertTrue(data.endswith(b"\x1b[?25h\n"))                                      # and gives the cursor back
        self.assertIn(b"\x1b[?2026h", data)
        order = [data.index(b"<A>"), data.index(b"<B>"), data.index(b"<C>")]
        self.assertEqual(order, sorted(order))
        self.assertNotIn(b"\x1b[12X", data)                                                 # (no erasing unless the page is transparent)
        out2, clk2 = io.BytesIO(), Fake()
        bifout.play_sixel([b"<A>", b"<B>"], [50, 50], 3, 7, out2, loops=1, transparent=True, clock=clk2.now, sleep=clk2.sleep)
        self.assertIn(b"\x1b[7X", out2.getvalue())

    def test_player_skips_frames_it_is_late_for_and_stops_on_ctrl_c(self):
        t = [0.0]

        def clock():
            t[0] += 0.25                                                                    # every look at the clock: a quarter second
            return t[0]
        out = io.BytesIO()
        sent = bifout.play_sixel([b"<%d>" % i for i in range(10)], [100] * 10, 2, 4, out, loops=1, clock=clock, sleep=lambda s: None)
        self.assertLess(sent, 10)                                                           # frames 3, 7 ... were skipped
        self.assertTrue(out.getvalue().endswith(b"\x1b[?25h\n"))

        def interrupt(s):
            raise KeyboardInterrupt
        out = io.BytesIO()
        bifout.play_sixel([b"<A>", b"<B>"], [100, 100], 2, 4, out, loops=0, clock=lambda: 0.0, sleep=interrupt)
        self.assertTrue(out.getvalue().endswith(b"\x1b[?25h\n"))                            # Ctrl-C leaves the terminal usable

    def test_play_end_to_end_on_a_fake_terminal(self):
        pic = self.pic()
        clk = [0.0]

        def now():
            return clk[0]

        def sleep(s):
            clk[0] += s
        out = io.BytesIO()
        r = bifout.play(pic, out, (10, 20), loop=1, clock=now, sleep=sleep, transparent=False)
        self.assertEqual(out.getvalue().count(b"\x1bP0;0;0q"), 12)                            # a SIXEL picture a frame
        up = out.getvalue().split(b"\x1b[")[1].split(b"\x1b")[0]                              # "5A": cursor up
        self.assertEqual(up[-1:], b"A")                                                     # the room it made, to go back up
        self.assertEqual(int(up[:-1]), -(-r.H // 20) + 1)

    def test_sixel_is_the_default_on_a_terminal_and_an_animation_there_plays(self):
        self.assertEqual(bifout.format_for(None, True), "sixel")                            # a terminal: SIXEL
        self.assertEqual(bifout.format_for(None, False), "png")                             # a pipe or a file: PNG
        self.assertEqual(bifout.format_for("x.gif", True), "gif")                           # a file name decides
        self.assertEqual(bifout.format_for("x.six", False), "sixel")
        pic, still = self.pic(), bifop.apply(self.pic(), ["frame:0"], bifop.Notes())
        parse = lambda *argv: bifout.build_parser().parse_args(list(argv))
        self.assertTrue(bifout.plays(pic, parse(), "sixel", True))                          # an animation to a SIXEL terminal: played
        self.assertFalse(bifout.plays(pic, parse(), "sixel", False))                        # (not into a pipe: nothing to play on)
        self.assertFalse(bifout.plays(pic, parse("-o", "x.six"), "sixel", True))            # (not into a file)
        self.assertFalse(bifout.plays(pic, parse("--frame", "1"), "sixel", True))           # (not when one frame is asked for)
        self.assertFalse(bifout.plays(pic, parse(), "png", True))
        self.assertFalse(bifout.plays(still, parse(), "sixel", True))                       # (a still is just drawn)

    def test_transparent_frames_are_not_blended_with_a_page(self):
        """Windows Terminal does not say its background, so frames go out transparent: a pixel is painted in its own colour if at
        least half covered, else left clear.  Blending an edge or a shadow with the picture's own (white) page made a pale halo."""
        alpha = np.array([[1.0, 0.7, 0.3, 0.0]], np.float32)
        color = np.zeros((1, 4, 3), np.uint8)
        color[:] = (200, 50, 50)
        r = bifrender.Rendering(4, 1, 1.0, 1.0, alpha, color, (255.0, 255.0, 255.0), [])
        pal = bifout.GifPalette([r], transparent=True, size=254)
        idx = pal.indices(r)[0]
        rgb = pal.rgb()
        for k in (0, 1):                                                                  # solid and 70% covered: the colour as it is
            self.assertTrue(all(abs(a_ - b_) <= 2 for a_, b_ in zip(rgb[idx[k]], (200, 50, 50))), (k, rgb[idx[k]]))
        self.assertEqual((int(idx[2]), int(idx[3])), (pal.trans, pal.trans))               # 30% and 0%: clear
        # one colour of ink (line art): the same, by the ramp's top index
        ink = bifrender.Rendering(4, 1, 1.0, 1.0, alpha, (10, 20, 30), (255.0, 255.0, 255.0), [])
        p2 = bifout.GifPalette([ink], transparent=True, size=254)
        i2 = p2.indices(ink)[0]
        self.assertEqual(tuple(p2.rgb()[i2[1]]), (10, 20, 30))
        self.assertEqual(int(i2[2]), p2.trans)

    def test_sixel_header_and_unpainted_page_for_each_erase_mode(self):
        import re
        pic = self.pic()
        first, frames, samples = bifout.draw_all(pic, [0, 1], {})
        for erase, p2 in (("ech", b"\x1bP0;1;0q"), ("bg", b"\x1bP0;0;0q")):
            six = list(bifout.sixel_frames(iter([first, first]), samples, transparent=True, erase=erase))
            self.assertTrue(six[0].startswith(p2), (erase, six[0][:12]))
            self.assertIsNone(re.search(rb"#0[!?-~]", six[0]))                            # index 0 is never painted: the page is not ours
        opaque = list(bifout.sixel_frames(iter([first]), samples, transparent=False, erase="bg"))
        self.assertTrue(opaque[0].startswith(b"\x1bP0;0;0q"))                              # (erase only means something for a clear page)

    def test_erasing_covers_every_row_made_room_for_and_only_when_asked(self):
        for erase, rows_erased in (("ech", 5), ("bg", 0), ("none", 0)):
            out = io.BytesIO()
            sent = bifout.play_sixel([b"<A>", b"<B>"], [50, 50], 5, 7, out, loops=1, transparent=True,
                                     clock=iter([0.0, 0.0, 0.06, 0.2]).__next__, sleep=lambda s: None, erase=erase)
            self.assertEqual(out.getvalue().count(b"\x1b[7X"), rows_erased * sent, (erase, sent))

    def test_cell_size(self):
        self.assertEqual(bifout.cell_size("8x16"), (8, 16))
        import bifterm
        self.assertEqual(bifout.cell_size(None, bifterm.Reply(True, None, (7, 15), True)), (7, 15))
        self.assertEqual(bifout.cell_size(None, None, fd=-1, env={}), (10, 20))
        self.assertEqual(bifout.cell_size(None, None, fd=-1, env={"BIDET_CELL": "9x18"}), (9, 18))
        for bad in ("8", "axb", "0x5"):
            with self.assertRaises(bif.BifError):
                bifout.cell_size(bad)

    def test_piped_sixel_of_an_animation_draws_frame_0_and_says_so(self):
        blob = bif.dumps(self.pic())
        p = subprocess.Popen([sys.executable, os.path.join(ROOT, "bifout.py"), "-s", "--no-query"], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate(blob)
        self.assertEqual(p.returncode, 0, err)
        self.assertTrue(out.startswith(b"\x1bP"))
        self.assertIn(b"SIXEL holds one", err)


def bidet(*args, **kw):
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "bidet.py")] + list(args), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate(kw.get("input"))
    return p.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


class Bidet(unittest.TestCase):
    def test_flags_are_bifop_operations(self):
        rc, out, err = bidet("-n", "--pop", "--spin", "--material", "chrome", "Hi", "-o", "x.gif")
        self.assertEqual(rc, 0, err)
        self.assertIn("bifop motion:path=pop+hold+spin,material=chrome", out)
        self.assertIn("bifout --width 640 -o x.gif", out)
        self.assertIn("sway:depth=0.3,degrees=30", bidet("-n", "--sway", "30", "--depth", "0.3", "Hi", "-o", "x.gif")[1])
        self.assertIn("bifop popout", bidet("-n", "--pop", "Hi", "-o", "x.gif")[1])
        self.assertIn("bifop spin:turns=2", bidet("-n", "--spin", "--turns", "2", "Hi", "-o", "x.gif")[1])
        self.assertIn("bifop extrude:view=-25+10+0", bidet("-n", "--3d", "--view=-25,10,0", "Hi", "-o", "x.png")[1])
        self.assertNotIn("bifop", bidet("-n", "Hi", "-o", "x.png")[1])

    def test_a_gif_of_a_pop_out(self):
        d = tempfile.mkdtemp()
        out = os.path.join(d, "pop.gif")
        rc, _, err = bidet("-F", FONT, "--pop", "--fps", "6", "AB", "-o", out)
        self.assertEqual(rc, 0, err)
        g = Image.open(out)
        self.assertEqual(g.n_frames, 10)                                                   # 1.6 s at 6 fps
        still = os.path.join(d, "still.png")
        rc, _, err = bidet("-F", FONT, "--3d", "--material", "gold", "AB", "-o", still)
        self.assertEqual(rc, 0, err)
        self.assertEqual(open(still, "rb").read(8), b"\x89PNG\r\n\x1a\n")

    def test_the_time_machine_flags(self):
        rc, out, err = bidet("-n", "--time-machine", "AB", "-o", "tm.gif")
        self.assertEqual(rc, 0, err)
        self.assertIn("motion:path=flat+tick+pop+hold+spin", out)
        self.assertIn("join:b.bif", out)
        rc, _, err = bidet("--time-machine", "AB")                                         # (a pipe: nothing to play on)
        self.assertNotEqual(rc, 0)
        self.assertIn("-o FILE.gif", err)


PRESETS = None


def presets():
    global PRESETS
    if PRESETS is None:
        import bidet
        PRESETS = bidet.load_presets([os.path.join(ROOT, "presets.ini")])
    return PRESETS


def plan_ops(*argv):
    import bidet
    args = bidet.build_parser().parse_args(list(argv) + ["-o", "x.gif", "Hi"])
    return bidet.make_plan(args, presets(), stdout_tty=False, stdin_tty=False, env={}).ops


class SolidPresets(unittest.TestCase):
    """The 3D presets: `solid =` (the look), `motion =` (what it does), `uses =` (made of others)."""

    def test_the_shipped_ones(self):
        ps = presets()
        looks = ("chrome", "rainbow", "gold", "superhero", "dusk", "lagoon", "cobalt", "graphite", "brick", "horizon", "lime", "relief")
        moves_ = ("popout", "turntable", "swing", "rise")
        shows = ("marquee", "bubble", "ripple", "skyline", "reveal", "carnival")
        for n in looks + moves_ + shows:
            self.assertIn(n, ps)
        for n in looks:
            self.assertTrue(ps[n].solid and not ps[n].motion, n)
            self.assertIn("material=", " ".join(ps[n].solid))
        for n in moves_:
            self.assertTrue(ps[n].motion and ps[n].uses, n)
        import bidet
        for n in ps:
            bidet.check_preset(ps[n], ps)

    def test_a_look_alone_is_a_still_and_a_motion_makes_it_move(self):
        still = plan_ops("-P", "chrome")
        self.assertEqual(still[-1].split(":")[0], "extrude")
        self.assertIn("material=chrome", still[-1])
        self.assertIn("tall=1.2", still[-1])
        moving = plan_ops("-P", "popout")
        self.assertTrue(moving[-1].startswith("motion:path=pop+hold+spin"))
        self.assertIn("material=rainbow", moving[-1])                                    # (via uses: its look)
        self.assertIn("hold=2.4", moving[-1])
        self.assertTrue(plan_ops("-P", "turntable")[-1].startswith("spin:"))
        self.assertTrue(plan_ops("-P", "swing")[-1].startswith("sway:"))
        self.assertIn("degrees=30", plan_ops("-P", "swing")[-1])
        self.assertNotIn("extrude", " ".join(plan_ops("-P", "arc")))                      # a 2D preset stays 2D

    def test_presets_combine_later_wins_and_nothing_piles_up(self):
        ops = plan_ops("-P", "arc", "-P", "popout", "-P", "chrome")
        self.assertEqual(ops[0].split(":")[0], "arc")                                      # the shape first
        last = ops[-1]
        self.assertIn("material=chrome", last)                                            # the look after the motion wins
        self.assertNotIn("rainbow", last)
        self.assertEqual(last.count("tall="), 1)                                          # `tall` replaced, not multiplied
        self.assertIn("path=pop+hold+spin", last)
        self.assertEqual(sum(1 for o in ops if o.startswith("stretch")), 0)
        rev = plan_ops("-P", "chrome", "-P", "popout")[-1]
        self.assertIn("material=rainbow", rev)                                            # (the order is the rule, as documented)

    def test_uses_builds_showpieces(self):
        ops = plan_ops("-P", "marquee")
        self.assertEqual(ops[0].split(":")[0], "arc")
        self.assertIn("material=gold", ops[-1])
        rv = plan_ops("-P", "reveal")
        self.assertTrue(rv[-1].startswith("motion:path=pop+hold+spin"))
        self.assertIn("material=chrome", rv[-1])
        import bidet
        ps = dict(presets())
        a = bidet.Preset("a", uses=["b"])
        b = bidet.Preset("b", uses=["a"])
        ps.update(a=a, b=b)
        with self.assertRaises(bif.BifError):
            bidet.expand(["a"], ps)                                                       # round in a circle
        with self.assertRaises(bif.BifError):
            bidet.expand(["nonesuch"], ps)
        with self.assertRaises(bif.BifError):
            bidet.check_preset(bidet.Preset("c", uses=["nonesuch"]), dict(ps, c=bidet.Preset("c", uses=["nonesuch"])))

    def test_flags_win_over_presets(self):
        self.assertTrue(plan_ops("-P", "popout", "--spin")[-1].startswith("spin:"))        # asked for: replaces the preset's motion
        self.assertEqual(plan_ops("-P", "popout", "--3d")[-1].split(":")[0], "extrude")    # --3d: a still
        self.assertIn("material=gold", plan_ops("-P", "popout", "--material", "gold")[-1])
        self.assertIn("depth=0.5", plan_ops("-P", "chrome", "--depth", "0.5")[-1])
        self.assertIn("view=10+20+0", plan_ops("-P", "chrome", "--view", "10,20,0")[-1])

    def test_bad_solid_or_motion_is_reported_with_the_preset_name(self):
        import bidet
        for kw in (dict(solid=["material"]), dict(solid=["nonesuch=1"]), dict(motion="pop hold"), dict(motion="pop+hold+spin bogus=1")):
            p = bidet.Preset("bad", **kw)
            with self.assertRaises(bif.BifError) as cm:
                bidet.check_preset(p)
            self.assertIn("bad", str(cm.exception))

    def test_tall_stretch_and_material_check(self):
        flat = flat_picture()
        a = bifop.apply(flat, ["extrude:tall=1"], bifop.Notes())
        b = bifop.apply(flat, ["extrude:tall=1.5"], bifop.Notes())
        self.assertAlmostEqual(b.unit_aspect, 1.5)
        r_a, r_b = bifrender.render(a), bifrender.render(b)
        self.assertAlmostEqual(r_b.H / float(r_a.H), 1.5, delta=0.08)                      # taller, as drawn
        self.assertAlmostEqual(r_b.W / float(r_a.W), 1.0, delta=0.05)
        with self.assertRaises(bif.BifError):
            bifop.apply(flat, ["extrude:tall=0"], bifop.Notes())
        st = bifop.apply(flat, ["stretch:y=2,x=0.5"], bifop.Notes())
        self.assertAlmostEqual(st.height, flat.height * 2)
        self.assertAlmostEqual(st.width, flat.width * 0.5)
        with self.assertRaises(bif.BifError):
            bifop.apply(flat, ["stretch:y=-1"], bifop.Notes())
        for name in ("graphite", "brick", "cobalt", "horizon"):
            self.assertIn(name, bif3d.MATERIALS)


class Gallery(unittest.TestCase):
    def test_which_presets_are_3d_and_which_move(self):
        import gallery
        ps = presets()
        self.assertTrue(gallery.is_3d("chrome", ps))
        self.assertFalse(gallery.moves("chrome", ps))
        self.assertTrue(gallery.moves("popout", ps))
        self.assertTrue(gallery.moves("reveal", ps))                                     # (through uses)
        self.assertTrue(gallery.is_3d("marquee", ps))
        self.assertFalse(gallery.is_3d("arc", ps))
        self.assertFalse(gallery.is_3d("plain", ps))

    def test_a_tile_of_a_moving_preset_is_its_final_pose_as_a_still(self):
        import gallery
        im = Image.open(io.BytesIO(gallery.render("popout", 240, presets())))
        self.assertGreater(im.size[0], 100)
        self.assertNotIn("duration", im.info)                                              # a PNG: one picture, not 60 frames
        g = np.asarray(im.convert("L"))
        self.assertGreater(float((g != g[0, 0]).mean()), 0.01)

    def test_the_animated_sheet_loops_on_the_master_loop(self):
        import gallery
        ps = presets()
        orig = (gallery.FPS, gallery.LOOP_SECONDS)
        gallery.FPS, gallery.LOOP_SECONDS = 4, 2                                           # (a quick one)
        try:
            tiles = gallery.animated_tiles("turntable", (150, 100), ps)
            self.assertEqual(len(tiles), 8)
            self.assertIsNone(gallery.animated_tiles("chrome", (150, 100), ps))             # a still has no frames of its own
            frames = gallery.animated_sheet(["chrome", "turntable"], ps, tile=(150, 100), columns=2)
            self.assertEqual(len(frames), 8)
            a, b = np.asarray(frames[0]), np.asarray(frames[3])
            self.assertTrue((a[:, :a.shape[1] // 2 - 20] == b[:, :a.shape[1] // 2 - 20]).all())    # the still tile does not change
            self.assertFalse((a == b).all())                                                 # the moving one does
            path = os.path.join(tempfile.mkdtemp(), "s.gif")
            gallery.save_gif(frames, path)
            self.assertEqual(Image.open(path).n_frames, 8)
        finally:
            gallery.FPS, gallery.LOOP_SECONDS = orig


class TimeMachine(unittest.TestCase):
    def cfg(self, **kw):
        kw.setdefault("stage_time", 0.2)
        kw.setdefault("ticker_steps", 3)
        kw.setdefault("fps", 6.0)
        kw.setdefault("res", 1)
        kw.setdefault("delay", 100)
        kw.setdefault("era_font", FONT)
        kw.setdefault("face", FONT)
        kw.setdefault("turns", 0.5)
        kw.setdefault("pop_time", 0.5)
        kw.setdefault("cell", 8)
        return timemachine.Settings(**kw)

    def test_the_imitations_of_the_old_tools(self):
        banner = timemachine.era_text(0, ["AB"], 60, FONT)
        self.assertIn("#", banner)
        self.assertNotIn("\x1b", banner)
        figlet = timemachine.era_text(1, ["AB"], 60, FONT)
        self.assertTrue(set(figlet) <= set(timemachine._QUAD) | set("\n"))
        toilet = timemachine.era_text(2, ["AB"], 60, FONT)
        self.assertIn("\x1b[38;2;", toilet)                                                # colour
        self.assertEqual(timemachine.visible_width("\x1b[31mab\x1b[0m"), 2)
        self.assertLessEqual(max(timemachine.visible_width(r) for r in banner.split("\n")), 56)

    def test_a_session_is_steps(self):
        s = timemachine.Script(50)
        s.step(2, 3, "hi", clear=True)
        s.wait(200)
        text = s.text()
        self.assertTrue(text.startswith("\x1b[2J\x1b[2;3Hhi\n"))
        self.assertEqual(text.count("\x1b[1;1H\n"), 4)                                      # a wait is steps that change nothing
        self.assertEqual(timemachine.year_at(1983, 1991, 0.0), 1983)
        self.assertEqual(timemachine.year_at(1983, 1991, 1.0), 1991)
        self.assertLess(timemachine.year_at(2020, 2026, 0.5), 2026)

    def test_the_show(self):
        cfg = self.cfg()
        steps = []
        pic = timemachine.build("AB", cfg, say=steps.append)
        self.assertEqual(len(steps), 3)
        self.assertEqual(pic.animation, {"loop": 0})
        bif.check(pic)
        n = len(pic.frames)
        self.assertGreater(n, 15)
        solid = [i for i, f in enumerate(pic.frames) if any(L.id == "solid" for L in f.layers)]
        self.assertGreater(len(solid), 5)
        self.assertEqual(solid, list(range(solid[0], n)))                                   # the 3D part is the end of the show
        self.assertGreater(solid[0], 8)                                                     # after the terminal eras
        # captions lie over the 3D frames; the flat 2020 frame lasts the stage time
        self.assertGreater(len(pic.frames[solid[0]].layers), 1)
        self.assertGreater(len(pic.frames[-1].layers), 1)
        self.assertEqual(pic.frames[solid[0]].duration, 200)
        # one canvas, whatever is shown
        r0, r1 = bifrender.render(pic, frame=0), bifrender.render(pic, frame=n - 1)
        self.assertEqual((r0.W, r0.H), (r1.W, r1.H))
        # and it plays out as a GIF
        buf = io.BytesIO()
        bifout.convert(pic, "gif", buf)
        self.assertGreater(Image.open(io.BytesIO(buf.getvalue())).n_frames, 10)

    def test_script_and_errors(self):
        text = timemachine.script("BIDeT", self.cfg(), "x.gif")
        for word in ("bifin -f vt", "bifin -f lettering", "motion:path=flat+tick+pop+hold+spin", "join:b.bif", "bifout tm.bif -o x.gif"):
            self.assertIn(word, text)
        with self.assertRaises(bif.BifError):
            timemachine.build("   ", self.cfg())
        with self.assertRaises(TypeError):
            timemachine.Settings(nonesuch=1)


if __name__ == "__main__":
    unittest.main()
