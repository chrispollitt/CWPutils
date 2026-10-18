"""Test suite for termprobe (see ../termprobe).

The analysis is tested on synthetic reply text.  The end-to-end tests (POSIX only) run the real script on a
pseudo-terminal whose master side plays the terminal, so nothing depends on which terminal the tests run in.
"""

import fcntl
import importlib.machinery
import importlib.util
import os
import select
import struct
import sys
import termios
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import script_path

try:
    import pty
except ImportError:                                  # native Windows
    pty = None

_loader = importlib.machinery.SourceFileLoader("termprobe", script_path("termprobe"))
_spec = importlib.util.spec_from_loader("termprobe", _loader)
tp = importlib.util.module_from_spec(_spec)
_loader.exec_module(tp)

ESC = "\x1b"
CLEAN = {
    "fg": ESC + "]10;rgb:cccc/cccc/cccc" + ESC + "\\",
    "bg": ESC + "]11;rgb:1e1e/2020/2424" + ESC + "\\",
    "xtver": ESC + "P>|FakeTerm 1.0" + ESC + "\\",
    "da2": ESC + "[>0;10;1c",
    "size18": ESC + "[8;24;80t",
    "pix14": ESC + "[4;384;640t",
    "cell16": ESC + "[6;16;8t",
    "cpr": ESC + "[1;1R",
    "kitty": ESC + "[?0u",
    "modkeys": ESC + "[>4;0m",
    "mode1000": ESC + "[?1000;2$y",
    "mode1006": ESC + "[?1006;2$y",
    "mode2004": ESC + "[?2004;2$y",
    "mode2026": ESC + "[?2026;0$y",
    "mode9001": ESC + "[?9001;2$y",
    "da1": ESC + "[?62;4c",
}
SIZE = (24, 80, 0, 0)


def reply(**changes):
    parts = dict(CLEAN)
    parts.update(changes)
    return "".join(parts[q.key] for q in tp.QUERIES if q.key in parts)


def issues_for(text, size=SIZE):
    seen = dict((q.key, 0.01) for q in tp.QUERIES if q.pat.search(text))
    return tp.analyse(text, seen, size)[1]


class TestParsing(unittest.TestCase):
    def test_rgb_digits_per_channel(self):
        self.assertEqual(tp.parse_rgb("rgb:ff/00/80"), (255, 0, 128))
        self.assertEqual(tp.parse_rgb("rgb:f/0/8"), (255, 0, 136))
        self.assertEqual(tp.parse_rgb("rgb:ffff/ffff/ffff"), (255, 255, 255))
        self.assertEqual(tp.parse_rgb("rgba:0000/0000/0000/ffff"), (0, 0, 0))
        self.assertIsNone(tp.parse_rgb("nonsense"))

    def test_unwrap_win32_input_mode(self):
        rec = lambda vk, uc, kd: ESC + "[%d;0;%d;%d;0;1_" % (vk, uc, kd)
        text = rec(65, 97, 1) + rec(65, 97, 0) + rec(38, 0, 1) + rec(38, 0, 0)
        self.assertEqual(tp.unwrap(text), "a" + ESC + "[A")                   # key-ups vanish, an arrow becomes its CSI
        wrapped = "".join(rec(0, ord(c), 1) for c in ESC + "[<0;5;5M")        # a mouse report wrapped one record per byte
        self.assertEqual(tp.unwrap(wrapped), ESC + "[<0;5;5M")


