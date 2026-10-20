#!/usr/bin/env python3
"""Tests for bifdiag.py: the spinning cursor, the frame counter, --debug and --profile in bidet, bifin, bifop and bifout.
python tests/test_diag.py"""
from __future__ import print_function

import io
import os
import subprocess
import sys
import tempfile
import time
import unittest

os.environ.setdefault("BIDET_NO_QUERY", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import bifdiag                                      # noqa: E402

ART = os.path.join(ROOT, "samples", "cow.txt")


class FakeTTY(io.StringIO):
    """Standard error as a terminal, written to a string (threads may write to it)."""

    def isatty(self):
        return True


class NotATTY(io.StringIO):
    def isatty(self):
        return False


def run(tool, *args, **kw):
    """(exit status, stdout bytes, stderr text) of a tool run as a program."""
    env = dict(os.environ, BIDET_NO_QUERY="1")
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, tool)] + list(args), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=ROOT)
    out, err = p.communicate(kw.get("stdin"))
    return p.returncode, out, err.decode("utf-8", "replace")


class Spinner(unittest.TestCase):
    def setUp(self):
        self.delay, self.step = bifdiag.SPIN_DELAY, bifdiag.SPIN_STEP
        bifdiag.SPIN_DELAY, bifdiag.SPIN_STEP = 0.01, 0.01

    def tearDown(self):
        bifdiag.stop(report=False)
        bifdiag.SPIN_DELAY, bifdiag.SPIN_STEP = self.delay, self.step

    def test_it_turns_on_a_terminal_and_is_rubbed_out_at_the_end(self):
        err = FakeTTY()
        bifdiag.start("bifin", err=err)
        time.sleep(0.2)
        bifdiag.stop()
        text = err.getvalue()
        for c in "|/-\\":
            self.assertIn(c + "\b", text)
        self.assertTrue(text.endswith(" \b"), repr(text[-10:]))

    def test_nothing_when_standard_error_is_not_a_terminal(self):
        err = NotATTY()
        bifdiag.start("bifin", err=err)
        time.sleep(0.1)
        bifdiag.progress("drawing frame", 1, 2)
        bifdiag.stop()
        self.assertEqual(err.getvalue(), "")

    def test_bidet_no_spin(self):
        err = FakeTTY()
        os.environ["BIDET_NO_SPIN"] = "1"
        try:
            bifdiag.start("bifin", err=err)
            time.sleep(0.1)
            bifdiag.stop()
        finally:
            del os.environ["BIDET_NO_SPIN"]
        self.assertEqual(err.getvalue(), "")

    def test_a_quick_run_shows_nothing(self):
        bifdiag.SPIN_DELAY = 5.0
        err = FakeTTY()
        bifdiag.start("bifin", err=err)
        bifdiag.stop()
        self.assertEqual(err.getvalue(), "")

    def test_quiet_stops_it_meanwhile(self):
        err = FakeTTY()
        bifdiag.start("bifout", err=err)
        time.sleep(0.1)
        with bifdiag.quiet():
            n = len(err.getvalue())
            time.sleep(0.1)
            self.assertEqual(len(err.getvalue()), n)              # (nothing written while quiet)
            self.assertTrue(err.getvalue().endswith(" \b"))      # (and the character was rubbed out first)
        time.sleep(0.1)
        self.assertGreater(len(err.getvalue()), n)                # it turns again
        bifdiag.stop()

    def test_progress_is_one_line_rewritten_and_a_message_starts_a_new_one(self):
        bifdiag.SPIN_DELAY = 5.0
        err = FakeTTY()
        bifdiag.start("bifout", err=err)
        bifdiag.progress("drawing frame", 1, 3)
        bifdiag.progress("drawing frame", 2, 3)
        bifdiag.say("hello")
        bifdiag.progress("drawing frame", 3, 3)
        bifdiag.stop()
        self.assertEqual(err.getvalue(), "\rbifout: drawing frame 1 of 3\rbifout: drawing frame 2 of 3\nbifout: hello\n"
                                         "\rbifout: drawing frame 3 of 3\n")


