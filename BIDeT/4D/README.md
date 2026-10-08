# BIDeT 4D

Re-architecture of BIDeT3D / unascii into three tools that talk through one file format.
Status: 2026-10-07, **M0 to M3 done, M4 started**: the format spec (draft 2), its reference library `bif.py`,
Tool 3 (`bifout`: BIF -> PNG / SIXEL) and Tool 1 for terminal art (`bifin`) exist, are tested, and draw
what unascii draws (the parity gate); Tool 2 (`bifop`) has its first operations.  New here? Read
[`HANDOFF.md`](HANDOFF.md). `../3D` (BIDeT3D, with `3D/unascii` and `3D/gfx-conv`) is **legacy**:
it gets no new features or fixes. 4D does not depend on it: the parity tests use a frozen copy of unascii
(`tests/reference/`) and 4D's own `samples/`; only an optional SIXEL decoder test looks in `3D/gfx-conv`.

    bifin cow.txt | bifout -s                     # the whole pipeline, SIXEL on the terminal
    bifin art.ans -o art.bif && bifout art.bif -o art.png --scale 3 --ink "#00ff66" --paper "#101820"
    bifin figlet.txt | bifop wave:amplitude=0.1 pen:1.5 crop:margin=8 | bifout -o wordart.png --scale 2

