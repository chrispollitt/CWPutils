#!/usr/bin/env python3
"""timemachine: your text the way each generation of big terminal text drew it, then popping out of the screen.

    timemachine.py "BIDeT" -o time-machine.gif          (also: bidet --time-machine BIDeT -o time-machine.gif)

banner(1) (1983), FIGlet (1991), TOIlet (2004) as terminal sessions, each typed out line by line with a year ticker winding
forward between them; then BIDeT (2020), flat; and then the 4D part, new since bidet3d's time machine: the flat picture
**pops out of the screen**: it grows its depth, rises toward you on a shadow that parts from it, takes the colours of its
material, and turns (bifop `motion:path=flat+tick+pop+hold+spin`).  The result is one multi-frame BIF, written as a GIF.

It is an assembly of the 4D tools, nothing more: the eras are `.vt` sessions read by bifin_vt (`-m ansi-block`: the terminal
as a picture), the flat picture is bifin's lettering importer, the pop-out is bifop_3d, and the pieces are put together with
bifop_join (`join` the two parts, `overlay` the captions).  `--script` prints the same as shell commands.  The real banner,
figlet and toilet programs are used if they are installed (BIDET_EMULATE=1 says not to), else imitations that draw the
text from a font.
"""
from __future__ import print_function

import argparse
import colorsys
import math
import os
import re
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image

import bif
import bifin_lettering
import bifin_vt
import bifop
import bifop_join
import bifout
import bifrender

VERSION = "0.1"
STAGES = [
    (1983, "banner(1)", "AT&T, UNIX System V: big text out of # characters"),
    (1991, "FIGlet", "Chappell and Chai: numerous fonts"),
    (2004, "TOIlet", "Sam Hocevar: more fonts, colour and filters"),
    (2020, "BIDeT", "Chris Pollitt: SIXEL graphics and real fonts"),
    (2026, "BIDeT 4D", "the fourth dimension: it pops out of the screen"),
]
INK = (229, 229, 229)                                    # the terminal's default text
FLAT_COLOUR = (100, 149, 237)                            # BIDeT (2020) was flat: one colour, no depth
_QUAD = " .,_')//`\\(L\"7[#"                              # figlet-ish character for each 2x2 block of ink: tl*8+tr*4+bl*2+br
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


# ---------------------------------------------------------------------------------------------
# The text-mode eras: the real programs, or imitations drawn from a font
# ---------------------------------------------------------------------------------------------
def text_mask(line, font="sans"):
    """The line set in a font, as an 8-bit coverage mask (Pillow image), 160 px tall-ish."""
    pic = bifin_lettering.lettering(line, font=font, size=160)
    r = bifrender.render(pic, scale=1.0)
    return Image.fromarray(np.clip(r.alpha * 255 + 0.5, 0, 255).astype(np.uint8), "L")


def _grid(mask, gw, gh):
    return np.asarray(mask.resize((max(1, gw), max(1, gh)), Image.BOX), np.float32) / 255.0


