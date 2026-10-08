#!/usr/bin/env python3
"""M3, the parity gate: bifin | bifout draws what unascii (the frozen v3 in tests/reference) draws.

    python tests/test_parity.py            the gate (a failure lists the worst cases)
    python tests/test_parity.py --report   the whole table: sample x option set -> differences

Two levels.  In process: for every sample and option set, unascii.render_grid_color against
bifin_text.import_grid + bifrender.render at scale 1 (size, coverage, colour, and the ink / paper the
importer chose).  Command line: the frozen unascii script against `bifin | bifout`, PNG and SIXEL.

What "the same" means: sizes equal; mean coverage difference below a tolerance (tight for tone and block,
which are the same raster, and for line art with `outlines=False`, which differs only by float32 vertices;
looser for vector letters, whose outlines are not FreeType's hinted pixels); colour within a few levels.
"""
from __future__ import print_function

import io
import os
import subprocess
import sys
import unittest

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(HERE, "reference"))
import bifin_text                                   # noqa: E402
import bifrender                                    # noqa: E402
import unascii_v3 as v3                             # noqa: E402

SAMPLES = os.path.join(ROOT, "samples")
NAMES = sorted(n for n in os.listdir(SAMPLES) if n.endswith((".txt", ".ans")))

# option sets that unascii and bifin share (the same Options fields)
OPTION_SETS = [
    ("default", {}),
    ("line", {"mode": "line"}),
    ("tone", {"mode": "tone"}),
    ("mix", {"mode": "mix"}),
    ("block", {"mode": "ansi-block"}),
    ("lineart", {"mode": "lineart"}),
    ("cell8", {"cell_w": 8}),
    ("cell24", {"cell_w": 24}),
    ("aspect1", {"aspect": 1.0}),
    ("weight2", {"weight": 2.0}),
    ("weight0.6", {"weight": 0.6}),
    ("bold-text", {"weight": 2.5, "text_bold": 0.6}),
    ("mono", {"color": "off"}),
    ("colour-on", {"color": "on"}),
    ("ink-paper", {"ink": (200, 30, 30), "paper": (250, 245, 230)}),
    ("no-crop", {"crop": False}),
    ("no-round", {"round_lines": False}),
    ("spline0", {"spline": 0.0}),
    ("join0", {"join": 0.0}),
    ("join2", {"join": 2.0}),
    ("no-shade", {"shade": ""}),
    ("hatch2", {"hatch": 2.0, "shade": "X#"}),
    ("smooth0", {"smooth": 0.0}),
    ("smooth1.5", {"smooth": 1.5}),
    ("detail", {"detail": 0.3, "scale": 0.8}),
    ("levels0", {"levels": 0}),
    ("invert", {"invert": True}),
    ("dark", {"dark": True}),
]


def tolerance(mode, outlines, coloured):
    """Allowed relative coverage difference for a result: sum |bifin - v3| / sum v3 coverage, that is, what
    fraction of the ink is different.  (A mean over the whole picture would let a big margin hide errors and
    would punish dense lettering, where outlines and FreeType's hinted pixels differ most.)

    The limits come from the measured spread of the whole matrix (run this file with --report), and each
    has a cause:
      block                  0       the same raster, bit for bit
      tone                   0.6%    coverage is stored as 8 bits (about 1/255 of the ink, measured: 0.2% median)
      line, raster letters   2%      only float32 vertices differ (Pillow 11: 1% at most; Pillow 7 truncates float
                                     coordinates, so more boundary pixels flip: worst measured 1.6%) ...
        ... and coloured     8%      ... plus the seams where a stroke changes colour: its pieces are painted one
                                     over the other (source-over), v3 merged coverage with max() (worst 5.9%)
      line, vector letters   20%     the font's outlines are not FreeType's hinted pixels; dense lettering (art that
                                     is mostly text, forced into line mode) differs most: worst measured 17%
    Sizes: equal, or within a pixel (v3 crops on a thresholded raster, bifin on the strokes' extent).
    """
    if mode == "block":
        return 0.0005
    if mode == "tone":
        return 0.006
    if outlines:
        return 0.20
    return 0.08 if coloured else 0.02


