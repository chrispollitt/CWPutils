#!/usr/bin/env python3
"""bifout: turn a BIF (BIDeT Intermediate Format) into a picture.

    bifout x.bif -o x.png                 PNG
    bifout x.bif -s                       SIXEL to the terminal (also the default on a terminal)
    unascii-or-whatever | bifout -o -     BIF from a pipe, PNG to a pipe

The picture is drawn at `--scale` pixels per canvas unit (or fitted into `--width` / `--height`), so
line art is as sharp as you ask for.  See BIF-SPEC.md for what a BIF holds and section 8 for how it is drawn.
Formats are registered in WRITERS (name -> function(rendering, file, transparent)); to add one, add one.
"""
from __future__ import print_function

import argparse
import io
import os
import sys

import bif
import bifrender
import bifsixel
import bifterm

VERSION = "0.1"
LIGHT_INK, DARK_INK = (235, 235, 235), (25, 25, 25)         # what the ink becomes where it would not show


# ---------------------------------------------------------------------------------------------
# Writers: function(rendering, fp, transparent) -> None
# ---------------------------------------------------------------------------------------------
def write_png(r, fp, transparent=False):
    from PIL import Image
    if transparent:
        img = Image.fromarray(r.rgba(), "RGBA")
    else:
        img = Image.fromarray(r.flatten(), "RGB")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    fp.write(buf.getvalue())


def write_sixel(r, fp, transparent=False):
    fp.write(bifsixel.encode(r.alpha, r.color, r.paper, transparent=transparent) + b"\n")


WRITERS = {
    "png": (write_png, (".png",)),
    "sixel": (write_sixel, (".six", ".sixel")),
}


def format_for(name, out_is_tty):
    """Choose a format from -f, else the output file's extension, else the terminal."""
    ext = os.path.splitext(name or "")[1].lower()
    for f, (_, exts) in WRITERS.items():
        if ext in exts:
            return f
    return "sixel" if out_is_tty else "png"


def convert(pic, fmt, fp, frame=0, transparent=False, **render_opts):
    """Render frame `frame` of a Picture and write it to `fp` as `fmt`.  Returns the Rendering."""
    if fmt not in WRITERS:
        raise bif.BifError("unknown output format %r (have: %s)" % (fmt, ", ".join(sorted(WRITERS))))
    r = bifrender.render(pic, frame=frame, **render_opts)
    WRITERS[fmt][0](r, fp, transparent)
    return r


def _color(s):
    from PIL import ImageColor
    try:
        return ImageColor.getrgb(s)[:3]
    except ValueError:
        sys.exit("bifout: bad colour '%s'" % s)


def build_parser():
    """bifout's command line (also used by bidet to read a preset's bifout flags)."""
    ap = argparse.ArgumentParser(prog="bifout", description="Draw a BIF as a PNG or SIXEL picture.")
    ap.add_argument("file", nargs="?", default="-", help="a .bif file (default: standard input)")
    ap.add_argument("-o", "--output", metavar="FILE", help="write here ('-' = standard output)")
    ap.add_argument("-f", "--format", choices=sorted(WRITERS), help="output format (default: from the file name; "
                    "sixel on a terminal, else png)")
    ap.add_argument("-s", "--sixel", action="store_true", help="same as -f sixel")
    ap.add_argument("--frame", type=int, default=0, metavar="N", help="which frame of an animation (default 0)")
    ap.add_argument("--scale", type=float, metavar="S", help="pixels per canvas unit (default 1)")
    ap.add_argument("--width", type=int, metavar="PX", help="fit the picture into this width")
    ap.add_argument("--height", type=int, metavar="PX", help="fit the picture into this height")
    ap.add_argument("--ss", type=int, metavar="N", help="supersampling of vector layers (default: automatic, up to 4)")
    ap.add_argument("--ink", metavar="COLOR", help="replace the palette's `ink` colour")
    ap.add_argument("--paper", metavar="COLOR", help="the page colour (default: the picture's, else white, "
                    "or black for light art)")
    ap.add_argument("--transparent", action="store_true", help="leave the page transparent (PNG alpha / SIXEL unpainted)")
    ap.add_argument("-b", "--background", metavar="auto|transparent|COLOR",
                    help="the page: a colour (as --paper), transparent, or auto: for SIXEL on a terminal, the terminal's own "
                         "background colour (asked with OSC 11), or transparent if it will not say, and the ink made light or dark "
                         "to show on it; anywhere else the picture's own page (default: the picture's)")
    ap.add_argument("--force", action="store_true", help="send SIXEL even if the terminal does not say it has it")
    ap.add_argument("--no-query", action="store_true", help="do not ask the terminal anything (also BIDET_NO_QUERY=1)")
    ap.add_argument("--layer", action="append", metavar="ID", help="draw only this layer id (repeatable)")
    ap.add_argument("--max-pixels", type=float, default=bifrender.DEFAULT_MAX_PIXELS, metavar="N",
                    help="largest picture to draw; bigger is drawn smaller (default %d)" % bifrender.DEFAULT_MAX_PIXELS)
    ap.add_argument("-t", "--truncated", action="store_true", help="draw what arrived of a file that ends early")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-V", "--version", action="version", version="bifout " + VERSION)
    return ap


