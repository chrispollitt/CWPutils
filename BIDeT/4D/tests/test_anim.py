#!/usr/bin/env python3
"""Tests for animation: bifin_vt.py (a terminal session -> frames), bifop crop over frames, bifout's GIF writer.
python tests/test_anim.py"""
from __future__ import print_function

import io
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageSequence

os.environ.setdefault("BIDET_NO_QUERY", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import bif                                          # noqa: E402
import bifin                                        # noqa: E402
import bifin_text                                   # noqa: E402
import bifin_vt                                     # noqa: E402
import bifop                                        # noqa: E402
import bifout                                       # noqa: E402
import bifrender                                    # noqa: E402

ESC = "\x1b"


def cup(r, c):
    return "%s[%d;%dH" % (ESC, r, c)


def walker(n=4, colour=None):
    """A little roof (strokes, not dashes: a row of only dashes draws nothing, as in v3) moving right, a step a newline."""
    pre = (ESC + "[%dm" % colour) if colour else ""
    return "".join(cup(5, 4 + 6 * i) + pre + "/\\_/\\\\" + (ESC + "[0m" if colour else "") + "\n" for i in range(n)).encode()


def vt(data, **kw):
    kw.setdefault("delay", 40)
    kw.setdefault("hold", 200)
    kw.setdefault("mode", "line")
    return bifin_vt.import_vt(data, **kw)


def gif_of(pic, **kw):
    buf = io.BytesIO()
    bifout.convert(pic, "gif", buf, **kw)
    return Image.open(io.BytesIO(buf.getvalue()))


def run(tool, *args, **kw):
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, tool)] + list(args), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate(kw.get("input"))
    return p.returncode, out, err.decode("utf-8", "replace")


class Replay(unittest.TestCase):
    def test_a_screen_for_each_newline_and_equal_ones_merge(self):
        # (the screen is taken before the newline is processed, as slowcat sleeps before printing it)
        f = bifin_vt.replay("a\n\n\n", 3, 10, 100, 500)
        self.assertEqual([ms for _, ms in f], [300, 500])               # {a} for 3 steps, then scrolled away
        self.assertEqual(f[0][0], {(0, 0): ("a", None, None)})
        self.assertEqual(f[1][0], {})

    def test_cursor_addressing_and_distinct_steps(self):
        f = bifin_vt.replay(cup(2, 3) + "x\n" + cup(2, 3) + "y\n", 5, 20, 10, 50)
        self.assertEqual([ms for _, ms in f], [10, 10 + 50])           # x; then y, and the final screen is the same as y
        self.assertEqual(f[1][0][(1, 2)][0], "y")

    def test_scroll_region_and_reverse_index(self):
        f = bifin_vt.replay("%s[1;3r%sX%sM\n" % (ESC, cup(1, 1), ESC), 5, 10, 10, 10)
        self.assertEqual(list(f[0][0]), [(1, 0)])                       # ESC M at the top of the region: X moves down a line

    def test_last_line_without_newline(self):
        f = bifin_vt.replay("ab", 3, 10, 100, 70)
        self.assertEqual([ms for _, ms in f], [70])

    def test_resample_keeps_the_time(self):
        f = bifin_vt.replay("".join(cup(1, 1 + i) + "x\n" for i in range(10)), 3, 20, 25, 25)
        total = sum(ms for _, ms in f)
        g = bifin_vt.resample(f, 20)                                    # one frame per 50 ms
        self.assertLess(len(g), len(f))
        self.assertAlmostEqual(sum(ms for _, ms in g), total, delta=50)
        self.assertEqual(g[0][0], f[0][0])


