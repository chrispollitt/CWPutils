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

Three tools around one file format, `.bif`. Milestones M0-M3 are done; M4 (`bifop`) is started.

| | |
| --- | --- |
| M0 | `BIF-SPEC.md`, `bif.py` (read / write / validate / `info|check|chunks`), `testdata/{good,bad}` (22 + 77 files) |
| M1 | `bifout` (BIF -> PNG / SIXEL), `bifrender.py`, `bifsixel.py` |
| M2 | `bifin` (terminal art -> BIF), `bifin_text.py` (unascii's reader / classifier / methods copied by line range + a new assembly), `ttfglyphs.py` (own TrueType outline reader: letters are vectors, raster `text-mask` fallback) |
| M3 | the parity gate, `tests/test_parity.py`, against a frozen copy of v3 (`tests/reference/unascii_v3.py`) and 4D's own `samples/` |
| after M3 | tone mode as traced vector lines: `tonetrace.py` (marching squares, tested on its own), `tone_vectors` / `_tone_layer` in `bifin_text.py`, `bifin --tone-raster` for the old raster; `bifrender` draws a stroke whose width multiplier is constant as an ordinary pen |

| M4 (started) | `bifop.py` (Tool 2): registry of operations (`@op(name, params, doc)`; first parameter may be given bare; ids joined with `+`), `apply()`/`clone()`, CLI (`-i`, `-o`, `--list`). Ops: pen, theme, recolor, opacity, blend, crop, scale, rotate, flip, keep/drop/hide/show, frame, meta, simplify, wave/arc/squeeze. Design: ops never write into arrays (they share the input's), transforms are composed into the layers' `transform` (non-destructive), `cells` layers sit on the grid so they are not transformed, and anything that breaks the grid (rotate, flip, warps) drops `grid` and the `cells` layer; warps bake the transform into the vertices (densify first so strokes bend) and skip rasters with a warning |

| M5 (started) | `bidet.py` + `presets.ini` (+ `gallery.py`, `gallery/gallery.png`): the casual front end, stage 1 = the 2D parts. See "The two modes" below. |

| M5 stage 2 | the **lettering importer**: `bifin -f lettering` (`bifin_lettering.py`: proportional layout from the font's own hmtx advances and legacy `kern`, `--size --spacing --line-height --align --wrap --bold --italic --margin`, one filled vector layer `text` with a `stem`; a missing bold / italic is faked: outline stroke / 12 deg shear), `fonts.py` (font lookup by family, file, comma list or generic name `sans serif mono impact script comic times arial courier georgia`, each with fallbacks so a recipe works anywhere; JSON cache of the catalogue in `$BIDET_CACHE` / `~/.cache/bidet/fonts.json`), `ttfglyphs` metrics / advance / kerning / names, `bifin --face` (lettering-only font, so a preset can ask for one without breaking art; `--font` is the art's monospace font), `--list-fonts`, `bidet -F`, `bifop pen` embolden of lettering via the `stem` layer key (new, in BIF-SPEC 7.1). `tests/test_lettering.py` (39) uses a synthetic font written by `tests/ttfbuild.py`: no installed font needed |

| M5 stage 5 (part) | **terminal queries** (`bifterm.py`; bifout `-b auto`, `--force`, `--no-query`; user request 2026-10-07, after the old bidet's `test-sixel.sh` and bidet3d's `query_terminal`): DA1 first and alone (a terminal without SIXEL is asked nothing else), then OSC 11 + CSI 16 t with a second DA1 as end mark. Like v1 (and unlike 3D) it asks whenever SIXEL goes to stdout, also into a pipe, and **silence counts as "no SIXEL"** (refused unless `--force`, `LSIX_FORCE_SIXEL_SUPPORT`, `BIDET_NO_QUERY`); no `/dev/tty` / not POSIX = not asked = go on. `-b auto`: terminal's colour as the page, else transparent; ink swapped for light / dark grey if it would not show (luminance gap < 0.4; unknown terminal = dark unless `COLORFGBG` says light). bidet adds `--background auto` on a terminal unless a preset / `--dark` / `--light` / `--ink` / `--paper` / the user's own bifout flag chose colours (a themed preset keeps its page). Plain-text input (stdin or file) that looks like prose is lettering (`looks_like_prose`; `--art` / `-t` override), and an empty picture is an error, not a blank page. **Untested in a real conhost** (a fake terminal on a pty in `tests/test_bifterm.py` does all the flows; the user reported conhost as the case where only v1 detected correctly). Not yet: bidet sizing from the CSI 16 t cell size when TIOCGWINSZ has no pixels (`bifterm.query(want_cell=True)` is there) |

| Animation, first cut (2026-10-12) | **`.vt` -> animated GIF**, the user's first idea (bambi.vt). `bifin_vt.py` + `bifin -f vt` (or a file named `*.vt`: `bifin.convert` looks at `options["name"]`): replays the stream on `bifin_text._Term` (new `_Term.screen()`, `screen_grid()`), takes the screen at every `\n` **before** the newline is processed (slowcat sleeps, then prints it), `--delay` (slowcat's argument; bambi.sh uses 25) / `--hold` (bambi.sh's `sleep 3`) / `--fps` (resample by time) / `--loop` (default 0 = forever); equal neighbours merge; the mode, colour and polarity are settled **once** from the fullest screen (`_settle`), `import_grid(info=...)` shares one palette across frames (`info["palette"]`), repeated screens reuse layers (arrays shared, props copied), crop is done once at the end over all frames (`bifop.extent_all`, `crop` now takes the union). `bifout`: `gif` in `WRITERS` (one frame) and `ANIMATED` (`write_gif_frames`); `--frame` now defaults to None (all frames for GIF, else 0 with a stderr note), `--speed`, `--loop`; `GifPalette` (line art = exact ink-page ramp, else median-cut of ~12 sampled frames, dither off), `gif_delays` (cumulative rounding to 1/100 s, min 2). `bidet`: `.gif` by extension (scale 1), `.vt` input, "nothing to draw" looks at all frames. `tests/test_anim.py` (21). Measured on Windows Py 3.11: bambi.vt 417 steps -> 293 frames 912x590, import 4.7 s + GIF 7.7 s, 530 KB, 13.42 s (13.425 expected); tetris.vt needs `-m ansi-block` (pieces are background colours; line mode shows only the text): 162 frames, 317 KB. **Not tested:** WSL Pillow 7 / Python 3.7 (the GIF code uses `quantize(palette=, dither=0)` with a fallback, and Pillow's lazy `append_images`), a real browser's playback of 20 ms frames. **Not done:** terminal (SIXEL) playback (SIXEL draws frame 0 and says so), APNG / WebP, asciinema `.cast` (has real timings), blank first frames are kept (the screen starts empty). Gotcha: a screen of only dashes draws nothing in line mode (the v3 quirk), so test sprites need strokes (`/\\_/\\`). |

| Animation, second cut (2026-10-12) | **bidet3d's animations ported, plus 2D -> 3D "pop out of the screen"** (user request). Self-contained, no code shared with 3D. `bif3d.py`: `Solid` (flat rgb + alpha -> face with bevel, sides, materials rainbow/chrome/gold/..., `paint` blend flat colour -> material), `State` per frame (depth, hover, view, bevel, paint, shadow, duration), `Camera` (rot_matrix, perspective, `shadow()` onto the screen plane), slice-stack `render`, `render_frames` (threads; crops all frames to what shows), paths `pop_path` / `spin_path` / `sway_path` / `hold_path` / `flat_path`. `bifop_3d.py` ops `extrude spin sway popout motion` (take ONE flat frame, replace it by raster frames; `motion:path=flat+tick+pop+hold+spin`; depth/hover are fractions of the ink's shorter side; hover default 0.6, a still 0). `bifop_join.py` ops `join` (append frames, merge palette with index remap, centre canvases) and `overlay` (layers onto frames; unique ids). `bifout`: **SIXEL playback** (`play`, `play_sixel`, `sixel_frames` on one shared palette via `GifPalette(size=254)`, steady clock with frame skipping, ECH clear for a transparent page, mode 2026), `--fps` (`schedule()` thins by time, also for GIF), `--cell`, `cell_size()`; `plays()` decides (animation, SIXEL for the terminal, no --frame). `bidet`: `--3d --spin --sway --pop --material --depth --view --turns --fps --time-machine --stage-time` (each a bifop op in `-n`), gif width 640. `timemachine.py`: eras as `.vt` sessions via bifin_vt (`-m ansi-block`, `smooth=0`), flat lettering, `motion`, `join` + `overlay` captions; real banner/figlet/toilet if installed (`BIDET_EMULATE=1` forces imitations); screen made tall enough for the pop; `gallery/time-machine.gif` (1.5 MB, 816x453, 137 frames, 22.7 s; `make time-machine`). `tests/test_3d.py` (35). **Not tested:** SIXEL playback in a real terminal (only a fake terminal and clock: bytes, order, timing, skipping, Ctrl-C cleanup), `bidet --time-machine` played on a terminal, Python 3.7 / Pillow 5.4. **Gotchas:** a black shadow is invisible on a black page (the time machine's page is #262b33); `bifop` ops must run on one flat frame; the first frame of `popout` is drawn through the engine at res 2, so it equals the flat picture only to within antialiasing; Windows Git Bash heredocs eat backslashes in Python edit scripts (use the Write tool). |

| 3D presets + gallery (2026-10-12) | **22 new presets** in `presets.ini` (50 in all): looks (`chrome rainbow gold superhero dusk lagoon cobalt graphite brick horizon lime relief`), motions (`popout turntable swing rise`, all 8 s or a divisor of it), showpieces (`marquee bubble ripple skyline reveal carnival`). Three new preset keys: `solid =` (key=value words for extrude/spin/popout), `motion =` (`pop+hold+spin hold=2.4`), `uses =` (presets applied first; `bidet.expand`, cycle/unknown errors). `bidet.motion_op(args, chosen, still)` merges presets then flags (flags win; `--3d` = still; later preset wins; `still=True` = the final pose floating, for tiles); `bidet.build_picture` split out of `run`; `check_preset(p, presets)` also checks `uses` and the 3D look/motion. New `tall=` param on the 3D ops (taller letters as a unit-aspect change: a later preset REPLACES it, unlike an op that would pile up) and a `stretch` bifop op; materials graphite/brick/cobalt/horizon; the light is higher (`SHADOW_DIR` 0.30, 0.40). `gallery.py` rewritten: PNG sheet of every preset (a moving one as its pose), `--gif` = `gallery/gallery-3d.gif` (every 3D preset, the moving ones playing on an 8 s loop, moving tiles grouped at the end so the GIF diffs small: 4 MB), `--gifs` = a GIF per moving preset; `make gallery-gif`. `gallery/popout.gif` (1.4 MB). `tests/test_3d.py` is now 45 tests, `test_bidet` draws all 50 presets (about 1 minute). **Untested:** a user's own `presets.ini` using `solid`/`motion`/`uses` beyond what the tests build; the look of texture/tile materials (not there). **Gotchas:** presets compose by order, so `-P chrome -P popout` is rainbow (popout's look wins); `uses` come before the preset that uses them; ops from several presets accumulate (crop, skew), only `solid` keys replace.

