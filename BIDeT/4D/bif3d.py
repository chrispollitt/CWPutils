"""bif3d: the 3D stage of BIDeT 4D: a flat picture lifted off the screen, extruded, turned and lit.

    solid = Solid(rgb, alpha, material="rainbow")           # any flat picture's colour and coverage
    states = pop_path(...) + spin_path(...)                  # one State per frame: depth, hover, view, ...
    frames = render_frames(solid, states, persp=2.5)         # RGBA images on one fixed canvas

A small software renderer (Pillow + numpy), the idea of bidet3d's: not a mesher.  The face is the picture, the extrusion is
a dense stack of copies of its silhouette, shaded by which way the edge faces, seen through a perspective camera, so
turning, pitch, roll and animation all come from the same math.  What is new in 4D is the *screen*: the picture starts
flat on it, and can rise toward the viewer, growing its depth as it goes, throwing a soft shadow on the page that
parts from it as it climbs ("pop out of the screen").  At depth 0 and hover 0 the picture is exactly the flat one.

Units are pixels of the flat rendering; x right, y down, z away from the viewer, so toward the viewer is negative.
The slab's back is at local z = +depth/2 and its face at -depth/2; it turns about its middle, which hovers at
z = -(depth/2 + hover) in front of the screen (z = 0).
"""
from __future__ import print_function

import math

import numpy as np
from PIL import Image, ImageChops, ImageFilter

SLICE_DENSITY = 2.0        # slices per output pixel of extrusion; higher = smoother near edge-on
MAX_SLICES = 320
SIDE_LEVELS = 48           # distinct extrusion shades (cached per level)
BEVEL_LEVELS = 10          # distinct bevel strengths of the face (cached per level)
SHADOW_SLICES = 14         # the shadow is soft, so it needs fewer
MAX_PIXELS = 60000000
LIGHT = np.array([-0.45, -0.55, 0.70], np.float32)
LIGHT /= np.linalg.norm(LIGHT)
SHADOW_DIR = (0.30, 0.40)                             # the shadow of a point h above the screen lands this far over, per h (a high lamp)


def C(h):
    """'#rrggbb' -> (r, g, b)"""
    h = h.strip()
    if len(h) == 4 and h[0] == "#":
        h = "#" + "".join(c * 2 for c in h[1:])
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


# ---------------------------------------------------------------------------------------------
# Materials: the faces and sides of bidet3d's css3wordart presets that make sense on any picture
#   fill: ("linear", "v"|"h", [(0..1, hex)]) | ("radial", stops) | ("solid", hex);  side: (back, front);  bevel: 0..1
# ---------------------------------------------------------------------------------------------
MATERIALS = {
    "rainbow": (("linear", "h", [(0, "#ee00ff"), (.16, "#ff3030"), (.32, "#ff9900"), (.49, "#fff430"), (.67, "#00ff08"),
                                 (.83, "#3223ff"), (1, "#aa00ff")]), ("#2a1040", "#5a2a7a"), 0.25),
    "chrome": (("linear", "v", [(0, "#b5b5b5"), (.23, "#4f4f4f"), (.64, "#f9f9f9"), (.69, "#212121"), (1, "#d3d3d3")]),
               ("#2B2B2B", "#6D6D6D"), 0.5),
    "gold": (("radial", [(0, "#fffa28"), (1, "#ec8a39")]), ("#7f5a10", "#c8962a"), 0.35),
    "superhero": (("linear", "v", [(0, "#fdea00"), (.44, "#fdcf00"), (1, "#fc2700")]), ("#802700", "#c23d00"), 0.25),
    "sunset": (("linear", "v", [(0, "#fafacc"), (1, "#f3919b")]), ("#081A33", "#114491"), 0.25),
    "aqua": (("linear", "v", [(0, "#828dfb"), (1, "#378484")]), ("#4a5560", "#B3B3B3"), 0.25),
    "blues": (("solid", "#24c0fd"), ("#00005a", "#0000aa"), 0.25),
    "purple": (("linear", "v", [(0, "#4222be"), (.73, "#a62cc1"), (1, "#a62cc1")]), ("#4a52c8", "#828DFB"), 0.25),
    "slate": (("solid", "#2F5485"), ("#8a8a8a", "#b3b3b3"), 0.25),
    "lime": (("solid", "#71F504"), ("#00116B", "#0a2090"), 0.25),
    "cornflower": (("solid", "#6495ed"), ("#1b2a4a", "#3e5c99"), 0.25),
    "graphite": (("linear", "h", [(0, "#606060"), (.5, "#ffffff"), (1, "#606060")]), ("#27271F", "#60614B"), 0.4),
    "brick": (("solid", "#4E0E0E"), ("#7C3E2C", "#E8703C"), 0.25),
    "cobalt": (("solid", "#1657BD"), ("#4d0d0d", "#771515"), 0.25),
    "horizon": (("linear", "v", [(0, "#7286a7"), (.13, "#7286a7"), (.5, "#ffffff"), (.56, "#812f30"), (1, "#ffffff")]),
                ("#161616", "#8d8d8d"), 0.25),
}


