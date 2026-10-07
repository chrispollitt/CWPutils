# unascii

ASCII art's job is to take a picture and turn it into printable characters.
`unascii` goes the other way: it takes terminal art (ASCII, ANSI colour, Unicode
blocks and braille) and redraws it as a clean PNG, or as SIXEL for the terminal.
It has two modes, and picks one by looking at what the art is made of:

- **lineart** for cowsay, figlet and other line drawings (and, by outlining the picture,
  for jp2a-style character-ramp art): a line drawing.
- **ansi-block** for art built from blocks and graphic characters (DOS `.ANS`, chafa,
  braille): the coloured picture it is, crisp, with exact blocks and the original colours.

```
cowsay -f turkey "gobble" | unascii            # in a SIXEL terminal: shows it
unascii art.txt -o art.png                     # PNG, black on white
unascii fish.ans                               # block art: the picture itself, in colour
unascii -m lineart fish.ans                    # ...or outlines of it instead
cowsay hi | unascii -o - | bidet3d             # ...and into BIDeT3D (see below)
```

![before and after: cowthink -f turkey through bidet3d](examples/turkey-3d-compare.png)

Left: bidet3d's art mode as it was (the glyphs extruded). Right: the same art redrawn by unascii first.
`examples/` also has the flat line drawing (`turkey-lineart.png`).
The colour examples (`ghostbusters-colour.png`, `dragon-colour.png`) are `cowsay | lolcat -f | unascii`.
`block-photo-ansi-block.png` is `unascii samples/blocks_color.ans` (chafa half-block art in ansi-block
mode: the picture itself) and `ansi-blocks-lineart.png` is `unascii -m lineart` on the same file (outlines of it).

## How it works

`-m auto` (the default) looks at which characters are used (`-v` shows the numbers).
`-m lineart` or `-m ansi-block` forces the family; inside lineart, `-m line`, `tone` or
`mix` force a method:

| mode | for | how |
|------|-----|-----|
| `ansi-block` | art made of blocks and graphic characters: DOS `.ANS`, chafa half blocks `▀▄`, `░▒▓`, braille, coloured backgrounds | The picture as a terminal would show it, with exact cell sizes: each cell is its background colour with the glyph in its foreground colour on top. Blocks and braille are exact rectangles, shade characters blend their two colours, other characters are font glyphs. Colour art is drawn the way a terminal shows it: on black, with light-grey default text; DOS `.ANS` art (CP437) gets the VGA palette, so light red is coral as in DOSBox. Uncoloured art (braille) is dark on white; `--ink white --paper black` for light dots on dark. The pixels are very lightly softened (`--smooth 0.12`; 0 = crisp). Art meant for another cell shape needs `-a`: 80x50 art such as `ansilove.ans` wants `-a 1`. |
| `line` | hand-drawn art: cowsay, figlet, boxes, `/ \ \| _ - ( ) ^ ' . ,` | Each character is a pen stroke. Stroke ends that meet are **joined into continuous lines** and gentle corners are rounded, so `_.-'''-._` becomes one smooth curve instead of a row of marks. `o` `O` `0` are rings, `^` `<` `>` are chevrons, box-drawing characters (light, heavy, double, rounded) are drawn exactly. Letters in words stay letters (`Moo` is text, `(oo)` is eyes). Joined strokes are **spline-smoothed**: staircases of `_` and `/` become diagonals and waves, while real corners (`^`, `<`, `|_`) stay sharp. cowsay **speech bubbles are closed** at the bottom. Runs of `X` (the filled regions of cowsay's ghostbusters) become **diagonal hatching**. |
| `tone` | picture-converted art: jp2a, chafa, caca, `.:-=+*#%@` ramps, half blocks `▀▄`, braille, coloured ANSI | The characters are ink density. The halftone is undone (averaged per dot: a cell, half a cell, a braille dot), the picture they were squinted from is rebuilt, and **outlines are traced at sub-pixel accuracy** (zero crossings of a difference of Gaussians). Gentle shading gets a few contour lines. Coloured art is outlined per colour channel, so an edge between two hues of the same brightness still gets a line. |
| `mix` | line art with dense fills (`#`, `@`, `█`) | strokes for the line characters, outlines for the fills |

Input can be plain text, UTF-8 or CP437 `.ANS` files (SAUCE records are dropped; the codes
below 32 are pictures there, `♥`, `►`). It is replayed on a small terminal emulator, not just read:
SGR colours (16, 256, truecolor), cursor addressing clamped to the screen (`--rows`, default 24),
scroll regions, erase / insert / delete, save and restore cursor, reverse index, the DEC
line-drawing set (`ESC ( 0`), OSC and other strings skipped, wrap at `--cols` (80 for `.ans`).
A long picture scrolls into history and all of it is kept. For a screen dump or animation
(`.vt` files) you get the final screen.

**Colour is kept.** If the art has ANSI colours, the lines come out in them: in `line` mode
every stroke, letter and hatched region takes its character's colour (a curve that wanders into
a blank cell keeps the colour it had); in `tone` mode a line takes the colour of the picture
it outlines, weighted to the colourful side of an edge so a coloured shape keeps its colour
against a dark ground. Colours are made legible on the page: greys and whites (which in a terminal just
mean "the text colour") become the ink colour, and colours too bright for a light page are darkened
(yellow becomes olive), or too dark for a dark page (`--paper black`) lightened. `--mono` turns it off.
`rainbow | unascii` works: `cowsay hi | lolcat -f | unascii -o rainbow.png`.

