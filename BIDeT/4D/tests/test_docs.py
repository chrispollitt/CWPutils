#!/usr/bin/env python3
"""Tests that the man pages say what the code does: every operation of bifop and every option of bifin is in its page, the
pages are well-formed roff, and the Makefile lists them; and that RECIPES.md (the book of pipelines with other programs) still
names real presets, operations and flags.   python tests/test_docs.py"""
from __future__ import print_function

import io
import os
import re
import shlex
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


class Recipes(unittest.TestCase):
    """RECIPES.md, the book of pipelines with other people's tools.  Nothing is run (the other programs may not be installed):
    every bidet, bifin, bifop and bifout command in it must still parse, every preset and operation it names must exist, and every
    other program it uses must be in its table of ingredients, so that a renamed flag or preset cannot leave the book wrong."""
    BUILTINS = ("echo", "printf", "cat", "for", "do", "done", "while", "sleep", "{", "}")

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "RECIPES.md"), encoding="utf-8") as f:
            cls.text = f.read()
        cls.presets = bidet.load_presets([os.path.join(ROOT, "presets.ini")])
        cls.commands = []                                                          # (cmd, args) of every command in a code block
        for line in cls.text.splitlines():
            if not re.match(r"^    \S", line) or line.startswith("    producer |"):          # (the template of a recipe is not one)
                continue
            lex = shlex.shlex(line, posix=True, punctuation_chars=True)
            lex.whitespace_split = True
            seg = []
            for tok in list(lex) + [";"]:
                if tok in ("|", ";", "&&", "||"):
                    while seg and seg[0] in ("do", "then", "{"):
                        seg = seg[1:]
                    if seg and seg[0] != "}":
                        args = seg[1:]
                        if ">" in args:
                            args = args[:args.index(">")]                          # (a redirection is not an argument)
                        cls.commands.append((seg[0], args))
                    seg = []
                else:
                    seg.append(tok)

    def table(self):
        return self.text.split("## Ingredients")[1].split("## Text as a ticker")[0]

    def parse(self, parser, args, what):
        saved, sys.stderr = sys.stderr, io.StringIO()
        try:
            return parser.parse_args(list(args))
        except SystemExit:
            self.fail("%s: RECIPES.md has a command that no longer parses: %s %s (%s)" % (
                what, what, " ".join(args), sys.stderr.getvalue().strip().splitlines()[-1:]))
        finally:
            sys.stderr = saved

    def test_there_are_recipes_to_check(self):
        names = set(c for c, _a in self.commands)
        for tool in ("bidet", "bifin", "bifop", "bifout", "fortune", "figlet", "ffmpeg", "git"):
            self.assertIn(tool, names)
        self.assertGreater(len([1 for c, _a in self.commands if c == "bidet"]), 20)

    def test_every_bidet_bifin_bifop_and_bifout_command_parses(self):
        for cmd, args in self.commands:
            if cmd == "bidet":
                a = self.parse(bidet.build_parser(), args, "bidet")
                for name in a.preset or []:
                    self.assertIn(name, self.presets, "bidet -P %s: no such preset" % name)
            elif cmd == "bifin":
                self.parse(bifin.build_parser(), args, "bifin")
            elif cmd == "bifout":
                self.parse(bifout.build_parser(), args, "bifout")
            elif cmd == "bifop":
                for spec in [x for x in args if not x.startswith("-")]:
                    name, raw = bifop.parse_spec(spec)
                    bifop.convert_args(name, raw)

    def test_every_preset_the_text_names_exists(self):
        for name in re.findall(r"(?<!\[)-P ([A-Za-z][\w-]*)", self.text):                  # (`[-P preset]` in the template is not a name)
            self.assertIn(name, self.presets, "RECIPES.md mentions -P %s, which is not a preset" % name)

    def test_every_other_program_is_in_the_table_of_ingredients(self):
        table = self.table()
        for cmd, _args in self.commands:
            if cmd in ("bidet", "bifin", "bifop", "bifout") or cmd in self.BUILTINS:
                continue
            self.assertIn("`%s`" % cmd, table, "%s is used in RECIPES.md but is not in the table of ingredients" % cmd)

    def test_the_book_is_honest_and_shipped(self):
        for heading in ("## How these were tested", "## Not tried, and not working", "## Gotchas"):
            self.assertIn(heading, self.text)
        with open(os.path.join(ROOT, "Makefile"), encoding="utf-8") as f:
            self.assertIn("RECIPES.md", re.search(r"^DOCS\s*=\s*(.*)$", f.read(), re.M).group(1).split())


if __name__ == "__main__":
    unittest.main()