def lerp_stops(t, stops):
    pos = [s[0] for s in stops]
    cols = np.array([C(s[1]) for s in stops], np.float32)
    return np.stack([np.interp(t, pos, cols[:, i]) for i in range(3)], -1).astype(np.float32)


def make_fill(spec, w, h, bbox):
    kind = spec[0]
    x0, y0, x1, y1 = bbox
    if kind == "solid":
        out = np.empty((h, w, 3), np.float32)
        out[:] = C(spec[1])
        return out
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if kind == "linear":
        t = (yy - y0) / max(1.0, y1 - y0) if spec[1] == "v" else (xx - x0) / max(1.0, x1 - x0)
        return lerp_stops(np.clip(t, 0, 1), spec[2])
    nx = (xx - (x0 + x1) / 2.0) / max(1.0, (x1 - x0) / 2.0)
    ny = (yy - (y0 + y1) / 2.0) / max(1.0, (y1 - y0) / 2.0)
    return lerp_stops(np.clip(np.hypot(nx, ny) / 1.4142, 0, 1), spec[1])


# ---------------------------------------------------------------------------------------------
# The solid
# ---------------------------------------------------------------------------------------------
class Solid(object):
    """A flat picture (rgb: float or uint8 (H, W, 3) straight colour; alpha: (H, W) 0..1) to be extruded.
    material: a name in MATERIALS (face colours from it), a '#rrggbb' (one colour), or None (the picture's own colours).
    side: (back, front) colours of the extrusion, else the material's, else made from the face.  bevel: strength of the
    edge lighting of the face (None: the material's, else 0.3)."""

    def __init__(self, rgb, alpha, material=None, side=None, bevel=None):
        self.alpha = np.clip(np.asarray(alpha, np.float32), 0.0, 1.0)
        self.H, self.W = self.alpha.shape
        ys, xs = np.nonzero(self.alpha > 0.03)
        if not len(ys):
            raise ValueError("the picture draws nothing, so there is nothing to extrude")
        self.bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        self.size = float(min(self.bbox[2] - self.bbox[0], self.bbox[3] - self.bbox[1]))   # the ink's shorter side
        rgb = np.broadcast_to(np.asarray(rgb, np.float32), (self.H, self.W, 3))
        spec = None
        if material:
            if material in MATERIALS:
                spec, mside, mbevel = MATERIALS[material]
            elif material.startswith("#"):
                spec, mside, mbevel = ("solid", material), None, 0.3
            else:
                raise ValueError("no material '%s' (have: %s, or a #rrggbb)" % (material, ", ".join(sorted(MATERIALS))))
        else:
            mside, mbevel = None, 0.3
        self.bevel = mbevel if bevel is None else bevel
        self.flat = np.array(rgb)                                    # the picture's own colours
        self.fill = make_fill(spec, self.W, self.H, self.bbox) if spec else self.flat
        solid = self.alpha > 0.5
        avg = self.fill[solid].mean(axis=0) if solid.any() else np.array([128.0] * 3, np.float32)
        side = side or mside
        if side:
            self.back, self.front = (np.array(C(c), np.float32) for c in side)
        elif 0.299 * avg[0] + 0.587 * avg[1] + 0.114 * avg[2] < 60:          # black ink: grey sides, or they would not show
            self.back, self.front = np.array([58.0] * 3, np.float32), np.array([154.0] * 3, np.float32)
        else:
            self.back, self.front = avg * 0.25, avg * 0.55
        # lighting, found once: the face's bevel (from a blurred height of the coverage) and the sides' shade
        u8 = (self.alpha * 255 + 0.5).astype(np.uint8)
        sz = max(8.0, self.size * 1.4)
        sig = max(1.0, 0.045 * sz)
        hmap = np.asarray(Image.fromarray(u8).filter(ImageFilter.GaussianBlur(sig)), np.float32) / 255.0
        gy, gx = np.gradient(hmap)
        k = sig * 3.0
        n = np.stack([-gx * k, -gy * k, np.ones_like(gx)], -1)
        n /= np.linalg.norm(n, axis=-1, keepdims=True)
        self.bevel_raw = 2.4 * (n.dot(LIGHT) - LIGHT[2])
        sig2 = max(1.0, 0.025 * sz)
        sm = np.asarray(Image.fromarray(u8).filter(ImageFilter.GaussianBlur(sig2)), np.float32) / 255.0
        sy_, sx_ = np.gradient(sm)
        mag = np.hypot(sx_, sy_)
        facing = np.where(mag > 1e-4, (-sx_ * LIGHT[0] - sy_ * LIGHT[1]) / np.maximum(mag, 1e-4), 0.0)
        shade = 0.55 + 0.75 * np.clip(facing * 0.5 + 0.5, 0, 1)
        self.side_shade = np.where(mag > 1e-4, shade, 0.8).astype(np.float32)[..., None]
        self.sil = u8
        self._sil_img = Image.fromarray(u8)
        self._faces, self._sides = {}, {}

    def face(self, bevel_scale, paint=1.0):
        """The front, as an RGBA image: its colours, lit by the bevel (scaled 0..1: no bevel while it is flat).
        paint: 0 = the picture's own colours, 1 = the material (between: a blend, as it pops out)."""
        lvl = int(round(min(1.0, max(0.0, bevel_scale)) * BEVEL_LEVELS))
        plvl = int(round(min(1.0, max(0.0, paint)) * BEVEL_LEVELS)) if self.fill is not self.flat else BEVEL_LEVELS
        img = self._faces.get((lvl, plvl))
        if img is None:
            shade = 1.0 + (lvl / float(BEVEL_LEVELS)) * self.bevel * self.bevel_raw
            base = self.fill if plvl == BEVEL_LEVELS else self.flat + (self.fill - self.flat) * (plvl / float(BEVEL_LEVELS))
            rgb = np.clip(base * np.clip(shade, 0.35, 1.6)[..., None], 0, 255).astype(np.uint8)
            img = self._faces[(lvl, plvl)] = Image.fromarray(np.dstack([rgb, self.sil]))
        return img

    def side(self, t):
        """The extrusion's colour at t (0 at the face, 1 at the back), as an RGBA image."""
        lvl = int(round(min(1.0, max(0.0, t)) * SIDE_LEVELS))
        img = self._sides.get(lvl)
        if img is None:
            col = self.front * (1 - lvl / float(SIDE_LEVELS)) + self.back * (lvl / float(SIDE_LEVELS))
            rgb = np.clip(self.side_shade * col, 0, 255).astype(np.uint8)
            img = self._sides[lvl] = Image.fromarray(np.dstack([rgb, self.sil]))
        return img