## Options

```
unascii [FILE|-] [-o FILE.png | -o - | -s] [options]

-o, --output FILE    write a PNG ('-' = stdout).  Default: SIXEL if stdout is a
                     terminal, else a PNG on stdout
-s, --sixel          print SIXEL to stdout
-m, --mode MODE      auto (default), lineart, ansi-block, or one lineart method: line, tone, mix
-c, --cell PX        width of one character cell in the output (default 12)
-a, --aspect R       cell height / width (default 2.0)
-w, --weight W       pen thickness (default 1; bidet3d wants 2-3)
-j, --join CELLS     line: join stroke ends up to this far apart (default 1, 0 = never)
    --no-round       line: no smoothing, keep every corner sharp
    --spline F       line: spline smoothing of joined strokes, in cell widths (default 0.6;
                     0 = only round the corners)
    --shade CHARS    line: runs of these characters are shading and get hatched (default X, '' = none)
    --hatch F        line: spacing of that hatching (default 1)
    --text-bold F    line: how much letters thicken when -w is above 1.2 (default 0.25; 0 = never)
    --smooth F       tone: blur in dot pitches (default 0.7); more = smoother contours.
                     ansi-block: softening of the pixels (default 0.12, 0 = crisp)
    --detail F       tone: smallest tonal step that gets an outline (default 0.12)
    --scale F        tone: finest outline feature (default 0.4)
    --levels N       tone: contour lines through shading (default 3, 0 = outlines only)
    --invert         tone: outline the negative (try it if the lines trace the wrong thing)
    --dark           tone: default colours are light on dark (automatic when the art uses colour)
    --color MODE     auto (default: keep the ANSI colours if the art has any), on, off; --mono = off
    --ink, --paper   the line colour and the page (default black on white; for colour block art light
                     grey on black, as a terminal shows it). Greys and whites in line art become --ink,
                     other colours are made legible on --paper; --transparent for a transparent page
    --rows N         screen height for cursor addressing and scroll regions (default 24)
    --width PX       scale the result to this width
    --font FILE      monospace font for letters (default: DejaVu Sans Mono, Consolas, ...)
    --encoding ENC   input encoding (default UTF-8, else CP437)
-v                   say what was chosen and why
```

## With BIDeT3D

`bidet3d` has it built in: whenever it is in art mode (`-a`, or a piped
multi-line picture that it detects as ASCII art) it redraws the art with unascii
before extruding it, so the lines are continuous instead of rows of separate
glyphs. `--no-lineart` turns that off, `--lineart MODE` forces a mode, `--pen`
sets the thickness.

As a pipeline, anything that writes a PNG (or JPEG/GIF) to bidet3d's stdin is
extruded as a shape, so you can tune the drawing first:

```
fortune -s | cowthink -f turkey | unascii -w 2.5 -o - | bidet3d -P rainbow
unascii photo-art.txt -m tone -w 3 -o - | bidet3d -P chrome
```

bidet3d looks for `unascii.py` in `$BIDET3D_UNASCII`, `unascii/` next to a
source checkout, and where `make install` puts it (`share/BIDeT3D/unascii`).

## As a library

```python
import unascii
ink = unascii.render(text, mode="auto", cell_w=16, weight=1.5)   # float array, 1 = ink
img = unascii.mask(text, 16, 32)                                  # PIL 'L', 255 = ink
png = unascii.to_image(ink, fg=(0, 0, 0), bg=(255, 255, 255))     # PIL RGB
sx  = unascii.sixel(ink)                                          # bytes

ink, rgb = unascii.render_color(text)      # rgb: uint8 colour of each line pixel, or None if the art has none
png = unascii.to_image(ink, rgb=rgb)       # coloured lines on white
sx  = unascii.sixel(ink, rgb=rgb)          # up to 24 colours x 6 shades; the paper stays exact
```

## Requirements and limits

Python 3.7+, Pillow 5.4+, numpy 1.16+; nothing else (no scipy or OpenCV), so it
runs on the same old systems as BIDeT3D. Tested with Python 3.11 / Pillow 11 /
numpy 2.2 and Python 3.8 / Pillow 7.0 / numpy 1.17. SIXEL output was checked by
decoding it with libsixel's `sixel2png`.

- Tone mode cannot know which way round the picture was meant: dense characters
  are taken as dark ink (the print convention). jp2a without `--invert` is the other
  way round; add `--invert` to unascii for those.
- `line` reads each character on its own, so unusual art styles (letters used as
  shading, `#` mazes) come out as the font glyphs, not as strokes.
- Wide (CJK) characters are treated as one cell.

Boost Software License 1.0, like BIDeT (see `../LICENSE`).
