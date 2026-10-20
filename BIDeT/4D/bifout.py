#!/usr/bin/env python3
"""bifout: turn a BIF (BIDeT Intermediate Format) into a picture.

    bifout x.bif -o x.png                 PNG
    bifout x.bif                          on a terminal: what it can show (SIXEL, kitty, iTerm2, else coloured text)
    bifout x.bif -s                       SIXEL to the terminal
    bifout x.bif -f kitty                 the kitty graphics protocol; -f iterm, -f ansi (coloured Unicode text)
    bifout x.bif -f tek                   Tektronix vectors, from the picture's own paths (-f tek-hatch, tek-dots, tek-contour)
    bifout x.bif -o x.gif                 an animation (a BIF with several frames) as an animated GIF
    unascii-or-whatever | bifout -o -     BIF from a pipe, PNG to a pipe

The picture is drawn at `--scale` pixels per canvas unit (or fitted into `--width` / `--height`), so
line art is as sharp as you ask for.  See BIF-SPEC.md for what a BIF holds and section 8 for how it is drawn.
Formats are registered in WRITERS (name -> function(rendering, file, transparent, **options)); to add one, add one.  A format
that can move is also in ANIMATED (name -> function(renderings, durations, file, transparent, loop, speed, samples)).  The
formats that are not images in a file (kitty, iTerm2, ANSI art, Tektronix) are in bifgfx.py.
"""
from __future__ import print_function

import argparse
import io
import itertools
import math
import os
import shutil
import sys

import numpy as np

import bif
import bifdiag
import bifgfx
import bifrender
import bifsixel
import bifterm

VERSION = "0.1"
LIGHT_INK, DARK_INK = (235, 235, 235), (25, 25, 25)         # what the ink becomes where it would not show


# ---------------------------------------------------------------------------------------------
# Writers: function(rendering, fp, transparent) -> None
# ---------------------------------------------------------------------------------------------
def png_bytes(r, transparent=False):
    from PIL import Image
    if transparent:
        img = Image.fromarray(r.rgba(), "RGBA")
    else:
        img = Image.fromarray(r.flatten(), "RGB")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def write_png(r, fp, transparent=False, **options):
    fp.write(png_bytes(r, transparent))


def write_sixel(r, fp, transparent=False, **options):
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


def write_gif(r, fp, transparent=False, **options):
    write_gif_frames([r], [100], fp, transparent)


# The formats of bifgfx: a PNG in an escape sequence (kitty, iTerm2), coloured text, Tektronix vectors.  `options` come
# from format_options(): cols, rows, glyphs, colors, aspect, term, tek_invert; a writer takes what it needs.
def write_kitty(r, fp, transparent=True, cols=None, rows=None, **options):
    fp.write(bifgfx.kitty_sequence(png_bytes(r, transparent), cols, rows) + b"\n")


def write_iterm(r, fp, transparent=True, cols=None, rows=None, **options):
    fp.write(bifgfx.iterm_sequence(png_bytes(r, transparent), cols, rows) + b"\n")


def ansi_geometry(r, cols=None, rows=None, aspect=2.0, term=(80, 24)):
    """(cols, rows) in characters for a rendering."""
    return bifgfx.ansi_size(r.W, r.H, cols, rows, aspect, term[0], term[1])


def write_ansi(r, fp, transparent=False, cols=None, rows=None, glyphs="blocks", colors=24, aspect=2.0, term=(80, 24), **options):
    """Coloured Unicode text, a line to a row of characters.  A page that is not transparent is filled in (the picture's own,
    or the --paper); transparent leaves the terminal's background showing."""
    cols, rows = ansi_geometry(r, cols, rows, aspect, term)
    page = None if transparent else tuple(int(v) for v in r.paper)
    fp.write(bifgfx.ansi_art(r.rgba(), cols, rows, glyphs, colors, page))


TEK_ERASE = b"\x1b\x0c"                         # clears the Tektronix screen: first in every stream


def _tek_writer(mode):
    """mode: "vector" (the picture's own paths, or hatching if it has none), or hatch / dots / contour (from the pixels)."""
    def write(r, fp, transparent=False, pic=None, frame=0, tek_invert=False, **options):
        body = bifgfx.tek_vectors(pic, frame) if (mode == "vector" and pic is not None) else None
        if body is None:
            if mode == "vector":
                r.notes.append("no vector layer to draw as strokes: drawn as hatching (tek-hatch)")
            rgba = r.rgba()
            if r.uniform:                                   # one colour of ink, whatever it is: the coverage is the ink
                rgba[..., :3] = 255
            body = bifgfx.tek_raster(rgba, "hatch" if mode == "vector" else mode, invert=tek_invert)[0]
        fp.write(TEK_ERASE + body)
    return write


