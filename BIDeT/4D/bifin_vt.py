"""bifin_vt: a terminal session as an animation (`bifin -f vt`, or any file named *.vt).

A .vt file is what a program wrote to a terminal: text with cursor addressing, scroll regions, erase and colour.
`slowcat bambi.vt 25` plays one by sleeping at every newline, and so does this importer, without sleeping: it replays
the stream on the terminal emulator that reads still art (bifin_text._Term), takes the picture of the screen at each
newline (before the newline is processed, as slowcat sleeps before printing it), and keeps each for `delay`
milliseconds.  Steps that leave the screen as it was are merged into one frame with the sum of their times.

All the frames are drawn the same way: the style (line, tone, block ...) and the colours are settled once, from the
fullest screen, the palette is shared, and the canvas is cut to what any frame draws.  The result is an ordinary
multi-frame BIF; `bifout -o x.gif` plays it out.
"""
from __future__ import print_function

import copy
import hashlib
import os

import bif
import bifdiag
import bifin_text as T

MAX_FRAMES = 4000
SCREEN_COLS = 80                                     # a terminal's width, when the file does not say


def _lines(text):
    """The text split after each newline (the last piece may have none)."""
    out, pos = [], 0
    while pos < len(text):
        i = text.find("\n", pos)
        if i < 0:
            out.append(text[pos:])
            break
        out.append(text[pos:i + 1])
        pos = i + 1
    return out


def replay(text, rows, cols, delay, hold, glyphs=False):
    """Run `text` on a terminal of rows x cols.  Returns [[screen, ms]]: the screens ({(line, column): cell}) in order, each
    with how long it stays, equal neighbours merged."""
    term = T._Term(rows, cols, 8, glyphs)
    frames = []

    def show(ms):
        scr = term.screen()
        if frames and frames[-1][0] == scr:
            frames[-1][1] += ms
        else:
            frames.append([scr, ms])
    for line in _lines(text):
        if line.endswith("\n"):
            term.run(line[:-1])
            show(delay)                                  # slowcat sleeps, then prints the newline
            term.run("\n")
        else:
            term.run(line)
    show(hold)
    return frames


def resample(frames, fps):
    """The screens at fps frames a second: whatever is showing at each tick.  Total time is kept."""
    total = sum(ms for _, ms in frames)
    ends, t = [], 0
    for _, ms in frames:
        t += ms
        ends.append(t)
    out, i = [], 0
    n = max(1, int(round(total * fps / 1000.0)))
    for k in range(n):
        t0 = k * 1000.0 / fps
        while i < len(frames) - 1 and ends[i] <= t0:
            i += 1
        ms = int(round((k + 1) * 1000.0 / fps)) - int(round(k * 1000.0 / fps))
        if out and out[-1][0] is frames[i][0]:
            out[-1][1] += ms
        else:
            out.append([frames[i][0], ms])
    return out


def _fullest(grids):
    return max(grids, key=lambda g: sum(c != " " for row in g.ch for c in row))


def _settle(grids, o):
    """Options that make every frame come out in the same style: the mode, colour and polarity the fullest screen
    (or any screen, for colour) would have picked."""
    o = copy.copy(o)
    mode = "block" if o.mode == "ansi-block" else o.mode
    if mode in ("auto", "lineart"):
        g = _fullest(grids)
        picked, _st = T.classify(g, T.shade_cells(g, o.shade))
        mode = "tone" if (mode == "lineart" and picked == "block") else picked
    colour = any(g.has_color() for g in grids)
    o.mode = mode
    if o.color == "auto":
        o.color = "on" if colour else "off"
    if o.dark is None:
        o.dark = colour
    return o


def import_vt(data, delay=100, hold=1000, fps=0.0, loop=0, **kw):
    """The bytes (or text) of a terminal session -> bif.Picture with one frame per distinct screen.
    delay: milliseconds a newline lasts; hold: how long the last screen stays; fps: 0 = every change, else
    at most this many frames a second; loop: 0 = forever.  The rest are bifin_text.Options (cols is the terminal's
    width, 80 if not given; rows its height)."""
    if delay <= 0 or hold < 0 or fps < 0:
        raise bif.BifError("vt: --delay must be positive, --hold and --fps not negative")
    encoding = kw.pop("encoding", None)
    o = T.Options(**kw)
    text, enc = T.decode2(data, encoding)
    cols = o.cols or SCREEN_COLS
    rows = o.rows
    with bifdiag.stage("replay"):
        frames = replay(text, rows, cols, int(delay), int(hold), glyphs=enc in ("cp437", "437"))
    if fps:
        frames = resample(frames, float(fps))
    if not any(scr for scr, _ in frames):
        raise bif.BifError("vt: nothing is ever drawn on the screen")
    if len(frames) > MAX_FRAMES:
        raise bif.BifError("vt: %d distinct pictures (limit %d): use --fps to take fewer" % (len(frames), MAX_FRAMES))
    width = max(x for scr, _ in frames for (_y, x) in scr) + 1 if any(scr for scr, _ in frames) else 1
    grids = [T.screen_grid(scr, rows, width, enc in ("cp437", "437")) for scr, _ in frames]
    crop = o.crop
    with bifdiag.stage("settle"):
        o = _settle(grids, o)
    o.crop = False                                       # (cut once, for all the frames, below)
    T._log(o, "vt: %d steps -> %d pictures of %d x %d characters, mode %s" % (
        sum(1 for _ in _lines(text)), len(frames), width, rows, o.mode))
    o.verbose = False                                    # (the frames' own reports would drown it)

    info = {}                                            # (import_grid keeps the shared palette here)
    base, cache, out = None, {}, []
    for n, ((scr, ms), grid) in enumerate(zip(frames, grids)):
        key = frozenset(scr.items())
        layers = cache.get(key)
        if layers is None:
            with bifdiag.stage("frame"):
                pic = T.import_grid(grid, o, info)
            if base is None:
                base = pic
            layers = cache[key] = pic.frames[0].layers
        bifdiag.progress("reading screen", n + 1, len(frames))
        f = bif.Frame(duration=int(ms))
        f.layers = [bif.Layer(L.kind, copy.deepcopy(L.props), dict(L.arrays)) for L in layers]
        out.append(f)
    base.frames = out
    base.animation = {"loop": int(loop)}
    base.palette = info["palette"].entries

    src = base.meta.setdefault("source", {})
    src["kind"] = "vt"
    if o.name:
        src["name"] = os.path.basename(o.name)
    src["encoding"] = enc
    if isinstance(data, bytes):
        src["sha256"] = hashlib.sha256(data).hexdigest()
        src["bytes"] = len(data)
    src["delay"], src["hold"] = int(delay), int(hold)
    base.meta.setdefault("generator", {})["importer"] = "vt"
    if o.keep_source and isinstance(data, bytes):
        base.source = (os.path.basename(o.name or ""), data)
    if crop:
        import bifop                                     # (here: bifop does not need to know bifin)
        cw = base.grid["cell_width"]
        bifop.op_crop(base, bifop.Notes(), margin=int(0.5 * cw), box=None)
    return base
