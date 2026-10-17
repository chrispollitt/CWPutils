#!/usr/bin/env python3
"""Tests for bifin_regions.py: art that is several kinds of art at once.   python tests/test_mixed.py

The art here is made up (a logo of strokes, a picture of half blocks, lines of prose in the way a neofetch or a
motd lays them out); the examples the feature was written for (a folder of motd files) are used where they are, and
skipped where they are not.
"""
from __future__ import print_function

import io
import os
import subprocess
import sys
import unittest

import numpy as np

os.environ.setdefault("BIDET_NO_QUERY", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import bif                                          # noqa: E402
import bifin_regions as R                           # noqa: E402
import bifin_text as T                              # noqa: E402
import bifrender                                    # noqa: E402

SAMPLES = os.path.join(ROOT, "samples")
MOTD = os.path.normpath(os.path.join(ROOT, "..", "..", "..", "Misc", "AsciiArt"))
FONT = T.find_font()

LOGO = [u"   _____    ",
        u"  /     \\   ",
        u" |  o o  |  ",
        u"  \\  ^  /   ",
        u"   -----    "]
INFO = [u"Linux localhost 4.9.232-ga8a0fbc4fb8e #0 SMP PREEMPT 2020",
        u"CPU: Intel i7-7700HQ @ 2.80GHz",
        u"Memory: 3535MiB / 8192MiB",
        u"Uptime: 5 hours, 30 mins"]


def rows_with_text(art, info, gap=6):
    out = []
    for i in range(max(len(art), len(info))):
        a = art[i] if i < len(art) else u" " * len(art[0])
        out.append(a + u" " * gap + (info[i] if i < len(info) else u""))
    return u"\n".join(out) + u"\n"


def half_blocks(w, h):
    """A coloured picture, as chafa draws one: a half block with a foreground and a background colour in every cell."""
    lines = []
    for y in range(h):
        row = []
        for x in range(w):
            r, g, b = 40 + 25 * x % 200, 60 + 40 * y % 190, 200 - 20 * x % 150
            row.append(u"\x1b[38;2;%d;%d;%dm\x1b[48;2;%d;%d;%dm▄" % (r, g, b, 255 - r, 255 - g, 255 - b))
        lines.append(u"".join(row) + u"\x1b[0m")
    return lines


def picture_and_text():
    pic = half_blocks(10, 5)
    text = [u"The picture says:  Welcome to the machine", u"Kernel: 4.9.232  Uptime: 5 hours, 30 mins",
            u"Host: VMware7,1", u"", u""]
    out = []
    for p, t in zip(pic, text):
        out.append(p + u"      " + t)
    return u"\n".join(out) + u"\n"


def imp(text, **kw):
    return T.import_text(text.encode("utf-8"), **kw)


def layer(pic, id):
    for L in pic.layers:
        if L.id == id:
            return L
    return None


def grid_of(text):
    return T.parse(text, 0, rows=24)


def text_mask(text):
    g = grid_of(text)
    return g, R.text_cells(g, R.kinds(g))


def run(*args, **kw):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "bifin.py")] + list(args), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    out, err = p.communicate(kw.get("input"))
    return p.returncode, out, err