WRITERS = {
    "png": (write_png, (".png",)),
    "sixel": (write_sixel, (".six", ".sixel")),
    "gif": (write_gif, (".gif",)),
    "kitty": (write_kitty, ()),
    "iterm": (write_iterm, ()),
    "ansi": (write_ansi, (".ans", ".ansi")),
    "tek": (_tek_writer("vector"), (".tek",)),
    "tek-hatch": (_tek_writer("hatch"), ()),
    "tek-dots": (_tek_writer("dots"), ()),
    "tek-contour": (_tek_writer("contour"), ()),
}
ANIMATED = {"gif": write_gif_frames}
TERMINAL_FORMATS = ("sixel", "kitty", "iterm", "ansi", "tek", "tek-hatch", "tek-dots", "tek-contour")      # what a terminal can be sent
PLAYABLE = ("sixel", "ansi")                                                 # ... and of those, what plays an animation


def format_for(name, out_is_tty):
    """Choose a format from -f, else the output file's extension, else the terminal."""
    ext = os.path.splitext(name or "")[1].lower()
    for f, (_, exts) in WRITERS.items():
        if ext in exts:
            return f
    return "auto" if out_is_tty else "png"


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


def draw_all(pic, indexes, render_opts, progress=None):
    """Draw the frames `indexes` of a picture alike: the page colour is settled by the first, which also fixes the size.
    Returns (first Rendering, an iterator of all of them one at a time, some of them for choosing a palette).
    progress(done, total): told as each frame of the iterator is drawn."""
    with bifdiag.stage("draw sample frames"):
        first = bifrender.render(pic, frame=indexes[0], **render_opts)
        opts = dict(render_opts, paper=first.paper)
        n = len(indexes)
        k = min(n, GIF_SAMPLES)
        picks = [0] if k < 2 else sorted(set(int(round(j * (n - 1) / float(k - 1))) for j in range(k)))
        drawn = dict((p_, first if p_ == 0 else bifrender.render(pic, frame=indexes[p_], **opts)) for p_ in picks)
        samples = [drawn[p_] for p_ in picks]

    def frames():
        for p_ in range(n):
            r = drawn.pop(p_) if p_ in drawn else bifrender.render(pic, frame=indexes[p_], **opts)
            if progress:
                progress(p_ + 1, n)
            yield r
    return first, frames(), samples


def convert(pic, fmt, fp, frame=None, transparent=False, speed=1.0, loop=None, fps=None, fmt_opts=None, **render_opts):
    """Render a Picture and write it to `fp` as `fmt`.  Returns the Rendering (of the first frame drawn).
    frame: which frame to draw; None = frame 0, or all of them if the format can move (GIF) and the picture has several.
    speed: times the frames go by faster; loop: how often an animation plays (0 = forever; None = as the picture says);
    fps: at most this many frames a second.  fmt_opts: what the format itself takes (format_options())."""
    if fmt not in WRITERS:
        raise bif.BifError("unknown output format %r (have: %s)" % (fmt, ", ".join(sorted(WRITERS))))
    bifdiag.step("bifout")
    if fmt in ANIMATED and frame is None and len(pic.frames) > 1:
        with bifdiag.stage("bifout %s animation" % fmt):
            return convert_animation(pic, fmt, fp, transparent, speed, loop, fps, **render_opts)
    with bifdiag.stage("bifout draw"):
        r = bifrender.render(pic, frame=frame or 0, **render_opts)
    bifdiag.debug("drew %dx%d px, %.3g x %.3g px per unit" % (r.W, r.H, r.sx, r.sy))
    if frame is None and len(pic.frames) > 1:
        r.notes.append("the picture has %d frames and %s holds one: drew frame 0 (--frame N for another, -o FILE.gif for all%s)"
                       % (len(pic.frames), fmt.upper(), "; on a terminal it is played" if fmt in PLAYABLE else ""))
    with bifdiag.stage("bifout write %s" % fmt):
        WRITERS[fmt][0](r, fp, transparent, pic=pic, frame=frame or 0, **(fmt_opts or {}))
    return r


