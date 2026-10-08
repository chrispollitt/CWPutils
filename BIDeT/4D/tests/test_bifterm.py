#!/usr/bin/env python3
"""Tests for bifterm.py and bifout's terminal handling (SIXEL support, `--background auto`).   python tests/test_bifterm.py"""
from __future__ import print_function

import os
import sys
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import bif                                          # noqa: E402
import bifin                                        # noqa: E402
import bifout                                       # noqa: E402
import bifterm                                      # noqa: E402

DA1_SIXEL = "\x1b[?64;1;2;4;6;9c"
DA1_PLAIN = "\x1b[?1;2c"
OSC_BG = "\x1b]11;rgb:1e1e/2020/2424\x1b\\"


def args(*argv):
    return bifout.build_parser().parse_args(list(argv))


class Parsers(unittest.TestCase):
    def test_da1(self):
        self.assertIs(bifterm.parse_da1(DA1_SIXEL), True)
        self.assertIs(bifterm.parse_da1(DA1_PLAIN), False)
        self.assertIs(bifterm.parse_da1("\x1b[?4c"), True)
        self.assertIs(bifterm.parse_da1("\x1b[?14c"), False)                    # attribute 14 is not 4
        self.assertIsNone(bifterm.parse_da1(""))
        self.assertIsNone(bifterm.parse_da1("junk"))

    def test_osc11(self):
        self.assertEqual(bifterm.parse_osc11(OSC_BG), (30, 32, 36))
        self.assertEqual(bifterm.parse_osc11("\x1b]11;rgb:ff/00/80\x07"), (255, 0, 128))     # two digits, BEL-terminated
        self.assertEqual(bifterm.parse_osc11("\x1b]11;rgb:f/0/8\x07"), (255, 0, 136))        # one digit
        self.assertEqual(bifterm.parse_osc11("\x1b]11;rgba:0000/0000/0000/ffff\x1b\\"), (0, 0, 0))
        self.assertEqual(bifterm.parse_osc11("\x1b]11;rgb:ffff/ffff/ffff\x1b\\"), (255, 255, 255))
        self.assertIsNone(bifterm.parse_osc11(DA1_SIXEL))
        self.assertIsNone(bifterm.parse_osc11("\x1b]11;nonsense\x07"))

    def test_cell_size(self):
        self.assertEqual(bifterm.parse_cell("\x1b[6;20;10t"), (10.0, 20.0))               # the reply says height;width
        self.assertIsNone(bifterm.parse_cell("\x1b[6;0;0t"))
        self.assertIsNone(bifterm.parse_cell(""))

    def test_a_whole_reply(self):
        r = bifterm.parse(OSC_BG + "\x1b[6;18;9t" + DA1_SIXEL)
        self.assertEqual((r.sixel, r.bg, r.cell), (True, (30, 32, 36), (9.0, 18.0)))
        r = bifterm.parse(DA1_PLAIN)                                                      # Windows Terminal: no OSC 11
        self.assertEqual((r.sixel, r.bg, r.cell), (False, None, None))
        self.assertEqual(bifterm.parse(""), bifterm.NOTHING)

    def test_luminance_and_dark_guess(self):
        self.assertEqual(bifterm.luminance((0, 0, 0)), 0)
        self.assertAlmostEqual(bifterm.luminance((255, 255, 255)), 1.0)
        self.assertGreater(bifterm.luminance((0, 255, 0)), bifterm.luminance((255, 0, 0)))
        self.assertIs(bifterm.guess_dark({"COLORFGBG": "15;0"}), True)
        self.assertIs(bifterm.guess_dark({"COLORFGBG": "0;default;15"}), False)
        self.assertIsNone(bifterm.guess_dark({"COLORFGBG": "7"}))
        self.assertIsNone(bifterm.guess_dark({}))


