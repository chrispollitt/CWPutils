#!/usr/bin/env python3
"""Tests for bif.py and the reference test data.   python tests/test_bif.py   (or pytest)"""
from __future__ import print_function

import glob
import io
import json
import os
import random
import struct
import sys
import time
import unittest
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import bif                                          # noqa: E402

DATA = os.path.join(os.path.dirname(HERE), "testdata")
GOOD = sorted(glob.glob(os.path.join(DATA, "good", "*.bif")))
with io.open(os.path.join(DATA, "bad", "manifest.json"), encoding="utf-8") as _f:
    BAD = json.load(_f)


def slurp(path):
    with open(path, "rb") as f:
        return f.read()


def jsonable(o):
    return json.loads(json.dumps(o, sort_keys=True))


class Dribble(object):
    """a pipe: never more than a few bytes per read"""
    def __init__(self, data, n=7):
        self.b, self.n = io.BytesIO(data), n

    def read(self, k=-1):
        return self.b.read(min(k, self.n) if k >= 0 else self.n)


class GoodFiles(unittest.TestCase):
    def test_there_are_some(self):
        self.assertGreaterEqual(len(GOOD), 10)

    def test_contents_match_summary(self):
        for path in GOOD:
            with io.open(path[:-4] + ".json", encoding="utf-8") as f:
                want = json.load(f)
            pic = bif.load(path)
            self.assertEqual(jsonable(bif.summary(pic)), want, os.path.basename(path))
            self.assertEqual(bif.check(pic)[0], [])

    def test_round_trip(self):
        for path in GOOD:
            pic = bif.load(path)
            want = jsonable(bif.summary(pic))
            for compress in (True, False, 1):
                again = bif.loads(bif.dumps(pic, compress=compress))
                self.assertEqual(jsonable(bif.summary(again)), want, (path, compress))
                self.assertEqual(again.extra, pic.extra)
                self.assertEqual(again.head_extra, pic.head_extra)
                self.assertEqual(again.canvas_extra, pic.canvas_extra)

    def test_writing_is_deterministic(self):
        for path in GOOD:
            pic = bif.load(path)
            self.assertEqual(bif.dumps(pic), bif.dumps(bif.loads(bif.dumps(pic))), path)

    def test_compression_is_used_and_is_optional(self):
        pic = bif.load(os.path.join(DATA, "good", "raster-rgb-float-alpha.bif"))
        small, big = len(bif.dumps(pic)), len(bif.dumps(pic, compress=False))
        self.assertLess(small, big)

    def test_pipe_sized_reads(self):
        for path in GOOD:
            data = slurp(path)
            a = bif.read(Dribble(data))
            b = bif.loads(data)
            self.assertEqual(jsonable(bif.summary(a)), jsonable(bif.summary(b)))

    def test_forward_compat(self):
        pic = bif.load(os.path.join(DATA, "good", "forward-compat.bif"))
        self.assertEqual([t for t, _ in pic.extra], ["xtra", "vndR"])
        self.assertEqual(pic.head_extra, {"x-future": {"a": 1}})
        self.assertEqual(pic.canvas_extra, {"dpi": 96})
        L = pic.frames[0].layers
        self.assertIn("hint", L[0].arrays)
        self.assertEqual(L[1].kind, "hologram")
        E, W = bif.check(pic)
        self.assertEqual(E, [])
        self.assertEqual(len(W), 3)

    def test_arrays_are_read_only_views_of_the_right_type(self):
        pic = bif.load(os.path.join(DATA, "good", "vector-full.bif"))
        L = pic.layers[0]
        self.assertEqual(L.xy.dtype, np.dtype("<f4"))
        self.assertEqual(L.xy.shape, (12, 2))
        self.assertFalse(L.xy.flags.writeable)
        self.assertEqual([len(p) for p in L.paths()], [4, 4, 3, 1])
        self.assertEqual(L.paths()[3].tolist(), [[80.0, 40.0]])

    def test_source_chunk(self):
        pic = bif.load(os.path.join(DATA, "good", "source-and-unicode.bif"))
        self.assertEqual(pic.source[0], "cow.txt")
        self.assertTrue(pic.source[1].startswith(b" ____\n< hi >"))
        self.assertIn(u"\U0001F42E", pic.meta["title"])

    def test_chunk_sequence_of_the_spec_example(self):
        ts = [t for t, _, _ in bif.iter_chunks(io.BytesIO(slurp(os.path.join(DATA, "good", "spec-example.bif"))))]
        self.assertEqual(ts, ["HEAD", "FRAM", "LAYR", "ARRY", "ARRY", "BEND"])

    def test_array_data_is_8_byte_aligned(self):
        for path in GOOD:
            for t, payload, _ in bif.iter_chunks(io.BytesIO(slurp(path))):
                if t == "ARRY":
                    hlen = struct.unpack_from("<I", payload)[0]
                    self.assertEqual((4 + hlen) % 8, 0, path)


