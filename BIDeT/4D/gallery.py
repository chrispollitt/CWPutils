#!/usr/bin/env python3
"""gallery: draw every bidet preset on an input that suits it, as contact sheets.

    python gallery.py                      gallery/gallery.png: every preset, a tile each (the moving ones as they end up)
    python gallery.py --gif                gallery/gallery-3d.gif: every 3D preset together, the moving ones moving
    python gallery.py --gifs               gallery/NAME.gif: each moving preset by itself
    python gallery.py -o sheet.png -p arc -p matrix -p sketch

Each tile is what `bidet -P NAME INPUT` draws, run in-process: the inputs are the preset's `sample =` kind
(text, art, picture, blocks, colour: see INPUTS), so the sheet is a tour of what 4D does and a quick look at whether
a change to a tool broke a preset.  A preset with a 3D look (`solid =`) or a motion (`motion =`) is a *3D preset*: on the
PNG sheet an animation is drawn as the pose it ends in (floating off the screen, on its shadow); on the GIF sheet the stills hold
still and the animations play, all on one loop of LOOP_SECONDS (the presets' motions are timed to divide it).
Python 3.7+, Pillow, numpy.
"""
from __future__ import print_function

import argparse
import io
import os
import sys

from PIL import Image, ImageDraw

import bidet
import bifout

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "samples")
LOOP_SECONDS = 8                                          # the GIF sheet's loop; the moving presets' times divide it
FPS = 10

# what each kind of sample is: (literal text, or a file in samples/)
INPUTS = {
    "text": ("text", "BIDeT 4D"),
    "art": ("file", "figlet_big.txt"),
    "picture": ("file", "tone80.txt"),
    "blocks": ("file", "blocks_color.ans"),
    "colour": ("file", "dragon_lolcat.ans"),
}


def is_3d(name, presets):
    """Does the preset (with those it uses) give a 3D look or a motion?"""
    return any(p.solid or p.motion for p in bidet.expand([name], presets))


def moves(name, presets):
    """Does the preset (with those it uses) animate?"""
    return any(p.motion for p in bidet.expand([name], presets))


def plan_for(preset, tile_width, presets, still):
    """(plan, input bytes) for a preset on its sample, drawn tile_width pixels wide."""
    kind, what = INPUTS[presets[preset].sample]
    argv = ["-P", preset, "-w", str(tile_width), "-o", "x.png"]
    argv += ["-t", what] if kind == "text" else [os.path.join(SAMPLES, what)]
    plan = bidet.make_plan(bidet.build_parser().parse_args(argv), presets, stdout_tty=False, stdin_tty=False, env={}, still=still)
    if kind == "text":
        data = (what + "\n").encode("utf-8")
    else:
        with open(os.path.join(SAMPLES, what), "rb") as f:
            data = f.read()
    return plan, data


def render(preset, tile_width=360, presets=None):
    """The preset drawn on its sample: PNG bytes, `tile_width` pixels wide.  (A motion is drawn as its final pose.)"""
    presets = presets or bidet.load_presets()
    plan, data = plan_for(preset, tile_width, presets, True)
    return bidet.run(plan, data)