class Asking(unittest.TestCase):
    def test_no_terminal_no_answers(self):
        self.assertEqual(bifterm.query(env={"BIDET_NO_QUERY": "1"}), bifterm.NOTHING)
        self.assertEqual(bifterm.query(env={"TERM": "yaft-256color"}).sixel, True if os.name == "posix" else None)

    @unittest.skipUnless(os.name == "posix", "needs select() on pipes")
    def test_the_exchange_stops_at_the_da1_reply(self):
        import time
        q_r, q_w = os.pipe()                        # what we ask
        a_r, a_w = os.pipe()                        # what the "terminal" answers

        def terminal():
            got = os.read(q_r, 256).decode("latin1")
            self.assertTrue(got.endswith(bifterm.DA1))                                # DA1 goes last: it marks the end
            self.assertIn(bifterm.OSC11, got)
            os.write(a_w, (OSC_BG + DA1_SIXEL).encode("latin1"))
        t = threading.Thread(target=terminal)
        t.start()
        t0 = time.time()
        text = bifterm.exchange(a_r, q_w, bifterm.OSC11 + bifterm.CELL + bifterm.DA1, timeout=5.0)
        t.join()
        self.assertLess(time.time() - t0, 2.0)                                       # it did not wait out the timeout
        self.assertEqual(bifterm.parse(text).bg, (30, 32, 36))
        self.assertIs(bifterm.parse(text).sixel, True)
        for fd in (q_r, q_w, a_r, a_w):
            os.close(fd)

    @unittest.skipUnless(os.name == "posix", "needs select() on pipes")
    def test_a_terminal_that_ignores_osc11_costs_no_wait(self):
        import time
        q_r, q_w = os.pipe()
        a_r, a_w = os.pipe()
        os.write(a_w, DA1_PLAIN.encode("latin1"))                                    # answers DA1 only
        t0 = time.time()
        text = bifterm.exchange(a_r, q_w, bifterm.OSC11 + bifterm.DA1, timeout=5.0)
        self.assertLess(time.time() - t0, 1.0)
        r = bifterm.parse(text)
        self.assertEqual((r.sixel, r.bg), (False, None))
        for fd in (q_r, q_w, a_r, a_w):
            os.close(fd)

    @unittest.skipUnless(os.name == "posix", "needs select() on pipes")
    def test_silence_ends_at_the_timeout(self):
        import time
        q_r, q_w = os.pipe()
        a_r, a_w = os.pipe()
        t0 = time.time()
        text = bifterm.exchange(a_r, q_w, bifterm.DA1, timeout=0.3)
        self.assertEqual(text, "")
        self.assertLess(time.time() - t0, 1.5)
        for fd in (q_r, q_w, a_r, a_w):
            os.close(fd)