# ---------------------------------------------------------------------------------------------
# What a frame looks like
# ---------------------------------------------------------------------------------------------
class State(object):
    """One frame: depth and hover in pixels (of the flat picture), the view in degrees, how much bevel the face has
    (0..1: it is flat while it grows), and the shadow's strength (0 hides it)."""

    def __init__(self, depth=0.0, hover=0.0, yaw=0.0, pitch=0.0, roll=0.0, bevel=1.0, shadow=1.0, duration=None, paint=1.0):
        self.depth, self.hover, self.yaw, self.pitch, self.roll = depth, hover, yaw, pitch, roll
        self.bevel, self.shadow, self.duration, self.paint = bevel, shadow, duration, paint

    def view(self):
        return (self.yaw, self.pitch, self.roll)

    def __repr__(self):
        return "<State depth %.0f hover %.0f view %.0f,%.0f,%.0f>" % (self.depth, self.hover, self.yaw, self.pitch, self.roll)


def rot_matrix(yaw, pitch, roll):
    """x right, y down, z away from the viewer.  yaw: right edge recedes; pitch: top edge recedes; roll: clockwise."""
    y, p, r = (math.radians(a) for a in (yaw, pitch, roll))
    cy, sy = math.cos(y), math.sin(y)
    cp, sp = math.cos(p), math.sin(p)
    cr, sr = math.cos(r), math.sin(r)
    Ry = np.array([[cy, 0, -sy], [0, 1, 0], [sy, 0, cy]])
    Rx = np.array([[1, 0, 0], [0, cp, sp], [0, -sp, cp]])
    Rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]])
    return Rz.dot(Rx).dot(Ry)


