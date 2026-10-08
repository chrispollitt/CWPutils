#!/usr/bin/env python3
"""Tests for tonetrace.py.   python tests/test_tonetrace.py"""
from __future__ import print_function

import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import tonetrace as tt                              # noqa: E402


def disc(H, W, cy, cx, r):
    y, x = np.mgrid[0:H, 0:W]
    return r - np.hypot(x - cx, y - cy)


def smooth_noise(H, W, seed, passes=6):
    rs = np.random.RandomState(seed)
    f = rs.randn(H, W)
    for _ in range(passes):
        f = (f + np.roll(f, 1, 0) + np.roll(f, -1, 0) + np.roll(f, 1, 1) + np.roll(f, -1, 1)) / 5.0
    return f - f.mean()


class Contours(unittest.TestCase):
    def test_a_circle_is_one_closed_loop_on_the_circle(self):
        cs = tt.contours(disc(40, 40, 19.3, 20.6, 11.4))
        self.assertEqual(len(cs), 1)
        pts, closed = cs[0]
        self.assertTrue(closed)
        r = np.hypot(pts[:, 0] - 20.6, pts[:, 1] - 19.3)
        self.assertLess(float(np.abs(r - 11.4).max()), 0.05)             # linear interpolation of a distance field
        self.assertGreater(len(pts), 60)

    def test_two_circles_two_loops(self):
        F = np.maximum(disc(40, 80, 20, 20, 9), disc(40, 80, 20, 60, 7))
        cs = tt.contours(F)
        self.assertEqual(sorted(c for _, c in cs), [True, True])

    def test_a_ring_has_an_outer_and_an_inner_loop(self):
        F = -np.abs(disc(50, 50, 25, 25, 15)) + 3
        cs = tt.contours(F)
        self.assertEqual(len(cs), 2)
        radii = sorted(float(np.hypot(p[:, 0] - 25, p[:, 1] - 25).mean()) for p, _ in cs)
        self.assertAlmostEqual(radii[0], 12, delta=0.2)
        self.assertAlmostEqual(radii[1], 18, delta=0.2)

    def test_a_line_to_the_border_is_open_and_exact(self):
        H, W = 12, 30
        F = np.tile(np.arange(W, dtype=float) - 10.25, (H, 1))
        cs = tt.contours(F)
        self.assertEqual(len(cs), 1)
        pts, closed = cs[0]
        self.assertFalse(closed)
        self.assertEqual(len(pts), H)
        self.assertLess(float(np.abs(pts[:, 0] - 10.25).max()), 1e-12)
        self.assertEqual(sorted(pts[:, 1].tolist()), list(range(H)))

    def test_every_point_is_on_the_level(self):
        for seed in (1, 2, 3):
            F = smooth_noise(60, 90, seed)
            for level in (0.0, 0.05):
                for pts, closed in tt.contours(F, level):
                    v = tt.bilinear(F, pts[:, 0], pts[:, 1]) - level
                    self.assertLess(float(np.abs(v).max()), 1e-9)

    def test_loops_are_closed_open_ones_end_on_the_border_and_nothing_is_shared(self):
        F = smooth_noise(50, 70, 7)
        cs = tt.contours(F)
        self.assertGreater(len(cs), 3)
        for pts, closed in cs:
            if not closed:
                for end in (pts[0], pts[-1]):
                    on_border = end[0] in (0.0, 69.0) or end[1] in (0.0, 49.0) or \
                        abs(end[0] - round(end[0])) < 1e-12 or abs(end[1] - round(end[1])) < 1e-12
                    self.assertTrue(on_border)
                # an open contour's ends are on the array border
                self.assertTrue(min(pts[0][0], pts[0][1], 69 - pts[0][0], 49 - pts[0][1]) < 1e-9)
                self.assertTrue(min(pts[-1][0], pts[-1][1], 69 - pts[-1][0], 49 - pts[-1][1]) < 1e-9)
        # no point appears in two chains
        seen = set()
        for pts, _ in cs:
            for p in map(tuple, np.round(pts, 9)):
                self.assertNotIn(p, seen)
                seen.add(p)

    def test_saddle_is_resolved_by_the_centre(self):
        high = tt.contours(np.array([[2.0, -1.0], [-1.0, 2.0]]))          # centre above: the two high corners join
        self.assertEqual(len(high), 2)
        for p, _ in high:
            self.assertEqual(len(p), 2)
        got = sorted(tuple(sorted(map(tuple, np.round(p, 6).tolist()))) for p, _ in high)
        want = sorted([tuple(sorted([(round(2 / 3.0, 6), 0.0), (1.0, round(1 / 3.0, 6))])),     # round the high-b corner
                       tuple(sorted([(round(1 / 3.0, 6), 1.0), (0.0, round(2 / 3.0, 6))]))])    # round the high-d corner
        self.assertEqual(got, want)
        low = tt.contours(np.array([[1.0, -2.0], [-2.0, 1.0]]))           # centre below: the high corners are apart
        self.assertEqual(len(low), 2)
        # the high corner (0,0) is cut off by a segment near it, not one that passes between the two
        near = [p for p, _ in low if float(np.hypot(p[:, 0], p[:, 1]).max()) < 1.0]
        self.assertEqual(len(near), 1)

    def test_nothing_to_trace(self):
        self.assertEqual(tt.contours(np.ones((5, 5))), [])
        self.assertEqual(tt.contours(-np.ones((5, 5))), [])
        self.assertEqual(tt.contours(np.zeros((5, 5))), [])
        self.assertEqual(tt.contours(np.ones((1, 9))), [])
        self.assertEqual(tt.contours(np.ones((0, 0))), [])

    def test_a_field_touching_the_level_exactly(self):
        F = np.array([[0.0, 1.0, 0.0], [1.0, 1.0, 1.0], [0.0, 1.0, 0.0]])
        for pts, closed in tt.contours(F):
            self.assertTrue(np.isfinite(pts).all())
            self.assertLess(float(np.abs(tt.bilinear(F, pts[:, 0], pts[:, 1])).max()), 1e-9)

    def test_the_same_input_gives_the_same_lines(self):
        F = smooth_noise(40, 60, 11)
        a, b = tt.contours(F), tt.contours(F.copy())
        self.assertEqual(len(a), len(b))
        for (p, c), (q, d) in zip(a, b):
            self.assertEqual(c, d)
            self.assertTrue(np.array_equal(p, q))

    def test_it_is_fast_enough_for_a_big_picture(self):
        import time
        F = smooth_noise(400, 600, 5, passes=10)
        t = time.time()
        cs = tt.contours(F)
        self.assertLess(time.time() - t, 5.0)
        self.assertGreater(sum(len(p) for p, _ in cs), 1000)


