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
  * the terminal: it is asked whether it has SIXEL and what its background colour is (OSC 11); the page takes that
    colour, or is transparent if it will not say, and the lines are light or dark to show on it (--dark / --light,
    --ink / --paper, or a preset's colours, take over)

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
import bifgfx
import bifin
import bifop
import bifout
import bifterm

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
    """solid: the 3D look, as key=value words for bifop's extrude / spin / popout (material depth view ...);
    motion: what it does, `pop+hold+spin` / `spin` / `sway` / `pop`, then key=value words for it (turns=2);
    uses: names of presets that are applied first (a showpiece made of others)."""
    def __init__(self, name, description="", bifin_flags=None, ops=None, bifout_flags=None, sample="art", solid=None,
                 motion="", uses=None):
        self.name, self.description, self.sample = name, description, sample
        self.bifin, self.ops, self.bifout = list(bifin_flags or []), list(ops or []), list(bifout_flags or [])
        self.solid, self.motion, self.uses = list(solid or []), motion, list(uses or [])


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
                                       shlex.split(sec.get("bifout", "")), sec.get("sample", "art").strip(),
                                       shlex.split(sec.get("solid", "")), sec.get("motion", "").strip(),
                                       sec.get("uses", "").split())
            except ValueError as e:
                raise bif.BifError("%s: preset '%s': %s" % (path, name, e))
    return presets


def expand(names, presets, _seen=()):
    """The presets of `names` in order, each preceded by the ones it `uses` (a list of Preset)."""
    out = []
    for name in names:
        if name not in presets:
            raise bif.BifError("no preset '%s' (bidet --list-presets shows them)" % name)
        if name in _seen:
            raise bif.BifError("preset '%s' uses itself" % name)
        out += expand(presets[name].uses, presets, _seen + (name,))
        out.append(presets[name])
    return out


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


def check_preset(p, presets=None):
    """Raise BifError if a preset's recipe would not run: bad flags or operations, a 3D look or motion that bifop would
    refuse, or (with `presets`, all of them) a `uses` that is missing or goes round in a circle."""
    chain = expand([p.name], presets) if presets is not None else [p]
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
    for still in (False, True):                                                       # its 3D look and motion, as bifop operations
        try:
            spec = motion_op(build_parser().parse_args([]), chain, still)
            if spec:
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
    return bifterm.guess_dark(env)


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
        self.lettering = False        # the input is words to set in a font (given as text, or found to read as prose), not art
        self.is_bif = False
        self.bifin = []
        self.ops = []
        self.bifout = []
        self.fmt = "png"              # png | gif | bif, or for a terminal: auto | sixel | kitty | iterm | ansi | tek ...
        self.format = None            # the format that was asked for with --format (else it follows from where the picture goes)
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
            if self.format and not (self.output and format_for(self.output) == self.fmt):
                tail += ["-f", self.format]
            tail += ["-o", self.output or "-"] if (self.output or self.fmt == "png") else []
            out.append(tail)
        return out

    def shell(self):
        parts = [" ".join(shlex.quote(w) for w in st) for st in self.stages()]
        head = ""
        if self.literal is not None:
            head = "printf '%%s\\n' %s | " % shlex.quote(self.literal)
        return head + " | ".join(parts)


PROSE_PUNCTUATION = " .,;:!?'\"()-&%$"


def looks_like_prose(data):
    """Is this a few words (a title, a sentence), not art?  bifin's classifier takes a word for picture art and
    draws nothing, so bidet sets such input as lettering.  Art is made of | _ / \\ + = * ~ and the like, which prose
    does not use; shaded picture art is dense, a sentence has spaces."""
    if not isinstance(data, bytes) or not data.strip() or len(data) > 2000:
        return False
    try:
        text = data.decode("utf-8").strip("\r\n")
    except UnicodeDecodeError:
        return False
    lines = text.replace("\r\n", "\n").split("\n")
    if len(lines) > 12 or not all(c.isalnum() or c in PROSE_PUNCTUATION or c == "\n" for c in text.replace("\r", "")):
        return False
    body = text.replace("\n", "")
    if sum(c.isalnum() for c in body) * 2 < len(body.strip()):                   # ".,,::;;" is a texture, not words
        return False
    tokens = text.split()
    if max(len(t) for t in tokens) > 30:
        return False
    return len(body) < 12 or len(tokens) > 1 and sum(c == " " for c in body) * 20 >= len(body)