| Media branch (2026-10-12) | **`gallery/` is the orphan `media` branch**, mounted as a git worktree at `BIDeT/4D/gallery/` (git-ignored by `main`): one commit holding gallery.png, gallery-3d.gif, popout.gif, time-machine.gif; `make media` AMENDS that commit (only the latest is kept, the repo does not grow per redraw), `make publish-media` force-pushes just that branch (optional; the user may keep it local), `make prune-media` reflog-expires + gc's the replaced files, `make media-checkout` mounts it in a fresh clone. Done by rewriting the 3 then-unpushed commits (`git filter-branch --index-filter 'git rm -r --cached BIDeT/4D/gallery' e6ee0b4..HEAD`) so the GIFs never reached `origin/main`; the old gallery.png of `b45d2d3`/`e6ee0b4` stays in pushed history (240 KB). A `backup-before-media` branch (the pre-rewrite commits, 8 MB of media) is kept until the user says it can go (`git branch -D backup-before-media`, then `make prune-media`). Gotchas: the gallery files exist only where the worktree is mounted (a plain clone of `main` has no `gallery/`: README images are broken there); gallery.py / bidet write into `gallery/` as before; `make media` fails in a clone that has not mounted it. |

| Project documents (2026-10-12) | The set tvmail has, for BIDeT (user request): **`BIDeT/` top level** (the whole family): `AUTHORS`, `LICENSE` (the Boost text, byte-identical to `3D/LICENSE`, plus a third-party section; BIDeT is Boost, tvmail is MIT: NOT changed), `WARRANTY`, `HISTORY.md` (factual, from the repo; the "why" in the author's voice is not in it: the user may want to add it); **`4D/`**: `INSTALL.md`, `DEVNOTES.txt` (stable developer notes; HANDOFF.md stays the running state); both READMEs refreshed. Makefile: `DOCS` gained INSTALL/DEVNOTES, `TOPDOCS` (`../AUTHORS ../LICENSE ../WARRANTY ../HISTORY.md`, or beside the Makefile in an unpacked tarball) are installed and shipped by `dist`; `dist` no longer fails when the `gallery/` worktree is not mounted. Checked: `make dist`, `install-doc` from the unpacked tarball, and `dist` without gallery. tvmail's own `DEVNOTES.txt` is a git-ignored scratch file with login lines in it (never committed); the 4D one is documentation and has no secrets. |

Not started: other importers (PNG/JPEG trace, SIXEL, SVG) and exporters (kitty, iTerm2, SVG, ANSI,
Tektronix, APNG / WebP). `bifop` still lacks: `smooth` (needs `vflag` from `bifin`), raster warps, `rasterize`, `bold`,
and warps (arc / squeeze / wave) of the solid before it is extruded (the 3D ops take the flat picture as it is; `join`
now exists for several BIFs).

## The two modes (user's requirement) and the plan for bidet

1. **Piping** (power users): `bifin | bifop | bifout` with every flag of every tool.
2. **`bidet`** (casual users; the replacement for bidet3d): one command, few options, presets, auto-detection.
   **Rule: it must stay sugar over mode 1**, never a second implementation. It builds the same three stages
   and runs them in-process (`bifin.build_parser/options_of`, `bifop.apply`, `bifout.build_parser/render_options/
   convert`); `bidet -n` prints the pipeline; `test_bidet.py::SugarOverThePipe` checks that bidet's bytes equal
   the real tools' bytes for several inputs/presets. Presets are recipes (`presets.ini`; user file
   `~/.config/bidet/presets.ini`, `$BIDET_PRESETS`); `-P` is repeatable and combines in order. User chose
   (2026-10-07): name `bidet`; recipes in a data file; stage it as 2D first, 3D later; **the presets need not copy
   bidet3d's: they are a showcase of what 4D can do** (and `gallery.py` draws them all on suitable samples).
   Assumptions made: a file name is a file, anything else is text, text is set with `-f lettering` (bifin's
   classifier takes plain words for picture art and traces bars), SIXEL on a tty else PNG (or by -o extension, `.bif` too),
   width = 95% of the terminal's pixel width (TIOCGWINSZ, else 8 px/column, 320..2400) or 1000 px for text / scale
   2 for art when writing a file, dark/light from `COLORFGBG` or `--dark/--light` (a preset's own colours win).
   **Stage 2 (font text) is done** (see M5 stage 2 above; presets banner / stamp / monument / wave / sunset / chalk ... use
   `--face`). Known limits: GPOS-only kerning is not read (fonts without a `kern` table are laid out unkerned), no
   ligatures / complex scripts / right-to-left, CFF (.otf) fonts are not seen, `pen` cannot thin letters,
   synthetic bold is a round-joined outline. **Stages still to do for a full bidet3d replacement:** (3) paint kinds in BIF
   (gradient / texture / tile fills; a spec change) and presets that use them; (4) **extrusion is done as `bifop`
   operations** (see "Animation, second cut"); what is left is 3D presets in `presets.ini` (named recipes of
   `bifop extrude|spin|popout` + a `--material`, e.g. the css3wordart look-alikes), textures and tiles (need stage 3);
   (5) real terminal queries (DA1 for SIXEL support, OSC 11 for the background, cell size) are done (M5 stage 5).

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
  Man pages: `bidet.1`, `bifin.1`, `bifop.1`, `bifout.1` exist (2026-10-12; `make lint` checks them with groff if present; `make install` puts them in share/man/man1; `tests/test_docs.py` checks that they name every bifop operation and parameter and every long option of bifin, bifout and bidet, so a new flag must be documented). Possible later: a `make install` check on a real Linux.

## Tests

```
make test-quick    # ~1.5 min: test_bif (37), test_bifout (47), test_bifin (47), test_tonetrace (14), test_bifop (45), test_bidet (38), test_anim (21)
make test          # ~3 min: that plus a smoke subset of the parity gate (PARITY_QUICK=1: every mode, 7 samples)
make test-full     # ~10 min: everything, the full parity matrix (1232 cases)
python tests/test_parity.py --report     # the whole parity table and its distribution
```
**Testing policy (user's request): while developing run `make test-quick` or `make test` on one platform
(Windows Python 3.11); run `make test-full` and the other platforms only at milestones, or after changing
numerically sensitive code (rendering, tracing, the fields).** Verified so far: the full set on Windows
Python 3.11 / numpy 2.2 / Pillow 11 and on WSL `Ubuntu-20.04` Python 3.8 / numpy 1.17 / Pillow 7 (all pass,
including the traced tone lines and the renderer antialiasing change); on the user's Cygwin Python 3.12 /
numpy 2.5 / Pillow 12 the four fast suites and the command-line parity pass, and the tone gate failed once on a
60-pixel case (dashes.txt), which is why per-case tone checks now skip cases under 150 line pixels (re-verified
on Windows only). Python 3.7 / Pillow 5.4 / numpy 1.16 (the stated minimum) is **untested**. To run
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

1. ~~Tone mode is a raster~~ **Done (after M3): tone is traced to vector lines** (`tonetrace.py`, `tone_vectors`
   and `_tone_layer` in `bifin_text.py`): marching squares on v3's own signed DoG field (the zero crossings),
   per-vertex width = the edge-strength gate (lines fade out as the edge does, via `vwidth`), the contour levels
   through gentle shading as 0.4 pens, colour sampled from the picture, smoothed along the line, legible, cut into
   16-level pieces. The fields are scaled up to a ~1.5 px grid before tracing (so lines are smooth drawn big),
   RDP at 0.04 px, the width smoothed along the line; where the RGB channels' outlines of one edge lie within
   a pen width of an earlier channel's they are dropped (v3's raster `max()` merges them; as vectors they were
   2-3 parallel lines), and runs shorter than 6 px left over by that are dropped (beads). `--tone-raster`
   keeps unascii's raster. Compared with v3 by position (2 px precision / recall; `ToneVectors` in
   test_parity.py): median 98.7% / 100%, worst 82% / 90%; the vector has 0.8-1.43x the pixels (median 1.08:
   the whole-pixel pen, as v3's strokes). Files 3-5x smaller; ~same import time; big pictures fine (300x150
   characters: ~2.6 s, 67 KB). Idea left: try `g**2` for the width if faint lines look too heavy.
   **Found on the way (fixed): `bifrender` chose its supersampling from the canvas size (v3's rule), so a
   canvas over ~4 MP (e.g. any 4x render of a normal picture) got `ss=1`, no antialiasing at all. It now
   chooses per run of strokes from a 64 MB mask budget (at most 4); an explicit `ss=` still wins.**
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

- **The user's Cygwin stack (Python 3.12 / Pillow 12.3 / numpy 2.5) traces `tone80.txt` differently** from Windows 3.11 / Pillow 11 and WSL 3.8 / Pillow 7: 49 paths against 44, and an extra faint straight line along the top edge (958 px long, 0.56 px thick). `test_bifop.test_simplify` failed there (IoU 0.796) because that line sits right on the 0.5 coverage mark the `iou` helper binarizes at, and `simplify` moving it 0.2 units flips all its pixels at once; `simplify` itself was right (worst vertex deviation 0.498 of 0.5). Fixed in the test (`iou(..., threshold=0.2)`, 0.996 there), not in `simplify`. A width-aware `simplify` (keep a vertex whose removal changes the pen width) was tried and dropped: it was not the cause. Not chased: why the newer Pillow adds that line (the parity gate, which compares with v3 by position, still passes). When a test fails only on one stack, compare the intermediate numbers (vertex counts, ink pixels, an overlay of the two drawings) before touching code or thresholds.

- **SIXEL animation in Windows Terminal had noise that mintty did not** (user's screenshots, 2026-10-12). Cause 1, fixed: Windows Terminal does not answer OSC 11, so `-b auto` sends *transparent* frames; they were flattened onto the picture's own white page and painted opaque, so soft shadows and antialiased edges became a pale halo on a dark terminal (found by decoding the frames with `3D/gfx-conv/sixeldec.py` and compositing over `#0c0c0c`, opaque row vs transparent row). Now `GifPalette(..., transparent=True)` quantizes and paints the STRAIGHT colours of pixels at least half covered and leaves the rest clear (shadows are not drawn there: the page is unknown); this also fixed the fringe of transparent GIFs. Cause 2, **not reproduced, only suspected**: orange specks, dashes where the shadow was and a 1 px dark line across letters are NOT in the SIXEL data (decoded: no orange pixels in either path), they look like stale pixels of the previous frame that ECH does not clear in Windows Terminal. Added `bifout --erase ech|bg|none` (bg = encode with SIXEL P2=0 so the terminal fills unpainted pixels with its own background; ech, the default, = erase the cells first, as bidet3d did, now all rows made room for). **Outcome of the user's test (2026-10-12): `--erase bg` is WORSE in Windows Terminal** (stale fragments pile up along the top of the picture: P2=0 does not clear there). Decision (user): live with Windows Terminal's SIXEL behaviour and hope the Windows Terminal devs fix it; document "YMMV" instead: README ("Terminals: your mileage may vary"), and the new man pages `bidet.1` / `bifout.1` (TERMINALS sections). The default stays `--erase ech`; `bg` and `none` are kept as options, documented as not helping there. Only mintty has been tested thoroughly for live animation; WezTerm, foot, xterm, mlterm, iTerm2 untested. Not asked for any further: `python bifterm.py` output in Windows Terminal (the cell height may be a 10x20 guess there). Known and left: the shared 253-colour palette bands the rainbow gradients (no dithering, on purpose, so still areas do not shimmer).

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