class Import(unittest.TestCase):
    def test_frames_durations_loop_and_meta(self):
        pic = vt(walker(4))
        self.assertEqual(len(pic.frames), 4)                             # (the screen after the last newline is the same)
        self.assertEqual([f.duration for f in pic.frames], [40, 40, 40, 40 + 200])
        self.assertEqual(sum(f.duration for f in pic.frames), 4 * 40 + 200)
        self.assertEqual(pic.animation, {"loop": 0})
        self.assertEqual(pic.meta["source"]["kind"], "vt")
        self.assertEqual(pic.meta["generator"]["importer"], "vt")
        bif.check(pic)
        self.assertEqual(len(bif.loads(bif.dumps(pic)).frames), len(pic.frames))

    def test_one_canvas_one_palette(self):
        pic = vt(walker(4, colour=31))
        self.assertTrue(any(e["rgb"] == [205, 0, 0] or e["rgb"][0] > 150 and e["rgb"][1] < 50 for e in pic.palette))
        for f in pic.frames:
            for L in f.layers:
                if "stroke" in L.arrays:
                    self.assertLess(int(L.arrays["stroke"].max()), len(pic.palette))

    def test_canvas_covers_every_frame_and_is_cropped(self):
        pic = vt(walker(4))
        full = vt(walker(4), crop=False)
        self.assertLess(pic.width, full.width)
        for i in range(len(pic.frames)):
            e = bifop.extent(pic, i)
            if e:
                self.assertGreaterEqual(e[0], -1e-6)
                self.assertGreaterEqual(e[1], -1e-6)
                self.assertLessEqual(e[2], pic.width + 1e-6)
                self.assertLessEqual(e[3], pic.height + 1e-6)

    def test_crop_op_takes_the_union_of_the_frames(self):
        pic = vt(walker(4), crop=False)
        e = [bifop.extent(pic, i) for i in range(len(pic.frames))]
        u = bifop.extent_all(pic)
        self.assertEqual(u[0], min(b[0] for b in e if b))
        self.assertEqual(u[2], max(b[2] for b in e if b))
        out = bifop.apply(pic, ["crop"])
        self.assertLessEqual(out.width, int(u[2] - u[0]) + 2)
        self.assertGreater(len(out.frames), 1)

    def test_style_is_settled_once(self):
        # a sparse screen and a full one: both are drawn the way the full one is classified
        sparse = T_grid(["hi"])
        dense = T_grid(["/\\_/\\", "( o.o )", " > ^ <"])
        o = bifin_vt._settle([sparse, dense], bifin_text.Options())
        picked, _ = bifin_text.classify(dense, bifin_text.shade_cells(dense, "X"))
        self.assertEqual(o.mode, picked)
        self.assertEqual(o.color, "off")

    def test_repeated_screens_share_their_arrays(self):
        s = (cup(1, 1) + "ab\n" + cup(1, 1) + "cd\n") * 2
        pic = vt(s.encode())
        a, c = pic.frames[0], pic.frames[2]
        la = [L for L in a.layers if L.kind == "vector"]
        lc = [L for L in c.layers if L.kind == "vector"]
        self.assertEqual(len(la), len(lc))
        for x, y in zip(la, lc):
            self.assertTrue(x.arrays["xy"] is y.arrays["xy"])

    def test_errors(self):
        with self.assertRaises(bif.BifError):
            vt(b"\n\n\n")                                                # nothing is ever drawn
        with self.assertRaises(bif.BifError):
            vt(walker(2), delay=0)

    def test_name_picks_the_importer(self):
        pic = bifin.convert(walker(3), None, name="x/session.VT")
        self.assertGreater(len(pic.frames), 1)
        still = bifin.convert(b"/\\\n\\/\n", None, name="x.txt")
        self.assertEqual(len(still.frames), 1)


def T_grid(rows):
    w = max(len(r) for r in rows)
    ch = [list(r.ljust(w)) for r in rows]
    return bifin_text.Grid(ch, [[None] * w for _ in rows], [[None] * w for _ in rows])


