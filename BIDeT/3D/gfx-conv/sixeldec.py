"""sixeldec - shared helpers for the gfx-conv converters (standard library only).

  decode_rgba(data)   SIXEL bytes -> (width, height, RGBA bytes); unpainted pixels are transparent
  png_bytes(w, h, rgba)   RGBA bytes -> PNG file bytes
  load_picture(data)  SIXEL, PNG or (with Pillow) any image -> (width, height, RGBA bytes)
  read_input(path)    the file's bytes, or standard input

The SIXEL decoder is the reference for the format as BIDeT3D writes it, and handles the whole
syntax: raster attributes, colour definitions in RGB and HLS, repeats, carriage return and
graphic newline.
"""
import colorsys
import struct
import sys
import zlib

# VT340 default palette, percent
_VT340 = [(0, 0, 0), (20, 20, 80), (80, 13, 13), (20, 80, 20), (80, 20, 80), (20, 80, 80), (80, 80, 20),
          (53, 53, 53), (26, 26, 26), (33, 33, 60), (60, 26, 26), (33, 60, 33), (60, 33, 60), (33, 60, 60),
          (60, 60, 33), (80, 80, 80)]


def _pct(v):
    return int(round(min(100, max(0, v)) * 255 / 100.0))


def decode_rgba(data):
    """SIXEL (with or without its DCS wrapper) -> (width, height, RGBA bytes)."""
    s = data.decode("latin1")
    i = max(s.find("\x1bP"), s.find("\x90"))
    i = s.index("q", i) + 1 if i >= 0 else 0
    n = len(s)
    pal = {k: tuple(_pct(c) for c in rgb) for k, rgb in enumerate(_VT340)}
    bands = []
    want = None
    cur = None
    x = 0
    col = 0

    def new_band():
        return [[] for _ in range(6)]

    def num(j):
        k = j
        while k < n and s[k].isdigit():
            k += 1
        return (int(s[j:k]) if k > j else None), k

    def put(count, bits):
        rgb = pal.get(col, (255, 255, 255))
        for k in range(6):
            line = cur[k]
            if len(line) < x + count:
                line.extend([None] * (x + count - len(line)))
            if bits >> k & 1:
                line[x:x + count] = [rgb] * count

    cur = new_band()
    bands.append(cur)
    while i < n:
        c = s[i]
        if c == "\x1b":
            break
        if c == "#":
            p, i = num(i + 1)
            vals = []
            while i < n and s[i] == ";":
                v, i = num(i + 1)
                vals.append(v or 0)
            if len(vals) == 4:
                pu, a, b, d = vals
                if pu == 1:                       # HLS; DEC hue 0 = blue, so shift to the usual red = 0
                    r, g, bl = colorsys.hls_to_rgb(((a - 120) % 360) / 360.0, b / 100.0, d / 100.0)
                    pal[p] = (int(round(r * 255)), int(round(g * 255)), int(round(bl * 255)))
                else:
                    pal[p] = (_pct(a), _pct(b), _pct(d))
            else:
                col = p or 0
        elif c == "!":
            cnt, i = num(i + 1)
            if i < n and "?" <= s[i] <= "~":
                put(cnt or 1, ord(s[i]) - 63)
                x += cnt or 1
            i += 1
        elif c == '"':                            # raster attributes Pan;Pad;Ph;Pv: the picture's real size
            j = i + 1
            while j < n and (s[j].isdigit() or s[j] == ";"):
                j += 1
            ras = [int(v) if v else 0 for v in s[i + 1:j].split(";")]
            if len(ras) == 4 and ras[2] > 0 and ras[3] > 0:
                want = (ras[2], ras[3])
            i = j
        elif c == "$":
            x = 0
            i += 1
        elif c == "-":
            x = 0
            cur = new_band()
            bands.append(cur)
            i += 1
        elif "?" <= c <= "~":
            put(1, ord(c) - 63)
            x += 1
            i += 1
        else:
            i += 1
    rows = [r for b in bands for r in b]
    while rows and not any(v is not None for v in rows[-1]):          # empty rows after the last band
        rows.pop()
    w = max((len(r) for r in rows), default=1)
    h = max(1, len(rows))
    if want:
        w, h = max(w, want[0]), want[1]
        rows = rows[:h] + [[] for _ in range(h - len(rows))]
    out = bytearray()
    clear = b"\0\0\0\0"
    for r in rows:
        for v in r:
            out += clear if v is None else bytes(v) + b"\xff"
        out += clear * (w - len(r))
    if not rows:
        out = bytearray(clear)
    return w, h, bytes(out)


def png_bytes(w, h, rgba):
    """Minimal PNG writer (8-bit RGBA)."""
    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xffffffff)
    stride = w * 4
    raw = b"".join(b"\0" + rgba[y * stride:(y + 1) * stride] for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def is_sixel(data):
    return b"\x1bP" in data[:64] or data[:1] == b"\x90"


def load_picture(data):
    """SIXEL, PNG or any image Pillow can read -> (w, h, RGBA bytes)."""
    if is_sixel(data):
        return decode_rgba(data)
    from PIL import Image                       # only needed for non-SIXEL input
    import io
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    return im.width, im.height, im.tobytes()


def picture_png(data):
    """Input as PNG file bytes: PNG passes straight through, SIXEL is decoded and encoded."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return data
    w, h, rgba = load_picture(data)
    return png_bytes(w, h, rgba)


def read_input(path):
    if path and path != "-":
        with open(path, "rb") as f:
            return f.read()
    if sys.stdin.isatty():
        sys.exit("reading a picture from the terminal; pipe one in or name a file (-h for help)")
    return sys.stdin.buffer.read()