def render_options(a):
    """The keyword arguments of convert() (and of bifrender.render) from parsed arguments."""
    bg = (a.background or "").strip().lower()
    paper = _color(a.paper) if a.paper else None
    if bg not in ("", "auto", "transparent"):
        paper = _color(a.background)
    return dict(frame=a.frame, transparent=a.transparent or bg == "transparent", scale=a.scale, width=a.width, height=a.height,
                ss=a.ss, ink=_color(a.ink) if a.ink else None, paper=paper,
                max_pixels=a.max_pixels, layers=set(a.layer) if a.layer else None)


def to_terminal(a, fmt, out_is_tty=True):
    """Is the picture SIXEL for standard output (not `-o FILE`)?  Then it is meant for the terminal, whether or not
    standard output is one right now (it may be a pipe to `less -R` or `cut`): the terminal is asked, like the
    old bidet's test-sixel did.  Callers that only ask on a real tty pass out_is_tty."""
    return fmt == "sixel" and out_is_tty and (not a.output or a.output == "-")


def ask_terminal(a, fmt, out_is_tty=True, env=None):
    """What the terminal says (bifterm.Reply), asking only if SIXEL is going to it; NOTHING otherwise."""
    if not to_terminal(a, fmt, out_is_tty) or a.no_query:
        return bifterm.NOTHING
    return bifterm.query(want_bg=(a.background or "").lower() == "auto", want_cell=False, env=env, debug=a.verbose)


def terminal_options(pic, a, opts, reply, env=None):
    """The render options for a picture that goes to a terminal that said `reply`: refuses SIXEL a terminal says it has
    not (unless --force), and settles `--background auto`: the terminal's colour for the page, or transparent if it
    would not say; the ink becomes light or dark if the page would swallow it."""
    env = os.environ if env is None else env
    if reply.asked and reply.sixel is not True and not (a.force or env.get("LSIX_FORCE_SIXEL_SUPPORT")):
        raise bif.BifError("your terminal does not report having SIXEL graphics support%s.  Try mintty, xterm -ti vt340, "
                           "mlterm, Windows Terminal or WezTerm; or --force to send it anyway, or -o FILE.png"
                           % ("" if reply.sixel is False else " (it did not answer)"))
    if (a.background or "").lower() != "auto":
        return opts
    opts = dict(opts)
    if reply.bg:
        opts["paper"], opts["transparent"] = tuple(reply.bg), False
        page = reply.bg
    else:
        opts["transparent"] = True                              # the terminal's own colour shows through
        page = (255, 255, 255) if bifterm.guess_dark(env) is False else (0, 0, 0)       # dark unless it says light
    inks = [e["rgb"] for e in pic.palette if e.get("role") == "ink"]
    if inks and not opts.get("ink") and abs(bifterm.luminance(inks[0]) - bifterm.luminance(page)) < 0.4:
        opts["ink"] = LIGHT_INK if bifterm.luminance(page) < 0.5 else DARK_INK
    return opts


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)

    if a.file == "-" and sys.stdin.isatty():
        ap.error("no input: give a .bif file or pipe one in")
    out_tty = sys.stdout.isatty()
    fmt = "sixel" if a.sixel else (a.format or format_for(a.output if a.output != "-" else None, out_tty and not a.output))
    if (not a.output or a.output == "-") and out_tty and fmt != "sixel":
        ap.error("will not write %s to a terminal: use -o FILE, -s for SIXEL, or a pipe" % fmt.upper())
    try:
        if a.file == "-":
            pic = bif.read(sys.stdin.buffer, allow_truncated=a.truncated)
        else:
            pic = bif.load(a.file, allow_truncated=a.truncated)
        buf = io.BytesIO()
        opts = render_options(a)
        if to_terminal(a, fmt):
            opts = terminal_options(pic, a, opts, ask_terminal(a, fmt))
        r = convert(pic, fmt, buf, **opts)
    except (bif.BifError, IOError) as e:
        sys.exit("bifout: %s" % e)
    for n in r.notes:
        sys.stderr.write("bifout: %s\n" % n)
    if a.verbose:
        sys.stderr.write("bifout: %dx%d px (%.3g x %.3g px per unit), %s, paper %s\n"
                         % (r.W, r.H, r.sx, r.sy, fmt, tuple(int(v) for v in r.paper)))
    if a.output and a.output != "-":
        with open(a.output, "wb") as f:
            f.write(buf.getvalue())
    else:
        sys.stdout.buffer.write(buf.getvalue())
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
