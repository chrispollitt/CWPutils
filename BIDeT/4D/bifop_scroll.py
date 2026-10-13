"""bifop_scroll: scrolling text.  A marquee, a news ticker, rolling credits: the picture slides through a window, round and round.

    bifin -f lettering --face impact "HELLO, WORLD" | bifop crop:margin=10 scroll | bifout --width 640 -o hello.gif
    bifop scroll:left,start=enter,window=8      the CP/M way: it begins empty and the text comes in from the right edge
    bifop scroll:up,window=1.2,start=enter      rolling credits: the lines climb from the bottom edge

This is the idea of LARGE.BAS, the CP/M "LARGE letter NIL program" (CWP!inc, 1994): it set a line in big letters and slid it left
across the screen a column at a time, the first letter going round to the back, until a key was pressed.  Here the picture is
any flat picture (lettering, art, a 3D still), the window and the speed are yours, and the loop is seamless: the last frame
leads into the first, so a GIF repeats and a terminal plays it until Ctrl-C.

How it works.  The picture is a strip of length L along the way it travels; a lap is the strip plus a gap, P = L + gap.  Frame i
shows the window (the new canvas) with copies of the strip at offsets base - s + k*P, s = i*P/n; the frames are n = P / step, so
the last one is one step short of the first and nothing jumps.  A vector layer is sliced for each frame to the paths that show
(compound letters are kept whole), so a long banner costs no more per frame than a short one, in time or in file size; a raster
layer is moved whole (its pixels are shared between the frames in memory, but not in a BIF file).
"""
from __future__ import print_function

import copy
import math

import numpy as np

import bif
import bifop
import bifop_join
from bifop import op, _float

DIRS = {"left": (0, -1), "right": (0, 1), "up": (1, -1), "down": (1, 1)}      # name: (axis it moves along, 0 = x, 1 = y; its sign)
DEFAULT_SPEED = (3.0, 0.2)                                                     # by axis (x, y): a unit of speed is the picture's height going
#                                                                              sideways but its width going up, which is the larger
STARTS = ("rest", "enter")
MAX_FRAMES = 5000

PATH_ARRAYS = ("width", "stroke", "fill", "flags", "group")                    # one value per path
VERTEX_ARRAYS = ("vwidth", "vflag")                                            # one value per vertex


class _Strip(object):
    """A vector layer ready to be sliced: where each unit that is drawn together (a path, or the paths of one `group`: a letter and
    its holes) lies along the way the picture travels, so a frame can be given just the units that show."""

    def __init__(self, layer, axis):
        A = layer.arrays
        self.layer = layer
        self.cut = all(k in ("xy", "start") or k in PATH_ARRAYS or k in VERTEX_ARRAYS for k in A)      # (an array we do not know
        st = A["start"].astype(np.int64)                                                                #  cannot be sliced)
        P = len(st) - 1
        self.P, self.counts = P, np.diff(st)
        m = bifop.layer_matrix(layer)
        xy = A["xy"].astype(np.float64)
        pos = (m[0] * xy[:, 0] + m[2] * xy[:, 1] + m[4]) if axis == 0 else (m[1] * xy[:, 0] + m[3] * xy[:, 1] + m[5])
        lo, hi = np.full(P, np.inf), np.full(P, -np.inf)                       # (a path with no points is never drawn)
        ne = np.nonzero(self.counts > 0)[0]
        if len(ne):
            lo[ne], hi[ne] = np.minimum.reduceat(pos, st[ne]), np.maximum.reduceat(pos, st[ne])
        width = float(A["width"].max()) if "width" in A and len(A["width"]) else float(layer.get("width", 1.0))
        vmax = float(A["vwidth"].max()) if "vwidth" in A and len(A["vwidth"]) else 1.0
        miter = max(1.0, float(layer.get("miter_limit", 4.0))) if layer.get("join") == "miter" else 1.0
        pad = 0.5 * width * bifop.scale_of(m) * max(1.0, vmax) * miter + 1.0       # how far the pen reaches past the points
        g = A["group"].astype(np.int64) if "group" in A else None
        new = np.ones(P, bool)
        if g is not None and P:
            new[1:] = (g[1:] != g[:-1]) | (g[1:] < 0)
        first = np.nonzero(new)[0]
        self.size = np.diff(np.append(first, P))
        if P:
            self.lo, self.hi = np.minimum.reduceat(lo, first) - pad, np.maximum.reduceat(hi, first) + pad

    def select(self, offset, window):
        """The arrays of what shows when the layer is moved `offset` along the way and the window is [0, window): all of them (shared),
        the arrays of just the units that show, or None if nothing does."""
        if self.P == 0:
            return None
        show = (self.lo + offset < window) & (self.hi + offset > 0)
        if not show.any():
            return None
        if show.all() or not self.cut:
            return self.layer.arrays
        pm = np.repeat(show, self.size)                                       # the paths, then the vertices, that show
        vm = np.repeat(pm, self.counts)
        out = {}
        for name, a in self.layer.arrays.items():
            if name == "xy":
                out[name] = a[vm]
            elif name == "start":
                s = np.zeros(int(pm.sum()) + 1, a.dtype)
                s[1:] = np.cumsum(self.counts[pm])
                out[name] = s
            else:
                out[name] = a[pm] if name in PATH_ARRAYS else a[vm]
        return out


def _choice(*names):
    """A parameter converter: one of these words."""
    def conv(s):
        if s not in names:
            raise bif.BifError("'%s' is not one of %s" % (s, ", ".join(names)))
        return s
    return conv


def _raster_span(layer, axis):
    """(first, last) of where the raster has any ink along the way, in canvas units, or None."""
    e = bifop._raster_extent(layer, bifop.layer_matrix(layer))
    if e is None:
        return None
    return (e[0], e[2]) if axis == 0 else (e[1], e[3])


