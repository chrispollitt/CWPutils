"""Test suite for ghgrep (see ../ghgrep)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import run

BRACKET_SAMPLE = "[Section A]\nfoo\nmatch1\nbar\n\n[Section B]\nbaz\nqux\n"
SEPARATOR_SAMPLE = "----\nHeader1\nfoo match2 bar\n----\nHeader2\nbaz\n"


def write_temp(text):
    f = tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt")
    f.write(text)
    f.close()
    return f.name


class GhgrepTestCase(unittest.TestCase):
    def setUp(self):
        self.bracket_file = write_temp(BRACKET_SAMPLE)
        self.separator_file = write_temp(SEPARATOR_SAMPLE)

    def tearDown(self):
        os.unlink(self.bracket_file)
        os.unlink(self.separator_file)


class TestBracketHeaders(GhgrepTestCase):
    def test_matching_group_prints_header_and_lines(self):
        r = run("ghgrep", ["--brackets", "match1", self.bracket_file])
        self.assertEqual(r.stdout, "[Section A]\nfoo\nmatch1\nbar\n")

    def test_non_matching_group_is_omitted(self):
        r = run("ghgrep", ["--brackets", "match1", self.bracket_file])
        self.assertNotIn("Section B", r.stdout)

    def test_only_headers_flag(self):
        r = run("ghgrep", ["--brackets", "--only-headers", "match1", self.bracket_file])
        self.assertEqual(r.stdout, "[Section A]\n")

    def test_no_match_produces_no_output(self):
        r = run("ghgrep", ["--brackets", "nomatch", self.bracket_file])
        self.assertEqual(r.stdout, "")

    def test_case_insensitive_flag(self):
        r = run("ghgrep", ["-i", "--brackets", "MATCH1", self.bracket_file])
        self.assertIn("match1", r.stdout)


class TestSeparatorHeaders(GhgrepTestCase):
    def test_separator_detects_header_after_separator_line(self):
        r = run("ghgrep", ["--separator=----", "match2", self.separator_file])
        self.assertIn("Header1", r.stdout)
        self.assertIn("foo match2 bar", r.stdout)


class TestSmartDetection(GhgrepTestCase):
    def test_smart_mode_finds_bracket_headers_by_default(self):
        r = run("ghgrep", ["match1", self.bracket_file])
        self.assertEqual(r.stdout, "[Section A]\nfoo\nmatch1\nbar\n")


class TestMiscOptions(GhgrepTestCase):
    def test_line_numbers(self):
        r = run("ghgrep", ["--brackets", "-n", "match1", self.bracket_file])
        self.assertIn("3:match1", r.stdout)

    def test_invert_match_excludes_group_with_no_non_matching_lines(self):
        # -v flips per-line matching for group *selection* purposes, but
        # an included group is still printed in full (context defaults
        # to the whole group), so a matching line can still appear if
        # its group also has non-matching lines.
        # every line in this group -- including the header -- contains
        # "match1", so under -v none of them qualify and the group as a
        # whole is dropped.
        sample = "[match1 Sect]\nmatch1\nmatch1\n\n[No Match]\nfoo\nbar\n"
        path = write_temp(sample)
        try:
            r = run("ghgrep", ["--brackets", "-v", "match1", path])
            self.assertNotIn("Sect", r.stdout)
            self.assertIn("No Match", r.stdout)
            self.assertIn("foo", r.stdout)
        finally:
            os.unlink(path)

    def test_invalid_regex_exits_nonzero(self):
        r = run("ghgrep", ["match1(", self.bracket_file])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("invalid regex", r.stderr)

    def test_missing_file_reports_error(self):
        r = run("ghgrep", ["--brackets", "x", "/no/such/file.txt"])
        self.assertIn("No such file", r.stderr)

    def test_reads_from_stdin_when_no_file_given(self):
        r = run("ghgrep", ["--brackets", "match1"], BRACKET_SAMPLE)
        self.assertEqual(r.stdout, "[Section A]\nfoo\nmatch1\nbar\n")


if __name__ == "__main__":
    unittest.main()