def persp_coeffs(dest, src):
    A, B = [], []
    for (X, Y), (x, y) in zip(dest, src):
        A.append([X, Y, 1, 0, 0, 0, -X * x, -Y * x])
        B.append(x)
        A.append([0, 0, 0, X, Y, 1, -X * y, -Y * y])
        B.append(y)
    return np.linalg.solve(np.array(A, float), np.array(B, float))


class Camera(object):
    """Where the corners of a slice of the solid are, in the world and on the screen."""

    def __init__(self, solid, persp):
        self.solid = solid
        self.f = persp * max(solid.W, solid.H)
        hw, hh = solid.W / 2.0, solid.H / 2.0
        self.corners = np.array([[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]])

    def world(self, st, z):
        """The 4 corners (x, y, Z) of the slice at local z, turned and moved to where `st` puts the solid."""
        R = rot_matrix(*st.view())
        P = np.c_[self.corners, np.full(4, float(z))].dot(R.T)
        P[:, 2] -= st.depth / 2.0 + st.hover
        return P

    def project(self, P):
        fac = self.f / np.maximum(self.f + P[:, 2], 0.05 * self.f)
        return np.stack([P[:, 0] * fac, P[:, 1] * fac], 1)

    def shadow(self, P):
        """Where those corners' shadows fall on the screen (the plane Z = 0)."""
        h = np.maximum(-P[:, 2], 0.0)
        return np.stack([P[:, 0] + SHADOW_DIR[0] * h, P[:, 1] + SHADOW_DIR[1] * h], 1)


def shadow_look(st, solid):
    """(opacity, blur sigma in px) of the shadow: absent while the solid lies on the screen, then softer and fainter as it climbs."""
    h = st.depth + st.hover                                  # how high the face is above the screen
    k = min(1.0, h / (0.05 * solid.size)) if solid.size > 0 else 0.0
    return st.shadow * 0.55 * k / (1.0 + h / (0.9 * solid.size)), 1.0 + 0.10 * h


