"""Test suite for cut2 (see ../cut2)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import run


class TestFieldMode(unittest.TestCase):
    def test_default_whitespace_delimiter(self):
        r = run("cut2", ["-f2"], "John    Doe    30\n")
        self.assertEqual(r.stdout, "Doe\n")

    def test_multiple_spaces_collapse(self):
        r = run("cut2", ["-f1,3"], "foo  bar    baz\n")
        self.assertEqual(r.stdout, "foo\tbaz\n")

    def test_consecutive_tabs_collapse_like_multiple_spaces(self):
        # default delimiter is "[\t ]+" (one-or-more), so a run of two
        # tabs is a single delimiter, not an empty field in between.
        r = run("cut2", ["-f1,3"], "a\t\tb\tc\n")
        self.assertEqual(r.stdout, "a\tc\n")

    def test_custom_single_char_delimiter(self):
        r = run("cut2", ["-f1,3", "-d,"], "Alice,Bob,25\n")
        self.assertEqual(r.stdout, "Alice\t25\n")

    def test_regex_delimiter(self):
        r = run("cut2", ["-f2,4", "-d[,;]"], "a,b;c,d\n")
        self.assertEqual(r.stdout, "b\td\n")

    def test_quoted_field_kept_as_one_field(self):
        r = run("cut2", ["-f2"], 'John "Doe Smith" 30\n')
        self.assertEqual(r.stdout, '"Doe Smith"\n')

    def test_quotes_are_preserved_not_stripped(self):
        r = run("cut2", ["-f1,3"], 'John "Doe Smith" 30\n')
        self.assertEqual(r.stdout, "John\t30\n")

    def test_escaped_quote_does_not_close_span(self):
        r = run("cut2", ["-f2"], 'a "b\\"c" d\n')
        self.assertEqual(r.stdout, '"b\\"c"\n')

    def test_single_quote_field(self):
        r = run("cut2", ["-f2"], "a 'b c' d\n")
        self.assertEqual(r.stdout, "'b c'\n")

    def test_open_ended_range(self):
        r = run("cut2", ["-f3-"], "a b c d e\n")
        self.assertEqual(r.stdout, "c\td\te\n")

    def test_out_of_range_field_is_dropped(self):
        r = run("cut2", ["-f1,5"], "a b\n")
        self.assertEqual(r.stdout, "a\n")

    def test_fields_can_be_reordered_and_duplicated(self):
        r = run("cut2", ["-f3,1,1"], "a b c\n")
        self.assertEqual(r.stdout, "c\ta\ta\n")

    def test_no_selected_fields_prints_blank_line(self):
        r = run("cut2", ["-f9"], "a b\n")
        self.assertEqual(r.stdout, "\n")

    def test_multiple_lines(self):
        r = run("cut2", ["-f1"], "a b\nc d\n")
        self.assertEqual(r.stdout, "a\nc\n")


class TestCharMode(unittest.TestCase):
    def test_char_range(self):
        r = run("cut2", ["-c1-3"], "abcdef\n")
        self.assertEqual(r.stdout, "abc\n")

    def test_open_ended_char_range(self):
        r = run("cut2", ["-c4-"], "abcdef\n")
        self.assertEqual(r.stdout, "def\n")

    def test_char_list(self):
        r = run("cut2", ["-c1,3,5"], "abcdef\n")
        self.assertEqual(r.stdout, "ace\n")

    def test_char_out_of_range_dropped(self):
        r = run("cut2", ["-c1,99"], "abc\n")
        self.assertEqual(r.stdout, "a\n")


class TestFilesAndErrors(unittest.TestCase):
    def test_reads_from_file_argument(self):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as f:
            f.write("x y z\n")
            path = f.name
        try:
            r = run("cut2", ["-f2", path])
            self.assertEqual(r.stdout, "y\n")
        finally:
            os.unlink(path)

    def test_missing_file_is_an_error(self):
        r = run("cut2", ["-f1", "/no/such/file/should/exist"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("cut2", r.stderr)

    def test_requires_f_or_c(self):
        r = run("cut2", [], "a b\n")
        self.assertNotEqual(r.returncode, 0)

    def test_f_and_c_are_mutually_exclusive(self):
        r = run("cut2", ["-f1", "-c1"], "a b\n")
        self.assertNotEqual(r.returncode, 0)

    def test_invalid_delimiter_regex(self):
        r = run("cut2", ["-f1", "-d[unterminated"], "a b\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("cut2", r.stderr)


if __name__ == "__main__":
    unittest.main()
