# unascii: handoff

State as of 2026-10-07. Read this first, then `README.md` (user-facing) and
`unascii.py` (one file, ~1400 lines, section banners in it).

## What it is

Terminal art (ASCII, ANSI colour, Unicode blocks, braille) back to a line
drawing: PNG, SIXEL, or a PIL mask for other programs. Built in one long
session on the user's request ("ASCII art turns a picture into characters;
turn it back"), then wired into BIDeT3D at their suggestion: bidet3d's art
mode (`-a`, or art auto-detected on a pipe) now redraws the art with unascii
before extruding it, and `unascii x.txt -o - | bidet3d` works as a pipeline.

Commits (local main, Cygwin git, both pushed by the user): `a2baaf9` (unascii
+ bidet3d integration), `3e581c8` (speed). Anything later is not committed
until the user says so; stage only the paths you touched (the repo has other
uncommitted work of theirs; never `git add -A`).

## Constraints that shaped the code

- **Old stacks.** Python 3.7+, Pillow 5.4+, numpy 1.16+ (cmpi is a Pi with
  exactly that). No scipy/OpenCV, no walrus, no `math.dist`, `np.pad` always
  with `mode=`, no `Image.Resampling`. Verified on Python 3.11/Pillow 11/numpy
  2.2 (Windows) and 3.8/Pillow 7.0/numpy 1.17 (WSL Ubuntu-20.04).
  **Not tested on Python 3.7 / Pillow 5.4 (cmpi).**
- Single file, importable (`import unascii`) and runnable. bidet3d finds it via
  `$BIDET3D_UNASCII`, `../unascii`, `share/BIDeT3D/unascii` (see
  `load_unascii` in `../3D/bidet3d.py`).
- Windows Write tool makes CRLF files: `sed -i 's/\r$//'` after writing
  scripts. Heredocs mangle backslashes: patch with the Edit tool or a Python
  file, not `sed`/heredoc.

## Code map (`unascii.py`)

| section | what | key names |
| --- | --- | --- |
| Reading | decode (UTF-8, else CP437, SAUCE dropped), mini terminal emulator (SGR 16/256/truecolor, cursor moves, erase, wrap) | `decode`, `parse`, `Grid` |
| Classification | which characters are strokes/fills/text; auto mode choice | `STRONG` `WEAK` `DENSE`, `classify`, `word_cells` (text vs eyes), `shade_cells` (X runs), `bubble_bottoms` (cowsay) |
| Fonts/glyphs | exact masks for blocks/braille, font masks for the rest | `Glyphs`, `find_font` |
| Image helpers | numpy-only blur (exact taps < 2.5 px, 3 box passes above), smoothstep | `blur`, `_box_sizes`, `_box_pass` |
| Tone | density -> picture -> outlines | `pitch_of`, `darkness`, `halftone_free`, `edge_lines` |
| Line | strokes, linking, chains, smoothing, hatching, drawing | `GEOM`, `box_arms`/`box_paths`, `glyph_paths`, `link_paths`, `chains`, `spline_smooth`/`_smooth_span`, `fillet` (older corner rounding, `--spline 0`), `hatch_layer`, `draw_strokes` |
| Assembly | `Options`, `render_grid` (the pipeline), `render`, `mask` (API for bidet3d), `to_image` | |
| SIXEL | own encoder, paper->ink ramp so colours are exact | `sixel`, `_rle` |
| CLI | argparse `main` | |

bidet3d side (`../3D/bidet3d.py`): `load_unascii`, `read_stdin` (cached bytes;
PNG/JPEG/GIF magic = picture, else UTF-8-first text), `load_image`,
`image_mask`, `get_lines` (builds `args._grid` / `args._image`), `shape_mask`,
and the `drawn` branch in `build_layer`. Flags: `--lineart[=MODE]`,
`--no-lineart`, `--pen` (default 2.2), `--image`. `fit_px` calls `build_layer`
as a probe at 24 px, so unascii runs twice per picture.

## How the line mode works (the part worth understanding)