def format_for(path):
    """The format a file name asks for: .bif, or any of bifout's (.png, .gif, .six, .ans, .tek ...), else a PNG."""
    if os.path.splitext(path or "")[1].lower() == ".bif":
        return "bif"
    return bifout.format_for(path, False)


def for_terminal(fmt):
    """Is this a format that a terminal is sent (auto: whichever it can show)?"""
    return fmt == "auto" or fmt in bifout.TERMINAL_FORMATS


MOVE_OPS = {"pop": "popout", "spin": "spin", "sway": "sway"}


def _kvs(tokens, what):
    out = collections.OrderedDict()
    for t in tokens:
        k, eq, v = t.partition("=")
        if not (eq and k):
            raise bif.BifError("%s: '%s' is not key=value" % (what, t))
        out[k] = v
    return out


def motion_op(args, chosen=(), still=False):
    """The bifop operation for the 3D look and the motion, or None.  They come from the presets (`solid =`, `motion =`, later
    ones win) and from --3d / --spin / --sway / --pop / --material / --depth / --view / --turns / --fps, which win over
    them: bidet3d's animations, and the new one, the picture flat on the screen popping out of it.  A look without a motion is a
    still (`extrude`).  still=True: only the final pose of the motion, floating (for a contact sheet)."""
    solid, path, extras, have = collections.OrderedDict(), None, collections.OrderedDict(), False
    for p in chosen:
        if p.solid:
            solid.update(_kvs(p.solid, "preset '%s' solid" % p.name))
            have = True
        if p.motion:
            words = p.motion.split()
            path = [m for m in words[0].split("+") if m]
            extras = _kvs(words[1:], "preset '%s' motion" % p.name)
            have = True
    cli = bool(args.spin or args.sway is not None or args.pop)
    if cli:                                                                    # what was asked for replaces the presets' motion
        path, extras = [], collections.OrderedDict()
        if args.pop:
            path.append("pop")
        if args.spin or args.sway is not None:
            if args.pop:
                path.append("hold")
            path.append("spin" if args.spin else "sway")
    elif args.solid:                                                           # --3d: a still
        path, extras = [], collections.OrderedDict()
    if not (have or cli or args.solid):
        return None
    if args.material:
        solid["material"] = args.material
    if args.depth is not None:
        solid["depth"] = "%g" % args.depth
    if args.view:
        solid["view"] = args.view.replace(",", "+")
    if args.fps:
        solid["fps"] = "%g" % args.fps
    path = path or []
    if still or not path:
        if still and path:
            solid.setdefault("hover", "0.6")                                   # the pose it ends in: up off the screen
        return "extrude" + (":" + ",".join("%s=%s" % kv for kv in solid.items()) if solid else "")
    if args.turns is not None and "spin" in path:
        extras["turns"] = "%g" % args.turns
    if args.sway is not None and "sway" in path:
        extras["degrees"] = "%g" % args.sway
    kw = list(solid.items()) + list(extras.items())
    if len(path) == 1 and path[0] in MOVE_OPS:
        return MOVE_OPS[path[0]] + (":" + ",".join("%s=%s" % x for x in kw) if kw else "")
    return "motion:" + ",".join(["path=" + "+".join(path)] + ["%s=%s" % x for x in kw])


