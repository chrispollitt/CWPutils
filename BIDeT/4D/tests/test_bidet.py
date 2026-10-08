#!/usr/bin/env python3
"""Tests for bidet.py and presets.ini.   python tests/test_bidet.py"""
from __future__ import print_function

import io
import os
import shlex
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

# the tests must not ask the terminal they happen to run in (bifterm.py): it may not have SIXEL
os.environ.setdefault("BIDET_NO_QUERY", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import bidet                                        # noqa: E402
import bif                                          # noqa: E402
import bifin                                        # noqa: E402

SAMPLES = os.path.join(ROOT, "samples")
PRESETS = bidet.load_presets([os.path.join(ROOT, "presets.ini")])


def args(*argv):
    return bidet.build_parser().parse_args(list(argv))


def plan(*argv, **kw):
    kw.setdefault("stdout_tty", False)
    kw.setdefault("stdin_tty", False)
    kw.setdefault("env", {})
    kw.setdefault("columns", 80)
    kw.setdefault("pixels", None)
    return bidet.make_plan(args(*argv), PRESETS, **kw)


def sample(name):
    return os.path.join(SAMPLES, name)


def tmp(text, name="p.ini"):
    d = tempfile.mkdtemp()
    p = os.path.join(d, name)
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


class Presets(unittest.TestCase):
    def test_the_shipped_presets(self):
        self.assertGreaterEqual(len(PRESETS), 25)
        for name, p in PRESETS.items():
            self.assertTrue(p.description, name)
            self.assertIn(p.sample, bidet.SAMPLE_KINDS, name)
            bidet.check_preset(p)                                       # its flags, operations and sample are valid
        for need in ("plain", "arc", "squeeze", "wave", "matrix", "bold", "sketch", "trace", "contour", "pixels", "huge"):
            self.assertIn(need, PRESETS)

    def test_every_preset_draws_something_on_its_own_sample(self):
        import gallery
        for name in PRESETS:
            im = Image.open(io.BytesIO(gallery.render(name, 300, PRESETS)))
            g = np.asarray(im.convert("L"))
            self.assertGreater(im.size[0], 100, name)
            self.assertGreater(float((g != g[0, 0]).mean()), 0.001, name)             # something is drawn on the page

    def test_picture_presets_trace_and_block_presets_keep_pixels(self):
        for name in ("sketch", "trace", "contour"):
            self.assertEqual(PRESETS[name].bifin[:2], ["-m", "tone"], name)
            self.assertEqual(PRESETS[name].sample, "picture")
        import gallery
        for name, mode in (("sketch", "tone"), ("contour", "tone"), ("pixels", "block")):
            kind, what = gallery.INPUTS[PRESETS[name].sample]
            p = plan("-P", name, sample(what), "-o", "x.bif")
            pic = bif.loads(bidet.run(p, open(sample(what), "rb").read()))
            self.assertEqual(pic.meta["mode"], mode, name)
        # contour lines through the shading: more of them than the plain outline
        data = open(sample("tone80.txt"), "rb").read()
        n = lambda nm: len(bif.loads(bidet.run(plan("-P", nm, sample("tone80.txt"), "-o", "x.bif"), data)).layers[0].xy)
        self.assertGreater(n("contour"), n("trace"))

    def test_the_gallery_contact_sheet(self):
        import gallery
        sheet = gallery.contact_sheet(["arc", "sketch", "pixels"], PRESETS, tile=(200, 120), columns=2)
        self.assertEqual(sheet.size, (2 * (200 + 12) + 12, 2 * (120 + 26 + 12) + 12))
        with self.assertRaises(KeyError):
            gallery.render("nosuch", 100, PRESETS)

    def test_user_files_add_and_replace(self):
        user = tmp("[arc]\ndescription = my arc\nbifop = arc:bend=0.9\n[mine]\nbifop = pen:5\n")
        ps = bidet.load_presets([os.path.join(ROOT, "presets.ini"), user])
        self.assertEqual((ps["arc"].description, ps["arc"].ops), ("my arc", ["arc:bend=0.9"]))
        self.assertEqual(ps["mine"].ops, ["pen:5"])
        self.assertEqual(list(ps)[:2], list(PRESETS)[:2])                  # the order they were first seen in
        self.assertEqual(bidet.load_presets([os.path.join(HERE, "no-such-file.ini")]), {})

    def test_where_user_presets_live(self):
        self.assertEqual(bidet.preset_files({"XDG_CONFIG_HOME": "/x"})[-1], os.path.join("/x", "bidet", "presets.ini"))
        self.assertEqual(bidet.preset_files({"BIDET_PRESETS": "/y/p.ini", "XDG_CONFIG_HOME": "/x"})[1], "/y/p.ini")
        self.assertTrue(bidet.preset_files({})[0].endswith("presets.ini"))

    def test_mistakes_in_a_preset_are_reported_with_its_name(self):
        for text, what in (("[a]\nbifop = nosuchop:1\n", "unknown operation"), ("[a]\nbifop = pen:abc\n", "not a number"),
                           ("[a]\nbifin = --nosuchflag\n", "bifin flags"), ("[a]\nbifout = --scale x\n", "bifout flags")):
            ps = bidet.load_presets([tmp(text)])
            with self.assertRaises(bif.BifError, msg=text) as cm:
                bidet.check_preset(ps["a"])
            self.assertIn("'a'", str(cm.exception))
            self.assertIn(what, str(cm.exception))
        with self.assertRaises(bif.BifError):
            bidet.load_presets([tmp("this is not an ini file\n")])

    def test_colours_with_a_hash_survive_the_ini_format(self):
        self.assertIn("theme:ink=#33ff66,paper=#001a08", PRESETS["matrix"].ops)


class Input(unittest.TestCase):
    def test_a_file_is_read_and_anything_else_is_text(self):
        p = plan(sample("cow.txt"))
        self.assertEqual((p.source, p.literal, p.stdin), (sample("cow.txt"), None, False))
        p = plan("Hello,", "World!")
        self.assertEqual((p.source, p.literal), (None, "Hello, World!"))
        p = plan("no_such_file.txt")
        self.assertEqual(p.literal, "no_such_file.txt")
        p = plan("-t", sample("cow.txt"))                                   # --text: it is text, though it names a file
        self.assertEqual((p.source, p.literal), (None, sample("cow.txt")))

    def test_text_is_set_in_a_font_not_traced_as_picture_art(self):
        # bifin's classifier takes plain words for picture-style art and traces the density: four vertical bars
        for words in (["Hi there"], ["Hello,", "World!"], ["BIDeT"]):
            p = plan(*(words + ["-o", "x.bif"]))
            self.assertEqual(p.bifin[:2], ["-f", "lettering"])
            pic = bif.loads(bidet.run(p, (" ".join(words) + "\n").encode("utf-8")))
            self.assertEqual(pic.meta["mode"], "lettering", words)
            self.assertIn("text", [L.id for L in pic.layers], words)                # letters, as font outlines
        self.assertEqual(plan(sample("cow.txt")).bifin, [])                         # a file is left to the classifier
        p = plan("Hi", "-F", "serif", "--bifin=--bold")                          # and what the user asks for wins, last
        self.assertEqual(p.bifin, ["-f", "lettering", "--face", "serif", "--bold"])
        self.assertIn("--face serif", p.shell())
        self.assertEqual(plan(sample("cow.txt"), "-F", "mono").bifin, ["--font", "mono"])       # for art: its monospace font

    def test_words_on_standard_input_or_in_a_file_are_lettering_too(self):
        # `echo test | bidet` drew a blank page: the art classifier took the word for picture art
        for data in (b"test\n", b"Hello, World!\n", b"Two lines\nof words\n", b"Sale - 50% off!\n", "Café über\n".encode("utf-8")):
            self.assertTrue(bidet.looks_like_prose(data), data)
            p = bidet.make_plan(args("-o", "x.png"), PRESETS, stdout_tty=False, stdin_tty=False, data=data)
            self.assertTrue(p.stdin and p.lettering, data)
            self.assertEqual(p.bifin[:2], ["-f", "lettering"])
            self.assertEqual(p.bifout[-2:], ["--width", "1000"])
            p = bidet.make_plan(args("-o", "x.bif"), PRESETS, stdout_tty=False, stdin_tty=False, data=data)
            pic = bif.loads(bidet.run(p, data))                                              # and draws something
            self.assertEqual(pic.meta["mode"], "lettering")
        p = plan(tmp("Hello there\n", "w.txt"))
        self.assertTrue(p.lettering)
        self.assertEqual(p.bifin[:2], ["-f", "lettering"])

    def test_art_is_not_taken_for_words(self):
        for name in ("cow.txt", "figlet_big.txt", "tone80.txt", "blocks_color.ans", "dragon_lolcat.ans"):
            with open(sample(name), "rb") as f:
                self.assertFalse(bidet.looks_like_prose(f.read()), name)
        for data in (b"", b"\n", b" /\\\n/__\\\n", b".,,::;;..,,\n", b"|||||\n", b"a" * 40 + b"\n", b"\xff\xfe", b"+--+\n|  |\n+--+\n",
                     b"line\n" * 20):
            self.assertFalse(bidet.looks_like_prose(data), data)
        self.assertFalse(plan(sample("cow.txt")).lettering)
        self.assertFalse(bidet.make_plan(args(), PRESETS, stdout_tty=False, stdin_tty=False, data=b"/\\\n").lettering)

    def test_the_user_can_say_which(self):
        words = b"test\n"
        mk = lambda *a: bidet.make_plan(args(*a), PRESETS, stdout_tty=False, stdin_tty=False, data=words)
        self.assertFalse(mk("--art").lettering)                                              # art, though it looks like words
        self.assertFalse(mk("--bifin=-m line").lettering)                                    # an importer flag: the user knows
        self.assertFalse(mk("-P", "sketch").lettering)                                       # a preset that reads picture art
        self.assertTrue(mk("-t").lettering)
        self.assertTrue(bidet.make_plan(args("-t"), PRESETS, stdout_tty=False, stdin_tty=False, data=b"/\\ | _\n").lettering)

    def test_a_picture_with_nothing_in_it_is_an_error_not_a_blank_page(self):
        p = plan("--art", "-o", "x.png")
        p.stdin, p.literal, p.lettering = True, None, False
        with self.assertRaises(bif.BifError) as cm:
            bidet.run(p, b"test\n")
        self.assertIn("nothing to draw", str(cm.exception))

    def test_a_missing_font_is_an_error_not_a_crash(self):
        p = plan("Hi", "-F", "no-such-font-anywhere", "-o", "x.png")
        with self.assertRaises(bif.BifError):
            bidet.run(p, b"Hi\n")

    def test_standard_input(self):
        self.assertTrue(plan().stdin)
        self.assertTrue(plan("-").stdin)
        with self.assertRaises(bif.BifError):
            plan(stdin_tty=True)                                            # nothing to read and nothing given

    def test_a_bif_is_drawn_as_it_is(self):
        path = tmp("", "x.bif")
        with open(path, "wb") as f:
            f.write(bif.dumps(bifin.convert(open(sample("cow.txt"), "rb").read())))
        p = plan(path)
        self.assertTrue(p.is_bif)
        self.assertEqual([s[0] for s in p.stages()], ["bifout"])
        p = plan(path, "-P", "arc")
        self.assertEqual([s[0] for s in p.stages()], ["bifop", "bifout"])
        with self.assertRaises(bif.BifError):                               # a BIF to a BIF with nothing to do
            plan(path, "-o", "y.bif")

    def test_unknown_preset(self):
        with self.assertRaises(bif.BifError) as cm:
            plan("-P", "nosuch", sample("cow.txt"))
        self.assertIn("nosuch", str(cm.exception))


class Recipe(unittest.TestCase):
    def test_presets_combine_in_order(self):
        p = plan("-P", "arc", "-P", "matrix", "-P", "mono", sample("cow.txt"))
        self.assertEqual(p.ops, PRESETS["arc"].ops + PRESETS["matrix"].ops)
        self.assertEqual(p.bifin, PRESETS["arc"].bifin + PRESETS["matrix"].bifin + PRESETS["mono"].bifin)
        self.assertEqual(p.bifin[-1], "--mono")
        p = plan("-P", "matrix", "-P", "amber", sample("cow.txt"))
        self.assertEqual(p.ops, PRESETS["matrix"].ops + PRESETS["amber"].ops)      # the later theme is applied last: it wins

    def test_extra_flags_are_passed_on(self):
        p = plan(sample("cow.txt"), "--bifin", "-m tone -c 16", "--bifop", "pen:2 flip:h", "--bifout", "--ss 2")
        self.assertEqual(p.bifin, ["-m", "tone", "-c", "16"])
        self.assertEqual(p.ops, ["pen:2", "flip:h"])
        self.assertIn("--ss", p.bifout)

    def test_colours(self):
        p = plan("--ink", "red", "--paper", "#102030", "-P", "matrix", sample("cow.txt"))
        self.assertEqual(p.ops[-1], "theme:ink=red,paper=#102030")                   # asked for: after the preset, so it wins
        self.assertEqual(plan("--ink", "red", sample("cow.txt")).ops, ["theme:ink=red"])
        self.assertEqual(plan("--dark", sample("cow.txt")).ops, [bidet.DARK_THEME])
        self.assertEqual(plan("--light", sample("cow.txt")).ops, [bidet.LIGHT_THEME])
        self.assertEqual(plan("--dark", "-P", "matrix", sample("cow.txt")).ops, PRESETS["matrix"].ops)   # a preset chose colours
        # on the terminal: bifout asks it (SIXEL support, background colour) and fits the page and the ink to it
        p = plan(sample("cow.txt"), stdout_tty=True)
        self.assertEqual(p.ops, [])
        self.assertEqual(p.bifout[:2], ["--background", "auto"])
        self.assertIn("--background auto", p.shell())
        self.assertEqual(plan(sample("cow.txt"), "-o", "a.png", stdout_tty=True).ops, [])         # a file: not the terminal's colours
        self.assertNotIn("--background", plan(sample("cow.txt"), "-o", "a.png", stdout_tty=True).bifout)
        self.assertNotIn("--background", plan(sample("cow.txt")).bifout)                          # a pipe: the picture's own page
        self.assertNotIn("--background", plan(sample("cow.txt"), "-P", "matrix", stdout_tty=True).bifout)   # a preset chose colours
        self.assertNotIn("--background", plan(sample("cow.txt"), "--dark", stdout_tty=True).bifout)
        self.assertNotIn("--background", plan(sample("cow.txt"), "--ink", "red", stdout_tty=True).bifout)
        for own in ("--background=#102030", "--paper=white", "--transparent"):                   # the user's own word wins
            p = plan(sample("cow.txt"), "--bifout=" + own, stdout_tty=True)
            self.assertNotIn("auto", p.bifout, own)

    def test_terminal_helpers(self):
        self.assertIs(bidet.dark_terminal({"COLORFGBG": "15;0"}), True)
        self.assertIs(bidet.dark_terminal({"COLORFGBG": "0;default;15"}), False)
        self.assertIs(bidet.dark_terminal({"COLORFGBG": "7;8"}), True)
        self.assertIsNone(bidet.dark_terminal({}))
        self.assertIsNone(bidet.dark_terminal({"COLORFGBG": "garbage"}))
        self.assertEqual(bidet.fit_width((1000, 600), 80), 950)
        self.assertEqual(bidet.fit_width(None, 100), 800)
        self.assertEqual(bidet.fit_width(None, None), 800)
        self.assertEqual(bidet.fit_width((100, 100), None), 320)                   # not absurdly small ...
        self.assertEqual(bidet.fit_width((9000, 5000), None), 2400)                # ... or large


class Output(unittest.TestCase):
    def test_format_follows_where_it_goes(self):
        self.assertEqual(plan(sample("cow.txt"), "-o", "a.png").fmt, "png")
        self.assertEqual(plan(sample("cow.txt"), "-o", "a.six").fmt, "sixel")
        self.assertEqual(plan(sample("cow.txt"), "-o", "a.sixel").fmt, "sixel")
        self.assertEqual(plan(sample("cow.txt"), "-o", "a.bif").fmt, "bif")
        self.assertEqual(plan(sample("cow.txt"), "-o", "a.unknown").fmt, "png")
        self.assertEqual(plan(sample("cow.txt"), stdout_tty=True).fmt, "sixel")           # on a terminal
        self.assertEqual(plan(sample("cow.txt")).fmt, "png")                               # in a pipe
        self.assertEqual(plan(sample("cow.txt"), "-o", "-", stdout_tty=True).fmt, "png")

    def test_size(self):
        self.assertEqual(plan(sample("cow.txt"), "-o", "a.png").bifout, ["--scale", "2"])           # a file: art twice life size
        self.assertEqual(plan("Hello", "-o", "a.png").bifout, ["--width", "1000"])                  # and text 1000 px wide
        self.assertEqual(plan(sample("cow.txt"), "-w", "640", "-o", "a.png").bifout, ["--width", "640"])
        p = plan(sample("cow.txt"), stdout_tty=True, pixels=(1000, 700))
        self.assertEqual(p.bifout, ["--background", "auto", "--width", "950"])                    # the terminal's width and colour
        p = plan(sample("cow.txt"), stdout_tty=True, columns=100)
        self.assertEqual(p.bifout, ["--background", "auto", "--width", "800"])
        p = plan(sample("cow.txt"), "-P", "plain", "--bifout", "--scale 3", stdout_tty=True)      # asked for: no automatic size
        self.assertEqual(p.bifout, ["--scale", "3", "--background", "auto"])
        self.assertEqual(plan(sample("cow.txt"), "-w", "500", "--bifout", "--scale 3", "-o", "a.png").bifout[-2:], ["--width", "500"])
        self.assertEqual(plan(sample("cow.txt"), "-o", "a.bif").bifout, [])                        # a BIF has no size

    def test_the_pipeline_text(self):
        p = plan(sample("cow.txt"), "-P", "arc", "-o", "a.png")
        p = plan(sample("cow.txt"), "-P", "arc", "--bifin=", "-o", "a.png")
        flags = " ".join(shlex.quote(f) for f in PRESETS["arc"].bifin)
        self.assertEqual(p.shell(), "bifin %s%s | bifop arc:bend=0.4 crop:margin=10 | bifout --scale 2 -o a.png"
                         % (flags + " " if flags else "", shlex.quote(sample("cow.txt"))))
        p = plan("it's a \"test\"", "-P", "bold", "-o", "a.png")
        self.assertTrue(p.shell().startswith("printf '%s\\n' "))
        self.assertEqual(shlex.split(p.shell().split(" | ")[0])[2], "it's a \"test\"")           # quoted so a shell gives it back
        self.assertEqual(plan(sample("cow.txt"), stdout_tty=True, pixels=(800, 600)).shell(),
                         "bifin %s | bifout --background auto --width 760 -s" % shlex.quote(sample("cow.txt")))
        self.assertEqual(plan(stdin_tty=False).shell(), "bifin | bifout --scale 2 -o -")
        self.assertEqual(plan(sample("cow.txt"), "-o", "a.six").shell(), "bifin %s | bifout --scale 2 -o a.six" % shlex.quote(sample("cow.txt")))
        self.assertEqual(plan(sample("cow.txt"), "-o", "a.bif").shell(), "bifin %s -o a.bif" % shlex.quote(sample("cow.txt")))
        self.assertEqual(plan(sample("cow.txt"), "-P", "bold", "-o", "a.bif").shell(),
                         "bifin %s | bifop pen:1.8 -o a.bif" % shlex.quote(sample("cow.txt")))


def run_tool(argv, data):
    prog = {"bifin": "bifin.py", "bifop": "bifop.py", "bifout": "bifout.py"}[argv[0]]
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, prog)] + argv[1:], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    out, err = p.communicate(data)
    if p.returncode:
        raise AssertionError("%s failed: %s" % (argv, err.decode("utf-8", "replace")))
    return out


