#!/usr/bin/env python3
"""ttfglyphs: glyph outlines from a TrueType font, standard library and numpy only.

    f = TrueType("DejaVuSansMono.ttf")            # raises Unsupported for CFF (.otf) and other fonts
    f.units_per_em
    f.contours(ord("g"), tol=2.0)                 # [[(x, y), ...], ...] closed polygons in font units, y up
    f.glyph_id(ord("g"))                          # 0 = .notdef

Reads head, maxp, cmap (formats 4 and 12), loca, glyf (simple and composite glyphs) and, for .ttc
collections, the first (or numbered) font.  Quadratic curves are flattened to the given tolerance.  This is
what lets text in BIF be vector outlines; where it cannot read a font the importer falls back to a raster.
Python 3.7+.
"""
from __future__ import print_function

import math
import struct


class Unsupported(Exception):
    """The font is not one this reader can use (CFF outlines, a broken table, ...)."""


def _u16(b, o):
    return struct.unpack_from(">H", b, o)[0]


def _i16(b, o):
    return struct.unpack_from(">h", b, o)[0]


def _u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


class TrueType(object):
    MAX_DEPTH = 6

    def __init__(self, path, index=0):
        with open(path, "rb") as f:
            self.data = d = f.read()
        base = 0
        if d[:4] == b"ttcf":
            try:
                base = _u32(d, 12 + 4 * index)
            except struct.error:
                raise Unsupported("no font %d in the collection" % index)
        if d[base:base + 4] not in (b"\x00\x01\x00\x00", b"true"):
            raise Unsupported("not a TrueType-outline font")
        try:
            n = _u16(d, base + 4)
            self.tables = {}
            for i in range(n):
                tag, _crc, off, length = struct.unpack_from(">4sIII", d, base + 12 + 16 * i)
                self.tables[tag.decode("latin1")] = (off, length)
            for need in ("head", "maxp", "cmap", "loca", "glyf"):
                if need not in self.tables:
                    raise Unsupported("no %s table" % need)
            head = self.tables["head"][0]
            self.units_per_em = _u16(d, head + 18)
            self._loca_long = _i16(d, head + 50) != 0
            self.num_glyphs = _u16(d, self.tables["maxp"][0] + 4)
            self._cmap = self._find_cmap()
        except (struct.error, IndexError):
            raise Unsupported("damaged font tables")
        if self.units_per_em <= 0:
            raise Unsupported("bad unitsPerEm")
        self._ids = {}
        self._cache = {}

    # -- character map -----------------------------------------------------------------------
    def _find_cmap(self):
        d = self.data
        off = self.tables["cmap"][0]
        n = _u16(d, off + 2)
        best = None
        for i in range(n):
            plat, enc, sub = struct.unpack_from(">HHI", d, off + 4 + 8 * i)
            fmt = _u16(d, off + sub)
            rank = {(3, 10, 12): 4, (0, 4, 12): 4, (3, 1, 4): 3, (0, 3, 4): 2, (0, 4, 4): 2}.get((plat, enc, fmt))
            if rank is None and fmt in (4, 12) and plat in (0, 3):
                rank = 1
            if rank and (best is None or rank > best[0]):
                best = (rank, off + sub, fmt)
        if best is None:
            raise Unsupported("no usable Unicode cmap")
        return best[1], best[2]

    def glyph_id(self, cp):
        g = self._ids.get(cp)
        if g is None:
            g = self._ids[cp] = self._lookup(cp)
        return g

    def _lookup(self, cp):
        d = self.data
        off, fmt = self._cmap
        if fmt == 12:
            n = _u32(d, off + 12)
            lo, hi = 0, n - 1
            while lo <= hi:
                mid = (lo + hi) // 2
                s, e, g = struct.unpack_from(">III", d, off + 16 + 12 * mid)
                if cp < s:
                    hi = mid - 1
                elif cp > e:
                    lo = mid + 1
                else:
                    return g + cp - s
            return 0
        if cp > 0xFFFF:
            return 0
        segx2 = _u16(d, off + 6)
        seg = segx2 // 2
        ends, starts = off + 14, off + 16 + segx2
        deltas, ranges = starts + segx2, starts + 2 * segx2
        lo, hi = 0, seg - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if _u16(d, ends + 2 * mid) < cp:
                lo = mid + 1
            else:
                hi = mid - 1
        if lo >= seg:
            return 0
        start = _u16(d, starts + 2 * lo)
        if cp < start:
            return 0
        delta, ro = _u16(d, deltas + 2 * lo), _u16(d, ranges + 2 * lo)
        if ro == 0:
            return (cp + delta) & 0xFFFF
        g = _u16(d, ranges + 2 * lo + ro + 2 * (cp - start))
        return (g + delta) & 0xFFFF if g else 0

    # -- metrics: how wide, how tall, how close ----------------------------------------------
    def metrics(self):
        """{"ascent", "descent", "line_gap"} in font units (descent positive, below the baseline), from the hhea
        table, else from the font's bounding box."""
        if "hhea" in self.tables:
            o = self.tables["hhea"][0]
            try:
                asc, desc, gap = _i16(self.data, o + 4), _i16(self.data, o + 6), _i16(self.data, o + 8)
                if asc - desc > 0:
                    return {"ascent": asc, "descent": -desc, "line_gap": max(0, gap)}
            except struct.error:
                pass
        h = self.tables["head"][0]
        return {"ascent": _i16(self.data, h + 42), "descent": -_i16(self.data, h + 38), "line_gap": 0}

    def advance(self, gid):
        """Horizontal advance of a glyph in font units (hmtx; glyphs past the last full record share its advance)."""
        if "hmtx" not in self.tables or "hhea" not in self.tables:
            return self.units_per_em // 2
        if not hasattr(self, "_nhm"):
            self._nhm = max(1, _u16(self.data, self.tables["hhea"][0] + 34))
        o = self.tables["hmtx"][0]
        try:
            return _u16(self.data, o + 4 * min(gid, self._nhm - 1))
        except struct.error:
            return self.units_per_em // 2

    def kerning(self):
        """{(left glyph, right glyph): adjustment in font units} from the legacy `kern` table (horizontal, format 0).
        Fonts that only have GPOS kerning give an empty dict: they are laid out without it."""
        if hasattr(self, "_kern"):
            return self._kern
        pairs = {}
        if "kern" in self.tables:
            d, o = self.data, self.tables["kern"][0]
            try:
                version, n = _u16(d, o), _u16(d, o + 2)
                p = o + 4
                for _ in range(n if version == 0 else 0):
                    length, coverage = _u16(d, p + 2), _u16(d, p + 4)
                    if coverage >> 8 == 0 and coverage & 1 and not coverage & 4:        # format 0, horizontal, not cross-stream
                        count = _u16(d, p + 6)
                        for i in range(count):
                            left, right, val = struct.unpack_from(">HHh", d, p + 14 + 6 * i)
                            pairs[(left, right)] = val
                    p += max(length, 6)
            except struct.error:
                pass
        self._kern = pairs
        return pairs

    def names(self):
        """{"family", "style", "full", "bold", "italic"} from the name and head tables."""
        return _names_of(self.data, self.tables)

    # -- glyphs ------------------------------------------------------------------------------
    def _glyph_span(self, gid):
        if not 0 <= gid < self.num_glyphs:
            return None
        lo = self.tables["loca"][0]
        d = self.data
        if self._loca_long:
            a, b = _u32(d, lo + 4 * gid), _u32(d, lo + 4 * gid + 4)
        else:
            a, b = 2 * _u16(d, lo + 2 * gid), 2 * _u16(d, lo + 2 * gid + 2)
        return None if b <= a else (self.tables["glyf"][0] + a, b - a)

    def _points(self, gid, depth=0):
        """The glyph's contours as lists of (x, y, on_curve) in font units."""
        span = self._glyph_span(gid)
        if span is None or depth > self.MAX_DEPTH:
            return []
        d = self.data
        o = span[0]
        nc = _i16(d, o)
        o += 10
        if nc >= 0:
            return self._simple(o, nc)
        out = []
        while True:
            flags, sub = _u16(d, o), _u16(d, o + 2)
            o += 4
            if flags & 1:
                a1, a2 = _i16(d, o), _i16(d, o + 2)
                o += 4
            else:
                a1, a2 = struct.unpack_from(">bb", d, o)
                o += 2
            m = [1.0, 0.0, 0.0, 1.0]
            if flags & 0x08:
                m[0] = m[3] = _i16(d, o) / 16384.0
                o += 2
            elif flags & 0x40:
                m[0], m[3] = _i16(d, o) / 16384.0, _i16(d, o + 2) / 16384.0
                o += 4
            elif flags & 0x80:
                m = [_i16(d, o + 2 * k) / 16384.0 for k in range(4)]     # xscale, scale01, scale10, yscale
                o += 8
            dx, dy = (a1, a2) if flags & 2 else (0, 0)                   # (point matching is not supported)
            for c in self._points(sub, depth + 1):
                out.append([(m[0] * x + m[2] * y + dx, m[1] * x + m[3] * y + dy, on) for x, y, on in c])
            if not flags & 0x20:
                return out

    def _simple(self, o, nc):
        d = self.data
        if nc == 0:
            return []
        ends = [_u16(d, o + 2 * i) for i in range(nc)]
        o += 2 * nc
        o += 2 + _u16(d, o)                                              # skip the instructions
        n = ends[-1] + 1
        flags = []
        while len(flags) < n:
            f = d[o]
            o += 1
            flags.append(f)
            if f & 8:
                r = d[o]
                o += 1
                flags.extend([f] * r)
        flags = flags[:n]
        xs, ys, v = [], [], 0
        for f in flags:
            if f & 2:
                dv = d[o]
                o += 1
                v += dv if f & 0x10 else -dv
            elif not f & 0x10:
                v += _i16(d, o)
                o += 2
            xs.append(v)
        v = 0
        for f in flags:
            if f & 4:
                dv = d[o]
                o += 1
                v += dv if f & 0x20 else -dv
            elif not f & 0x20:
                v += _i16(d, o)
                o += 2
            ys.append(v)
        out, s = [], 0
        for e in ends:
            out.append([(xs[i], ys[i], bool(flags[i] & 1)) for i in range(s, e + 1)])
            s = e + 1
        return out

    def contours(self, cp, tol=1.0):
        """Closed polygons [[(x, y), ...], ...] (font units, y up) for a code point, curves flattened to `tol`
        font units.  A missing character gives the font's .notdef box (glyph 0), as a renderer would."""
        key = (cp, tol)
        c = self._cache.get(key)
        if c is None:
            try:
                c = [_flatten(p, tol) for p in self._points(self.glyph_id(cp))]
            except (struct.error, IndexError):
                raise Unsupported("damaged glyph data")
            c = [p for p in c if len(p) >= 3]
            self._cache[key] = c
        return c


