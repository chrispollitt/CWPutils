# Where BIDeT comes from

> *You know banner. You know FIGlet. You may have heard of TOIlet. It's now time for BIDeT.*
> -- the opening of the original demonstration

A short history of the project, written from what is in the repository: its folders, changelogs
and commit dates. Dates for 2026 are the repository's; BIDeT 1 is from 2020. (The
reasons *why* are the author's to tell, and are not in the repository, so this is the *what*.)

## banner, FIGlet, TOIlet

Big text for the terminal has a lineage, and `bidet --time-machine` walks it with your own text:

| year | tool | made big text out of |
| --- | --- | --- |
| 1983 | `banner(1)`, AT&T UNIX System V | `#` characters |
| 1991 | FIGlet, Glenn Chappell and Ian Chai | characters, in numerous fonts |
| 2004 | TOIlet, Sam Hocevar | characters, with colour and filters |
| 2020 | BIDeT | **pixels**: SIXEL graphics, and real fonts |

The name, and the opening above, say where BIDeT sees itself: the next step after Toilet.

## BIDeT 1 (2020), `v1/`

A Perl program, `BIDeT.pl`: Ghostscript drew the text from real fonts, netpbm converted the result, and the
terminal was sent SIXEL. It came with a font finder, a list of terminals that do SIXEL
(`TERMINAL-SUPPORT-LIST.txt`), and `test-sixel.sh`, which asks a terminal whether it can show SIXEL at all
(DA1) rather than guess. It worked, but it needed an old, patched netpbm and a pile of other tools, and one of its
install scripts (`fixnetpbm`) did things as root that no script should; it is disabled. v1 is kept for posterity
and is unmaintained.

## BIDeT 2, `v2/`

`bidet2.py`, a Python port: Pillow in place of Ghostscript and netpbm. Its own description is "BIDeT - Use this after
you're done with Toilet! Enhanced version with multiple effects and optimized performance." Also kept for posterity,
also unmaintained.

## BIDeT3D (October 2026), `3D/`

1990s WordArt, extruded into real 3D. The thirty designs of
[css3wordart](https://github.com/arizzitano/css3wordart), including the arc, inverted-arc and squeeze baselines that
its author marked "not achievable" in CSS, drawn by a small software renderer (Pillow and numpy): the face is one
picture, the extrusion a dense stack of shaded silhouettes seen through a perspective camera. First release, 0.1, on
2026-10-01. It could `--spin` and `--sway`, pre-rendering a seamless loop on one palette and replaying it on a steady
clock, and soon after it gained a `--time-machine`. It asked the terminal what it could do (SIXEL support, background colour) and
had a fallback for terminals that will not say, Windows Terminal among them. It was written to run on old libraries:
Python 3.7, Pillow 5.4, numpy 1.16.

Two helpers grew beside it, and moved into `3D/` on 2026-10-07:

- **`unascii/`**: terminal art back to a line drawing. It reads a cowsay or a figlet as pen strokes, joins the ends that
  meet, rounds the corners; it replays its input on a terminal emulator (cursor addressing, scroll regions), so screen
  dumps work; and for art made of blocks it draws the coloured picture it is.
- **`gfx-conv/`**: SIXEL to kitty, iTerm2, ANSI art and Tektronix. Its history of how pictures got into terminals,
  [`GRAPHICS-HISTORY.md`](GRAPHICS-HISTORY.md), now lives at the top level, since it is about all of BIDeT's output.

## Why a format (a reading of the repository, not the author's words)

In BIDeT3D, art went from unascii to the 3D stage as a pixel mask (4D's notes call that call "lossy"): the strokes,
the letters, the colours and the character grid did not survive the trip, and each tool had its own idea of what
the picture was. 4D's answer was to describe the picture once, in a file that keeps all of that, and let the tools
share it.

## BIDeT 4D (October 2026 onward), `4D/`

"4D" is 3D plus time. A picture is described once, in a file, the **BIF** (BIDeT Intermediate Format: vector and
raster layers, a palette with roles, the character grid kept alongside, frames for animation, a chunked stream in the
spirit of PNG), and three tools pass it along: `bifin` makes a BIF from terminal art, text in a font, or a recorded
terminal session; `bifop` changes it (weight, colour, shape, crop, 3D); `bifout` draws it as PNG or GIF, or on a
terminal as SIXEL, kitty or iTerm2 graphics, coloured text or Tektronix vectors, at any size, and plays it. `bidet` is the casual front end, sugar over that pipeline and never a second
implementation. The format is specified (`4D/BIF-SPEC.md`) so that others can build on it.

How it went, in order:

1. the spec, the reference library and a hostile-file test set; `bifout` (PNG, SIXEL);
2. `bifin` for terminal art, with letters as vector outlines read straight from the font, and a **parity gate**:
   a frozen copy of unascii and 1,232 comparisons, so the new tools were held to the old tools' output before they were
   allowed to differ;
3. tone art (jp2a, chafa) traced into vector lines; `bifop`; `bidet` with named presets; lettering in any installed font;
   real terminal queries instead of guesses;
4. **animation** (12 October 2026): a recorded terminal session (`bambi.vt`, `tetris.vt`) becomes an animated GIF;
   bidet3d's spin, sway and time machine were ported; and the new thing, a flat picture that **pops out of the
   screen**, growing depth and rising on a shadow that parts from it; presets for all of it; a gallery that shows them
   all; and the pictures moved to their own `media` branch so the repository does not grow with every redraw;
5. **every way to a terminal** (12 October 2026): `bifout` gained the output formats of `3D/gfx-conv` (kitty and iTerm2
   images, ANSI art, Tektronix), ported by copy and tested byte for byte against the originals. `-f auto`, now the
   default on a terminal, picks whichever the terminal can show; coloured text plays an animation too; and `-f tek`
   draws the picture's own paths as strokes, which a BIF can do and a bitmap converter could not
   ([`GRAPHICS-HISTORY.md`](GRAPHICS-HISTORY.md) is the story of why there are so many).

## Decisions that stuck

- **The pipeline is the product.** `bifin | bifop | bifout` with every flag; `bidet` only ever builds that pipeline
  (`bidet -n` prints it, and a test checks the pictures are byte for byte the same).
- **3D is legacy.** It works and gets no new features; 4D does not depend on it.
- **Tested on more than one stack.** Python 3.8 with Pillow 7, Python 3.11 with Pillow 11, and Cygwin's Python 3.12 with
  Pillow 12 do not trace or draw identically, and a couple of tests have been fixed because only one of them noticed.
- **Hold to the terminals' limits, and say so.** Animation on a terminal is the hardest thing asked of SIXEL; it has been
  tested thoroughly only in mintty, and the documents say that other terminals are YMMV.

## What is still ahead

APNG and WebP, asciinema recordings (which have real timings), textures and tiles (they need paint kinds in the BIF
format), warps of the solid before it is extruded. The working list is in `4D/HANDOFF.md` and
`4D/DEVNOTES.txt`.