1. Every stroke character becomes a `Path` (polyline in pixels) from `GEOM`;
   `link=True` paths may join others. Letters in words and unknown glyphs are
   font masks, not strokes. Shaded cells (X runs) are skipped and hatched.
2. `link_paths`: greedy nearest-end joining within `--join` cell widths, never
   to itself, never doubling back; leftover ends get a bare segment to a nearby
   junction (`extras`). A `.` is a point on the line (two coincident ends).
3. `chains` walks the links into long polylines with a per-vertex "join" flag.
4. `spline_smooth`: cut the chain at sharp corners, resample each stretch and
   Gaussian-smooth it with the ends pinned (odd reflection). Sharpness:
   inside a character 80 deg; at a join 85 deg for a single corner (adjacent
   same-direction turns are summed, because a right angle between characters
   is two ~45 deg turns), but up to 100 deg for an S-step ("terrace": two
   opposite turns within 1.1 cell widths) so staircases of `_` and `-` flow.
   Rings, box pieces and `extras` are never smoothed (a ring collapses to a dot).
5. Strokes are drawn supersampled (up to 4x, capped at 16 MP) and box-filtered.

Tone mode: average per dot (cell / half cell / braille dot, `pitch_of`) ->
bicubic up -> blur -> autolevel -> zero crossings of a difference of
Gaussians, drawn at sub-pixel position with gating by edge height (`--detail`),
plus a few contour lines only where shading is gentle (`--levels`).

## Decisions and why

- **Pooling before blurring (tone).** Edge-replicate blur of a periodic glyph
  texture made a false frame round the whole picture.
- **Contours only on gentle gradients.** Iso-lines at step edges doubled every
  outline.
- **Terrace vs corner rule** (above): without it either figlet's `BIDeT`
  turned bulbous or the Ghostbusters terraces stayed stepped.
- **Letters stay letters** (`word_cells`): `o`, `v`, `0` are eyes/strokes only
  when not part of a word.
- **Bubble bottom** is lifted to the row boundary (`bubble_bottoms`): the user
  asked that cowsay bubbles close at the bottom.
- **Glyph emboldening** at high pen weights is gentle (`--text-bold`, capped
  1.6x): bidet3d's art font is already Courier Bold.
- **bidet3d default**: lineart is ON in art mode (user's request), falls back
  silently to glyphs if unascii is missing; `--lineart` explicitly makes a
  missing module an error.

## Testing

```
./test.sh            # every sample x every mode, SIXEL framing, library
                     # asserts (classify, parse, bubbles, shading, spline),
                     # and a pipe into ../3D/bidet3d.py   (~1 min)
cd ../3D && ./test.sh  # includes art / --no-lineart / --lineart=tone / pipe
```

`samples/` holds real output of cowsay, figlet, toilet, jp2a, chafa
(generated in WSL Ubuntu-20.04: `wsl -d Ubuntu-20.04`). SIXEL was verified by
decoding with libsixel's `sixel2png` (max pixel diff = the 16-level
quantization). For ad-hoc looks: `python unascii.py FILE -c 16 -w 1.3 -o
out/x.png` then view the PNG; `out/` is gitignored. bidet3d needs
`COLUMNS=160 LINES=60` set to render large PNGs when stdout is not a tty.

## Known gaps and ideas

- Never viewed in a real SIXEL terminal (only decoded); cmpi/Py3.7 untested.
- Tone mode cannot know polarity: dense characters are taken as dark ink; jp2a's
  default output needs `--invert`. Could guess from a border-vs-centre density
  test.
- `make lint` in `../3D` stops at the user's `profiling.sh` (dash: "Bad for loop
  variable"). Not from this work; run the other lint steps by hand.
- bidet3d runs unascii twice (probe + final); skipping the lineart in the
  probe would save ~0.1-0.2 s (offered, not done).
- Wide (CJK) characters count as one cell; colour is ignored in line mode
  (only tone mode uses it); no `unascii(1)` man page (bidet3d.1 refers to one).
- Ideas not done: other shading characters by default (`#`, `M`; `--shade`
  already takes any set), colour-tinted lines, hatch density by character
  (`x` < `X` < `#`), a Windows Terminal check of `unascii -s`.
