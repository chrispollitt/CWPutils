#!/usr/bin/env python3
"""bidet: the simple way in to BIDeT 4D.

    bidet "Hello, World!"                      text, drawn on the terminal (SIXEL)
    bidet cow.txt -P arc -P matrix             ASCII / ANSI art, arched, green on black
    cowsay moo | bidet -P bold -o moo.png      from a pipe, to a PNG
    bidet --list-presets                       what -P knows

It reads the input, applies the presets you ask for, and draws the result: it makes the same
`bifin ... | bifop ... | bifout ...` pipeline a power user would type, and runs it in-process.
`bidet -n ...` (--show-pipeline) prints that pipeline instead, so you can start from it and use the
three tools with all their flags.  Presets are recipes in presets.ini (yours go in
~/.config/bidet/presets.ini); `--bifin`, `--bifop` and `--bifout` pass extra flags to a stage.

What it works out for you:
  * the input: a file name is read as a file, anything else is the text itself; a BIF is drawn as it is
  * the output: SIXEL on a terminal, else PNG; with -o the format follows the file name (.png, .six, .bif)
  * the size: as wide as the terminal's pixels (or --width); for a file, text 1000 px wide and art twice life size
  * dark terminals: with COLORFGBG saying the background is dark (or --dark), light lines on dark paper

Python 3.7+, numpy 1.16+, Pillow 5.4+.
"""
from __future__ import print_function

import argparse
import collections
import io
import os
import shlex
import sys

import bif
import bifin
import bifop
import bifout

try:
    import configparser
except ImportError:                                                       # (Python 2 is not supported)
    raise SystemExit("bidet: needs Python 3")

VERSION = "0.1"
HERE = os.path.dirname(os.path.realpath(__file__))
DARK_THEME = "theme:ink=#e6e6e6,paper=#000000"
LIGHT_THEME = "theme:ink=#000000,paper=#ffffff"


# ---------------------------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------------------------
SAMPLE_KINDS = ("text", "art", "picture", "blocks", "colour")


class Preset(object):
    def __init__(self, name, description="", bifin_flags=None, ops=None, bifout_flags=None, sample="art"):
        self.name, self.description, self.sample = name, description, sample
        self.bifin, self.ops, self.bifout = list(bifin_flags or []), list(ops or []), list(bifout_flags or [])


def preset_files(env=None):
    """The files presets come from, later ones replacing earlier ones: ours, $BIDET_PRESETS, the user's."""
    env = os.environ if env is None else env
    files = [os.path.join(HERE, "presets.ini")]
    if env.get("BIDET_PRESETS"):
        files.append(env["BIDET_PRESETS"])
    cfg = env.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    files.append(os.path.join(cfg, "bidet", "presets.ini"))
    return files


def load_presets(files=None):
    """{name: Preset}, in the order first seen."""
    presets = collections.OrderedDict()
    for path in (preset_files() if files is None else files):
        if not os.path.isfile(path):
            continue
        cp = configparser.ConfigParser(interpolation=None, delimiters=("=",), comment_prefixes=("#", ";"),
                                       inline_comment_prefixes=None)
        try:
            with io.open(path, encoding="utf-8") as f:
                cp.read_file(f)
        except (configparser.Error, IOError, UnicodeError) as e:
            raise bif.BifError("%s: %s" % (path, str(e).splitlines()[0]))
        for name in cp.sections():
            sec = cp[name]
            try:
                presets[name] = Preset(name, sec.get("description", "").strip(),
                                       shlex.split(sec.get("bifin", "")), shlex.split(sec.get("bifop", "")),
                                       shlex.split(sec.get("bifout", "")), sec.get("sample", "art").strip())
            except ValueError as e:
                raise bif.BifError("%s: preset '%s': %s" % (path, name, e))
    return presets


def _parse_flags(parser, flags, what):
    """Check a stage's flags with that tool's own parser (which exits on a mistake: say where it came from)."""
    saved = sys.stderr
    sys.stderr = io.StringIO()
    try:
        return parser.parse_args(list(flags))
    except SystemExit:
        msg = sys.stderr.getvalue().strip().splitlines()
        raise bif.BifError("%s: %s" % (what, msg[-1] if msg else "bad flags"))
    finally:
        sys.stderr = saved


