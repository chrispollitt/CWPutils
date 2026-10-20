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
        with bifdiag.stage("classify"):
            time.sleep(0.2)
        bifdiag.stop()
        text = err.getvalue()
        for c in "|/-\\":
            self.assertIn("\rbifin: classify " + c + "\x1b[K", text)
        self.assertTrue(text.endswith("\r\x1b[K"), repr(text[-10:]))

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
            self.assertTrue(err.getvalue().endswith("\r\x1b[K"))  # (and the line was rubbed out first)
        time.sleep(0.1)
        self.assertGreater(len(err.getvalue()), n)                # it turns again
        bifdiag.stop()

    def test_a_message_rubs_the_line_out_first(self):
        err = FakeTTY()
        bifdiag.start("bifout", err=err)
        time.sleep(0.1)
        bifdiag.say("hello")
        self.assertTrue(err.getvalue().endswith("\r\x1b[Kbifout: hello\n"), repr(err.getvalue()[-30:]))
        bifdiag.stop()

    def test_a_long_line_is_cut_to_the_terminal(self):
        err = FakeTTY()
        bifdiag.start("bifout", err=err)
        bifdiag._S.width = 40
        with bifdiag.stage("x" * 100):
            time.sleep(0.1)
        bifdiag.stop()
        lines = [l for l in err.getvalue().split("\r") if l.startswith("bifout")]
        self.assertTrue(lines)
        self.assertTrue(all(len(l.replace("\x1b[K", "")) <= 40 for l in lines), lines)


