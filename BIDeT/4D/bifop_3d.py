"""bifop_3d: operations that lift a flat picture into the third dimension, and make frames of it.

    bifin -f lettering --font impact BIDeT | bifop popout material=rainbow | bifout -o pop.gif
    bifop extrude:material=chrome frame:0 ...      one extruded still (a one-frame picture)
    bifop motion:path=pop+hold+spin                 several moves in one go

`extrude` (a still), `spin` (turns about the vertical axis, a seamless loop), `sway` (swings and back) and `popout` (the
picture, flat on the screen, grows its depth, rises toward the viewer on a shadow that parts from it, and turns: "pop
out of the screen") all take ONE flat picture, draw it once, and replace it with frames: raster layers on one canvas,
drawn by bif3d (see there).  `motion` plays a path of moves (pop, hold, spin, sway) so that they follow each other
from where the last one stopped.  They are the animations of bidet3d (--spin, --sway) and the new pop-out.

Depth and hover are fractions of the drawing's shorter side, so they suit any picture.  The result keeps the palette
(the page colour) but not the character grid; the layers are rasters, so a later `pen` or `wave` has nothing to work on.
"""
from __future__ import print_function

import math
import os

import numpy as np

import bif
import bif3d
import bifop
import bifrender
from bifop import op, REQUIRED, _float, _int, _ids, _str

DEFAULT_VIEW = (-20.0, 8.0, 0.0)

def common(hover=0.6):
    return [
    ("depth", _float, 0.22, "extrusion depth, as a fraction of the drawing's shorter side"),
    ("hover", _float, hover, "how far it floats off the screen when it is up (same unit)"),
    ("view", _ids, None, "yaw+pitch+roll in degrees (default -20+8+0); yaw alone is allowed"),
    ("tall", _float, 1.0, "stretch the picture's height by this before it is extruded (WordArt's taller letters: 1.4)"),
    ("material", _str, None, "the face: rainbow chrome gold superhero sunset aqua blues purple slate lime cornflower, or "
                             "#rrggbb; default: the picture's own colours"),
    ("side", _ids, None, "the extrusion's colours, back+front, e.g. #2a1040+#5a2a7a (default: from the material or the face)"),
    ("bevel", _float, None, "edge lighting of the face, 0..1 (default: the material's)"),
    ("perspective", _float, 2.5, "camera distance in picture widths; smaller = stronger perspective"),
    ("shadow", _float, 1.0, "strength of the shadow on the screen, 0 = none"),
    ("fps", _float, 15.0, "frames a second"),
    ("res", _int, 2, "pixels per canvas unit that the frames are drawn at (bifout --scale 1 averages them down)"),
    ]


COMMON = common()


def _view(v):
    if not v:
        return DEFAULT_VIEW
    try:
        nums = [float(x) for x in v]
    except ValueError:
        raise bif.BifError("view: yaw+pitch+roll are numbers")
    if len(nums) == 1:
        return (nums[0], DEFAULT_VIEW[1], 0.0)
    if len(nums) != 3:
        raise bif.BifError("view: yaw+pitch+roll (or just the yaw)")
    return tuple(nums)


def _frames_for(seconds, fps):
    return max(2, int(round(seconds * fps)))


def _workers():
    return max(1, min(4, os.cpu_count() or 1))


def _lift(pic, notes, name, segments, o):
    """Replace the flat picture by the frames of `segments` ([(kind, params)], kinds: pop hold spin sway still)."""
    if len(pic.frames) != 1:
        raise bif.BifError("%s: needs a flat picture (one frame); to do several moves in one go use motion:path=pop+spin" % name)
    if o["fps"] <= 0 or o["res"] < 1:
        raise bif.BifError("%s: fps must be positive and res at least 1" % name)
    if o["tall"] <= 0:
        raise bif.BifError("%s: tall must be positive" % name)
    src = pic
    if o["tall"] != 1.0:                                          # taller: the same picture on a taller unit (not an op of its own:
        src = bifop.clone(pic)                                    # a later preset's `tall` then replaces this one, it does not pile up)
        src.unit_aspect = float(pic.unit_aspect) * o["tall"]
    r = bifrender.render(src, frame=0, scale=float(o["res"]))
    for n_ in r.notes:
        notes.warn("%s: %s" % (name, n_))
    rgb = np.broadcast_to(r.color_u8(), (r.H, r.W, 3))
    try:
        solid = bif3d.Solid(rgb, r.alpha, material=o["material"], side=o["side"], bevel=o["bevel"])
    except ValueError as e:
        raise bif.BifError("%s: %s" % (name, e))
    view = _view(o["view"])
    depth, hover = o["depth"] * solid.size, o["hover"] * solid.size
    if depth < 0 or hover < 0:
        raise bif.BifError("%s: depth and hover cannot be negative" % name)
    fps, sh = o["fps"], o["shadow"]
    states = []
    for kind, p in segments:
        if kind == "pop":
            states += bif3d.pop_path(_frames_for(p["time"], fps), depth, hover, view, fps, sh)
        elif kind == "hold":
            states += bif3d.hold_path(p["time"], depth, hover, view, sh)
        elif kind == "flat":
            states += bif3d.flat_path(p["frames"], p["ms"])
        elif kind == "spin":
            sign = 1.0 if p["speed"] >= 0 else -1.0
            n = max(4, int(round(360.0 * p["turns"] / max(1.0, abs(p["speed"])) * fps)))
            states += bif3d.spin_path(n, depth, hover, view, p["turns"], fps, sh, sign)
        elif kind == "sway":
            states += bif3d.sway_path(_frames_for(p["time"], fps), depth, hover, view, p["degrees"], fps, sh)
        elif kind == "still":
            states.append(bif3d.State(depth=depth, hover=hover, yaw=view[0], pitch=view[1], roll=view[2], shadow=sh))
        else:
            raise bif.BifError("%s: no move '%s'" % (name, kind))
    if not states:
        raise bif.BifError("%s: no frames" % name)
    images, lo, hi = bif3d.render_frames(solid, states, o["perspective"], _workers())
    cw, chh = images[0].size
    sx, sy = r.sx, r.sy
    bounds = [0, 0, cw / sx, chh / sy]
    frames = []
    for st, im in zip(states, images):
        a = np.asarray(im)
        f = bif.Frame(duration=int(round(st.duration)) if st.duration else None)
        f.layers.append(bif.raster_layer(alpha=np.ascontiguousarray(a[..., 3]), rgb=np.ascontiguousarray(a[..., :3]),
                                         id="solid", bounds=bounds))
        frames.append(f)
    bifop.drop_grid(pic)
    pic.frames = frames
    pic.width, pic.height = int(math.ceil(bounds[2] - 1e-9)), int(math.ceil(bounds[3] - 1e-9))
    pic.unit_aspect = src.unit_aspect
    pic.animation = {"loop": 0} if len(frames) > 1 else None
    pic.meta["solid"] = {"tall": o["tall"], "depth": o["depth"], "hover": o["hover"], "view": list(view), "material": o["material"] or "picture",
                         "perspective": o["perspective"], "fps": fps}


