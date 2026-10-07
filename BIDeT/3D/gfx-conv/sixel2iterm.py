#!/usr/bin/env python3
"""sixel2iterm - show a SIXEL (or PNG/JPEG...) picture with iTerm2's inline images protocol.

    bidet3d --transparent --force "Hello" | sixel2iterm
    sixel2iterm -w 40 picture.png

The protocol (https://iterm2.com/documentation-images.html, OSC 1337 File=) is understood by
iTerm2, WezTerm, mintty and some others.  The picture goes out as PNG, base64 encoded, in one
escape sequence; transparency is kept.  Standard library only (Pillow is needed only for
input that is neither SIXEL nor PNG).
"""
import argparse
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sixeldec  # noqa: E402


def iterm_sequence(png, width=None, height=None, name="picture.png"):
    """OSC 1337 sequence that shows one PNG at the cursor.  width/height: character cells,
    or None for the picture's own size."""
    args = ["name=" + base64.standard_b64encode(name.encode()).decode(), "size=%d" % len(png), "inline=1",
            "preserveAspectRatio=1"]
    if width:
        args.append("width=%d" % width)
    if height:
        args.append("height=%d" % height)
    return (b"\x1b]1337;File=" + ";".join(args).encode() + b":" + base64.standard_b64encode(png) + b"\x07")


def main():
    ap = argparse.ArgumentParser(description="SIXEL / image -> iTerm2 inline image")
    ap.add_argument("file", nargs="?", help="SIXEL or image file (default: standard input)")
    ap.add_argument("-w", "--width", type=int, help="width in character cells (default: the picture's own size)")
    ap.add_argument("-H", "--height", type=int, help="height in character cells")
    ap.add_argument("-n", "--no-newline", action="store_true", help="no newline after the picture")
    args = ap.parse_args()
    png = sixeldec.picture_png(sixeldec.read_input(args.file))
    out = sys.stdout.buffer
    out.write(iterm_sequence(png, args.width, args.height))
    if not args.no_newline:
        out.write(b"\n")
    out.flush()


if __name__ == "__main__":
    main()