def _tool(argv, line, stdin=False):
    """Output of a real banner/figlet/toilet, or None if it is missing or fails."""
    if os.environ.get("BIDET_EMULATE") or not shutil.which(argv[0]):
        return None
    try:
        r = subprocess.run(argv + ([] if stdin else [line]), input=(line + "\n").encode("utf-8") if stdin else None,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    out = r.stdout.decode("utf-8", "replace").rstrip("\n")
    return out if r.returncode == 0 and out.strip() else None


def emulate_banner(line, cols, font="sans"):
    mask = text_mask(line, font)
    a = mask.width / float(mask.height)
    rows = 7
    gw = int(round(a * rows * 1.5))
    if gw > cols - 4:
        gw = cols - 4
        rows = max(3, int(gw / (a * 1.5)))
    g = _grid(mask, gw, rows) > 0.35
    return "\n".join("".join("#" if v else " " for v in row) for row in g)


def emulate_figlet(line, cols, font="sans"):
    mask = text_mask(line, font)
    a = mask.width / float(mask.height)
    rows = 6
    gw = min(cols - 4, int(round(a * rows * 1.6)))
    g = _grid(mask, gw * 2, rows * 2) > 0.4
    out = []
    for y in range(rows):
        row = ""
        for x in range(gw):
            t = y * 2
            row += _QUAD[int(g[t, 2 * x]) * 8 + int(g[t, 2 * x + 1]) * 4 + int(g[t + 1, 2 * x]) * 2 + int(g[t + 1, 2 * x + 1])]
        out.append(row)
    return "\n".join(out)


def emulate_toilet(line, cols, font="sans"):
    mask = text_mask(line, font)
    a = mask.width / float(mask.height)
    gh = 8
    gw = int(round(a * gh))
    if gw > cols - 4:
        gw = cols - 4
        gh = max(2, int(gw / a) // 2 * 2)
    g = _grid(mask, gw, gh) > 0.4                        # half-blocks: every pixel is square
    out = []
    for y in range(0, gh, 2):
        row = ""
        for x in range(gw):
            top, bot = g[y, x], g[y + 1, x]
            if not (top or bot):
                row += " "
                continue
            r, gr, b = (int(255 * c) for c in colorsys.hsv_to_rgb(0.85 * x / gw, 0.8, 1.0))
            row += "\x1b[38;2;%d;%d;%dm%s" % (r, gr, b, "█" if top and bot else "▀" if top else "▄")
        out.append(row + "\x1b[0m")
    return "\n".join(out)


def era_text(stage, lines, cols, font="sans"):
    """The text of eras 0..2 (banner, FIGlet, TOIlet) for the lines of text: the real program when installed."""
    blocks = []
    for ln in lines:
        if not ln.strip():
            continue
        if stage == 0:
            txt = None
            if not ln.startswith("-"):
                txt = _tool(["banner", "-w", str(cols - 4)], ln)
                if txt and max(len(r) for r in txt.split("\n")) > cols - 2:
                    txt = None
            txt = txt or emulate_banner(ln, cols, font)
        elif stage == 1:
            txt = _tool(["figlet", "-w", str(cols - 4)], ln, stdin=True) or emulate_figlet(ln, cols, font)
        else:
            txt = (_tool(["toilet", "-f", "future", "-F", "gay", "-w", str(cols - 4)], ln, stdin=True)
                   or _tool(["toilet", "-F", "gay", "-w", str(cols - 4)], ln, stdin=True)
                   or emulate_toilet(ln, cols, font))
        blocks.append(txt)
    return "\n\n".join(blocks)


def visible_width(s):
    return len(_ANSI.sub("", s))


# ---------------------------------------------------------------------------------------------
# A terminal session, written step by step: each step is one line to a .vt player (one delay)
# ---------------------------------------------------------------------------------------------
class Script(object):
    def __init__(self, delay):
        self.delay, self.parts = delay, []

    def step(self, row, col, text="", clear=False):
        """Put text at a place (and clear the screen first, if asked): one step of the session."""
        self.parts.append(("\x1b[2J" if clear else "") + "\x1b[%d;%dH" % (row, col) + text + "\n")

    def wait(self, ms):
        """Leave the screen alone for about this long: steps that change nothing (a player sleeps at each newline)."""
        self.parts.append("\x1b[1;1H\n" * max(1, int(round(ms / float(self.delay)))))

    def text(self):
        return "".join(self.parts)


def caption(i):
    year, name, note = STAGES[i]
    return "\x1b[1;33m%d\x1b[0m  \x1b[1;36m%s\x1b[0m  \x1b[90m%s\x1b[0m" % (year, name, note)


def year_at(y0, y1, t):
    return int(round(y0 + (y1 - y0) * (1 - (1 - t) ** 2)))        # the ticker slows as it arrives


def ticker(s, row, y0, y1, steps):
    for k in range(steps + 1):
        s.step(row, 3, "\x1b[K\x1b[1;32m>>> %d <<<\x1b[0m" % year_at(y0, y1, k / float(steps)))


class Settings(object):
    """The knobs of the show, with the defaults that make a good GIF."""
    stage_time = 3.0            # seconds each era is shown
    delay = 60                  # ms a line of a terminal session takes (the typing speed)
    cols = 64                   # the terminal's width in characters (wider if the art is)
    cell = 12                   # pixels per character cell
    paper = (38, 43, 51)        # the screen's colour: dark, but not black, so that shadows show
    face = "impact"            # BIDeT's font
    era_font = "sans"           # the font the imitations of banner, figlet and toilet draw from
    material = "rainbow"        # what it pops out as
    depth = 0.22
    hover = 0.6
    view = "-20+8+0"
    turns = 1.0                 # turns of the spin that ends the show
    fps = 15.0
    res = 2
    ticker_steps = 12
    pop_time = 1.6

    def __init__(self, **kw):
        for k, v in kw.items():
            if not hasattr(self, k):
                raise TypeError("unknown setting " + k)
            setattr(self, k, v)


def eras(lines, cfg):
    """(texts, cols, rows): the art of the three terminal eras, and a screen that holds them all."""
    cols = cfg.cols
    texts = [era_text(i, lines, cols, cfg.era_font) for i in range(3)]
    widest = max(visible_width(r) for t in texts for r in t.split("\n"))
    cols = max(cols, widest + 6, max(visible_width(caption(i)) for i in range(len(STAGES))) + 4)
    height = max(len(t.split("\n")) for t in texts)
    return texts, cols, max(12, height + 6)


def terminal_session(texts, cfg):
    """The three terminal eras as one session, with the year ticker winding forward after each; the last winds up to 2020."""
    s = Script(cfg.delay)
    for i, art in enumerate(texts):
        s.step(1, 1, caption(i), clear=True)
        rows = art.split("\n")
        for r, line in enumerate(rows):                                  # typed out, line by line
            s.step(3 + r, 3, line)
        s.wait(cfg.stage_time * 1000)
        ticker(s, 3 + len(rows) + 1, STAGES[i][0], STAGES[i + 1][0], cfg.ticker_steps)
    return s.text()


def vt_pictures(cfg, cols, rows):
    """kwargs of bifin_vt.import_vt that every terminal picture of the show shares (so they line up)."""
    return dict(delay=cfg.delay, hold=200, mode="ansi-block", crop=False, cols=cols, rows=rows, cell_w=cfg.cell,
                aspect=2.0, ink=INK, paper=cfg.paper, color="on", smooth=0.0)


def read_vt(stream, cfg, cols, rows, **extra):
    return bifin_vt.import_vt(stream.encode("utf-8"), **dict(vt_pictures(cfg, cols, rows), **extra))


def caption_only(i, cfg, cols, rows, with_ticker=False):
    """A picture of era i's caption, on the same screen as the terminal eras (one frame; with the ticker: a frame per year)."""
    s = Script(cfg.delay)
    s.step(1, 1, caption(i), clear=True)
    if with_ticker:
        ticker(s, 3, STAGES[i][0], STAGES[i + 1][0], cfg.ticker_steps)
    else:
        s.wait(cfg.delay)
    return read_vt(s.text(), cfg, cols, rows, hold=cfg.delay)


def flat_lettering(lines, cfg, canvas_w, canvas_h):
    """BIDeT (2020): the text flat, in one colour, set to fill about half the screen."""
    text = "\n".join(l for l in lines if l.strip())
    probe = bifin_lettering.lettering(text, font=cfg.face, size=100, align="center", margin=0.1)
    k = min(canvas_w * 0.50 / probe.width, canvas_h * 0.46 / probe.height)
    size = max(24.0, min(170.0, 100.0 * k))
    return bifin_lettering.lettering(text, font=cfg.face, size=size, align="center", margin=0.1, ink=FLAT_COLOUR, paper=cfg.paper)


def motion_spec(cfg, ticks, tickms):
    """The bifop operation that pops the flat picture out and spins it (what `--script` prints, and what is run)."""
    return ("motion:path=flat+tick+pop+hold+spin,flat=%g,ticks=%d,tickms=%g,time=%g,hold=0.4,turns=%g,material=%s,depth=%g,"
            "hover=%g,view=%s,fps=%g,res=%d" % (cfg.stage_time, ticks, tickms, cfg.pop_time, cfg.turns, cfg.material, cfg.depth,
                                                cfg.hover, cfg.view, cfg.fps, cfg.res))


def build(text, cfg=None, say=None):
    """The whole show as one bif.Picture (an animation).  say: a function that is told what is being done."""
    cfg = cfg or Settings()
    say = say or (lambda msg: None)
    lines = [l for l in text.replace("\r", "").split("\n") if l.strip()]
    if not lines:
        raise bif.BifError("time machine: no text")
    say("the terminal eras (%s)" % ", ".join(s_[1] for s_ in STAGES[:3]))
    texts, cols, rows = eras(lines, cfg)

    # BIDeT (2020), flat, drawn to fit the screen; then popped out of it.  The pop needs room (it rises, and has a shadow):
    # the screen is made tall enough to hold it, so that the captions keep clear
    say("BIDeT flat, then popping out of the screen")
    tick = caption_only(3, cfg, cols, rows, with_ticker=True)            # (here to count the ticker's frames)
    ticks = len(tick.frames)
    flat = flat_lettering(lines, cfg, cols * cfg.cell + 2 * cfg.cell, rows * 2 * cfg.cell + 2 * cfg.cell)
    part = bifop.apply(flat, [motion_spec(cfg, ticks, 40)], bifop.Notes())
    need = int(math.ceil((part.height + 4 * cfg.cell) / (2.0 * cfg.cell))) + 2
    if need > rows:
        rows = need
        tick = caption_only(3, cfg, cols, rows, with_ticker=True)
    for j, f in enumerate(tick.frames):                                   # (the ticker runs at its own pace)
        part.frames[1 + j].props["duration"] = f.duration
    part.frames[0].props["duration"] = int(cfg.stage_time * 1000)
    pic = read_vt(terminal_session(texts, cfg), cfg, cols, rows)
    n_term = len(pic.frames)

    say("putting it together")
    d1, _d2 = bifop_join.append(pic, part)
    cap_flat = caption_only(3, cfg, cols, rows)
    cap_4d = caption_only(4, cfg, cols, rows)
    nb = len(part.frames)
    first = n_term
    bifop_join.overlay(pic, cap_flat, first, first, d1[0], d1[1])
    bifop_join.overlay(pic, tick, first + 1, first + ticks, d1[0], d1[1])
    bifop_join.overlay(pic, cap_4d, first + ticks + 1, first + nb - 1, d1[0], d1[1])
    pic = bifop.apply(pic, ["crop:margin=%d" % cfg.cell], bifop.Notes())
    pic.animation = {"loop": 0}
    pic.meta["title"] = "BIDeT time machine"
    return pic


def script(text, cfg=None, output="time-machine.gif"):
    """The same show as shell commands (what `bidet --time-machine -n` prints)."""
    cfg = cfg or Settings()
    return "\n".join([
        "# the terminal eras, typed out as .vt sessions (banner, figlet, toilet and a year ticker; written by timemachine.py)",
        "bifin -f vt era.vt -m ansi-block --no-crop --delay %d --ink '#e5e5e5' --paper '#%02x%02x%02x' -o a.bif" % ((cfg.delay,) + tuple(cfg.paper)),
        "# BIDeT flat, popped out of the screen and spun",
        "bifin -f lettering --face %s --align center --ink '#6495ed' --paper '#%02x%02x%02x' -o b0.bif <<< %r" % ((cfg.face,) + tuple(cfg.paper) + (text,)),
        "bifop -i b0.bif -o b.bif '%s'" % motion_spec(cfg, cfg.ticker_steps + 1, 40),
        "# together: the eras, then BIDeT; the captions on top of it",
        "bifop -i a.bif -o tm.bif join:b.bif overlay:cap2020.bif overlay:tick.bif overlay:cap4d.bif crop:margin=%d" % cfg.cell,
        "bifout tm.bif -o %s" % output,
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="timemachine", description="Your text through the history of big terminal text, "
                                 "then popping out of the screen: a GIF.")
    ap.add_argument("text", nargs="*", help="the text (default: BIDeT)")
    ap.add_argument("-o", "--output", default="time-machine.gif", metavar="FILE", help="the animation: .gif or .bif (default time-machine.gif)")
    ap.add_argument("--stage-time", type=float, default=Settings.stage_time, metavar="SEC", help="seconds for each era (default 3)")
    ap.add_argument("--material", default=Settings.material, help="what it pops out as (bifop extrude --list: rainbow, chrome, gold, ...)")
    ap.add_argument("--face", default=Settings.face, help="BIDeT's font (default impact)")
    ap.add_argument("--turns", type=float, default=Settings.turns, help="turns of the final spin (default 1)")
    ap.add_argument("--fps", type=float, default=Settings.fps, help="frames a second of the 3D part (default 15)")
    ap.add_argument("--scale", type=float, default=1.0, help="size of the GIF: pixels per canvas unit (default 1)")
    ap.add_argument("--script", action="store_true", help="print the shell commands of the same thing and stop")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    text = " ".join(a.text) if a.text else "BIDeT"
    cfg = Settings(stage_time=a.stage_time, material=a.material, face=a.face, turns=a.turns, fps=a.fps)
    if a.script:
        print(script(text, cfg, a.output))
        return 0
    try:
        pic = build(text, cfg, say=(lambda m: sys.stderr.write("timemachine: %s\n" % m)) if a.verbose else None)
        if a.output.lower().endswith(".bif"):
            bif.save(pic, a.output)
        else:
            with open(a.output, "wb") as f:
                bifout.convert(pic, bifout.format_for(a.output, False), f, scale=a.scale)
    except (bif.BifError, ValueError, IOError) as e:
        sys.exit("timemachine: %s" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