class Words(unittest.TestCase):
    """Which cells are prose."""

    def test_a_line_of_info_is_text_with_its_numbers_and_signs(self):
        g, m = text_mask(INFO[0] + u"\n")
        self.assertEqual(sum(m[0]), sum(1 for c in INFO[0] if c != u" "))       # the 8s, the # and the dots too

    def test_key_and_value(self):
        for line in INFO[1:]:
            g, m = text_mask(line + u"\n")
            self.assertEqual(sum(m[0]), sum(1 for c in line if c != u" "), line)

    def test_shading_made_of_letters_is_not_text(self):
        art = u"\n".join([u",tyxfyi`,0!  Of  PHPnIgBm\"", u"loolloddol;.  lxyyx+`  cX:  dH%", u"gBe vR&5)z@Hv \"ODa:8BA", u"MMMMMMMMMMkk MMMMMMMMWd."])
        g, m = text_mask(art + u"\n")
        self.assertFalse(any(any(r) for r in m))

    def test_fill_characters_are_not_words(self):
        g, m = text_mask(u"8888888 8888888 88888\n8888888 8888888 88888\n")
        self.assertFalse(any(any(r) for r in m))

    def test_a_cowsay_bubble_keeps_its_sides(self):
        art = u" ___________\n< Hello there >\n -----------\n"
        g, m = text_mask(art)
        self.assertFalse(any(any(r) for r in m))                      # beside drawing: line art sets the words itself

    def test_a_caption_alone_is_text_and_a_word_in_a_drawing_is_not(self):
        g, m = text_mask(u"  ______\n /      \\\n|  jgs   |\n \\______/\n\n  cmlaptop\n")
        self.assertFalse(any(m[2]))
        self.assertTrue(all(m[5][2:10]))

    def test_an_underline_belongs_to_the_text_over_it(self):
        g, m = text_mask(u"cpsol\n-----\n")
        self.assertTrue(all(m[0][:5]) and all(m[1][:5]))

    def test_a_number_a_tab_away(self):
        g, m = text_mask(u"SunOS 5.11        11.4\n")
        self.assertTrue(all(m[0][18:22]))

    def test_token_classes(self):
        for tok, cls in (("Linux", "S"), ("4.9.232-ga8a0fbc4fb8e", "S"), ("/dev/ttys000", "S"), ("19H4", "W"), ("OS:", "W"),
                         ("MMMMMMMM", "P"), ("(oo)", "W"), ("PHPnIgBm", "P"), ("loolloddol", "P"), ("-----", "P"),
                         ("macOS", "S"), ("VMware7,1", "S"), ("x86_64", "W")):
            self.assertEqual(R._token_class(tok), cls, tok)