def make_plan(args, presets, env=None, stdout_tty=None, stdin_tty=None, columns=None, pixels=None, data=None, still=False):
    """Turn parsed command-line arguments into a Plan (nothing is drawn).  `data`: the bytes of a standard input
    already read, so that a few plain words can be told from art; a named file is looked into here."""
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
        with open(plan.source, "rb") as f:
            data = f.read(2001)
        plan.is_bif = data[:8] == bif.MAGIC
    elif len(words) == 1 and words[0] == "-" and not args.text:
        plan.stdin = True
    else:
        plan.literal = " ".join(words)
    # a literal is words to set in a font; so is a file or standard input of plain words, or when asked with -t
    # (the art classifier takes words for picture art and draws nothing); --art or an importer flag says otherwise
    chosen = expand(args.preset or [], presets)
    user_in = shlex.split(args.bifin or "") + [f for p in chosen for f in p.bifin]
    art_flags = any(f in ("-f", "--from", "-m", "--mode") or f.startswith("--from=") or f.startswith("--mode=") for f in user_in)
    if plan.literal is not None:
        plan.lettering = True
    elif not plan.is_bif and not args.art and not art_flags:
        plan.lettering = args.text or (data is not None and looks_like_prose(data))
    # the recipe: presets in the order asked for, then what was asked on the command line
    if plan.lettering:
        plan.bifin = ["-f", "lettering"]  # set in a font, not drawn as art
    for p in chosen:
        plan.bifin += p.bifin
        plan.ops += p.ops
        plan.bifout += p.bifout
    if args.font:
        plan.bifin += ["--face" if plan.lettering else "--font", args.font]                 # (the lettering's, or the art's)
    plan.bifin += shlex.split(args.bifin or "")
    plan.ops += shlex.split(args.bifop or "")
    mo = motion_op(args, chosen, still)
    if mo:
        plan.ops.append(mo)
    plan.bifout += shlex.split(args.bifout or "")
    # where the picture goes
    plan.output = args.output if args.output and args.output != "-" else None
    if args.format:
        plan.fmt = plan.format = args.format                              # asked for: it wins over the file name
    elif args.output and args.output != "-":
        plan.fmt = format_for(args.output)
    elif args.output == "-":
        plan.fmt = "png"                                                  # asked for on standard output
    elif stdout_tty:
        plan.fmt = "auto"                                                 # what the terminal can show: SIXEL if it has it
    else:
        plan.fmt = "png"
    # colours: what is asked for (--ink / --paper, last, so it wins; --dark / --light).  Else, on a terminal, bifout's
    # `-b auto`: the terminal's own background as the page (or transparent if it will not say) and ink that shows on
    # it.  A preset that chose colours keeps its own page.
    themed = any(o.startswith("theme") for o in plan.ops)
    dark = True if args.dark else (False if args.light else None)
    if args.ink or args.paper:
        plan.ops.append("theme:" + ",".join(k + "=" + v for k, v in (("ink", args.ink), ("paper", args.paper)) if v))
    elif dark is not None and not themed:
        plan.ops.insert(0, DARK_THEME if dark else LIGHT_THEME)
    elif for_terminal(plan.fmt) and not plan.fmt.startswith("tek") and not plan.output and not themed:
        own = _parse_flags(bifout.build_parser(), plan.bifout, "bifout flags")
        if not (own.background or own.paper or own.transparent):
            plan.bifout += ["--background", "auto"]
    if plan.fmt == "bif" and plan.is_bif and not plan.ops:
        raise bif.BifError("nothing to do: the input is a BIF and no preset or operation was asked for")
    # the size: asked for, else fitted to the terminal (SIXEL) or twice life size (a file)
    probe = _parse_flags(bifout.build_parser(), plan.bifout, "bifout flags")
    if args.width:
        plan.bifout += ["--width", str(args.width)]
    elif probe.scale is None and probe.width is None and probe.height is None:
        if for_terminal(plan.fmt) and not plan.fmt.startswith("tek") and not plan.output:
            plan.bifout += ["--width", str(fit_width(pixels if pixels is not None else terminal_pixels(),
                                                     columns if columns is not None else terminal_columns()))]
        elif plan.fmt != "bif":                                           # a file: text fills 1000 px, art is drawn twice life size
            if plan.fmt == "gif":                                         # (a GIF is a lot of pictures: smaller)
                plan.bifout += ["--width", "640"] if plan.lettering else ["--scale", "1"]
            else:
                plan.bifout += ["--width", "1000"] if plan.lettering else ["--scale", "2"]
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


