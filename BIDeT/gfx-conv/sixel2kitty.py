#!/usr/bin/env python3
"""sixel2kitty - show a SIXEL (or PNG/JPEG...) picture with the kitty graphics protocol.

    bidet3d --transparent --force "Hello" | sixel2kitty
    sixel2kitty -c 40 picture.png

The protocol (https://sw.kovidgoyal.net/kitty/graphics-protocol/) is understood by kitty,
WezTerm, Ghostty and some others.  The picture goes out as PNG, base64 encoded, in APC
chunks of at most 4096 bytes; transparency is kept.  Standard library only (Pillow is needed
only for input that is neither SIXEL nor PNG).
"""
import argparse
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sixeldec  # noqa: E402

CHUNK = 4096


def kitty_sequence(png, cols=None, rows=None, image_id=None):
    """APC sequence(s) that transmit and display one PNG at the cursor."""
    b64 = base64.standard_b64encode(png)
    keys = ["a=T", "f=100", "q=2"]                    # transmit+display, PNG, no terminal replies
    if cols:
        keys.append("c=%d" % cols)
    if rows:
        keys.append("r=%d" % rows)
    if image_id:
        keys.append("i=%d" % image_id)
    out = []
    for pos in range(0, len(b64), CHUNK):
        part = b64[pos:pos + CHUNK]
        more = 1 if pos + CHUNK < len(b64) else 0
        head = ",".join(keys + ["m=%d" % more]) if pos == 0 else "m=%d,q=2" % more
        out.append(b"\x1b_G" + head.encode() + b";" + part + b"\x1b\\")
    return b"".join(out)


def main():
    ap = argparse.ArgumentParser(description="SIXEL / image -> kitty graphics protocol")
    ap.add_argument("file", nargs="?", help="SIXEL or image file (default: standard input)")
    ap.add_argument("-c", "--cols", type=int, help="scale to this many character cells wide")
    ap.add_argument("-r", "--rows", type=int, help="scale to this many character cells high")
    ap.add_argument("-i", "--id", type=int, help="image id, so a later picture with the same id replaces it")
    ap.add_argument("-n", "--no-newline", action="store_true", help="no newline after the picture")
    args = ap.parse_args()
    png = sixeldec.picture_png(sixeldec.read_input(args.file))
    out = sys.stdout.buffer
    out.write(kitty_sequence(png, args.cols, args.rows, args.id))
    if not args.no_newline:
        out.write(b"\n")
    out.flush()


if __name__ == "__main__":
    main()