def convert_animation(pic, fmt, fp, transparent=False, speed=1.0, loop=None, fps=None, **render_opts):
    """Every frame of a Picture, written as one animation."""
    sched = schedule(pic, fps, speed)
    bifdiag.debug("%d frames of %d to draw" % (len(sched), len(pic.frames)))
    first, frames, samples = draw_all(pic, [i for i, _ in sched], render_opts, progress=progress_on_stderr)
    if loop is None:
        loop = int((pic.animation or {}).get("loop", 1))
    with bifdiag.stage("draw and write frames"):
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
         erase="ech", fmt="sixel", fmt_opts=None, **render_opts):
    """Draw every frame of an animated Picture, encode them (SIXEL on one palette, or coloured text) and play them on `out`
    (a terminal).  cell: (width, height) of a character cell in pixels.  loop: 0 = until Ctrl-C (default: as the picture
    says).  fmt: "sixel" or "ansi".  Returns the Rendering of the first frame."""
    sched = schedule(pic, fps, speed)
    first, frames, samples = draw_all(pic, [i for i, _ in sched], render_opts)
    encoded = []
    if fmt == "ansi":                                   # text: the same size for every frame, the picture's own page if opaque
        fo = fmt_opts or {}
        cols, text_rows = ansi_geometry(first, fo.get("cols"), fo.get("rows"), fo.get("aspect", 2.0), fo.get("term", (80, 24)))
        page = None if transparent else tuple(int(v) for v in first.paper)
        enc = (bifgfx.ansi_art(r.rgba(), cols, text_rows, fo.get("glyphs", "blocks"), fo.get("colors", 24), page) for r in frames)
        rows, transparent, erase = text_rows + 1, False, "none"      # (every cell is written: nothing to erase)
    elif fmt == "sixel":
        enc = sixel_frames(frames, samples, transparent, erase)
        rows = int(math.ceil(first.H / float(cell[1]))) + 1
        cols = int(math.ceil(first.W / float(cell[0]))) + 1
    else:
        raise bif.BifError("%s cannot play an animation (sixel and ansi can)" % fmt)
    try:
        with bifdiag.stage("draw and encode frames"):
            for n, frame_bytes in enumerate(enc):
                encoded.append(frame_bytes)
                if progress:
                    progress(n + 1, len(sched))
    except KeyboardInterrupt:
        return first
    if loop is None:
        loop = int((pic.animation or {}).get("loop", 1))
    with bifdiag.quiet():                                   # (the terminal is the picture's now)
        play_sixel(encoded, [d for _, d in sched], rows, cols, out, loop, transparent, clock, sleep, erase)
    return first


def _color(s):
    from PIL import ImageColor
    try:
        return ImageColor.getrgb(s)[:3]
    except ValueError:
        sys.exit("bifout: bad colour '%s'" % s)


def build_parser():
    """bifout's command line (also used by bidet to read a preset's bifout flags)."""
    ap = argparse.ArgumentParser(prog="bifout", description="Draw a BIF as a picture: PNG, GIF, SIXEL, kitty, iTerm2, coloured "
                                 "text or Tektronix vectors.")
    ap.add_argument("file", nargs="?", default="-", help="a .bif file (default: standard input)")
    ap.add_argument("-o", "--output", metavar="FILE", help="write here ('-' = standard output)")
    ap.add_argument("-f", "--format", choices=sorted(WRITERS) + ["auto"],
                    help="output format (default: from the file name; on a terminal auto, else png).  auto: what the terminal can "
                         "show: kitty or iTerm2 if the environment says so, else SIXEL if the terminal reports it, else ansi.  "
                         "tek: Tektronix strokes from the picture's own paths; tek-hatch, tek-dots, tek-contour: from its pixels")
    ap.add_argument("-s", "--sixel", action="store_true", help="same as -f sixel")
    ap.add_argument("--cols", type=int, metavar="N", help="kitty, iterm: scale the picture to this many character cells wide; "
                    "ansi: the width in characters (negative: that many fewer than the terminal; default: the picture's own size "
                    "at 8 pixels a character, at most the terminal's width)")
    ap.add_argument("--rows", type=int, metavar="N", help="kitty, iterm, ansi: the same, for the height (the picture's shape is kept)")
    ap.add_argument("--glyphs", choices=list(bifgfx.GLYPHS), default="blocks",
                    help="ansi: the characters to use: half blocks; plus quadrants; plus eighths (default); Braille dots")
    ap.add_argument("--colors", type=int, choices=list(bifgfx.COLOR_DEPTHS), default=24,
                    help="ansi: the colour depth: 24-bit (default), 256 or 16 colours")
    ap.add_argument("--tek-invert", action="store_true", help="tek-hatch, tek-dots, tek-contour: dark is ink (for a picture of "
                    "dark shading on a light page)")
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
    ap.add_argument("--transparent", action="store_true", help="leave the page transparent (PNG alpha, SIXEL unpainted, ansi "
                    "and kitty and iterm: the terminal's own background shows)")
    ap.add_argument("-b", "--background", metavar="auto|transparent|COLOR",
                    help="the page: a colour (as --paper), transparent, or auto: on a terminal, the terminal's own "
                         "background colour (asked with OSC 11) for SIXEL, or transparent (kitty, iterm, ansi, or if it will not "
                         "say), and the ink made light or dark to show on it; anywhere else the picture's own page "
                         "(default: the picture's)")
    ap.add_argument("--force", action="store_true", help="send SIXEL even if the terminal does not say it has it")
    ap.add_argument("--no-query", action="store_true", help="do not ask the terminal anything (also BIDET_NO_QUERY=1)")
    ap.add_argument("--layer", action="append", metavar="ID", help="draw only this layer id (repeatable)")
    ap.add_argument("--max-pixels", type=float, default=bifrender.DEFAULT_MAX_PIXELS, metavar="N",
                    help="largest picture to draw; bigger is drawn smaller (default %d)" % bifrender.DEFAULT_MAX_PIXELS)
    ap.add_argument("-t", "--truncated", action="store_true", help="draw what arrived of a file that ends early")
    ap.add_argument("-v", "--verbose", action="store_true")
    bifdiag.add_arguments(ap)
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
    """Is the picture for the terminal on standard output (not `-o FILE`)?  Then it is meant for the terminal, whether or not
    standard output is one right now (it may be a pipe to `less -R` or `cut`): for SIXEL the terminal is asked what it can do,
    like the old bidet's test-sixel did.  Callers that only ask on a real tty pass out_is_tty."""
    return (fmt in TERMINAL_FORMATS or fmt == "auto") and out_is_tty and (not a.output or a.output == "-")