def build_picture(plan, data, notes):
    """The plan's bifin and bifop stages: the Picture, before it is drawn."""
    if plan.is_bif:
        pic = bif.loads(data)
    else:
        a = _parse_flags(bifin.build_parser(), plan.bifin, "bifin flags")
        a.file = plan.source or "-"
        pic = bifin.convert(data, a.kind, **bifin.options_of(a))
    if not any(L.kind in ("vector", "raster") and L.get("visible", True) for f in pic.frames for L in f.layers):
        raise bif.BifError("nothing to draw: the input was read as %s and has no lines (a few words? try -t; art? try --art or "
                           "--bifin='-m line')" % pic.meta.get("mode", "art"))
    if plan.ops:
        pic = bifop.apply(pic, plan.ops, notes)
    return pic


def run(plan, data, notes=None):
    """Draw the plan: the bytes of the result (a PNG, SIXEL or BIF)."""
    notes = notes or bifop.Notes()
    pic = build_picture(plan, data, notes)
    if plan.fmt == "bif":
        return bif.dumps(pic)
    a = _parse_flags(bifout.build_parser(), plan.bifout, "bifout flags")
    buf = io.BytesIO()
    opts = bifout.render_options(a)
    if not plan.output and bifout.to_terminal(a, plan.fmt):                              # for the terminal: it is asked, as bifout does
        r, data = bifout.terminal_data(pic, a, plan.fmt, opts, tty=sys.stdout.isatty())   # (an animation is played there and then)
        notes.lines.extend(r.notes)
        return b"" if data is None else data
    r = bifout.convert(pic, plan.fmt, buf, fmt_opts=bifout.format_options(a), **opts)
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
    ap.add_argument("-o", "--output", metavar="FILE", help="write the picture here (.png, .gif, .six, .ans, .tek, .bif); '-' = standard "
                    "output.  A .vt file (a terminal session) is an animation: write it as .gif")
    ap.add_argument("--format", choices=sorted(bifout.WRITERS) + ["auto", "bif"], metavar="FORMAT",
                    help="the format of the picture, if the file name or the terminal should not decide: png, gif, sixel, kitty, iterm, "
                         "ansi (coloured text), tek (Tektronix strokes), tek-hatch, tek-dots, tek-contour, bif; on a terminal the "
                         "default is auto: SIXEL if the terminal has it, kitty or iTerm2 if that is what it is, else ansi")
    ap.add_argument("-w", "--width", type=int, metavar="PX", help="draw this many pixels wide (default: the terminal's width, "
                    "or, for a file, 1000 for text and twice life size for art)")
    ap.add_argument("-F", "--font", metavar="NAME", help="the font for text (a family, impact, serif, mono, script, ... or a .ttf file; "
                    "default sans)")
    ap.add_argument("--list-fonts", action="store_true", help="list the fonts found and exit")
    ap.add_argument("--ink", metavar="COLOR", help="colour of the lines")
    ap.add_argument("--paper", metavar="COLOR", help="colour of the page")
    ap.add_argument("--dark", action="store_true", help="draw for a dark background (light lines on black)")
    ap.add_argument("--light", action="store_true", help="draw for a light background (dark lines on white)")
    ap.add_argument("-t", "--text", action="store_true", help="the input is text to set in a font, even if it names a file "
                    "or is read from a pipe")
    ap.add_argument("--art", action="store_true", help="the input is terminal art, even if it looks like a few words")
    an = ap.add_argument_group("3D and animation (bifop's extrude, spin, sway, popout and motion; see `bifop --list`)")
    an.add_argument("--3d", dest="solid", action="store_true", help="extrude it: a still, lit, with a shadow on the screen")
    an.add_argument("--spin", action="store_true", help="turn it about the vertical axis: an animation (GIF, or played on a SIXEL terminal)")
    an.add_argument("--sway", nargs="?", type=float, const=25.0, default=None, metavar="DEG",
                    help="swing it this far each side and back (default 25)")
    an.add_argument("--pop", action="store_true",
                    help="2D to 3D: it starts flat on the screen and pops out of it (then --spin or --sway to go on)")
    an.add_argument("--material", metavar="NAME", help="the 3D face: rainbow chrome gold superhero sunset aqua blues purple slate "
                    "lime cornflower, or #rrggbb (default: the picture's colours)")
    an.add_argument("--depth", type=float, metavar="F", help="extrusion depth, as a fraction of the picture's shorter side (default 0.22)")
    an.add_argument("--view", metavar="YAW,PITCH,ROLL", help="the camera angles in degrees (default -20,8,0)")
    an.add_argument("--turns", type=float, metavar="N", help="--spin: how many turns (default 1)")
    an.add_argument("--fps", type=float, metavar="N", help="frames a second of an animation (default 15)")
    an.add_argument("--time-machine", action="store_true",
                    help="your text through banner (1983), FIGlet, TOIlet, BIDeT (2020), then popping out of the screen: "
                         "an animation (-o FILE.gif, or played on a SIXEL terminal); --stage-time SEC for each era")
    an.add_argument("--stage-time", type=float, default=3.0, metavar="SEC", help="--time-machine: seconds for each era (default 3)")
    ap.add_argument("-n", "--show-pipeline", action="store_true", help="print the bifin | bifop | bifout pipeline and do not run it")
    ap.add_argument("--bifin", metavar="FLAGS", help="extra flags for bifin, as one quoted string (a single flag: --bifin=--mono)")
    ap.add_argument("--bifop", metavar="OPS", help="extra operations for bifop, as one quoted string")
    ap.add_argument("--bifout", metavar="FLAGS", help="extra flags for bifout, as one quoted string (a single flag: --bifout=--ss=2)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-V", "--version", action="version", version="bidet " + VERSION)
    return ap


