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
import math
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


def _padded(pal, size=256):
    """pal as a flat list of exactly size*3 numbers: cut, or filled up with copies of the last colour (so that an
    index the quantizer picks from the unused tail is still the right colour)."""
    pal = list(pal)[:size * 3]
    if not pal:
        pal = [0, 0, 0]
    while len(pal) < size * 3:
        pal += pal[-3:]
    return pal


def _straight(r):
    """The colours of a Rendering as they are, not blended with any page: uint8 (H, W, 3)."""
    return np.ascontiguousarray(np.broadcast_to(r.color_u8(), (r.H, r.W, 3)))


class GifPalette(object):
    """The colours of one animation (at most `size`), made from some of its Renderings; and the conversion of any
    Rendering to indices into them.  Used for GIF (size 256, `transparent`: the last index is "no colour") and for SIXEL.
    `transparent`: the page is not known (it is the viewer's, or the terminal's), so nothing is blended with one: a pixel is
    painted in its own colour if it is at least half covered, else left clear (a soft shadow or an antialiased edge blended
    with a guessed white page would be a pale halo on a dark terminal)."""

    def __init__(self, samples, transparent=False, size=256):
        from PIL import Image
        self.transparent, self.size, self.trans = transparent, size, size - 1
        inks = set(tuple(int(v) for v in r.color_u8()) if r.uniform else None for r in samples)
        if len(inks) == 1 and None not in inks:
            self.ink = inks.pop()
            self.paper = tuple(int(round(v)) for v in samples[0].paper)
            self.levels = size - 2 if transparent else size - 1
            ramp = [[int(round(p + (i_ - p) * k / float(self.levels))) for p, i_ in zip(self.paper, self.ink)]
                    for k in range(self.levels + 1)]
            self.pimg = Image.new("P", (1, 1))
            self.pimg.putpalette(_padded((v for c in ramp for v in c), size))
        else:
            self.ink = None
            step = max(1, int(np.ceil(np.sqrt(len(samples) * samples[0].W * samples[0].H / float(GIF_SAMPLE_PIXELS)))))
            if transparent:                                                  # the colours of what will be painted, as they are
                px = [_straight(r)[::step, ::step][(np.clip(r.alpha, 0.0, 1.0) >= 0.5)[::step, ::step]] for r in samples]
                px = np.concatenate(px) if any(len(p_) for p_ in px) else np.zeros((1, 3), np.uint8)
                mont = px.reshape(-1, 1, 3)
            else:
                mont = np.concatenate([r.flatten()[::step, ::step] for r in samples], axis=0)
            q = Image.fromarray(np.ascontiguousarray(mont), "RGB").quantize(colors=size - 1 if transparent else size, method=0)
            q.putpalette(_padded(q.getpalette(), size))
            self.pimg = q

    def rgb(self):
        """The palette as a list of `size` (r, g, b)."""
        p = _padded(self.pimg.getpalette(), self.size)
        return [tuple(p[i:i + 3]) for i in range(0, self.size * 3, 3)]

    def indices(self, r):
        """A Rendering as a uint8 (H, W) array of indices into this palette."""
        from PIL import Image
        alpha = np.clip(r.alpha, 0.0, 1.0)
        if self.ink is not None and r.uniform and tuple(int(v) for v in r.color_u8()) == self.ink:
            if self.transparent:
                return np.where(alpha >= 0.5, self.levels, self.trans).astype(np.uint8)
            return np.rint(alpha * self.levels).astype(np.uint8)
        rgb = Image.fromarray(_straight(r) if self.transparent else np.ascontiguousarray(r.flatten()), "RGB")      # the nearest colour
        try:
            im = rgb.quantize(palette=self.pimg, dither=0)
        except TypeError:                                                    # (Pillow before 7 cannot turn dithering off)
            im = rgb.quantize(palette=self.pimg)
        idx = np.minimum(np.array(im), self.size - 1).astype(np.uint8)
        if self.transparent:
            idx[alpha < 0.5] = self.trans
        return idx

    def image(self, r):
        """A Rendering as a mode-P Image using this palette."""
        from PIL import Image
        idx = self.indices(r)
        im = Image.frombytes("P", (r.W, r.H), idx.tobytes())
        im.putpalette(_padded(self.pimg.getpalette(), self.size))
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