def ask_terminal(a, fmt, out_is_tty=True, env=None, want_cell=False):
    """What the terminal says (bifterm.Reply), asking only if SIXEL may be going to it (sixel, or auto); NOTHING otherwise.
    want_cell: also how big a character cell is (an animation needs it to know how many lines it takes)."""
    if not to_terminal(a, fmt, out_is_tty) or a.no_query or fmt not in ("sixel", "auto"):
        return bifterm.NOTHING
    with bifdiag.stage("ask the terminal"), bifdiag.quiet():
        reply = bifterm.query(want_bg=(a.background or "").lower() == "auto", want_cell=want_cell, env=env,
                              debug=a.verbose or bifdiag.debugging())
    bifdiag.debug("terminal: sixel=%s bg=%s cell=%s" % (reply.sixel, reply.bg, reply.cell))
    return reply


def plays(pic, a, fmt, out_tty=True):
    """Is this an animation that goes to the terminal as something that can play (SIXEL, coloured text, or auto: which will be
    one of them or not), to be played?  (Not with --frame, not into a file or a pipe.)"""
    return len(pic.frames) > 1 and a.frame is None and to_terminal(a, fmt, out_tty) and (fmt in PLAYABLE or fmt == "auto")


def progress_on_stderr(done, total):
    bifdiag.progress("drawing frame", done, total)


def terminal_options(pic, a, opts, reply, env=None, fmt="sixel", check=None):
    """The render options for a picture that goes to a terminal that said `reply`, in format `fmt`: refuses SIXEL a terminal
    says it has not (unless --force; `check`: only when that was asked for, which is the default for fmt "sixel"), and settles
    `--background auto`: the terminal's colour for the page (SIXEL), or transparent (kitty, iterm, ansi, or if it will not say);
    the ink becomes light or dark if the page would swallow it."""
    env = os.environ if env is None else env
    check = (fmt == "sixel") if check is None else check
    if check and reply.asked and reply.sixel is not True and not (a.force or env.get("LSIX_FORCE_SIXEL_SUPPORT")):
        raise bif.BifError("your terminal does not report having SIXEL graphics support%s.  Try mintty, xterm -ti vt340, "
                           "mlterm, Windows Terminal or WezTerm; or --force to send it anyway, -f ansi for coloured text, -f auto "
                           "to let bifout choose, or -o FILE.png"
                           % ("" if reply.sixel is False else " (it did not answer)"))
    if (a.background or "").lower() != "auto":
        return opts
    opts = dict(opts)
    if reply.bg and fmt == "sixel":
        opts["paper"], opts["transparent"] = tuple(reply.bg), False
        page = reply.bg
    else:
        opts["transparent"] = True                              # the terminal's own colour shows through
        page = reply.bg or ((255, 255, 255) if bifterm.guess_dark(env) is False else (0, 0, 0))     # dark unless it says light
    inks = [e["rgb"] for e in pic.palette if e.get("role") == "ink"]
    if inks and not opts.get("ink") and abs(bifterm.luminance(inks[0]) - bifterm.luminance(page)) < 0.4:
        opts["ink"] = LIGHT_INK if bifterm.luminance(page) < 0.5 else DARK_INK
    return opts