def bounds_of(solid, states, persp):
    """(lo, hi): the region of the screen (px, around the picture's centre) that any of the frames draws on, shadows too."""
    cam = Camera(solid, persp)
    lo = np.array([1e9, 1e9])
    hi = -lo
    lo = np.minimum(lo, cam.corners.min(0))                      # (the flat picture is always inside)
    hi = np.maximum(hi, cam.corners.max(0))
    for st in states:
        pts = []
        for z in (-st.depth / 2.0, st.depth / 2.0):
            P = cam.world(st, z)
            pts.append(cam.project(P))
            op, sig = shadow_look(st, solid)
            if op > 0.01:
                s = cam.shadow(P)
                pts.append(s - 3 * sig)
                pts.append(s + 3 * sig)
        q = np.concatenate(pts)
        lo = np.minimum(lo, q.min(0))
        hi = np.maximum(hi, q.max(0))
    return np.floor(lo) - 2, np.ceil(hi) + 2


def render(solid, st, persp, bounds):
    """One frame as an RGBA PIL image covering `bounds` (lo, hi) of the screen.  Straight (not premultiplied) colour;
    the page is transparent, with the shadow, if any, as translucent black on it."""
    cam = Camera(solid, persp)
    lo, hi = bounds
    cw, chh = int(hi[0] - lo[0]), int(hi[1] - lo[1])
    if cw * chh > MAX_PIXELS:
        raise ValueError("the animation is too large (%dx%d): lower the resolution" % (cw, chh))
    canvas = Image.new("RGBA", (cw, chh), (0, 0, 0, 0))
    R = rot_matrix(*st.view())
    n = 1
    if st.depth > 0.5:
        q0 = cam.project(cam.world(st, -st.depth / 2.0))
        q1 = cam.project(cam.world(st, st.depth / 2.0))
        n = int(min(max(math.ceil(float(np.abs(q1 - q0).max()) * SLICE_DENSITY) + 1, 2), MAX_SLICES))
    zs = [(-st.depth / 2.0 + st.depth * k / float(max(1, n - 1))) for k in range(n)]
    src = [(0, 0), (solid.W, 0), (solid.W, solid.H), (0, solid.H)]

    def warp(img, q):
        q = q - lo
        x0 = max(0, int(math.floor(q[:, 0].min())) - 1)
        y0 = max(0, int(math.floor(q[:, 1].min())) - 1)
        x1 = min(cw, int(math.ceil(q[:, 0].max())) + 1)
        y1 = min(chh, int(math.ceil(q[:, 1].max())) + 1)
        if x1 <= x0 or y1 <= y0:
            return None
        try:
            co = persp_coeffs(q - (x0, y0), src)
        except np.linalg.LinAlgError:
            return None                                        # edge-on: the slice has no area
        return img.transform((x1 - x0, y1 - y0), Image.PERSPECTIVE, tuple(co), Image.BILINEAR), x0, y0

    # the shadow first: the silhouette of some slices, thrown on the screen, blurred and faded
    op, sig = shadow_look(st, solid)
    if op > 0.01:
        sh = Image.new("L", (cw, chh), 0)
        m = min(n, SHADOW_SLICES)
        for j in range(m):
            z = -st.depth / 2.0 + st.depth * j / float(max(1, m - 1))
            w = warp(solid._sil_img, cam.shadow(cam.world(st, z)))
            if w:
                part, x0, y0 = w
                box = sh.crop((x0, y0, x0 + part.width, y0 + part.height))
                sh.paste(ImageChops.lighter(box, part), (x0, y0))
        sh = sh.filter(ImageFilter.GaussianBlur(sig)).point(lambda v: int(v * op))
        canvas.paste(Image.merge("RGBA", (Image.new("L", sh.size, 0),) * 3 + (sh,)), (0, 0))

    # the solid, farthest slice first
    depthz = [(R.dot(np.array([0.0, 0.0, z])))[2] for z in zs]
    order = sorted(range(n), key=lambda k: -depthz[k])
    for k in order:
        if k == 0 and R[2, 2] > 0:
            img = solid.face(st.bevel, st.paint)               # the front cap, facing us
        else:
            img = solid.side(k / float(max(1, n - 1)))
        q = cam.project(cam.world(st, zs[k]))
        w = warp(img, q)
        if w:
            part, x0, y0 = w
            canvas.alpha_composite(part, (x0, y0))
    return canvas