def schedule(pic, fps=None, speed=1.0):
    """[[frame index, milliseconds]] for playing the picture `speed` times as fast, with at most `fps` frames a second
    (the frame showing at each tick of that clock: equal neighbours merge, the total time is kept)."""
    if speed <= 0:
        raise bif.BifError("--speed must be positive")
    ms = [(f.duration if f.duration is not None else 100) / float(speed) for f in pic.frames]
    if not fps:
        return [[i, d] for i, d in enumerate(ms)]
    if fps <= 0:
        raise bif.BifError("--fps must be positive")
    ends, t = [], 0.0
    for d in ms:
        t += d
        ends.append(t)
    out, i = [], 0
    for k in range(max(1, int(round(t * fps / 1000.0)))):
        while i < len(ends) - 1 and ends[i] <= k * 1000.0 / fps:
            i += 1
        d = int(round((k + 1) * 1000.0 / fps)) - int(round(k * 1000.0 / fps))
        if out and out[-1][0] == i:
            out[-1][1] += d
        else:
            out.append([i, d])
    return out


def draw_all(pic, indexes, render_opts):
    """Draw the frames `indexes` of a picture alike: the page colour is settled by the first, which also fixes the size.
    Returns (first Rendering, an iterator of all of them one at a time, some of them for choosing a palette)."""
    first = bifrender.render(pic, frame=indexes[0], **render_opts)
    opts = dict(render_opts, paper=first.paper)
    n = len(indexes)
    k = min(n, GIF_SAMPLES)
    picks = [0] if k < 2 else sorted(set(int(round(j * (n - 1) / float(k - 1))) for j in range(k)))
    drawn = dict((p_, first if p_ == 0 else bifrender.render(pic, frame=indexes[p_], **opts)) for p_ in picks)
    samples = [drawn[p_] for p_ in picks]

    def frames():
        for p_ in range(n):
            yield drawn.pop(p_) if p_ in drawn else bifrender.render(pic, frame=indexes[p_], **opts)
    return first, frames(), samples


def convert(pic, fmt, fp, frame=None, transparent=False, speed=1.0, loop=None, fps=None, **render_opts):
    """Render a Picture and write it to `fp` as `fmt`.  Returns the Rendering (of the first frame drawn).
    frame: which frame to draw; None = frame 0, or all of them if the format can move (GIF) and the picture has several.
    speed: times the frames go by faster; loop: how often an animation plays (0 = forever; None = as the picture says);
    fps: at most this many frames a second."""
    if fmt not in WRITERS:
        raise bif.BifError("unknown output format %r (have: %s)" % (fmt, ", ".join(sorted(WRITERS))))
    if fmt in ANIMATED and frame is None and len(pic.frames) > 1:
        return convert_animation(pic, fmt, fp, transparent, speed, loop, fps, **render_opts)
    r = bifrender.render(pic, frame=frame or 0, **render_opts)
    if frame is None and len(pic.frames) > 1:
        r.notes.append("the picture has %d frames and %s holds one: drew frame 0 (--frame N for another, -o FILE.gif for all%s)"
                       % (len(pic.frames), fmt.upper(), "; on a terminal it is played" if fmt == "sixel" else ""))
    WRITERS[fmt][0](r, fp, transparent)
    return r


def convert_animation(pic, fmt, fp, transparent=False, speed=1.0, loop=None, fps=None, **render_opts):
    """Every frame of a Picture, written as one animation."""
    sched = schedule(pic, fps, speed)
    first, frames, samples = draw_all(pic, [i for i, _ in sched], render_opts)
    if loop is None:
        loop = int((pic.animation or {}).get("loop", 1))
    ANIMATED[fmt](frames, [d for _, d in sched], fp, transparent, loop, 1.0, samples=samples)
    return first