def run_pipeline(p, data):
    """What a user gets by typing the pipeline: the real tools, one after another, with pipes between them."""
    stages = p.stages()
    for argv in stages:
        if p.output and argv is stages[-1]:                                  # -o FILE: the tool writes it
            argv = argv[:-1] + [os.path.join(tempfile.mkdtemp(), "out")] if argv[-2] == "-o" else argv
            path = argv[-1]
            run_tool(argv, data)
            with open(path, "rb") as f:
                return f.read()
        data = run_tool(argv, data)
    return data


class SugarOverThePipe(unittest.TestCase):
    """The claim that makes the two modes one: what bidet draws is what its printed pipeline draws."""

    def check(self, p, data):
        self.assertEqual(bidet.run(p, data), run_pipeline(p, data), p.shell())

    def test_art_with_presets(self):
        for name, presets in (("cow.txt", ["arc", "matrix"]), ("figlet_big.txt", ["bold", "up"]), ("tone80.txt", ["plain"]),
                              ("dragon_lolcat.ans", ["mono", "wave"]), ("blocks_color.ans", ["paper"])):
            data = open(sample(name), "rb").read()
            argv = [sample(name), "-o", "x.png"]
            for pr in presets:
                argv += ["-P", pr]
            p = plan(*argv)
            self.check(p, data)

    def test_text(self):
        p = plan("Hello, World!", "-P", "squeeze", "-P", "blueprint", "-o", "x.png")
        self.check(p, ("Hello, World!\n").encode("utf-8"))

    def test_sixel_on_a_terminal(self):
        data = open(sample("cow.txt"), "rb").read()
        p = plan(sample("cow.txt"), "-P", "wave", stdout_tty=True, pixels=(900, 600))
        self.assertEqual(p.fmt, "sixel")
        out = bidet.run(p, data)
        self.assertTrue(out.startswith(b"\x1bP") and out.rstrip().endswith(b"\x1b\\"))
        self.assertEqual(out, run_pipeline(p, data))

    def test_a_bif_out_and_back_in(self):
        data = open(sample("cow.txt"), "rb").read()
        p = plan(sample("cow.txt"), "-P", "arc", "-o", "x.bif")
        blob = bidet.run(p, data)
        self.assertEqual(blob, run_pipeline(p, data))
        self.assertEqual([e["op"] for e in bif.loads(blob).meta["history"]], ["arc", "crop"])
        path = tmp("", "x.bif")
        with open(path, "wb") as f:
            f.write(blob)
        q = plan(path, "-P", "matrix", "-o", "y.png")
        self.assertEqual(bidet.run(q, blob), run_pipeline(q, blob))

    def test_extra_flags(self):
        data = open(sample("cow.txt"), "rb").read()
        p = plan(sample("cow.txt"), "--bifin", "-m tone", "--bifop", "rotate:90", "--bifout", "--ss 2", "-o", "x.png")
        self.check(p, data)