def render_frames(solid, states, persp=2.5, workers=1, progress=None):
    """All the frames on one canvas.  Returns (images, lo, hi): RGBA images of the same size, and the region they cover
    (px around the picture's centre; (0, 0) of the flat picture is at (W/2, H/2) of that centre-relative frame)."""
    bounds = bounds_of(solid, states, persp)
    if workers > 1 and len(states) > 2:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(workers) as ex:
            images = []
            for im in ex.map(lambda st: render(solid, st, persp, bounds), states):
                images.append(im)
                if progress:
                    progress(len(images), len(states))
    else:
        images = []
        for i, st in enumerate(states):
            images.append(render(solid, st, persp, bounds))
            if progress:
                progress(i + 1, len(states))
    # the bounds are an estimate (a faint shadow far off is counted): cut to what any frame really shows
    box = None
    for im in images:
        b = im.getchannel("A").point(lambda v: 255 if v > 10 else 0).getbbox()
        if b:
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
    lo, hi = bounds
    if box:
        images = [im.crop(box) for im in images]
        lo = lo + np.array([box[0], box[1]], float)
        hi = lo + np.array(images[0].size, float)
    return images, lo, hi


# ---------------------------------------------------------------------------------------------
# Camera paths: lists of State
# ---------------------------------------------------------------------------------------------
def smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def out_back(t, s=1.4):
    """Eases out, overshooting a little before it settles: a spring."""
    t = min(1.0, max(0.0, t)) - 1.0
    return 1.0 + (s + 1.0) * t ** 3 + s * t * t


def lerp(a, b, t):
    return a + (b - a) * t


def pop_path(n, depth, hover, view, fps=15.0, shadow=1.0):
    """The picture flat on the screen, then: it grows its depth, rises toward the viewer (with a little overshoot) and
    turns to `view`.  The first frame is the flat picture; the last is the solid at rest at `view`."""
    out = []
    for i in range(n):
        u = i / float(max(1, n - 1))
        grow = smooth(u / 0.5)                                 # first half: the depth comes out of the screen
        rise = smooth((u - 0.25) / 0.75)                       # then it climbs and turns
        lift = out_back((u - 0.25) / 0.75)
        out.append(State(depth=depth * grow, hover=hover * lift, yaw=view[0] * rise, pitch=view[1] * rise,
                         roll=view[2] * rise, bevel=grow, paint=grow, shadow=shadow, duration=1000.0 / fps))
    return out


def hold_path(seconds, depth, hover, view, shadow=1.0):
    """The solid at rest at `view` for `seconds`: one frame that lasts that long."""
    return [State(depth=depth, hover=hover, yaw=view[0], pitch=view[1], roll=view[2], shadow=shadow,
                  duration=1000.0 * seconds)]


def flat_path(n, ms):
    """The picture flat on the screen, as n frames of `ms` milliseconds (one long frame, or a run for a ticker to be
    laid over).  Drawn through the same engine, so the frames agree with the ones that pop out of it."""
    return [State(depth=0.0, hover=0.0, bevel=0.0, paint=0.0, shadow=0.0, duration=ms) for _ in range(n)]


def spin_path(n, depth, hover, view, turns=1.0, fps=15.0, shadow=1.0, sign=1.0):
    """`turns` full turns about the vertical axis from the view's yaw, as n frames; one turn is a seamless loop."""
    return [State(depth=depth, hover=hover, yaw=view[0] + sign * 360.0 * turns * i / float(n), pitch=view[1], roll=view[2],
                  shadow=shadow, duration=1000.0 / fps) for i in range(n)]


def sway_path(n, depth, hover, view, degrees=25.0, fps=15.0, shadow=1.0):
    """The solid swings +-degrees about the view's yaw and back: a seamless loop of n frames."""
    return [State(depth=depth, hover=hover, yaw=view[0] + degrees * math.sin(2 * math.pi * i / float(n)), pitch=view[1],
                  roll=view[2], shadow=shadow, duration=1000.0 / fps) for i in range(n)]
