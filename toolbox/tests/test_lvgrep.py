"""Test suite for lvgrep (see ../lvgrep)."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import run


class LvgrepTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="lvgrep-test-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def make(self, rel, text="", mode="w"):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode) as f:
            f.write(text)
        return path

    def lv(self, args):
        """Run lvgrep with cwd-relative output: returns (completed process, list of names)."""
        saved = os.getcwd()
        os.chdir(self.dir)
        try:
            r = run("lvgrep", args)
        finally:
            os.chdir(saved)
        return r, [n for n in r.stdout.split("\n") if n]


class TestBasics(LvgrepTestCase):
    def test_lists_only_files_without_match(self):
        self.make("a.txt", "has foo\n")
        self.make("b.txt", "nothing\n")
        r, names = self.lv(["foo", "a.txt", "b.txt"])
        self.assertEqual(names, ["b.txt"])
        self.assertEqual(r.returncode, 0)

    def test_exit_1_when_every_file_has_the_pattern(self):
        self.make("a.txt", "foo\n")
        r, names = self.lv(["foo", "a.txt"])
        self.assertEqual(names, [])
        self.assertEqual(r.returncode, 1)

    def test_empty_file_lacks_pattern(self):
        self.make("empty.txt", "")
        r, names = self.lv(["foo", "empty.txt"])
        self.assertEqual(names, ["empty.txt"])

    def test_regex_not_literal(self):
        self.make("a.txt", "abc123\n")
        self.make("b.txt", "abc\n")
        r, names = self.lv([r"c\d+", "a.txt", "b.txt"])
        self.assertEqual(names, ["b.txt"])

    def test_ignore_case(self):
        self.make("a.txt", "FOO\n")
        self.assertEqual(self.lv(["foo", "a.txt"])[1], ["a.txt"])
        self.assertEqual(self.lv(["-i", "foo", "a.txt"])[1], [])

    def test_anchors_are_per_line(self):
        self.make("a.txt", "first\nsecond\n")
        self.assertEqual(self.lv(["^second$", "a.txt"])[1], [])

    def test_bad_pattern_is_exit_2(self):
        self.make("a.txt", "x\n")
        r, _ = self.lv(["(", "a.txt"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("bad pattern", r.stderr)

    def test_missing_file_is_reported_and_exit_2(self):
        r, names = self.lv(["foo", "nope.txt"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("nope.txt", r.stderr)
        self.assertEqual(names, [])

    def test_no_files_without_recursive_is_usage_error(self):
        r, _ = self.lv(["foo"])
        self.assertEqual(r.returncode, 2)

    def test_quiet_prints_nothing_but_sets_status(self):
        self.make("a.txt", "nothing\n")
        r, names = self.lv(["-q", "foo", "a.txt"])
        self.assertEqual(r.stdout, "")
        self.assertEqual(r.returncode, 0)

    def test_null_terminated(self):
        self.make("a.txt", "x\n")
        self.make("b.txt", "y\n")
        r, _ = self.lv(["-0", "foo", "a.txt", "b.txt"])
        self.assertEqual(r.stdout, "a.txt\0b.txt\0")


class TestMultiline(LvgrepTestCase):
    def test_default_is_line_by_line(self):
        self.make("a.txt", "foo\nbar\n")
        self.assertEqual(self.lv([r"foo\nbar", "a.txt"])[1], ["a.txt"])

    def test_multiline_spans_lines(self):
        self.make("a.txt", "foo\nbar\n")
        self.assertEqual(self.lv(["-M", r"foo\nbar", "a.txt"])[1], [])

    def test_dot_stops_at_newline_unless_dotall(self):
        self.make("a.txt", "foo\nbar\n")
        self.assertEqual(self.lv(["-M", "foo.bar", "a.txt"])[1], ["a.txt"])
        self.assertEqual(self.lv(["-Ms", "foo.bar", "a.txt"])[1], [])


class TestRecursive(LvgrepTestCase):
    def setUp(self):
        super().setUp()
        self.make("top.py", "import os\n")
        self.make("sub/has.py", "#!/usr/bin/env python3\n")
        self.make("sub/lacks.py", "print(1)\n")
        self.make("sub/notes.txt", "none\n")
        self.make(".git/config", "none\n")
        self.make("skipme/x.py", "none\n")

    def test_directory_without_r_is_error(self):
        r, _ = self.lv(["^#!", "sub"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("is a directory", r.stderr)

    def test_recursive_default_dir_and_vcs_skipped(self):
        r, names = self.lv(["-r", "^#!"])
        names = sorted(n.replace("\\", "/") for n in names)
        self.assertEqual(names, ["./skipme/x.py", "./sub/lacks.py", "./sub/notes.txt", "./top.py"])

    def test_include(self):
        r, names = self.lv(["-r", "--include=*.py", "^#!", "sub"])
        self.assertEqual([n.replace("\\", "/") for n in names], ["sub/lacks.py"])

    def test_exclude(self):
        r, names = self.lv(["-r", "--exclude=*.txt", "--exclude-dir=skipme", "^#!"])
        names = sorted(n.replace("\\", "/") for n in names)
        self.assertEqual(names, ["./sub/lacks.py", "./top.py"])

    def test_named_file_ignores_include(self):
        r, names = self.lv(["--include=*.py", "^#!", "sub/notes.txt"])
        self.assertEqual(names, ["sub/notes.txt"])


class TestBinary(LvgrepTestCase):
    def test_binary_skipped_unless_text(self):
        self.make("bin.dat", b"abc\0def", mode="wb")
        self.assertEqual(self.lv(["foo", "bin.dat"])[1], [])
        self.assertEqual(self.lv(["-a", "foo", "bin.dat"])[1], ["bin.dat"])


if __name__ == "__main__":
    unittest.main()