def check_preset(p):
    """Raise BifError if a preset's recipe would not run: bad flags or operations."""
    if p.sample not in SAMPLE_KINDS:
        raise bif.BifError("preset '%s': sample is one of %s, not '%s'" % (p.name, ", ".join(SAMPLE_KINDS), p.sample))
    _parse_flags(bifin.build_parser(), p.bifin, "preset '%s' bifin flags" % p.name)
    _parse_flags(bifout.build_parser(), p.bifout, "preset '%s' bifout flags" % p.name)
    for spec in p.ops:
        try:
            name, raw = bifop.parse_spec(spec)
            bifop.convert_args(name, raw)
        except bif.BifError as e:
            raise bif.BifError("preset '%s': %s" % (p.name, e))


# ---------------------------------------------------------------------------------------------
# The terminal
# ---------------------------------------------------------------------------------------------
def terminal_pixels(fd=1):
    """(width, height) in pixels of the terminal on `fd`, if it says (most do, through the window size), else None."""
    try:
        import fcntl
        import struct
        import termios
        rows, cols, xp, yp = struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8))
        if xp and yp:
            return xp, yp
    except Exception:                                                     # no tty, no termios (Windows), no pixels
        pass
    return None


def terminal_columns(fd=1):
    try:
        return os.get_terminal_size(fd).columns
    except (OSError, ValueError, AttributeError):
        try:
            return int(os.environ.get("COLUMNS", ""))
        except ValueError:
            return None


def fit_width(pixels=None, columns=None):
    """How wide to draw on a terminal: 95% of its pixel width, or 8 px a column if it does not say, within 320..2400."""
    if pixels:
        w = int(0.95 * pixels[0])
    elif columns:
        w = 8 * columns
    else:
        w = 800
    return max(320, min(2400, w))


def dark_terminal(env=None):
    """True / False from COLORFGBG ('15;0': foreground;background as ANSI numbers), or None if it does not say."""
    env = os.environ if env is None else env
    v = env.get("COLORFGBG", "")
    if ";" not in v:
        return None
    try:
        bg = int(v.split(";")[-1])
    except ValueError:
        return None
    return bg in (0, 1, 2, 3, 4, 5, 6, 8)


# ---------------------------------------------------------------------------------------------
# The plan: what a command line comes to
# ---------------------------------------------------------------------------------------------
class Plan(object):
    """Everything bidet decided: the three stages' flags and operations, where the input comes from and where
    the picture goes."""
    def __init__(self):
        self.source = None            # a file name, or None for text / stdin
        self.literal = None           # the text, if the input is text given on the command line
        self.stdin = False
        self.is_bif = False
        self.bifin = []
        self.ops = []
        self.bifout = []
        self.fmt = "png"              # png | sixel | bif
        self.output = None            # a file name, or None for standard output

    def stages(self):
        """The pipeline as a list of command words: [[program, words...], ...]."""
        out, infile = [], None
        if self.is_bif:
            if self.ops:
                out.append(["bifop", "-i", self.source] + self.ops)
            else:
                infile = self.source                                      # nothing to change: bifout reads the file
        else:
            out.append(["bifin"] + self.bifin + ([self.source] if self.source else []))
            if self.ops:
                out.append(["bifop"] + self.ops)
        if self.fmt == "bif":
            if self.output:
                out[-1] += ["-o", self.output]
        else:
            tail = ["bifout"] + self.bifout + ([infile] if infile else [])
            tail += ["-s"] if self.fmt == "sixel" and not self.output else []
            tail += ["-o", self.output or "-"] if (self.output or self.fmt == "png") else []
            out.append(tail)
        return out

    def shell(self):
        parts = [" ".join(shlex.quote(w) for w in st) for st in self.stages()]
        head = ""
        if self.literal is not None:
            head = "printf '%%s\\n' %s | " % shlex.quote(self.literal)
        return head + " | ".join(parts)


