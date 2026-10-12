#!/usr/bin/env python3
"""bifout: turn a BIF (BIDeT Intermediate Format) into a picture.

    bifout x.bif -o x.png                 PNG
    bifout x.bif -s                       SIXEL to the terminal (also the default on a terminal)
    bifout x.bif -o x.gif                 an animation (a BIF with several frames) as an animated GIF
    unascii-or-whatever | bifout -o -     BIF from a pipe, PNG to a pipe

The picture is drawn at `--scale` pixels per canvas unit (or fitted into `--width` / `--height`), so
line art is as sharp as you ask for.  See BIF-SPEC.md for what a BIF holds and section 8 for how it is drawn.
Formats are registered in WRITERS (name -> function(rendering, file, transparent)); to add one, add one.  A format that
can move is also in ANIMATED (name -> function(renderings, durations, file, transparent, loop, speed, samples)).
"""
from __future__ import print_function

import argparse
import io
import itertools
import os
import sys

import numpy as np

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


# GIF: at most 256 colours for the whole animation, so the palette is made once.  Line art is one colour over the page,
# and then the palette is the exact ramp between them (no quantizer, nothing to flicker); other art is quantized from
# a sample of its frames, without dithering (dither noise would shimmer on a still background).
GIF_TRANSPARENT = 255                                       # the palette index of "no colour" (--transparent)
GIF_SAMPLES = 12                                            # frames looked at to choose the palette
GIF_SAMPLE_PIXELS = 1500000                                 # ... and how much of them


def _padded(pal):
    pal = list(pal)[:768]
    return pal + [0] * (768 - len(pal))


class GifPalette(object):
    """The colours of one GIF, made from some of its Renderings, and the conversion of any Rendering to indices."""

    def __init__(self, samples, transparent=False):
        from PIL import Image
        self.transparent = transparent
        inks = set(tuple(int(v) for v in r.color_u8()) if r.uniform else None for r in samples)
        if len(inks) == 1 and None not in inks:
            self.ink = inks.pop()
            self.paper = tuple(int(round(v)) for v in samples[0].paper)
            self.levels = 254 if transparent else 255
            ramp = [[int(round(p + (i_ - p) * k / float(self.levels))) for p, i_ in zip(self.paper, self.ink)]
                    for k in range(self.levels + 1)]
            self.pimg = Image.new("P", (1, 1))
            self.pimg.putpalette(_padded(v for c in ramp for v in c))
        else:
            self.ink = None
            step = max(1, int(np.ceil(np.sqrt(len(samples) * samples[0].W * samples[0].H / float(GIF_SAMPLE_PIXELS)))))
            mont = np.concatenate([r.flatten()[::step, ::step] for r in samples], axis=0)
            q = Image.fromarray(np.ascontiguousarray(mont), "RGB").quantize(colors=255 if transparent else 256, method=0)
            q.putpalette(_padded(q.getpalette()))
            self.pimg = q

    @property
    def palette(self):
        return _padded(self.pimg.getpalette())

    def image(self, r):
        """A Rendering as a mode-P Image using this palette."""
        from PIL import Image
        alpha = np.clip(r.alpha, 0.0, 1.0)
        if self.ink is not None and r.uniform and tuple(int(v) for v in r.color_u8()) == self.ink:
            if self.transparent:
                idx = np.where(alpha >= 0.5, self.levels, GIF_TRANSPARENT).astype(np.uint8)
            else:
                idx = np.rint(alpha * self.levels).astype(np.uint8)
            im = Image.frombytes("P", (r.W, r.H), idx.tobytes())
        else:                                               # a colour the sample did not have: the nearest in the palette
            rgb = Image.fromarray(np.ascontiguousarray(r.flatten()), "RGB")
            try:
                im = rgb.quantize(palette=self.pimg, dither=0)
            except TypeError:                               # (Pillow before 7 cannot turn dithering off)
                im = rgb.quantize(palette=self.pimg)
            if self.transparent:
                idx = np.array(im)
                idx[alpha < 0.5] = GIF_TRANSPARENT
                im = Image.frombytes("P", (r.W, r.H), idx.tobytes())
        im.putpalette(self.palette)
        return im


def gif_delays(durations_ms, speed=1.0):
    """GIF counts in hundredths of a second: the times in ms, rounded from the running total so that 25 ms frames do not
    drift (2, 3, 2, 3 ...), and never under 2 (viewers play a shorter frame at 100 ms).  Returns milliseconds."""
    out, total, done = [], 0.0, 0
    for d in durations_ms:
        total += d / float(speed) / 10.0
        cs = max(2, int(round(total)) - done)
        done += cs
        out.append(cs * 10)
    return out