def time_machine(args):
    """--time-machine: build the show (timemachine.py) and write or play it."""
    import timemachine
    text = " ".join(args.input) if args.input else "BIDeT"
    cfg = timemachine.Settings(stage_time=args.stage_time, material=args.material or timemachine.Settings.material,
                               face=args.font or timemachine.Settings.face, turns=args.turns or timemachine.Settings.turns,
                               fps=args.fps or timemachine.Settings.fps)
    if args.depth is not None:
        cfg.depth = args.depth
    if args.view:
        cfg.view = args.view.replace(",", "+")
    if args.show_pipeline:
        print(timemachine.script(text, cfg, args.output or "time-machine.gif"))
        return 0
    tty = sys.stdout.isatty()
    if not args.output and not tty:
        raise bif.BifError("the time machine is an animation: write it with -o FILE.gif, or run it on a SIXEL terminal")
    pic = timemachine.build(text, cfg, say=(lambda m: sys.stderr.write("bidet: %s\n" % m)) if (args.verbose or tty) else None)
    if args.output and args.output != "-":
        fmt = format_for(args.output)
        if fmt == "bif":
            bif.save(pic, args.output)
        else:
            with open(args.output, "wb") as f:
                bifout.convert(pic, fmt, f, width=args.width)
        return 0
    a = bifout.build_parser().parse_args(["--background", "auto"] + (["-f", args.format] if args.format else []))
    opts = bifout.render_options(a)
    opts["width"] = args.width or fit_width(terminal_pixels(), terminal_columns())
    bifout.show(pic, a, a.format or "auto", opts, tty=True)
    return 0


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.list_fonts:
        import fonts
        print("\n".join(fonts.families()) or "no TrueType fonts found")
        return 0
    try:
        if args.time_machine:
            return time_machine(args)
        presets = load_presets()
        if args.list_presets:
            width = max(len(n) for n in presets) if presets else 0
            for name, p in presets.items():
                print("%-*s  %s" % (width, name, p.description))
            return 0
        if args.dark and args.light:
            raise bif.BifError("--dark and --light together")
        plan = make_plan(args, presets)
        data = None
        if plan.stdin:                                                    # read it now: words are told from art by looking
            data = read_input(plan)
            plan = make_plan(args, presets, data=data)
        if args.show_pipeline:
            print(plan.shell())
            return 0
        if plan.fmt != "bif" and not plan.output and sys.stdout.isatty() and not for_terminal(plan.fmt):
            raise bif.BifError("will not write a %s to a terminal: use -o FILE, or --format auto" % plan.fmt)
        notes = bifop.Notes()
        if data is None:
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
    elif sys.stdout.isatty() and blob.startswith(bifout.TEK_ERASE):       # a Tektronix picture on a terminal: xterm's Tek mode
        bifgfx.tek_emit(blob[len(bifout.TEK_ERASE):], sys.stdout.buffer, xterm=True, erase=True)
    else:
        sys.stdout.buffer.write(blob)
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