def format_for(path):
    ext = os.path.splitext(path or "")[1].lower()
    if ext in (".six", ".sixel"):
        return "sixel"
    if ext == ".bif":
        return "bif"
    return "png"


def make_plan(args, presets, env=None, stdout_tty=None, stdin_tty=None, columns=None, pixels=None):
    """Turn parsed command-line arguments into a Plan (no input is read, nothing is drawn)."""
    env = os.environ if env is None else env
    stdout_tty = sys.stdout.isatty() if stdout_tty is None else stdout_tty
    stdin_tty = sys.stdin.isatty() if stdin_tty is None else stdin_tty
    plan = Plan()
    words = args.input
    if not words:
        if stdin_tty:
            raise bif.BifError("no input: give some text or a file, or pipe the art in (bidet --help)")
        plan.stdin = True
    elif len(words) == 1 and not args.text and os.path.isfile(words[0]):
        plan.source = words[0]
        plan.is_bif = open(plan.source, "rb").read(8) == bif.MAGIC
    elif len(words) == 1 and words[0] == "-" and not args.text:
        plan.stdin = True
    else:
        plan.literal = " ".join(words)
    # the recipe: presets in the order asked for, then what was asked on the command line
    if plan.literal is not None:
        plan.bifin = ["-m", "line"]       # text is lettering: bifin's classifier would take it for picture-style art
    chosen = []
    for name in args.preset or []:
        if name not in presets:
            raise bif.BifError("no preset '%s' (bidet --list-presets shows them)" % name)
        chosen.append(presets[name])
    for p in chosen:
        plan.bifin += p.bifin
        plan.ops += p.ops
        plan.bifout += p.bifout
    plan.bifin += shlex.split(args.bifin or "")
    plan.ops += shlex.split(args.bifop or "")
    plan.bifout += shlex.split(args.bifout or "")
    # colours: what is asked for, else dark or light as the terminal is; a preset's own colours come later and win
    dark = True if args.dark else (False if args.light else None)
    if dark is None and stdout_tty and not args.output:
        dark = dark_terminal(env)
    if args.ink or args.paper:                                            # asked for: last, so it wins
        plan.ops.append("theme:" + ",".join(k + "=" + v for k, v in (("ink", args.ink), ("paper", args.paper)) if v))
    elif dark is not None and not any(o.startswith("theme") for o in plan.ops):
        plan.ops.insert(0, DARK_THEME if dark else LIGHT_THEME)           # worked out: only if no preset chose colours
    # where the picture goes
    plan.output = args.output if args.output and args.output != "-" else None
    if args.output and args.output != "-":
        plan.fmt = format_for(args.output)
    elif args.output == "-":
        plan.fmt = "png"                                                  # asked for on standard output
    elif stdout_tty:
        plan.fmt = "sixel"
    else:
        plan.fmt = "png"
    if plan.fmt == "bif" and plan.is_bif and not plan.ops:
        raise bif.BifError("nothing to do: the input is a BIF and no preset or operation was asked for")
    # the size: asked for, else fitted to the terminal (SIXEL) or twice life size (a file)
    probe = _parse_flags(bifout.build_parser(), plan.bifout, "bifout flags")
    if args.width:
        plan.bifout += ["--width", str(args.width)]
    elif probe.scale is None and probe.width is None and probe.height is None:
        if plan.fmt == "sixel" and not plan.output:
            plan.bifout += ["--width", str(fit_width(pixels if pixels is not None else terminal_pixels(),
                                                     columns if columns is not None else terminal_columns()))]
        elif plan.fmt != "bif":                                           # a file: text fills 1000 px, art is drawn twice life size
            plan.bifout += ["--width", "1000"] if plan.literal is not None else ["--scale", "2"]
    return plan


# ---------------------------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------------------------
def read_input(plan):
    if plan.literal is not None:
        return (plan.literal + "\n").encode("utf-8")
    if plan.source:
        with open(plan.source, "rb") as f:
            return f.read()
    return sys.stdin.buffer.read()


