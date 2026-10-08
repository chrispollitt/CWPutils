#!/usr/bin/env python3
"""Tests for the lettering importer: ttfglyphs' metrics / kerning / names, fonts.py, bifin_lettering.py, bifin -f lettering.
Self-contained: the fonts are written by ttfbuild.py.   python tests/test_lettering.py"""
from __future__ import print_function

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

# the tests must not ask the terminal they happen to run in (bifterm.py): it may not have SIXEL
os.environ.setdefault("BIDET_NO_QUERY", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import bif                                          # noqa: E402
import bifin                                        # noqa: E402
import bifin_lettering                              # noqa: E402
import bifrender                                    # noqa: E402
import fonts                                        # noqa: E402
import ttfbuild                                     # noqa: E402
import ttfglyphs                                    # noqa: E402

TMP = tempfile.mkdtemp(prefix="bidet-lettering-")
FONTS = os.path.join(TMP, "fonts")
os.makedirs(FONTS)
PLAIN = ttfbuild.write(os.path.join(FONTS, "test-regular.ttf"), family="Testface", style="Regular", kern={("A", "V"): -200})
BOLD = ttfbuild.write(os.path.join(FONTS, "test-bold.ttf"), family="Testface", style="Bold", bold=True)
OTHER = ttfbuild.write(os.path.join(FONTS, "other-italic.ttf"), family="Otherface", style="Italic", italic=True)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def letters(pic):
    return [L for L in pic.layers if L.id == "text"][0]


def extent(pic):
    """(x0, y0, x1, y1) of the ink in a lettering picture."""
    xy = letters(pic).xy
    return xy[:, 0].min(), xy[:, 1].min(), xy[:, 0].max(), xy[:, 1].max()


class TrueTypeMetrics(unittest.TestCase):
    def setUp(self):
        self.tt = ttfglyphs.TrueType(PLAIN)

    def test_vertical_metrics(self):
        self.assertEqual(self.tt.metrics(), {"ascent": 800, "descent": 200, "line_gap": 100})

    def test_advances(self):
        g = self.tt.glyph_id
        self.assertEqual([self.tt.advance(g(ord(c))) for c in "AB V"], [600, 700, 300, 600])
        self.assertEqual(self.tt.advance(g(ord("Z"))), 400)                      # unmapped: .notdef

    def test_kerning_pairs(self):
        g = self.tt.glyph_id
        self.assertEqual(self.tt.kerning(), {(g(ord("A")), g(ord("V"))): -200})
        self.assertEqual(ttfglyphs.TrueType(BOLD).kerning(), {})                  # a font without a kern table

    def test_names_and_style_flags(self):
        self.assertEqual(self.tt.names()["family"], "Testface")
        self.assertFalse(self.tt.names()["bold"])
        self.assertTrue(ttfglyphs.TrueType(BOLD).names()["bold"])
        self.assertTrue(ttfglyphs.read_names(OTHER)["italic"])
        self.assertEqual(ttfglyphs.read_names(OTHER)["family"], "Otherface")

    def test_read_names_refuses_what_is_not_a_font(self):
        junk = os.path.join(TMP, "junk.ttf")
        with open(junk, "wb") as f:
            f.write(b"not a font at all" * 4)
        self.assertIsNone(ttfglyphs.read_names(junk))

    def test_a_glyph_with_a_hole_has_two_contours(self):
        self.assertEqual(len(self.tt.contours(ord("B"))), 2)
        self.assertEqual(len(self.tt.contours(ord(" "))), 0)


class FontLookup(unittest.TestCase):
    def test_catalog_and_families(self):
        self.assertEqual(fonts.families([FONTS]), ["Otherface", "Testface"])
        self.assertEqual(len(fonts.catalog([FONTS])), 3)

    def test_family_names_are_case_blind_and_partial(self):
        for name in ("testface", "TESTFACE", "test"):
            self.assertEqual(fonts.resolve(name, dirs=[FONTS]).family, "Testface", name)

    def test_style_is_matched_and_faked_when_missing(self):
        f = fonts.resolve("testface", bold=True, dirs=[FONTS])
        self.assertEqual((f.style, f.need_bold), ("Bold", False))
        f = fonts.resolve("testface", italic=True, dirs=[FONTS])                  # the family has no italic
        self.assertEqual((f.need_italic, f.need_bold), (True, False))
        f = fonts.resolve("otherface", italic=True, dirs=[FONTS])
        self.assertFalse(f.need_italic)
        f = fonts.resolve("testface", dirs=[FONTS])
        self.assertEqual(f.style, "Regular")                                      # plain asked: the plain face

    def test_plain_style_beats_a_variant_in_the_same_family(self):
        # Arial's family also holds "Narrow" and "Black": asking for Arial must give Regular
        d = os.path.join(TMP, "variants")
        os.makedirs(d)
        ttfbuild.write(os.path.join(d, "a-narrow.ttf"), family="Variant", style="Narrow")
        ttfbuild.write(os.path.join(d, "b-regular.ttf"), family="Variant", style="Regular")
        ttfbuild.write(os.path.join(d, "c-black.ttf"), family="Variant", style="Black", bold=True)
        self.assertEqual(fonts.resolve("variant", dirs=[d]).style, "Regular")
        self.assertEqual(fonts.resolve("variant", bold=True, dirs=[d]).style, "Black")      # (only bold one there is)

    def test_a_file_and_a_comma_list(self):
        self.assertEqual(fonts.resolve(OTHER, dirs=[FONTS]).family, "Otherface")
        self.assertEqual(fonts.resolve("nonesuch, otherface", dirs=[FONTS]).family, "Otherface")

    def test_a_generic_always_gets_some_font(self):
        for name in ("sans", "serif", "mono", "impact", "script"):
            self.assertIn(fonts.resolve(name, dirs=[FONTS]).family, ("Testface", "Otherface"), name)

    def test_unknown_name_lists_what_there_is(self):
        with self.assertRaises(fonts.FontNotFound) as cm:
            fonts.resolve("nonesuch", dirs=[FONTS])
        self.assertIn("Testface", str(cm.exception))

    def test_not_a_font_file(self):
        junk = os.path.join(TMP, "junk2.ttf")
        with open(junk, "wb") as f:
            f.write(b"x" * 64)
        with self.assertRaises(fonts.FontNotFound):
            fonts.resolve(junk, dirs=[FONTS])

    def test_cache_is_kept_and_reused(self):
        old = os.environ.get("BIDET_CACHE")
        os.environ["BIDET_CACHE"] = os.path.join(TMP, "cache")
        try:
            fonts._cache.clear()
            self.assertEqual(fonts.cache_path(), os.path.join(TMP, "cache", "fonts.json"))
            fonts.catalog(dirs=[FONTS])
            self.assertFalse(os.path.exists(fonts.cache_path()))                 # explicit dirs bypass the cache
            fonts._cache.clear()
            first = fonts.catalog(dirs=[FONTS], use_cache=True)
            self.assertEqual(len(first), 3)
            stored = fonts._load_cache(fonts.cache_path())
            self.assertEqual(sorted(os.path.basename(p) for p in stored["fonts"]),
                             ["other-italic.ttf", "test-bold.ttf", "test-regular.ttf"])
            fonts._cache.clear()
            self.assertEqual(len(fonts.catalog(dirs=[FONTS], use_cache=True)), 3)    # from the file this time
        finally:
            if old is None:
                os.environ.pop("BIDET_CACHE", None)
            else:
                os.environ["BIDET_CACHE"] = old


class Layout(unittest.TestCase):
    def setUp(self):
        self.tt = ttfglyphs.TrueType(PLAIN)

    def test_pen_positions_follow_the_advances(self):
        placed, pitch, widths = bifin_lettering.layout("AB", self.tt, 1000)
        self.assertEqual([round(x) for _c, _g, x, _l in placed], [0, 600])
        self.assertEqual(widths, [1300.0])
        self.assertEqual(pitch, 1100.0)                                           # ascent + descent + line gap

    def test_size_scales_everything(self):
        _p, pitch, widths = bifin_lettering.layout("AB", self.tt, 100)
        self.assertAlmostEqual(widths[0], 130.0)
        self.assertAlmostEqual(pitch, 110.0)

    def test_kerning_pulls_a_pair_together(self):
        _p, _pitch, w = bifin_lettering.layout("AV", self.tt, 1000)
        self.assertEqual(w, [1200.0 - 200.0])                                     # 600 + 600 - 200
        _p, _pitch, w = bifin_lettering.layout("VA", self.tt, 1000)
        self.assertEqual(w, [1200.0])                                             # only the pair AV is in the table

    def test_spacing_goes_between_letters_only(self):
        _p, _pitch, w = bifin_lettering.layout("AB", self.tt, 1000, spacing=0.1)
        self.assertAlmostEqual(w[0], 1300 + 100)

    def test_lines_and_alignment(self):
        placed, _pitch, widths = bifin_lettering.layout("BBB\nA", self.tt, 1000, align="center")
        self.assertEqual(widths, [2100.0, 600.0])
        xs = [x for _c, _g, x, l in placed if l == 1]
        self.assertAlmostEqual(xs[0], (2100 - 600) / 2.0)
        placed, _pitch, _w = bifin_lettering.layout("BBB\nA", self.tt, 1000, align="right")
        self.assertAlmostEqual([x for _c, _g, x, l in placed if l == 1][0], 1500.0)

    def test_wrapping_breaks_at_spaces(self):
        placed, _pitch, widths = bifin_lettering.layout("AA AA AA", self.tt, 1000, wrap=3000)
        self.assertEqual(len(widths), 2)                                          # "AA AA" is 2700 wide, "AA AA AA" 4200
        self.assertTrue(all(w <= 3000 for w in widths))
        _p, _pitch, widths = bifin_lettering.layout("AAAAAAAA", self.tt, 1000, wrap=2500)
        self.assertEqual(len(widths), 1)                                          # no space: a long word stays whole

    def test_line_height_is_in_ems(self):
        _p, pitch, _w = bifin_lettering.layout("A\nA", self.tt, 200, line_height=2.0)
        self.assertEqual(pitch, 400.0)


class Lettering(unittest.TestCase):
    def make(self, text="AB", **kw):
        kw.setdefault("font", PLAIN)
        return bifin_lettering.lettering(text, **kw)

    def test_a_valid_vector_picture(self):
        pic = self.make("AB AV")
        back = bif.loads(bif.dumps(pic))
        L = letters(back)
        self.assertEqual(L.kind, "vector")
        self.assertEqual(len(L.paths()), 5)                                       # A, B (+ its hole), A, V: a space has no outline
        self.assertEqual(back.meta["mode"], "lettering")
        self.assertEqual(back.meta["source"]["font"]["family"], "Testface")
        self.assertEqual(back.meta["source"]["characters"], 5)                    # the space counts as a character

    def test_the_hole_of_a_b_is_a_hole(self):
        pic = self.make("B", margin=0.0)
        a = bifrender.render(pic, scale=10, ss=2).alpha                           # the ink coverage, 0..1
        h, w = a.shape
        self.assertLess(a[h // 2, w // 2], 0.1)                                   # the middle of the hole is paper
        self.assertGreater(a[h // 2, 10], 0.9)                                    # the stem beside it is ink

    def test_size_and_margin_set_the_canvas(self):
        pic = self.make("A", size=100, margin=0.0)                                # a 500 x 500 unit square at 1000 upm
        self.assertAlmostEqual(pic.width, 50.0, 1)
        self.assertAlmostEqual(pic.height, 50.0, 1)
        pic = self.make("A", size=100, margin=0.2)
        self.assertAlmostEqual(pic.width, 50.0 + 40.0, 1)
        pic = self.make("A", size=200, margin=0.0)
        self.assertAlmostEqual(pic.width, 100.0, 1)

    def test_baseline_and_line_pitch(self):
        one = self.make("A", size=1000, margin=0.0)
        two = self.make("A\nA", size=1000, margin=0.0)
        self.assertAlmostEqual(two.height - one.height, 1100.0, 1)                # one line pitch taller

    def test_kerning_shows_in_the_width(self):
        # ink width: A is 500 wide, V (origin 600 - 200) is 500 wide -> 900; unkerned VA: 600 + 500 = 1100
        self.assertAlmostEqual(self.make("AV", size=1000, margin=0.0).width, 900.0, 0)
        self.assertAlmostEqual(self.make("VA", size=1000, margin=0.0).width, 1100.0, 0)

    def test_synthetic_italic_slants_the_top_to_the_right(self):
        flat = self.make("A", size=1000, margin=0.0)
        slanted = self.make("A", italic=True, size=1000, margin=0.0)             # PLAIN has no italic: faked
        self.assertEqual(slanted.meta["source"]["font"]["synthetic"], ["italic"])
        self.assertGreater(slanted.width, flat.width)                             # 500 * tan(12 deg) wider
        xy = letters(slanted).xy
        top, bottom = xy[xy[:, 1] < xy[:, 1].min() + 1], xy[xy[:, 1] > xy[:, 1].max() - 1]
        self.assertGreater(top[:, 0].mean(), bottom[:, 0].mean())

    def test_pen_makes_letters_bolder_by_adding_an_outline(self):
        import bifop
        pic = self.make("A", size=100, margin=0.3)
        stem = letters(pic).props["stem"]
        self.assertGreater(stem, 0)
        bold = bifop.apply(self.make("A", size=100, margin=0.3), ["pen:3"], bifop.Notes())
        self.assertAlmostEqual(float(letters(bold).arrays["width"][0]), 2 * stem, 3)       # (3 - 1) stems of outline
        a0 = bifrender.render(pic, scale=4, ss=2).alpha.sum()
        a1 = bifrender.render(bold, scale=4, ss=2).alpha.sum()
        self.assertGreater(a1, a0 * 1.15)                                                  # visibly more ink
        notes = bifop.Notes()
        thin = bifop.apply(self.make("A", margin=0.3), ["pen:0.5"], notes)
        self.assertEqual(float(letters(thin).arrays["width"][0]), 0.0)                     # cannot be thinner than the font
        self.assertTrue(any("thinner" in line for line in notes.lines))

    def test_a_warp_scales_the_stem_with_the_strokes(self):
        import bifop
        pic = self.make("AB", size=100)
        out = bifop.apply(pic, ["arc:bend=0.3"], bifop.Notes())
        self.assertGreater(letters(out).props["stem"], 0)                         # kept (and scaled with the width)
        self.assertEqual(float(letters(out).props["width"]), 0.0)

    def test_colours_and_empty_text(self):
        pic = self.make("A", ink=(255, 0, 0), paper=(0, 0, 255))
        self.assertEqual([p["rgb"] for p in pic.palette], [[255, 0, 0], [0, 0, 255]])
        pic = self.make("   ")                                                    # nothing to draw is still a picture
        self.assertEqual(pic.layers, [])
        self.assertGreater(pic.width, 0)

    def test_control_characters_and_tabs(self):
        pic = self.make("A\tA\x07\r\n")                                           # the tab is four spaces, the bell nothing
        wide = self.make("A    A")
        self.assertEqual(len(letters(pic).paths()), 2)
        self.assertAlmostEqual(pic.width, wide.width, 3)

    def test_errors(self):
        with self.assertRaises(bif.BifError):
            self.make("A", size=0)
        with self.assertRaises(bif.BifError):
            self.make("A", align="middle")
        with self.assertRaises(bif.BifError):
            self.make("A", font=os.path.join(TMP, "nope.ttf"))

    def test_unmapped_characters_draw_the_notdef_box(self):
        self.assertEqual(len(letters(self.make("Z")).paths()), 2)                  # .notdef: a box with a hole


class CommandLine(unittest.TestCase):
    def run_bifin(self, args, data=b"AB\n"):
        p = subprocess.Popen([sys.executable, os.path.join(ROOT, "bifin.py")] + args, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate(data)
        return p.returncode, out, err.decode("utf-8", "replace")

    def test_lettering_through_the_tool(self):
        code, out, err = self.run_bifin(["-f", "lettering", "--font", PLAIN, "--size", "50", "--align", "center"])
        self.assertEqual(code, 0, err)
        pic = bif.loads(out)
        self.assertEqual(pic.meta["mode"], "lettering")
        self.assertEqual(pic.meta["generator"]["args"]["size"], 50.0)

    def test_the_tool_agrees_with_the_library(self):
        code, out, err = self.run_bifin(["-f", "lettering", "--font", PLAIN, "--spacing", "0.1", "--margin", "0.3"], b"AV AB\n")
        self.assertEqual(code, 0, err)
        mine = bifin.convert(b"AV AB\n", "lettering", name=None, lettering=dict(font=PLAIN, size=100.0, spacing=0.1, margin=0.3))
        self.assertEqual(out, bif.dumps(mine))

    def test_a_bad_font_is_a_message_not_a_traceback(self):
        code, out, err = self.run_bifin(["-f", "lettering", "--font", "no-such-font-anywhere"])
        self.assertNotEqual(code, 0)
        self.assertIn("no font", err)
        self.assertNotIn("Traceback", err)

    def test_list_fonts(self):
        code, out, err = self.run_bifin(["--list-fonts"], b"")
        self.assertEqual(code, 0, err)

    def test_art_is_untouched_by_the_lettering_options(self):
        art = b"  /\\\n /  \\\n/____\\\n"
        code, a, err = self.run_bifin([], art)
        self.assertEqual(code, 0, err)
        code, b, err = self.run_bifin(["--size", "300", "--align", "right"], art)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