class BadFiles(unittest.TestCase):
    def test_manifest_matches_files(self):
        files = set(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(DATA, "bad", "*.bif")))
        self.assertEqual(files, set(BAD))

    def test_every_bad_file_is_rejected_for_the_right_reason(self):
        for name, info in sorted(BAD.items()):
            data = slurp(os.path.join(DATA, "bad", name + ".bif"))
            try:
                bif.loads(data)
            except bif.BifError as e:
                self.assertRegex(str(e), info["error"])
            else:
                self.fail("%s was accepted (%s)" % (name, info["why"]))

    def test_truncated_files_can_be_used_on_request(self):
        for name, info in sorted(BAD.items()):
            data = slurp(os.path.join(DATA, "bad", name + ".bif"))
            if info["usable_if_truncated_accepted"]:
                pic = bif.loads(data, allow_truncated=True)
                self.assertTrue(pic.truncated, name)
                self.assertEqual(len(pic.frames), 1)
            else:
                with self.assertRaises(bif.BifError, msg=name):
                    bif.loads(data, allow_truncated=True)

    def test_a_dribbling_pipe_gives_the_same_errors(self):
        for name in sorted(BAD):
            data = slurp(os.path.join(DATA, "bad", name + ".bif"))
            with self.assertRaises(bif.BifError, msg=name):
                bif.read(Dribble(data, 5))

    def test_a_lying_length_does_not_allocate(self):
        data = bif.MAGIC + struct.pack("<I", 0xFFFFFFF0) + b"ARRY" + b"x" * 10
        t = time.time()
        with self.assertRaises(bif.BifError):
            bif.loads(data)
        self.assertLess(time.time() - t, 1.0)

    def test_limits_can_be_lowered(self):
        pic = bif.load(os.path.join(DATA, "good", "raster-rgb-float-alpha.bif"))
        with self.assertRaises(bif.BifError):
            bif.loads(bif.dumps(pic), max_array=1000)


class Fuzz(unittest.TestCase):
    """Whatever is done to a file, the reader may only succeed or raise BifError."""

    @staticmethod
    def chunks(data):
        return [(t, p) for t, p, _ in bif.iter_chunks(io.BytesIO(data))]

    @staticmethod
    def rebuild(chs):
        return bif.MAGIC + b"".join(bif.chunk(t, p) for t, p in chs)

    def attempt(self, data, what):
        try:
            bif.loads(data)
        except bif.BifError:
            pass
        except Exception as e:                      # any other exception is a bug in the reader
            self.fail("%s: %s: %s" % (what, type(e).__name__, e))

    def test_every_truncation(self):
        for path in GOOD:
            data = slurp(path)
            if len(data) > 2500:
                continue
            for n in range(len(data)):
                self.attempt(data[:n], "%s cut at %d" % (os.path.basename(path), n))

    def test_byte_flips_with_valid_crcs(self):
        rnd = random.Random(1234)
        for path in GOOD:
            chs = self.chunks(slurp(path))
            for i in range(120):
                k = rnd.randrange(len(chs))
                t, p = chs[k]
                if not p:
                    continue
                q = bytearray(p)
                for _ in range(rnd.choice((1, 1, 2, 4))):
                    q[rnd.randrange(len(q))] = rnd.randrange(256)
                mut = list(chs)
                mut[k] = (t, bytes(q))
                self.attempt(self.rebuild(mut), "%s chunk %d (%s) mutated" % (os.path.basename(path), k, t))

    def test_chunk_shuffles_and_drops(self):
        rnd = random.Random(99)
        for path in GOOD:
            chs = self.chunks(slurp(path))
            for i in range(40):
                mut = list(chs)
                op = rnd.choice(("drop", "dup", "swap"))
                a, b = rnd.randrange(len(mut)), rnd.randrange(len(mut))
                if op == "drop":
                    del mut[a]
                elif op == "dup":
                    mut.insert(b, mut[a])
                else:
                    mut[a], mut[b] = mut[b], mut[a]
                self.attempt(self.rebuild(mut), "%s %s %d %d" % (os.path.basename(path), op, a, b))

    def test_random_bytes_after_magic(self):
        rnd = random.Random(5)
        for i in range(200):
            junk = bytes(bytearray(rnd.randrange(256) for _ in range(rnd.randrange(0, 200))))
            self.attempt(bif.MAGIC + junk, "junk %d" % i)


