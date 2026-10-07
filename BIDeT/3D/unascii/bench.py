#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Time unascii stage by stage.

    bench.py                     every file in samples/
    bench.py FILE_OR_DIR ...     those files (a directory: the art files in it)
    bench.py -p FILE             also cProfile the render of FILE and show the top functions

For each file: parse, render (what the mode picked), PNG, SIXEL.  Run it before and after a change
that is meant to be faster, and compare the pictures too (an A/B: keep a copy of the old unascii.py
and compare render_grid_color's ink arrays, as the speed-up work did).
"""
import argparse
import cProfile
import glob
import io
import os
import pstats
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import unascii as u

EXTS = (".txt", ".ans", ".asc", ".vt", ".nfo", ".diz")


def files_in(args):
    out = []
    for a in args or [os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")]:
        if os.path.isdir(a):
            out += sorted(f for f in glob.glob(os.path.join(a, "*")) if f.lower().endswith(EXTS))
        else:
            out.append(a)
    return out


def main():
    ap = argparse.ArgumentParser(description="Time unascii stage by stage.")
    ap.add_argument("paths", nargs="*")
    ap.add_argument("-p", "--profile", action="store_true", help="cProfile the render of each file")
    a = ap.parse_args()
    rows = []
    for f in files_in(a.paths):
        data = open(f, "rb").read()
        t0 = time.time()
        text, enc = u.decode2(data)
        grid = u.parse(text, 80 if f.lower().endswith(".ans") else 0, glyphs=enc == "cp437")
        t1 = time.time()
        o = u.Options()
        pr = cProfile.Profile() if a.profile else None
        if pr:
            pr.enable()
        ink, rgb = u.render_grid_color(grid, o)
        if pr:
            pr.disable()
        t2 = time.time()
        buf = io.BytesIO()
        u.to_image(ink, o.ink, o.paper, False, rgb).save(buf, "PNG")
        t3 = time.time()
        sx = u.sixel(ink, o.ink, o.paper, rgb=rgb)
        t4 = time.time()
        rows.append((os.path.basename(f), grid.rows, grid.cols, ink.shape[1], ink.shape[0],
                     t1 - t0, t2 - t1, t3 - t2, t4 - t3, len(sx) // 1024))
        if pr:
            print("== %s" % f)
            pstats.Stats(pr).sort_stats("tottime").print_stats(8)
    print("%-26s %9s %11s %7s %7s %7s %7s %8s" % ("file", "cells", "pixels", "parse", "render", "png", "sixel", "sixel KB"))
    for name, r, c, w, h, tp, tr, tg, ts, kb in rows:
        print("%-26s %4dx%-4d %5dx%-5d %6.2fs %6.2fs %6.2fs %6.2fs %8d" % (name, c, r, w, h, tp, tr, tg, ts, kb))
    print("%-26s %9s %11s %6.2fs %6.2fs %6.2fs %6.2fs" % ("total", "", "", *[sum(x[i] for x in rows) for i in (5, 6, 7, 8)]))


if __name__ == "__main__":
    main()
