"""ttfbuild: write a tiny TrueType font for the tests (no font on the machine is needed, and every number is known).

    path = ttfbuild.write(path, family="Testface", style="Regular", kern={("A", "V"): -200})

Glyphs (1000 units per em, ascent 800, descent 200, line gap 100):
    .notdef   a 400-wide hollow box          A   a 600-wide solid square (0..500)
    B         700 wide, a square with a hole (two contours)           V   600 wide, a triangle
    space     300 wide, empty                i   a 300-wide bar, to have a narrow letter
Table cmap is format 4; `kern` is format 0 (legacy); `name` has English family and style records.
"""
from __future__ import print_function

import struct

UPEM, ASCENT, DESCENT, GAP = 1000, 800, 200, 100


def _simple(contours):
    """glyf record of closed all-on-curve polygons: [[(x, y), ...], ...]."""
    pts = [p for c in contours for p in c]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    out = struct.pack(">hhhhh", len(contours), min(xs), min(ys), max(xs), max(ys))
    ends, n = [], 0
    for c in contours:
        n += len(c)
        ends.append(n - 1)
    out += struct.pack(">%dH" % len(ends), *ends) + struct.pack(">H", 0)             # no instructions
    out += bytes(bytearray([1] * len(pts)))                                         # on-curve, 16-bit deltas
    for coords in (xs, ys):
        prev = 0
        for v in coords:
            out += struct.pack(">h", v - prev)
            prev = v
    return out + b"\0" * (-len(out) % 4)


def _glyphs():
    box = [(50, 0), (350, 0), (350, 700), (50, 700)]
    sq = [(0, 0), (500, 0), (500, 500), (0, 500)]
    outer = [(0, 0), (600, 0), (600, 700), (0, 700)]
    hole = [(150, 150), (150, 550), (450, 550), (450, 150)]                         # opposite winding: a hole
    tri = [(0, 0), (500, 0), (250, 700)]
    bar = [(50, 0), (250, 0), (250, 700), (50, 700)]
    # (character, advance, contours)
    return [(None, 400, [box, [(100, 50), (100, 650), (300, 650), (300, 50)]]), ("A", 600, [sq]), ("B", 700, [outer, hole]),
            ("V", 600, [tri]), (" ", 300, []), ("i", 300, [bar])]


def _table_dir(tables):
    n = len(tables)
    sr = 1
    while sr * 2 <= n:
        sr *= 2
    head = struct.pack(">IHHHH", 0x00010000, n, sr * 16, sr.bit_length() - 1, n * 16 - sr * 16)
    off = 12 + 16 * n
    recs, body = b"", b""
    for tag in sorted(tables):
        data = tables[tag]
        recs += struct.pack(">4sIII", tag.encode("latin1"), 0, off + len(body), len(data))
        body += data + b"\0" * (-len(data) % 4)
    return head + recs + body


def build(family="Testface", style="Regular", bold=False, italic=False, kern=None):
    glyphs = _glyphs()
    n = len(glyphs)
    glyf, loca = b"", [0]
    for _ch, _adv, contours in glyphs:
        glyf += _simple(contours) if contours else b""
        loca.append(len(glyf))
    chars = sorted((ord(ch), gid) for gid, (ch, _a, _c) in enumerate(glyphs) if ch)
    # cmap format 4, one segment per character (idDelta maps it) plus the closing 0xFFFF segment
    segs = [(cp, cp, (gid - cp) & 0xFFFF) for cp, gid in chars] + [(0xFFFF, 0xFFFF, 1)]
    sx2 = 2 * len(segs)
    sub = struct.pack(">HHHHHHH", 4, 16 + 8 * len(segs), 0, sx2, 0, 0, 0)
    sub += b"".join(struct.pack(">H", e) for _s, e, _d in segs) + b"\0\0"
    sub += b"".join(struct.pack(">H", s) for s, _e, _d in segs)
    sub += b"".join(struct.pack(">H", d) for _s, _e, d in segs) + b"\0\0" * len(segs)
    cmap = struct.pack(">HH", 0, 1) + struct.pack(">HHI", 3, 1, 12) + sub
    mac = (1 if bold else 0) | (2 if italic else 0)
    head = struct.pack(">IIIIHHqqhhhhHHhhh", 0x00010000, 0x00010000, 0, 0x5F0F3CF5, 0, UPEM, 0, 0, 0, -200, 700, 800, mac, 8, 2, 0, 0)
    hhea = struct.pack(">IhhhHhhhhhhhhhhhH", 0x00010000, ASCENT, -DESCENT, GAP, 700, 0, 0, 700, 1, 0, 0, 0, 0, 0, 0, 0, n)
    hmtx = b"".join(struct.pack(">Hh", adv, 0) for _c, adv, _g in glyphs)
    maxp = struct.pack(">IH", 0x00010000, n) + b"\0" * 26
    full = family + " " + style
    recs = [(1, family), (2, style), (4, full)]
    strings, entries = b"", b""
    for nid, text in recs:
        raw = text.encode("utf-16-be")
        entries += struct.pack(">HHHHHH", 3, 1, 0x409, nid, len(raw), len(strings))
        strings += raw
    name = struct.pack(">HHH", 0, len(recs), 6 + 12 * len(recs)) + entries + strings
    tables = {"cmap": cmap, "glyf": glyf, "head": head, "hhea": hhea, "hmtx": hmtx, "loca": b"".join(struct.pack(">I", v) for v in loca),
              "maxp": maxp, "name": name}
    tables["head"] = tables["head"][:50] + struct.pack(">h", 1) + tables["head"][52:]            # long loca offsets
    if kern:
        gid = dict((ch, i) for i, (ch, _a, _c) in enumerate(glyphs) if ch)
        pairs = sorted((gid[a], gid[b], v) for (a, b), v in kern.items())
        sub = struct.pack(">HHH", 0, 14 + 6 * len(pairs), 1)
        sub += struct.pack(">HHHH", len(pairs), 0, 0, 0) + b"".join(struct.pack(">HHh", a, b, v) for a, b, v in pairs)
        tables["kern"] = struct.pack(">HH", 0, 1) + sub
    return _table_dir(tables)


def write(path, **kw):
    with open(path, "wb") as f:
        f.write(build(**kw))
    return path
