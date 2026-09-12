"""Test suite for pullout (see ../pullout)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import run


class TestBasicMatching(unittest.TestCase):
    def test_extracts_want_between_bmatch_and_amatch(self):
        r = run("pullout", ["BEGIN", r"\w+", "END"], "foo BEGIN hello END bar\n")
        self.assertEqual(r.stdout, "hello\n")

    def test_amatch_optional(self):
        r = run("pullout", ["BEGIN", r"\w+"], "foo BEGIN hello world\n")
        self.assertEqual(r.stdout, "hello\n")

    def test_case_insensitive(self):
        r = run("pullout", ["begin", r"\w+", "end"], "foo BEGIN hello END bar\n")
        self.assertEqual(r.stdout, "hello\n")

    def test_non_matching_line_is_skipped(self):
        r = run("pullout", ["BEGIN", r"\w+", "END"], "no markers here\nBEGIN yes END\n")
        self.assertEqual(r.stdout, "yes\n")

    def test_multiple_lines_each_matched_independently(self):
        r = run("pullout", ["BEGIN", r"\w+", "END"], "BEGIN one END\nBEGIN two END\n")
        self.assertEqual(r.stdout, "one\ntwo\n")


class TestOutputModes(unittest.TestCase):
    def test_dash_a_prints_three_parts(self):
        r = run("pullout", ["-a", "BEGIN", r"\w+", "END"], "foo BEGIN hello END bar\n")
        self.assertEqual(r.stdout, "BEGIN\thello\tEND\n")

    def test_dash_cap_a_prints_five_parts_with_gaps(self):
        r = run("pullout", ["-A", "BEGIN", r"\w+", "END"], "foo BEGIN hello END bar\n")
        self.assertEqual(r.stdout, "BEGIN\t \thello\t \tEND\n")


class TestGapControl(unittest.TestCase):
    def test_dont_flag_requires_adjacency(self):
        r = run("pullout", ["-d", "BEGIN:", r"\w+", ":END"], "foo BEGIN:hello:END bar\n")
        self.assertEqual(r.stdout, "hello\n")

    def test_dont_flag_fails_when_not_adjacent(self):
        r = run("pullout", ["-d", "BEGIN:", r"\w+", ":END"], "foo BEGIN: hello :END bar\n")
        self.assertEqual(r.stdout, "")


class TestMultilineMode(unittest.TestCase):
    def test_multiline_matches_across_newlines(self):
        r = run("pullout", ["-m", "BEGIN", r"\w+", "END"], "foo\nBEGIN\nhello\nworld\nEND\nbar\n")
        self.assertEqual(r.stdout, "hello\n")

    def test_multiline_finds_all_matches(self):
        r = run("pullout", ["-m", "-d", "BEGIN:", r"\w+", ":END"], "BEGIN:one:END BEGIN:two:END\n")
        self.assertEqual(r.stdout, "one\ntwo\n")


class TestValidation(unittest.TestCase):
    def test_empty_bmatch_is_an_error(self):
        r = run("pullout", ["", "want"], "x\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("bmatch", r.stderr)
        self.assertIn("rpullout", r.stderr)

    def test_empty_want_is_an_error(self):
        r = run("pullout", ["before", ""], "x\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("want", r.stderr)

    def test_missing_args_shows_usage(self):
        r = run("pullout", [], "x\n")
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
