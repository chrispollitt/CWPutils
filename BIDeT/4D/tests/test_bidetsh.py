#!/usr/bin/env python3
"""Tests for ttyd/bidetsh.py, the imitation shell behind the web terminal: parsing, pipelines, what it refuses, and how it
starts outside programs (with stand-ins for figlet and friends, so nothing needs to be installed).   python tests/test_bidetsh.py"""
from __future__ import print_function

import io
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "ttyd"))
import bidetsh                                      # noqa: E402

# stand-ins: print the arguments they were given, one per line in [], then what came in on standard input
STANDIN = """#!/bin/sh
for a in "$@"; do printf '[%s]' "$a"; done
echo
if [ $# -eq 0 ] || [ "$1" = "-s" ]; then cat; fi
"""


class ShellCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bin = tempfile.mkdtemp()
        for name in ("figlet", "cowsay", "fortune"):
            path = os.path.join(cls.bin, name)
            with open(path, "w") as f:
                f.write(STANDIN)
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        cls.old_path = bidetsh.SAFE_PATH
        bidetsh.SAFE_PATH = cls.bin + os.pathsep + "/usr/bin:/bin"

    @classmethod
    def tearDownClass(cls):
        bidetsh.SAFE_PATH = cls.old_path
        shutil.rmtree(cls.bin, True)

    def setUp(self):
        self.out, self.err = io.StringIO(), io.StringIO()
        self.sh = bidetsh.Shell(self.out, self.err)
        self.sh._presets = ["arc", "gold", "matrix"]

    def run_(self, line):
        self.out.seek(0)
        self.out.truncate()
        self.err.seek(0)
        self.err.truncate()
        self.sh.run_line(line)
        return self.out.getvalue()


class TestParsing(ShellCase):
    def test_quotes_hide_operators(self):
        self.assertEqual(self.run_("echo 'a | b' \"c ; d\" e\\;f"), "a | b c ; d e;f\n")

    def test_variables_expand_when_the_command_runs(self):
        self.assertEqual(self.run_('x="a  b"; echo "[$x]" $?'), "[a  b] 0\n")
        self.assertEqual(self.run_("y=1; z=$y$y; echo $z ${y}x '$y' \"\\$y\" $NOPE."), "11 1x $y $y .\n")

    def test_status_variable(self):
        self.assertEqual(self.run_("false; echo $?"), "1\n")

    def test_comment_and_empty(self):
        self.assertEqual(self.run_("echo hi # not this"), "hi\n")
        self.assertEqual(self.run_("   "), "")

    def test_refused_syntax(self):
        for line, word in (("echo a > f", ">"), ("echo a < f", "<"), ("echo a &", "background"), ("echo `id`", "`"),
                           ("echo $(id)", "$("), ("(echo a)", "("), ("echo 'oops", "unterminated"),
                           ("| echo", "syntax"), ("echo a ||", "syntax"), ("; echo", "syntax")):
            self.assertEqual(self.run_(line), "", line)
            self.assertIn(word, self.err.getvalue(), line)
            self.assertEqual(self.sh.status, 2, line)

    def test_control_characters_are_ignored(self):
        self.assertEqual(self.run_("echo \x1b[31mred"), "")
        self.assertEqual(self.err.getvalue(), "")