def _positions(n, tile, columns):
    label_h, pad = 26, 12
    rows = (n + columns - 1) // columns
    size = (columns * (tile[0] + pad) + pad, rows * (tile[1] + label_h + pad) + pad)
    return size, [(pad + (i % columns) * (tile[0] + pad), pad + (i // columns) * (tile[1] + label_h + pad)) for i in range(n)], label_h


def fit_tile(im, tile):
    """The picture centred in a tile of its own page colour."""
    im = im.convert("RGB")
    im.thumbnail((tile[0] - 8, tile[1] - 8))
    box = Image.new("RGB", tile, im.getpixel((0, 0)))
    box.paste(im, ((tile[0] - im.width) // 2, (tile[1] - im.height) // 2))
    return box


def _base_sheet(names, presets, tile, columns, tiles):
    """The sheet with its labels and the given tiles (PIL images, one per name)."""
    size, pos, label_h = _positions(len(names), tile, columns)
    sheet = Image.new("RGB", size, (236, 236, 240))
    d = ImageDraw.Draw(sheet)
    for name, (x, y), t in zip(names, pos, tiles):
        sheet.paste(t, (x, y + label_h))
        tag = "  [3D]" if is_3d(name, presets) and not moves(name, presets) else ("  [4D]" if moves(name, presets) else "")
        d.text((x, y + 4), ("%s%s  -  %s" % (name, tag, presets[name].description))[:72], fill=(30, 30, 40))
    return sheet, pos, label_h


def contact_sheet(names, presets, tile=(380, 230), columns=4):
    """One image with a labelled tile per preset."""
    tiles = [fit_tile(Image.open(io.BytesIO(render(n, tile[0] - 8, presets))), tile) for n in names]
    return _base_sheet(names, presets, tile, columns, tiles)[0]


def animated_tiles(name, tile, presets):
    """One tile per tick of the loop (FPS * LOOP_SECONDS of them) for a moving preset, else None."""
    if not moves(name, presets):
        return None
    plan, data = plan_for(name, tile[0] - 8, presets, False)
    notes = bidet.bifop.Notes()
    pic = bidet.build_picture(plan, data, notes)
    if len(pic.frames) < 2:
        return None
    a = bidet._parse_flags(bifout.build_parser(), plan.bifout, "bifout flags")
    opts = bifout.render_options(a)
    opts.pop("frame"), opts.pop("speed"), opts.pop("loop"), opts.pop("fps"), opts.pop("transparent")
    sched = bifout.schedule(pic, fps=FPS)
    ticks = [i for i, ms in sched for _ in range(max(1, int(round(ms / (1000.0 / FPS)))))]
    first, frames, _samples = bifout.draw_all(pic, sorted(set(ticks)), opts)
    by_frame = {}
    for i, r in zip(sorted(set(ticks)), frames):
        by_frame[i] = fit_tile(Image.fromarray(r.flatten(), "RGB"), tile)
    return [by_frame[ticks[k % len(ticks)]] for k in range(FPS * LOOP_SECONDS)]


def animated_sheet(names, presets, tile=(270, 170), columns=5):
    """Frames (PIL images) of a sheet of these presets: stills hold, moving ones play; one loop of LOOP_SECONDS."""
    stills, moving = [], {}
    for n, name in enumerate(names):
        tl = animated_tiles(name, tile, presets)
        if tl:
            moving[n] = tl
            stills.append(tl[0])
        else:
            stills.append(fit_tile(Image.open(io.BytesIO(render(name, tile[0] - 8, presets))), tile))
    base, pos, label_h = _base_sheet(names, presets, tile, columns, stills)
    frames = []
    for k in range(FPS * LOOP_SECONDS):
        f = base.copy()
        for n, tl in moving.items():
            f.paste(tl[k], (pos[n][0], pos[n][1] + label_h))
        frames.append(f)
    return frames


def save_gif(frames, path):
    """A looping GIF of PIL images on ONE palette (a still tile must not shimmer from frame to frame)."""
    step = max(1, len(frames) // 8)
    w, h = frames[0].size
    mont = Image.new("RGB", (w, h * len(frames[::step])))
    for i, f in enumerate(frames[::step]):
        mont.paste(f, (0, i * h))
    pal = mont.quantize(colors=255, method=0)
    out = []
    for f in frames:
        try:
            out.append(f.quantize(palette=pal, dither=0))
        except TypeError:                                          # (Pillow before 7)
            out.append(f.quantize(palette=pal))
    out[0].save(path, save_all=True, append_images=out[1:], duration=int(1000 / FPS), loop=0, optimize=False, disposal=1)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gallery", description="Draw every bidet preset on a suitable sample.")
    ap.add_argument("-o", "--output", default=None, metavar="FILE",
                    help="the contact sheet (default: gallery/gallery.png, or gallery/gallery-3d.gif with --gif)")
    ap.add_argument("-p", "--preset", action="append", metavar="NAME", help="only these presets (repeatable)")
    ap.add_argument("--single", action="store_true", help="also write each preset as its own PNG next to the sheet")
    ap.add_argument("--gif", action="store_true", help="an animated sheet of the 3D presets (moving ones move) instead of the PNG")
    ap.add_argument("--gifs", action="store_true", help="also write each moving preset as its own GIF next to the sheet")
    ap.add_argument("--columns", type=int, default=None)
    a = ap.parse_args(argv)
    presets = bidet.load_presets()
    names = a.preset or list(presets)
    for n in names:
        if n not in presets:
            sys.exit("gallery: no preset '%s'" % n)
    default = os.path.join(HERE, "gallery", "gallery-3d.gif" if a.gif else "gallery.png")
    out = a.output or default
    out_dir = os.path.dirname(os.path.abspath(out))
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    if a.gif:
        names = sorted([n for n in names if is_3d(n, presets)], key=lambda n: moves(n, presets))      # (the moving ones together:
        #                                                                       only their rows change from frame to frame: a small GIF)
        if not names:
            sys.exit("gallery: none of these presets is 3D")
        save_gif(animated_sheet(names, presets, columns=a.columns or 5), out)
    else:
        contact_sheet(names, presets, columns=a.columns or 4).save(out, optimize=True)
    if a.single:
        for n in names:
            with open(os.path.join(out_dir, n + ".png"), "wb") as f:
                f.write(render(n, 800, presets))
    if a.gifs:
        for n in names:
            if moves(n, presets):
                plan, data = plan_for(n, 480, presets, False)
                plan.output, plan.fmt = os.path.join(out_dir, n + ".gif"), "gif"
                plan.bifout = [x for x in plan.bifout]
                with open(plan.output, "wb") as f:
                    f.write(bidet.run(plan, data))
    print("wrote %s (%d presets)" % (out, len(names)))


if __name__ == "__main__":
    main()