def read_sample(name):
    with io.open(os.path.join(SAMPLES, name), "rb") as f:
        return f.read()


def parse_with(mod, name, data):
    a = name.endswith(".ans")
    return mod.parse(mod.decode2(data)[0], 80 if a else 0, glyphs=a)


def best_alignment(a, b):
    """Two 2-D arrays whose sizes differ by at most one in each direction -> both cut to the common size at the
    placement (of either one inside the other) with the smallest difference."""
    H, W = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    best = None
    for ay in range(a.shape[0] - H + 1):
        for ax in range(a.shape[1] - W + 1):
            for by in range(b.shape[0] - H + 1):
                for bx in range(b.shape[1] - W + 1):
                    ca, cb = a[ay:ay + H, ax:ax + W], b[by:by + H, bx:bx + W]
                    s = float(np.abs(ca - cb).sum())
                    if best is None or s < best[0]:
                        best = (s, ca, cb)
    return best[1], best[2]


def compare(name, label, kw, outlines):
    """One row: (name, label, outlines, mode, size_ok, relative_diff, colour_diff, ink_paper_ok, note).

    v3 chooses how much to supersample its strokes from the size of the canvas *before* cropping; a BIF only knows
    the cropped size, so the two can differ by one (and the whole-pixel pen then rounds differently).  The
    gate draws with v3's factor, so it measures geometry, not that heuristic."""
    data = read_sample(name)
    o3 = v3.Options(**kw)
    seen = {}
    orig = v3.draw_strokes

    def spy(strokes, W, H, w, ss):
        seen["ss"] = ss
        return orig(strokes, W, H, w, ss)
    v3.draw_strokes = spy
    try:
        ink, rgb = v3.render_grid_color(parse_with(v3, name, data), o3)
    finally:
        v3.draw_strokes = orig
    o4 = bifin_text.Options(outlines=outlines, **kw)
    pic = bifin_text.import_grid(parse_with(bifin_text, name, data), o4)
    r = bifrender.render(pic, scale=1, ss=seen.get("ss"))
    mode = pic.meta["mode"]
    a_, i_ = r.alpha, ink
    shifted = False
    if a_.shape != i_.shape:
        if abs(a_.shape[0] - i_.shape[0]) <= 1 and abs(a_.shape[1] - i_.shape[1]) <= 1:
            # the crop follows the ink: v3 finds it on a raster (ink > 0.02), bifin from the strokes' extent, and a
            # vector letter's extent differs from FreeType's hinted one; either can land a pixel apart (Pillow 7
            # does it for raster letters too).  Compare at the best alignment.
            a_, i_ = best_alignment(a_, i_)
            shifted = True
        else:
            return (name, label, outlines, mode, False, None, None, None, "size %s vs %s" % (r.alpha.shape, ink.shape))
    d = float(np.abs(a_ - i_).sum() / max(float(i_.sum()), 1.0))
    cd = None
    if rgb is not None and not r.uniform and not shifted:
        both = (r.alpha > 0.5) & (ink > 0.5)
        if both.any():
            cd = float(np.abs(r.color_u8()[both].astype(int) - rgb[both].astype(int)).mean())
    elif (rgb is None) != r.uniform:
        # the same picture held two ways: v3 coloured it but every stroke came out the colour of the ink
        inked = rgb.reshape(-1, 3)[ink.reshape(-1) > 0.5] if rgb is not None else None
        if not (inked is not None and r.uniform and len(np.unique(inked, axis=0)) <= 1):
            return (name, label, outlines, mode, True, d, None, None,
                    "colour/mono disagree: v3 rgb %s, bifin uniform %s" % (rgb is not None, r.uniform))
    ip = (tuple(pic.palette[0]["rgb"]), tuple(pic.palette[1]["rgb"])) == (tuple(o3.ink), tuple(o3.paper))
    return (name, label, outlines, mode, True, d, cd, ip, "")


