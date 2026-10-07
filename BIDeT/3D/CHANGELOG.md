# Changelog

## Unreleased

- ASCII art is redrawn before it is extruded: art mode (`-a`, or art detected on a pipe) now
  runs the art through the new `../unascii`, which reads the characters as pen strokes, joins
  the ends that meet into continuous curves and rounds the corners (cowsay, figlet, boxes), or
  traces outlines of the density for picture-style art (jp2a, chafa, braille, half blocks). The
  extruded result is one drawing instead of rows of glyphs. `--no-lineart` restores the old
  glyphs, `--lineart=MODE` forces a method, `--pen` sets the thickness; line spacing is 1.0 for
  drawn art. `BIDET3D_UNASCII` / `make install` find `unascii.py` like the gfx-conv modules; if it
  is missing, art mode falls back to glyphs.
- Drawn art (unascii): joined strokes are spline-smoothed (diagonals and waves instead of staircases;
  corners stay sharp), cowsay speech bubbles close at the bottom, and runs of `X` become hatched
  shading. `unascii --spline F`, `--shade CHARS`, `--hatch F`; defaults apply in bidet3d.
- unascii now replays its input on a terminal emulator (screen, scrollback, cursor addressing,
  scroll regions, DEC line drawing, OSC skipped), so screen dumps and `ESC[9999;1H` art work
  (a 256-colour chart that took 300 s takes under a second), and keeps ANSI colours when used on its
  own (`unascii art.ans -o art.png`); bidet3d still takes only the shape.
- unascii has two modes: `lineart` (line drawings; what bidet3d always asks for) and `ansi-block`
  (art made of blocks and graphic characters, rendered as the coloured picture it is). On its own
  it picks one automatically; `-m lineart` / `-m ansi-block` force it.
- `--image FILE`, or a PNG/JPEG/GIF on stdin, extrudes a picture instead of text, so
  `unascii art.txt -o - | bidet3d` works as a pipeline.

- `-F/--format`: print kitty graphics, iTerm2 inline images, ANSI art or Tektronix vectors as well as SIXEL
  (or `auto`), via the `../gfx-conv` converters, which `make install` now installs under
  `share/BIDeT3D/gfx` and links into `bin`. `BIDET3D_GFX` points elsewhere. These formats keep a
  transparent background (no OSC 11 query) and do not animate.
- Transparent pictures no longer come out with a grey background on Raspberry Pi OS: img2sixel
  1.8.2 ignores the PNG transparent index, so keyed pictures are now encoded to SIXEL directly
  (`encode_keyed`), without img2sixel.
- Character-cell size is asked of the terminal (CSI 16 t) when the tty cannot report it, as over
  ssh; the guess of 10x20 made pictures too wide and clipped on the right. `-d` shows which was used.
- Speed on old/slow machines (Pi, Pillow < 7): nearest-colour mapping works on distinct colours
  with a matrix product (was 65% of the run time), and the extrusion slices are warped on up to
  4 threads. A two-line quote on cmpi (armv7, 4 cores): ~13-17 s -> ~6 s.
- ASCII art: `-a/--art` keeps lines aligned (they were each centred separately), uses a monospace
  font, no letter-spacing and tighter lines (0.9). Piped multi-line art (cowsay, figlet, boxes) is
  detected automatically; `--no-art` turns that off. `-l` now defaults to per-mode, not 1.0.
- `--time-machine` (with `--stage-time`): banner, FIGlet, TOIlet, BIDeT and BIDeT3D, in that
  order. Uses the real programs when installed, imitations otherwise (`BIDET3D_EMULATE`).
- Animation internals split into `render_loop` / `play_loop` (no change in behaviour).

## 0.1 (2026-10-01)

First release.

- 30 css3wordart WordArt presets rendered as real 3D (software renderer, Pillow + numpy),
  including the arc / inverted-arc / squeeze baselines; wave baseline.
- Camera control (`--view`, `--yaw`, `--pitch`, `--roll`, `--perspective`), `--depth`, `--shape`.
- `--spin` / `--sway` animation: one seamless pre-rendered loop on a shared palette.
- SIXEL output via the libsixel Python binding or `img2sixel`; SIXEL support check (DA1);
  terminal background detection (OSC 11) with exact background colour through quantization;
  transparent-sixel fallback for terminals that will not report it (Windows Terminal).
- BIDeT-compatible options (`-b -c -f -l -p -s -w -d -v`).
- Works with old libraries: Python 3.7, Pillow 5.4, numpy 1.16 and up.
- Man page (`bidet3d.1`), Makefile, smoke test (`test.sh`).
