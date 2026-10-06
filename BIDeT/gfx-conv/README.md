# gfx-conv

Converters from SIXEL (what BIDeT3D writes) to other terminal graphics standards, so the same
picture can be shown on terminals that don't do SIXEL. Python 3, standard library only (Pillow
is needed only if you feed them something that is neither SIXEL nor PNG; `sixel2ans.py` also uses numpy when present). They also take PNG,
JPEG and so on directly, so they work as small `imgcat`s.

| tool | protocol | terminals that understand it |
| --- | --- | --- |
| `sixel2kitty.py` | [kitty graphics protocol](https://sw.kovidgoyal.net/kitty/graphics-protocol/) (APC `_G`) | kitty, WezTerm, Ghostty, and some others |
| `sixel2iterm.py` | [iTerm2 inline images](https://iterm2.com/documentation-images.html) (OSC 1337) | iTerm2, WezTerm, mintty, and some others |
| `sixel2ans.py` | coloured Unicode text ("ANSI art"): block, quadrant, eighth and Braille characters, 24/256/16 colours | any terminal with UTF-8; 24-bit colour in most modern ones |
| `sixel2tek.py` | Tektronix 4010/4014 vector graphics | xterm in Tek mode (`xterm -t`), and real Tektronix terminals and emulators |

SIXEL itself is the oldest of these and the one most terminals share; the other two are the
common modern ones. Which terminals support what changes from release to release, so check
your terminal's own documentation.

    bidet3d --transparent --force "Hello" | sixel2iterm.py
    bidet3d --transparent --force "Hello" | sixel2kitty.py -c 40
    bidet3d --transparent --force "Hello" | sixel2tek.py --xterm -m contour
    sixel2iterm.py photo.jpg

Transparent backgrounds stay transparent in the kitty and iTerm2 output. `bidet3d` writes a
transparent SIXEL when the terminal can't report its background colour; use `--transparent`
to ask for one when piping.

## sixel2ans

The successor to `img2ans`, which BIDeT v1 used when the terminal had no SIXEL. That was
csdvrx and Justine Tunney's *derasterize* (ISC licence; still in [`../v1/`](../v1/)). Same idea:
each character cell is an 8x8 patch of the picture, and the block character plus the two colours that fit
that patch best are chosen. What's different:

* Python, no compiler, no ImageMagick, no AVX2. Uses numpy if present (about 0.5 s for a
  70-column picture); without it the same result comes out of plain Python, slower.
* Reads SIXEL (so `bidet3d | sixel2ans` works) as well as PNG/JPEG.
* Transparency is kept: transparent areas show the terminal's own background (`-b COLOR`
  fills them instead, like img2ans's `-b`).
* `-C 24|256|16` colour depth, `-g half|quad|blocks|braille` glyph set, `-x/-y` size (negative =
  that much less than the terminal), `-a` for unusual cell shapes. The aspect ratio is kept.

    bidet3d --transparent --force "Hello" | sixel2ans
    sixel2ans -g braille -C 256 photo.jpg > photo.ans && cat photo.ans

## sixel2tek

SIXEL is raster and Tektronix is vector, so the picture is vectorised. Bright means ink:

| mode (`-m`) | what it draws | pictures |
| --- | --- | --- |
| `hatch` (default) | horizontal scan lines, denser where the picture is brighter | [tek-hatch.png](tek-hatch.png) |
| `dots` | point-plot mode, Floyd-Steinberg dithered | [tek-dots.png](tek-dots.png) |
| `contour` | outline of the lit area plus brightness iso-lines (marching squares) | [tek-contour.png](tek-contour.png) |

`--xterm` switches xterm into Tek mode (`ESC [ ? 38 h`), draws, waits for Enter and switches
back (`ESC ETX`); going back hides the Tek window. Without it the output is a plain Tek
stream you can `cat` into a Tek-mode xterm. Windows Terminal and mintty have no Tek mode; use
xterm (Cygwin/X or Linux). Everything is drawn at 1024x780, the 4010's addressing.
`-i` inverts, `-g` sets gamma, `--levels` and `--simplify` tune `contour`, `--pitch` and `-l`
tune `hatch`.

## Notes from testing

* WezTerm on Windows passes the **iTerm2** protocol through ConPTY but not the **kitty**
  one: `sixel2kitty.py | type`-style output run directly in WezTerm shows nothing, while the same
  bytes sent over ssh (`wezterm ssh host -- cat file`) draw fine. This is ConPTY dropping APC
  sequences, not the converter. Use the iTerm2 protocol for native Windows programs there, or
  go through ssh/WSL2.
* kitty graphics inside tmux or screen needs the multiplexer's passthrough enabled.

## Files

`sixeldec.py` (SIXEL decoder and PNG writer, shared), the three converters, and `test.sh`
(`./test.sh`: decodes a generated picture and checks every converter's framing; it can't see
whether a terminal draws the result).

Same license as BIDeT3D: Boost Software License 1.0 (see [`../3D/LICENSE`](../3D/LICENSE)).