# ---------------------------------------------------------------------------------------------
# Playing an animation on the terminal (SIXEL): drawn and encoded once, then replayed on a steady clock
# ---------------------------------------------------------------------------------------------
def parse_cell(text):
    """'8x16' -> (8, 16)."""
    try:
        w, h = (int(v) for v in text.lower().split("x"))
        if w > 0 and h > 0:
            return w, h
    except ValueError:
        pass
    raise bif.BifError("--cell is WIDTHxHEIGHT in pixels, like 8x16")


def cell_size(opt=None, reply=None, fd=1, env=None):
    """(width, height) of a character cell in pixels: --cell, else what the terminal said (CSI 16 t), else the window size's
    pixels over its characters, else 10 x 20."""
    env = os.environ if env is None else env
    if opt:
        return parse_cell(opt)
    if reply is not None and reply.cell:
        return tuple(reply.cell)
    if env.get("BIDET_CELL"):
        return parse_cell(env["BIDET_CELL"])
    try:
        import fcntl
        import struct
        import termios
        rows, cols, xp, yp = struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8))
        if xp and yp and rows and cols:
            return max(1, xp // cols), max(1, yp // rows)
    except Exception:
        pass
    return 10, 20


def sixel_frames(renders, samples, transparent=False, erase="ech"):
    """SIXEL bytes of each Rendering, all on one palette (colours do not shimmer between frames; the page is exact).
    transparent: the page is left unpainted (palette index 0); erase "bg": and the terminal fills those pixels with its own
    background colour (SIXEL P2=0) instead of leaving what was there (see play_sixel)."""
    pal = GifPalette(samples, transparent, size=254)
    colours = [tuple(int(v) for v in samples[0].paper)] + pal.rgb()
    for r in renders:
        idx = pal.indices(r).astype(np.int32) + 1
        if transparent:
            idx[idx == pal.trans + 1] = 0                                    # "no colour" is index 0, which is left unpainted
        yield bifsixel._sixel_stream(np.minimum(idx, 254).astype(np.uint8), colours, transparent,
                                     p2=0 if (transparent and erase == "bg") else None)


def play_sixel(sixels, delays_ms, rows, cols, out, loops=0, transparent=False, clock=None, sleep=None, erase="ech"):
    """Replay encoded SIXEL frames on `out` until Ctrl-C (loops = 0) or that many times.  A terminal that cannot keep up
    skips frames, it does not slow the motion down.  Returns how many frames it sent.
    A transparent frame leaves some pixels unpainted, and those would show the frame before.  erase says how that is
    prevented: "ech" erases the character cells of the picture before each frame (what bidet3d did); "bg" needs nothing here:
    the frames were encoded so that the terminal fills those pixels with its background (sixel_frames); "none" does neither."""
    import bisect
    import time
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    ends, t = [], 0.0
    for d in delays_ms:
        t += d
        ends.append(t)
    total = ends[-1]
    clear = b""
    if transparent and erase == "ech":                  # unpainted pixels would show the frame before: erase the picture area first
        clear = b"\x1b8" + (b"\x1b[%dX\x1b[B" % cols) * (rows - 1) + b"\x1b[%dX" % cols      # (every row that was made room for)
    out.write(b"\n" * rows + b"\x1b[%dA" % rows + b"\x1b7\x1b[?25l")
    start, last, sent = clock(), -1, 0
    try:
        while True:
            now = (clock() - start) * 1000.0
            if loops and now >= total * loops:
                break
            pos = now % total
            k = min(bisect.bisect_right(ends, pos), len(sixels) - 1)
            if k == last:
                sleep(max(0.001, (ends[k] - pos) / 1000.0))
                continue
            last = k
            out.write(b"\x1b[?2026h\x1b8" + clear + b"\x1b8" + sixels[k] + b"\x1b[?2026l")        # (2026: no tearing)
            out.flush()
            sent += 1
    except KeyboardInterrupt:
        pass
    finally:
        out.write(b"\x1b[?2026l\x1b8" + b"\x1b[%dB" % rows + b"\x1b[?25h\n")
        out.flush()
    return sent


def play(pic, out, cell, frame=None, transparent=False, speed=1.0, loop=None, fps=None, progress=None, clock=None, sleep=None,
         erase="ech", **render_opts):
    """Draw every frame of an animated Picture, encode them as SIXEL on one palette, and play them on `out` (a terminal).
    cell: (width, height) of a character cell in pixels.  loop: 0 = until Ctrl-C (default: as the picture says).
    Returns the Rendering of the first frame."""
    sched = schedule(pic, fps, speed)
    first, frames, samples = draw_all(pic, [i for i, _ in sched], render_opts)
    sixels = []
    try:
        for n, six in enumerate(sixel_frames(frames, samples, transparent, erase)):
            sixels.append(six)
            if progress:
                progress(n + 1, len(sched))
    except KeyboardInterrupt:
        return first
    if loop is None:
        loop = int((pic.animation or {}).get("loop", 1))
    rows = int(math.ceil(first.H / float(cell[1]))) + 1
    cols = int(math.ceil(first.W / float(cell[0]))) + 1
    play_sixel(sixels, [d for _, d in sched], rows, cols, out, loop, transparent, clock, sleep, erase)
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
    ap.add_argument("--fps", type=float, default=None, metavar="N",
                    help="animation: at most this many frames a second (default: the picture's own; fewer = quicker to draw, smaller)")
    ap.add_argument("--erase", choices=["ech", "bg", "none"], default="ech",
                    help="animation on a terminal whose colour it did not say (transparent frames): how an earlier frame is kept from "
                         "showing through: ech = erase the picture's cells first (default), bg = the terminal fills unpainted pixels "
                         "with its own background (SIXEL P2=0), none.  If frames leave specks or lines behind, try bg")
    ap.add_argument("--cell", metavar="WxH", help="animation on a terminal: the size of a character cell in pixels, if the "
                    "terminal does not say (default: asked, else the window's, else 10x20; also BIDET_CELL)")
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
    return dict(frame=a.frame, speed=a.speed, loop=a.loop, fps=a.fps, transparent=a.transparent or bg == "transparent", scale=a.scale, width=a.width, height=a.height,
                ss=a.ss, ink=_color(a.ink) if a.ink else None, paper=paper,
                max_pixels=a.max_pixels, layers=set(a.layer) if a.layer else None)


def to_terminal(a, fmt, out_is_tty=True):
    """Is the picture SIXEL for standard output (not `-o FILE`)?  Then it is meant for the terminal, whether or not
    standard output is one right now (it may be a pipe to `less -R` or `cut`): the terminal is asked, like the
    old bidet's test-sixel did.  Callers that only ask on a real tty pass out_is_tty."""
    return fmt == "sixel" and out_is_tty and (not a.output or a.output == "-")


def ask_terminal(a, fmt, out_is_tty=True, env=None, want_cell=False):
    """What the terminal says (bifterm.Reply), asking only if SIXEL is going to it; NOTHING otherwise.  want_cell: also how
    big a character cell is (an animation needs it to know how many lines it takes)."""
    if not to_terminal(a, fmt, out_is_tty) or a.no_query:
        return bifterm.NOTHING
    return bifterm.query(want_bg=(a.background or "").lower() == "auto", want_cell=want_cell, env=env, debug=a.verbose)


def plays(pic, a, fmt, out_tty=True):
    """Is this an animation that goes to the terminal as SIXEL, to be played?  (Not with --frame, not into a file or a pipe.)"""
    return len(pic.frames) > 1 and a.frame is None and to_terminal(a, fmt, out_tty)


def progress_on_stderr(done, total):
    if sys.stderr.isatty():
        sys.stderr.write("\rbifout: drawing frame %d of %d" % (done, total) + ("\n" if done == total else ""))
        sys.stderr.flush()


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
        animated = plays(pic, a, fmt, out_tty)
        if to_terminal(a, fmt):
            reply = ask_terminal(a, fmt, want_cell=animated)
            opts = terminal_options(pic, a, opts, reply)
        if animated:                                             # play it: there is no file to write
            r = play(pic, sys.stdout.buffer, cell_size(a.cell, reply), progress=progress_on_stderr, erase=a.erase, **opts)
            for n in r.notes:
                sys.stderr.write("bifout: %s\n" % n)
            return
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
