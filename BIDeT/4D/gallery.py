#!/usr/bin/env python3
"""gallery: draw every bidet preset on an input that suits it, as one contact sheet.

    python gallery.py                      writes gallery/gallery.png (and one PNG per preset)
    python gallery.py -o sheet.png -p arc -p matrix -p sketch

Each tile is what `bidet -P NAME INPUT` draws, run in-process: the inputs are the preset's `sample =` kind
(text, art, picture, blocks, colour: see INPUTS), so the sheet is a tour of what 4D does and a quick look at whether
a change to a tool broke a preset.  Python 3.7+, Pillow, numpy.
"""
from __future__ import print_function

import argparse
import io
import os
import sys

from PIL import Image, ImageDraw

import bidet

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "samples")

# what each kind of sample is: (literal text, or a file in samples/)
INPUTS = {
    "text": ("text", "BIDeT 4D"),
    "art": ("file", "figlet_big.txt"),
    "picture": ("file", "tone80.txt"),
    "blocks": ("file", "blocks_color.ans"),
    "colour": ("file", "dragon_lolcat.ans"),
}


def render(preset, tile_width=360, presets=None):
    """The preset drawn on its sample: PNG bytes, `tile_width` pixels wide."""
    presets = presets or bidet.load_presets()
    kind, what = INPUTS[presets[preset].sample]
    argv = ["-P", preset, "-w", str(tile_width), "-o", "x.png"]
    argv += ["-t", what] if kind == "text" else [os.path.join(SAMPLES, what)]
    ap = bidet.build_parser()
    plan = bidet.make_plan(ap.parse_args(argv), presets, stdout_tty=False, stdin_tty=False, env={})
    if kind == "text":
        data = (what + "\n").encode("utf-8")
    else:
        with open(os.path.join(SAMPLES, what), "rb") as f:
            data = f.read()
    return bidet.run(plan, data)


def contact_sheet(names, presets, tile=(380, 230), columns=4):
    """One image with a labelled tile per preset."""
    label_h, pad = 26, 12
    rows = (len(names) + columns - 1) // columns
    W = columns * (tile[0] + pad) + pad
    H = rows * (tile[1] + label_h + pad) + pad
    sheet = Image.new("RGB", (W, H), (236, 236, 240))
    d = ImageDraw.Draw(sheet)
    for i, name in enumerate(names):
        x = pad + (i % columns) * (tile[0] + pad)
        y = pad + (i // columns) * (tile[1] + label_h + pad)
        im = Image.open(io.BytesIO(render(name, tile[0] - 8, presets))).convert("RGB")
        im.thumbnail((tile[0] - 8, tile[1] - 8))
        box = Image.new("RGB", tile, im.getpixel((0, 0)))
        box.paste(im, ((tile[0] - im.width) // 2, (tile[1] - im.height) // 2))
        sheet.paste(box, (x, y + label_h))
        d.text((x, y + 4), "%s  -  %s" % (name, presets[name].description[:48]), fill=(30, 30, 40))
    return sheet


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gallery", description="Draw every bidet preset on a suitable sample.")
    ap.add_argument("-o", "--output", default=os.path.join(HERE, "gallery", "gallery.png"), metavar="FILE",
                    help="the contact sheet (default: gallery/gallery.png)")
    ap.add_argument("-p", "--preset", action="append", metavar="NAME", help="only these presets (repeatable)")
    ap.add_argument("--single", action="store_true", help="also write each preset as its own PNG next to the sheet")
    ap.add_argument("--columns", type=int, default=4)
    a = ap.parse_args(argv)
    presets = bidet.load_presets()
    names = a.preset or list(presets)
    for n in names:
        if n not in presets:
            sys.exit("gallery: no preset '%s'" % n)
    out_dir = os.path.dirname(os.path.abspath(a.output))
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    contact_sheet(names, presets, columns=a.columns).save(a.output, optimize=True)
    if a.single:
        for n in names:
            with open(os.path.join(out_dir, n + ".png"), "wb") as f:
                f.write(render(n, 800, presets))
    print("wrote %s (%d presets)" % (a.output, len(names)))


if __name__ == "__main__":
    main()