def write_gif_frames(renders, durations_ms, fp, transparent=False, loop=0, speed=1.0, samples=None):
    """An animated GIF.  renders: an iterator of Renderings (drawn one at a time; they all have the same size);
    samples: some of them, in a list, for the palette (default: the first); loop: how often it plays, 0 = forever."""
    renders = iter(renders)
    first = next(renders)
    pal = GifPalette(samples or [first], transparent)
    images = itertools.chain([pal.image(first)], (pal.image(r) for r in renders))
    head = next(images)
    kw = dict(save_all=True, append_images=images, duration=gif_delays(durations_ms, speed), optimize=False,
              disposal=2 if transparent else 1)
    if transparent:
        kw["transparency"] = GIF_TRANSPARENT
    if loop != 1:
        kw["loop"] = 0 if loop == 0 else max(0, loop - 1)
    buf = io.BytesIO()
    head.save(buf, "GIF", **kw)
    fp.write(buf.getvalue())


def write_gif(r, fp, transparent=False):
    write_gif_frames([r], [100], fp, transparent)


WRITERS = {
    "png": (write_png, (".png",)),
    "sixel": (write_sixel, (".six", ".sixel")),
    "gif": (write_gif, (".gif",)),
}
ANIMATED = {"gif": write_gif_frames}


def format_for(name, out_is_tty):
    """Choose a format from -f, else the output file's extension, else the terminal."""
    ext = os.path.splitext(name or "")[1].lower()
    for f, (_, exts) in WRITERS.items():
        if ext in exts:
            return f
    return "sixel" if out_is_tty else "png"


def convert(pic, fmt, fp, frame=None, transparent=False, speed=1.0, loop=None, **render_opts):
    """Render a Picture and write it to `fp` as `fmt`.  Returns the Rendering (of the first frame drawn).
    frame: which frame to draw; None = frame 0, or all of them if the format can move (GIF) and the picture has several.
    speed: times the frames go by faster; loop: how often an animation plays (0 = forever; None = as the picture says)."""
    if fmt not in WRITERS:
        raise bif.BifError("unknown output format %r (have: %s)" % (fmt, ", ".join(sorted(WRITERS))))
    if fmt in ANIMATED and frame is None and len(pic.frames) > 1:
        return convert_animation(pic, fmt, fp, transparent, speed, loop, **render_opts)
    r = bifrender.render(pic, frame=frame or 0, **render_opts)
    if frame is None and len(pic.frames) > 1:
        r.notes.append("the picture has %d frames and %s holds one: drew frame 0 (--frame N for another, -o FILE.gif for all)"
                       % (len(pic.frames), fmt.upper()))
    WRITERS[fmt][0](r, fp, transparent)
    return r


def convert_animation(pic, fmt, fp, transparent=False, speed=1.0, loop=None, **render_opts):
    """Every frame of a Picture, drawn alike (the page colour is settled by the first frame, which also fixes the size)."""
    if speed <= 0:
        raise bif.BifError("--speed must be positive")
    n = len(pic.frames)
    first = bifrender.render(pic, frame=0, **render_opts)
    opts = dict(render_opts, paper=first.paper)
    k = min(n, GIF_SAMPLES)
    picks = sorted(set(int(round(j * (n - 1) / float(k - 1))) for j in range(k)))
    drawn = dict((i, first if i == 0 else bifrender.render(pic, frame=i, **opts)) for i in picks)
    samples = [drawn[i] for i in picks]

    def frames():
        for i in range(n):
            yield drawn.pop(i) if i in drawn else bifrender.render(pic, frame=i, **opts)
    if loop is None:
        loop = int((pic.animation or {}).get("loop", 1))
    ANIMATED[fmt](frames(), [f.duration if f.duration is not None else 100 for f in pic.frames], fp, transparent,
                  loop, speed, samples=samples)
    return first


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
    ap.add_argument("--frame", type=int, default=None, metavar="N",
                    help="draw only this frame of an animation (default: all of them for GIF, else frame 0)")
    ap.add_argument("--speed", type=float, default=1.0, metavar="F", help="animation: play this many times faster (default 1)")
    ap.add_argument("--loop", type=int, default=None, metavar="N",
                    help="animation: how often it plays, 0 = forever (default: as the picture says)")
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
    return dict(frame=a.frame, speed=a.speed, loop=a.loop, transparent=a.transparent or bg == "transparent", scale=a.scale, width=a.width, height=a.height,
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