class Helpers(unittest.TestCase):
    def test_bilinear(self):
        A = np.arange(12, dtype=float).reshape(3, 4)                      # A[i, j] = 4 i + j: linear in both
        x, y = np.array([0.0, 1.5, 3.0, 2.25]), np.array([0.0, 0.5, 2.0, 1.75])
        self.assertTrue(np.allclose(tt.bilinear(A, x, y), 4 * y + x))
        self.assertAlmostEqual(float(tt.bilinear(A, np.array([-5.0]), np.array([99.0]))[0]), 8.0)    # clamped to the corner

    def test_simplify(self):
        line = np.stack([np.linspace(0, 10, 50), np.linspace(0, 5, 50)], 1)
        self.assertEqual(len(tt.simplify(line, 0.01)), 2)
        corner = np.array([[0, 0], [5, 0.001], [10, 0], [10, 5], [10, 10]], float)
        s = tt.simplify(corner, 0.05)
        self.assertEqual(s.tolist(), [[0, 0], [10, 0], [10, 10]])
        rs = np.random.RandomState(0)
        wiggly = np.cumsum(rs.randn(300, 2), 0)
        for tol in (0.1, 0.5, 2.0):
            s = tt.simplify(wiggly, tol)
            self.assertLess(len(s), len(wiggly))
            self.assertTrue((s[0] == wiggly[0]).all() and (s[-1] == wiggly[-1]).all())
            # every original point is within tol of the simplified polyline
            worst = 0.0
            for p in wiggly:
                d = min(_seg_dist(p, s[i], s[i + 1]) for i in range(len(s) - 1))
                worst = max(worst, d)
            self.assertLessEqual(worst, tol + 1e-9)
        self.assertEqual(len(tt.simplify(np.array([[0.0, 0.0], [1.0, 1.0]]), 1.0)), 2)

    def test_runs(self):
        self.assertEqual(tt.runs([0, 1, 1, 0, 1, 0, 0, 1, 1, 1]), [(1, 3), (4, 5), (7, 10)])
        self.assertEqual(tt.runs([1, 1]), [(0, 2)])
        self.assertEqual(tt.runs([0, 0]), [])
        self.assertEqual(tt.runs([]), [])


def _seg_dist(p, a, b):
    d = b - a
    L2 = float(d.dot(d))
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, float((p - a).dot(d)) / L2))
    return float(np.hypot(*(p - (a + t * d))))


if __name__ == "__main__":
    unittest.main(verbosity=1)