def format_options(a, cell=None, reply=None):
    """The options of the formats themselves (what a writer in WRITERS takes), from parsed arguments: the size in characters,
    the glyph set and colour depth of ansi, the shape of a character cell, the terminal's size."""
    cw, ch = cell if cell else cell_size(a.cell, reply)
    t = shutil.get_terminal_size((80, 24))
    return dict(cols=a.cols, rows=a.rows, glyphs=a.glyphs, colors=a.colors, aspect=ch / float(cw), term=(t.columns, t.lines),
                tek_invert=a.tek_invert)


def terminal_data(pic, a, fmt, opts, out=None, tty=True):
    """Everything about drawing a picture for the terminal on standard output in `fmt` (auto: whatever it can show) except
    writing it.  An animation that the format can play (and tty: standard output is a terminal) is played on `out` here.
    Returns (the Rendering of the first frame, the bytes to write, or None if it was played)."""
    out = out or sys.stdout.buffer
    bifdiag.step("bifout")
    multi = len(pic.frames) > 1 and a.frame is None
    reply = ask_terminal(a, fmt, want_cell=multi or fmt == "auto")
    asked_for = fmt
    if fmt == "auto":
        fmt = "sixel" if (a.force or os.environ.get("LSIX_FORCE_SIXEL_SUPPORT")) else bifgfx.pick_format(reply)
    opts = terminal_options(pic, a, opts, reply, fmt=fmt, check=(asked_for == "sixel"))
    cell = cell_size(a.cell, reply)
    fo = format_options(a, cell)
    if multi and tty and fmt in PLAYABLE:
        return play(pic, out, cell, progress=progress_on_stderr, erase=a.erase, fmt=fmt, fmt_opts=fo, **opts), None
    buf = io.BytesIO()
    r = convert(pic, fmt, buf, fmt_opts=fo, **opts)
    return r, buf.getvalue()


def show(pic, a, fmt, opts, out=None, tty=True):
    """terminal_data(), and the bytes written to `out` (standard output): a Tektronix picture, on a terminal, switches an xterm
    into Tek mode, draws, waits for Enter and switches back.  Returns the Rendering of the first frame."""
    out = out or sys.stdout.buffer
    r, data = terminal_data(pic, a, fmt, opts, out, tty)
    if data is None:
        return r
    with bifdiag.quiet():
        if tty and data.startswith(TEK_ERASE):
            bifgfx.tek_emit(data[len(TEK_ERASE):], out, xterm=True, erase=True)
        else:
            out.write(data)
            out.flush()
    return r


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)

    if a.file == "-" and sys.stdin.isatty():
        ap.error("no input: give a .bif file or pipe one in")
    out_tty = sys.stdout.isatty()
    fmt = "sixel" if a.sixel else (a.format or format_for(a.output if a.output != "-" else None, out_tty and not a.output))
    on_stdout = not a.output or a.output == "-"
    if fmt == "auto" and not on_stdout:
        ap.error("-f auto chooses what a terminal can show: use a format with -o FILE")
    if on_stdout and out_tty and fmt not in TERMINAL_FORMATS and fmt != "auto":
        ap.error("will not write %s to a terminal: use -o FILE, -s for SIXEL, -f ansi, -f auto, or a pipe" % fmt.upper())
    try:
        if a.file == "-":
            data = sys.stdin.buffer.read()                       # (the tools before it are working: the spinner waits)
        else:
            with open(a.file, "rb") as f:
                data = f.read()
        bifdiag.start("bifout", debug=a.debug, profile=a.profile)
        with bifdiag.stage("read BIF"):
            pic = bif.loads(data, allow_truncated=a.truncated)
        opts = render_options(a)
        if to_terminal(a, fmt):                                  # for the terminal: it is asked, and an animation played
            r = show(pic, a, fmt, opts, tty=out_tty)
            bifdiag.stop()
            for n in r.notes:
                sys.stderr.write("bifout: %s\n" % n)
            return
        buf = io.BytesIO()
        r = convert(pic, fmt, buf, fmt_opts=format_options(a), **opts)
    except (bif.BifError, IOError) as e:
        bifdiag.fail("bifout", e, a.debug)
    bifdiag.stop()
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