def _opts(kw):
    return dict((k, kw[k]) for k in [c[0] for c in COMMON])


@op("extrude", common(0.0), "A still of the picture as a solid: extruded to `depth`, turned to `view`, lit, on its shadow.")
def op_extrude(pic, notes, **kw):
    _lift(pic, notes, "extrude", [("still", {})], _opts(kw))


@op("spin", COMMON + [("speed", _float, 90.0, "degrees a second (negative: the other way)"),
                      ("turns", _float, 1.0, "how many turns; one is a seamless loop")],
    "Turns the solid about the vertical axis: a seamless loop of frames (bidet3d --spin).")
def op_spin(pic, notes, speed, turns, **kw):
    if turns <= 0:
        raise bif.BifError("spin: turns must be positive")
    _lift(pic, notes, "spin", [("spin", {"speed": speed, "turns": turns})], _opts(kw))


@op("sway", COMMON + [("degrees", _float, 25.0, "swing this far each side of the view"),
                      ("time", _float, 4.0, "seconds for there and back")],
    "Swings the solid to and back: a seamless loop of frames (bidet3d --sway).")
def op_sway(pic, notes, degrees, time, **kw):
    _lift(pic, notes, "sway", [("sway", {"degrees": degrees, "time": time})], _opts(kw))


@op("popout", COMMON + [("time", _float, 1.6, "seconds it takes")],
    "The picture flat on the screen, then it grows its depth, rises toward the viewer on a shadow that parts from it, and "
    "turns to the view: 2D to 3D, popping out of the screen.  The first frame is the flat picture.")
def op_popout(pic, notes, time, **kw):
    _lift(pic, notes, "popout", [("pop", {"time": time})], _opts(kw))


@op("motion", COMMON + [("path", _ids, REQUIRED, "moves one after another: flat tick pop hold spin sway still (pop+hold+spin)"),
                        ("time", _float, 1.6, "seconds of a pop"),
                        ("hold", _float, 1.0, "seconds of a hold"),
                        ("flat", _float, 1.0, "seconds of flat: the picture as it is, on the screen"),
                        ("ticks", _int, 24, "tick: how many frames of flat (to lay a ticker or a caption over, one each)"),
                        ("tickms", _float, 40.0, "tick: milliseconds each"),
                        ("speed", _float, 90.0, "spin: degrees a second"),
                        ("turns", _float, 1.0, "spin: turns"),
                        ("degrees", _float, 25.0, "sway: each side"),
                        ("swing", _float, 4.0, "sway: seconds for there and back")],
    "Several moves in one go, each starting where the last stopped: path=pop+hold+spin is the picture popping out of the "
    "screen, resting a moment, then turning; flat+tick+pop starts with the picture as it is.")
def op_motion(pic, notes, path, time, hold, flat, ticks, tickms, speed, turns, degrees, swing, **kw):
    segs = []
    for name in path:
        if name == "pop":
            segs.append(("pop", {"time": time}))
        elif name == "hold":
            segs.append(("hold", {"time": hold}))
        elif name == "flat":
            segs.append(("flat", {"frames": 1, "ms": flat * 1000.0}))
        elif name == "tick":
            segs.append(("flat", {"frames": max(1, ticks), "ms": tickms}))
        elif name == "spin":
            segs.append(("spin", {"speed": speed, "turns": turns}))
        elif name == "sway":
            segs.append(("sway", {"degrees": degrees, "time": swing}))
        elif name == "still":
            segs.append(("still", {}))
        else:
            raise bif.BifError("motion: no move '%s' (flat, tick, pop, hold, spin, sway, still)" % name)
    _lift(pic, notes, "motion", segs, _opts(kw))