| file | what |
| --- | --- |
| [`BIF-SPEC.md`](BIF-SPEC.md) | the format |
| [`bif.py`](bif.py) | reference reader / writer / validator, one file, numpy only; `bif.py info\|check\|chunks FILE` |
| [`bifin.py`](bifin.py) | **Tool 1**: `bifin art.txt -o art.bif` (all of unascii's options: `-m`, `-c`, `-w`, `--ink`, ...; plus `--no-outlines`, `--no-cells`, `--keep-source`). Input kinds are sniffed; importers are registered in `READERS` (only `text` so far; PNG / SIXEL / SVG say so) |
| [`bifin_text.py`](bifin_text.py) | the text importer: unascii's reader, classifier and line / tone / block methods (ported by copy, unchanged) plus a new assembly that emits layers: `strokes`, `text` and `tone` (vector), `text-mask`, `hatch`, `picture` (raster), `cells` (hidden grid); SAUCE records read (title, credit, width) |
| [`ttfglyphs.py`](ttfglyphs.py) | TrueType outlines (glyf, cmap 4 / 12, composites, .ttc) with no dependencies: letters become vectors. CFF / other fonts fall back to a raster `text-mask` |
| [`tonetrace.py`](tonetrace.py) | marching squares: contour lines of a field as sub-pixel polylines, plus stitching, simplification and bilinear sampling. Tone mode (picture-style art: jp2a, chafa, shaded ASCII) is traced with it, so its outlines are vectors whose width fades with the edge strength (`--tone-raster` for unascii's raster of them) |
| [`bifop.py`](bifop.py) | **Tool 2**: `bifop OP [OP ...]` reads a BIF (stdin or `-i`), writes the changed BIF (stdout or `-o`). Operations: `pen` (line thickness), `theme` / `recolor` (colours by role or number), `opacity`, `blend`, `crop`, `scale`, `rotate`, `flip`, `keep` / `drop` / `hide` / `show` (layers), `frame`, `meta`, `simplify`, and the WordArt warps `wave`, `arc`, `squeeze` (on vector layers). `bifop --list` describes them; they are registered with `@op`. It does what BIF-SPEC.md asks of a manipulator: passes on everything it does not know, keeps the credit and licence, appends to `meta.history`. |
| [`bifout.py`](bifout.py) | **Tool 3**: `bifout x.bif -o x.png [--scale S \| --width PX] [--ink C --paper C]`, `bifout x.bif -s` (SIXEL), pipes both ways. Writers are registered in `WRITERS` |
| [`bifrender.py`](bifrender.py) | BIF -> pixels: vector layers (strokes, fills with holes, caps / joins, tapers, transforms), raster layers (affine, smooth or nearest), blend modes, `ink` / `paper` role overrides |
| [`bifsixel.py`](bifsixel.py) | the SIXEL encoder (from v3, with a bug fixed, see below) |
| [`testdata/`](testdata/) | reference files for any implementation: `good/` (with the expected contents as JSON) and `bad/` (each must be rejected; `manifest.json` says why) |
| [`tests/`](tests/) | `test_bif.py` (37 tests: the files above, round trips, fuzzing, API, CLI), `test_bifout.py` (47: geometry, rasters, blending, SIXEL decoded back, CLI, parity with v3's `draw_strokes` / `sixel`), `test_bifin.py` (47: outlines vs FreeType, SAUCE, every sample, the cells layer equals the art, modes and options, hostile input, tone as vector lines, parity with unascii per sample, CLI), `test_tonetrace.py` (14: marching squares: every traced point is on the level, loops, saddles, borders, speed), `test_bifop.py` (44: the manipulator contract, each operation against what it must do to the drawing, the warps against their formulas, CLI), `test_parity.py` (**the M3 gate**, see Milestones; also the vector tone lines), `reference/unascii_v3.py` (the frozen v3 it compares with), `make_testdata.py` |
| [`samples/`](samples/) | the art the tests use (cowsay, figlet, toilet, jp2a, chafa output; nothing third-party) |
| [`HANDOFF.md`](HANDOFF.md) | state, decisions, gaps and working notes for whoever continues |
| [`test.sh`](test.sh) | runs the tests: everything (about 10 minutes), or `--quick` (a smoke subset of the parity gate, about 3 minutes); verified on Python 3.11 / numpy 2.2 / Pillow 11 and Python 3.8 / numpy 1.17 / Pillow 7, the fast suites also on Cygwin's Python 3.12 / numpy 2.5 / Pillow 12 (not on 3.7 / 1.16 / 5.4) |
| [`Makefile`](Makefile) | `make help`: `lint`, `test-quick` (about 1 min), `test` (plus a parity smoke run, about 3 min), `test-full` (everything), `testdata`, `install` / `uninstall` (`bif`, `bifin`, `bifout` into `PREFIX/bin`, modules in `share/BIDeT4D`, docs; `DESTDIR` supported), `installreq`, `dist`, `clean` |
| [`requirements.txt`](requirements.txt) | numpy, Pillow (no libsixel: SIXEL is written here) |

Found while porting (v3 is untouched; both are fixed in the copies here):

- **unascii v3's SIXEL encoder** emits `!72` (a repeat count with nothing to repeat) before `$` or `-`
  when a colour's row ends in a long blank run (`_sixel_stream`: the `endswith("?")` branch strips the
  `?` of `!72?` and leaves the count). libsixel ignores it; a strict decoder takes the `$` as the repeated
  character and loses the carriage return, so the picture comes out far too wide. `bifsixel.py` drops the
  whole run.
- **v3's terminal reader** raises `KeyError: 0` on a NUL byte in CP437 input (`CP437_GLYPHS` has codes
  1..31 but the code looks up every code below 32). `bifin_text.py` ignores NUL.
- Not a bug but a quirk: a line of only dashes (or a single `x`) is classified `tone`, which has no edges to
  outline, so it draws nothing in v3 and in `bifin`.

```
 sources ──► Tool 1: import ──► .bif ──► Tool 2: manipulate ──► .bif ──► Tool 3: export ──► sinks
 text, ANSI, cowsay, figlet,    (a pipe   scale, trim, pen weight,      (a pipe)  PNG, SIXEL, kitty, iTerm2,
 PNG/JPEG, SIXEL, SVG,          or file)  smooth, recolour, warp,                 SVG, Tektronix, ANSI, ...
 a font and a string                      extrude, tile, merge
```

"4D" is 3D plus time: a BIF may hold several frames (spin, animation).

## The format: [BIF-SPEC.md](BIF-SPEC.md)

A chunked binary stream (PNG-style: magic, JSON for structure, CRC'd binary chunks for arrays, critical
and ancillary chunks so it can grow). A picture is frames, a frame is a stack of layers, and a layer is

| kind | holds | for |
| --- | --- | --- |
| `vector` | polylines and polygons, flat numpy arrays (`xy` + `start` offsets, per-path width and paint, per-vertex join / corner flags) | line art: cowsay, figlet, box drawing, traced outlines. Scales to any size. |
| `raster` | coverage and/or RGB, smooth or nearest upscaling | block / pixel art, photographs, masks |
| `height` | a relief map | extrusion |
| `cells` | the character grid (code points, colours, attributes), hidden | turning a BIF back into ANSI / text, re-import at another size |

Colours are palette entries with optional roles (`ink`, `paper`) so a manipulator can re-theme.
Metadata records the source, mode, polarity, credit / licence (carried through every step) and a
history of what was done.

## The tools (working names)

All three read stdin and write stdout by default, refuse to write binary to a terminal, and are built
from one library, `bif.py` (single file, numpy only; Python 3.7+, Pillow 5.4+, numpy 1.16+, as v3).
Importers, operations and exporters are registered modules, so adding a format is adding a file.

| tool | job | what it takes from v3 |
| --- | --- | --- |
| `bifin` | any input -> BIF | `unascii`: terminal emulator (`_Term`), `classify`, `word_cells`, line / tone / block methods. Line and tone modes emit vector paths (join / corner flags not yet); block emits a raster (a dot-resolution picture is planned); `cells` is kept. `bidet3d`: text + font -> shape. `gfx-conv/sixeldec.py`: SIXEL -> raster. New: PNG/JPEG trace, SVG. |
| `bifop` | BIF -> BIF | `bidet3d` warps (arc, squeeze, wave), pen weight, `legible()` re-theming, `spline_smooth` as an operation on vector layers, crop, merge, flatten; extrusion / materials as an operation that adds a rendered raster or frames. |
| `bifout` | BIF -> any output | `unascii`: `draw_strokes`, `to_image`, the SIXEL encoder. `gfx-conv`: kitty, iTerm2, ANSI, Tektronix (native from vectors, no re-trace). New: SVG, PDF/HPGL maybe. |

Then `unascii x.txt -o x.png` is `bifin x.txt | bifout -f png -o x.png`, and bidet3d's art mode takes
the `shape` layer of a BIF instead of the lossy `mask()` call.

## Milestones

1. **M0** (done) Spec 1.0 + `bif.py` (read, write, validate, `info`) + test vectors, including a hostile-file set.
2. **M1** (done) `bifout`: PNG and SIXEL from vector and raster layers (port `draw_strokes`, the encoder).
   Not drawn yet: `height` and `cells` layers (no flat picture), kitty / iTerm2 / SVG / animation output (M5).
3. **M2** (done, with three things left for later) `bifin` for text: the reader and the three methods
   are ported and emit BIF; letters are vector outlines (raster fallback). At scale 1 the result is
   unascii's picture: tone and block exactly, line exactly with `--no-outlines` (to float32 rounding),
   and with outline letters 0.2% of pixels differ (the font's outline against FreeType's hinted
   rendering). **Left for later:** (a) ~~tone mode is a raster~~ **done after M3: tone is traced to vector
   lines** (`tonetrace.py`; see below); (b) hatching is a raster; (c) the block picture is a raster at the
   nominal resolution (smooth upscaling), not at dot resolution with `nearest`.
4. **M3** (done) the parity gate, `tests/test_parity.py`: 28 option sets x every sample (1232 cases) in process
   against a frozen copy of v3, plus the command line (PNG and SIXEL) end to end. Block mode is exact, tone
   within 0.6% of the ink, line art within 2% (8% when coloured), vector letters within 20%; the limits and
   their causes are in `tolerance()` and `HANDOFF.md`. **Changed from the plan:** v3 does not become a wrapper
   over 4D: 3D is legacy and stays as it is.
   **Tone as vectors** (after M3, `tonetrace.py`): the traced lines are compared with v3's raster ones by
   position, since a pixel difference says nothing about 1.4 px lines: median 98.7% of the traced pixels lie
   within 2 px of a v3 line pixel (precision) and 100% the other way (recall); no case below 82% / 90%.
   The files are 3-5x smaller than the raster ones, and the lines are sharp and smooth at any `bifout
   --scale`. The three colour channels' outlines of one edge are merged into one line (v3's raster unions
   them into a slightly bold one). The exact comparison with v3 (tone within 0.6%) still runs, on `--tone-raster`.
5. **M4** (started) `bifop`. Done: the operation registry and CLI, and the operations listed above (44 tests).
   Still to do: `extrude` / a 3D step (the shape layer in, rendered frames out, as bidet3d does; the idea of
   integrating with bidet3d itself is dropped, 3D is legacy), `smooth` (needs `vflag` from `bifin`), `merge` of
   several BIFs, warps of raster layers, `rasterize`, `bold` (thicken filled letters), multi-input animation.
6. **M5** more importers / exporters, animation.

## Open decisions

See "Open points" at the end of the spec, plus: final tool names, and whether bidet3d's 3D render is a
`bifop` (BIF in, BIF with frames out) or a `bifout` backend. The first is more composable; the second is
simpler. Leaning to `bifop`.