def _decode_name(raw, platform):
    try:
        return raw.decode("utf-16-be") if platform in (0, 3) else raw.decode("mac-roman")
    except (UnicodeDecodeError, LookupError):
        return raw.decode("latin-1")


def _names_of(d, tables, base=0):
    """Family and style names of a font whose tables are in `d` (the whole file or enough of it: offsets are
    relative to `base`)."""
    out = {"family": "", "style": "", "full": "", "bold": False, "italic": False}
    if "name" in tables:
        o = tables["name"][0] - base
        try:
            count, sto = _u16(d, o + 2), _u16(d, o + 4)
            best = {}
            for i in range(count):
                plat, enc, lang, nid, length, off = struct.unpack_from(">HHHHHH", d, o + 6 + 12 * i)
                if nid not in (1, 2, 4, 16, 17):
                    continue
                rank = 2 if (plat == 3 and lang == 0x409) else (1 if plat in (0, 3) else 0)      # English first
                text = _decode_name(d[o + sto + off:o + sto + off + length], plat).strip("\x00 ")
                if text and rank >= best.get(nid, (-1, ""))[0]:
                    best[nid] = (rank, text)
            fam = best.get(16) or best.get(1)
            sty = best.get(17) or best.get(2)
            out["family"], out["style"] = fam[1] if fam else "", sty[1] if sty else ""
            out["full"] = best.get(4, (0, ""))[1]
        except struct.error:
            pass
    if "head" in tables:
        try:
            mac = _u16(d, tables["head"][0] - base + 44)
            out["bold"], out["italic"] = bool(mac & 1), bool(mac & 2)
        except struct.error:
            pass
    low = out["style"].lower() + " " + out["full"].lower()
    out["bold"] = out["bold"] or "bold" in low or "black" in low or "heavy" in low
    out["italic"] = out["italic"] or "italic" in low or "oblique" in low
    return out


