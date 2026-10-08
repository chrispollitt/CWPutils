#!/usr/bin/env python3
"""bifin: turn terminal art into a BIF (BIDeT Intermediate Format).

    bifin cow.txt -o cow.bif              ASCII / ANSI / Unicode art, UTF-8 or DOS (CP437), SAUCE read
    cowsay hi | bifin | bifout -s         through a pipe, to SIXEL on the terminal
    echo Hello | bifin -f lettering --font impact --size 120 | bifout -s      a string set in a font

The same readings as unascii (-m line | tone | mix | ansi-block ...), but the result is vectors and
rasters, not pixels: strokes and letters stay sharp at any `bifout --scale`, the colours are a palette
a manipulator can change, and the character grid is kept in the file (hidden `cells` layer).
`-f lettering` is the other importer: not art but a string typeset in a proportional font (bifin --list-fonts).
Importers are registered in READERS (name -> function(data, options) -> bif.Picture).
"""
from __future__ import print_function

import argparse
import os
import sys

import bif
import bifin_lettering
import bifin_text
import fonts

VERSION = "0.1"


def sniff(data):
    """What the input is: 'bif', 'png', 'jpeg', 'gif', 'sixel', 'svg' or 'text'."""
    if data[:8] == bif.MAGIC:
        return "bif"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:2] == b"\x1bP" and b"q" in data[:40]:
        return "sixel"
    if data.lstrip()[:5] in (b"<?xml", b"<svg ") or data.lstrip()[:4] == b"<svg":
        return "svg"
    return "text"


def read_text(data, **options):
    options.pop("lettering", None)                                  # (the other importer's options)
    return bifin_text.import_text(data, **options)


def read_lettering(data, **options):
    """A string set in a font (the options are bifin's: `lettering` holds this importer's, ink / paper / name are shared)."""
    kw = dict(options.get("lettering") or {})
    if options.get("ink"):
        kw["ink"] = options["ink"]
    if options.get("paper"):
        kw["paper"] = options["paper"]
    kw["name"] = options.get("name")
    return bifin_lettering.lettering(data.decode("utf-8", "replace"), **kw)


READERS = {"text": read_text, "lettering": read_lettering}


def convert(data, kind=None, **options):
    """Bytes of any supported input -> bif.Picture.  kind: force an importer by name (default: sniff)."""
    kind = kind or sniff(data)
    if kind == "bif":
        raise bif.BifError("the input is already a BIF")
    if kind not in READERS:
        raise bif.BifError("no importer for %s input yet (have: %s)" % (kind, ", ".join(sorted(READERS))))
    return READERS[kind](data, **options)


def _color(s):
    from PIL import ImageColor
    try:
        return ImageColor.getrgb(s)[:3]
    except ValueError:
        sys.exit("bifin: bad colour '%s'" % s)