class TestAnalyse(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(issues_for(reply()), [])

    def test_unsupported_queries_are_not_faults(self):
        text = reply()
        for q in ("xtver", "kitty", "modkeys"):
            text = text.replace(CLEAN[q], "")
        self.assertEqual(issues_for(text), [])

    def test_doubled_reply(self):
        self.assertTrue(any("answered 2 times" in i for i in issues_for(reply() + CLEAN["da1"])))

    def test_garbage_is_reported(self):
        got = issues_for(reply() + "M3m3M3m" + ESC + "[8;14;")
        self.assertTrue(any("no known reply" in i and "M3m3M3m" in i for i in got), got)

    def test_size_disagreeing_with_window(self):
        got = issues_for(reply(size18=ESC + "[8;50;200t"))
        self.assertTrue(any("CSI 18t says 200x50" in i for i in got), got)

    def test_conhost_canned_da1(self):
        got = issues_for(reply(da1=ESC + "[?1;0c"))
        self.assertTrue(any("canned" in i for i in got), got)

    def test_missing_da1(self):
        got = issues_for(reply().replace(CLEAN["da1"], ""))
        self.assertTrue(any("DA1 got no reply" in i for i in got), got)

    def test_win32_input_mode_on(self):
        got = issues_for(reply(mode9001=ESC + "[?9001;1$y"))
        self.assertTrue(any("win32-input-mode" in i for i in got), got)

    def test_osc_verdict(self):
        self.assertEqual(tp.osc_verdict({"bg": 0.0}, "x"), ("ANSWERED", 0))
        self.assertEqual(tp.osc_verdict({"da1": 0.0}, "x"), ("DROPPED", 1))
        self.assertEqual(tp.osc_verdict({}, ""), ("SILENT", 1))


@unittest.skipIf(pty is None or os.name != "posix", "needs a POSIX pty")
class TestEndToEnd(unittest.TestCase):
    """Run termprobe on a pty and play the terminal on the master side."""

    def run_probe(self, answer, args=(), after=None):
        """answer(queries_text) -> bytes to send back (or None for silence). Returns (exit code, output)."""
        pid, fd = pty.fork()
        if pid == 0:
            os.execv(sys.executable, [sys.executable, script_path("termprobe"), "--timeout", "1"] + list(args))
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        out, answered, deadline = b"", False, time.time() + 20
        while time.time() < deadline:
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                out += data
                if not answered and out.endswith(b"\x1b[c"):
                    answered = True
                    back = answer(out.decode("latin1"))
                    if back:
                        os.write(fd, back.encode("latin1"))
                if after and answered and b"INPUT TEST" in out:
                    after(fd)
                    after = None
        _, status = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(status), out.decode("latin1").replace("\r", "")

    def test_clean_terminal(self):
        code, out = self.run_probe(lambda q: reply())
        self.assertEqual(code, 0, out)
        self.assertIn("ANSWERED", out)
        self.assertIn("NEGOTIATION: CLEAN", out)
        self.assertIn("rgb(30, 32, 36)", out)

    def test_colour_query_dropped(self):
        code, out = self.run_probe(lambda q: reply(fg="", bg=""))
        self.assertEqual(code, 1, out)
        self.assertIn("OSC 11:      DROPPED", out)

    def test_silent_terminal(self):
        code, out = self.run_probe(lambda q: None)
        self.assertEqual(code, 1, out)
        self.assertIn("SILENT", out)

    def test_da1_before_the_colours_still_counts(self):
        # ConPTY answers DA1 at once; the colours come later.  The probe must not stop at DA1.
        def answer(q):
            return CLEAN["da1"] + reply(da1="")
        code, out = self.run_probe(answer)
        self.assertEqual(code, 0, out)

    def test_tvision_mode_clean_and_split(self):
        def keys(split):
            def send(fd):
                time.sleep(0.2)
                rec = lambda vk, uc, kd: ("\x1b[%d;0;%d;%d;0;1_" % (vk, uc, kd)).encode()
                first = True
                for c in b"abcdefghij":
                    r = rec(c - 32, c, 1)
                    if split and first:
                        first = False
                        os.write(fd, r[:1])
                        time.sleep(0.3)
                        os.write(fd, r[1:])
                    else:
                        os.write(fd, r)
                    os.write(fd, rec(c - 32, c, 0))
                for _ in range(3):
                    for b in b"\x1b[<0;5;5M\x1b[<0;5;5m":
                        os.write(fd, rec(0, b, 1))
                for vk in (38, 40, 37, 39):
                    os.write(fd, rec(vk, 0, 1) + rec(vk, 0, 0))
            return send

        code, out = self.run_probe(lambda q: reply(), ["--tvision"], keys(False))
        self.assertIn("INPUT:       CLEAN", out)
        self.assertIn("0 split across reads", out)
        code, out = self.run_probe(lambda q: reply(), ["--tvision"], keys(True))
        self.assertIn("INPUT:       PROBLEM", out)
        self.assertIn("1 split across reads", out)
        self.assertIn("ESCDELAY", out)

    def test_no_terminal(self):
        import subprocess
        p = subprocess.run([sys.executable, script_path("termprobe")], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, start_new_session=True)       # no controlling terminal
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("NO TTY", p.stderr)


if __name__ == "__main__":
    unittest.main()
