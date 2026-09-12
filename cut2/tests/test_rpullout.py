"""Test suite for rpullout (see ../rpullout)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import run


class TestBasicMatching(unittest.TestCase):
    def test_extracts_want_before_amatch(self):
        r = run("rpullout", [r"\w+", "END"], "foo hello world END bar\n")
        self.assertEqual(r.stdout, "world\n")

    def test_picks_last_occurrence_not_first(self):
        r = run("rpullout", [r"\w+", "STOP"], "one two three STOP\n")
        self.assertEqual(r.stdout, "three\n")

    def test_case_insensitive(self):
        r = run("rpullout", ["[a-z]+", "STOP"], "Foo BAR baz STOP\n")
        self.assertEqual(r.stdout, "baz\n")

    def test_non_matching_line_is_skipped(self):
        r = run("rpullout", [r"\w+", "STOP"], "no marker here\nfoo bar STOP\n")
        self.assertEqual(r.stdout, "bar\n")


class TestGapControl(unittest.TestCase):
    def test_dont_flag_requires_adjacency(self):
        r = run("rpullout", ["-d", r"\w+", "STOP"], "wordSTOP\n")
        self.assertEqual(r.stdout, "word\n")

    def test_dont_flag_fails_when_not_adjacent(self):
        r = run("rpullout", ["-d", r"\w+", "STOP"], "word STOP\n")
        self.assertEqual(r.stdout, "")


class TestMultilineMode(unittest.TestCase):
    def test_multiline_matches_across_newlines(self):
        r = run("rpullout", ["-m", r"\w+", "STOP"], "one\ntwo\nthree\nSTOP\n")
        self.assertEqual(r.stdout, "three\n")


class TestValidation(unittest.TestCase):
    def test_empty_want_is_an_error(self):
        r = run("rpullout", ["", "STOP"], "x\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("want", r.stderr)

    def test_empty_amatch_is_an_error(self):
        r = run("rpullout", ["want", ""], "x\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("amatch", r.stderr)

    def test_missing_args_shows_usage(self):
        r = run("rpullout", [], "x\n")
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