class Cells(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(R.kind_of(" ", None), "b")
        self.assertEqual(R.kind_of(" ", (0, 0, 0)), "b")                  # a terminal that says black everywhere
        self.assertEqual(R.kind_of(" ", (10, 20, 30)), "p")
        self.assertEqual(R.kind_of(u"▄", None), "p")
        self.assertEqual(R.kind_of(u"⣿", None), "p")
        self.assertEqual(R.kind_of("x", (0, 0, 0)), "c")
        self.assertEqual(R.kind_of("x", (200, 0, 0)), "p")

    def test_a_screen_that_says_black_behind_every_character_is_not_a_picture(self):
        art = u"".join(u"\x1b[40m" + line + u"\x1b[0m\n" for line in rows_with_text(LOGO, INFO).split(u"\n") if line)
        g = grid_of(art)
        self.assertNotIn(R.BLOCK, R.plan(g, T.Options()).modes)


class Plans(unittest.TestCase):
    def test_line_art_and_prose_is_one_method_with_text_cells(self):
        pl = R.plan(grid_of(rows_with_text(LOGO, INFO)), T.Options())
        self.assertEqual(pl.modes, set([R.LINE, R.TEXT]))
        self.assertFalse(pl.mixed)

    def test_picture_and_prose_is_mixed(self):
        pl = R.plan(grid_of(picture_and_text()), T.Options())
        self.assertIn(R.BLOCK, pl.modes)
        self.assertIn(R.TEXT, pl.modes)
        self.assertTrue(pl.mixed)

    def test_every_cell_has_one_label_and_blank_cells_none(self):
        g = grid_of(picture_and_text())
        pl = R.plan(g, T.Options())
        for y in range(g.rows):
            for x in range(g.cols):
                self.assertEqual(pl.labels[y][x] is None, R.kind_of(g.ch[y][x], g.bg[y][x]) == "b" or g.ch[y][x] == " " and g.bg[y][x] is None, (y, x))

    def test_a_box_two_blanks_from_a_picture_is_not_part_of_it(self):
        # motd-cygwin: a half-block picture, two blank columns, then a box of | and _ (line art) with a caption in it
        pic = half_blocks(10, 8)
        box = [u" " + u"_" * 22] + [u"|" + u" " * 22 + u"|"] * 3 + [u"|" + u"   /\\  /\\  ( o o )   " + u"|"] + [u"|" + u" " * 22 + u"|"] * 2 + [u"|" + u"_" * 22 + u"|"]
        art = u"\n".join(p + u"  " + b for p, b in zip(pic, box)) + u"\n"
        pl = R.plan(grid_of(art), T.Options())
        self.assertIn(R.BLOCK, pl.modes)
        self.assertEqual(pl.labels[3][12 + 0], R.LINE)                    # the box's left edge is line art, not part of the picture
        self.assertEqual(pl.labels[3][0], R.BLOCK)

    def test_a_few_characters_in_a_picture_stay_in_it(self):
        pic = [u"\x1b[7m \x1b[7m \x1b[7m \x1b[7m \x1b[7m \x1b[7m \x1b[7m \x1b[7m \x1b[0m",
               u"\x1b[7m \x1b[7m \x1b[7m~\x1b[7m_\x1b[7m \x1b[7m \x1b[7m \x1b[0m",
               u"\x1b[7m \x1b[7m \x1b[7m \x1b[7m \x1b[7m \x1b[7m \x1b[7m \x1b[7m \x1b[0m"]
        pl = R.plan(grid_of(u"\n".join(pic) + u"\n"), T.Options())
        self.assertEqual(pl.modes, set([R.BLOCK]))

    def test_a_stray_character_follows_the_drawing_it_is_in(self):
        g = grid_of(u"\n".join(LOGO) + u"\n         .\n")
        self.assertEqual(R.plan(g, T.Options()).modes, set([R.LINE]))

    def test_a_shaded_logo_touching_a_figlet_title_is_two_things(self):
        # one blank column between them, so they are one piece of art: it is split into the fill and the strokes
        fill = [u"@@@@@@@@@@"] * 6
        title = [u"  _    _  _ ", u" / \\  | || |", u"/ _ \\ | || |", u"\\_/ \\_\\|_||_|", u" _   _  __  ", u"|_| |_|/__\\ "]
        art = u"\n".join(f + u" " + t for f, t in zip(fill, title)) + u"\n"
        g = grid_of(art)
        pl = R.plan(g, T.Options())
        self.assertEqual(pl.modes, set([R.TONE, R.LINE]))
        self.assertTrue(all(pl.labels[y][x] == R.TONE for y in range(6) for x in range(10)))
        self.assertTrue(all(pl.labels[y][x] == R.LINE for y in range(6) for x in range(11, 23) if g.ch[y][x] != u" "))

    def test_commas_among_the_fill_of_a_title_stay_with_it(self):
        art = u"\n".join([u"88,888, 88  88", u"88  88  88  88", u"88  88  88  88", u"88  88  '88888'", u"88  88  88  88"]) + u"\n"
        pl = R.plan(grid_of(art), T.Options())
        self.assertNotIn(R.LINE, pl.modes)

    def test_no_cells(self):
        pl = R.plan(grid_of(u"\n\n"), T.Options())
        self.assertEqual(pl.modes, set())
        self.assertFalse(pl.mixed)

    def test_show(self):
        s = R.show(R.plan(grid_of(picture_and_text()), T.Options()))
        self.assertTrue(s.splitlines()[0].startswith("BBBBBBBBBB"))
        self.assertIn("T", s.splitlines()[0])


@unittest.skipIf(not FONT, "no monospace font found")
class Import(unittest.TestCase):
    def test_picture_and_prose_in_one_picture(self):
        pic = imp(picture_and_text())
        self.assertEqual(pic.meta["mode"], "mixed")
        self.assertEqual(sorted(pic.meta["regions"]), ["block", "text"])
        self.assertEqual(bif.check(pic)[0], [])
        kinds = dict((L.id, L.kind) for L in pic.layers)
        self.assertEqual(kinds["picture"], "raster")
        self.assertEqual(kinds["text"], "vector")                         # the prose is outlines, not a blur of pixels
        self.assertEqual(kinds["cells"], "cells")

    def test_tone_in_a_mixed_picture_gets_the_arts_polarity_not_the_pages(self):
        # coloured art is light on dark whatever the page is; given the page's polarity (light), a solid shape was
        # traced with two outlines instead of one (the green @ robot of motd-android)
        blob = [u"\x1b[32m" + u"@" * 12 + u"\x1b[m"] * 2 + [u"\x1b[32m" + u"@" * w + u"\x1b[m" for w in (14, 14, 12, 12, 10, 10)]
        art = u"\n" + u"\n".join(blob) + u"\n\nLinux localhost 4.9.232 Mon Nov 9 04:25:13 UTC 2020 aarch64\n"
        auto = imp(art, cells=False, tone_fill="off")
        self.assertEqual(auto.meta["mode"], "mixed")
        self.assertEqual(auto.meta["polarity"], "dark-on-light")           # (the page is light: no block picture)
        n = lambda p: len(layer(p, "tone").start) - 1
        self.assertEqual(n(auto), n(imp(art, cells=False, dark=True, tone_fill="off")))
        self.assertLess(n(auto), n(imp(art, cells=False, dark=False, tone_fill="off")))

    def test_the_page_is_black_for_a_coloured_picture(self):
        pic = imp(picture_and_text())
        self.assertEqual(pic.palette[1]["rgb"], [0, 0, 0])
        self.assertEqual(pic.meta["polarity"], "light-on-dark")
        self.assertEqual(pic.palette[0]["rgb"], [229, 229, 229])

    def test_layer_ids_are_unique_and_the_palette_is_shared(self):
        pic = imp(picture_and_text(), cells=False)
        ids = [L.id for L in pic.layers]
        self.assertEqual(len(ids), len(set(ids)), ids)
        for L in pic.layers:
            if L.kind == "vector":
                self.assertLess(int(L.stroke.max()), len(pic.palette))

    def test_one_method_is_not_mixed(self):
        with io.open(os.path.join(SAMPLES, "cow.txt"), "rb") as f:
            pic = T.import_text(f.read())
        self.assertEqual(pic.meta["mode"], "line")
        self.assertNotIn("regions", pic.meta)

    def test_line_art_with_prose_sets_every_character_of_the_prose_as_a_letter(self):
        pic = imp(rows_with_text(LOGO, INFO))
        self.assertEqual(pic.meta["mode"], "line")
        letters = len(set(layer(pic, "text").group.tolist()))
        want = sum(1 for line in INFO for c in line if c != u" ")
        self.assertGreaterEqual(letters, want - 4)                       # (a glyph with no outline, like a lone dot, has none)
        self.assertIn(u"8", u"".join(INFO))

    def test_forcing_it(self):
        a = imp(picture_and_text(), mode="mixed")
        self.assertEqual(a.meta["mode"], "mixed")
        b = imp(u"\n".join(LOGO) + u"\n", mode="mixed")                  # nothing to split: the usual way
        self.assertEqual(b.meta["mode"], "line")

    def test_text_mode_sets_everything_in_the_font(self):
        pic = imp(u"|_ - |\n(o) 88 #\n", mode="text")
        self.assertIsNone(layer(pic, "strokes"))
        self.assertEqual(len(set(layer(pic, "text").group.tolist())), 10)

    def test_crop_and_no_crop(self):
        full = imp(picture_and_text(), crop=False)
        cut = imp(picture_and_text())
        self.assertLessEqual(cut.width, full.width)
        self.assertLessEqual(cut.height, full.height)
        g = full.grid
        self.assertEqual(full.width, g["cols"] * g["cell_width"] + 2 * g["cell_width"])

    def test_one_cells_layer_and_none_if_not_wanted(self):
        self.assertEqual(sum(1 for L in imp(picture_and_text()).layers if L.kind == "cells"), 1)
        self.assertEqual(sum(1 for L in imp(picture_and_text(), cells=False).layers if L.kind == "cells"), 0)

    def test_it_draws(self):
        pic = imp(picture_and_text())
        r = bifrender.render(pic, scale=1)
        rgb = r.flatten()
        self.assertEqual(rgb.shape[:2], (int(pic.height), int(pic.width)))
        self.assertFalse(r.uniform)
        # the picture is where the picture is (left), light text on the black page where the text is (right)
        g = pic.grid
        left = rgb[:, :int(8 * g["cell_width"])].reshape(-1, 3)
        self.assertGreater(len(set(map(tuple, left.tolist()))), 20)
        right = rgb[:, int(14 * g["cell_width"]):].reshape(-1, 3)
        self.assertGreater(right.max(), 200)

    def test_same_input_same_bytes(self):
        self.assertEqual(bif.dumps(imp(picture_and_text())), bif.dumps(imp(picture_and_text())))

    def test_the_options_of_the_import_are_kept_in_the_file(self):
        pic = imp(picture_and_text(), weight=1.5)
        self.assertEqual(pic.meta["generator"]["args"]["weight"], 1.5)

    def test_explicit_colours_are_used(self):
        pic = imp(picture_and_text(), ink=(10, 20, 30), paper=(250, 240, 230))
        self.assertEqual(pic.palette[0]["rgb"], [10, 20, 30])
        self.assertEqual(pic.palette[1]["rgb"], [250, 240, 230])

    def test_mono(self):
        pic = imp(picture_and_text(), color="off")
        self.assertEqual(pic.meta["mode"], "mixed")
        self.assertEqual(bif.check(pic)[0], [])


def robot(color=u"\x1b[32m"):
    """A solid logo of @ with two eyes (blank cells), then a line of prose: what motd-android is, in miniature."""
    rows = [u"   @@@@@@@@@@@@   ", u"  @@@@@@@@@@@@@@  ", u" @@@@  @@@@  @@@@ ", u" @@@@  @@@@  @@@@ ", u" @@@@@@@@@@@@@@@@ ",
            u" @@@@@@@@@@@@@@@@ ", u" @@@@@@@@@@@@@@@@ ", u"  @@@@@@@@@@@@@@  ", u"   @@@@@@@@@@@@   ", u"     @@@@  @@@@     "]
    return u"\n".join(color + r + u"\x1b[m" for r in rows) + u"\n\nLinux localhost 4.9.232 Mon Nov 9 04:25:13 UTC 2020 aarch64\n"


@unittest.skipIf(not FONT, "no monospace font found")
class Fill(unittest.TestCase):
    """A solid logo (all @, mostly M) in mixed art is a solid shape, not its outline."""

    def test_solid_regions(self):
        g = grid_of(robot())
        self.assertTrue(R.solid_region(g, [[c == u"@" for c in row] for row in g.ch]))
        share, n = R.solidity(g, [[c != u" " for c in row] for row in g.ch])
        self.assertGreater(share, 0.6)
        with io.open(os.path.join(SAMPLES, "tone80.txt"), "rb") as f:
            t = grid_of(f.read().decode("utf-8"))
        self.assertFalse(R.solid_region(t, [[c != u" " for c in row] for row in t.ch]))      # a photograph in characters: no

    def test_the_logo_is_filled_and_has_no_outline(self):
        pic = imp(robot(), cells=False)
        self.assertEqual(pic.meta["mode"], "mixed")
        f = layer(pic, "fill")
        self.assertIsNotNone(f)
        self.assertEqual(f.kind, "vector")
        self.assertIsNone(layer(pic, "tone"))                            # the shape is its own outline
        self.assertEqual(pic.layers[0].id, "fill")                       # under everything else

    def test_eyes_are_holes(self):
        f = layer(imp(robot(), cells=False), "fill")
        groups = f.group.tolist()
        self.assertGreater(len(groups), len(set(groups)))               # a group has more than one path: the body and its holes
        self.assertTrue(all(int(v) & 2 for v in f.flags.tolist()))      # even-odd

    def test_bands_of_colour_keep_their_colours(self):
        rows = []
        for col in (u"\x1b[31m", u"\x1b[33m", u"\x1b[34m"):
            rows += [col + u"M" * 18 + u"\x1b[m"] * 3
        art = u"\n".join(rows) + u"\n\nLinux localhost 4.9.232 Mon Nov 9 04:25:13 UTC 2020 aarch64\n"
        f = layer(imp(art, cells=False), "fill")
        self.assertIsNotNone(f)
        self.assertEqual(len(set(f.fill.tolist())), 3)

    def test_a_diagonal_line_of_cells_stays_a_line(self):
        # the robot's antennae: single cells touching at corners.  One cell blurs to less than half: they must be joined
        chain = [u" " * i + u"@" + u" " * (19 - i) for i in range(8)]                 # 8 cells, touching only at corners
        rows = chain + [u"@" * 20] * 4                                                  # hanging off a block
        art = u"\n".join(rows) + u"\n\nLinux localhost 4.9.232 Mon Nov 9 04:25:13 UTC 2020 aarch64\n"
        pic = imp(art, cells=False)
        f = layer(pic, "fill")
        self.assertIsNotNone(f)
        chh, y0 = pic.grid["cell_height"], pic.grid["y"]
        block_top = y0 + 8 * chh
        # one shape runs from the chain's first cell into the block: not a heap of beads, not a stump
        self.assertTrue(any(p[:, 1].min() < y0 + 1.5 * chh and p[:, 1].max() > block_top + 2 * chh for p in f.paths()),
                        [(round(float(p[:, 1].min())), round(float(p[:, 1].max()))) for p in f.paths()])

    def test_bands_meet_flush_on_the_outside(self):
        rows = []
        for col in (u"\x1b[31m", u"\x1b[33m", u"\x1b[34m"):
            rows += [col + u"M" * 20 + u"\x1b[m"] * 4
        art = u"\n".join(rows) + u"\n\nLinux localhost 4.9.232 Mon Nov 9 04:25:13 UTC 2020 aarch64\n"
        pic = imp(art, cells=False)
        rgb = bifrender.render(pic, scale=1).flatten().astype(int)
        g = pic.grid
        page = rgb[0, 0]
        ink = np.abs(rgb - page).max(2) > 40
        for k in (1, 2):                                                 # the two junctions between bands
            y = int(g["y"] + 4 * k * g["cell_height"])
            lefts = [int(np.nonzero(ink[yy])[0].min()) for yy in range(y - 6, y + 7)]
            rights = [int(np.nonzero(ink[yy])[0].max()) for yy in range(y - 6, y + 7)]
            self.assertLessEqual(max(lefts) - min(lefts), 2, lefts)      # no notch where one colour meets the next
            self.assertLessEqual(max(rights) - min(rights), 2, rights)

    def test_the_fill_does_not_depend_on_how_much_ink_the_font_has(self):
        # DejaVu's glyphs have a fifth less ink than Consolas's: the same art must fill the same
        import bifin_text
        rows = [u",tyxfyi`,0!  Of  PHPnIgBm", u"?Pn!::|\"`:mt gHz nH0 ,OBr", u" !Wr  \\Xt  +5yyz>  ,l,", u" IN, \\X? iA!,:(Gl \"m|",
                u" nP.  \\mt %t  yA`\"m|  ,mc.X_", u"  +Wt  \\mt %i  aA`>m|  ,mc.X|", u"   lNy|,,\\_ :Ot r%^`.>Pz :Gy,``\\Xc"]
        g = grid_of(u"\n".join(u"\x1b[36m" + r + u"\x1b[m" for r in rows) + u"\n")
        keep = [[c != u" " for c in row] for row in g.ch]
        real = bifin_text.Glyphs(12, 24, None)

        class Fainter(object):
            cw, ch, path = real.cw, real.ch, real.path

            def mask(self, c):
                return real.mask(c) * 0.8

        pal = bifin_text._Palette((0, 0, 0), (255, 255, 255))
        a = R.fill_layer(g, keep, real, 12, pal, (0, 0, 0), (255, 255, 255))
        b = R.fill_layer(g, keep, Fainter(), 12, pal, (0, 0, 0), (255, 255, 255))
        area = lambda paths: sum(abs(float(np.dot(p[:, 0], np.roll(p[:, 1], 1)) - np.dot(p[:, 1], np.roll(p[:, 0], 1)))) / 2 for p in paths)
        self.assertEqual(len(a[1]), len(b[1]))
        self.assertAlmostEqual(area(a[1]) / area(b[1]), 1.0, delta=0.03)

    def test_it_draws_solid(self):
        pic = imp(robot(), cells=False)
        rgb = bifrender.render(pic, scale=1).flatten()
        g = pic.grid
        cy, cx = int(g["y"] + 5.5 * g["cell_height"]), int(g["x"] + 8.5 * g["cell_width"])        # the middle of the body
        px = rgb[cy, cx]
        self.assertGreater(int(px[1]), 150)                              # green, not the white of the page
        self.assertLess(int(px[0]), 80)

    def test_off_gives_the_outline(self):
        pic = imp(robot(), cells=False, tone_fill="off")
        self.assertIsNone(layer(pic, "fill"))
        self.assertIsNotNone(layer(pic, "tone"))

    def test_a_solid_picture_that_is_not_mixed_is_filled_too(self):
        solid = u"\n".join([u"@" * 14] * 8) + u"\n"
        self.assertIsNotNone(layer(imp(solid, cells=False), "fill"))
        self.assertIsNone(layer(imp(solid, cells=False, tone_fill="off"), "fill"))
        self.assertIsNotNone(layer(imp(solid, mode="tone", cells=False, tone_fill="on"), "fill"))

    def test_an_explicit_tone_mode_keeps_its_outlines(self):
        solid = u"\n\n" + u"\n".join([u"  " + u"@" * 14] * 8) + u"\n\n"          # (a margin round it, so there is an edge to trace)
        pic = imp(solid, mode="tone", cells=False)                       # (-m tone asks for tone's outlines)
        self.assertIsNone(layer(pic, "fill"))
        self.assertIsNotNone(layer(pic, "tone"))

    def test_coloured_letters_make_a_wordmark_but_the_same_letters_in_the_default_colour_do_not(self):
        # the CloudLinux logo: every letter there is, in one colour; a picture in characters has its tone from the default colour
        rows = [u",tyxfyi`,0!  Of  PHPnIgBm", u"?Pn!::|\"`:mt gHz nH0 ,OBr", u" !Wr  \\Xt  +5yyz>  ,l,", u" IN, \\X? iA!,:(Gl \"m|",
                u" nP.  \\mt %t  yA`\"m|  ,mc.X_", u"  +Wt  \\mt %i  aA`>m|  ,mc.X|", u"   lNy|,,\\_ :Ot r%^`.>Pz :Gy,``\\Xc"]
        col = u"\n".join(u"\x1b[36m" + r + u"\x1b[m" for r in rows) + u"\n"
        plain = u"\n".join(rows) + u"\n"
        g = grid_of(col)
        keep = [[c != u" " for c in row] for row in g.ch]
        self.assertFalse(R.solidity(g, keep)[0] >= R.FILL_SOLID)         # no one letter dominates
        self.assertTrue(R.solid_region(g, keep))
        gp = grid_of(plain)
        self.assertFalse(R.solid_region(gp, [[c != u" " for c in row] for row in gp.ch]))
        self.assertIsNotNone(layer(imp(col, cells=False), "fill"))
        self.assertIsNone(layer(imp(plain, cells=False), "fill"))

    def test_a_single_method_picture_is_untouched(self):
        with io.open(os.path.join(SAMPLES, "tone80.txt"), "rb") as f:
            self.assertIsNone(layer(T.import_text(f.read()), "fill"))

    def test_the_option_is_kept_in_the_file(self):
        self.assertEqual(imp(robot(), cells=False, tone_fill="on").meta["generator"]["args"]["tone_fill"], "on")


class Render(unittest.TestCase):
    def test_a_one_colour_layer_under_a_many_colour_one(self):
        # bifrender.compose compared a tuple colour with an array colour (an ambiguous truth value)
        pic = bif.Picture(40, 40, palette=[{"rgb": [0, 0, 0], "role": "ink"}, {"rgb": [255, 255, 255], "role": "paper"},
                                           {"rgb": [200, 0, 0]}], background=1)
        fr = pic.add_frame()
        fr.layers.append(bif.vector_layer([[(2, 2), (30, 2), (30, 30), (2, 30)]], widths=[0.0], strokes=[0], fills=[2],
                                          closed=[1], id="a", width=0))
        fr.layers.append(bif.vector_layer([[(5, 5), (35, 5)], [(5, 9), (35, 9)]], widths=[2.0, 2.0], strokes=[0, 2], id="b", width=2))
        self.assertEqual(bifrender.render(pic, scale=1).flatten().shape, (40, 40, 3))


@unittest.skipIf(not FONT, "no monospace font found")
class Cli(unittest.TestCase):
    def test_mode_mixed_and_the_report(self):
        rc, blob, err = run("-m", "mixed", "-v", input=picture_and_text().encode("utf-8"))
        self.assertEqual(rc, 0, err)
        self.assertEqual(bif.loads(blob).meta["mode"], "mixed")
        self.assertIn(b"mixed:", err)

    def test_auto_does_it_without_being_asked(self):
        rc, blob, err = run(input=picture_and_text().encode("utf-8"))
        self.assertEqual(rc, 0, err)
        self.assertEqual(bif.loads(blob).meta["mode"], "mixed")

    def test_a_plain_mode_is_left_alone(self):
        rc, blob, err = run("-m", "tone", input=picture_and_text().encode("utf-8"))
        self.assertEqual(rc, 0, err)
        self.assertNotEqual(bif.loads(blob).meta["mode"], "mixed")


@unittest.skipIf(not os.path.isdir(MOTD), "the AsciiArt examples are not here")
class Motd(unittest.TestCase):
    """The examples the feature is for, in place (they are not ours to copy into the repository)."""

    def modes(self, name):
        with io.open(os.path.join(MOTD, "motd-" + name), "rb") as f:
            data = f.read()
        text, enc = T.decode2(data, None)
        return R.plan(T.parse(text, 0, rows=24), T.Options())

    def test_cygwin_is_a_picture_a_drawing_and_a_caption(self):
        pl = self.modes("cygwin")
        self.assertEqual(pl.modes, set([R.BLOCK, R.LINE, R.TEXT]))
        self.assertEqual(pl.labels[2][52], R.LINE)                       # the box and the figlet in it are line art, not part of the picture
        self.assertEqual(pl.labels[15][54], R.LINE)                      # (the / of the c of cygwin)

    def test_macos_is_a_shaded_logo_swatches_and_text(self):
        self.assertEqual(self.modes("macos").modes, set([R.BLOCK, R.TONE, R.TEXT]))

    def test_solaris(self):
        self.assertEqual(self.modes("solaris").modes, set([R.BLOCK, R.LINE, R.TEXT]))

    def test_android_keeps_its_kernel_line_whole(self):
        pl = self.modes("android")
        self.assertIn(R.TEXT, pl.modes)
        self.assertEqual(pl.count(R.TEXT), sum(1 for c in u"Linux localhost 4.9.232-ga8a0fbc4fb8e-ab6960310 #0 SMP PREEMPT Mon Nov 9 04:25:13 UTC 2020 aarch64 Android" if c != u" "))

    def test_raspbian_and_cloudlinux_are_one_method(self):
        self.assertFalse(self.modes("raspbian").mixed)
        self.assertFalse(self.modes("cloudlinux").mixed)

    def test_ubuntu_is_not_a_picture(self):
        self.assertNotIn(R.BLOCK, self.modes("ubuntu").modes)


class Samples(unittest.TestCase):
    """The samples that were one method stay one method: bifin's parity with unascii does not change."""

    def test_no_sample_is_split(self):
        names = sorted(n for n in os.listdir(SAMPLES) if n.endswith((".txt", ".ans")))
        for name in names:
            with io.open(os.path.join(SAMPLES, name), "rb") as f:
                data = f.read()
            text, enc = T.decode2(data, None)
            g = T.parse(text, 80 if name.endswith(".ans") else 0, rows=24, glyphs=enc in ("cp437", "437") or name.endswith(".ans"))
            self.assertFalse(R.plan(g, T.Options()).mixed, name)


if __name__ == "__main__":
    unittest.main()