class TestRunning(ShellCase):
    def test_connectors(self):
        self.assertEqual(self.run_("true && echo a || echo b"), "a\n")
        self.assertEqual(self.run_("false && echo a || echo b"), "b\n")
        self.assertEqual(self.run_("false; echo c"), "c\n")
        self.assertEqual(self.run_("echo a; echo b | rev"), "a\nb\n")

    def test_pipelines(self):
        self.assertEqual(self.run_("echo hello | rev"), "olleh\n")
        self.assertEqual(self.run_("seq 5 | sort -nr | head -n 2 | tac"), "4\n5\n")
        self.assertEqual(self.run_("echo a b c | tr a-c A-C | wc -w"), "3\n")
        self.assertEqual(self.run_("seq 3 | nl | grep 2"), "     2\t2\n")
        self.assertEqual(self.run_("echo b a b | tr ' ' '\\n' | sort | uniq -c | wc -l"), "2\n")
        self.assertEqual(self.sh.status, 0)

    def test_pipeline_status_is_the_last_commands(self):
        self.run_("false | true")
        self.assertEqual(self.sh.status, 0)
        self.run_("true | false")
        self.assertEqual(self.sh.status, 1)

    def test_unknown_and_refused_commands(self):
        self.run_("nosuch")
        self.assertIn("command not found", self.err.getvalue())
        self.assertEqual(self.sh.status, 127)
        self.run_("bash -c id")
        self.assertIn("not available", self.err.getvalue())
        self.run_("echo a | nosuch | cat")           # a failed stage feeds the next one nothing, as in bash
        self.assertEqual(self.out.getvalue(), "")
        self.run_("sudo ls")
        self.assertIn("sudoers", self.err.getvalue())

    def test_stdin_needed(self):
        self.run_("rev")
        self.assertIn("nothing piped", self.err.getvalue())

    def test_file_system_is_pretend(self):
        self.assertEqual(self.run_("pwd"), "/home/guest\n")
        self.assertIn("README", self.run_("ls"))
        self.assertIn("bidetsh", self.run_("cat README"))
        self.assertIn("Hello", self.run_("cat ~/hello.txt | wc -l && cd /etc && cat motd"))
        self.assertEqual(self.run_("cd /nope"), "")
        self.assertIn("No such file", self.err.getvalue())
        self.run_("cat /etc/passwd")
        self.assertIn("No such file", self.err.getvalue())
        self.assertEqual(self.run_("cd ../../..; pwd"), "/\n")

    def test_output_is_capped(self):
        self.assertLessEqual(len(self.run_("seq 1000 | rev | rev | rev | tr 0-9 xxxxxxxxxx")), bidetsh.MAX_OUT)

    def test_exit(self):
        with self.assertRaises(bidetsh.ExitShell):
            self.run_("echo bye; exit")

    def test_cal(self):
        self.assertIn("February 2026", self.run_("cal 2 2026"))
        self.run_("cal 13 2026")
        self.assertIn("bad month", self.err.getvalue())


class TestOutsidePrograms(ShellCase):
    def test_text_is_passed_after_double_dash(self):
        self.assertEqual(self.run_("figlet -f slant -- -x Hello"), "[-f][slant][--][-x Hello]\n")
        self.assertEqual(self.run_("figlet -cw 40 Hi there"), "[-c][-w][40][--][Hi there]\n")

    def test_piped_text_goes_to_standard_input(self):
        self.assertEqual(self.run_("echo hi | figlet"), "\nhi\n")        # no arguments, then the text

    def test_options_are_checked(self):
        for line in ("figlet -f ../../etc/passwd x", "figlet -d /etc x", "figlet -f /etc/passwd x", "figlet -w 9999 x",
                     "cowsay -f /tmp/evil x", "cowsay -e abc x","figlet --help", "cowsay -C x"):
            self.run_(line)
            self.assertEqual(self.sh.status, 2, line)
            self.assertEqual(self.out.getvalue(), "", line)

    def test_categories_are_names_only(self):
        self.assertEqual(self.run_("fortune -s art"), "[-s][art]\n")
        self.run_("fortune /etc/passwd")
        self.assertEqual(self.sh.status, 2)

    def test_length_limits(self):
        self.run_("figlet " + "x" * (bidetsh.MAX_TEXT + 1))
        self.assertIn("too long", self.err.getvalue())

    def test_environment_and_directory_are_fixed(self):
        seen = {}

        def fake_run(argv, **kw):
            seen.update(kw, argv=argv)
            return mock.Mock(stdout=b"", stderr=b"", returncode=0)
        with mock.patch.object(bidetsh.subprocess, "run", fake_run):
            self.run_("figlet Hi")
        self.assertEqual(set(seen["env"]), {"PATH", "LANG", "TERM", "COLUMNS"})
        self.assertEqual(seen["cwd"], self.sh.scratch)
        self.assertTrue(seen["timeout"])
        self.assertIsInstance(seen["argv"], list)

    def test_a_missing_tool_is_not_a_command(self):
        with mock.patch.object(bidetsh, "SAFE_PATH", self.bin):          # the stand-ins only: no toilet here
            self.run_("toilet x")
            self.assertIn("not installed", self.err.getvalue())
            self.assertNotIn("toilet", self.sh.commands())
            self.assertIn("figlet", self.sh.commands())
            self.assertIn("bidet", self.sh.commands())