def run(plan, data, notes=None):
    """Draw the plan: the bytes of the result (a PNG, SIXEL or BIF)."""
    notes = notes or bifop.Notes()
    if plan.is_bif:
        pic = bif.loads(data)
    else:
        a = _parse_flags(bifin.build_parser(), plan.bifin, "bifin flags")
        a.file = plan.source or "-"
        pic = bifin.convert(data, a.kind, **bifin.options_of(a))
    if plan.ops:
        pic = bifop.apply(pic, plan.ops, notes)
    if plan.fmt == "bif":
        return bif.dumps(pic)
    a = _parse_flags(bifout.build_parser(), plan.bifout, "bifout flags")
    buf = io.BytesIO()
    r = bifout.convert(pic, plan.fmt, buf, **bifout.render_options(a))
    notes.lines.extend(r.notes)
    return buf.getvalue()


def build_parser():
    ap = argparse.ArgumentParser(
        prog="bidet", description="Draw text or terminal art as a picture, in a style.",
        epilog="bidet is the simple front end of the BIDeT 4D tools bifin, bifop and bifout; "
               "`bidet -n ...` prints the pipeline of those it would run.")
    ap.add_argument("input", nargs="*", metavar="TEXT|FILE", help="text to draw, or a file (art, or a .bif); "
                    "with neither, standard input")
    ap.add_argument("-P", "--preset", action="append", metavar="NAME", help="a style; repeat to combine (-P arc -P matrix)")
    ap.add_argument("-l", "--list-presets", action="store_true", help="list the presets and exit")
    ap.add_argument("-o", "--output", metavar="FILE", help="write the picture here (.png, .six, .bif); '-' = standard output")
    ap.add_argument("-w", "--width", type=int, metavar="PX", help="draw this many pixels wide (default: the terminal's width, "
                    "or, for a file, 1000 for text and twice life size for art)")
    ap.add_argument("--ink", metavar="COLOR", help="colour of the lines")
    ap.add_argument("--paper", metavar="COLOR", help="colour of the page")
    ap.add_argument("--dark", action="store_true", help="draw for a dark background (light lines on black)")
    ap.add_argument("--light", action="store_true", help="draw for a light background (dark lines on white)")
    ap.add_argument("-t", "--text", action="store_true", help="the arguments are text, even if one names a file")
    ap.add_argument("-n", "--show-pipeline", action="store_true", help="print the bifin | bifop | bifout pipeline and do not run it")
    ap.add_argument("--bifin", metavar="FLAGS", help="extra flags for bifin, as one quoted string (a single flag: --bifin=--mono)")
    ap.add_argument("--bifop", metavar="OPS", help="extra operations for bifop, as one quoted string")
    ap.add_argument("--bifout", metavar="FLAGS", help="extra flags for bifout, as one quoted string (a single flag: --bifout=--ss=2)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-V", "--version", action="version", version="bidet " + VERSION)
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        presets = load_presets()
        if args.list_presets:
            width = max(len(n) for n in presets) if presets else 0
            for name, p in presets.items():
                print("%-*s  %s" % (width, name, p.description))
            return 0
        if args.dark and args.light:
            raise bif.BifError("--dark and --light together")
        plan = make_plan(args, presets)
        if args.show_pipeline:
            print(plan.shell())
            return 0
        if plan.fmt != "bif" and not plan.output and sys.stdout.isatty() and plan.fmt != "sixel":
            raise bif.BifError("will not write a %s to a terminal" % plan.fmt)
        notes = bifop.Notes()
        data = read_input(plan)
        blob = run(plan, data, notes)
    except (bif.BifError, ValueError, IOError) as e:
        sys.exit("bidet: %s" % e)
    for line in notes.lines:
        sys.stderr.write("bidet: %s\n" % line)
    if args.verbose:
        sys.stderr.write("bidet: %s\n" % plan.shell())
    if plan.output:
        with open(plan.output, "wb") as f:
            f.write(blob)
    else:
        sys.stdout.buffer.write(blob)
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