_rows = {}


def rows_for(outlines):
    if outlines not in _rows:
        rows = []
        for name in NAMES:
            for label, kw in OPTION_SETS:
                try:
                    rows.append(compare(name, label, dict(kw), outlines))
                except ValueError:                     # a case v3 itself rejects (its size limit) is not a parity failure
                    rows.append((name, label, outlines, "?", True, 0.0, None, True, ""))
        _rows[outlines] = rows
    return _rows[outlines]


def gate_failures(rows):
    bad = []
    for name, label, outlines, mode, size_ok, d, cd, ip, note in rows:
        why = None
        if not size_ok or note:
            why = note
        elif d > tolerance(mode, outlines, cd is not None):
            why = "%.2f%% of the ink differs (limit %.2f%%)" % (100 * d, 100 * tolerance(mode, outlines, cd is not None))
        elif cd is not None and cd > 3.0:
            why = "colour differs by %.2f levels" % cd
        elif not ip:
            why = "ink / paper chosen differently"
        if why:
            bad.append("%s [%s, %s letters, %s]: %s" % (name, label, "vector" if outlines else "raster", mode, why))
    return bad


class InProcess(unittest.TestCase):
    def test_option_matrix_with_raster_letters(self):
        """outlines=False is unascii's own letters: the strictest comparison."""
        bad = gate_failures(rows_for(False))
        self.assertEqual(bad, [], "\n" + "\n".join(bad[:25]))

    def test_option_matrix_with_vector_letters(self):
        bad = gate_failures(rows_for(True))
        self.assertEqual(bad, [], "\n" + "\n".join(bad[:25]))

    def test_the_matrix_is_what_it_says(self):
        self.assertGreaterEqual(len(rows_for(True)), len(NAMES) * len(OPTION_SETS) - 20)
        modes = {r[3] for r in rows_for(True)}
        self.assertTrue({"line", "tone", "block"} <= modes, modes)