def read_names(path, index=0):
    """names() of a font file without reading all of it (only the table directory and the small tables), or None
    if it is not a TrueType-outline font.  What a font catalogue needs: a system can have hundreds of fonts."""
    try:
        with open(path, "rb") as f:
            head = f.read(12)
            base = 0
            if head[:4] == b"ttcf":
                f.seek(12 + 4 * index)
                base = struct.unpack(">I", f.read(4))[0]
                f.seek(base)
                head = f.read(12)
            if head[:4] not in (b"\x00\x01\x00\x00", b"true"):
                return None
            n = struct.unpack(">H", head[4:6])[0]
            if n > 200:
                return None
            f.seek(base + 12)
            raw = f.read(16 * n)
            tables = {}
            for i in range(n):
                tag, _crc, off, length = struct.unpack_from(">4sIII", raw, 16 * i)
                tables[tag.decode("latin1")] = (off, length)
            if "glyf" not in tables:
                return None
            small = {}
            for tag in ("name", "head"):
                if tag in tables and tables[tag][1] < 1 << 20:
                    f.seek(tables[tag][0])
                    small[tag] = f.read(tables[tag][1])
        # present the two small tables as one buffer, with tables at the offsets _names_of expects
        buf, tabs, pos = b"", {}, 0
        for tag in ("name", "head"):
            if tag in small:
                tabs[tag] = (pos, len(small[tag]))
                buf += small[tag]
                pos += len(small[tag])
        return _names_of(buf, tabs)
    except (IOError, OSError, struct.error):
        return None