class BifoutOptions(unittest.TestCase):
    def pic(self, dark_ink=True):
        pic = bifin.convert(b"/\\\n", name=None)                                      # a palette with an ink role: black on white
        if not dark_ink:
            for e in pic.palette:
                if e.get("role") == "ink":
                    e["rgb"] = [240, 240, 240]
        return pic

    def test_background_options_everywhere(self):
        self.assertTrue(bifout.render_options(args("-b", "transparent"))["transparent"])
        self.assertEqual(bifout.render_options(args("-b", "#102030"))["paper"], (16, 32, 48))
        o = bifout.render_options(args("-b", "auto"))
        self.assertEqual((o["paper"], o["transparent"]), (None, False))                  # auto is settled only on a terminal
        o = bifout.render_options(args())
        self.assertEqual((o["paper"], o["transparent"]), (None, False))

    def test_auto_takes_the_terminal_colour_and_keeps_the_ink_visible(self):
        a = args("-b", "auto", "-s")
        reply = bifterm.Reply(True, (30, 32, 36), None)
        o = bifout.terminal_options(self.pic(), a, bifout.render_options(a), reply)
        self.assertEqual((o["paper"], o["transparent"]), ((30, 32, 36), False))
        self.assertEqual(o["ink"], bifout.LIGHT_INK)                                      # black ink on a dark page: lightened
        o = bifout.terminal_options(self.pic(), a, bifout.render_options(a), bifterm.Reply(True, (250, 250, 245), None))
        self.assertIsNone(o["ink"])                                                       # black on light shows: untouched
        o = bifout.terminal_options(self.pic(False), a, bifout.render_options(a), bifterm.Reply(True, (250, 250, 245), None))
        self.assertEqual(o["ink"], bifout.DARK_INK)                                       # light ink on a light page: darkened

    def test_auto_without_an_osc11_reply_is_transparent(self):
        a = args("-b", "auto", "-s")
        reply = bifterm.Reply(True, None, None)
        o = bifout.terminal_options(self.pic(), a, bifout.render_options(a), reply, env={})
        self.assertTrue(o["transparent"])
        self.assertIsNone(o["paper"])
        self.assertEqual(o["ink"], bifout.LIGHT_INK)                                      # unknown: taken as a dark terminal ...
        o = bifout.terminal_options(self.pic(), a, bifout.render_options(a), reply, env={"COLORFGBG": "0;15"})
        self.assertIsNone(o["ink"])                                                       # ... unless COLORFGBG says light

    def test_a_chosen_ink_or_page_is_left_alone(self):
        a = args("-b", "auto", "-s", "--ink", "black")
        o = bifout.terminal_options(self.pic(), a, bifout.render_options(a), bifterm.Reply(True, (0, 0, 0), None))
        self.assertEqual(o["ink"], (0, 0, 0))
        a = args("--ink", "black", "-s")                                                  # no -b auto: nothing is changed
        o = bifout.render_options(a)
        self.assertEqual(bifout.terminal_options(self.pic(), a, o, bifterm.Reply(True, (0, 0, 0), None)), o)

    def test_sixel_support_is_checked(self):
        a = args("-s")
        o = bifout.render_options(a)
        with self.assertRaises(bif.BifError) as cm:
            bifout.terminal_options(self.pic(), a, o, bifterm.Reply(False, None, None), env={})
        self.assertIn("SIXEL", str(cm.exception))
        with self.assertRaises(bif.BifError) as cm:                                                 # silence is "no", as in v1
            bifout.terminal_options(self.pic(), a, o, bifterm.Reply(None, None, None), env={})
        self.assertIn("did not answer", str(cm.exception))
        bifout.terminal_options(self.pic(), a, o, bifterm.NOTHING, env={})                          # no terminal to ask: go on
        bifout.terminal_options(self.pic(), a, o, bifterm.Reply(True, None, None), env={})
        bifout.terminal_options(self.pic(), args("-s", "--force"), o, bifterm.Reply(False, None, None), env={})
        bifout.terminal_options(self.pic(), a, o, bifterm.Reply(False, None, None), env={"LSIX_FORCE_SIXEL_SUPPORT": "1"})

    def test_only_sixel_for_a_terminal_asks(self):
        self.assertTrue(bifout.to_terminal(args(), "sixel", True))
        self.assertTrue(bifout.to_terminal(args(), "sixel"))                              # SIXEL on stdout, even into a pipe
        self.assertFalse(bifout.to_terminal(args(), "sixel", False))                      # (callers that ask only on a tty)
        self.assertFalse(bifout.to_terminal(args(), "png", True))
        self.assertFalse(bifout.to_terminal(args("-o", "x.six"), "sixel", True))          # a file
        self.assertEqual(bifout.ask_terminal(args("--no-query"), "sixel", True), bifterm.NOTHING)
        self.assertEqual(bifout.ask_terminal(args(), "png", True), bifterm.NOTHING)


def run_on_a_terminal(reply, extra=(), piped=False):
    """Run `bifout -s` with a pty as its terminal; `reply` is what the fake terminal sends back to the queries.
    piped: standard output is a pipe (`bifout -s | cut`), the pty only the controlling terminal.
    Returns (exit status, what was written, what the program asked, standard error)."""
    import pty
    import select
    import subprocess
    import tempfile
    import time
    d = tempfile.mkdtemp()
    path = os.path.join(d, "x.bif")
    bif.save(bifin.convert(b"/\\\n", name=None), path)
    master, slave = pty.openpty()
    cmd = [sys.executable, os.path.join(ROOT, "bifout.py")] + list(extra) + ["-s"]

    def own_terminal():
        os.setsid()                                                                      # the pty becomes its controlling terminal
        import fcntl
        import termios
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
    stdin = open(path, "rb")                                                             # the picture comes from a file, not the terminal
    env = dict((k, v) for k, v in os.environ.items() if k != "BIDET_NO_QUERY")
    p = subprocess.Popen(cmd, stdin=stdin, stdout=subprocess.PIPE if piped else slave, stderr=subprocess.PIPE,
                         preexec_fn=own_terminal, close_fds=True, env=env)
    if not piped:
        os.close(slave)                                  # (when piped it stays open, or the master reads EOF before the program opens it)
    # the fake terminal: it answers each "what are you?" (DA1) the program asks, the first time with just the
    # DA1 part of `reply`, the second time (colour and size questions with a DA1 behind them) with the rest
    m = bifterm._DA1.search(reply)
    da1, rest = (m.group(0), reply[:m.start()] + reply[m.end():]) if m else ("", reply)
    out, answers, t0 = "", 0, time.time()
    while time.time() - t0 < 20:
        if select.select([master], [], [], 0.2)[0]:
            try:
                chunk = os.read(master, 4096).decode("latin1")
            except OSError:
                break
            if not chunk:
                break
            out += chunk
            while answers < out.count(bifterm.DA1) and da1:
                os.write(master, (da1 if answers == 0 else rest + da1).encode("latin1"))
                answers += 1
        elif p.poll() is not None:
            break
    asked = out.split("\x1bP")[0]                                                        # what it wrote before any picture
    if piped:
        out = p.stdout.read().decode("latin1")
    p.wait()
    err = p.stderr.read().decode("utf-8", "replace")
    stdin.close()
    os.close(master)
    if piped:
        os.close(slave)
    return p.returncode, out, asked, err