def run(args, tool, data=None):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.Popen([sys.executable, os.path.join(*tool)] + list(args), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    out, err = p.communicate(data)
    return p.returncode, out, err


V3 = (HERE, "reference", "unascii_v3.py")
BIFIN = (ROOT, "bifin.py")
BIFOUT = (ROOT, "bifout.py")


class CommandLine(unittest.TestCase):
    """The frozen unascii script against `bifin | bifout`, end to end."""
    SETS = [[], ["-m", "line"], ["-m", "tone"], ["-w", "1.5", "-c", "16"], ["--mono"],
            ["--ink", "#a02020", "--paper", "#fff8e8"], ["--no-crop"], ["--transparent"]]
    FILES = ["cow.txt", "dragon_lolcat.ans", "tone80.txt", "blocks_color.ans", "figlet_big.txt"]

    @staticmethod
    def flat(img):
        """What the picture looks like: RGBA over white.  (The RGB stored under fully transparent pixels is
        arbitrary and differs between the two programs; comparing it would compare nothing.)"""
        return np.asarray(Image.alpha_composite(Image.new("RGBA", img.size, (255, 255, 255, 255)), img).convert("RGB"), np.float32)

    def test_png(self):
        bad = []
        for name in self.FILES:
            path = os.path.join(SAMPLES, name)
            for opts in self.SETS:
                rc, out, err = run(["-o", "-"] + opts + [path], V3)
                self.assertEqual(rc, 0, err)
                want = Image.open(io.BytesIO(out)).convert("RGBA")
                # --transparent is bifout's; everything else is bifin's
                rc, blob, err = run([o for o in opts if o != "--transparent"] + [path], BIFIN)
                self.assertEqual(rc, 0, err)
                rc, out, err = run(["-", "-o", "-"] + [o for o in opts if o == "--transparent"], BIFOUT, blob)
                self.assertEqual(rc, 0, err)
                got = Image.open(io.BytesIO(out)).convert("RGBA")
                label = "%s %s" % (name, " ".join(opts))
                if got.size != want.size:
                    near = abs(got.size[0] - want.size[0]) <= 1 and abs(got.size[1] - want.size[1]) <= 1
                    if near and (name in ("cow.txt", "dragon_lolcat.ans", "figlet_big.txt") or opts == ["-m", "line"]):
                        continue       # vector letters: the crop differs by a pixel (the in-process matrix compares these aligned)
                    bad.append("%s: size %s, v3 %s" % (label, got.size, want.size))
                    continue
                diff = float(np.abs(self.flat(want) - self.flat(got)).mean())
                adiff = float(np.abs(np.asarray(want, np.float32)[..., 3] - np.asarray(got, np.float32)[..., 3]).mean())
                tol = 3.0 if name in ("cow.txt", "figlet_big.txt", "dragon_lolcat.ans") else 0.5      # (vector letters)
                if name == "tone80.txt" and opts == ["-m", "line"]:
                    tol = 8.0          # a picture of characters forced into line mode: all lettering, 17% of the ink differs
                if diff >= tol or adiff >= tol:
                    bad.append("%s: mean pixel difference %.3f, alpha %.3f (limit %.1f)" % (label, diff, adiff, tol))
        self.assertEqual(bad, [], "\n" + "\n".join(bad))

    def test_sixel(self):
        sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "3D", "gfx-conv"))
        try:
            import sixeldec
        except ImportError:
            self.skipTest("../3D/gfx-conv/sixeldec.py not found")
        for name in ("cow.txt", "dragon_lolcat.ans", "blocks_color.ans"):
            path = os.path.join(SAMPLES, name)
            rc, six3, err = run(["-s", path], V3)
            self.assertEqual(rc, 0, err)
            rc, blob, err = run([path], BIFIN)
            rc, six4, err = run(["-", "-s"], BIFOUT, blob)
            self.assertEqual(rc, 0, err)
            w3, h3, p3 = sixeldec.decode_rgba(six3)
            w4, h4, p4 = sixeldec.decode_rgba(six4)
            self.assertEqual((w4, h4), (w3, h3), name)
            diff = np.abs(np.frombuffer(p3, np.uint8).astype(int) - np.frombuffer(p4, np.uint8).astype(int)).mean()
            self.assertLess(float(diff), 3.0, "%s: SIXEL pixels differ by %.2f" % (name, diff))


def report():
    rows = rows_for(False) + rows_for(True)
    print("%-24s %-10s %-8s %-6s %9s %8s  %s" % ("sample", "options", "letters", "mode", "ink diff", "colour", ""))
    for name, label, outlines, mode, size_ok, d, cd, ip, note in rows:
        print("%-24s %-10s %-8s %-6s %9s %8s  %s" % (name, label, "vector" if outlines else "raster", mode,
                                                    "%.2f%%" % (100 * d) if d is not None else "-",
                                                    "%.2f" % cd if cd is not None else "", note))
    for outlines in (False, True):
        for m in ("line", "mix", "tone", "block"):
            ds = sorted(r[5] for r in rows if r[2] == outlines and r[3] == m and r[5] is not None)
            if ds:
                print("%-7s letters, %-5s: %4d cases, ink diff median %.2f%%, 95th %.2f%%, worst %.2f%%"
                      % ("vector" if outlines else "raster", m, len(ds), 100 * ds[len(ds) // 2], 100 * ds[int(len(ds) * .95)], 100 * ds[-1]))
    bad = gate_failures(rows)
    print("\n%d cases, %d failures" % (len(rows), len(bad)))
    for b in bad:
        print("  " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    if "--report" in sys.argv:
        sys.exit(report())
    unittest.main(verbosity=1)