class Stages(unittest.TestCase):
    def tearDown(self):
        bifdiag.stop(report=False)

    def test_a_stage_does_nothing_before_start(self):
        with bifdiag.stage("x"):
            pass
        self.assertFalse(bifdiag.active())

    def test_debug_says_each_stage_with_its_time(self):
        err = NotATTY()
        bifdiag.start("bifop", debug=True, err=err)
        with bifdiag.stage("outer"):
            with bifdiag.stage("inner"):
                bifdiag.debug("in here")
        bifdiag.stop()
        lines = err.getvalue().splitlines()
        self.assertIn("Python", lines[0])
        self.assertIn("numpy", lines[0])
        self.assertTrue(any(l.endswith("> outer") for l in lines))
        self.assertTrue(any(l.endswith("  > inner") for l in lines))
        self.assertTrue(any("< inner (" in l for l in lines))
        self.assertIn("bifop: in here", lines)
        self.assertTrue(lines[-1].endswith("in all"))

    def test_no_debug_lines_without_debug(self):
        err = NotATTY()
        bifdiag.start("bifop", err=err)
        with bifdiag.stage("outer"):
            bifdiag.debug("in here")
        bifdiag.stop()
        self.assertEqual(err.getvalue(), "")

    def test_the_profile_adds_up_repeated_stages_under_their_parent(self):
        err = NotATTY()
        bifdiag.start("bidet", profile=True, err=err)
        with bifdiag.stage("bifout gif"):
            for _ in range(3):
                with bifdiag.stage("frame"):
                    sum(range(1000))
        with bifdiag.stage("write"):
            pass
        bifdiag.stop()
        text = err.getvalue()
        self.assertIn("bidet: profile", text)
        rows = [l.split() for l in text.splitlines() if l.strip().endswith(("bifout gif", "frame", "write"))]
        self.assertEqual([(r[1], r[-1]) for r in rows], [("1", "gif"), ("3", "frame"), ("1", "write")])
        self.assertIn("    frame", text)                                     # (indented under its parent)
        self.assertIn("cumtime", text)

    def test_the_statistics_are_saved_where_bidet_profile_says(self):
        path = os.path.join(tempfile.mkdtemp(), "x.prof")
        os.environ["BIDET_PROFILE"] = path
        try:
            bifdiag.start("bidet", profile=True, err=NotATTY())
            bifdiag.stop()
        finally:
            del os.environ["BIDET_PROFILE"]
        import pstats
        pstats.Stats(path)                                                   # (a real statistics file)


class CommandLines(unittest.TestCase):
    def test_bifin_debug(self):
        rc, out, err = run("bifin.py", "--debug", ART, "-o", os.path.join(tempfile.mkdtemp(), "c.bif"))
        self.assertEqual(rc, 0, err)
        for stage in ("> bifin text", "> parse", "> classify", "> write BIF"):
            self.assertIn(stage, err)

    def test_the_pipe_with_profile(self):
        rc, blob, err = run("bifin.py", "--profiling", ART)
        self.assertEqual(rc, 0, err)
        self.assertIn("bifin: profile", err)
        rc, blob, err = run("bifop.py", "--profile", "pen:2", stdin=blob)
        self.assertEqual(rc, 0, err)
        self.assertIn("bifop pen", err)
        rc, png, err = run("bifout.py", "--profile", "-o", "-", "-f", "png", stdin=blob)
        self.assertEqual(rc, 0, err)
        self.assertEqual(png[:4], b"\x89PNG")
        self.assertIn("bifout draw", err)
        self.assertIn("bifout write png", err)

    def test_debug_gives_a_traceback(self):
        rc, out, err = run("bifop.py", "--debug", "pen", stdin=b"not a bif")
        self.assertNotEqual(rc, 0)
        self.assertIn("Traceback", err)
        self.assertTrue(err.rstrip().endswith("bifop: not a BIF file (bad magic number)"), err)
        rc, out, err = run("bifop.py", "pen", stdin=b"not a bif")
        self.assertNotIn("Traceback", err)

    def test_bidet_profile_covers_every_stage(self):
        out = os.path.join(tempfile.mkdtemp(), "c.png")
        rc, _, err = run("bidet.py", "--profile", "--debug", "--art", ART, "-o", out)
        self.assertEqual(rc, 0, err)
        self.assertIn("bidet: pipeline: ", err)
        for stage in ("bifin text", "bifout draw", "bifout write png"):
            self.assertIn(stage, err.split("bidet: profile")[1])


if __name__ == "__main__":
    unittest.main()