@unittest.skipUnless(os.name == "posix", "needs a pty")
class OnATerminal(unittest.TestCase):
    """The real thing, with a fake terminal: queries go to /dev/tty, the answers decide what is drawn."""

    def test_a_terminal_that_answers_everything(self):
        code, out, asked, err = run_on_a_terminal(OSC_BG + DA1_SIXEL, ["-b", "auto"])
        self.assertEqual(code, 0, err)
        self.assertIn(bifterm.OSC11, asked)                                              # it asked for the background ...
        self.assertIn("\x1bP0;0;0q", out)                                                # SIXEL, opaque
        self.assertIn(";2;12;13;14", out)                                               # ... and the page is that colour (30,32,36)

    def test_a_terminal_that_will_not_say_its_background_gets_a_transparent_page(self):
        code, out, asked, err = run_on_a_terminal(DA1_SIXEL, ["-b", "auto"])
        self.assertEqual(code, 0, err)
        self.assertNotIn(";2;12;13;14", out)
        self.assertIn("\x1bP0;1;0q", out)                                                # P2 = 1: unpainted pixels stay transparent

    def test_a_terminal_without_sixel_is_refused(self):
        code, out, asked, err = run_on_a_terminal(DA1_PLAIN)
        self.assertNotEqual(code, 0)
        self.assertIn("SIXEL", err)
        self.assertNotIn("\x1bP", out)
        code, out, asked, err = run_on_a_terminal(DA1_PLAIN, ["--force"])               # unless forced
        self.assertEqual(code, 0, err)
        self.assertIn("\x1bP0;0;0q", out)

    def test_a_terminal_without_sixel_is_not_asked_about_colours(self):
        code, out, asked, err = run_on_a_terminal(DA1_PLAIN, ["-b", "auto"])
        self.assertNotEqual(code, 0)
        self.assertIn(bifterm.DA1, asked)
        self.assertNotIn(bifterm.OSC11, asked)                                           # a console might print what it cannot read

    def test_it_asks_when_the_output_is_piped_too(self):
        # `bifout -s | cut -c-100` on conhost: the old bidet said "Sixel not supported" there; so does this
        code, out, asked, err = run_on_a_terminal(DA1_PLAIN, piped=True)
        self.assertNotEqual(code, 0)
        self.assertIn("SIXEL", err)
        self.assertEqual(out.count("\x1bP"), 0)
        code, out, asked, err = run_on_a_terminal(DA1_SIXEL, ["-b", "auto"], piped=True)
        self.assertEqual(code, 0, err)
        self.assertIn("\x1bP0;1;0q", out)                                                # no OSC 11 reply: transparent

    def test_a_silent_terminal_is_taken_for_one_without_sixel(self):
        code, out, asked, err = run_on_a_terminal("", piped=True)
        self.assertNotEqual(code, 0)
        self.assertIn("did not answer", err)

    def test_nothing_is_asked_with_no_query(self):
        code, out, asked, err = run_on_a_terminal("", ["--no-query", "-b", "auto"])
        self.assertEqual(code, 0, err)
        self.assertEqual(asked, "")


if __name__ == "__main__":
    unittest.main()
