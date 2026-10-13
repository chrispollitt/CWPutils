#!/usr/bin/env python3
"""Tests for scrolling text: bifop_scroll.py (the `scroll` operation) and bidet's --scroll / --window / --speed, the `scroll =`
preset key and the presets that use it.   python tests/test_scroll.py"""
from __future__ import print_function

import os
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageSequence

os.environ.setdefault("BIDET_NO_QUERY", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import bidet                                        # noqa: E402
import bif                                          # noqa: E402
import bifop                                        # noqa: E402
import bifop_scroll                                 # noqa: E402
import bifout                                       # noqa: E402
import bifrender                                    # noqa: E402
import gallery                                      # noqa: E402
import ttfbuild                                     # noqa: E402

PRESETS = bidet.load_presets([os.path.join(ROOT, "presets.ini")])
FONT = ttfbuild.write(os.path.join(tempfile.mkdtemp(), "test-regular.ttf"), family="Testface", style="Regular")


def strip_picture(width=300, height=50, unit_aspect=1.0):
    """Three filled shapes (the last two make one `group`, as a letter and its hole would) on a canvas of whole units."""
    pic = bif.Picture(width, height, unit_aspect, None, [{"rgb": [0, 0, 0], "role": "ink"}, {"rgb": [255, 255, 255], "role": "paper"}],
                      None, None, {})
    sq = lambda x, y, s: [(x, y), (x + s, y), (x + s, y + s), (x, y + s)]
    paths = [sq(20, 10, 30), sq(120, 10, 30), sq(130, 20, 10), sq(250, 10, 30)]
    L = bif.vector_layer(paths, widths=[0, 0, 0, 0], fills=[0, 0, 1, 0], closed=[True] * 4, evenodd=[True] * 4,
                         groups=[-1, 5, 5, -1], vwidth=[1.0] * 16, id="text")
    pic.add_frame().layers.append(L)
    return pic


def alpha(pic, i):
    return bifrender.render(pic, frame=i, scale=1.0).alpha


def scrolled(pic=None, spec="scroll:left,window=4,gap=2,time=4,fps=25"):
    return bifop.apply(pic or strip_picture(), [spec])


class Scroll(unittest.TestCase):
    def test_the_canvas_is_the_window_and_the_frames_are_the_lap(self):
        pic = scrolled()
        self.assertEqual((pic.width, pic.height), (200, 50))                 # 4 heights wide
        self.assertEqual(len(pic.frames), 100)                               # 4 s at 25 frames a second
        self.assertEqual(sum(f.duration for f in pic.frames), 4000)
        self.assertEqual(pic.animation, {"loop": 0})
        self.assertEqual(pic.meta["scroll"]["frames"], 100)

    def test_a_step_moves_the_picture_whole_units_and_the_loop_is_seamless(self):
        pic = scrolled()                                                     # period 300 + 100 = 400 over 100 frames: 4 units a frame
        n = len(pic.frames)
        for i in range(n):
            a, b = alpha(pic, i), alpha(pic, (i + 1) % n)                    # (the last frame leads into the first)
            self.assertTrue(np.allclose(b[:, :-4], a[:, 4:], atol=1e-6), "frame %d to %d" % (i, (i + 1) % n))

    def test_it_looks_like_the_picture_moved_not_sliced(self):
        base = strip_picture()
        pic = scrolled(base)
        for i in (0, 7, 30, 55):
            ref = bifop.clone(base)
            bifop.post_transform(ref, (1.0, 0.0, 0.0, 1.0, -4.0 * i, 0.0))   # the whole layer, no slicing, in the same window
            ref.width = 200
            self.assertTrue(np.array_equal(alpha(pic, i), alpha(ref, 0)), "frame %d" % i)

    def test_start_rest_shows_the_beginning(self):
        a = alpha(scrolled(), 0)
        self.assertGreater(float(a.sum()), 0.0)
        self.assertEqual(int(np.nonzero(a.sum(axis=0))[0].min()), 20)        # the first shape, where the picture has it

    def test_the_picture_comes_in_at_the_far_edge(self):
        pic = scrolled(spec="scroll:left,window=4,start=enter,time=4,fps=25")        # gap = the window: empty to begin with
        self.assertEqual(float(alpha(pic, 0).sum()), 0.0)
        cols = [np.nonzero(alpha(pic, i).sum(axis=0))[0] for i in (6, 8)]
        self.assertGreater(cols[0].min(), 100)                               # in from the right ...
        self.assertLess(cols[1].min(), cols[0].min())                        # ... and moving left

    def test_right_and_down_run_the_lap_the_other_way(self):
        left, right = scrolled(), scrolled(spec="scroll:right,window=4,gap=2,time=4,fps=25")
        n = len(left.frames)
        self.assertTrue(np.allclose(alpha(right, 1)[:, 4:], alpha(right, 0)[:, :-4], atol=1e-6))     # it moves right
        self.assertTrue(np.allclose(alpha(left, 1)[:, :-4], alpha(left, 0)[:, 4:], atol=1e-6))
        self.assertEqual(len(right.frames), n)

    def test_up_scrolls_along_y_and_measures_in_widths(self):
        pic = bifop.apply(strip_picture(80, 200), ["scroll:up,window=1.5,gap=0.5,time=2,fps=20"])
        self.assertEqual((pic.width, pic.height, len(pic.frames)), (80, 120, 40))        # 1.5 widths tall
        a, b = alpha(pic, 0), alpha(pic, 1)
        step = 240 // 40                                                     # (period 240 over 40 frames: 6 units a frame)
        self.assertTrue(np.allclose(b[:-step], a[step:], atol=1e-6))
        # the sideways default is faster than the one for up (3 heights a second against 0.2 widths)
        pic2 = bifop.apply(strip_picture(), ["scroll:left"])
        pic3 = bifop.apply(strip_picture(), ["scroll:up"])
        self.assertEqual(pic2.meta["scroll"]["seconds"], round((300 + 250) / (3.0 * 50), 3))
        self.assertEqual(pic3.meta["scroll"]["seconds"], round((50 + 1500) / (0.2 * 300), 3))

    def test_the_unit_aspect_is_respected_along_y(self):
        pic = bifop.apply(strip_picture(100, 100, 2.0), ["scroll:up,window=1,time=1,fps=10"])
        self.assertEqual(pic.height, 50)                                     # a unit is 2 wide-units tall: 100 wide = 50 units

    def test_slicing_keeps_a_group_whole_and_the_arrays_in_step(self):
        L = strip_picture().frames[0].layers[0]
        strip = bifop_scroll._Strip(L, 0)
        arrays = strip.select(-80.0, 60)          # window [0, 60) over the layer moved 80 left: shows the group, at 40..70 (x 120..150)
        self.assertEqual(len(arrays["start"]) - 1, 2)                        # both of its paths (one is at x 130: also in) ...
        self.assertEqual(list(arrays["group"]), [5, 5])                      # ... as a group, nothing else
        self.assertEqual(len(arrays["vwidth"]), len(arrays["xy"]))
        self.assertEqual(int(arrays["start"][-1]), len(arrays["xy"]))
        self.assertIsNone(strip.select(-500.0, 60))                          # nothing shows
        self.assertIs(strip.select(0.0, 1000), L.arrays)                     # everything shows: the arrays are shared
        self.assertEqual(len(strip.select(0.0, 100)["start"]) - 1, 1)        # the first shape only (the next group starts at x 120)

    def test_a_long_picture_costs_a_window_not_the_whole_length(self):
        pic = strip_picture(3000, 50)
        L = pic.frames[0].layers[0]
        paths = [[(x, 10), (x + 20, 10), (x + 20, 30), (x, 30)] for x in range(0, 3000, 40)]
        pic.frames[0].layers[0] = bif.vector_layer(paths, widths=[0] * len(paths), fills=[0] * len(paths), closed=[True] * len(paths),
                                                    id="text")
        out = bifop.apply(pic, ["scroll:left,window=4,gap=1,fps=10,speed=2"])
        shown = [len(L.arrays["start"]) - 1 for f in out.frames for L in f.layers]
        self.assertLess(max(shown), 12)                                      # a window of 200 units holds 5 of the 75 shapes (plus the next lap)
        self.assertGreater(min(shown), 0)

    def test_a_raster_layer_moves_too(self):
        pic = bif.Picture(100, 20, 1.0, None, [{"rgb": [0, 0, 0], "role": "ink"}, {"rgb": [255, 255, 255], "role": "paper"}], None, None, {})
        a = np.zeros((20, 30), np.uint8)
        a[:, :] = 255
        pic.add_frame().layers.append(bif.raster_layer(alpha=a, rgb=np.zeros((20, 30, 3), np.uint8), bounds=[0, 0, 30, 20], id="solid"))
        out = bifop.apply(pic, ["scroll:left,window=2,gap=1,time=2,fps=10,start=enter"])
        sums = [float(alpha(out, i).sum()) for i in range(len(out.frames))]
        self.assertEqual(sums[0], 0.0)
        self.assertGreater(max(sums), 20 * 25)

    def test_layer_ids_stay_unique_in_a_frame(self):
        out = scrolled(spec="scroll:left,window=8,gap=0.5,time=4,fps=10")     # two laps show at once
        for f in out.frames:
            ids = [L.id for L in f.layers]
            self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(any(len(f.layers) > 1 for f in out.frames))

    def test_the_result_is_a_valid_bif_and_survives_a_round_trip(self):
        pic = scrolled()
        errors, _w = bif.check(pic)
        self.assertEqual(errors, [])
        back = bif.loads(bif.dumps(pic))
        self.assertEqual(len(back.frames), len(pic.frames))
        self.assertTrue(np.array_equal(alpha(back, 17), alpha(pic, 17)))

    def test_mistakes_are_one_line_errors(self):
        for spec, word in (("scroll:sideways", "dir"), ("scroll:left,start=middle", "start"), ("scroll:left,window=0", "positive"),
                           ("scroll:left,speed=-1", "positive"), ("scroll:left,gap=-9999", "gap"), ("scroll:left,fps=0", "positive"),
                           ("scroll:left,window=x", "number")):
            with self.assertRaises(bif.BifError) as cm:
                bifop.apply(strip_picture(), [spec])
            self.assertIn(word, str(cm.exception))
        with self.assertRaises(bif.BifError) as cm:                           # it needs ONE frame
            bifop.apply(scrolled(), ["scroll:left"])
        self.assertIn("one frame", str(cm.exception))
        with self.assertRaises(bif.BifError) as cm:                           # a lap of too many frames
            bifop.apply(strip_picture(), ["scroll:left,time=1000,fps=25"])
        self.assertIn("too many", str(cm.exception))

    def test_it_is_in_bifops_list(self):
        self.assertIn("scroll", bifop.OPS)
        self.assertIn("scroll", bifop.describe())


class Bidet(unittest.TestCase):
    def args(self, *argv):
        return bidet.build_parser().parse_args(list(argv))

    def plan(self, *argv):
        return bidet.make_plan(self.args(*argv), PRESETS, stdout_tty=False, stdin_tty=False, env={}, columns=80, pixels=())

    def test_the_flags_make_the_last_operation(self):
        p = self.plan("--scroll", "up", "--window", "2", "--speed", "0.5", "Hello")
        self.assertEqual(p.ops[-1], "scroll:dir=up,window=2,speed=0.5")
        self.assertEqual(self.plan("Hello", "--scroll").ops[-1], "scroll:dir=left")
        self.assertEqual(self.plan("Hello", "--scroll", "--fps", "10").ops[-1], "scroll:dir=left,fps=10")

    def test_the_text_after_a_bare_flag_is_not_taken_for_its_value(self):
        a = self.args("--scroll", "Hello there")
        self.assertEqual((a.scroll, a.input), ("left", ["Hello there"]))
        self.assertEqual(self.args("--scroll", "right", "Hi").scroll, "right")
        self.assertEqual(self.args("--scroll=down", "Hi").scroll, "down")
        a = self.args("--sway", "Hello")                                     # (the same trap, for --sway)
        self.assertEqual((a.sway, a.input), (25.0, ["Hello"]))
        a = self.args("--sway", "40", "Hello")
        self.assertEqual((a.sway, a.input), (40.0, ["Hello"]))
        self.assertEqual(self.args("--sway").sway, 25.0)
        self.assertEqual(bidet.bare_optionals(["-P", "x", "--scroll"]), ["-P", "x", "--scroll=left"])

    def test_a_preset_scrolls_and_the_flags_win(self):
        p = self.plan("-P", "cpm", "Hello")
        self.assertEqual(p.ops[-1], "scroll:dir=left,window=5,start=enter")
        self.assertEqual(self.plan("-P", "cpm", "--window", "9", "--scroll", "right", "Hello").ops[-1],
                         "scroll:dir=right,window=9,start=enter")
        self.assertEqual(self.plan("-P", "ticker", "-P", "cpm", "Hello").ops[-1], "scroll:dir=left,window=5,start=enter")   # the later wins
        self.assertTrue(self.plan("-P", "credits", "Hello").ops[-1].startswith("scroll:dir=up"))
        a = self.plan("-P", "ticker", "--speed", "6", "Hello").ops[-1]
        self.assertIn("speed=6", a)
        self.assertIn("gap=1.5", a)

    def test_text_that_scrolls_sideways_is_set_on_one_line(self):
        for argv in (("--scroll",), ("--scroll", "right"), ("-P", "ticker"), ("-P", "cpm")):
            self.assertIn("--one-line", self.plan(*(argv + ("Hello",))).bifin, argv)
        self.assertNotIn("--one-line", self.plan("--scroll", "up", "Hello").bifin)        # credits keep their lines
        self.assertNotIn("--one-line", self.plan("-P", "credits", "Hello").bifin)
        self.assertNotIn("--one-line", self.plan("Hello").bifin)                          # and plain lettering does not scroll
        self.assertNotIn("--one-line", self.plan(os.path.join(ROOT, "samples", "figlet_big.txt"), "--scroll").bifin)   # art is not text

    def test_a_fortune_on_a_pipe_is_one_line_of_lettering(self):
        text = b"Never trust a man who has\n   occasional flashes of silence\n\t\t-- Sydney Smith\n"
        self.assertTrue(bidet.looks_like_prose(text))                         # (a tab-indented attribution is still prose)
        p = bidet.make_plan(self.args("--scroll"), PRESETS, data=text, stdout_tty=False, stdin_tty=False, env={}, columns=80, pixels=())
        self.assertEqual(p.bifin, ["-f", "lettering", "--one-line"])
        pic = bidet.build_picture(p, text, bifop.Notes())
        self.assertEqual(pic.meta["scroll"]["dir"], "left")
        self.assertLess(pic.height, 400)                                       # one line (three would be ~3 times taller)

    def test_it_comes_after_the_shape_and_the_3d_look(self):
        ops = self.plan("-P", "arc", "-P", "gold", "--scroll", "Hello").ops
        self.assertTrue(ops[-1].startswith("scroll"))
        self.assertTrue(ops[-2].startswith("extrude"))
        self.assertTrue(any(o.startswith("arc") for o in ops[:-2]))

    def test_a_contact_sheet_gets_the_picture_not_the_scroll(self):
        a = self.args("-P", "cpm", "Hello")
        self.assertIsNone(bidet.scroll_op(a, bidet.expand(["cpm"], PRESETS), True))
        self.assertFalse(any(o.startswith("scroll") for o in bidet.make_plan(a, PRESETS, still=True, stdout_tty=False, stdin_tty=False,
                                                                         env={}, columns=80, pixels=()).ops))

    def test_window_and_speed_need_a_scroll(self):
        with self.assertRaises(bif.BifError):
            self.plan("--window", "3", "Hello")

    def test_the_presets_that_scroll_are_valid_and_the_gallery_knows_they_move(self):
        for name in ("ticker", "cpm", "credits"):
            bidet.check_preset(PRESETS[name], PRESETS)
            self.assertTrue(gallery.moves(name, PRESETS))
            self.assertTrue(PRESETS[name].scroll)
        self.assertFalse(gallery.moves("gold", PRESETS))
        bad = bidet.Preset("bad", scroll="left start=middle")
        with self.assertRaises(bif.BifError):
            bidet.check_preset(bad, dict(PRESETS, bad=bad))

    def test_text_to_a_scrolling_gif(self):
        path = os.path.join(tempfile.mkdtemp(), "s.gif")
        bidet.main(["-F", FONT, "--scroll", "--window", "3", "--speed", "6", "-w", "240", "-o", path, "AB BA"])
        im = Image.open(path)
        frames = [f.copy() for f in ImageSequence.Iterator(im)]
        self.assertGreater(len(frames), 10)
        self.assertEqual(im.info.get("loop"), 0)
        self.assertEqual(frames[0].size[0], 240)
        self.assertGreater(frames[0].size[0], frames[0].size[1] * 2)
        self.assertNotEqual(frames[0].tobytes(), frames[len(frames) // 2].tobytes())          # it moves

    def test_the_pipeline_text_is_the_real_pipeline(self):
        import shlex
        line = bidet.make_plan(self.args("-n", "--scroll", "Hi"), PRESETS, stdout_tty=False, stdin_tty=False, env={}, columns=80,
                               pixels=()).shell()
        self.assertIn("bifop scroll:dir=left", line)
        self.assertEqual(shlex.split(line.split(" | ")[1])[0], "bifin")


class Terminal(unittest.TestCase):
    def test_a_scroll_plays_on_a_terminal_like_any_animation(self):
        pic = bifop.apply(strip_picture(), ["scroll:left,window=2,time=1,fps=10"])
        a = bifout.build_parser().parse_args(["--width", "100"])
        self.assertTrue(bifout.plays(pic, a, "sixel"))


if __name__ == "__main__":
    unittest.main()