def build_parser():
    """bifin's command line (also used by bidet to read a preset's bifin flags)."""
    ap = argparse.ArgumentParser(prog="bifin", description="Turn terminal art into a BIF.")
    ap.add_argument("file", nargs="?", default="-", help="art file (default: standard input)")
    ap.add_argument("-o", "--output", metavar="FILE", help="write the BIF here (default: standard output)")
    ap.add_argument("-f", "--from", dest="kind", choices=sorted(READERS), help="input kind (default: detected)")
    ap.add_argument("-m", "--mode", choices=["auto", "lineart", "ansi-block", "block", "line", "tone", "mix"], default="auto",
                    help="lineart: line drawing (cowsay, figlet; picture-style art is outlined); ansi-block: "
                         "block/graphic-character art as the coloured picture it is; auto picks one (default). "
                         "line, tone, mix: force one lineart method")
    ap.add_argument("-c", "--cell", type=int, default=12, metavar="PX",
                    help="nominal width of one character cell, in the file's units (default 12)")
    ap.add_argument("-a", "--aspect", type=float, default=2.0, help="cell height / width (default 2.0)")
    ap.add_argument("-w", "--weight", type=float, default=1.0, help="pen thickness (default 1)")
    ap.add_argument("-j", "--join", type=float, default=1.0, metavar="CELLS",
                    help="line mode: join stroke ends this close (cell widths, default 1; 0 = never)")
    ap.add_argument("--no-round", action="store_true", help="line mode: no smoothing, keep every corner sharp")
    ap.add_argument("--spline", type=float, default=0.6, metavar="F",
                    help="line mode: spline smoothing of joined strokes, in cell widths (default 0.6; 0 = only round the corners)")
    ap.add_argument("--shade", default="X", metavar="CHARS",
                    help="line mode: runs of these characters are shading and get hatched (default X; '' = none)")
    ap.add_argument("--text-bold", type=float, default=0.25, metavar="F",
                    help="line mode: how much letters thicken with --weight above 1.2 (default 0.25; 0 = never)")
    ap.add_argument("--hatch", type=float, default=1.0, metavar="F", help="line mode: spacing of the hatching (default 1)")
    ap.add_argument("--smooth", type=float, default=None,
                    help="tone: blur in dot pitches (default 0.7); ansi-block: softening of the pixels (default 0.12, 0 = crisp)")
    ap.add_argument("--detail", type=float, default=0.12, help="tone: smallest tonal step that gets an outline (0..1, default 0.12)")
    ap.add_argument("--scale", type=float, default=0.4, help="tone: finest outline feature in dot pitches (default 0.4)")
    ap.add_argument("--levels", type=int, default=3, help="tone: contour lines through the shading (default 3, 0 = outlines only)")
    ap.add_argument("--dark", action="store_true", default=None,
                    help="tone: the art is light on dark (default colours); on by itself when the art uses colour")
    ap.add_argument("--color", "--colour", dest="color", choices=["auto", "on", "off"], default="auto",
                    help="keep the ANSI colours: auto = if the art has any (default), on, off")
    ap.add_argument("--mono", dest="color", action="store_const", const="off", help="one colour (the palette's ink)")
    ap.add_argument("--invert", action="store_true", help="tone: outline the negative")
    ap.add_argument("--ink", default=None, help="the ink colour in the palette (default black; light grey for colour block art)")
    ap.add_argument("--paper", default=None, help="the page colour in the palette (default white; black for colour block art)")
    ap.add_argument("--font", help="art: the monospace TrueType font, a file or a name (default: DejaVu Sans Mono, Consolas, ...); "
                    "-f lettering: the same as --face")
    ap.add_argument("--face", help="-f lettering: the font to set the text in, a file, a family (impact, 'Times New Roman'), a "
                    "generic (sans, serif, mono, script...) or several joined with commas (default sans).  Art ignores it, "
                    "so a recipe can ask for a face without breaking the art it is used on")
    lt = ap.add_argument_group("lettering (-f lettering): a string set in a font")
    lt.add_argument("--size", type=float, default=100.0, metavar="PX", help="font size, the units of the picture (default 100)")
    lt.add_argument("--spacing", type=float, default=0.0, metavar="EM", help="extra space between letters, in ems (default 0)")
    lt.add_argument("--line-height", type=float, default=None, metavar="EM", help="distance between lines, in ems (default: the font's)")
    lt.add_argument("--align", choices=["left", "center", "right"], default="left", help="alignment of several lines (default left)")
    lt.add_argument("--wrap", type=float, default=0.0, metavar="PX", help="break lines at spaces to fit this width (default: never)")
    lt.add_argument("--bold", action="store_true", help="a bold face (faked with an outline if the family has none)")
    lt.add_argument("--italic", action="store_true", help="an italic face (faked with a slant if the family has none)")
    lt.add_argument("--margin", type=float, default=0.15, metavar="EM", help="space round the letters, in ems (default 0.15)")
    ap.add_argument("--list-fonts", action="store_true", help="list the font families found and exit")
    ap.add_argument("--no-outlines", action="store_true", help="letters as a raster layer, as unascii draws them, not vector outlines")
    ap.add_argument("--tone-raster", action="store_true", help="tone: the outlines as a raster layer, as unascii draws them, not traced vector lines")
    ap.add_argument("--encoding", help="input encoding (default: UTF-8, else CP437)")
    ap.add_argument("--cols", type=int, default=0, help="wrap column for .ANS art (default: from SAUCE, else 80 for .ans, else none)")
    ap.add_argument("--rows", type=int, default=24, help="screen height for cursor addressing and scroll regions (default 24)")
    ap.add_argument("--no-crop", action="store_true", help="keep the margin around the drawing")
    ap.add_argument("--no-cells", action="store_true", help="do not keep the character grid in the file")
    ap.add_argument("--keep-source", action="store_true", help="store the input itself in the file (srce chunk)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-V", "--version", action="version", version="bifin " + VERSION)
    return ap


def options_of(a):
    """The importer's options (bifin_text.Options fields, and `lettering` for the other importer) from parsed arguments."""
    art_font = a.font
    if art_font and a.kind != "lettering" and not os.path.isfile(art_font):          # a name will do for the art's font too
        try:
            art_font = fonts.find(art_font)
        except fonts.FontNotFound as e:
            raise bif.BifError(str(e))
    options = dict(mode=a.mode, cell_w=a.cell, aspect=a.aspect, weight=a.weight, join=a.join * 1.0 if a.join > 0 else 0.0,
                   round_lines=not a.no_round, spline=a.spline, shade=a.shade, hatch=a.hatch, text_bold=a.text_bold,
                   smooth=a.smooth, detail=a.detail, scale=a.scale, levels=a.levels, dark=a.dark, invert=a.invert,
                   font=art_font, rows=a.rows, color=a.color, cols=a.cols, crop=not a.no_crop, verbose=a.verbose,
                   outlines=not a.no_outlines, tone_vectors=not a.tone_raster, cells=not a.no_cells, keep_source=a.keep_source,
                   name=None if a.file == "-" else a.file, encoding=a.encoding,
                   lettering=dict(font=a.face or a.font, size=a.size, spacing=a.spacing, line_height=a.line_height, align=a.align,
                                  wrap=a.wrap, bold=a.bold, italic=a.italic, margin=a.margin))
    if a.ink:
        options["ink"] = _color(a.ink)
    if a.paper:
        options["paper"] = _color(a.paper)
    return options


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.list_fonts:
        fams = fonts.families()
        print("\n".join(fams) if fams else "no TrueType fonts found")
        return

    if a.file == "-":
        if sys.stdin.isatty():
            ap.error("no input: give a file or pipe the art in")
        data = sys.stdin.buffer.read()
    else:
        try:
            with open(a.file, "rb") as f:
                data = f.read()
        except IOError as e:
            sys.exit("bifin: %s" % e)
    if not a.output and sys.stdout.isatty():
        ap.error("will not write a BIF to a terminal: use -o FILE, or pipe it into bifout")
    try:
        options = options_of(a)
        pic = convert(data, a.kind, **options)
        blob = bif.dumps(pic)
    except (bif.BifError, ValueError) as e:
        sys.exit("bifin: %s" % e)
    if a.output and a.output != "-":
        with open(a.output, "wb") as f:
            f.write(blob)
    else:
        sys.stdout.buffer.write(blob)
        sys.stdout.buffer.flush()
    if a.verbose:
        sys.stderr.write("bifin: %s, %d layer(s), %d bytes\n" % (pic, len(pic.layers), len(blob)))


if __name__ == "__main__":
    main()