class Api(unittest.TestCase):
    def test_build_write_read(self):
        pic = bif.Picture(960, 400, palette=[{"rgb": [0, 0, 0], "role": "ink"}], meta={"title": "t"})
        pic.add_frame().layers.append(bif.vector_layer([[(2, 2), (20, 20)], [(5, 5)]], width=2, id="a"))
        again = bif.loads(bif.dumps(pic))
        self.assertEqual(again.width, 960)
        self.assertEqual(again.meta, {"title": "t"})
        self.assertEqual(len(again.layers[0].paths()), 2)

    def test_numpy_scalars_in_props(self):
        pic = bif.Picture(np.float32(10), np.int64(10), meta={"n": np.int32(3), "a": np.arange(3)})
        pic.add_frame()
        again = bif.loads(bif.dumps(pic))
        self.assertEqual(again.meta, {"n": 3, "a": [0, 1, 2]})

    def test_big_endian_arrays_are_written_little_endian(self):
        pic = bif.Picture(4, 4, palette=[{"rgb": [0, 0, 0]}])
        pic.add_frame().layers.append(bif.height_layer(np.arange(6, dtype=">f4").reshape(2, 3)))
        pic.layers[0].arrays["z"] = np.arange(6, dtype=">f4").reshape(2, 3)
        again = bif.loads(bif.dumps(pic))
        self.assertEqual(again.layers[0].z.tolist(), [[0, 1, 2], [3, 4, 5]])

    def test_the_writer_refuses_invalid_pictures(self):
        pic = bif.Picture(10, 10, palette=[{"rgb": [0, 0, 0]}])
        pic.add_frame().layers.append(bif.vector_layer([[(0, 0), (float("nan"), 1)]]))
        with self.assertRaises(bif.BifError):
            bif.dumps(pic)
        pic.layers[0].arrays["xy"] = np.zeros((2, 2), "<f8")                 # a dtype the format lacks
        with self.assertRaises(bif.BifError):
            bif.dumps(pic)
        pic2 = bif.Picture(10, 10, meta={"x": float("inf")})
        pic2.add_frame()
        with self.assertRaises(bif.BifError):
            bif.dumps(pic2)

    def test_check_reports_without_raising(self):
        pic = bif.Picture(-1, 10)
        E, W = bif.check(pic)
        self.assertTrue(E)

    def test_rasters_alpha_dtypes(self):
        pic = bif.Picture(4, 4, palette=[{"rgb": [0, 0, 0]}])
        pic.add_frame().layers.append(bif.raster_layer(alpha=np.full((3, 3), 200, "|u1")))
        pic.add_frame().layers.append(bif.raster_layer(alpha=np.full((3, 3), 0.5, "<f4")))
        self.assertEqual(len(bif.loads(bif.dumps(pic)).frames), 2)

    def test_empty_arrays_survive(self):
        pic = bif.Picture(4, 4)
        pic.add_frame().layers.append(bif.vector_layer([]))
        again = bif.loads(bif.dumps(pic))
        self.assertEqual(again.layers[0].xy.shape, (0, 2))
        self.assertEqual(again.layers[0].start.tolist(), [0])

    def test_unknown_critical_and_ancillary_chunks_when_writing(self):
        with self.assertRaises(bif.BifError):
            bif.chunk("AB1D", b"")
        with self.assertRaises(bif.BifError):
            bif.chunk("ABC", b"")

    def test_group_adjacency_check(self):
        pic = bif.Picture(4, 4, palette=[{"rgb": [0, 0, 0]}])
        pic.add_frame().layers.append(bif.vector_layer([[(0, 0)], [(1, 1)], [(2, 2)]], groups=[0, 0, 1]))
        self.assertEqual(bif.check(pic)[0], [])
        pic.layers[0].arrays["group"] = np.array([0, 1, 0], "<i4")
        self.assertTrue(bif.check(pic)[0])

    def test_vectors_for_old_numpy(self):
        # the same code must run on numpy 1.16: nothing here uses newer API
        a = bif.paths_to_csr([[(0, 0), (1, 1)], [], [(2, 2)]])
        self.assertEqual(a[1].tolist(), [0, 2, 2, 3])


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        o, e = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            rc = bif.main(list(args))
        finally:
            sys.stdout, sys.stderr = o, e
        return rc, out.getvalue(), err.getvalue()

    def test_info(self):
        rc, out, err = self.run_cli("info", os.path.join(DATA, "good", "vector-full.bif"))
        self.assertEqual((rc, err), (0, ""))
        self.assertIn("4 paths, 12 vertices", out)

    def test_info_json_is_the_summary(self):
        p = os.path.join(DATA, "good", "height.bif")
        rc, out, err = self.run_cli("info", "--json", p)
        self.assertEqual(json.loads(out), jsonable(bif.summary(bif.load(p))))

    def test_check_good_and_bad(self):
        rc, out, err = self.run_cli("check", os.path.join(DATA, "good", "minimal.bif"))
        self.assertEqual(rc, 0)
        rc, out, err = self.run_cli("check", os.path.join(DATA, "bad", "bad-crc.bif"), os.path.join(DATA, "good", "minimal.bif"))
        self.assertEqual(rc, 1)
        self.assertIn("CRC", err)
        self.assertIn("minimal.bif: ok", out)               # it carries on after a bad one

    def test_check_truncated_flag(self):
        p = os.path.join(DATA, "bad", "missing-bend.bif")
        self.assertEqual(self.run_cli("check", p)[0], 1)
        rc, out, err = self.run_cli("check", "-t", p)
        self.assertEqual(rc, 0)
        self.assertIn("truncated", out)

    def test_chunks(self):
        rc, out, err = self.run_cli("chunks", os.path.join(DATA, "good", "spec-example.bif"))
        self.assertEqual(rc, 0)
        self.assertEqual([l.split()[1] for l in out.splitlines()], ["HEAD", "FRAM", "LAYR", "ARRY", "ARRY", "BEND"])

    def test_missing_file(self):
        rc, out, err = self.run_cli("check", os.path.join(DATA, "nope.bif"))
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
