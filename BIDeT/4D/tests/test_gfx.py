#!/usr/bin/env python3
"""Tests for bifgfx.py and the output formats of bifout that come from it: kitty, iTerm2, ANSI art, Tektronix; `auto`; playing
an animation as text; bidet's --format.   python tests/test_gfx.py
Where ../3D/gfx-conv (the legacy converters these were ported from) is present, the output is compared with theirs byte for byte."""
from __future__ import print_function

import base64
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

os.environ.setdefault("BIDET_NO_QUERY", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import bif                                          # noqa: E402
import bifgfx                                       # noqa: E402
import bifin                                        # noqa: E402
import bifout                                       # noqa: E402
import bifrender                                    # noqa: E402
import bifterm                                      # noqa: E402

try:
    from unittest import mock
except ImportError:                                 # pragma: no cover
    mock = None

GFX_CONV = os.path.join(os.path.dirname(ROOT), "3D", "gfx-conv")


def legacy():
    """The legacy converters, or None."""
    if not os.path.isdir(GFX_CONV):
        return None
    sys.path.insert(0, GFX_CONV)
    try:
        import sixel2ans, sixel2iterm, sixel2kitty, sixel2tek
        return dict(ans=sixel2ans, iterm=sixel2iterm, kitty=sixel2kitty, tek=sixel2tek)
    except ImportError:
        return None
    finally:
        sys.path.pop(0)


def solid_picture(color=(200, 30, 30), w=24, h=16, paper=(255, 255, 255)):
    """A BIF with one raster layer filled with `color`."""
    p = bif.Picture(w, h, palette=[{"rgb": list(color), "role": "ink"}, {"rgb": list(paper), "role": "paper"}], background=1)
    f = p.add_frame(duration=60)
    rgb = np.zeros((h, w, 3), np.uint8)
    rgb[:] = color
    f.layers.append(bif.raster_layer(alpha=np.full((h, w), 255, np.uint8), rgb=rgb, id="r", bounds=[0, 0, w, h]))
    return p


def line_picture():
    """A BIF of strokes: a closed triangle and an open line, no raster."""
    p = bif.Picture(100, 50, palette=[{"rgb": [0, 0, 0], "role": "ink"}, {"rgb": [255, 255, 255], "role": "paper"}], background=1)
    f = p.add_frame()
    lay = bif.vector_layer([[(10, 10), (60, 10), (35, 40)], [(70, 5), (95, 45)]], widths=[2, 2], strokes=[0, 0], id="v", width=2)
    lay.arrays["flags"] = np.array([1, 0], "|u1")                                  # the triangle is closed
    f.layers.append(lay)
    return p


def rendering(pic, **kw):
    return bifrender.render(pic, **kw)


def png_of(r, transparent=True):
    return bifout.png_bytes(r, transparent)


def strip_sgr(b):
    return re.sub(rb"\x1b\[[0-9;]*m", b"", b).decode("utf-8")


def decode_tek(stream):
    """Tektronix stream -> [('GS' | 'FS', [(x, y), ...])], reading the addresses back (high bytes persist until changed)."""
    out, cur = [], None
    hy = hx = ly = 0
    pending = None
    i = 0
    stream = bytes(stream)
    while i < len(stream):
        b = stream[i:i + 1]
        if b in (bifgfx.GS, bifgfx.FS):
            cur = (("GS" if b == bifgfx.GS else "FS"), [])
            out.append(cur)
            hy = hx = ly = 0
            pending = None
            i += 1
            continue
        if b == bifgfx.US:
            break
        v = stream[i]
        if 0x20 <= v < 0x40:                      # a high byte: Y if the next kind is Y... tracked by order below
            if pending is None:
                pending = "hy"
            hy_or_hx = v & 31
            # Tek order is HiY, LoY, HiX, LoX; a high byte seen before a LoY is HiY, after a LoY it is HiX
            if ly_seen[0]:
                hx = hy_or_hx
            else:
                hy = hy_or_hx
        elif 0x60 <= v < 0x80:
            ly = v & 31
            ly_seen[0] = True
        elif 0x40 <= v < 0x60:
            lx = v & 31
            cur[1].append(((hx << 5) | lx, (hy << 5) | ly))
            ly_seen[0] = False
        i += 1
    return out


ly_seen = [False]


class Protocols(unittest.TestCase):
    def pngs(self):
        r = rendering(solid_picture(w=300, h=200))
        return png_of(r)

    def test_kitty_is_a_chunked_png(self):
        png = np.random.RandomState(1).bytes(9000)                                   # (incompressible, so it takes several chunks)
        seq = bifgfx.kitty_sequence(png, cols=30, rows=10, image_id=7)
        chunks = re.findall(rb"\x1b_G([^;]*);([^\x1b]*)\x1b\\", seq)
        self.assertGreater(len(chunks), 1)                                           # more than one chunk of 4096
        first_keys = chunks[0][0].decode()
        for key in ("a=T", "f=100", "q=2", "c=30", "r=10", "i=7", "m=1"):
            self.assertIn(key, first_keys.split(","))
        self.assertTrue(all(len(c[1]) <= bifgfx.CHUNK for c in chunks))
        self.assertEqual([c[0].decode() for c in chunks[1:-1]], ["m=1,q=2"] * (len(chunks) - 2))
        self.assertEqual(chunks[-1][0].decode(), "m=0,q=2")
        self.assertEqual(base64.b64decode(b"".join(c[1] for c in chunks)), png)       # the PNG, whole
        one = bifgfx.kitty_sequence(b"x" * 10)
        self.assertEqual(one, b"\x1b_Ga=T,f=100,q=2,m=0;" + base64.b64encode(b"x" * 10) + b"\x1b\\")

    def test_iterm_is_one_osc_with_the_png(self):
        png = self.pngs()
        seq = bifgfx.iterm_sequence(png, width=40, height=12, name="a.png")
        m = re.match(rb"\x1b\]1337;File=([^:]*):([^\x07]*)\x07$", seq)
        self.assertTrue(m)
        args = dict(kv.split("=", 1) for kv in m.group(1).decode().split(";"))
        self.assertEqual((args["inline"], args["width"], args["height"], args["size"]), ("1", "40", "12", str(len(png))))
        self.assertEqual(base64.b64decode(args["name"]), b"a.png")
        self.assertEqual(base64.b64decode(m.group(2)), png)
        self.assertNotIn(b"width=", bifgfx.iterm_sequence(png))

    def test_the_formats_through_bifout(self):
        pic = solid_picture()
        for fmt, prefix, suffix in (("kitty", b"\x1b_G", b"\x1b\\\n"), ("iterm", b"\x1b]1337;File=", b"\x07\n"),
                                    ("ansi", b"\x1b[", b"\x1b[0m\n"), ("tek", bifout.TEK_ERASE, bifgfx.US),
                                    ("tek-hatch", bifout.TEK_ERASE, bifgfx.US), ("tek-dots", bifout.TEK_ERASE, bifgfx.US),
                                    ("tek-contour", bifout.TEK_ERASE, bifgfx.US)):
            buf = io.BytesIO()
            r = bifout.convert(pic, fmt, buf, fmt_opts=dict(cols=12, rows=4))
            data = buf.getvalue()
            self.assertTrue(data.startswith(prefix), (fmt, data[:12]))
            self.assertTrue(data.endswith(suffix), (fmt, data[-12:]))
            self.assertGreater(r.W, 0)
        self.assertEqual(bifout.format_for("x.ans", False), "ansi")
        self.assertEqual(bifout.format_for("x.ANSI", False), "ansi")
        self.assertEqual(bifout.format_for("x.tek", False), "tek")
        self.assertEqual(bifout.format_for("x.bin", False), "png")


class AnsiArt(unittest.TestCase):
    def test_glyph_sets(self):
        sizes = dict((n, len(bifgfx.glyph_set(n))) for n in bifgfx.GLYPHS)
        self.assertEqual(sizes["half"], 2)
        self.assertGreater(sizes["quad"], sizes["half"])
        self.assertGreater(sizes["blocks"], sizes["quad"])
        self.assertEqual(sizes["braille"], 254)
        for n in bifgfx.GLYPHS:
            g = bifgfx.glyph_set(n)
            meaning = {}
            for c, m in g:
                meaning.setdefault(c, set()).add(m)
            self.assertTrue(all(len(v) == 1 for v in meaning.values()), n)            # a character always means the same patch
            self.assertTrue(all(0 < m < bifgfx.FULL for _, m in g), n)               # none is empty or full
        with self.assertRaises(ValueError):
            bifgfx.glyph_set("emoji")

    def test_sizes_keep_the_shape(self):
        size = bifgfx.ansi_size
        self.assertEqual(size(160, 80), (20, 5))                                      # its own size at 8 px a character
        self.assertEqual(size(1600, 800, term_cols=100), (100, 25))                   # at most the terminal's width
        self.assertEqual(size(200, 100, cols=40), (40, 10))                           # rows from the shape and the cell's aspect
        self.assertEqual(size(200, 100, rows=10), (40, 10))
        self.assertEqual(size(200, 100, cols=40, rows=3), (12, 3))                    # both: the picture fits inside
        self.assertEqual(size(200, 100, cols=-10, term_cols=80), (70, 18))            # negative: fewer than the terminal
        self.assertEqual(size(200, 100, cols=40, aspect=1.0), (40, 20))               # a square cell

    def rgba(self, top, bottom, w=16, h=16):
        a = np.zeros((h, w, 4), np.uint8)
        a[:h // 2, :, :3] = top
        a[h // 2:, :, :3] = bottom
        a[..., 3] = 255
        return a

    def test_two_colours_become_a_half_block_with_both_colours(self):
        lines = bifgfx.ansi_lines(self.rgba((255, 0, 0), (0, 0, 255)), 2, 1, "half")
        self.assertEqual(len(lines), 1)
        text = lines[0].decode("utf-8")
        self.assertIn("▀", text)                                                 # upper half block
        self.assertIn("38;2;255;0;0", text)                                           # red on top
        self.assertIn("48;2;0;0;255", text)                                           # blue behind
        self.assertEqual(strip_sgr(lines[0]), "▀▀")
        self.assertTrue(text.endswith("\x1b[0m"))

    def test_one_colour_is_a_background_of_spaces(self):
        a = np.zeros((16, 16, 4), np.uint8)
        a[...] = (10, 200, 30, 255)
        text = bifgfx.ansi_art(a, 2, 1).decode("utf-8")
        self.assertEqual(strip_sgr(text.encode("utf-8")), "  \n")
        self.assertIn("48;2;10;200;30", text)

    def test_transparency_and_a_background(self):
        a = np.zeros((16, 16, 4), np.uint8)                                           # nothing there at all
        text = bifgfx.ansi_art(a, 2, 1).decode("utf-8")
        self.assertEqual(strip_sgr(text.encode("utf-8")), "  \n")
        self.assertNotIn(";2;", text)                                                 # the terminal's own background: no colour
        filled = bifgfx.ansi_art(a, 2, 1, background=(1, 2, 3)).decode("utf-8")
        self.assertIn("48;2;1;2;3", filled)                                           # ... or the one asked for

    def test_colour_depths(self):
        a = self.rgba((255, 0, 0), (0, 0, 255))
        t256 = bifgfx.ansi_art(a, 2, 1, "half", 256).decode("utf-8")
        self.assertIn("38;5;", t256)
        self.assertNotIn(";2;", t256)
        t16 = bifgfx.ansi_art(a, 2, 1, "half", 16).decode("utf-8")
        self.assertNotIn(";5;", t16)
        self.assertNotIn(";2;", t16)
        self.assertRegex(t16, r"\x1b\[(9[0-7]|3[0-7]);(10[0-7]|4[0-7])m")
        with self.assertRaises(ValueError):
            bifgfx.ansi_art(a, 2, 1, "half", 8)

    def test_every_line_is_the_width_asked_for(self):
        r = rendering(solid_picture(w=200, h=100))
        for glyphs in bifgfx.GLYPHS:
            text = bifgfx.ansi_art(r.rgba(), 30, 8, glyphs)
            lines = strip_sgr(text).split("\n")[:-1]
            self.assertEqual((len(lines), set(len(l) for l in lines)), (8, set([30])), glyphs)


class Tektronix(unittest.TestCase):
    def test_addresses_round_trip(self):
        for pts in ([(0, 0), (1023, 779)], [(512, 400), (513, 400), (513, 431)], [(31, 31), (32, 32), (100, 63)]):
            tek = bifgfx.Tek()
            tek.polyline(pts)
            tek.end()
            got = decode_tek(tek.out)
            self.assertEqual(len(got), 1)
            self.assertEqual(got[0][0], "GS")
            want = [(x, y - (1 if y & 31 == 31 else 0)) for x, y in pts]                 # (LoY 0x7F is DEL: nudged down)
            self.assertEqual(got[0][1], want)
        tek = bifgfx.Tek()
        tek.points([(5, 6), (7, 8)])
        self.assertEqual(decode_tek(bytes(tek.out) + bifgfx.US), [("FS", [(5, 6), (7, 8)])])
        tek = bifgfx.Tek()
        tek.polyline([(-50, 5000)])                                                      # off the screen: clamped to it
        self.assertEqual(decode_tek(bytes(tek.out) + bifgfx.US)[0][1], [(0, bifgfx.TEK_H - 1)])

    def test_unchanged_high_bytes_are_left_out(self):
        tek = bifgfx.Tek()
        tek.polyline([(100, 100), (101, 100)])
        short = len(tek.out)
        tek2 = bifgfx.Tek()
        tek2.polyline([(100, 100), (400, 700)])
        self.assertLess(short, len(tek2.out))

    def test_a_pictures_own_paths_become_strokes(self):
        pic = line_picture()
        body = bifgfx.tek_vectors(pic)
        strokes = decode_tek(body)
        self.assertEqual([k for k, _ in strokes], ["GS", "GS"])                          # one stroke a path
        tri, line = strokes[0][1], strokes[1][1]
        self.assertEqual(len(tri), 4)                                                     # three corners, and back to the first
        self.assertEqual(tri[0], tri[-1])
        self.assertEqual(len(line), 2)
        s = min(1023 / 100.0, 779 / 50.0)                                                # the canvas is fitted and centred, y up
        ox, oy = (1024 - 100 * s) / 2.0, (780 - 50 * s) / 2.0
        want = (ox + 10 * s, 779 - (oy + 10 * s))
        self.assertAlmostEqual(tri[0][0], want[0], delta=1.01)
        self.assertAlmostEqual(tri[0][1], want[1], delta=1.01)
        self.assertGreater(line[1][0], line[0][0])                                        # (70,5) to (95,45): right and down...
        self.assertLess(line[1][1], line[0][1])                                           # ... which is lower on a y-up screen

    def test_layers_that_are_not_drawn_and_transforms(self):
        pic = line_picture()
        base = decode_tek(bifgfx.tek_vectors(pic))[1][1]
        pic.frames[0].layers[0].props["transform"] = [1, 0, 0, 1, 10, 0]                  # ten units right
        moved = decode_tek(bifgfx.tek_vectors(pic))[1][1]
        self.assertAlmostEqual(moved[0][0] - base[0][0], 10 * min(1023 / 100.0, 779 / 50.0), delta=1.5)
        pic.frames[0].layers[0].props["visible"] = False
        self.assertIsNone(bifgfx.tek_vectors(pic))                                        # nothing drawn: no vectors
        self.assertIsNone(bifgfx.tek_vectors(solid_picture()))                            # a raster is not a path

    def test_raster_modes(self):
        r = rendering(line_picture(), scale=4)
        rgba = r.rgba()
        rgba[..., :3] = 255
        for mode in bifgfx.TEK_MODES:
            body, w, h = bifgfx.tek_raster(rgba, mode)
            self.assertTrue(body.endswith(bifgfx.US), mode)
            self.assertTrue(body[:1] in (bifgfx.GS, bifgfx.FS), mode)
            self.assertGreater(len(body), 100, mode)
            self.assertEqual((w, h), (r.W, r.H))
        with self.assertRaises(ValueError):
            bifgfx.tek_raster(rgba, "engrave")
        big = np.zeros((1600, 2000, 4), np.uint8)
        big[400:1200, 500:1500] = 255
        body, w, h = bifgfx.tek_raster(big, "hatch")
        self.assertLessEqual((w, h), (bifgfx.TEK_W, bifgfx.TEK_H))                       # no use giving it more than the screen has
        inverted = bifgfx.tek_raster(rgba, "hatch", invert=True)[0]
        self.assertNotEqual(inverted, bifgfx.tek_raster(rgba, "hatch")[0])

    def test_tek_writer_uses_vectors_else_says_it_hatches(self):
        buf = io.BytesIO()
        r = bifout.convert(line_picture(), "tek", buf)
        self.assertEqual(r.notes, [])
        self.assertEqual(len(decode_tek(buf.getvalue()[2:])), 2)
        buf = io.BytesIO()
        r = bifout.convert(solid_picture(), "tek", buf)                                   # a raster: nothing to stroke
        self.assertTrue(any("hatching" in n for n in r.notes))
        self.assertTrue(buf.getvalue().startswith(bifout.TEK_ERASE))


class Auto(unittest.TestCase):
    def test_pick_format(self):
        pick = bifgfx.pick_format
        capable = bifterm.Reply(True, None, None, True)
        no = bifterm.Reply(False, None, None, True)
        silent = bifterm.Reply(None, None, None, True)
        self.assertEqual(pick(capable, {}), "sixel")                                       # SIXEL if the terminal has it
        self.assertEqual(pick(no, {}), "ansi")                                             # else text, which always arrives
        self.assertEqual(pick(silent, {}), "ansi")                                         # silence counts as no SIXEL
        self.assertEqual(pick(bifterm.NOTHING, {}), "sixel")                               # nothing could be asked: as it always was
        self.assertEqual(pick(None, {}), "sixel")
        self.assertEqual(pick(no, {"KITTY_WINDOW_ID": "1"}), "kitty")
        self.assertEqual(pick(no, {"TERM": "xterm-kitty"}), "kitty")
        self.assertEqual(pick(no, {"TERM_PROGRAM": "ghostty"}), "kitty")
        self.assertEqual(pick(no, {"TERM_PROGRAM": "iTerm.app"}), "iterm")
        self.assertEqual(pick(no, {"LC_TERMINAL": "iTerm2"}), "iterm")
        self.assertEqual(pick(capable, {"KITTY_WINDOW_ID": "1"}), "kitty")                  # what it says it is wins over DA1

    @unittest.skipIf(mock is None, "no unittest.mock")
    def test_what_a_terminal_gets(self):
        pic = solid_picture()
        a = bifout.build_parser().parse_args([])
        opts = bifout.render_options(a)
        env = dict((k, v) for k, v in os.environ.items() if k not in ("KITTY_WINDOW_ID", "LC_TERMINAL"))
        env.update(TERM="xterm", TERM_PROGRAM="mintty")
        with mock.patch.dict(os.environ, env, clear=True):
            r, data = bifout.terminal_data(pic, a, "auto", opts, tty=False)
            self.assertTrue(data.startswith(b"\x1bP"))                                       # nothing known: SIXEL
            with mock.patch.object(bifout, "ask_terminal", return_value=bifterm.Reply(False, None, None, True)):
                r, data = bifout.terminal_data(pic, a, "auto", opts, tty=False)
                self.assertTrue(data.startswith(b"\x1b["))                                   # it says no SIXEL: coloured text
                with self.assertRaises(bif.BifError):                                        # ... and SIXEL asked for by name is refused
                    bifout.terminal_data(pic, a, "sixel", opts, tty=False)
            with mock.patch.object(bifout, "ask_terminal", return_value=bifterm.Reply(True, None, None, True)):
                self.assertTrue(bifout.terminal_data(pic, a, "auto", opts, tty=False)[1].startswith(b"\x1bP"))
            forced = bifout.build_parser().parse_args(["--force"])
            with mock.patch.object(bifout, "ask_terminal", return_value=bifterm.Reply(False, None, None, True)):
                self.assertTrue(bifout.terminal_data(pic, forced, "auto", opts, tty=False)[1].startswith(b"\x1bP"))
        with mock.patch.dict(os.environ, dict(env, KITTY_WINDOW_ID="3"), clear=True):
            self.assertTrue(bifout.terminal_data(pic, a, "auto", opts, tty=False)[1].startswith(b"\x1b_G"))
        with mock.patch.dict(os.environ, dict(env, TERM_PROGRAM="iTerm.app"), clear=True):
            self.assertTrue(bifout.terminal_data(pic, a, "auto", opts, tty=False)[1].startswith(b"\x1b]1337"))

    def test_background_auto_for_the_formats_that_have_alpha(self):
        pic = solid_picture(color=(0, 0, 0))                                                  # black ink
        a = bifout.build_parser().parse_args(["-b", "auto"])
        opts = bifout.render_options(a)
        dark = bifterm.Reply(True, (10, 10, 10), None, True)
        o = bifout.terminal_options(pic, a, opts, dark, fmt="sixel")
        self.assertEqual((o["transparent"], o["paper"]), (False, (10, 10, 10)))             # SIXEL: the terminal's exact colour
        o = bifout.terminal_options(pic, a, opts, dark, fmt="kitty")
        self.assertTrue(o["transparent"])                                                    # the others: the alpha channel
        self.assertEqual(o["ink"], bifout.LIGHT_INK)                                         # ... and ink that shows on a dark page


class Playing(unittest.TestCase):
    def animated(self):
        p = solid_picture((255, 0, 0), 16, 16)
        for colour in ((0, 255, 0), (0, 0, 255)):
            q = solid_picture(colour, 16, 16)
            p.frames.append(q.frames[0])
        p.animation = {"loop": 1}
        return p

    def test_an_animation_plays_as_text(self):
        clk = [0.0]
        out = io.BytesIO()

        def now():
            return clk[0]

        def sleep(s):
            clk[0] += s
        fo = dict(cols=2, rows=1, aspect=2.0, term=(80, 24))
        r = bifout.play(self.animated(), out, (10, 20), loop=1, clock=now, sleep=sleep, fmt="ansi", fmt_opts=fo)
        data = out.getvalue()
        for colour in (b"48;2;255;0;0", b"48;2;0;255;0", b"48;2;0;0;255"):
            self.assertEqual(data.count(colour), 1)                                         # one frame each, in order
        order = [data.index(c) for c in (b"48;2;255;0;0", b"48;2;0;255;0", b"48;2;0;0;255")]
        self.assertEqual(order, sorted(order))
        self.assertTrue(data.startswith(b"\n\n\x1b[2A\x1b7\x1b[?25l"))                      # room for 1 line + 1, then remember the place
        self.assertTrue(data.endswith(b"\x1b[?25h\n"))
        self.assertNotIn(b"X", data.replace(b"\x1b[2X", b""))                              # (text needs no erasing: no ECH)
        self.assertEqual((r.W, r.H), (16, 16))

    def test_formats_that_cannot_play_say_so(self):
        with self.assertRaises(bif.BifError):
            bifout.play(self.animated(), io.BytesIO(), (10, 20), fmt="kitty")

    def test_into_a_pipe_it_is_frame_0_and_says_how_to_play(self):
        buf = io.BytesIO()
        r = bifout.convert(self.animated(), "ansi", buf, fmt_opts=dict(cols=2, rows=1))
        self.assertTrue(any("frames" in n and "played" in n for n in r.notes))
        self.assertIn(b"48;2;255;0;0", buf.getvalue())
        self.assertNotIn(b"48;2;0;255;0", buf.getvalue())
        buf = io.BytesIO()
        r = bifout.convert(self.animated(), "kitty", buf)
        self.assertTrue(any("frames" in n and "played" not in n for n in r.notes))        # (kitty does not play)


class Command(unittest.TestCase):
    def run_main(self, *argv, **kw):
        p = subprocess.Popen([sys.executable, os.path.join(ROOT, kw.pop("tool", "bifout.py"))] + list(argv), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate(kw.get("input"))
        return p.returncode, out, err.decode("utf-8", "replace")

    def test_each_format_on_the_command_line(self):
        blob = bif.dumps(line_picture())
        d = tempfile.mkdtemp()
        path = os.path.join(d, "x.ans")
        rc, out, err = self.run_main("-f", "ansi", "--cols", "40", "--glyphs", "half", "--colors", "16", "-o", path, input=blob)
        self.assertEqual(rc, 0, err)
        with open(path, "rb") as f:
            text = f.read()
        lines = strip_sgr(text).split("\n")[:-1]
        self.assertEqual(set(len(l) for l in lines), set([40]))
        self.assertNotIn(b";2;", text)
        self.assertNotIn(b";5;", text)
        rc, out, err = self.run_main("-f", "tek", input=blob)                                # to a pipe: the stream, no mode switch
        self.assertEqual(rc, 0, err)
        self.assertTrue(out.startswith(bifout.TEK_ERASE) and out.endswith(bifgfx.US))
        rc, out, err = self.run_main("-f", "kitty", "--cols", "20", input=blob)
        self.assertEqual(rc, 0, err)
        self.assertTrue(out.startswith(b"\x1b_Ga=T,f=100,q=2,c=20,m="))
        rc, out, err = self.run_main("-f", "iterm", "--cols", "20", input=blob)
        self.assertEqual(rc, 0, err)
        self.assertIn(b"width=20", out)

    def test_auto_is_for_terminals(self):
        rc, out, err = self.run_main("-f", "auto", "-o", os.path.join(tempfile.mkdtemp(), "x.png"), input=bif.dumps(line_picture()))
        self.assertNotEqual(rc, 0)
        self.assertIn("terminal", err)
        rc, out, err = self.run_main("-f", "nonesuch", input=bif.dumps(line_picture()))
        self.assertNotEqual(rc, 0)


class BidetFormats(unittest.TestCase):
    def plan(self, *argv, **kw):
        import bidet
        kw.setdefault("stdout_tty", False)
        kw.setdefault("stdin_tty", False)
        kw.setdefault("env", {})
        kw.setdefault("columns", 80)
        kw.setdefault("pixels", ())
        args = bidet.build_parser().parse_args(list(argv))
        return bidet.make_plan(args, bidet.load_presets([os.path.join(ROOT, "presets.ini")]), **kw)

    def test_the_format_follows_the_file_name_unless_asked(self):
        self.assertEqual(self.plan("-o", "a.ans", "Hi").fmt, "ansi")
        self.assertEqual(self.plan("-o", "a.tek", "Hi").fmt, "tek")
        p = self.plan("--format", "kitty", "-o", "a.png", "Hi")
        self.assertEqual((p.fmt, p.format), ("kitty", "kitty"))                                # asked for: it wins over the name
        self.assertIn("-f kitty", p.shell())
        self.assertNotIn("-f", self.plan("-o", "a.ans", "Hi").stages()[-1])                    # (the name already says so)

    def test_a_terminal_gets_auto_and_the_fit(self):
        p = self.plan("Hi", stdout_tty=True, pixels=(1000, 600))
        self.assertEqual(p.fmt, "auto")
        self.assertEqual(p.bifout, ["--background", "auto", "--width", "950"])
        self.assertNotIn("-f", p.stages()[-1])                                                 # (auto is what bifout does by itself)
        p = self.plan("--format", "ansi", "Hi", stdout_tty=True, pixels=(1000, 600))
        self.assertEqual(p.bifout, ["--background", "auto", "--width", "950"])               # (the picture is sized for the terminal)
        self.assertIn("-f ansi", p.shell())
        p = self.plan("--format", "tek", "Hi", stdout_tty=True)
        self.assertNotIn("--background", p.bifout)                                             # Tektronix: no page to blend with
        self.assertEqual(p.bifout, ["--width", "1000"])                                        # (and the screen is 1024 wide at most)

    def test_bidet_run_gives_what_the_terminal_gets(self):
        import bidet
        p = self.plan("--format", "ansi", "Hi", stdout_tty=True, pixels=(600, 400))
        data = bidet.run(p, b"Hi\n")
        self.assertIn(b"\x1b[", data)
        self.assertTrue(data.endswith(b"\x1b[0m\n"))
        p = self.plan("--format", "kitty", "Hi", stdout_tty=True, pixels=(600, 400))
        self.assertTrue(bidet.run(p, b"Hi\n").startswith(b"\x1b_G"))
        p = self.plan("--format", "tek", "Hi", stdout_tty=True)
        out = bidet.run(p, b"Hi\n")
        self.assertTrue(out.startswith(bifout.TEK_ERASE) and out.endswith(bifgfx.US))


@unittest.skipIf(legacy() is None, "../3D/gfx-conv not found")
class ParityWithGfxConv(unittest.TestCase):
    """The port is exact: same picture in, same bytes out, as the converters it was ported from."""

    @classmethod
    def setUpClass(cls):
        cls.old = legacy()
        pic = bifin.convert(b"BIDeT 4D", "lettering", ink=(255, 255, 255), paper=(20, 30, 60), lettering=dict(font=None, size=80))
        r = rendering(pic, scale=0.8)
        cls.rgba = r.rgba()
        cls.W, cls.H = r.W, r.H
        cls.png = png_of(r)

    def test_kitty_and_iterm(self):
        self.assertEqual(bifgfx.kitty_sequence(self.png, 40, 10, 7), self.old["kitty"].kitty_sequence(self.png, 40, 10, 7))
        self.assertEqual(bifgfx.iterm_sequence(self.png, 40, 10), self.old["iterm"].iterm_sequence(self.png, 40, 10))

    def test_ansi_art(self):
        for glyphs in bifgfx.GLYPHS:
            for colors in (24, 256, 16):
                for bg in (None, (30, 40, 90)):
                    want = self.old["ans"].convert(self.png, self.old["ans"].ans_args(cols=60, rows=18, aspect=2.0, glyphs=glyphs,
                                                                                         colors=colors, background=bg))
                    cols, rows = bifgfx.ansi_size(self.W, self.H, 60, 18, 2.0, 80, 24)
                    self.assertEqual(bifgfx.ansi_art(self.rgba, cols, rows, glyphs, colors, bg), want, (glyphs, colors, bg))

    def test_tektronix_from_pixels(self):
        tek = self.old["tek"]
        for mode in bifgfx.TEK_MODES:
            self.assertEqual(bifgfx.tek_raster(self.rgba, mode)[0], tek.tek_stream(self.png, tek.tek_args(mode))[0], mode)
            for kw, arg in ((dict(invert=True), dict(invert=True)), (dict(gamma=0.6), dict(gamma=0.6)),
                            (dict(auto=False), dict(no_auto=True))):
                self.assertEqual(bifgfx.tek_raster(self.rgba, mode, **kw)[0], tek.tek_stream(self.png, tek.tek_args(mode, **arg))[0],
                                 (mode, kw))


if __name__ == "__main__":
    unittest.main()