def _quad(p0, c, p1, tol, out):
    d = math.hypot(p0[0] - 2 * c[0] + p1[0], p0[1] - 2 * c[1] + p1[1])
    n = max(1, int(math.ceil(math.sqrt(d / (4.0 * tol))))) if d > 0 else 1
    for i in range(1, n + 1):
        t = i / float(n)
        u = 1.0 - t
        out.append((u * u * p0[0] + 2 * u * t * c[0] + t * t * p1[0], u * u * p0[1] + 2 * u * t * c[1] + t * t * p1[1]))


def _flatten(pts, tol):
    """One contour of (x, y, on_curve) -> polygon, with TrueType's implied on-curve midpoints."""
    if pts[0][2]:
        start, rest = pts[0], pts[1:]
    elif pts[-1][2]:
        start, rest = pts[-1], pts[:-1]
    else:
        start, rest = ((pts[0][0] + pts[-1][0]) / 2.0, (pts[0][1] + pts[-1][1]) / 2.0, True), list(pts)
    out = [(start[0], start[1])]
    cur, ctrl = (start[0], start[1]), None
    for p in rest + [start]:
        pt = (p[0], p[1])
        if p[2]:
            if ctrl is None:
                out.append(pt)
            else:
                _quad(cur, ctrl, pt, tol, out)
                ctrl = None
            cur = pt
        else:
            if ctrl is not None:
                mid = ((ctrl[0] + pt[0]) / 2.0, (ctrl[1] + pt[1]) / 2.0)
                _quad(cur, ctrl, mid, tol, out)
                cur = mid
            ctrl = pt
    if len(out) > 1 and out[-1] == out[0]:
        out.pop()                                                       # closed: the last point is the first
    return out
