"""Test suite for wincygterm (see ../wincygterm).

The pure functions are tested directly.  The pty helper (the Cygwin half) is run for real on POSIX, with pipes in
place of the Windows front-end.  The front-end itself needs a Windows console and is not covered here; it was
checked by hand in Windows Terminal.
"""

import importlib.machinery
import importlib.util
import os
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import run, script_path

_loader = importlib.machinery.SourceFileLoader("wincygterm", script_path("wincygterm"))
_spec = importlib.util.spec_from_loader("wincygterm", _loader)
wct = importlib.util.module_from_spec(_spec)
_loader.exec_module(wct)

POSIX = os.name == "posix"


def frame(kind, payload):
    return struct.pack(">cH", kind, len(payload)) + payload


def start_helper(rows, cols, *cmd):
    return subprocess.Popen([sys.executable, script_path("wincygterm"), "--helper", str(rows), str(cols)] + list(cmd),
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)


def finish(proc, timeout=20):
    """Wait for the helper (killing it if it hangs); -> (exit status, all of its output)."""
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    try:
        out = proc.stdout.read()
        return proc.wait(), out.decode("latin1").replace("\r", "")
    finally:
        timer.cancel()
        for pipe in (proc.stdin, proc.stdout):
            try:
                pipe.close()
            except OSError:
                pass


class TestPureFunctions(unittest.TestCase):
    def test_cygwin_path(self):
        self.assertEqual(wct.cygwin_path("C:\\Users\\chris\\a b"), "/cygdrive/c/Users/chris/a b")
        self.assertEqual(wct.cygwin_path("D:\\x"), "/cygdrive/d/x")

    def test_find_root(self):
        wct.registry_roots, wct.COMMON_ROOTS = (lambda: []), ()                # not whatever this machine has
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(wct.find_root(os.path.join(d, "nope"), environ={}))
            os.makedirs(os.path.join(d, "bin"))
            open(os.path.join(d, "bin", "cygwin1.dll"), "w").close()
            self.assertEqual(wct.find_root(d, environ={}), d)
            self.assertEqual(wct.find_root(None, environ={"CYGWIN_ROOT": d}), d)

    def test_find_cygwin_python_takes_the_newest(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "bin"))
            for name in ("python3.8.exe", "python3.12.exe", "python3.9.exe", "python3.exe", "python3.12-config",
                         "python3.6m.exe"):
                open(os.path.join(d, "bin", name), "w").close()
            self.assertEqual(wct.find_cygwin_python(d), os.path.join(d, "bin", "python3.12.exe"))
            self.assertIsNone(wct.find_cygwin_python(os.path.join(d, "missing")))

    def test_child_environment(self):
        env = wct.child_environment("C:\\cyg", environ={"PATH": "P", "WT_SESSION": "x"})
        self.assertEqual(env["PATH"], os.path.join("C:\\cyg", "bin") + os.pathsep + "P")
        self.assertEqual(env["TERM"], "xterm-256color")
        self.assertEqual(env["COLORTERM"], "truecolor")                         # Windows Terminal does truecolor
        self.assertEqual(env["CHERE_INVOKING"], "1")                            # stay in the current directory
        self.assertEqual(env["WINCYGTERM"], wct.VERSION)                        # termprobe reports it
        env = wct.child_environment("C:\\cyg", term="vt100", login_dir=True,
                                    environ={"PATH": "P", "TERM": "other", "COLORTERM": "24bit"})
        self.assertEqual((env["TERM"], env["COLORTERM"]), ("vt100", "24bit"))   # given values win
        self.assertNotIn("CHERE_INVOKING", env)
        self.assertEqual(wct.child_environment("C:\\cyg", environ={"PATH": "", "TERM": "screen"})["TERM"], "screen")
        self.assertNotIn("COLORTERM", wct.child_environment("C:\\cyg", environ={"PATH": ""}))

    def test_profile_line(self):
        line = wct.profile_line("C:\\cyg")
        self.assertIn(sys.executable, line)
        self.assertIn('--root "C:\\cyg"', line)
        self.assertTrue(line.endswith("--login-dir"))


@unittest.skipUnless(POSIX, "the helper needs a POSIX pty")
class TestHelper(unittest.TestCase):
    def test_command_runs_on_a_pty_of_the_given_size(self):
        proc = start_helper(24, 80, "/bin/sh", "-c", "tty; stty size")
        status, out = finish(proc)
        self.assertEqual(status, 0, out)
        self.assertIn("/dev/", out)
        self.assertNotIn("not a tty", out)
        self.assertIn("24 80", out)

    def test_exit_status_is_passed_on(self):
        self.assertEqual(finish(start_helper(24, 80, "/bin/sh", "-c", "exit 7"))[0], 7)

    def test_unknown_command(self):
        status, out = finish(start_helper(24, 80, "/no/such/command"))
        self.assertEqual(status, 127)
        self.assertIn("cannot run", out)

    def test_data_goes_to_the_pty_and_resize_changes_its_size(self):
        proc = start_helper(24, 80, "/bin/sh", "-c", "read x; stty size; echo got-$x")
        proc.stdin.write(frame(b"R", struct.pack(">HH", 40, 100)))
        proc.stdin.write(frame(b"D", b"hello\n"))
        proc.stdin.flush()
        status, out = finish(proc)
        self.assertEqual(status, 0, out)
        self.assertIn("40 100", out)
        self.assertIn("got-hello", out)

    def test_large_and_split_frames(self):
        proc = start_helper(24, 80, "/bin/sh", "-c", "read x; echo len-${#x}")
        data = frame(b"D", b"a" * 3000 + b"\n")
        for i in range(0, len(data), 7):                                        # trickle it in, mid-frame cuts
            proc.stdin.write(data[i:i + 7])
            proc.stdin.flush()
        status, out = finish(proc)
        self.assertEqual(status, 0, out)
        self.assertIn("len-3000", out)

    def test_hangup_when_the_front_end_goes_away(self):
        proc = start_helper(24, 80, "/bin/sh", "-c", "sleep 30")
        proc.stdin.close()
        status, _ = finish(proc, timeout=15)
        self.assertEqual(status, 128 + signal.SIGHUP)

    def test_utf8_round_trip(self):
        proc = start_helper(24, 80, "/bin/sh", "-c", "read x; echo \"$x\"")
        proc.stdin.write(frame(b"D", "h\u00e9llo \u4e16\u754c\n".encode("utf-8")))
        proc.stdin.flush()
        out = finish(proc)[1]
        self.assertIn("h\u00e9llo \u4e16\u754c", out.encode("latin1").decode("utf-8", "replace"))


class TestCommandLine(unittest.TestCase):
    def test_version(self):
        p = run("wincygterm", ["--version"])
        self.assertEqual(p.returncode, 0)
        self.assertIn("wincygterm " + wct.VERSION, p.stdout)

    @unittest.skipUnless(POSIX, "on native Windows the front-end would start")
    def test_front_end_refuses_to_run_off_windows(self):
        p = run("wincygterm", [])
        self.assertEqual(p.returncode, 2)
        self.assertIn("native Windows Python", p.stderr)

    def test_help_lists_the_options(self):
        out = run("wincygterm", ["--help"]).stdout
        for opt in ("--root", "--python", "--term", "--login-dir", "--no-reset", "--debug", "--profile"):
            self.assertIn(opt, out)


if __name__ == "__main__":
    unittest.main()