def _place(frame, layer, arrays, offset, axis):
    """Add `layer` (with these arrays) to a frame, moved `offset` units along the way."""
    props = copy.deepcopy(layer.props)
    shift = (1.0, 0.0, 0.0, 1.0, offset, 0.0) if axis == 0 else (1.0, 0.0, 0.0, 1.0, 0.0, offset)
    props["transform"] = list(bifop.mmul(shift, bifop.layer_matrix(layer)))
    if props.get("id"):
        props["id"] = bifop_join._unique_id(frame, props["id"])
    frame.layers.append(bif.Layer(layer.kind, props, arrays))


@op("scroll", [("dir", _choice(*sorted(DIRS)), "left", "the way the picture travels: left (a ticker, a marquee), right, up (rolling credits) or down"),
               ("window", _float, 5.0, "how much shows at once, in times the picture's size across the way it travels (its height, "
                                       "for left and right); this becomes the canvas"),
               ("speed", _float, None, "how fast it goes, in that same unit a second (default 3 for left and right, 0.2 for up and down)"),
               ("time", _float, None, "seconds for one lap, instead of a speed: the loop lasts exactly this long"),
               ("gap", _float, None, "empty space between the end of one lap and the start of the next, in that unit "
                                     "(default: as wide as the window, so the picture has left before it comes back, as on CP/M)"),
               ("start", _choice(*STARTS), "rest", "rest: begins with the start of the picture in the window; "
                                       "enter: begins empty and the picture comes in at the far edge"),
               ("fps", _float, 25.0, "frames a second")],
    "Scrolling text: the picture slides through a window, round and round, a seamless loop of frames (the CP/M LARGE.BAS, a "
    "ticker, rolling credits).  Takes ONE flat picture (do crop and any warp or 3D look first); right and down run the lap "
    "the other way; only what is drawn is moved (a character grid is forgotten).")
def op_scroll(pic, notes, dir, window, speed, time, gap, start, fps):
    if len(pic.frames) != 1:
        raise bif.BifError("scroll: needs a flat picture (one frame), not %d; scroll comes last" % len(pic.frames))
    axis, sign = DIRS[dir]
    if speed is None:
        speed = DEFAULT_SPEED[axis]
    if window <= 0 or fps <= 0 or speed <= 0 or (time is not None and time <= 0):
        raise bif.BifError("scroll: window, speed (or time) and fps must be positive")
    ua = float(pic.unit_aspect)
    f = 1.0 if axis == 0 else ua                                               # how long a canvas unit is along the way (a unit of x is 1)
    length = float(pic.width if axis == 0 else pic.height)                     # the strip, in canvas units
    cross = float(pic.height) * ua if axis == 0 else float(pic.width)          # its size across (the unit of window, speed and gap)
    if length <= 0 or cross <= 0:
        raise bif.BifError("scroll: the picture has no size")
    win = max(1, int(round(window * cross / f)))                               # the window, in whole canvas units
    gap_u = win if gap is None else gap * cross / f
    period = length + gap_u
    if period <= 0:
        raise bif.BifError("scroll: the gap swallows the whole picture")
    seconds = float(time) if time is not None else period * f / (speed * cross)
    n = max(2, int(round(seconds * fps)))
    if n > MAX_FRAMES:
        raise bif.BifError("scroll: %d frames is too many (at most %d): scroll faster (speed=, time=), use fewer frames a second "
                           "(fps=), shorten the gap, or make the picture shorter" % (n, MAX_FRAMES))
    bifop.drop_grid(pic)
    base = pic.frames[0]
    drawn, kept = [], []
    for L in base.layers:
        shows = L.get("visible", True) and L.get("role") != "source"
        if L.kind == "vector" and shows and "xy" in L.arrays and "start" in L.arrays:
            drawn.append((L, _Strip(L, axis), None))
        elif L.kind == "raster" and shows and _raster_span(L, axis) is not None:
            drawn.append((L, None, _raster_span(L, axis)))
        else:
            kept.append(L)                                                     # not drawn (hidden, a source, a kind we do not know)
    if not drawn:
        raise bif.BifError("scroll: nothing is drawn, so there is nothing to scroll")
    origin = (win if sign < 0 else -length) if start == "enter" else 0.0       # where the strip starts, before it moves
    total_ms = n * 1000.0 / fps
    slack = length                                                             # (ink may hang over the canvas a little)
    frames = []
    for i in range(n):
        ms = int(round(total_ms * (i + 1) / n)) - int(round(total_ms * i / n))
        frame = bif.Frame(duration=max(1, ms), props=dict((k, v) for k, v in base.props.items() if k != "duration"))
        if i == 0:
            frame.layers.extend(kept)
        o0 = origin + sign * period * i / n
        k0, k1 = int(math.floor((-length - slack - o0) / period)), int(math.ceil((win + slack - o0) / period))
        for L, strip, span in drawn:
            for k in range(k0, k1 + 1):
                o = o0 + k * period
                if strip is not None:
                    arrays = strip.select(o, win)
                elif span[0] + o < win and span[1] + o > 0:
                    arrays = L.arrays
                else:
                    arrays = None
                if arrays is not None:
                    _place(frame, L, arrays, o, axis)
        frames.append(frame)
    pic.frames = frames
    if axis == 0:
        pic.width = win
    else:
        pic.height = win
    pic.animation = {"loop": 0}
    pic.meta["scroll"] = {"dir": dir, "window": window, "start": start, "fps": fps, "frames": n, "seconds": round(seconds, 3),
                          "gap": gap_u * f / cross}