def run_cli(*argv, **kw):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop("COLORFGBG", None)
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "bidet.py")] + list(argv), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    out, err = p.communicate(kw.get("input"))
    return p.returncode, out, err


class Cli(unittest.TestCase):
    def test_list(self):
        rc, out, err = run_cli("--list-presets")
        self.assertEqual(rc, 0)
        text = out.decode("utf-8")
        for name in PRESETS:
            self.assertIn(name, text)
        self.assertIn("Arched upward", text)

    def test_text_to_a_file(self):
        path = os.path.join(tempfile.mkdtemp(), "hello.png")
        rc, out, err = run_cli("Hello,", "World!", "-P", "arc", "-o", path)
        self.assertEqual((rc, out), (0, b""), err)
        im = Image.open(path)
        self.assertGreater(im.size[0], 100)

    def test_a_pipe(self):
        rc, out, err = run_cli("-P", "bold", "-P", "neon", input=open(sample("cow.txt"), "rb").read())
        self.assertEqual((rc, out[:4]), (0, b"\x89PNG"), err)

    def test_show_pipeline(self):
        rc, out, err = run_cli("-n", sample("cow.txt"), "-P", "arc")
        self.assertEqual(rc, 0)
        self.assertEqual(out.decode().strip().count(" | "), 2)
        self.assertEqual(out.decode().split()[0], "bifin")

    def test_verbose_prints_the_pipeline_on_stderr(self):
        path = os.path.join(tempfile.mkdtemp(), "v.png")
        rc, out, err = run_cli("-v", sample("cow.txt"), "-o", path)
        self.assertIn(b"bifin", err)

    def test_warnings_reach_stderr(self):
        rc, out, err = run_cli("-P", "wave", sample("blocks_color.ans"), "-o", os.path.join(tempfile.mkdtemp(), "w.png"))
        self.assertEqual(rc, 0, err)
        self.assertIn(b"raster", err)

    def test_errors_are_one_line_and_nonzero(self):
        for argv, text in ((("-P", "nosuch", "x"), b"no preset"), (("--dark", "--light", "x"), b"--dark and --light"),
                           (("x", "--bifop", "nosuchop"), b"unknown operation"), (("x", "--bifin=--nosuchflag"), b"bifin flags"),
                           (("x", "--bifop", "pen:abc"), b"not a number")):
            rc, out, err = run_cli(*argv, input=b"", )
            self.assertEqual(rc, 1, argv)
            self.assertIn(text, err)
            self.assertEqual(len(err.strip().splitlines()), 1, err)

    def test_version(self):
        rc, out, err = run_cli("-V")
        self.assertEqual(rc, 0)
        self.assertIn(b"bidet", out + err)


if __name__ == "__main__":
    unittest.main(verbosity=1)