class TestBidet(ShellCase):
    def draw(self, line, window=(30, 100, 0, 0)):
        calls = []

        def fake_run(argv, **kw):
            calls.append(argv)
            return mock.Mock(returncode=0)
        with mock.patch.object(bidetsh.subprocess, "run", fake_run), mock.patch.object(bidetsh, "window_size", lambda: window):
            self.run_(line)
        return calls

    def test_text_is_forced_and_after_double_dash(self):
        argv = self.draw("bidet -P arc,gold --3d -w 600 --sway=20 --scroll=up Hello there")[0]
        self.assertEqual(argv[2:], ["-t", "-P", "arc", "-P", "gold", "--3d", "--sway=20", "--scroll=up",
                                    "--bifout=--width 600 --height 459", "--", "Hello there"])

    def test_picture_is_kept_shorter_than_the_window(self):
        # 100 columns of 8 px, 30 rows: all but the last 3 rows (17 px each) are for the picture
        self.assertEqual(self.draw("bidet Hi")[0][-3], "--bifout=--width 800 --height 459")
        # a window that reports pixels: 95% of the width, rows as tall as they are
        self.assertEqual(self.draw("bidet Hi", (40, 200, 1800, 880))[0][-3], "--bifout=--width 1710 --height 814")
        # a tiny window still gets a picture, and a wide one is capped as bidet does
        self.assertEqual(self.draw("bidet Hi", (4, 300, 0, 0))[0][-3], "--bifout=--width 2400 --height 100")
        self.assertEqual(self.draw("bidet Hi", (0, 0, 0, 0))[0][-3], "--bifout=--width 640 --height 357")

    def test_text_from_a_pipe(self):
        self.assertEqual(self.draw("echo Hi | bidet")[0][-2:], ["--", "Hi"])

    def test_on_a_terminal_it_waits_for_enter_and_clears(self):
        asked = []
        self.sh.interactive = True
        with mock.patch("builtins.input", lambda prompt="": asked.append(prompt) or ""):
            self.draw("echo Hi | bidet")
        self.assertEqual(len(asked), 1)
        self.assertIn("Enter", asked[0])
        self.assertTrue(self.out.getvalue().endswith("\033[H\033[2J\033[3J"))
        with mock.patch("builtins.input", mock.Mock(side_effect=EOFError)):        # Ctrl-D at the pause still clears
            self.draw("echo Hi | bidet")
        self.assertTrue(self.out.getvalue().endswith("\033[H\033[2J\033[3J"))

    def test_without_a_terminal_it_does_not_wait(self):
        with mock.patch("builtins.input", mock.Mock(side_effect=AssertionError("asked"))):
            self.draw("echo Hi | bidet")
        self.assertNotIn("\033[2J", self.out.getvalue())

    def test_must_be_last(self):
        self.assertEqual(self.draw("echo Hi | bidet | cat"), [])
        self.assertIn("last command", self.err.getvalue())

    def test_refusals(self):
        for line in ("bidet -P nosuch Hi", "bidet -o /tmp/x.png Hi", "bidet -F /etc/passwd Hi", "bidet --ink 'a;b' Hi",
                     "bidet -w 99999 Hi", "bidet --scroll=sideways Hi", "bidet", "bidet " + "x" * 201):
            self.assertEqual(self.draw(line), [], line)
            self.assertEqual(self.sh.status, 2, line)

    def test_listing_is_captured_so_it_can_be_piped(self):
        def fake_run(argv, **kw):
            self.assertEqual(argv[2:], ["-l"])
            self.assertTrue(kw.get("capture_output"))
            return mock.Mock(stdout=b"arc  an arch\ngold  shiny\n", stderr=b"", returncode=0)
        with mock.patch.object(bidetsh.subprocess, "run", fake_run):
            self.assertEqual(self.run_("bidet -l | grep gold"), "gold  shiny\n")


if __name__ == "__main__":
    unittest.main()
