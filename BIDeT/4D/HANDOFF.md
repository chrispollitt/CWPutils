# BIDeT 4D: handoff

State as of 2026-10-07 (evening). Read this, then `README.md` (overview, file table, milestones) and
`BIF-SPEC.md` (the format, draft 2).

## Where things stand

M0-M3 are done and committed (`1c0ceb5` v3 fixes, `1e60761` the move of gfx-conv/unascii into 3D/, and the
4D commit). The parity gate passes on **both** stacks: Windows Python 3.11 / numpy 2.2 / Pillow 11 and WSL
Python 3.8 / numpy 1.17 / Pillow 7 (about 6 minutes each). On Pillow 7 the limits needed widening, with reasons
in `tolerance()`: line art with raster letters 2% (measured worst 1.6%; Pillow 7 truncates float coordinates so
more boundary pixels flip), 8% when coloured (worst 5.9%), and canvas sizes may differ by 1 px (v3 crops on a
thresholded raster, bifin on the strokes' extent). Python 3.7 / Pillow 5.4 / numpy 1.16 is still untested.

## What exists

Three tools around one file format, `.bif`. Milestones M0-M3 are done.

| | |
| --- | --- |
| M0 | `BIF-SPEC.md`, `bif.py` (read / write / validate / `info|check|chunks`), `testdata/{good,bad}` (22 + 77 files) |
| M1 | `bifout` (BIF -> PNG / SIXEL), `bifrender.py`, `bifsixel.py` |
| M2 | `bifin` (terminal art -> BIF), `bifin_text.py` (unascii's reader / classifier / methods copied by line range + a new assembly), `ttfglyphs.py` (own TrueType outline reader: letters are vectors, raster `text-mask` fallback) |
| M3 | the parity gate, `tests/test_parity.py`, against a frozen copy of v3 (`tests/reference/unascii_v3.py`) and 4D's own `samples/` |

Not started: Tool 2 (`bifop`), other importers (PNG/JPEG trace, SIXEL, SVG, font+string) and exporters
(kitty, iTerm2, SVG, ANSI, Tektronix, animation).

## Decisions the user made (do not re-litigate)

- BIF: hybrid vector + raster layers, PNG-style chunked binary stream, frames reserved in 1.0 ("4D" = 3D + time).
- 4D lives in `BIDeT/4D`; letters: **option 3** = vector outlines where the font is TrueType, raster fallback.
- **`3D/` (bidet3d, with `3D/unascii` and `3D/gfx-conv`) is legacy**: no features, no fixes, no wrapper
  conversion. Their last edits were two approved bug fixes (commit `1c0ceb5`) and the move into `3D/`
  (commit `1e60761`). 4D must not depend on them (it does not; only an optional SIXEL decoder test looks in
  `3D/gfx-conv/sixeldec.py`).
- The 4D `Makefile` and `requirements.txt`, and the top-level `BIDeT/README.md` (now: 4D current, 3D legacy
  but still the only 3D-WordArt maker, v1/v2 obsolete), are done (verified: `make lint / test-quick / install /
  uninstall / dist` in Cygwin, the installed symlinked tools run, the README's example commands work).
  Possible later: man pages (`bifin.1`, `bifout.1`; 3D has `bidet3d.1`), a `make install` check on a real Linux.

## Tests

```
./test.sh          # all four suites: test_bif (37), test_bifout (47), test_bifin (35), test_parity (5; ~5 min)
python tests/test_parity.py --report     # the whole parity table (1232 cases) and its distribution
```
All four suites pass on Windows Python 3.11 / numpy 2.2 / Pillow 11 and on WSL `Ubuntu-20.04` Python 3.8 /
numpy 1.17 / Pillow 7; the first three (119 tests, `make test-quick`) also on the user's Cygwin Python 3.12 /
numpy 2.5 / Pillow 12 (the parity gate was not run there). Python 3.7 / Pillow 5.4 / numpy 1.16 (the stated minimum) is **untested**. To run
the gate in WSL from the Bash tool use PowerShell (`wsl -d Ubuntu-20.04 -- bash -c "cd /mnt/d/... && python3
tests/test_parity.py"`): Git Bash rewrites `/mnt/...` paths. If a limit must be widened again, do it with a
measured number and a stated reason in `tolerance()`; do not hide a difference.

### What the parity limits mean (`tolerance()` in test_parity.py, set from the measured spread)

relative ink difference = sum|bifin - v3| / sum v3 coverage. block 0.05%; tone 0.6% (8-bit coverage);
line + raster letters 2% (Pillow 11 stays under 1%; Pillow 7 worst 1.6%), 8% when coloured (colour-run pieces are
painted source-over where v3 used max(); worst 5.9%); line + vector letters 20% (outlines vs FreeType's hinted
pixels; worst 17% = dense text forced into line mode). Canvas sizes may differ by 1 px (crop), compared aligned.
The gate renders with v3's own supersampling factor (v3 derives it from the uncropped canvas, a BIF only
knows the cropped one; the whole-pixel pen then rounds differently, about 10% of the ink on turkey at cell 24).

## Known gaps / ideas (roughly in order of value)

1. Tone mode is still a **raster** of recovered outlines (v3's DoG zero crossings) at the nominal resolution.
   Planned: trace the signed field to vector polylines (marching squares). Real algorithm work, not a port.
2. Hatching is a raster (`hatch_layer`); block pictures are rasters at the nominal resolution with smooth
   upscaling (better: dot resolution + `nearest`, crisp at any scale).
3. `vflag` (JOIN / CORNER) is not emitted by `bifin`, so a later smoothing op has nothing to go on.
4. Tool 2 `bifop`: pen weight, re-theme (palette roles already work in `bifout --ink/--paper`), crop, merge,
   smooth, warps (arc / squeeze / wave from bidet3d), extrusion as an op. Open: is bidet3d's 3D render a
   `bifop` (leaning yes) or an output backend?
5. Exporters: kitty / iTerm2 / SVG / ANSI / Tektronix / animation (frames); `height` and `cells` layers are not drawn.
6. SAUCE: only the fields are read; its aspect / font flags (80x50 art) are not used to set `unit_aspect` or `-a`.
   SAUCE is tested only with synthetic records (no ScreenTests file has one).
7. BIF spec open points (end of `BIF-SPEC.md`): curves, `same_as` between frames, fixed canvas units, PNG's
   four chunk-case bits.
8. v3 quirk kept on purpose (parity): a row of only dashes, or one `x`, is classed `tone` and draws nothing.
9. Reverse-video default colours in the `cells` layer are stored as an attribute bit only (lossy).

## Findings worth remembering

- v3 bugs found while porting (both fixed in v3 as the user approved, and in 4D): dangling SIXEL repeat
  count `!72$`; NUL byte in CP437 input -> `KeyError: 0`.
- Pillow's even-width pen is a sub-pixel off centre and a nominal 1-pixel pen draws about 0.75 px thick at
  ss=4 (v3 does the same; kept for parity).
- `bifrender` fills compound shapes (letters with holes) in a window around each shape; the first version
  allocated the whole text run per glyph and was 20x slower.
- Storing vertices as float32 flips a few boundary pixels vs v3 (0.2% on Pillow 7).

## Working here (gotchas)

- No git in the user's habit for edits: **copy a file to its directory's `BAK/` (`name.YYYYMMDD`) before editing
  an existing file** (new files exempt). `BAK/` is git-ignored.
- Git: use **Cygwin git** (`/d/cygwin/bin/bash -lc 'cd /home/chris/github/chrispollitt/CWPutils && git ...'`);
  never `git config a b`; commit only when asked, the user pushes, stage only the paths you touched.
  Tools that rewrite files (`sed -i`, the Edit/Write tools) can flip the executable bit: check
  `git show --summary` for `mode change` before leaving a commit.
- The Bash tool has no `python3`; use the Windows Python
  (`/c/Users/chris/AppData/Local/Programs/Python/Python311/python.exe`) or `wsl -d Ubuntu-20.04 -- python3`.
- Windows Write creates LF here, but heredocs in the Bash tool break on quotes and `sed` mangles backslashes:
  write files with the Write tool, patch with Edit (read the file first), use `sed` only for plain text.
- Don't copy third-party art (the user's ScreenTests folder, DOPEFISH.ANS ...) into the repo; test in place.
- Commit message trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