class Gif(unittest.TestCase):
    def test_delays_are_rounded_from_the_running_total(self):
        d = bifout.gif_delays([25] * 4)
        self.assertEqual((sum(d), set(d)), (100, set([20, 30])))
        self.assertEqual(sum(bifout.gif_delays([25] * 400)), 10000)
        self.assertEqual(bifout.gif_delays([1, 1, 1]), [20, 20, 20])       # never under 2/100 s
        self.assertEqual(bifout.gif_delays([100, 100], speed=2.0), [50, 50])

    def test_frames_size_loop_and_time(self):
        pic = vt(walker(4))
        g = gif_of(pic)
        self.assertEqual(g.n_frames, len(pic.frames))
        r = bifrender.render(pic)
        self.assertEqual(g.size, (r.W, r.H))
        self.assertEqual(g.info.get("loop"), 0)
        total = 0
        for f in ImageSequence.Iterator(g):
            total += f.info["duration"]
        self.assertAlmostEqual(total, 4 * 40 + 200, delta=20)

    def test_line_art_palette_is_the_exact_ramp(self):
        pic = vt(walker(3))
        g = gif_of(pic)
        g.seek(2)
        got = np.array(g.convert("RGB")).astype(int)
        want = bifrender.render(pic, frame=2).flatten().astype(int)
        self.assertLessEqual(np.abs(got - want).max(), 1)
        self.assertTrue((got == 0).all(axis=2).any())                      # solid ink
        self.assertTrue((got == 255).all(axis=2).any())                    # the page

    def test_colour_art(self):
        pic = vt(walker(3, colour=31) + walker(3, colour=34))
        g = gif_of(pic)
        g.seek(2)
        got = np.array(g.convert("RGB")).astype(int)
        want = bifrender.render(pic, frame=2).flatten().astype(int)
        self.assertLessEqual(np.abs(got - want).mean(), 3.0)
        self.assertLessEqual(len(set(map(tuple, got.reshape(-1, 3)))), 256)

    def test_transparent(self):
        pic = vt(walker(3))
        g = gif_of(pic, transparent=True)
        self.assertEqual(g.info.get("transparency"), 255)
        g.seek(1)
        rgba = np.array(g.convert("RGBA"))                                 # (Pillow renumbers the palette it saves: look at the result)
        self.assertEqual(set(np.unique(rgba[..., 3])), set([0, 255]))     # no partial transparency in a GIF
        ink = rgba[..., 3] == 255
        self.assertTrue(ink.any())
        self.assertTrue((rgba[ink][:, :3] < 8).all())                      # the ink is solid, not blended with a page

    def test_speed_loop_and_a_single_frame(self):
        pic = vt(walker(4))
        slow = sum(f.info["duration"] for f in ImageSequence.Iterator(gif_of(pic)))
        fast = sum(f.info["duration"] for f in ImageSequence.Iterator(gif_of(pic, speed=2.0)))
        self.assertAlmostEqual(fast, slow / 2.0, delta=30)
        self.assertNotIn("loop", gif_of(pic, loop=1).info)                  # plays once
        self.assertEqual(gif_of(pic, loop=3).info.get("loop"), 2)           # (the number of repeats)
        one = gif_of(pic, frame=2)
        self.assertEqual(one.n_frames, 1)
        with self.assertRaises(bif.BifError):
            bifout.convert(pic, "gif", io.BytesIO(), speed=0)

    def test_a_still_makes_a_one_frame_gif_and_png_takes_frame_0(self):
        pic = vt(walker(3))
        still = bifop.apply(pic, ["frame:1"])
        self.assertEqual(gif_of(still).n_frames, 1)
        buf = io.BytesIO()
        r = bifout.convert(pic, "png", buf)
        self.assertEqual(buf.getvalue()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertTrue(any("frames" in n for n in r.notes))                # it says that it drew only one
        self.assertFalse(any("frames" in n for n in bifout.convert(pic, "png", io.BytesIO(), frame=1).notes))
        self.assertEqual(bifout.format_for("x.gif", False), "gif")


class Cli(unittest.TestCase):
    def test_pipe_from_vt_to_gif_and_bidet(self):
        d = tempfile.mkdtemp()
        src = os.path.join(d, "walk.vt")
        with open(src, "wb") as f:
            f.write(walker(4))
        rc, bifdata, err = run("bifin.py", src, "--delay", "40", "--hold", "100")
        self.assertEqual(rc, 0, err)
        out = os.path.join(d, "walk.gif")
        rc, _, err = run("bifout.py", "-o", out, input=bifdata)
        self.assertEqual(rc, 0, err)
        self.assertGreater(Image.open(out).n_frames, 1)
        rc, bifdata2, err = run("bifin.py", "-f", "vt", "--fps", "10", input=walker(4))
        self.assertEqual(rc, 0, err)
        self.assertGreater(len(bif.loads(bifdata2).frames), 0)
        out2 = os.path.join(d, "b.gif")
        rc, _, err = run("bidet.py", src, "-o", out2)
        self.assertEqual(rc, 0, err)
        self.assertGreater(Image.open(out2).n_frames, 1)
        rc, text, err = run("bidet.py", "-n", src, "-o", out2)
        self.assertIn("bifout", text.decode())


if __name__ == "__main__":
    unittest.main()