class Status(unittest.TestCase):
    """What the status line says (status_line() is what the thread draws, without the spinner)."""

    def setUp(self):
        bifdiag.start("bidet", spin=False, err=NotATTY())

    def tearDown(self):
        bifdiag.stop(report=False)

    def test_the_stages_open_now(self):
        self.assertEqual(bifdiag.status_line(), "bidet: working")
        with bifdiag.stage("bifout gif animation"):
            with bifdiag.stage("draw and write frames"):
                self.assertEqual(bifdiag.status_line(), "bidet: bifout gif animation: draw and write frames")

    def test_a_counted_loop_has_a_percent_and_then_the_time_left(self):
        with bifdiag.stage("draw"):
            bifdiag.progress("drawing frame", 1, 40)
            t0 = bifdiag._S.loop[4]
            self.assertEqual(bifdiag.status_line(now=t0), "bidet: draw: drawing frame 1 of 40, 2%")
            bifdiag.progress("drawing frame", 11, 40)
            bifdiag._S.loop[6] = t0 + 2.0                          # 10 frames in 2 s since the first: 29 to go = 5.8 s
            self.assertEqual(bifdiag.loop_text(now=t0 + 2.0), "drawing frame 11 of 40, 27%, 6 s left")
            self.assertEqual(bifdiag.loop_text(now=t0 + 4.0), "drawing frame 11 of 40, 27%, 4 s left")   # (counts down)
            self.assertEqual(bifdiag.loop_text(now=t0 + 9.0), "drawing frame 11 of 40, 27%, nearly done")
            bifdiag._S.loop[6] = t0 + 200.0
            self.assertEqual(bifdiag.loop_text(now=t0 + 200.0), "drawing frame 11 of 40, 27%, 9 min 40 s left")
            self.assertEqual(bifdiag.loop_text(now=t0 + 0.1), "drawing frame 11 of 40, 27%")    # (too soon to tell)
        self.assertEqual(bifdiag.loop_text(), "")                  # (the loop ends with its stage)

    def test_a_narrow_line_loses_the_middle_stages_first(self):
        bifdiag.plan(["bifin", "bifout"])
        bifdiag.step("bifout")
        with bifdiag.stage("bifout gif animation"), bifdiag.stage("mid"), bifdiag.stage("draw and write frames"):
            bifdiag.progress("drawing frame", 13, 100)
            self.assertEqual(bifdiag.status_line(room=200),
                             "bidet: [2/2] bifout gif animation: mid: draw and write frames: drawing frame 13 of 100, 13%")
            self.assertEqual(bifdiag.status_line(room=70), "bidet: [2/2] bifout gif animation: drawing frame 13 of 100, 13%")
            self.assertEqual(bifdiag.status_line(room=60), "bidet: [2/2] bifout: drawing frame 13 of 100, 13%")
            self.assertEqual(bifdiag.status_line(room=40), "bidet: [2/2] bifout: drawing frame 13...")

    def test_the_last_one_ends_the_loop(self):
        bifdiag.progress("reading screen", 1, 2)
        bifdiag.progress("reading screen", 2, 2)
        self.assertEqual(bifdiag.loop_text(), "")

    def test_the_steps_of_a_plan(self):
        bifdiag.plan(["bifin", "bifop crop", "bifop spin", "bifout"])
        bifdiag.step("bifin")
        with bifdiag.stage("bifin text"):
            with bifdiag.stage("classify"):
                self.assertEqual(bifdiag.status_line(), "bidet: [1/4] bifin text: classify")
        bifdiag.step("bifop spin")
        self.assertEqual(bifdiag.status_line(), "bidet: [3/4] bifop spin")
        bifdiag.step("bifout")
        bifdiag.step("bifout")                                     # (the same step again is not a new one)
        with bifdiag.stage("draw"):
            bifdiag.progress("drawing frame", 3, 10)
            self.assertEqual(bifdiag.status_line(), "bidet: [4/4] bifout: draw: drawing frame 3 of 10, 30%")

    def test_bidet_counts_its_pipeline(self):
        import bidet
        plan = bidet.make_plan(bidet.build_parser().parse_args(["Hi", "--spin", "-o", "x.gif"]), {})
        self.assertEqual(bidet.steps(plan), ["bifin", "bifop spin", "bifout"])


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

    def test_no_status_line_with_profile(self):
        err = FakeTTY()
        bifdiag.start("bidet", profile=True, err=err)              # (its thread would be in the statistics)
        self.assertIsNone(bifdiag._S.spin)
        bifdiag.stop()

    def test_bidet_threads(self):
        import bifop_3d
        os.environ["BIDET_THREADS"] = "1"
        try:
            self.assertEqual(bifop_3d._workers(), 1)
        finally:
            del os.environ["BIDET_THREADS"]
        self.assertGreaterEqual(bifop_3d._workers(), 1)

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


class RealTerminal(unittest.TestCase):
    """bidet on a pty, its standard error read by pyte (a terminal emulator), where both exist (Cygwin, Linux)."""

    def test_the_status_line_moves_and_is_gone_at_the_end(self):
        try:
            import pty
            import pyte
        except ImportError:
            self.skipTest("needs pty and pyte")
        master, slave = pty.openpty()
        out = os.path.join(tempfile.mkdtemp(), "s.gif")
        env = dict(os.environ, BIDET_NO_QUERY="1", COLUMNS="100")
        p = subprocess.Popen([sys.executable, os.path.join(ROOT, "bidet.py"), "Hi", "--spin", "--fps", "6", "-o", out],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=slave, env=env, cwd=ROOT)
        os.close(slave)
        data = b""
        while True:
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            data += chunk
        p.wait()
        os.close(master)
        self.assertEqual(p.returncode, 0, data[-500:])
        text = data.decode("utf-8", "replace")
        self.assertIn("bidet: [2/3] bifop spin", text)
        self.assertRegex(text, r"drawing (3D )?frame \d+ of \d+, \d+%")
        screen = pyte.Screen(100, 5)
        stream = pyte.Stream(screen)
        stream.feed(text.replace("\n", "\r\n"))
        self.assertEqual([l.rstrip() for l in screen.display], [""] * 5)      # (nothing left behind)


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
