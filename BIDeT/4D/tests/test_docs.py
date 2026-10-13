#!/usr/bin/env python3
"""Tests that the man pages say what the code does: every operation of bifop and every option of bifin is in its page, the
pages are well-formed roff, and the Makefile lists them.   python tests/test_docs.py"""
from __future__ import print_function

import os
import re
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import bifin                                        # noqa: E402
import bifop                                        # noqa: E402
import bifout                                       # noqa: E402
import bidet                                        # noqa: E402

PAGES = ("bidet", "bifin", "bifop", "bifout")


def page(name):
    with open(os.path.join(ROOT, name + ".1"), encoding="utf-8") as f:
        return f.read()


def plain(text):
    """The page's words as a reader sees them: roff escapes for a hyphen and font changes removed."""
    text = text.replace("\\-", "-").replace("\\&", "")
    return re.sub(r"\\f[BIRP]", "", text)


def long_options(parser):
    out = set()
    for action in parser._actions:
        out.update(o for o in action.option_strings if o.startswith("--") and o not in ("--help",))
    return out


class ManPages(unittest.TestCase):
    def mentions(self, text, word, what):
        """A failure says what is missing, not the whole page."""
        self.assertTrue(word in text, what)

    def test_every_page_has_its_sections_and_is_in_the_makefile(self):
        with open(os.path.join(ROOT, "Makefile"), encoding="utf-8") as f:
            makefile = f.read()
        listed = re.search(r"^MANPAGES\s*=\s*(.*)$", makefile, re.M).group(1).split()
        for n in PAGES:
            text = page(n)
            self.assertTrue(text.startswith(".TH %s 1 " % n.upper()), n)
            for section in ("NAME", "SYNOPSIS", "DESCRIPTION", "SEE ALSO"):
                self.assertIn(".SH %s" % section, text, (n, section))
            self.assertIn(n + ".1", listed, "%s.1 is not in MANPAGES" % n)
            self.assertTrue(re.search(r"\.SH NAME\n%s - " % n, plain(text)), "%s.1: NAME does not start with the name" % n)

    @unittest.skipUnless(shutil.which("groff"), "no groff to check the pages with")
    def test_the_pages_are_well_formed_roff(self):
        for n in PAGES:
            p = subprocess.Popen(["groff", "-man", "-ww", "-z", os.path.join(ROOT, n + ".1")], stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT)
            out = p.communicate()[0].decode("utf-8", "replace")
            self.assertEqual(out.strip(), "", "%s.1: %s" % (n, out))

    def test_bifop_documents_every_operation(self):
        text = plain(page("bifop"))
        for name in bifop.OPS:
            self.assertTrue(re.search(r"\b%s\b" % re.escape(name), text), "bifop.1 does not mention the operation %s" % name)
        # and every parameter any operation takes
        params = set(p[0] for _fn, ps, _doc in bifop.OPS.values() for p in ps)
        for pname in sorted(params):
            self.assertTrue(re.search(r"\b%s\b" % re.escape(pname), text), "bifop.1 does not mention the parameter %s" % pname)

    def test_bifin_documents_every_option(self):
        text = plain(page("bifin"))
        for opt in sorted(long_options(bifin.build_parser())):
            self.mentions(text, opt, "bifin.1 does not mention %s" % opt)
        for short in ("-o", "-f", "-m", "-c", "-a", "-w", "-j", "-v", "-V"):
            self.mentions(text, short, "bifin.1 does not mention %s" % short)

    def test_bifout_and_bidet_name_what_they_play_and_draw(self):
        out = plain(page("bifout"))
        for opt in sorted(long_options(bifout.build_parser())):                      # every option, none excused
            self.mentions(out, opt, "bifout.1 does not mention %s" % opt)
        b = plain(page("bidet"))
        for opt in sorted(long_options(bidet.build_parser())):
            if opt in ("--bifin", "--bifop", "--bifout"):
                continue                                                                # (named in one phrase, below)
            self.mentions(b, opt, "bidet.1 does not mention %s" % opt)
        for opt in ("--bifin", "--bifop", "--bifout", "-P", "-o", "-n"):
            self.mentions(b, opt, "bidet.1 does not mention %s" % opt)

    def test_the_terminal_caveat_is_in_the_pages_that_play_animations(self):
        for n in ("bifout", "bidet"):
            self.mentions(page(n), "YMMV", "%s.1 has no YMMV note" % n)
            self.mentions(page(n), "mintty", "%s.1 does not say where it was tested" % n)


if __name__ == "__main__":
    unittest.main()
